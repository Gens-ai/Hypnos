"""Coaching tool handlers: goals, commitments, wind-down, check-in."""

from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any

from . import activity as _activity
from . import goals as _goals
from . import storage as _storage
from . import winddown as _winddown

_HHMM = re.compile(r"^\d{1,2}:\d{2}$")


def _ok(**kw: Any) -> str:
    return json.dumps({"success": True, **kw}, indent=2)


def _err(msg: str, **kw: Any) -> str:
    return json.dumps({"success": False, "error": msg, **kw}, indent=2)


def _valid_hhmm(v: str) -> bool:
    if not _HHMM.match(str(v)):
        return False
    h, m = (int(x) for x in str(v).split(":"))
    return 0 <= h <= 23 and 0 <= m <= 59


# ------------------------------------------------------------ kairos_goal


def kairos_goal(params: dict, **_kw: Any) -> str:
    action = (params.get("action") or "get").lower()

    if action == "get":
        g = _goals.get_goals()
        night = _activity.night_of(_dt.datetime.now().timestamp())
        return _ok(goals=g, tonight=_goals.resolve_target(night))

    if action == "stop_ramp":
        return _ok(goals=_goals.set_goals(goal_bedtime="", ramp_started=""))

    if action == "start_ramp":
        g = _goals.get_goals()
        if not g.get("goal_bedtime"):
            return _err("Set goal_bedtime first, so there is something to ramp toward.")
        return _ok(
            goals=_goals.set_goals(ramp_started=_dt.date.today().isoformat()),
            note=(
                f"Shifting the target toward {g['goal_bedtime']} by "
                f"{g.get('ramp_min_per_week', 15)} min/week."
            ),
        )

    if action != "set":
        return _err("action must be get, set, start_ramp or stop_ramp")

    for key in ("target_bedtime", "goal_bedtime", "checkin_time"):
        v = params.get(key)
        if v not in (None, "") and not _valid_hhmm(v):
            return _err(f"'{key}' must be 'HH:MM', got {v!r}.")

    dur = params.get("target_duration_min")
    if dur is not None and not 180 <= int(dur) <= 900:
        return _err("target_duration_min should be between 180 and 900 minutes.")

    tone = params.get("tone")
    if tone is not None and tone not in _goals.TONES:
        return _err(f"tone must be one of {', '.join(_goals.TONES)}")

    g = _goals.set_goals(
        target_bedtime=params.get("target_bedtime"),
        target_duration_min=dur,
        goal_bedtime=params.get("goal_bedtime"),
        ramp_min_per_week=params.get("ramp_min_per_week"),
        tone=tone,
        checkin_enabled=params.get("checkin_enabled"),
        checkin_time=params.get("checkin_time"),
        checkin_channel=params.get("checkin_channel"),
    )
    night = _activity.night_of(_dt.datetime.now().timestamp())
    return _ok(goals=g, tonight=_goals.resolve_target(night))


# ------------------------------------------------------ kairos_commitment


def kairos_commitment(params: dict, **_kw: Any) -> str:
    action = (params.get("action") or "list").lower()

    if action == "list":
        return _ok(commitments=_goals.list_commitments(upcoming_only=False))

    if action == "remove":
        cid = params.get("id")
        if cid is None:
            return _err("'id' is required to remove a commitment.")
        return _ok(removed=_goals.remove_commitment(int(cid)))

    if action != "add":
        return _err("action must be list, add or remove")

    on_date = params.get("on_date")
    wake_by = params.get("wake_by")
    if not on_date or not wake_by:
        return _err("'on_date' and 'wake_by' are both required.")
    try:
        _dt.date.fromisoformat(str(on_date))
    except ValueError:
        return _err("'on_date' must be an ISO date like 2026-11-14.")
    if not _valid_hhmm(wake_by):
        return _err("'wake_by' must be 'HH:MM'.")

    cid = _goals.add_commitment(
        str(on_date),
        str(wake_by),
        label=params.get("label") or "",
        prep_days=int(params.get("prep_days") or 1),
    )

    # Show the user what it actually does to the affected nights.
    prep = max(1, int(params.get("prep_days") or 1))
    d0 = _dt.date.fromisoformat(str(on_date))
    schedule = []
    for lead in range(prep, 0, -1):
        n = (d0 - _dt.timedelta(days=lead)).isoformat()
        t = _goals.resolve_target(n)
        schedule.append({"night": n, "bedtime": t["bedtime"], "source": t["source"]})

    return _ok(id=cid, schedule=schedule,
               note="Normal target resumes the night after.")


# -------------------------------------------------------- kairos_winddown


def kairos_winddown(params: dict, **_kw: Any) -> str:
    action = (params.get("action") or "status").lower()
    now = _dt.datetime.now()
    night = _activity.night_of(now.timestamp())

    if action == "snooze":
        _storage.snooze_night(night)
        return _ok(night=night, snoozed=True,
                   note="Muted for tonight. Say nothing more about it.")

    if action == "handoff":
        summary = (params.get("summary") or "").strip()
        if not summary:
            return _err("'summary' is required: what was in flight and the next step.")
        path = _storage.write_handoff(night, summary)
        return _ok(night=night, path=path,
                   note="Thread saved. Nothing is lost.")

    if action != "status":
        return _err("action must be status, snooze or handoff")

    target = _goals.resolve_target(night)
    if target["source"] == "none":
        return _ok(nudge=None, target=target,
                   note="No target set, so Kairos stays quiet.")

    due = _winddown.should_nudge(now=now, recent=_storage.recent_outcomes())
    return _ok(
        night=night,
        target=target,
        snoozed=_storage.is_snoozed(night),
        rung=_winddown.current_rung(target["bedtime"], now),
        nudge=due["text"] if due else None,
    )


# --------------------------------------------------------- kairos_checkin


def kairos_checkin(params: dict, **_kw: Any) -> str:
    action = (params.get("action") or "ask").lower()
    # The check-in asks about last night, which ended this morning.
    last_night = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()

    if action == "ask":
        _storage.record_checkin(last_night, asked=True)
        act = {r["day"]: r for r in _storage.list_activity(limit=7)}.get(last_night)
        context = {}
        if act and act.get("last_activity"):
            context["stopped_at"] = _dt.datetime.fromtimestamp(
                act["last_activity"]
            ).strftime("%H:%M")
        return _ok(
            night=last_night,
            question="How did you sleep?",
            context=context,
            note=(
                "One question only. Do NOT open with a missed target or mention "
                "how late they worked — just ask, log the answer with "
                "sleep_log, and let them get on with their day."
            ),
        )

    if action != "answer":
        return _err("action must be ask or answer")

    answer = (params.get("answer") or "").strip()
    if not answer:
        return _err("'answer' is required.")
    _storage.record_checkin(last_night, answer=answer)
    return _ok(
        night=last_night,
        recorded=True,
        note="If they gave a duration, call sleep_log with it too.",
    )


# -------------------------------------------------------- kairos_pomodoro


def kairos_pomodoro(params: dict, **_kw: Any) -> str:
    from . import pomodoro as _pomodoro  # noqa: PLC0415

    action = (params.get("action") or "status").lower()
    now = _dt.datetime.now().timestamp()
    recent = _storage.recent_outcomes()

    if action == "status":
        return _ok(pomodoro=_pomodoro.status(now, recent))
    if action not in ("rest", "skip"):
        return _err("action must be status, rest or skip")
    if not _pomodoro.config(_goals.get_goals())["enabled"]:
        return _err("The pomodoro is off. It can be switched on in Kairos settings.")

    if action == "rest":
        minutes = params.get("minutes")
        if minutes is not None:
            try:
                minutes = int(minutes)
            except (TypeError, ValueError):
                return _err("'minutes' must be a whole number.")
            if not 1 <= minutes <= 240:
                return _err("'minutes' must be 1-240.")
        out = _pomodoro.declare_rest(now, minutes)
        return _ok(**out, note="Noted. Say nothing about it when they're back.")

    scope = (params.get("scope") or "block").lower()
    if scope not in ("block", "today"):
        return _err("scope must be block or today")
    out = _pomodoro.skip(now, scope)
    return _ok(**out, note=(
        "No more offers until they've been away a while. Drop the subject."
        if scope == "today" else "Drop it; the next offer is a full block away."
    ))
