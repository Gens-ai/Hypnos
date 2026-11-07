"""Hypnos tool handlers."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any, Optional

from . import activity as _activity
from . import analysis as _analysis
from . import storage as _storage

_DUR = re.compile(
    r"^\s*(?:(?P<h>\d+(?:\.\d+)?)\s*h)?\s*(?:(?P<m>\d+)\s*m)?\s*$", re.I
)


def _parse_duration(text: str) -> Optional[int]:
    """Accept '7h20m', '6.5h', '400m', '7:20', or a bare minute count."""
    if text is None:
        return None
    s = str(text).strip().lower()
    if not s:
        return None
    if ":" in s:
        try:
            h, m = s.split(":", 1)
            return int(float(h) * 60 + int(m))
        except ValueError:
            return None
    m = _DUR.match(s)
    if m and (m.group("h") or m.group("m")):
        total = 0.0
        if m.group("h"):
            total += float(m.group("h")) * 60
        if m.group("m"):
            total += int(m.group("m"))
        return int(total)
    try:
        return int(float(s))
    except ValueError:
        return None


def _default_night() -> str:
    """The night most likely being logged: last night."""
    now = _dt.datetime.now()
    d = now if now.hour < _activity.NIGHT_ROLLOVER_HOUR else now - _dt.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _ok(**kw: Any) -> str:
    return json.dumps({"success": True, **kw}, indent=2)


def _err(msg: str, **kw: Any) -> str:
    return json.dumps({"success": False, "error": msg, **kw}, indent=2)


# ------------------------------------------------------------- sleep_log


def sleep_log(params: dict, **_kw: Any) -> str:
    duration = _parse_duration(params.get("duration"))
    if duration is None:
        return _err(
            "Could not parse 'duration'. Try '7h20m', '6.5h', '400m' or '7:20'."
        )
    if not 30 <= duration <= 1000:
        return _err(f"Duration {duration} min is out of plausible range (30-1000).")

    night = params.get("night") or _default_night()
    try:
        _dt.datetime.strptime(night, "%Y-%m-%d")
    except ValueError:
        return _err("'night' must be an ISO date like 2026-11-07.")

    quality = params.get("quality")
    if quality is not None and not 1 <= int(quality) <= 5:
        return _err("'quality' must be 1-5.")

    _storage.upsert_sleep(
        night,
        duration,
        wake_count=params.get("wake_count"),
        quality=int(quality) if quality is not None else None,
        source=params.get("source") or "manual",
        note=params.get("note"),
    )

    total = _storage.sleep_count()
    short = max(0, _analysis.MIN_PAIRS - total)
    return _ok(
        night=night,
        duration_min=duration,
        hours=round(duration / 60, 2),
        nights_logged=total,
        note=(
            f"{short} more night(s) until Hypnos will report a correlation."
            if short
            else "Enough nights logged to attempt a correlation."
        ),
    )


# ---------------------------------------------------------- sleep_import


def sleep_import(params: dict, **_kw: Any) -> str:
    """Import a CSV of nights. Gadgetbridge/Mi Fitness/Fit exports, or hand-rolled.

    Expected headers (case-insensitive, extras ignored):
        night|date, duration|duration_min|minutes, wake_count?, quality?
    """
    path = params.get("path")
    if not path:
        return _err("'path' is required.")
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return _err(f"No such file: {path}")
    if os.path.getsize(path) > 8 * 1024 * 1024:
        return _err("Refusing to read a file larger than 8 MB.")

    import csv  # noqa: PLC0415

    imported, skipped = 0, []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return _err("CSV has no header row.")
        norm = {(f or "").strip().lower(): f for f in reader.fieldnames}

        def pick(*names):
            for nm in names:
                if nm in norm:
                    return norm[nm]
            return None

        c_night = pick("night", "date", "day")
        c_dur = pick("duration", "duration_min", "minutes", "sleep_duration")
        c_wake = pick("wake_count", "wakeups", "awake_count")
        c_qual = pick("quality", "score")
        if not c_night or not c_dur:
            return _err(
                "CSV needs a date column (night|date|day) and a duration column "
                "(duration|duration_min|minutes).",
                found_columns=reader.fieldnames,
            )

        for i, row in enumerate(reader, start=2):
            raw_night = (row.get(c_night) or "").strip()[:10]
            dur = _parse_duration(row.get(c_dur))
            try:
                _dt.datetime.strptime(raw_night, "%Y-%m-%d")
            except ValueError:
                skipped.append({"line": i, "why": f"bad date {raw_night!r}"})
                continue
            if dur is None or not 30 <= dur <= 1000:
                skipped.append({"line": i, "why": f"bad duration {row.get(c_dur)!r}"})
                continue
            wake = None
            if c_wake and (row.get(c_wake) or "").strip().isdigit():
                wake = int(row[c_wake])
            qual = None
            if c_qual:
                try:
                    q = int(float(row[c_qual]))
                    qual = q if 1 <= q <= 5 else None
                except (TypeError, ValueError):
                    qual = None
            _storage.upsert_sleep(
                raw_night,
                dur,
                wake_count=wake,
                quality=qual,
                source=params.get("source") or "csv",
            )
            imported += 1

    return _ok(
        imported=imported,
        skipped=len(skipped),
        skipped_detail=skipped[:10],
        nights_logged=_storage.sleep_count(),
    )


# ---------------------------------------------------- hypnos_activity


def hypnos_activity(params: dict, **_kw: Any) -> str:
    days = int(params.get("days") or 30)
    days = max(1, min(days, 365))
    synced = _activity.sync_activity(days=days)
    rows = _storage.list_activity(limit=days)
    hist = _activity.hour_histogram(days=days)

    peak = max(hist.items(), key=lambda kv: kv[1])[0] if any(hist.values()) else None
    total = sum(hist.values())
    night_share = (
        sum(v for h, v in hist.items() if h >= 23 or h < 5) / total if total else 0.0
    )

    return _ok(
        days_scanned=days,
        nights_with_activity=synced,
        hour_histogram=hist,
        peak_hour=peak,
        after_11pm_share=round(night_share, 3),
        summary=(
            f"{round(night_share * 100)}% of your agent activity happens between "
            f"23:00 and 05:00"
            + (f", peaking at {peak:02d}:00." if peak is not None else ".")
        ),
        recent=rows[:14],
    )


# ------------------------------------------------------ hypnos_report


def _bar(n: int, width: int = 40, peak: int = 1) -> str:
    return "#" * max(0, round(n / max(peak, 1) * width))


def hypnos_report(params: dict, **_kw: Any) -> str:
    days = int(params.get("days") or 60)
    _activity.sync_activity(days=days)
    sleep_rows = _storage.list_sleep(limit=days)
    act_rows = _storage.list_activity(limit=days)
    result = _analysis.analyze(sleep_rows, act_rows)

    if params.get("format") == "text":
        hist = _activity.hour_histogram(days=days)
        peak = max(hist.values()) if hist else 1
        lines = ["HYPNOS", "=" * 52, "", "Agent activity by hour of day:"]
        for h in range(24):
            c = hist.get(h, 0)
            if c:
                lines.append(f"  {h:02d}:00 {_bar(c, 40, peak)} {c}")
        lines += ["", f"Verdict: {result['verdict']}", result["message"], ""]
        for c in result.get("correlations", []):
            if "r" in c:
                ci = c.get("ci95")
                ci_s = f"  CI95 [{ci[0]}, {ci[1]}]" if ci else ""
                lines.append(
                    f"  [{c['verdict']}] {c['label']}: r={c['r']} "
                    f"({c['strength']}){ci_s}"
                )
                if c.get("detail"):
                    lines.append(f"      {c['detail']}")
            else:
                lines.append(f"  [{c['verdict']}] {c['label']}")
        return _ok(report="\n".join(lines), **result)

    return _ok(**result)


# ------------------------------------------------------- hypnos_guard


def hypnos_guard(params: dict, **_kw: Any) -> str:
    action = (params.get("action") or "status").lower()
    if action == "status":
        return _ok(config=_storage.get_guard_config(),
                   recent_events=_storage.recent_guard_events(10))
    if action in ("enable", "disable"):
        cfg = _storage.set_guard_config(enabled=(action == "enable"))
        return _ok(config=cfg)
    if action == "configure":
        for key in ("quiet_start", "quiet_end"):
            v = params.get(key)
            if v and not re.match(r"^\d{1,2}:\d{2}$", str(v)):
                return _err(f"'{key}' must look like 23:30.")
        mode = params.get("mode")
        if mode and mode not in ("approve", "block"):
            return _err("'mode' must be 'approve' or 'block'.")
        cfg = _storage.set_guard_config(
            quiet_start=params.get("quiet_start"),
            quiet_end=params.get("quiet_end"),
            mode=mode,
        )
        return _ok(config=cfg)
    return _err("action must be one of: status, enable, disable, configure")
