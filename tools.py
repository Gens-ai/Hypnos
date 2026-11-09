"""Kairos tool handlers."""

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
    from . import normalize as _norm  # noqa: PLC0415

    duration = _parse_duration(params.get("duration"))
    if duration is None:
        return _err(
            "Could not parse 'duration'. Try '7h20m', '6.5h', '400m' or '7:20'."
        )
    # The shared bounds, not a third private copy of them.
    lo, hi = _norm.MIN_SLEEP_MIN, _norm.MAX_SLEEP_MIN
    if not lo <= duration <= hi:
        return _err(f"Duration {duration} min is out of plausible range ({lo}-{hi}).")

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
            f"{short} more night(s) until Kairos will report a correlation."
            if short
            else "Enough nights logged to attempt a correlation."
        ),
    )


# ---------------------------------------------------------- sleep_import


def sleep_import(params: dict, **_kw: Any) -> str:
    """Import nights from a file. Dispatches to the registry by format.

    A thin dispatcher on purpose: the alias tables, unit coercion,
    plausibility bounds, dedupe and manual-protection all live in
    ``normalize``, so a CSV and a Gadgetbridge database get byte-identical
    treatment. This function used to carry its own smaller copy of that
    logic, which is how it ended up overwriting hand-logged nights while
    the MCP path protected them.
    """
    from . import sleep_sources as _src  # noqa: PLC0415

    path = params.get("path")
    if not path:
        return _err("'path' is required.")

    name = (params.get("source") or "").strip().lower()
    if name in ("", "auto"):
        name = _src.sniff_file(str(path)) or ""
        if not name:
            return _err(
                f"Could not read {path!r}. Pass source= explicitly.",
                known_sources=sorted(_src.REGISTRY),
            )
    source = _src.get_source(name)
    if source is None:
        return _err(f"Unknown source {name!r}.", known_sources=sorted(_src.REGISTRY))

    cfg = {k: v for k, v in params.items() if k not in ("source", "probe")}
    if params.get("probe"):
        out = source.probe(cfg)
        return _ok(**out) if out.get("ok") else _err(out.get("error", "probe failed"))

    out = source.fetch(cfg)
    if not out.get("ok"):
        return _err(out.get("error", "import failed"))
    return _ok(**out)


# ---------------------------------------------------- kairos_activity


def kairos_activity(params: dict, **_kw: Any) -> str:
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


# ------------------------------------------------------ kairos_report


def _bar(n: int, width: int = 40, peak: int = 1) -> str:
    return "#" * max(0, round(n / max(peak, 1) * width))


def kairos_report(params: dict, **_kw: Any) -> str:
    days = int(params.get("days") or 60)
    _activity.sync_activity(days=days)
    sleep_rows = _storage.list_sleep(limit=days)
    act_rows = _storage.list_activity(limit=days)
    result = _analysis.analyze(sleep_rows, act_rows)

    if params.get("format") == "text":
        hist = _activity.hour_histogram(days=days)
        peak = max(hist.values()) if hist else 1
        lines = ["KAIROS", "=" * 52, "", "Agent activity by hour of day:"]
        for h in range(24):
            c = hist.get(h, 0)
            if c:
                lines.append(f"  {h:02d}:00 {_bar(c, 40, peak)} {c}")
        lines += ["", f"Verdict: {result['verdict']}", result["message"], ""]
        for c in result.get("correlations", []):
            if "r" in c:
                ci = c.get("ci")
                ci_s = f"  CI{c.get('ci_level', '')} [{ci[0]}, {ci[1]}]" if ci else ""
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


# ------------------------------------------------------- kairos_guard


def kairos_guard(params: dict, **_kw: Any) -> str:
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
