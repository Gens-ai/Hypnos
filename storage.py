"""Hypnos storage — schema + accessors.

All state lives in the per-plugin data root so it survives
`hermes plugins update` / `remove` and follows the active profile.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any, Optional

PLUGIN_NAME = "hypnos"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sleep (
    night        TEXT PRIMARY KEY,   -- ISO date of the night you went to bed
    sleep_start  REAL,               -- epoch seconds, optional
    sleep_end    REAL,               -- epoch seconds, optional
    duration_min INTEGER NOT NULL,
    wake_count   INTEGER,
    quality      INTEGER,            -- 1..5 subjective, optional
    source       TEXT NOT NULL,      -- manual | gadgetbridge | csv | healthconnect
    note         TEXT,
    logged_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    day              TEXT PRIMARY KEY,   -- ISO date, local
    first_activity   REAL,
    last_activity    REAL,
    session_count    INTEGER NOT NULL DEFAULT 0,
    message_count    INTEGER NOT NULL DEFAULT 0,
    tool_calls       INTEGER NOT NULL DEFAULT 0,
    late_minutes     INTEGER NOT NULL DEFAULT 0,  -- activity minutes after 23:00
    terminal_calls   INTEGER NOT NULL DEFAULT 0,
    error_results    INTEGER NOT NULL DEFAULT 0,
    tool_mix_json    TEXT,
    updated_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS guard_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guard_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         REAL NOT NULL,
    tool_name  TEXT NOT NULL,
    action     TEXT NOT NULL,      -- block | approve | allow
    reason     TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """Open the plugin's own SQLite database via the sanctioned helper."""
    from plugins.plugin_storage import plugin_db  # noqa: PLC0415

    con = plugin_db(PLUGIN_NAME)
    con.executescript(_SCHEMA)
    con.commit()
    return con


# ---------------------------------------------------------------- sleep


def upsert_sleep(
    night: str,
    duration_min: int,
    *,
    sleep_start: Optional[float] = None,
    sleep_end: Optional[float] = None,
    wake_count: Optional[int] = None,
    quality: Optional[int] = None,
    source: str = "manual",
    note: Optional[str] = None,
) -> None:
    con = connect()
    con.execute(
        """
        INSERT INTO sleep (night, sleep_start, sleep_end, duration_min,
                           wake_count, quality, source, note, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(night) DO UPDATE SET
            sleep_start  = excluded.sleep_start,
            sleep_end    = excluded.sleep_end,
            duration_min = excluded.duration_min,
            wake_count   = excluded.wake_count,
            quality      = excluded.quality,
            source       = excluded.source,
            note         = excluded.note,
            logged_at    = excluded.logged_at
        """,
        (
            night,
            sleep_start,
            sleep_end,
            int(duration_min),
            wake_count,
            quality,
            source,
            note,
            _dt.datetime.now().timestamp(),
        ),
    )
    con.commit()


def list_sleep(limit: int = 60) -> list[dict[str, Any]]:
    con = connect()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM sleep ORDER BY night DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def sleep_count() -> int:
    return connect().execute("SELECT COUNT(*) FROM sleep").fetchone()[0]


# ------------------------------------------------------------- activity


def upsert_activity(day: str, fields: dict[str, Any]) -> None:
    """Merge-in a day's activity row. Counters accumulate, bounds widen."""
    con = connect()
    con.row_factory = sqlite3.Row
    cur = con.execute("SELECT * FROM activity WHERE day = ?", (day,)).fetchone()
    now = _dt.datetime.now().timestamp()

    if cur is None:
        con.execute(
            """
            INSERT INTO activity (day, first_activity, last_activity, session_count,
                                  message_count, tool_calls, late_minutes,
                                  terminal_calls, error_results, tool_mix_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day,
                fields.get("first_activity"),
                fields.get("last_activity"),
                fields.get("session_count", 0),
                fields.get("message_count", 0),
                fields.get("tool_calls", 0),
                fields.get("late_minutes", 0),
                fields.get("terminal_calls", 0),
                fields.get("error_results", 0),
                fields.get("tool_mix_json"),
                now,
            ),
        )
    else:
        first = [v for v in (cur["first_activity"], fields.get("first_activity")) if v]
        last = [v for v in (cur["last_activity"], fields.get("last_activity")) if v]
        con.execute(
            """
            UPDATE activity SET
                first_activity = ?, last_activity = ?,
                session_count  = session_count + ?,
                message_count  = message_count + ?,
                tool_calls     = tool_calls + ?,
                late_minutes   = MAX(late_minutes, ?),
                terminal_calls = terminal_calls + ?,
                error_results  = error_results + ?,
                tool_mix_json  = COALESCE(?, tool_mix_json),
                updated_at     = ?
            WHERE day = ?
            """,
            (
                min(first) if first else None,
                max(last) if last else None,
                fields.get("session_count", 0),
                fields.get("message_count", 0),
                fields.get("tool_calls", 0),
                fields.get("late_minutes", 0),
                fields.get("terminal_calls", 0),
                fields.get("error_results", 0),
                fields.get("tool_mix_json"),
                now,
                day,
            ),
        )
    con.commit()


def list_activity(limit: int = 60) -> list[dict[str, Any]]:
    con = connect()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM activity ORDER BY day DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- guard


_GUARD_DEFAULTS = {
    "enabled": "false",
    "quiet_start": "23:30",
    "quiet_end": "06:00",
    "mode": "approve",  # approve | block
}


def get_guard_config() -> dict[str, str]:
    con = connect()
    rows = con.execute("SELECT key, value FROM guard_config").fetchall()
    cfg = dict(_GUARD_DEFAULTS)
    cfg.update({k: v for k, v in rows})
    return cfg


def set_guard_config(**kwargs: Any) -> dict[str, str]:
    con = connect()
    for k, v in kwargs.items():
        if v is None or k not in _GUARD_DEFAULTS:
            continue
        con.execute(
            "INSERT INTO guard_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, str(v).lower() if isinstance(v, bool) else str(v)),
        )
    con.commit()
    return get_guard_config()


def record_guard_event(tool_name: str, action: str, reason: str) -> None:
    con = connect()
    con.execute(
        "INSERT INTO guard_events (at, tool_name, action, reason) VALUES (?, ?, ?, ?)",
        (_dt.datetime.now().timestamp(), tool_name, action, reason),
    )
    con.commit()


def recent_guard_events(limit: int = 20) -> list[dict[str, Any]]:
    con = connect()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM guard_events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
