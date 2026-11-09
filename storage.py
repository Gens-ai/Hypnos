"""Kairos storage — schema + accessors.

All state lives in the per-plugin data root so it survives
`hermes plugins update` / `remove` and follows the active profile.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any, Optional

PLUGIN_NAME = "kairos"

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

-- The user's own targets. There is no normative "correct" bedtime here;
-- 02:30 is as valid as 22:00. Only the user sets these.
CREATE TABLE IF NOT EXISTS goals (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Obligations that move a specific night's target: an early flight, a
-- 7am standup, a race. The agent works backwards from the wake time.
CREATE TABLE IF NOT EXISTS commitments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    on_date    TEXT NOT NULL,      -- ISO date of the obligation
    wake_by    TEXT NOT NULL,      -- 'HH:MM' the user must be up
    label      TEXT,
    prep_days  INTEGER NOT NULL DEFAULT 1,   -- nights to ease the shift over
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS commitments_date ON commitments(on_date);

-- One nudge per rung per night for the early rungs; 'past' may repeat on
-- the user's chosen interval. Multiple rows per rung are allowed, so the
-- gate is a count plus a cooldown rather than a primary-key collision.
CREATE TABLE IF NOT EXISTS nudge_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    night  TEXT NOT NULL,
    rung   TEXT NOT NULL,
    at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS nudge_log_night ON nudge_log(night);

-- A nudge that came due while work was mid-flight waits here for a natural
-- stopping point, up to the user's patience window.
CREATE TABLE IF NOT EXISTS nudge_pending (
    night TEXT NOT NULL,
    rung  TEXT NOT NULL,
    since REAL NOT NULL,
    PRIMARY KEY (night, rung)
);

-- 'not tonight' mute, honoured without comment.
CREATE TABLE IF NOT EXISTS snooze (
    night TEXT PRIMARY KEY,
    at    REAL NOT NULL
);

-- Morning check-in answers.
CREATE TABLE IF NOT EXISTS checkins (
    night     TEXT PRIMARY KEY,
    asked_at  REAL,
    answered_at REAL,
    answer    TEXT
);
"""


def connect() -> sqlite3.Connection:
    """Open the plugin's own SQLite database via the sanctioned helper."""
    from plugins.plugin_storage import plugin_db  # noqa: PLC0415

    con = plugin_db(PLUGIN_NAME)
    con.executescript(_SCHEMA)
    _migrate(con)
    con.commit()
    return con


def _migrate(con: sqlite3.Connection) -> None:
    """Bring an older nudge_log (PK night+rung, no id) up to the new shape."""
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info('nudge_log')")}
    except sqlite3.Error:
        return
    if not cols or "id" in cols:
        return
    try:
        con.executescript(
            """
            ALTER TABLE nudge_log RENAME TO nudge_log_old;
            CREATE TABLE nudge_log (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                night  TEXT NOT NULL,
                rung   TEXT NOT NULL,
                at     REAL NOT NULL
            );
            INSERT INTO nudge_log (night, rung, at)
                SELECT night, rung, at FROM nudge_log_old;
            DROP TABLE nudge_log_old;
            CREATE INDEX IF NOT EXISTS nudge_log_night ON nudge_log(night);
            """
        )
        con.commit()
    except sqlite3.Error:
        pass


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
    protect_manual: bool = False,
) -> dict[str, Any]:
    """Write a night. Returns {status, previous} rather than silently winning.

    ``protect_manual`` is for automated importers: a wearable must never
    overwrite something you told Kairos yourself. You know whether you lay
    awake for an hour; the watch is guessing. The incoming row is reported as
    skipped, with the disagreement, so the caller can surface it.
    """
    con = connect()
    row = con.execute(
        "SELECT duration_min, source FROM sleep WHERE night = ?", (night,)
    ).fetchone()
    previous = {"duration_min": row[0], "source": row[1]} if row else None

    if protect_manual and previous and previous["source"] in ("manual", "csv"):
        return {"status": "skipped_manual", "previous": previous}

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
            quality      = COALESCE(excluded.quality, sleep.quality),
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
    return {
        "status": "updated" if previous else "inserted",
        "previous": previous,
    }


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


# ------------------------------------------------- nudges, snooze, check-ins


def nudge_already_fired(night: str, rung: str) -> bool:
    return nudge_count(night, rung) > 0


def nudge_count(night: str, rung: str) -> int:
    con = connect()
    row = con.execute(
        "SELECT COUNT(*) FROM nudge_log WHERE night = ? AND rung = ?", (night, rung)
    ).fetchone()
    return int(row[0]) if row else 0


def last_nudge_at(night: str) -> Optional[float]:
    """When any nudge last fired tonight — the cooldown anchor."""
    con = connect()
    row = con.execute(
        "SELECT MAX(at) FROM nudge_log WHERE night = ?", (night,)
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def record_nudge(night: str, rung: str) -> None:
    con = connect()
    con.execute(
        "INSERT INTO nudge_log (night, rung, at) VALUES (?, ?, ?)",
        (night, rung, _dt.datetime.now().timestamp()),
    )
    con.execute(
        "DELETE FROM nudge_pending WHERE night = ? AND rung = ?", (night, rung)
    )
    con.commit()


def pending_since(night: str, rung: str) -> Optional[float]:
    """When this rung first came due while work was mid-flight."""
    con = connect()
    row = con.execute(
        "SELECT since FROM nudge_pending WHERE night = ? AND rung = ?", (night, rung)
    ).fetchone()
    return float(row[0]) if row else None


def mark_pending(night: str, rung: str, since: float) -> None:
    con = connect()
    con.execute(
        "INSERT OR IGNORE INTO nudge_pending (night, rung, since) VALUES (?, ?, ?)",
        (night, rung, since),
    )
    con.commit()


def clear_pending(night: str, rung: str) -> None:
    con = connect()
    con.execute(
        "DELETE FROM nudge_pending WHERE night = ? AND rung = ?", (night, rung)
    )
    con.commit()


def is_snoozed(night: str) -> bool:
    con = connect()
    row = con.execute("SELECT 1 FROM snooze WHERE night = ?", (night,)).fetchone()
    return row is not None


def snooze_night(night: str) -> None:
    """'not tonight' — honoured without comment or follow-up."""
    con = connect()
    con.execute(
        "INSERT OR REPLACE INTO snooze (night, at) VALUES (?, ?)",
        (night, _dt.datetime.now().timestamp()),
    )
    con.commit()


def record_checkin(night: str, *, asked: bool = False, answer: Optional[str] = None) -> None:
    con = connect()
    now = _dt.datetime.now().timestamp()
    if asked:
        con.execute(
            "INSERT INTO checkins (night, asked_at) VALUES (?, ?) "
            "ON CONFLICT(night) DO UPDATE SET asked_at = excluded.asked_at",
            (night, now),
        )
    if answer is not None:
        con.execute(
            "INSERT INTO checkins (night, answered_at, answer) VALUES (?, ?, ?) "
            "ON CONFLICT(night) DO UPDATE SET "
            "answered_at = excluded.answered_at, answer = excluded.answer",
            (night, now, answer),
        )
    con.commit()


def last_checkin() -> Optional[dict[str, Any]]:
    con = connect()
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM checkins ORDER BY night DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


# ------------------------------------------------- stop-state ring buffer

# In-process only: the last few tool outcomes, used to tell whether the user
# is at a natural break. Deliberately NOT persisted — it is transient
# context for one decision, not a record of anyone's work.
_OUTCOMES: list[dict[str, Any]] = []
_OUTCOMES_MAX = 12


def record_outcome(tool_name: str, error: bool) -> None:
    _OUTCOMES.append(
        {"tool": tool_name, "error": bool(error), "at": _dt.datetime.now().timestamp()}
    )
    del _OUTCOMES[:-_OUTCOMES_MAX]


def recent_outcomes() -> list[dict[str, Any]]:
    return list(_OUTCOMES)


# ------------------------------------------------------------- handoff


def write_handoff(night: str, summary: str) -> str:
    """Save where the work got to, so stopping costs nothing."""
    from plugins.plugin_storage import plugin_data_dir  # noqa: PLC0415

    d = plugin_data_dir(PLUGIN_NAME) / "handoffs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{night}.md"
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# Where we left off — {night}\n\nSaved {stamp}.\n\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(header if not path.stat().st_size else f"\n---\n\nSaved {stamp}.\n\n")
        fh.write(summary.rstrip() + "\n")
    return str(path)


def read_handoff(night: str) -> Optional[str]:
    from plugins.plugin_storage import plugin_data_dir  # noqa: PLC0415

    path = plugin_data_dir(PLUGIN_NAME) / "handoffs" / f"{night}.md"
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
