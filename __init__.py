"""Hypnos — your agent's work pattern, measured against your sleep.

Hermes already knows you were up at 3am wrestling a build. Hypnos turns
that record into a lifestyle sensor, logs your sleep beside it, and reports
only the correlations the sample can actually support.

Surfaces used: ctx.register_tool, ctx.register_hook. No network calls.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from . import activity as _activity
from . import schemas as _schemas
from . import storage as _storage
from . import tools as _tools

__version__ = "0.1.0"

# Tools that can lose work or touch the outside world. The quiet-hours guard
# only ever considers these; everything else is untouched.
RISKY_TOOLS = {
    "terminal",
    "write_file",
    "patch",
    "execute_code",
    "browser_exec",
    "delegate_task",
}

# Argument patterns worth stopping for at 3am even inside a risky tool.
_DESTRUCTIVE = re.compile(
    r"\b(rm\s+-rf|drop\s+table|git\s+push\s+--force|force-push|migrate|"
    r"truncate|deploy|DELETE\s+FROM|git\s+reset\s+--hard)\b",
    re.I,
)


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
    # ----------------------------------------------------------- tools
    for schema, handler in (
        (_schemas.SLEEP_LOG, _tools.sleep_log),
        (_schemas.SLEEP_IMPORT, _tools.sleep_import),
        (_schemas.HYPNOS_ACTIVITY, _tools.hypnos_activity),
        (_schemas.HYPNOS_REPORT, _tools.hypnos_report),
        (_schemas.HYPNOS_GUARD, _tools.hypnos_guard),
    ):
        ctx.register_tool(
            name=schema["name"],
            toolset="hypnos",
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
        """Accumulate live signal state.db cannot give us: error rate."""
        del args, kwargs
        try:
            night = _activity.night_of(_dt.datetime.now().timestamp())
            fields = {"tool_calls": 1}
            if tool_name in ("terminal", "execute_code"):
                fields["terminal_calls"] = 1
            if _activity._is_error(result):
                fields["error_results"] = 1
            now = _dt.datetime.now()
            if now.hour >= _activity.LATE_HOUR or now.hour < _activity.NIGHT_ROLLOVER_HOUR:
                fields["late_minutes"] = _activity._late_minutes([now.timestamp()])
            fields["last_activity"] = now.timestamp()
            _storage.upsert_activity(night, fields)
        except Exception:
            pass

    def pre_tool_call(tool_name=None, args=None, task_id=None, **kwargs):
        """Quiet-hours guard. Off unless the user enabled it."""
        del task_id, kwargs
        try:
            cfg = _storage.get_guard_config()
            if cfg.get("enabled") != "true":
                return None
            if tool_name not in RISKY_TOOLS:
                return None
            now = _dt.datetime.now()
            if not _in_quiet_hours(now, cfg["quiet_start"], cfg["quiet_end"]):
                return None

            blob = json.dumps(args or {})[:4000]
            destructive = bool(_DESTRUCTIVE.search(blob))
            # Only the genuinely destructive stuff is worth interrupting for.
            if not destructive:
                return None

            reason = (
                f"Hypnos: it is {now.strftime('%H:%M')}, inside your declared "
                f"quiet hours ({cfg['quiet_start']}-{cfg['quiet_end']}), and this "
                f"{tool_name} call looks destructive. Past-you asked to be stopped here."
            )
            action = "block" if cfg.get("mode") == "block" else "approve"
            _storage.record_guard_event(tool_name or "?", action, reason)
            return {"action": action, "message": reason}
        except Exception:
            return None  # fail open: never wedge the agent

    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("post_tool_call", post_tool_call)
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
