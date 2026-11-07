"""Activity sensor — derive daily work-pattern features from Hermes's own session store.

Read-only. Opens `state.db` with `mode=ro` and never writes to it.
This is the half of Hypnos that makes it unusual: the agent's own
telemetry becomes a lifestyle sensor.
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import os
import sqlite3
from typing import Any, Optional

# Local hour at which "late" starts accruing.
LATE_HOUR = 23

# A night is attributed to the day you went to bed, so activity after
# midnight belongs to the previous calendar day.
NIGHT_ROLLOVER_HOUR = 5


def _state_db_path() -> str:
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    return os.path.join(home, "state.db")


def _open_ro() -> Optional[sqlite3.Connection]:
    path = _state_db_path()
    if not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return None


def night_of(ts: float) -> str:
    """Which night does this timestamp belong to?

    03:00 Tuesday is still Monday night. Without this every late session
    lands on the wrong day and the correlation is garbage.
    """
    d = _dt.datetime.fromtimestamp(ts)
    if d.hour < NIGHT_ROLLOVER_HOUR:
        d -= _dt.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _late_minutes(timestamps: list[float]) -> int:
    """Minutes of activity falling after LATE_HOUR, counting post-midnight."""
    if not timestamps:
        return 0
    latest = max(timestamps)
    d = _dt.datetime.fromtimestamp(latest)
    if d.hour < NIGHT_ROLLOVER_HOUR:
        # after midnight: minutes since 23:00 the previous evening
        return (d.hour + 24 - LATE_HOUR) * 60 + d.minute
    if d.hour >= LATE_HOUR:
        return (d.hour - LATE_HOUR) * 60 + d.minute
    return 0


def _is_error(result: Any) -> bool:
    if not isinstance(result, str):
        return False
    low = result[:400].lower()
    return any(
        k in low
        for k in ('"success": false', "traceback", "command not found", "error:", "failed")
    )


def scan_state_db(days: int = 90) -> dict[str, dict[str, Any]]:
    """Return {night: features} derived from state.db.

    Degrades to {} when state.db is absent or unreadable — the plugin must
    never hard-fail because the host's session store moved.
    """
    con = _open_ro()
    if con is None:
        return {}

    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).timestamp()
    per_night: dict[str, dict[str, Any]] = {}
    buckets: dict[str, list[float]] = collections.defaultdict(list)
    tool_mix: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )

    try:
        rows = con.execute(
            "SELECT session_id, timestamp, role, tool_name "
            "FROM messages WHERE timestamp IS NOT NULL AND timestamp >= ? "
            "ORDER BY timestamp",
            (cutoff,),
        ).fetchall()
    except sqlite3.Error:
        con.close()
        return {}

    sessions_seen: dict[str, set] = collections.defaultdict(set)

    for session_id, ts, _role, tool_name in rows:
        n = night_of(ts)
        rec = per_night.setdefault(
            n,
            {
                "message_count": 0,
                "tool_calls": 0,
                "terminal_calls": 0,
                "session_count": 0,
            },
        )
        rec["message_count"] += 1
        buckets[n].append(ts)
        if session_id:
            sessions_seen[n].add(session_id)
        if tool_name:
            rec["tool_calls"] += 1
            tool_mix[n][tool_name] += 1
            if tool_name in ("terminal", "execute_code"):
                rec["terminal_calls"] += 1

    con.close()

    for n, rec in per_night.items():
        stamps = buckets[n]
        rec["first_activity"] = min(stamps) if stamps else None
        rec["last_activity"] = max(stamps) if stamps else None
        rec["late_minutes"] = _late_minutes(stamps)
        rec["session_count"] = len(sessions_seen[n])
        rec["tool_mix_json"] = json.dumps(dict(tool_mix[n].most_common(12)))
        rec["error_results"] = 0  # live hook fills this; state.db has no result text

    return per_night


def sync_activity(days: int = 90) -> int:
    """Refresh the plugin's own activity table from state.db. Returns rows touched."""
    from . import storage  # noqa: PLC0415

    found = scan_state_db(days=days)
    con = storage.connect()
    for night, rec in found.items():
        con.execute(
            """
            INSERT INTO activity (day, first_activity, last_activity, session_count,
                                  message_count, tool_calls, late_minutes,
                                  terminal_calls, error_results, tool_mix_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                first_activity = MIN(COALESCE(activity.first_activity, excluded.first_activity),
                                     excluded.first_activity),
                last_activity  = MAX(COALESCE(activity.last_activity, excluded.last_activity),
                                     excluded.last_activity),
                session_count  = MAX(activity.session_count, excluded.session_count),
                message_count  = MAX(activity.message_count, excluded.message_count),
                tool_calls     = MAX(activity.tool_calls, excluded.tool_calls),
                late_minutes   = MAX(activity.late_minutes, excluded.late_minutes),
                terminal_calls = MAX(activity.terminal_calls, excluded.terminal_calls),
                tool_mix_json  = excluded.tool_mix_json,
                updated_at     = excluded.updated_at
            """,
            (
                night,
                rec.get("first_activity"),
                rec.get("last_activity"),
                rec.get("session_count", 0),
                rec.get("message_count", 0),
                rec.get("tool_calls", 0),
                rec.get("late_minutes", 0),
                rec.get("terminal_calls", 0),
                0,
                rec.get("tool_mix_json"),
                _dt.datetime.now().timestamp(),
            ),
        )
    con.commit()
    return len(found)


def hour_histogram(days: int = 90) -> dict[int, int]:
    """Messages per local hour-of-day. The 'you are a 3am person' chart."""
    con = _open_ro()
    if con is None:
        return {}
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).timestamp()
    try:
        rows = con.execute(
            "SELECT timestamp FROM messages WHERE timestamp IS NOT NULL AND timestamp >= ?",
            (cutoff,),
        ).fetchall()
    except sqlite3.Error:
        con.close()
        return {}
    con.close()
    hist = collections.Counter(
        _dt.datetime.fromtimestamp(r[0]).hour for r in rows
    )
    return {h: hist.get(h, 0) for h in range(24)}
