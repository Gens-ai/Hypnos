"""One normalizer and one write path, shared by every sleep bridge.

Every source Hypnos will ever read \u2014 a CSV, an MCP health server, a
Gadgetbridge SQLite export, some future vendor API \u2014 ends with the same
question: is this a plausible night, and may it overwrite what the user
already told us? Answering that in each adapter is how the CSV importer
ended up silently clobbering hand-logged nights while the MCP path
protected them, and how the plausibility bound drifted to 1000 in one
place and 1080 in the other.

So the rules live here, once:

* field aliases and unit coercion   -> ``normalize_night``
* the lenient walker for JSON-ish payloads -> ``extract_nights``
* plausibility, dedupe, provenance, manual protection -> ``ingest``

An adapter's only job is to locate its data and hand back dicts. It never
writes, never validates, and never decides whose number wins.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
from typing import Any, Optional

from . import storage as _storage

# A night shorter than this is a nap or a glitch; longer is a device that
# forgot to stop recording. One pair of numbers, used by every source.
MIN_SLEEP_MIN = 30
MAX_SLEEP_MIN = 1080  # 18h

# Field aliases. Keys whose unit is unambiguous are resolved by name;
# anything else falls back to coerce_minutes.
DATE_KEYS = (
    "night", "day", "date", "calendar_date", "calendarDate", "summary_date",
    "dateOfSleep", "start_date", "startDate", "bedtime_start", "start",
)
DUR_SECONDS = (
    "total_sleep_duration", "asleep_duration", "duration_seconds",
    "sleep_duration_seconds",
)
DUR_MINUTES = (
    "duration_min", "minutes_asleep", "minutesAsleep", "duration_minutes",
    "asleep_minutes",
)
DUR_AMBIG = ("duration", "total_sleep", "sleep_duration", "time_asleep", "value")
DUR_HOURS = ("duration_hours", "duration_h", "hours", "hours_asleep", "sleep_hours")
WAKE_KEYS = (
    "wake_count", "awake_count", "numberOfAwakenings", "awakeningsCount",
    "wakeups", "awakenings",
)
QUALITY_KEYS = ("quality", "score", "sleep_score")
START_KEYS = ("sleep_start", "bedtime_start", "startDate", "start_time", "start")
END_KEYS = ("sleep_end", "bedtime_end", "endDate", "end_time", "end")
_LIST_KEYS = (
    "data", "records", "nights", "results", "items", "sleep", "sessions", "entries",
)


def first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def parse_date(v: Any) -> Optional[str]:
    """Pull an ISO date out of a date, datetime or epoch timestamp."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and v > 1_000_000_000:
        return _dt.datetime.fromtimestamp(float(v)).strftime("%Y-%m-%d")
    s = str(v)
    m = _re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = _re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return None


def epoch(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 1_000_000_000 else None
    try:
        return _dt.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def coerce_minutes(raw: Any) -> tuple[Optional[int], Optional[str]]:
    """Best-effort minutes from an unlabelled duration, plus any assumption.

    Returns ``(minutes, assumption)``. ``assumption`` is non-None whenever
    the unit had to be guessed from the magnitude, so the caller can report
    it instead of presenting a guess as a reading.

    Over 1440 cannot be minutes (more than a day), so it is seconds. A bare
    value at or under 24 is almost always hours in a sleep export (``6.5``,
    ``7``) but could be minutes \u2014 and reading ``12`` as a 12-hour night
    would be inventing data, so that case is flagged. Explicit formats
    (``7h20m``, ``7:20``) are unambiguous and carry no assumption.
    """
    if raw is None:
        return None, None
    if isinstance(raw, str):
        s = raw.strip()
        m = _re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", s, _re.I)
        if m and (m.group(1) or m.group(2)):
            return int(m.group(1) or 0) * 60 + int(m.group(2) or 0), None
        m = _re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2)), None
        try:
            raw = float(s)
        except ValueError:
            return None, None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None, None
    if v <= 0:
        return None, None
    if v > 1440:
        return int(round(v / 60.0)), "read as seconds"
    if v <= 24:
        return int(round(v * 60)), f"read {v:g} as hours \u2014 rename the column to " \
                                   f"duration_min if it meant minutes"
    return int(round(v)), None


def normalize_night(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """One raw record -> one canonical night, or None if it isn't one.

    Canonical shape::

        {night, duration_min, sleep_start?, sleep_end?, wake_count?,
         quality?, extra?}
    """
    if not isinstance(row, dict):
        return None
    night = parse_date(first(row, DATE_KEYS))
    if not night:
        return None

    dur = None
    assumption = None
    v = first(row, DUR_SECONDS)
    if v is not None:
        try:
            dur = int(round(float(v) / 60.0))
        except (TypeError, ValueError):
            dur = None
    if dur is None:
        v = first(row, DUR_MINUTES)
        if v is not None:
            try:
                dur = int(round(float(v)))
            except (TypeError, ValueError):
                dur = None
    if dur is None:
        v = first(row, DUR_HOURS)
        if v is not None:
            try:
                dur = int(round(float(v) * 60))
            except (TypeError, ValueError):
                dur = None
    if dur is None:
        dur, assumption = coerce_minutes(first(row, DUR_AMBIG))

    start, end = epoch(first(row, START_KEYS)), epoch(first(row, END_KEYS))
    if dur is None and start and end and end > start:
        dur = int(round((end - start) / 60.0))
    if dur is None:
        return None

    wake = first(row, WAKE_KEYS)
    try:
        wake = int(wake) if wake is not None else None
    except (TypeError, ValueError):
        wake = None

    qual = first(row, QUALITY_KEYS)
    try:
        q = int(float(qual)) if qual is not None else None
        qual = q if q is not None and 1 <= q <= 5 else None
    except (TypeError, ValueError):
        qual = None

    out = {
        "night": night,
        "duration_min": dur,
        "sleep_start": start,
        "sleep_end": end,
        "wake_count": wake,
        "quality": qual,
    }
    if assumption:
        out["assumed"] = assumption
    if isinstance(row.get("extra"), dict):
        out["extra"] = row["extra"]
    return out


def extract_nights(payload: Any) -> list[dict[str, Any]]:
    """Find and normalize sleep rows in an arbitrary payload. Never raises."""
    try:
        rows = _collect(payload)
    except Exception:
        return []
    out, seen = [], set()
    for r in rows:
        n = normalize_night(r) if isinstance(r, dict) else None
        if not n or n["night"] in seen:
            continue
        if not MIN_SLEEP_MIN <= n["duration_min"] <= MAX_SLEEP_MIN:
            continue
        seen.add(n["night"])
        out.append(n)
    return sorted(out, key=lambda r: r["night"])


def _collect(payload: Any, depth: int = 0) -> list[Any]:
    """Walk a response looking for the list of per-night records."""
    if depth > 6:
        return []
    if isinstance(payload, str):
        s = payload.strip()
        if s.startswith(("{", "[")):
            try:
                return _collect(_json.loads(s), depth + 1)
            except ValueError:
                return []
        return []
    if isinstance(payload, list):
        if payload and all(isinstance(x, dict) for x in payload):
            return payload
        found: list[Any] = []
        for item in payload:
            found.extend(_collect(item, depth + 1))
        return found
    if isinstance(payload, dict):
        # MCP content-block envelope: {"content": [{"type":"text","text":"..."}]}
        if "content" in payload and isinstance(payload["content"], list):
            found = []
            for block in payload["content"]:
                if isinstance(block, dict) and "text" in block:
                    found.extend(_collect(block["text"], depth + 1))
                else:
                    found.extend(_collect(block, depth + 1))
            if found:
                return found
        for k in _LIST_KEYS:
            if isinstance(payload.get(k), list):
                got = _collect(payload[k], depth + 1)
                if got:
                    return got
        if parse_date(first(payload, DATE_KEYS)):
            return [payload]
        found = []
        for v in payload.values():
            if isinstance(v, (dict, list)):
                found.extend(_collect(v, depth + 1))
        return found
    return []


def ingest(
    nights: list[dict[str, Any]],
    source: str,
    *,
    protect_manual: bool = True,
) -> dict[str, Any]:
    """The single write path. Every bridge goes through here.

    ``protect_manual`` defaults to **True** for every automated source, so
    no importer can quietly overwrite a night the user entered themselves.
    Disagreements come back as ``conflicts`` for the user to settle; they
    are never resolved silently in the device's favour.
    """
    added = updated = skipped = rejected = 0
    conflicts: list[dict[str, Any]] = []
    assumed: list[dict[str, Any]] = []
    for n in nights:
        dur = n.get("duration_min")
        if not isinstance(dur, int) or not MIN_SLEEP_MIN <= dur <= MAX_SLEEP_MIN:
            rejected += 1
            continue
        if n.get("assumed"):
            assumed.append({"night": n["night"], "minutes": dur,
                            "assumption": n["assumed"]})
        out = _storage.upsert_sleep(
            n["night"],
            dur,
            sleep_start=n.get("sleep_start"),
            sleep_end=n.get("sleep_end"),
            wake_count=n.get("wake_count"),
            quality=n.get("quality"),
            source=source,
            note=n.get("note"),
            protect_manual=protect_manual,
        )
        if out["status"] == "inserted":
            added += 1
        elif out["status"] == "updated":
            updated += 1
        else:
            skipped += 1
            prev = out.get("previous") or {}
            if prev.get("duration_min") != dur:
                conflicts.append({
                    "night": n["night"],
                    "you_logged_min": prev.get("duration_min"),
                    "device_says_min": dur,
                })
    return {
        "added": added,
        "updated": updated,
        "skipped_you_logged_these": skipped,
        "rejected_implausible": rejected,
        "conflicts": conflicts,
        # A guessed unit is reported, never presented as a reading. If this
        # list is non-empty the user should look before trusting the numbers.
        "assumed_units": assumed,
        "nights_logged": _storage.sleep_count(),
    }
