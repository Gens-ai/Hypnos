"""The descriptive failed-call rate, exercised where the truth is known.

Three things must hold, and the third is the one that matters:

  1. The lag is real — a night is compared against the day AFTER it, not
     the day that led into it.
  2. The rate is a rate — a day with ten times the calls does not look ten
     times worse.
  3. Backfilled days are UNKNOWN, not clean. Days with no observed_calls
     carry error_results = 0 because Hermes stores no tool result text, and
     counting them as error-free would manufacture a trend out of nothing.

Run with:  python -m pytest tests/  (or python tests/test_failed_calls.py)
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kairos import activity  # noqa: E402

DAY0 = _dt.date(2026, 3, 1)


def _day(i: int) -> str:
    return (DAY0 + _dt.timedelta(days=i)).isoformat()


def _act(i: int, observed: int, errors: int, calls: int | None = None) -> dict:
    return {
        "day": _day(i),
        "observed_calls": observed,
        "error_results": errors,
        "tool_calls": calls if calls is not None else observed,
    }


def test_unobserved_days_are_excluded() -> None:
    rows = [
        _act(0, observed=0, errors=0, calls=300),  # backfilled: unknown
        _act(1, observed=5, errors=4, calls=5),  # too few calls: noise
        _act(2, observed=100, errors=10, calls=100),  # real
    ]
    rates = activity.failed_call_rates(rows)
    assert [r["day"] for r in rates] == [_day(2)], rates
    assert rates[0]["failure_rate"] == 0.1


def test_rate_not_count() -> None:
    """A busy day and a quiet day with the same rate must look the same."""
    rows = [_act(0, observed=50, errors=5), _act(1, observed=500, errors=50)]
    rates = activity.failed_call_rates(rows)
    assert rates[0]["failure_rate"] == rates[1]["failure_rate"] == 0.1


def test_pairing_is_lagged() -> None:
    """Night N is judged by day N+1. Planted effect: short night, bad day after."""
    sleep_rows, act_rows = [], []
    for i in range(12):
        short = i % 2 == 0
        sleep_rows.append(
            {"night": _day(i), "duration_min": 260 if short else 520}
        )
        # The failures land on the day AFTER each short night. A non-lagged
        # pairing would read this as short nights being CLEAN.
        act_rows.append(_act(i, observed=200, errors=40 if (i % 2 == 1) else 4))

    out = activity.failures_after_sleep(sleep_rows, act_rows)
    assert out["status"] == "OBSERVED", out
    short_rate = out["shorter_nights"]["mean_failure_rate"]
    long_rate = out["longer_nights"]["mean_failure_rate"]
    assert short_rate > long_rate, out
    assert abs(short_rate - 0.20) < 0.01, out
    assert abs(long_rate - 0.02) < 0.01, out
    # Descriptive only: no coefficient, no interval, no verdict.
    for banned in ("r", "ci", "verdict", "strength", "direction"):
        assert banned not in out, banned


def test_backfill_cannot_fabricate_a_trend() -> None:
    """All-backfilled history must refuse to compare, not report zeroes."""
    sleep_rows = [
        {"night": _day(i), "duration_min": 200 + i * 20} for i in range(20)
    ]
    act_rows = [_act(i, observed=0, errors=0, calls=400) for i in range(21)]
    out = activity.failures_after_sleep(sleep_rows, act_rows)
    assert out["status"] == "NOT_ENOUGH_OBSERVED_DAYS", out
    assert out["paired_days"] == 0
    assert "unknown, not zero" in out["note"]
    assert "shorter_nights" not in out


def test_too_few_days_refuses() -> None:
    sleep_rows = [{"night": _day(i), "duration_min": 300} for i in range(4)]
    act_rows = [_act(i, observed=100, errors=5) for i in range(5)]
    out = activity.failures_after_sleep(sleep_rows, act_rows)
    assert out["status"] == "NOT_ENOUGH_OBSERVED_DAYS", out
    assert out["paired_days"] == 4


def test_error_rate_is_not_a_correlation_feature() -> None:
    """It must stay out of the Bonferroni family in analysis.FEATURES."""
    from kairos import analysis

    assert "error_results" not in analysis.FEATURES
    assert "observed_calls" not in analysis.FEATURES
    assert len(analysis.FEATURES) == 5


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
