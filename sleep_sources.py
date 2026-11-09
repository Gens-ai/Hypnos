"""Sleep bridges. Adding one is a class and a line in REGISTRY.

Each source answers three questions and nothing else:

* ``requirements()`` \u2014 what config it needs, so the agent can ask for it
* ``probe(cfg)`` \u2014 retrieve and parse, **writing nothing**
* ``fetch(cfg)`` \u2014 the same, returning canonical nights

Validation, dedupe, plausibility, provenance and manual protection all
live in ``normalize``. A source that tries to do any of that is doing
someone else's job.

``probe`` is not optional. Every format these bridges read is a moving
target \u2014 the MCP tool names here are informed guesses, and Gadgetbridge's
sleep encoding is device-specific \u2014 so the contract is: show the user what
came back and what you made of it *before* anything lands in their
history. ``provides`` is equally load-bearing: a source that cannot supply
onset latency must say so rather than letting the report treat absent as
zero.
"""

from __future__ import annotations

import os as _os
import sqlite3 as _sqlite3
from typing import Any, Optional

from . import normalize as _norm

# What a source can supply, beyond the required night + duration. The
# report consults this instead of inferring capability from nulls.
FIELDS = ("sleep_start", "sleep_end", "wake_count", "quality", "onset_latency", "hr", "hrv")


class SleepSource:
    """Base class. Subclasses override name/provides/requirements/_load."""

    name = "abstract"
    label = "Abstract source"
    provides: tuple[str, ...] = ()

    def requirements(self) -> dict[str, Any]:
        return {}

    def _load(self, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
        """Return (raw rows or payload-derived nights, a preview of the raw)."""
        raise NotImplementedError

    # -- the two public verbs, identical for every source ---------------

    def probe(self, cfg: dict[str, Any]) -> dict[str, Any]:
        try:
            nights, preview = self._load(cfg)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "ok": True,
            "source": self.name,
            "provides": list(self.provides),
            "nights_parsed": len(nights),
            "nights": nights[-7:],
            "assumed_units": [
                {"night": n["night"], "minutes": n["duration_min"],
                 "assumption": n["assumed"]}
                for n in nights if n.get("assumed")
            ],
            "raw_preview": preview,
            "wrote_nothing": True,
            "verdict": (
                f"Parsed {len(nights)} night(s). Nothing was written \u2014 import "
                "when the numbers look right."
                if nights else
                "Parsed nothing. Check raw_preview: the location or the "
                "mapping is probably wrong."
            ),
        }

    def fetch(self, cfg: dict[str, Any]) -> dict[str, Any]:
        try:
            nights, _ = self._load(cfg)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        result = _norm.ingest(nights, source=self.name, protect_manual=True)
        return {"ok": True, "source": self.name, **result}


# ----------------------------------------------------------------- CSV


class CsvSource(SleepSource):
    name = "csv"
    label = "CSV export (any tracker, or hand-made)"
    provides = ("wake_count", "quality")

    def requirements(self) -> dict[str, Any]:
        return {"path": "Path to a .csv with a date column and a duration column."}

    def _load(self, cfg):
        import csv  # noqa: PLC0415

        path = _os.path.expanduser(str(cfg.get("path") or ""))
        if not path:
            raise ValueError("'path' is required.")
        if not _os.path.exists(path):
            raise FileNotFoundError(f"No such file: {path}")
        if _os.path.getsize(path) > 8 * 1024 * 1024:
            raise ValueError("Refusing to read a file larger than 8 MB.")
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row.")
            fields = list(reader.fieldnames)
            # Fail closed on anything that is not recognisably a sleep export,
            # and echo NOTHING from it. Without this check the probe preview
            # turns this tool into an arbitrary file reader that reports the
            # first line of any readable file -- /etc/passwd, a token file --
            # straight back into the transcript. The tool's job is importing
            # sleep, so a file with no date column is simply refused.
            lowered = {(f or "").strip().lower() for f in fields}
            if not (lowered & set(_norm.DATE_KEYS)):
                raise ValueError(
                    "This does not look like a sleep export: no recognisable "
                    "date column (one of night/date/day/...). Its contents are "
                    "not shown. Point this at a sleep CSV, or pass the right "
                    "file."
                )
            rows = [dict(r) for r in reader]
        # Lower-case the keys so the shared alias tables apply to CSV too,
        # instead of CSV keeping its own smaller list.
        rows = [{(k or "").strip().lower(): v for k, v in r.items()} for r in rows]
        nights = _norm.extract_nights(rows)
        preview = {"columns": fields, "rows_read": len(rows)}
        return nights, preview


# ----------------------------------------------------------------- MCP


class McpSource(SleepSource):
    """Any health MCP server the user already runs, via ``ctx.call_mcp``."""

    name = "mcp"
    label = "Health MCP server (Oura / WHOOP / Garmin / Apple Health)"
    provides = ("sleep_start", "sleep_end", "wake_count", "quality")

    # Informed guesses, not verified against live servers. probe() is how
    # you find out which is right on a given install.
    PRESETS: dict[str, dict[str, Any]] = {
        "athletedata": {
            "tool": "get_sleep", "args": {"days": 7},
            "note": "Garmin / Oura / WHOOP and ~35 more, via their hosted MCP.",
        },
        "apple-health-mcp": {
            "tool": "query",
            "args": {"sql": "SELECT * FROM sleep ORDER BY startDate DESC LIMIT 14"},
            "note": "Local Apple Health export; the tool is usually SQL-shaped.",
        },
        "healthrelay": {
            "tool": "get_sleep_data", "args": {"days": 7},
            "note": "Apple Health through a receiver you host yourself.",
        },
        "health-data": {
            "tool": "health_query", "args": {"metric": "sleep", "days": 7},
            "note": "Local health store with its own query tools.",
        },
    }

    def requirements(self) -> dict[str, Any]:
        return {
            "server": "MCP server name from mcp.servers, granted in "
                      "plugins.entries.hypnos.mcp_allowlist.",
            "tool": "Tool on that server. Defaults to the preset.",
            "args": "Arguments for that tool. Defaults to the preset.",
            "_ctx": "Injected: the plugin ctx, for call_mcp.",
        }

    def _load(self, cfg):
        ctx = cfg.get("_ctx")
        server = str(cfg.get("server") or "").strip()
        tool = str(cfg.get("tool") or "").strip()
        if not server:
            raise ValueError("'server' is required. See the presets.")
        if not tool:
            tool = str(self.PRESETS.get(server, {}).get("tool") or "")
        if not tool:
            raise ValueError(f"No preset tool for '{server}' \u2014 pass tool= explicitly.")
        args = cfg.get("args")
        if args is None:
            args = self.PRESETS.get(server, {}).get("args") or {}
        if ctx is None or not hasattr(ctx, "call_mcp"):
            raise RuntimeError("No ctx.call_mcp available in this context.")
        try:
            res = ctx.call_mcp(server, tool, args, timeout=30)
        except PermissionError as exc:
            raise PermissionError(
                f"Not allowed to call MCP server '{server}'. Grant it in "
                f"config.yaml under plugins.entries.hypnos.mcp_allowlist, "
                f"then retry. ({exc})"
            ) from exc
        if not isinstance(res, dict) or not res.get("ok"):
            err = res.get("error") if isinstance(res, dict) else str(res)
            raise RuntimeError(f"MCP server returned an error: {err}")
        payload = res.get("structuredContent") or res.get("result")
        return _norm.extract_nights(payload), _preview(payload)


# --------------------------------------------------------- Gadgetbridge


class GadgetbridgeSource(SleepSource):
    """A Gadgetbridge SQLite export, read-only.

    Gadgetbridge does not store nights. It stores one row per minute in a
    per-device sample table, each tagged with a raw activity kind, so a
    night has to be reassembled: select the sleep-kind samples, group
    contiguous runs, and collapse each run into a duration plus the number
    of interruptions inside it.

    The raw-kind encoding is device-specific and undocumented per model, so
    nothing here is hardcoded blind: the table and columns are discovered,
    the sleep kinds are configurable, and ``probe`` reports the kind
    histogram it found so the mapping can be corrected rather than guessed
    at twice.
    """

    name = "gadgetbridge"
    label = "Gadgetbridge SQLite export (Mi Band, Amazfit, and friends)"
    provides = ("sleep_start", "sleep_end", "wake_count")

    # Gadgetbridge's normalized ActivityKind bits for sleep, plus the raw
    # Huami values commonly seen for light/deep sleep on Mi Band hardware.
    DEFAULT_SLEEP_KINDS = (2, 4, 16, 112, 122, 123)
    # Samples this far apart or less are the same sleep; a longer gap ends it.
    DEFAULT_GAP_MIN = 30
    # A run shorter than this is noise, not a night.
    MIN_RUN_MIN = 30

    def requirements(self) -> dict[str, Any]:
        return {
            "path": "Path to the exported Gadgetbridge .db (Syncthing it over).",
            "table": "Optional: sample table. Auto-discovered when omitted.",
            "sleep_kinds": f"Optional: raw kind values counted as sleep. "
                           f"Default {list(self.DEFAULT_SLEEP_KINDS)}.",
            "gap_min": f"Optional: minutes of gap that end a sleep block. "
                       f"Default {self.DEFAULT_GAP_MIN}.",
        }

    def _load(self, cfg):
        path = _os.path.expanduser(str(cfg.get("path") or ""))
        if not path:
            raise ValueError("'path' is required.")
        if not _os.path.exists(path):
            raise FileNotFoundError(f"No such file: {path}")
        con = _sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            table, ts_col, kind_col = self._discover(con, cfg.get("table"))
            kinds = tuple(cfg.get("sleep_kinds") or self.DEFAULT_SLEEP_KINDS)
            gap = int(cfg.get("gap_min") or self.DEFAULT_GAP_MIN)

            hist = dict(
                con.execute(
                    f"SELECT {kind_col}, COUNT(*) FROM {table} "
                    f"GROUP BY {kind_col} ORDER BY 2 DESC"
                ).fetchall()[:20]
            )
            placeholders = ",".join("?" * len(kinds))
            rows = con.execute(
                f"SELECT {ts_col} FROM {table} WHERE {kind_col} IN ({placeholders}) "
                f"ORDER BY {ts_col}",
                kinds,
            ).fetchall()
        finally:
            con.close()

        stamps = [int(r[0]) for r in rows if r[0] is not None]
        nights = self._assemble(stamps, gap)
        preview = {
            "table": table,
            "timestamp_column": ts_col,
            "kind_column": kind_col,
            "sleep_kinds_used": list(kinds),
            "kind_histogram": {str(k): v for k, v in hist.items()},
            "sleep_samples_matched": len(stamps),
            "hint": (
                "kind_histogram lists every raw kind in the table with its row "
                "count. If nights look wrong, the sleep kinds are wrong \u2014 pass "
                "sleep_kinds explicitly."
            ),
        }
        return nights, preview

    def _discover(self, con, override: Optional[str]) -> tuple[str, str, str]:
        """Find the sample table and its timestamp / kind columns."""
        names = [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        candidates = [override] if override else [
            n for n in names if "ACTIVITY_SAMPLE" in n.upper()
        ]
        sample_like = [n for n in names if "ACTIVITY_SAMPLE" in n.upper()]
        if override and override not in names:
            # Only name the tables when this really is a Gadgetbridge export.
            # Otherwise this error would enumerate an arbitrary database's
            # schema back to the caller.
            hint = f" Tables: {sample_like[:25]}" if sample_like else ""
            raise ValueError(f"No such table {override!r}.{hint}")

        best = None
        for t in candidates:
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})").fetchall()]
            up = {c.upper(): c for c in cols}
            ts = up.get("TIMESTAMP") or next(
                (up[k] for k in up if "TIMESTAMP" in k or k == "TS"), None
            )
            kind = up.get("RAW_KIND") or next(
                (up[k] for k in up if "KIND" in k), None
            )
            if not ts or not kind:
                continue
            try:
                n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except _sqlite3.Error:
                continue
            if best is None or n > best[3]:
                best = (t, ts, kind, n)
        if best is None:
            raise ValueError(
                "This SQLite file has no Gadgetbridge activity-sample table "
                "with a timestamp and a kind column, so it is not a "
                "Gadgetbridge export. Its schema is not shown."
                + (f" Sample-like tables seen: {sample_like[:25]}"
                   if sample_like else "")
            )
        return best[0], best[1], best[2]

    def _assemble(self, stamps: list[int], gap_min: int) -> list[dict[str, Any]]:
        """Contiguous runs of sleep samples -> one canonical night each."""
        if not stamps:
            return []
        from . import activity as _activity  # noqa: PLC0415

        gap = gap_min * 60
        runs: list[list[int]] = [[stamps[0]]]
        for t in stamps[1:]:
            if t - runs[-1][-1] <= gap:
                runs[-1].append(t)
            else:
                runs.append([t])

        by_night: dict[str, dict[str, Any]] = {}
        for run in runs:
            start, end = run[0], run[-1]
            minutes = int(round((end - start) / 60.0))
            if minutes < self.MIN_RUN_MIN:
                continue
            # Interruptions = sample gaps inside the run beyond one interval.
            interval = _median_delta(run) or 60
            wakes = sum(1 for a, b in zip(run, run[1:]) if (b - a) > interval * 3)
            # A block that starts at 02:00 belongs to the night before, the
            # same rollover the activity sensor uses, so the two line up.
            night = _activity.night_of(float(start))
            prev = by_night.get(night)
            if prev is None or minutes > prev["duration_min"]:
                by_night[night] = {
                    "night": night,
                    "duration_min": minutes,
                    "sleep_start": float(start),
                    "sleep_end": float(end),
                    "wake_count": wakes,
                }
        return [
            n for n in sorted(by_night.values(), key=lambda r: r["night"])
            if _norm.MIN_SLEEP_MIN <= n["duration_min"] <= _norm.MAX_SLEEP_MIN
        ]


def _median_delta(stamps: list[int]) -> Optional[int]:
    d = sorted(b - a for a, b in zip(stamps, stamps[1:]))
    return d[len(d) // 2] if d else None


def _preview(payload: Any, limit: int = 600) -> str:
    import json  # noqa: PLC0415

    try:
        s = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    except Exception:
        s = str(payload)
    return s[:limit] + ("\u2026" if len(s) > limit else "")


# --------------------------------------------------------------- Xiaomi


class XiaomiSource(SleepSource):
    """A Mi Fitness / Xiaomi account data export.

    Xiaomi's GDPR export is not a sleep file. It is a long key/value table
    (``hlth_center_aggregated_fitness_data.csv``) where each row's ``Value``
    is a JSON blob, and sleep is the subset whose ``Key`` is ``sleep``. A
    second table, ``hlth_center_fitness_data.csv``, carries per-device
    ``watch_night_sleep`` rows with an ``awake_count`` the aggregate lacks,
    so the two are merged by night.

    ``total_duration`` is Xiaomi's figure for all sleep in the day,
    including naps — a night with a 20-minute nap and a 443-minute sleep
    reports 463. For correlating against a working day the main sleep is
    the honest number, so the **longest segment** becomes the night and the
    daily total is kept in ``extra``.
    """

    name = "xiaomi"
    label = "Mi Fitness / Xiaomi account export (Mi Band, Redmi Watch)"
    provides = ("sleep_start", "sleep_end", "wake_count", "quality")

    AGG_GLOB = "*aggregated_fitness_data.csv"
    FIT_GLOB = "*center_fitness_data.csv"

    def requirements(self) -> dict[str, Any]:
        return {
            "path": "The extracted export folder, or the aggregated CSV itself. "
                    "Get it from account.xiaomi.com -> Privacy -> Manage Your "
                    "Data -> Mi Fitness -> Download.",
        }

    def _find(self, root: str) -> tuple[Optional[str], Optional[str]]:
        import glob  # noqa: PLC0415

        if _os.path.isfile(root):
            return root, None
        agg = glob.glob(_os.path.join(root, "**", self.AGG_GLOB), recursive=True)
        fit = [
            f for f in glob.glob(_os.path.join(root, "**", self.FIT_GLOB), recursive=True)
            if "aggregated" not in _os.path.basename(f)
        ]
        return (agg[0] if agg else None), (fit[0] if fit else None)

    def _load(self, cfg):
        import csv  # noqa: PLC0415
        import json  # noqa: PLC0415

        from . import activity as _activity  # noqa: PLC0415

        root = _os.path.expanduser(str(cfg.get("path") or ""))
        if not root:
            raise ValueError("'path' is required.")
        if not _os.path.exists(root):
            raise FileNotFoundError(f"No such path: {root}")
        agg, fit = self._find(root)
        if not agg:
            raise ValueError(
                "No Xiaomi aggregated fitness CSV found under that path. Point "
                "this at the extracted export folder. Its contents are not shown."
            )

        def read(path, key):
            out = []
            if not path:
                return out
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                for r in csv.DictReader(fh):
                    if r.get("Key") != key:
                        continue
                    try:
                        r["_v"] = json.loads(r.get("Value") or "{}")
                    except ValueError:
                        continue
                    out.append(r)
            return out

        agg_rows = read(agg, "sleep")
        fit_rows = read(fit, "watch_night_sleep")

        # awake_count by night, from the per-device rows only.
        wakes: dict[str, int] = {}
        for r in fit_rows:
            v = r["_v"]
            bed = v.get("bedtime") or r.get("Time")
            if bed is None:
                continue
            night = _activity.night_of(float(bed))
            if v.get("awake_count") is not None:
                wakes[night] = int(v["awake_count"])

        nights: dict[str, dict[str, Any]] = {}
        for r in agg_rows + fit_rows:
            v = r["_v"]
            segs = [s for s in (v.get("segment_details") or [])
                    if isinstance(s, dict) and s.get("duration")]
            if segs:
                main = max(segs, key=lambda s: s.get("duration") or 0)
                dur = int(main["duration"])
                start = main.get("bedtime")
                end = main.get("wake_up_time")
            else:
                dur = v.get("duration") or v.get("total_duration")
                start, end = v.get("bedtime"), v.get("wake_up_time")
                if dur is None:
                    continue
                dur = int(dur)
            if start is None:
                start = r.get("Time")
            if start is None:
                continue
            night = _activity.night_of(float(start))

            score = v.get("sleep_score")
            quality = None
            if isinstance(score, (int, float)) and score > 0:
                quality = max(1, min(5, int(round(float(score) / 20.0))))

            rec = {
                "night": night,
                "duration_min": dur,
                "sleep_start": float(start) if start else None,
                "sleep_end": float(end) if end else None,
                "wake_count": wakes.get(night, v.get("awake_count")),
                "quality": quality,
                "extra": {
                    k: v[k] for k in (
                        "sleep_deep_duration", "sleep_light_duration",
                        "sleep_rem_duration", "sleep_awake_duration",
                        "sleep_score", "total_duration", "avg_hr", "avg_spo2",
                    ) if v.get(k) not in (None, 0)
                },
            }
            if len(segs) > 1:
                rec["extra"]["segments"] = len(segs)
            # Prefer the richer record when both tables describe one night.
            prev = nights.get(night)
            if prev is None or (rec["quality"] is not None and prev["quality"] is None) \
                    or len(rec["extra"]) > len(prev.get("extra") or {}):
                nights[night] = rec

        out = [n for n in sorted(nights.values(), key=lambda r: r["night"])
               if _norm.MIN_SLEEP_MIN <= n["duration_min"] <= _norm.MAX_SLEEP_MIN]
        preview = {
            "aggregated_csv": _os.path.basename(agg),
            "device_csv": _os.path.basename(fit) if fit else None,
            "aggregated_sleep_rows": len(agg_rows),
            "device_sleep_rows": len(fit_rows),
            "distinct_nights": len(nights),
            "kept_after_plausibility": len(out),
            "date_range": (f"{out[0]['night']} .. {out[-1]['night']}" if out else None),
        }
        return out, preview


# ------------------------------------------------------------- registry

REGISTRY: dict[str, SleepSource] = {
    s.name: s for s in (CsvSource(), McpSource(), GadgetbridgeSource(), XiaomiSource())
}


def get_source(name: str) -> Optional[SleepSource]:
    return REGISTRY.get((name or "").strip().lower())


def describe_sources() -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "label": s.label,
            "provides": list(s.provides),
            "requirements": s.requirements(),
        }
        for s in REGISTRY.values()
    ]


def sniff_file(path: str) -> Optional[str]:
    """Guess the source so the user needn't name the format."""
    import glob  # noqa: PLC0415

    path = _os.path.expanduser(path or "")
    if _os.path.isdir(path):
        # A Xiaomi export is a folder of key/value CSVs, not one sleep file.
        if glob.glob(_os.path.join(path, "**", XiaomiSource.AGG_GLOB), recursive=True):
            return "xiaomi"
        return None
    if not _os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    if head.startswith(b"SQLite format 3"):
        return "gadgetbridge"
    if "aggregated_fitness_data" in _os.path.basename(path):
        return "xiaomi"
    return "csv"
