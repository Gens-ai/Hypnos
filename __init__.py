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
     'encouraging'. "not tonight" is honoured without comment.
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
from . import moments as _moments
from . import pomodoro as _pomodoro
from . import schemas as _schemas
from . import storage as _storage
from . import tools as _tools
from . import wearable_tools as _wtools
from . import winddown as _winddown

__version__ = "0.5.1"

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


_NON_HUMAN_PLATFORMS = {"cron", "subagent"}

# Delivered ahead of a pomodoro offer. The agent keeps working: the user is
# the one who may step away, so nothing waits on an answer.
POMODORO_INSTRUCTION = (
    "[Kairos] Deliver the block below to the user verbatim, as its own quoted "
    "block, before anything else you say -- then carry on with the user's "
    "request as normal. Do not wait for an answer to the offer. Do not mention "
    "the hour, do not suggest they are tired or have been working too long, and "
    "do not interpret the block count. If they say 'skip' or 'keep going', call "
    "kairos_pomodoro(action='skip'); 'not today' -> kairos_pomodoro(action="
    "'skip', scope='today'); 'taking five', 'brb', 'back in 10' -> "
    "kairos_pomodoro(action='rest'). When they come back from a rest, say "
    "nothing about it.\n\n"
)


def _now_ts() -> float:
    """Indirection so the hook tests can drive the clock."""
    return _dt.datetime.now().timestamp()


def _human_turn(platform=None, parent_session_id=None, **_kw) -> bool:
    """True for the user's own interactive turns; False for cron and subagent work.

    A cron job firing at 03:00 is not the user working, and a subagent's tool
    failures are not the user going in circles. Both would otherwise receive
    nudges meant for the user and feed the thrash detector.
    """
    if platform in _NON_HUMAN_PLATFORMS:
        return False
    return not parent_session_id


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
        (_cschemas.KAIROS_POMODORO, _ctools.kairos_pomodoro),
    ):
        ctx.register_tool(
            name=schema["name"],
            toolset="kairos",
            schema=schema,
            handler=handler,
        )

    # ----------------------------------------------------------- hooks
    # Set on session start, cleared once the handoff has been offered. A
    # handoff is something you come back to, so it belongs on the first turn
    # of a later session and nowhere else.
    _fresh_session = {"value": True}

    # post_tool_call carries no platform, so pre_llm_call remembers which
    # sessions belong to cron or subagents. Bounded: a long-lived gateway
    # must not grow this forever.
    _non_human_sessions: dict[str, None] = {}
    _NON_HUMAN_MAX = 256

    def _note_session(kwargs) -> bool:
        """Record whether this hook call is human; returns True if it is."""
        human = _human_turn(**kwargs)
        sid = kwargs.get("session_id")
        if not human and sid:
            _non_human_sessions[sid] = None
            while len(_non_human_sessions) > _NON_HUMAN_MAX:
                _non_human_sessions.pop(next(iter(_non_human_sessions)))
        return human

    def _session_is_human(session_id) -> bool:
        return not (session_id and session_id in _non_human_sessions)

    # Per-turn facts for the pomodoro's boundary check, in-process and
    # bounded. Keyed by turn_id; popped when the turn ends.
    _turn_calls: dict[str, int] = {}
    _turn_started: dict[str, float] = {}
    _TURNS_MAX = 64

    def _bounded(d: dict) -> None:
        while len(d) > _TURNS_MAX:
            d.pop(next(iter(d)))

    def on_session_start(**kwargs):
        """Refresh the activity table so a report is never stale."""
        # A cron session starting in the gateway is not the user coming back,
        # so it must not arm the handoff for whichever chat speaks next.
        if _note_session(kwargs):
            _fresh_session["value"] = True
        try:
            _activity.sync_activity(days=90)
        except Exception:  # never break session startup
            pass

    def post_tool_call(tool_name=None, args=None, result=None, **kwargs):
        """Accumulate activity, and track whether work is currently going well."""
        del args
        if not _session_is_human(kwargs.get("session_id")):
            return
        tid = kwargs.get("turn_id")
        if tid:
            _turn_calls[tid] = _turn_calls.get(tid, 0) + 1
            _bounded(_turn_calls)
        try:
            errored = _activity._is_error(result)
            # Transient, in-process only: feeds stopping-point detection.
            _storage.record_outcome(tool_name or "?", errored)

            now = _dt.datetime.now()
            night = _activity.night_of(now.timestamp())
            # observed_calls is the denominator for error_results: this hook
            # is the only place either number can be known, because state.db
            # keeps no result text to inspect.
            fields = {
                "tool_calls": 1,
                "observed_calls": 1,
                "last_activity": now.timestamp(),
            }
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

    def _other_moments():
        """Moments that are not bedtime. Only reached when no nudge is due.

        Order matters: a handoff is a greeting and a break is an
        interruption, so the greeting goes first and only one is ever
        returned. Two prompts in one turn is how a plugin gets muted.
        """
        # 1. the note the last session left you, once, on the way in
        if _fresh_session["value"]:
            try:
                hand = _moments.pending_handoff()
            except Exception:
                hand = None
            _fresh_session["value"] = False
            if hand:
                _storage.mark_handoff_seen(hand["night"])
                return {
                    "context": (
                        "[Kairos] The user left themselves this note when they "
                        "stopped. Deliver the block below verbatim as its own "
                        "quoted block before anything else, then wait. Do not "
                        "summarise it, do not add encouragement, and do not "
                        "assume they want to continue that work.\n\n"
                        + hand["text"]
                    )
                }

        # 2. the work has stopped moving forward
        try:
            brk = _moments.should_suggest_break(recent=_storage.recent_outcomes())
        except Exception:
            brk = None
        if brk:
            _storage.record_moment("break", brk["night"])
            return {
                "context": (
                    "[Kairos] Deliver the block below to the user verbatim, as "
                    "its own quoted block, before anything else you say. This "
                    "is about the work, not the hour and not the user: do not "
                    "mention bedtime, do not suggest they are tired, frustrated "
                    "or struggling, and do not diagnose why the failures are "
                    "happening. If they decline or say anything like 'keep "
                    "going', drop the subject and do not raise it again this "
                    "session.\n\n" + brk["text"]
                )
            }
        return None

    def pre_llm_call(**kwargs):
        """Deliver at most one moment between turns, never mid-tool-chain.

        Priority: wind-down, then handoff, then the thrash break, then the
        pomodoro offer. Injected as context so the agent speaks it in its own voice, arriving
        as part of the conversation rather than as an alarm.
        """
        if not _note_session(kwargs):
            return None  # cron and subagent turns: nothing to deliver, nothing to learn
        now = _now_ts()
        tid = kwargs.get("turn_id")
        if tid:
            _turn_started[tid] = now
            _bounded(_turn_started)

        out = _bedtime_or_other()
        # The pomodoro clock moves on every human turn, even when another
        # moment owns this one -- you did speak. It only gets the turn if
        # nothing else wanted it: one moment per turn.
        try:
            pom = _pomodoro.on_user_turn(
                now, recent=_storage.recent_outcomes(), may_speak=out is None
            )
        except Exception:
            pom = None
        if out is None and pom:
            return {"context": POMODORO_INSTRUCTION + pom["text"]}
        return out

    def _bedtime_or_other():
        """The wind-down if one is due, else the other moments, else None."""
        try:
            due = _winddown.should_nudge(recent=_storage.recent_outcomes())
            if not due:
                return _other_moments()
            _storage.record_nudge(due["night"], due["rung"])

            # The OS notification can only be posted from the Desktop half
            # (ctx.os is a Desktop SDK door, not a Python one), so broadcast
            # the moment and let desktop/plugin.js call ctx.os.notify. The
            # conversation block below is delivered regardless: the Desktop
            # may not be running, and the SDK only shows OS notifications
            # while the user is away from Hermes.
            if _goals.get_goals().get("nudge_delivery") in ("notify", "both"):
                try:
                    from hermes_cli.plugin_events import (  # noqa: PLC0415
                        broadcast_plugin_event,
                    )

                    broadcast_plugin_event(
                        "kairos",
                        "nudge.due",
                        {
                            "night": due["night"],
                            "rung": due["rung"],
                            "bedtime": (due.get("target") or {}).get("bedtime"),
                        },
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

    def on_session_end(**kwargs):
        """Once per turn: how the agent handed back. Stop is a human action."""
        if not _note_session(kwargs) or not _session_is_human(kwargs.get("session_id")):
            return
        try:
            now = _now_ts()
            tid = kwargs.get("turn_id")
            started = _turn_started.pop(tid, None) if tid else None
            _pomodoro.on_turn_end(
                now,
                completed=bool(kwargs.get("completed")),
                interrupted=bool(kwargs.get("interrupted")),
                failed=bool(kwargs.get("failed")),
                calls=_turn_calls.pop(tid, 0) if tid else 0,
                turn_min=int((now - started) // 60) if started else 0,
            )
        except Exception:
            pass

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
    ctx.register_hook("on_session_end", on_session_end)
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
