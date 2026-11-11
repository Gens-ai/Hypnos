"""Pomodoro, minus the alarm: offer a rest at a boundary, never mid-thought.

Keeps the rhythm of the technique -- a block of attention, a short rest,
every fourth rest a longer one -- and drops the ring. Kairos has no timer
thread; it is evaluated when the user speaks, so the only moment it can
ever speak is right after someone has finished composing a message. It
waits for that moment to also be a boundary in the work, and gives up
gracefully when ignored.

Same contract as the wind-down and the break moment:

  * It measures the work, never the person. Focus is unobservable; tool
    outcomes, timestamps and how the last turn ended are not.
  * Only the user's own actions touch the clock (a message, a stop). Agent
    tool calls are evidence of nothing about whether anyone is watching.
  * It offers, it does not instruct. The agent keeps working; the user is
    the one who may step away.
  * Three ignored offers and it goes quiet until a rest is observed.

The functions down to ``render`` are pure. The storage-backed wrapper at the
bottom is what the hooks call.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

# --- the shape of the technique. Constants, not settings: see the README.
BLOCKS_PER_CYCLE = 4
LONG_REST_MIN = 20       # a rest this long also resets the four-block cycle
TIGHT_LOOP_SEC = 60      # reply this soon after handback = mid-flight
MAX_IGNORED = 3          # the same ceiling as the wind-down's MAX_REPEATS
PAUSE_LIFTS_AFTER_H = 5  # "not today" ends after an absence long enough to be sleep

# setting -> (min, max, default). Mirrored by the settings routes and UI.
RANGES = {
    "work_min": (15, 120, 25),
    "break_min": (3, 15, 5),
    "away_min": (3, 30, 8),
}

# key -> type. One row per key in the pomodoro_state table, stored as text.
_FIELDS: dict[str, type] = {
    "stretch_start": float,      # when the current unbroken stretch began
    "last_human_at": float,      # last action BY THE USER -- never a tool call
    "blocks_done": int,          # offers since the last long rest (0..3)
    "ignored_streak": int,       # consecutive offers with no rest after them
    "paused": int,               # "not today": lifted by a long absence
    "paused_until": float,       # ...or by this, a hard 24h backstop
    "pending_since": float,      # due but held for a boundary since
    "last_turn_ended": float,    # when the agent last handed back
    "last_turn_ok": bool,        # that turn completed, not stopped or failed
    "last_turn_calls": int,      # tool calls in that turn
    "last_turn_min": int,        # how long that turn ran
    "last_reset_reason": str,    # "away 11m" | "idle 6m" | "rest declared" | "offer"
    "resets_night": str,         # the night resets_today belongs to
    "resets_today": int,         # rests observed tonight
}


def blank_state() -> dict[str, Any]:
    s: dict[str, Any] = {k: t() for k, t in _FIELDS.items()}
    s["last_turn_ok"] = True
    return s


def parse_state(raw: dict[str, str]) -> dict[str, Any]:
    """Text rows from storage -> typed state. Unknown or broken values fall back."""
    s = blank_state()
    for k, t in _FIELDS.items():
        if k not in raw:
            continue
        v = raw[k]
        try:
            if t is bool:
                s[k] = str(v).lower() in ("1", "true")
            elif t is int:
                s[k] = int(float(v))
            elif t is float:
                s[k] = float(v)
            else:
                s[k] = str(v)
        except (TypeError, ValueError):
            pass
    return s


def dump_state(state: dict[str, Any]) -> dict[str, str]:
    out = {}
    for k, t in _FIELDS.items():
        v = state.get(k, blank_state()[k])
        out[k] = ("1" if v else "0") if t is bool else str(v)
    return out


def config(goals: dict[str, Any]) -> dict[str, Any]:
    """The pomodoro settings out of the goals table, clamped to their ranges."""

    def _num(key: str) -> int:
        lo, hi, default = RANGES[key]
        try:
            v = int(float(goals.get(f"pomodoro_{key}", default)))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    try:
        patience = max(0, int(goals.get("clean_break_patience_min") or 20))
    except (TypeError, ValueError):
        patience = 20
    return {
        "enabled": str(goals.get("pomodoro_enabled", "false")).lower() == "true",
        "work_min": _num("work_min"),
        "break_min": _num("break_min"),
        "away_min": _num("away_min"),
        "tone": goals.get("tone") or "encouraging",
        "prefer_clean": str(goals.get("prefer_clean_break", "true")).lower() == "true",
        "patience_min": patience,
    }


# ------------------------------------------------------------ stretch clock


def _rest(state: dict[str, Any], now: float, length_sec: float, reason: str,
          night: Optional[str]) -> None:
    """A rest happened: start a fresh stretch. Mutates ``state``."""
    state["stretch_start"] = now
    state["ignored_streak"] = 0
    state["pending_since"] = 0.0
    state["last_reset_reason"] = reason
    if length_sec >= LONG_REST_MIN * 60:
        state["blocks_done"] = 0
    if night is not None:
        if state.get("resets_night") != night:
            state["resets_night"], state["resets_today"] = night, 0
        state["resets_today"] = int(state.get("resets_today") or 0) + 1


def touch(state: dict[str, Any], cfg: dict[str, Any], now: float,
          night: Optional[str] = None) -> dict[str, Any]:
    """Record a human action at ``now``, inferring a rest from the silence before it.

    Two silences count as a rest:

      away  -- nothing from you for away_min, whatever the agent was doing
      idle  -- the agent had handed back, then nothing at all for break_min

    Pass ``night`` to keep the per-night rest count.
    """
    s = dict(state)
    last = float(s.get("last_human_at") or 0.0)
    ended = float(s.get("last_turn_ended") or 0.0)

    if not s.get("stretch_start") or not last:
        s["stretch_start"] = now
    else:
        away = now - last
        idle = (now - ended) if ended >= last else 0.0
        if s.get("paused") and (
            away >= PAUSE_LIFTS_AFTER_H * 3600
            or 0 < float(s.get("paused_until") or 0.0) <= now
        ):
            s["paused"] = 0
        if away >= cfg["away_min"] * 60:
            _rest(s, now, away, f"away {int(away // 60)}m", night)
        elif idle >= cfg["break_min"] * 60:
            _rest(s, now, idle, f"idle {int(idle // 60)}m", night)

    s["last_human_at"] = now
    return s


def stretch_min(state: dict[str, Any], now: float) -> int:
    start = float(state.get("stretch_start") or 0.0)
    return int((now - start) // 60) if start else 0


# ------------------------------------------------------------ boundary facts


def boundary_state(recent: list[dict[str, Any]], state: dict[str, Any],
                   now: float) -> dict[str, Any]:
    """Is the work at a boundary? Facts only, like winddown.stop_state.

    ``idle_since_handback_sec`` is measured from when the agent last handed
    back, not from your last message -- otherwise a 3-minute run answered the
    instant it finished would pass for a thoughtful pause.
    """
    from . import winddown as _winddown  # noqa: PLC0415

    stop = _winddown.stop_state(recent or [])
    ended = float(state.get("last_turn_ended") or 0.0)
    idle = (now - ended) if ended else None
    tight = idle is not None and idle < TIGHT_LOOP_SEC
    ok = bool(state.get("last_turn_ok", True))
    return {
        "clean": stop["clean"],
        "observed": stop["observed"],
        "recent_errors": stop["recent_errors"],
        "last_turn_ok": ok,
        "idle_since_handback_sec": None if idle is None else int(idle),
        "tight_loop": tight,
        "last_turn_calls": int(state.get("last_turn_calls") or 0),
        "last_turn_min": int(state.get("last_turn_min") or 0),
        "at_boundary": stop["clean"] and ok and not tight,
    }


# ------------------------------------------------------------------- gates


def should_suggest_pomodoro(
    now: float,
    state: dict[str, Any],
    recent: list[dict[str, Any]],
    cfg: dict[str, Any],
    snoozed: bool = False,
    bedtime_delta: Optional[int] = None,
    last_break_at: Optional[float] = None,
) -> dict[str, Any]:
    """Decide whether to offer a rest right now. Pure: everything is passed in.

    Always returns a dict. ``speak`` False carries ``why`` (and ``hold`` when
    the offer is due but waiting for a boundary, so the caller can start the
    patience clock). Gates, most absolute first:

      1. disabled, or tone off                -> silent
      2. "not tonight" (the wind-down snooze) -> silent
      3. "not today"                          -> silent
      4. inside the bedtime band              -> silent, the wind-down owns it
      5. block not up yet                     -> silent
      6. three offers ignored                 -> silent until a rest
      7. a break offer inside this block      -> silent, that was the offer
      8. not at a boundary                    -> hold, up to the patience
         window; never at 'gentle'
    """
    from . import moments as _moments  # noqa: PLC0415
    from . import winddown as _winddown  # noqa: PLC0415

    def quiet(why: str, **kw: Any) -> dict[str, Any]:
        return {"speak": False, "why": why, "hold": False, **kw}

    if not cfg.get("enabled"):
        return quiet("Pomodoro is off in settings.")
    tone = cfg.get("tone") or "encouraging"
    if tone == "off":
        return quiet("Tone is 'off' — measurement only.")
    if snoozed:
        return quiet("Snoozed for tonight ('not tonight').")
    if state.get("paused"):
        return quiet(f"Paused ('not today') until you've been away "
                     f"{PAUSE_LIFTS_AFTER_H} hours.")
    if bedtime_delta is not None and (
        -_moments.BEDTIME_PRIORITY_MIN <= bedtime_delta <= _winddown.PAST_LIMIT_MIN
    ):
        return quiet("Close to your bedtime target — the wind-down has this hour.")

    mins = stretch_min(state, now)
    work = cfg["work_min"]
    if mins < work:
        return quiet(f"{mins} of {work} min into this block.", not_due=True)

    ignored = int(state.get("ignored_streak") or 0)
    if ignored >= MAX_IGNORED:
        return quiet(f"{ignored} offers in a row went untaken; quiet until a rest.")

    if last_break_at is not None and now - last_break_at < work * 60:
        return quiet("A break was offered inside this block already.")

    b = boundary_state(recent, state, now)
    waited = 0
    if not b["at_boundary"]:
        since = float(state.get("pending_since") or 0.0)
        if tone in _winddown.CLEAN_ONLY:
            return quiet("Due, but 'gentle' only speaks at a clean spot.", hold=True,
                         boundary=b)
        if cfg.get("prefer_clean", True):
            waited = int((now - since) // 60) if since else 0
            if not since or waited < cfg["patience_min"]:
                return quiet(
                    f"Due; holding for a clean spot ({waited} of "
                    f"{cfg['patience_min']} min patience).",
                    hold=True, boundary=b,
                )

    block = int(state.get("blocks_done") or 0) % BLOCKS_PER_CYCLE + 1
    long_rest = block == BLOCKS_PER_CYCLE
    return {
        "speak": True,
        "why": "",
        "hold": False,
        "block": block,
        "long_rest": long_rest,
        "next_blocks_done": 0 if long_rest else block,
        "repeat": ignored,
        "stretch_min": mins,
        "clean": b["at_boundary"],
        "boundary": b,
        "waited_for_break_min": waited,
    }


# -------------------------------------------------------------------- copy
#
# House rules: lead with a fact about the work, offer, end in a question.
# No "should", nothing about how the person is or feels, and no reading of
# the block count -- it is a counter, not a score.

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n: int) -> str:
    """5 -> 'five', 25 -> 'twenty-five'. Digits past 99."""
    if 0 <= n < 20:
        return _ONES[n]
    if 20 <= n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + (f"-{_ONES[o]}" if o else "")
    return str(n)


def _ring(block: int) -> str:
    return "\u25cf" * block + "\u25cb" * (BLOCKS_PER_CYCLE - block)


def _why_not_clean(b: dict[str, Any]) -> str:
    if b.get("recent_errors"):
        return "some of the last few calls failed"
    if not b.get("last_turn_ok", True):
        return "the last turn was stopped partway"
    if b.get("tight_loop"):
        return "we've been going back and forth fast"
    return "the work is mid-flight"


def render(p: dict[str, Any], cfg: dict[str, Any]) -> str:
    """The block the agent delivers. ``p`` is a speaking gate payload."""
    rest, work = words(cfg["break_min"]), words(cfg["work_min"])
    b = p.get("boundary") or {}
    clean, repeat, block = p.get("clean", True), int(p.get("repeat") or 0), p["block"]

    where = f"{p['stretch_min']} min on this stretch"
    header = (f"\u25cb  {_ring(block)} \u00b7 fourth block \u00b7 {where}"
              if p.get("long_rest") else f"\u25cb  {_ring(block)} \u00b7 {where}")

    if clean:
        spot = ("Clean spot \u2014 the last few calls all went through."
                if b.get("observed") else "Clean spot \u2014 that turn wrapped up.")
    else:
        spot = f"Not a clean spot \u2014 {_why_not_clean(b)} \u2014 but it has been a while."

    if repeat >= MAX_IGNORED - 1:
        body = [f"{rest.capitalize()} minutes if you want them. Last one until "
                "I see you step away; then the count picks back up."]
    elif repeat:
        body = ([spot] if not clean else ["Still a clean spot."]) + [
            f"{rest.capitalize()} minutes if you want them \u2014 say the word "
            "and I'll note where we are."]
    elif p.get("long_rest"):
        body = [spot,
                f"This is the longer rest the pattern asks for \u2014 "
                f"{words(LONG_REST_MIN)} or so, not {rest}. Want to take it "
                "while I keep at this?"]
    elif block == 1:
        body = [spot,
                f"The deal with this pattern is that {rest} minutes now buys back "
                f"the next {work}. Want to step away while I get on with this? "
                "It'll be here when you're back, and I'll note where we are if "
                "that helps."]
    elif clean:
        body = [spot,
                f"Want to step away for {rest} while I get on with this? It'll be "
                "here when you're back."]
    else:
        body = [spot, f"Want {rest} while I keep at it?"]

    footer = ('\u00b7 "not today" and I\'ll stop' if repeat >= MAX_IGNORED - 1 else
              '\u00b7 "skip" and I\'ll ask again next block  '
              '\u00b7 "not today" and I\'ll stop')
    return "\n".join([header, "", *body, "", footer])


# ------------------------------------------------- storage-backed wrapper
#
# Everything below reads and writes the plugin database. The hooks call
# on_user_turn / on_turn_end; the tool calls declare_rest / skip / status.


def _load() -> tuple[dict[str, Any], dict[str, Any]]:
    from . import goals as _goals  # noqa: PLC0415
    from . import storage as _storage  # noqa: PLC0415

    return config(_goals.get_goals()), parse_state(_storage.get_pomodoro_state())


def _save(state: dict[str, Any]) -> None:
    from . import storage as _storage  # noqa: PLC0415

    _storage.set_pomodoro_state(dump_state(state))


def _night(now: float) -> str:
    from . import activity as _activity  # noqa: PLC0415

    return _activity.night_of(now)


def _evaluate(now: float, state: dict[str, Any], recent: list[dict[str, Any]],
              cfg: dict[str, Any]) -> dict[str, Any]:
    """Gather the outside facts the pure gate needs, then ask it."""
    from . import activity as _activity  # noqa: PLC0415
    from . import storage as _storage  # noqa: PLC0415

    night = _night(now)
    out = should_suggest_pomodoro(
        now=now,
        state=state,
        recent=recent,
        cfg=cfg,
        snoozed=_storage.is_snoozed(night),
        bedtime_delta=_activity.minutes_past_target(_dt.datetime.fromtimestamp(now)),
        last_break_at=_storage.last_moment_at("break", night),
    )
    out["night"] = night
    return out


def on_user_turn(now: float, recent: list[dict[str, Any]],
                 may_speak: bool = True) -> Optional[dict[str, Any]]:
    """A message from the user. Moves the clock; returns an offer payload or None.

    ``may_speak`` is False when another moment already owns this turn: the
    clock still moves (you did speak), but nothing else is said.
    """
    from . import storage as _storage  # noqa: PLC0415

    cfg, state = _load()
    if not cfg["enabled"]:
        return None  # off means inert: not even the clock moves
    night = _night(now)
    state = touch(state, cfg, now, night=night)

    offer = None
    if may_speak:
        res = _evaluate(now, state, recent, cfg)
        if res["speak"]:
            res["text"] = render(res, cfg)
            _storage.record_moment("pomodoro", night)
            # The offer marks the block boundary whether or not it is taken,
            # or it would repeat on every message.
            state.update(
                stretch_start=now,
                blocks_done=res["next_blocks_done"],
                ignored_streak=int(state["ignored_streak"]) + 1,
                pending_since=0.0,
                last_reset_reason="offer",
            )
            offer = res
        elif res.get("hold") and not state.get("pending_since"):
            state["pending_since"] = now
    _save(state)
    return offer


def on_turn_end(now: float, completed: bool, interrupted: bool, failed: bool,
                calls: int, turn_min: int) -> None:
    """The agent handed back. Hitting stop counts as you being there."""
    cfg, state = _load()
    if not cfg["enabled"]:
        return
    if interrupted:
        state = touch(state, cfg, now, night=_night(now))
    state.update(
        last_turn_ended=now,
        last_turn_ok=bool(completed) and not (interrupted or failed),
        last_turn_calls=int(calls or 0),
        last_turn_min=int(turn_min or 0),
    )
    _save(state)


def declare_rest(now: float, minutes: Optional[int] = None) -> dict[str, Any]:
    """'Taking five.' Starts a fresh stretch now; a long one resets the cycle."""
    from . import storage as _storage  # noqa: PLC0415

    cfg, state = _load()
    mins = int(minutes) if minutes else cfg["break_min"]
    night = _night(now)
    _rest(state, now, mins * 60, "rest declared", night)
    state["last_human_at"] = now
    _save(state)
    _storage.record_moment("pomodoro_rest", night)
    return {"night": night, "minutes": mins, "long_rest": mins >= LONG_REST_MIN}


def skip(now: float, scope: str = "block") -> dict[str, Any]:
    """'skip' needs no state: the offer already started the next block."""
    if scope != "today":
        return {"scope": "block", "paused": False}
    cfg, state = _load()
    state.update(paused=1, paused_until=now + 24 * 3600, pending_since=0.0)
    _save(state)
    return {"scope": "today", "paused": True}


def status(now: float, recent: list[dict[str, Any]]) -> dict[str, Any]:
    """Where the clock is and why it is quiet. Reads only."""
    from . import storage as _storage  # noqa: PLC0415

    cfg, state = _load()
    res = _evaluate(now, state, recent, cfg)
    b = res.get("boundary") or boundary_state(recent, state, now)
    night = res["night"]
    block = int(state.get("blocks_done") or 0) % BLOCKS_PER_CYCLE + 1
    return {
        "enabled": cfg["enabled"],
        "block_min": cfg["work_min"],
        "rest_min": cfg["break_min"],
        "away_min": cfg["away_min"],
        "stretch_min": stretch_min(state, now),
        "block": f"{block} of {BLOCKS_PER_CYCLE}",
        "ring": _ring(block),  # same ring the offer for this block would show
        "due": bool(res["speak"]),
        "at_boundary": b["at_boundary"],
        "why_silent": "" if res["speak"] else res["why"],
        # For the readout under the clock: blank when it would only repeat
        # the minutes the clock line already shows.
        "note": ("Due — it will offer at your next message." if res["speak"]
                 else "" if res.get("not_due") else res["why"]),
        "ignored_streak": int(state.get("ignored_streak") or 0),
        "paused": bool(state.get("paused")),
        "last_reset_reason": state.get("last_reset_reason") or "",
        "offers_today": _storage.moment_count("pomodoro", night),
        "resets_today": (int(state.get("resets_today") or 0)
                         if state.get("resets_night") == night else 0),
    }
