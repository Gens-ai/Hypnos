"""Correlation with an honesty gate.

The entire credibility of this plugin rests on refusing to report a
relationship the sample cannot support. Fourteen nights cannot tell you
that late debugging costs you 40 minutes of sleep. We say so.

Rules:
  * Fewer than MIN_PAIRS matched nights  -> INSUFFICIENT_EVIDENCE, no numbers.
  * Correlation reported with a bootstrap CI; if the CI straddles zero the
    verdict is INCONCLUSIVE, not a direction.
  * Never a causal verb. "associated with", never "causes".
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional

# Below this, we report nothing but the shortfall.
MIN_PAIRS = 10
# Enough to start quoting an interval with a straight face.
DECENT_PAIRS = 21

FEATURES: dict[str, str] = {
    "late_minutes": "how late you were still working",
    "tool_calls": "total tool calls (session intensity)",
    "terminal_calls": "hands-on terminal/code work",
    "message_count": "conversation volume",
    "session_count": "number of distinct sessions",
}


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _bootstrap_ci(
    xs: list[float], ys: list[float], iters: int = 2000, alpha: float = 0.05
) -> Optional[tuple[float, float]]:
    n = len(xs)
    if n < 4:
        return None
    rng = random.Random(20261107)
    stats: list[float] = []
    for _ in range(iters):
        idx = [rng.randrange(n) for _ in range(n)]
        r = _pearson([xs[i] for i in idx], [ys[i] for i in idx])
        if r is not None:
            stats.append(r)
    if len(stats) < iters // 4:
        return None
    stats.sort()
    lo = stats[int((alpha / 2) * len(stats))]
    hi = stats[min(len(stats) - 1, int((1 - alpha / 2) * len(stats)))]
    return (lo, hi)


def _strength(r: float) -> str:
    a = abs(r)
    if a < 0.2:
        return "negligible"
    if a < 0.4:
        return "weak"
    if a < 0.6:
        return "moderate"
    return "strong"


def pair_nights(
    sleep_rows: list[dict[str, Any]], activity_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join sleep to the activity of the night it belongs to."""
    act = {r["day"]: r for r in activity_rows}
    out = []
    for s in sleep_rows:
        a = act.get(s["night"])
        if not a:
            continue
        out.append({"night": s["night"], "sleep": s, "activity": a})
    return out


def analyze(
    sleep_rows: list[dict[str, Any]], activity_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    pairs = pair_nights(sleep_rows, activity_rows)
    n = len(pairs)

    base: dict[str, Any] = {
        "matched_nights": n,
        "sleep_nights_logged": len(sleep_rows),
        "activity_days_known": len(activity_rows),
        "min_pairs_required": MIN_PAIRS,
    }

    if n < MIN_PAIRS:
        base.update(
            {
                "verdict": "INSUFFICIENT_EVIDENCE",
                "message": (
                    f"Only {n} night(s) have both sleep and activity data. "
                    f"Kairos needs at least {MIN_PAIRS} before it will report a "
                    f"correlation, and about {DECENT_PAIRS} before the number is worth "
                    f"acting on. Log {MIN_PAIRS - n} more night(s)."
                ),
                "correlations": [],
            }
        )
        return base

    durations = [float(p["sleep"]["duration_min"]) for p in pairs]
    results = []
    for feat, label in FEATURES.items():
        xs = [float(p["activity"].get(feat) or 0) for p in pairs]
        if len(set(xs)) < 2:
            results.append(
                {
                    "feature": feat,
                    "label": label,
                    "verdict": "NO_VARIANCE",
                    "detail": "this feature never varied across the matched nights",
                }
            )
            continue
        r = _pearson(xs, durations)
        if r is None:
            results.append(
                {"feature": feat, "label": label, "verdict": "NOT_COMPUTABLE"}
            )
            continue
        ci = _bootstrap_ci(xs, durations)
        entry: dict[str, Any] = {
            "feature": feat,
            "label": label,
            "r": round(r, 3),
            "strength": _strength(r),
            "direction": "less sleep" if r < 0 else "more sleep",
            "n": n,
        }
        if ci:
            entry["ci95"] = [round(ci[0], 3), round(ci[1], 3)]
            if ci[0] <= 0 <= ci[1]:
                entry["verdict"] = "INCONCLUSIVE"
                entry["detail"] = (
                    "the 95% interval includes zero — direction not established"
                )
            else:
                entry["verdict"] = "ASSOCIATED"
                entry["detail"] = (
                    f"higher {label} is associated with {entry['direction']} "
                    f"(not established as the cause)"
                )
        else:
            entry["verdict"] = "INCONCLUSIVE"
            entry["detail"] = "sample too small for an interval"
        results.append(entry)

    results.sort(key=lambda e: abs(e.get("r", 0) or 0), reverse=True)
    base.update(
        {
            "verdict": "REPORTED" if n >= DECENT_PAIRS else "PROVISIONAL",
            "message": (
                f"{n} matched nights."
                + (
                    ""
                    if n >= DECENT_PAIRS
                    else f" Below {DECENT_PAIRS} nights, treat every number as provisional."
                )
            ),
            "mean_sleep_min": round(sum(durations) / len(durations), 1),
            "correlations": results,
        }
    )
    return base
