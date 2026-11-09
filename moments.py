"""Opportune moments other than bedtime.

Kairos is named for the right moment, and a bedtime is only one of them. This
module holds the others. Each follows the same contract as the wind-down: it
offers, it never instructs, it says nothing rather than guessing, and it tells
you what it observed rather than what it concluded about you.

Two so far:

``break``
    The work has stopped moving forward. Four or more failures inside a short
    window, or the same tool failing over and over, is a measurable fact about
    the work -- not a claim about the person. If bedtime is close the wind-down
    owns the moment instead, because suggesting a coffee twenty minutes before
    someone's target would be absurd.

``handoff``
    Kairos writes down where the work got to when you stop. Nothing used to
    hand it back. Now the most recent note is offered once, on the first turn
    of a later session, and then marked seen.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from . import activity as _activity
from . import goals as _goals
from . import storage as _storage
from . import winddown as _winddown

# --- break detection ------------------------------------------------------
#
# Deliberately conservative. A false positive here is worse than a miss: it
# interrupts someone who is working fine, which is exactly the failure mode
# this plugin exists to avoid.

MIN_ERRORS = 4          # failures needed inside the window
WINDOW_MIN = 25         # how recent they have to be
MIN_CALLS = 6           # don't judge a session that has barely started
ERROR_SHARE = 0.5       # at least half of recent calls going wrong
BREAK_COOLDOWN_MIN = 90  # once an hour and a half at most
MAX_BREAKS = 2          # and twice a night is the ceiling

# If the bedtime target is this close, the wind-down owns the moment.
BEDTIME_PRIORITY_MIN = 90

# --- handoff recall -------------------------------------------------------

HANDOFF_MAX_AGE_H = 36  # older than this and it is history, not a handoff


def thrash_state(
    recent: list[dict[str, Any]], now: Optional[_dt.datetime] = None
) -> dict[str, Any]:
    """Measure whether the work is going round in circles.

    Returns counts only. No interpretation, and nothing about the person --
    the copy layer is not allowed to upgrade this into a mood.
    """
    now = now or _dt.datetime.now()
    cutoff = now.timestamp() - WINDOW_MIN * 60
    window = [o for o in (recent or []) if o.get("at", 0) >= cutoff]
    errors = [o for o in window if o.get("error")]

    # Which tool is failing most, if one stands out.
    by_tool: dict[str, int] = {}
    for o in errors:
        by_tool[o.get("tool") or "?"] = by_tool.get(o.get("tool") or "?", 0) + 1
    worst_tool, worst_count = (None, 0)
    if by_tool:
        worst_tool, worst_count = max(by_tool.items(), key=lambda kv: kv[1])

    share = (len(errors) / len(window)) if window else 0.0
    spread_min = 0
    if errors:
        spread_min = int((errors[-1]["at"] - errors[0]["at"]) / 60)

    return {
        "calls": len(window),
        "errors": len(errors),
        "error_share": round(share, 2),
        "worst_tool": worst_tool,
        "worst_tool_errors": worst_count,
        "spread_min": spread_min,
        "thrashing": (
            len(window) >= MIN_CALLS
            and len(errors) >= MIN_ERRORS
            and share >= ERROR_SHARE
        ),
    }


def render_break(state: dict[str, Any]) -> str:
    """Copy for a suggested break: what was observed, an offer, a question.

    States a count and nothing else. It does not say the user is stuck,
    frustrated, tired or going in circles -- those are conclusions about a
    person drawn from a number about some tool calls.
    """
    n = state["errors"]
    tool = state["worst_tool"]

    if tool and state["worst_tool_errors"] >= 3:
        what = f"{n} failed calls in a row here, mostly `{tool}`."
    else:
        what = f"{n} of the last {state['calls']} calls came back failed."

    lines = [
        "\u25cb  nothing to do with the hour \u2014 just the work",
        "",
        what,
        "",
        "That is often the point where stepping away beats another attempt.",
        "I can write down where this got to, so picking it up is cheap.",
        "Want me to?",
        "",
        "\u00b7 say \"keep going\" and I'll drop it",
    ]
    return "\n".join(lines)


def should_suggest_break(
    now: Optional[_dt.datetime] = None,
    recent: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    """Decide whether to offer a break right now. Returns a payload, or None.

    Gates, most absolute first:

      1. tone 'off'                                  -> silent
      2. snoozed tonight                             -> silent
      3. bedtime is close                            -> silent, wind-down wins
      4. work is not measurably stuck                -> silent
      5. already said twice tonight, or inside the
         cooldown                                    -> silent
    """
    now = now or _dt.datetime.now()
    g = _goals.get_goals()
    if (g.get("tone") or "encouraging") == "off":
        return None

    night = _activity.night_of(now.timestamp())
    if _storage.is_snoozed(night):
        return None

    # The wind-down owns the hours around a target, so stay out of that band
    # or the user gets two different things to answer in one turn.
    #
    # minutes_past_target is a SIGNED ARC on the 24h circle, not a countdown:
    # with a 02:30 target, 14:00 reads as +690 ("past"), not as "ahead". So the
    # test has to be a band bounded on both sides, using the same window the
    # wind-down actually speaks in. A one-sided check here silenced the whole
    # working day.
    delta = _activity.minutes_past_target(now)
    if delta is not None and -BEDTIME_PRIORITY_MIN <= delta <= _winddown.PAST_LIMIT_MIN:
        return None

    state = thrash_state(recent or _storage.recent_outcomes(), now=now)
    if not state["thrashing"]:
        return None

    if _storage.moment_count("break", night) >= MAX_BREAKS:
        return None
    last = _storage.last_moment_at("break", night)
    if last is not None and (now.timestamp() - last) < BREAK_COOLDOWN_MIN * 60:
        return None

    return {
        "kind": "break",
        "night": night,
        "state": state,
        "text": render_break(state),
    }


def render_handoff(night: str, text: str, age_h: float) -> str:
    """Hand back the note the last session left, without ceremony."""
    when = "last night" if age_h < 24 else f"{int(age_h // 24)} days ago"
    body = text.strip()
    if len(body) > 1200:
        body = body[:1200].rstrip() + "\n\n[...]"
    return (
        f"\u25cb  you left yourself a note {when}\n"
        "\n"
        f"{body}\n"
        "\n"
        "\u00b7 that's where we stopped. Pick it up, or say \"fresh start\"."
    )


def pending_handoff(
    now: Optional[_dt.datetime] = None,
) -> Optional[dict[str, Any]]:
    """The handoff worth handing back, if there is one. Reads only.

    Silent when: there is no handoff, it is older than HANDOFF_MAX_AGE_H, it
    has already been offered, or it belongs to the night still in progress
    (you have not been away yet, so there is nothing to come back to).
    """
    now = now or _dt.datetime.now()
    latest = _storage.latest_handoff()
    if not latest:
        return None
    night, text, written_at = latest
    if not (text or "").strip():
        return None

    age_h = (now.timestamp() - written_at) / 3600.0
    if age_h > HANDOFF_MAX_AGE_H:
        return None

    # Written during the night that is still current: the session never ended,
    # so handing it back would be reading someone their own notes.
    if night == _activity.night_of(now.timestamp()) and age_h < 1:
        return None

    if _storage.handoff_was_seen(night):
        return None

    return {
        "kind": "handoff",
        "night": night,
        "age_h": round(age_h, 1),
        "text": render_handoff(night, text, age_h),
    }
