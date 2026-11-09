"""Kairos — your coding agent, paying attention to when you sleep.

Hermes is the thing you talk to at 3am. That makes it the only honest
candidate for this job: not a bystander asking what you did yesterday, but
the accomplice that was there, participating.

Design commitments, in order of importance:

  1. There is no correct bedtime. Kairos measures you against the target
     *you* set, and stays silent until you set one. Working till 3am and
     sleeping till 11 is a valid way to live, not a defect to correct.
  2. It never assumes you are tired. The hour on the clock is not evidence
     about your body.
  3. It offers, it does not instruct. Tone is the user's choice, default
     'gentle'. "not tonight" is honoured without comment.
  4. Stopping mid-problem is not a failure. Sleeping on something is a real
     strategy, and the copy is allowed to say so.

Surfaces used: ctx.register_tool, ctx.register_hook, ctx.register_skill.
No network calls.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from . import activity as _activity
from . import coach_schemas as _cschemas
from . import coach_tools as _ctools
from . import goals as _goals
from . import schemas as _schemas
from . import storage as _storage
from . import tools as _tools
from . import wearable_tools as _wtools
from . import winddown as _winddown

__version__ = "0.4.0"

# Tools that can lose work or touch the outside world. The quiet-hours guard
# only ever considers these; everything else is untouched at every tone.
RISKY_TOOLS = {
    "terminal",
    "write_file",
    "patch",
    "execute_code",
    "browser_exec",
    "delegate_task",
}

# Argument patterns worth a second look before they run.
_DESTRUCTIVE = re.compile(
    r"\b(rm\s+-rf|drop\s+table|git\s+push\s+--force|force-push|migrate|"
    r"truncate|deploy|DELETE\s+FROM|git\s+reset\s+--hard)\b",
    re.I,
)

# Only these tones will ever gate a tool call, and the guard must also be
# switched on. Nothing is gated at 'gentle' or 'encouraging'.
_GATING_TONES = {"firm", "guardian"}


def _in_quiet_hours(now: _dt.datetime, start: str, end: str) -> bool:
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except (ValueError, AttributeError):
        return False
    cur = now.hour * 60 + now.minute
    s = sh * 60 + sm
    e = eh * 60 + em
    return cur >= s or cur < e if s > e else s <= cur < e


def register(ctx):  # noqa: C901
    _wtools.bind_ctx(ctx)
    # ----------------------------------------------------------- tools
    for schema, handler in (
        (_schemas.SLEEP_LOG, _tools.sleep_log),
        (_schemas.SLEEP_IMPORT, _tools.sleep_import),
        (_schemas.KAIROS_ACTIVITY, _tools.kairos_activity),
        (_schemas.KAIROS_REPORT, _tools.kairos_report),
        (_schemas.KAIROS_GUARD, _tools.kairos_guard),
        (_cschemas.KAIROS_GOAL, _ctools.kairos_goal),
        (_cschemas.KAIROS_COMMITMENT, _ctools.kairos_commitment),
        (_cschemas.KAIROS_WINDDOWN, _ctools.kairos_winddown),
        (_cschemas.KAIROS_CHECKIN, _ctools.kairos_checkin),
        (_cschemas.KAIROS_WEARABLE, _wtools.kairos_wearable),
        (_cschemas.KAIROS_PING, _wtools.kairos_ping),
    ):
        ctx.register_tool(
            name=schema["name"],
            toolset="kairos",
            schema=schema,
            handler=handler,
        )

    # ----------------------------------------------------------- hooks
    def on_session_start(**kwargs):
        """Refresh the activity table so a report is never stale."""
        del kwargs
        try:
            _activity.sync_activity(days=90)
        except Exception:  # never break session startup
            pass

    def post_tool_call(tool_name=None, args=None, result=None, **kwargs):
        """Accumulate activity, and track whether work is currently going well."""
        del args, kwargs
        try:
            errored = _activity._is_error(result)
            # Transient, in-process only: feeds stopping-point detection.
            _storage.record_outcome(tool_name or "?", errored)

            now = _dt.datetime.now()
            night = _activity.night_of(now.timestamp())
            fields = {"tool_calls": 1, "last_activity": now.timestamp()}
            if tool_name in ("terminal", "execute_code"):
                fields["terminal_calls"] = 1
            if errored:
                fields["error_results"] = 1
            # Lateness is measured against the user's OWN target, never a
            # hardcoded hour. No target means no such thing as late.
            past = _activity.minutes_past_target(now)
            if past is not None and past > 0:
                fields["late_minutes"] = past
            _storage.upsert_activity(night, fields)
        except Exception:
            pass

    def pre_llm_call(**kwargs):
        """Deliver the wind-down nudge between turns, never mid-tool-chain.

        Injected as context so the agent speaks it in its own voice, arriving
        as part of the conversation rather than as an alarm.
        """
        del kwargs
        try:
            due = _winddown.should_nudge(recent=_storage.recent_outcomes())
            if not due:
                return None
            _storage.record_nudge(due["night"], due["rung"])

            if _goals.get_goals().get("nudge_delivery") in ("notify", "both"):
                try:
                    ctx.os.notify(
                        title="Kairos",
                        body=f"Wind-down \u00b7 {due['target']['bedtime']} target",
                    )
                except Exception:
                    pass

            return {
                "context": (
                    "[Kairos] Deliver the block below to the user verbatim, as its "
                    "own quoted block, before anything else you say. Do not "
                    "paraphrase it, do not add commentary about the hour, and do "
                    "not suggest they are tired \u2014 the clock says nothing about "
                    "that. If they decline, or say anything resembling 'not "
                    "tonight', call kairos_winddown(action='snooze') and drop the "
                    "subject completely for the rest of the night.\n\n" + due["text"]
                )
            }
        except Exception:
            return None

    def pre_tool_call(tool_name=None, args=None, task_id=None, **kwargs):
        """Gate destructive work in quiet hours. Opt-in tones only."""
        del task_id, kwargs
        try:
            cfg = _storage.get_guard_config()
            tone = _goals.get_goals().get("tone", "gentle")
            if cfg.get("enabled") != "true" or tone not in _GATING_TONES:
                return None
            if tool_name not in RISKY_TOOLS:
                return None
            now = _dt.datetime.now()
            if not _in_quiet_hours(now, cfg["quiet_start"], cfg["quiet_end"]):
                return None
            if not _DESTRUCTIVE.search(json.dumps(args or {})[:4000]):
                return None

            night = _activity.night_of(now.timestamp())
            target = _goals.resolve_target(night)
            reason = (
                f"Kairos: this {tool_name} call looks destructive, and it is "
                f"{now.strftime('%H:%M')} \u2014 inside the quiet hours you set "
                f"({cfg['quiet_start']}\u2013{cfg['quiet_end']}"
                + (f", bedtime {target['bedtime']}" if target.get("bedtime") else "")
                + "). Worth a second look before it runs."
            )
            action = "block" if cfg.get("mode") == "block" else "approve"
            _storage.record_guard_event(tool_name or "?", action, reason)
            return {"action": action, "message": reason}
        except Exception:
            return None  # fail open: never wedge the agent

    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)

    # ----------------------------------------------------------- skills
    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                try:
                    ctx.register_skill(child.name, skill_md)
                except Exception:
                    pass
