"""The honesty gate, exercised against data where the truth is known.

Synthetic nights with one real effect planted (late_minutes pulls sleep
down) and four features that are pure noise. The analysis must find the
planted one and call every noise feature INCONCLUSIVE. A false positive
here is the one failure this module exists to prevent.

Run with:  python -m pytest tests/  (or python tests/test_analysis.py)
"""

from __future__ import annotations

import datetime as _dt
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kairos import analysis  # noqa: E402

PLANTED = "late_minutes"
NIGHTS = 30
SEED = 7


def synthetic(n: int = NIGHTS, seed: int = SEED):
    rng = random.Random(seed)
    sleep_rows, activity_rows = [], []
    day0 = _dt.date(2026, 1, 1)
    for i in range(n):
        night = (day0 + _dt.timedelta(days=i)).isoformat()
        late = rng.uniform(0, 240)
        # The planted effect: every hour of lateness costs ~25 min of sleep,
        # plus some genuine night-to-night noise.
        duration = 480 - late * 0.42 + rng.gauss(0, 18)
        sleep_rows.append({"night": night, "duration_min": round(duration)})
        activity_rows.append(
            {
                "day": night,
                PLANTED: round(late),
                "tool_calls": rng.randint(20, 400),
                "terminal_calls": rng.randint(0, 120),
                "message_count": rng.randint(10, 300),
                "session_count": rng.randint(1, 6),
            }
        )
    return sleep_rows, activity_rows


def test_insufficient_evidence_below_min_pairs():
    s, a = synthetic(n=analysis.MIN_PAIRS - 1)
    out = analysis.analyze(s, a)
    assert out["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert out["correlations"] == []


def test_provisional_below_decent_pairs():
    s, a = synthetic(n=analysis.DECENT_PAIRS - 1)
    assert analysis.analyze(s, a)["verdict"] == "PROVISIONAL"


def test_finds_planted_effect():
    s, a = synthetic()
    out = analysis.analyze(s, a)
    assert out["verdict"] == "REPORTED"
    by_feat = {c["feature"]: c for c in out["correlations"]}
    real = by_feat[PLANTED]
    assert real["verdict"] == "ASSOCIATED"
    assert real["r"] < -0.6
    assert real["ci"][1] < 0
    assert len([f for f in by_feat if f != PLANTED]) == 4


def false_positive_rates(n: int, seeds: int = 300) -> dict:
    """Across many synthetic datasets: how often is the planted effect
    missed, and how often does a pure-noise feature clear the gate?"""
    missed = fp = runs_with_fp = 0
    for seed in range(seeds):
        s, a = synthetic(n=n, seed=seed)
        got = {c["feature"]: c for c in analysis.analyze(s, a)["correlations"]}
        missed += got[PLANTED]["verdict"] != "ASSOCIATED"
        f = sum(1 for k, c in got.items() if k != PLANTED and c["verdict"] == "ASSOCIATED")
        fp += f
        runs_with_fp += f > 0
    return {
        "n": n,
        "planted_missed": missed / seeds,
        "noise_fp_per_feature": fp / (4 * seeds),
        "runs_with_any_fp": runs_with_fp / seeds,
    }


def test_rates_are_what_the_corrected_interval_promises():
    """The interval is Bonferroni-corrected (ALPHA / number of features), so
    a noise feature should clear the gate ~1% of the time, more at small n
    where the bootstrap interval is optimistic. Family-wise, a report should
    carry a spurious association about one time in twenty from 30 nights up,
    and about one in eleven at 21. The strong planted effect is found every
    time from 30 nights, and very nearly every time at 21."""
    for n in (analysis.DECENT_PAIRS, 30, 60):
        r = false_positive_rates(n, seeds=150)
        assert r["planted_missed"] <= (0.02 if n == analysis.DECENT_PAIRS else 0), r
        assert r["noise_fp_per_feature"] <= 0.04, r
        assert r["runs_with_any_fp"] <= (0.12 if n == analysis.DECENT_PAIRS else 0.08), r


def test_no_causal_verbs():
    s, a = synthetic()
    out = analysis.analyze(s, a)
    text = " ".join(c.get("detail", "") for c in out["correlations"]).lower()
    assert "causes" not in text and "because" not in text


if __name__ == "__main__":
    s, a = synthetic()
    out = analysis.analyze(s, a)
    for c in out["correlations"]:
        print(f"{c['feature']:16} r={c.get('r')!s:7} ci={c.get("ci")}  {c['verdict']}")
    print()
    for n in (10, 21, 30, 60):
        r = false_positive_rates(n)
        print(
            f"n={n:3d}  planted missed {r['planted_missed']:.1%}   "
            f"noise FP per feature {r['noise_fp_per_feature']:.1%}   "
            f"reports with >=1 FP {r['runs_with_any_fp']:.1%}"
        )
    print()
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
