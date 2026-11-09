"""The wind-down ladder: when to speak, and what to say.

Copy rules, enforced by the templates below:
  * Never assume tiredness. "It's late" is not evidence that anyone is
    tired. Plenty of people work till 3am by choice and sleep till 11.
  * Never moralise about the hour. The only reference point is the
    target the user set.
  * Name the sleep goal out loud, so it is never mistaken for a
    productivity nag.
  * Lead with something true about the work.
  * End in a question. Offer, never instruct. The word "should" is banned.
  * Promise continuity — the thread is saved, nothing is lost.
  * One nudge per rung per night, then silence.
  * Stopping mid-problem is not a failure; sleeping on it is a real
    strategy, and the copy may say so.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from . import goals as _goals
from . import storage as _storage

# Rungs are minutes relative to the target bedtime (negative = before).
RUNGS: tuple[tuple[str, int, int], ...] = (
    ("runway", -120, -45),   # plenty of time left
    ("approach", -45, -5),   # closing in
    ("target", -5, 60),      # at it
    ("past", 60, 10_000),    # well beyond
)

# Which rungs each tone is allowed to speak on.
TONE_RUNGS: dict[str, frozenset[str]] = {
    "off": frozenset(),
    "gentle": frozenset({"approach"}),          # one quiet note, clean points only
    "encouraging": frozenset({"runway", "approach", "target", "past"}),
    "firm": frozenset({"runway", "approach", "target", "past"}),
    "guardian": frozenset({"runway", "approach", "target", "past"}),
}

# Only these tones will speak regardless of whether work is at rest; gentle
# waits for a genuine clean break and gives up if one never comes.
CLEAN_ONLY = frozenset({"gentle"})

# Rungs allowed to fire more than once a night, spaced by nudge_gap_min.
# Everything before the target is said once and then dropped; staying up
# well past your own mark is the only thing worth mentioning again.
REPEATABLE_RUNGS = frozenset({"past"})

# ...and even that one tapers and then stops. Three mentions of the same
# thing in one night is the ceiling; past that it is nagging, whatever the
# gap is set to.
MAX_REPEATS = 3

_BAR_CELLS = 10


def night_bar(fraction: float) -> str:
    """Night filling the bar as the target approaches. 0.0 = early, 1.0 = at it."""
    f = max(0.0, min(1.0, fraction))
    filled = int(f * _BAR_CELLS)
    out = ["\u2588"] * filled
    if filled < _BAR_CELLS:
        # One transitional cell so the bar reads as a gradient, not a step.
        rem = f * _BAR_CELLS - filled
        out.append("\u2593" if rem > 0.66 else "\u2592" if rem > 0.33 else "\u2591")
        out += ["\u2591"] * (_BAR_CELLS - len(out))
    return "".join(out[:_BAR_CELLS])


def _minutes_to(target_hhmm: str, now: _dt.datetime) -> Optional[int]:
    """Signed minutes from now to the target (negative = target still ahead)."""
    try:
        th, tm = (int(x) for x in target_hhmm.split(":"))
    except (ValueError, AttributeError):
        return None
    now_min = now.hour * 60 + now.minute
    tgt = th * 60 + tm
    # Shortest signed arc on the 24h circle.
    return (now_min - tgt + 720) % 1440 - 720


def current_rung(target_hhmm: str, now: _dt.datetime) -> Optional[tuple[str, int]]:
    delta = _minutes_to(target_hhmm, now)
    if delta is None:
        return None
    for name, lo, hi in RUNGS:
        if lo <= delta < hi:
            return name, delta
    return None


# ------------------------------------------------- safe stopping point


def stop_state(recent: list[dict[str, Any]], cwd: Optional[str] = None) -> dict[str, Any]:
    """Is this a natural place to leave the work?

    Deliberately valence-free: `open_threads` is a fact, not a judgement.
    Sleeping on an unsolved problem is a legitimate strategy.

    ``observed`` distinguishes "I looked and the work is at rest" from "I have
    nothing to look at". A scheduled ping fired while you are away from Hermes
    gets the latter, and must not claim your work is tidy when it has no idea.
    """
    errors = sum(1 for r in recent[-6:] if r.get("error"))
    last_error = bool(recent and recent[-1].get("error"))
    dirty = None
    if cwd:
        dirty = _git_dirty(cwd)
    clean = (not last_error) and errors == 0 and dirty is not True
    return {
        "clean": clean,
        "observed": bool(recent) or dirty is not None,
        "recent_errors": errors,
        "last_call_errored": last_error,
        "uncommitted": dirty,
        "open_threads": errors > 0 or dirty is True,
    }


def _git_dirty(cwd: str) -> Optional[bool]:
    import subprocess  # noqa: PLC0415

    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode != 0:
            return None
        return bool(r.stdout.strip())
    except Exception:
        return None


# ------------------------------------------------------------ rendering

_POPPY = "     \u2740"


def render(
    rung: str,
    delta_min: int,
    target: dict[str, Any],
    state: dict[str, Any],
    now: _dt.datetime,
    repeat: int = 0,
) -> str:
    """Build the blockquote the agent will deliver.

    ``repeat`` is how many times this rung has already fired tonight, so a
    recurring nudge can taper instead of saying the same sentence twice.
    """
    bedtime = target["bedtime"]
    # Fraction of the way from the 'runway' edge to the target.
    frac = 1.0 if delta_min >= 0 else 1.0 - (abs(delta_min) / 120.0)
    bar = night_bar(frac)

    if delta_min < 0:
        when = f"bedtime {bedtime} \u00b7 {abs(delta_min)} min out"
    elif delta_min < 5:
        when = f"{bedtime} \u00b7 that's your bedtime"
    else:
        hrs = delta_min // 60
        when = (
            f"{now.strftime('%H:%M')} \u00b7 "
            + (f"{hrs}h past your {bedtime} target" if hrs else f"past your {bedtime} target")
        )

    header = f"\u263e {bar} \u00b7 {when}"
    body = _body(rung, target, state, repeat)
    footer = '\u00b7 say "not tonight" to mute'

    lines = []
    # The poppy is Kairos's own attribute and only earns its place by being
    # rare: once a night, on the first time we're past the mark. A second
    # one an hour later would make it wallpaper.
    if rung == "past" and repeat == 0:
        lines.append(_POPPY)
    lines += [header, "", body, "", footer]
    return "\n".join("> " + ln if ln else ">" for ln in lines)


def _body(
    rung: str, target: dict[str, Any], state: dict[str, Any], repeat: int = 0
) -> str:
    dur = target.get("duration_min") or 450
    hours = f"{dur // 60}h{dur % 60:02d}" if dur % 60 else f"{dur // 60}h"
    because = f" ({target['reason']})" if target.get("reason") else ""

    if rung == "runway":
        return (
            f"Flagging the runway, nothing more \u2014 you're aiming for {hours} "
            f"tonight{because}. Carry on."
        )

    if rung == "approach":
        if not state.get("observed"):
            # Scheduled ping: Kairos cannot see the work, so it says nothing
            # about the work. Only the clock and the goal, which it does know.
            return (
                f"Bedtime's {target['bedtime']}{because}, and you're coming up "
                f"on it if you want the full {hours}. "
                "No idea what you're in the middle of \u2014 just marking the time."
            )
        if state.get("clean"):
            return (
                "Good spot \u2014 nothing failing and nothing half-finished. If you "
                f"want the full {hours}, this is an easy place to leave it. "
                "Want me to write up where we got to so you can start winding down?"
            )
        return (
            f"Coming up on the bedtime you set{because}. No rush \u2014 want me to "
            "flag the next clean break so you can wind down from there?"
        )

    if rung == "target":
        if not state.get("observed"):
            return (
                f"That's the {target['bedtime']} you set{because}. Wherever "
                f"you've got to, {hours} from now still works if you turn in "
                "soon. Want me to save the thread first?"
            )
        if state.get("clean"):
            return (
                "That's your bedtime, and you're at a natural break. I've got the "
                "thread \u2014 nothing's lost if you head to bed now."
            )
        return (
            "That's your bedtime. Land whatever you're mid-way through and I'll "
            "note where we end up \u2014 it'll be waiting, with fresh eyes on it."
        )

    # past
    if repeat:
        # Already said once tonight. Get shorter, drop the reasoning, and
        # signal that this is the end of it rather than the start of a habit.
        if repeat >= MAX_REPEATS - 1:
            return (
                "Last mention tonight, then I'll leave you to it. Say the word "
                "and I'll write up where we are."
            )
        return (
            f"Still the {target['bedtime']} mark{because}. Want me to park "
            "things so tomorrow starts clean?"
        )
    if state.get("open_threads"):
        return (
            "Still something open here. Worth saying: handing a problem to "
            "tomorrow-you is a real strategy, not giving up \u2014 sleep genuinely "
            "does some of the work. Want me to park it and write up the state?"
        )
    if not state.get("observed"):
        return (
            f"You'd set {target['bedtime']} as the mark{because}. No pressure "
            "and no idea what you're up to \u2014 but if you're winding down "
            "anyway, this is me saying goodnight."
        )
    return (
        f"You'd set {target['bedtime']} as the mark{because}, and the work is at "
        "rest. Want me to save the thread and leave you to it?"
    )


# ----------------------------------------------------------- gating


def should_nudge(
    now: Optional[_dt.datetime] = None,
    recent: Optional[list[dict[str, Any]]] = None,
    cwd: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Decide whether to speak right now. Returns the payload, or None.

    Order of gates, cheapest and most absolute first:

      1. no target set, or tone 'off'            -> silent, always
      2. snoozed tonight                         -> silent, no exceptions
      3. not in a rung this tone may speak on    -> silent
      4. inside the cooldown (nudge_gap_min)     -> silent
      5. rung already said, and not repeatable   -> silent
      6. work is mid-flight                      -> hold for a natural break,
         up to clean_break_patience_min; 'gentle' never fires while messy
    """
    now = now or _dt.datetime.now()
    from . import activity as _activity  # noqa: PLC0415

    night = _activity.night_of(now.timestamp())
    target = _goals.resolve_target(night)
    if target["source"] == "none" or not target.get("bedtime"):
        return None

    g = _goals.get_goals()
    tone = target.get("tone", "gentle")
    if tone == "off":
        return None

    if _storage.is_snoozed(night):
        return None

    r = current_rung(target["bedtime"], now)
    if not r:
        return None
    rung, delta = r

    if rung not in TONE_RUNGS.get(tone, frozenset()):
        return None

    # --- spacing: never two nudges inside the user's chosen gap
    try:
        gap_min = max(0, int(g.get("nudge_gap_min") or 45))
    except (TypeError, ValueError):
        gap_min = 45
    last = _storage.last_nudge_at(night)
    if last is not None and (now.timestamp() - last) < gap_min * 60:
        return None

    # --- repetition: early rungs are said once, 'past' may recur but tapers
    fired = _storage.nudge_count(night, rung)
    if fired and rung not in REPEATABLE_RUNGS:
        return None
    if fired >= MAX_REPEATS:
        return None

    # --- natural stopping point
    state = stop_state(recent or [], cwd=cwd)
    waited_min = 0
    if not state["clean"]:
        if tone in CLEAN_ONLY:
            # Gentle would rather miss the window than cut in.
            return None
        if str(g.get("prefer_clean_break", "true")).lower() == "true":
            try:
                patience = max(0, int(g.get("clean_break_patience_min") or 20))
            except (TypeError, ValueError):
                patience = 20
            since = _storage.pending_since(night, rung)
            if since is None:
                since = now.timestamp()
                _storage.mark_pending(night, rung, since)
            waited_min = int((now.timestamp() - since) / 60)
            if waited_min < patience:
                return None  # still hoping for a clean break
    else:
        _storage.clear_pending(night, rung)

    return {
        "night": night,
        "rung": rung,
        "delta_min": delta,
        "tone": tone,
        "target": target,
        "state": state,
        "waited_for_break_min": waited_min,
        "repeat": fired,
        "text": render(rung, delta, target, state, now, repeat=fired),
    }
