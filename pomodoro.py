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
PAUSE_LIFTS_AFTER_H = 3  # "not today" ends once you've been gone this long

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
