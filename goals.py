"""Goals, commitments and per-night target resolution.

Design rule that governs this whole module: **there is no correct bedtime.**
A 02:30 target is as legitimate as a 22:00 one. Many people who use Hermes
have no boss and no clock-in, and shifting your whole day later is a valid
way to live. Hypnos only ever measures you against the target *you* set.

What it does care about:
  * hitting your own target
  * consistency (variance hurts more than lateness)
  * obligations that genuinely require an early start, eased in over days
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from . import storage as _storage

TONES = ("off", "gentle", "encouraging", "firm", "guardian")

DEFAULTS: dict[str, str] = {
    # No target until the user sets one — we refuse to invent a bedtime.
    "target_bedtime": "",
    "target_duration_min": "450",  # 7h30, used only once a bedtime exists
    "goal_bedtime": "",            # where they eventually want to land
    "ramp_min_per_week": "15",
    "ramp_started": "",
    "tone": "gentle",
    "nudge_delivery": "inject",    # inject | notify | both
    "checkin_enabled": "false",
    "checkin_time": "10:00",
    "checkin_channel": "desktop",  # desktop | <messaging target>
    "track_open_threads": "true",
}


def get_goals() -> dict[str, str]:
    con = _storage.connect()
    rows = con.execute("SELECT key, value FROM goals").fetchall()
    g = dict(DEFAULTS)
    g.update({k: v for k, v in rows})
    return g


def set_goals(**kwargs: Any) -> dict[str, str]:
    con = _storage.connect()
    for k, v in kwargs.items():
        if v is None or k not in DEFAULTS:
            continue
        con.execute(
            "INSERT INTO goals (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, str(v).lower() if isinstance(v, bool) else str(v)),
        )
    con.commit()
    return get_goals()


# ------------------------------------------------------------ commitments


def add_commitment(
    on_date: str, wake_by: str, label: str = "", prep_days: int = 1
) -> int:
    con = _storage.connect()
    cur = con.execute(
        "INSERT INTO commitments (on_date, wake_by, label, prep_days, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (on_date, wake_by, label, max(0, int(prep_days)), _dt.datetime.now().timestamp()),
    )
    con.commit()
    return int(cur.lastrowid or 0)


def list_commitments(upcoming_only: bool = True) -> list[dict[str, Any]]:
    import sqlite3  # noqa: PLC0415

    con = _storage.connect()
    con.row_factory = sqlite3.Row
    if upcoming_only:
        today = _dt.date.today().isoformat()
        rows = con.execute(
            "SELECT * FROM commitments WHERE on_date >= ? ORDER BY on_date", (today,)
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM commitments ORDER BY on_date").fetchall()
    return [dict(r) for r in rows]


def remove_commitment(cid: int) -> bool:
    con = _storage.connect()
    cur = con.execute("DELETE FROM commitments WHERE id = ?", (int(cid),))
    con.commit()
    return cur.rowcount > 0


# ------------------------------------------------------- target resolution


def _parse_hhmm(s: str) -> Optional[tuple[int, int]]:
    try:
        h, m = s.split(":")
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return None


def _ramped_bedtime(g: dict[str, str]) -> Optional[str]:
    """Walk the target gradually from target_bedtime toward goal_bedtime.

    Shifting a sleep schedule abruptly does not work; ~15 min/week does.
    The agent owns the ramp so the user never has to do the arithmetic.
    """
    cur = _parse_hhmm(g.get("target_bedtime", ""))
    goal = _parse_hhmm(g.get("goal_bedtime", ""))
    started = g.get("ramp_started", "")
    if not cur or not goal or not started:
        return g.get("target_bedtime") or None
    try:
        start = _dt.date.fromisoformat(started)
    except ValueError:
        return g.get("target_bedtime") or None

    weeks = max(0, (_dt.date.today() - start).days / 7.0)
    per_week = float(g.get("ramp_min_per_week") or 15)
    shift = int(weeks * per_week)

    cur_min = cur[0] * 60 + cur[1]
    goal_min = goal[0] * 60 + goal[1]
    # Work in signed deltas on a 24h circle, choosing the shorter arc.
    delta = (goal_min - cur_min + 720) % 1440 - 720
    moved = max(-abs(delta), min(abs(delta), shift)) * (1 if delta >= 0 else -1)
    now_min = (cur_min + moved) % 1440
    return f"{now_min // 60:02d}:{now_min % 60:02d}"


def resolve_target(night: str) -> dict[str, Any]:
    """The bedtime that applies to one night, and why.

    Returns source='none' when the user has set no target. In that case
    Hypnos stays silent — it will not invent a bedtime for someone.
    """
    g = get_goals()
    duration = int(g.get("target_duration_min") or 450)

    base = _ramped_bedtime(g)
    out: dict[str, Any] = {
        "night": night,
        "bedtime": base,
        "duration_min": duration,
        "source": "goal" if base else "none",
        "reason": "",
        "tone": g.get("tone", "gentle"),
    }
    if not base:
        out["reason"] = "No target set. Hypnos stays quiet until you choose one."
        return out

    # An obligation the next morning overrides the night's target.
    try:
        night_d = _dt.date.fromisoformat(night)
    except ValueError:
        return out

    for c in list_commitments(upcoming_only=False):
        try:
            cd = _dt.date.fromisoformat(c["on_date"])
        except ValueError:
            continue
        wake = _parse_hhmm(c["wake_by"])
        if not wake:
            continue
        lead = (cd - night_d).days
        prep = max(1, int(c.get("prep_days") or 1))
        # lead == 1 is the night you must actually sleep to make the wake time.
        # lead == 0 is the night *after* the obligation — it no longer applies.
        # lead 2..prep ease the shift in beforehand.
        if lead < 1 or lead > prep:
            continue

        # Work backwards: bedtime = wake - duration, eased across prep nights.
        wake_min = wake[0] * 60 + wake[1]
        needed = (wake_min - duration) % 1440
        cur = _parse_hhmm(base)
        cur_min = cur[0] * 60 + cur[1] if cur else needed
        delta = (needed - cur_min + 720) % 1440 - 720
        frac = (prep - lead + 1) / prep
        shifted = int(round(cur_min + delta * frac)) % 1440
        out["bedtime"] = f"{shifted // 60:02d}:{shifted % 60:02d}"
        out["source"] = "commitment"
        label = c.get("label") or "an early start"
        out["reason"] = (
            f"{label} on {c['on_date']} needs you up by {c['wake_by']}"
            + (
                ""
                if lead == 1
                else f" — easing in, {lead - 1} night(s) before the one that counts"
            )
        )
        break

    return out


def consistency(sleep_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Spread of sleep onset. Variance matters more than earliness."""
    starts = []
    for r in sleep_rows:
        ts = r.get("sleep_start")
        if not ts:
            continue
        d = _dt.datetime.fromtimestamp(ts)
        m = d.hour * 60 + d.minute
        # Centre the circle on 03:00 so late nights don't wrap badly.
        starts.append((m - 180) % 1440)
    if len(starts) < 3:
        return {"n": len(starts), "verdict": "INSUFFICIENT_EVIDENCE"}
    mean = sum(starts) / len(starts)
    var = sum((s - mean) ** 2 for s in starts) / len(starts)
    sd = var ** 0.5
    return {
        "n": len(starts),
        "sd_minutes": round(sd),
        "verdict": "REPORTED",
        "note": (
            "Bedtime spread, not bedtime lateness. A consistent 02:00 beats "
            "an erratic 23:00."
        ),
    }
