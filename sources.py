"""Read last night's sleep from whatever health source the user already runs.

Hypnos deliberately writes no vendor integrations. Hermes plugins can call a
configured MCP server through ``ctx.call_mcp``, gated by a per-plugin,
per-server allowlist the operator sets in ``config.yaml``. Several health MCP
servers already exist in the Hermes catalog, so one lenient reader covers all
of them: the user grants a server, names a tool, and sleep arrives.

Every server returns a different shape, so the parser is deliberately
forgiving about field names and units rather than pretending there is a
standard. ``probe()`` exists because the honest first step is always "show me
what your server actually returned".
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
from typing import Any, Optional

# Presets for the health MCP servers currently in the Hermes catalog. These
# are starting points, not promises — tool names change, so probe() is the
# authority on any given install.
PRESETS: dict[str, dict[str, Any]] = {
    "athletedata": {
        "tool": "get_sleep",
        "args": {"days": 7},
        "note": "Garmin / Oura / WHOOP and ~35 more, via their hosted MCP.",
    },
    "apple-health-mcp": {
        "tool": "query",
        "args": {"sql": "SELECT * FROM sleep ORDER BY startDate DESC LIMIT 14"},
        "note": "Reads a local Apple Health export; tool is usually SQL-shaped.",
    },
    "healthrelay": {
        "tool": "get_sleep_data",
        "args": {"days": 7},
        "note": "Apple Health through a receiver you host yourself.",
    },
    "health-data": {
        "tool": "health_query",
        "args": {"metric": "sleep", "days": 7},
        "note": "Local health store with its own query tools.",
    },
}

# Field aliases, longest-specific first. Keys whose unit we know for certain
# are resolved by name; anything ambiguous falls back to _coerce_minutes.
_DATE_KEYS = (
    "night", "day", "date", "calendar_date", "calendarDate", "summary_date",
    "dateOfSleep", "start_date", "startDate", "bedtime_start", "start",
)
_DUR_SECONDS = ("total_sleep_duration", "asleep_duration", "duration_seconds", "sleep_duration_seconds")
_DUR_MINUTES = ("duration_min", "minutes_asleep", "minutesAsleep", "duration_minutes", "asleep_minutes")
_DUR_AMBIG = ("duration", "total_sleep", "sleep_duration", "time_asleep", "value")
_WAKE_KEYS = ("wake_count", "awake_count", "numberOfAwakenings", "awakeningsCount", "wakeups", "awakenings")
_START_KEYS = ("sleep_start", "bedtime_start", "startDate", "start_time", "start")
_END_KEYS = ("sleep_end", "bedtime_end", "endDate", "end_time", "end")
_LIST_KEYS = ("data", "records", "nights", "results", "items", "sleep", "sessions", "entries")


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def _parse_date(v: Any) -> Optional[str]:
    """Pull an ISO date out of a date, datetime or timestamp."""
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


def _epoch(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 1_000_000_000 else None
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (None,):  # fromisoformat handles the common cases
        try:
            return _dt.datetime.fromisoformat(s).timestamp()
        except (ValueError, TypeError):
            break
    return None


def _coerce_minutes(raw: Any) -> Optional[int]:
    """Best-effort minutes from an unlabelled duration.

    Over 1440 cannot be minutes (that is more than a day), so it is seconds.
    Values that look like hours (<= 24) are scaled up. Everything between is
    taken at face value as minutes.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        m = _re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", s, _re.I)
        if m and (m.group(1) or m.group(2)):
            return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
        m = _re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        try:
            raw = float(s)
        except ValueError:
            return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v > 1440:          # must be seconds
        return int(round(v / 60.0))
    if v <= 24:           # must be hours
        return int(round(v * 60))
    return int(round(v))


def extract_nights(payload: Any) -> list[dict[str, Any]]:
    """Find sleep rows in an arbitrary MCP response. Never raises."""
    rows: list[dict[str, Any]] = []
    try:
        rows = _collect(payload)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        night = _parse_date(_first(r, _DATE_KEYS))
        if not night or night in seen:
            continue

        dur = None
        v = _first(r, _DUR_SECONDS)
        if v is not None:
            try:
                dur = int(round(float(v) / 60.0))
            except (TypeError, ValueError):
                dur = None
        if dur is None:
            v = _first(r, _DUR_MINUTES)
            if v is not None:
                try:
                    dur = int(round(float(v)))
                except (TypeError, ValueError):
                    dur = None
        if dur is None:
            dur = _coerce_minutes(_first(r, _DUR_AMBIG))

        start, end = _epoch(_first(r, _START_KEYS)), _epoch(_first(r, _END_KEYS))
        if dur is None and start and end and end > start:
            dur = int(round((end - start) / 60.0))
        if dur is None or not 30 <= dur <= 1080:
            continue  # implausible, or no duration at all

        wake = _first(r, _WAKE_KEYS)
        try:
            wake = int(wake) if wake is not None else None
        except (TypeError, ValueError):
            wake = None

        seen.add(night)
        out.append({
            "night": night,
            "duration_min": dur,
            "sleep_start": start,
            "sleep_end": end,
            "wake_count": wake,
        })
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
        if _parse_date(_first(payload, _DATE_KEYS)):
            return [payload]       # a single night
        found = []
        for v in payload.values():
            if isinstance(v, (dict, list)):
                found.extend(_collect(v, depth + 1))
        return found
    return []


def fetch(ctx: Any, server: str, tool: str, args: Optional[dict] = None,
          timeout: float = 30) -> dict[str, Any]:
    """Call the MCP tool and parse it. Returns a result envelope, never raises."""
    if not hasattr(ctx, "call_mcp"):
        return {"ok": False, "error": "This Hermes build has no ctx.call_mcp."}
    try:
        res = ctx.call_mcp(server, tool, args or {}, timeout=timeout)
    except PermissionError as exc:
        return {
            "ok": False,
            "error": (
                f"Not allowed to call MCP server '{server}'. Grant it in "
                f"config.yaml under plugins.entries.hypnos.mcp_allowlist, then "
                f"retry. ({exc})"
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if not isinstance(res, dict) or not res.get("ok"):
        err = res.get("error") if isinstance(res, dict) else str(res)
        return {"ok": False, "error": f"MCP server returned an error: {err}"}

    payload = res.get("structuredContent") or res.get("result")
    nights = extract_nights(payload)
    return {
        "ok": True,
        "nights": nights,
        "truncated": bool(res.get("truncated")),
        "raw_preview": _preview(payload),
    }


def _preview(payload: Any, limit: int = 600) -> str:
    try:
        s = payload if isinstance(payload, str) else _json.dumps(payload, default=str)
    except Exception:
        s = str(payload)
    return s[:limit] + ("…" if len(s) > limit else "")
