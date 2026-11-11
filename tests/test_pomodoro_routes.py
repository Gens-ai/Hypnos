"""Settings and pane routes for the pomodoro.

Run with:  python -m pytest tests/   (skipped where fastapi isn't installed)
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kairos import goals, storage  # noqa: E402
from kairos.dashboard import plugin_api as api  # noqa: E402


@pytest.fixture(autouse=True)
def db(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.executescript(storage._SCHEMA)
    monkeypatch.setattr(storage, "connect", lambda: con)


def _run(coro):
    return asyncio.run(coro)


def test_settings_save_and_validate():
    out = _run(api.write_goals(api.GoalBody(
        pomodoro_enabled=True, pomodoro_work_min=50, pomodoro_break_min=10,
        pomodoro_away_min=15)))
    assert out["success"], out
    g = goals.get_goals()
    assert (g["pomodoro_enabled"], g["pomodoro_work_min"], g["pomodoro_break_min"],
            g["pomodoro_away_min"]) == ("true", "50", "10", "15")


@pytest.mark.parametrize("field,value", [
    ("pomodoro_work_min", 10), ("pomodoro_work_min", 121),
    ("pomodoro_break_min", 2), ("pomodoro_break_min", 16),
    ("pomodoro_away_min", 2), ("pomodoro_away_min", 31),
])
def test_settings_out_of_range_are_refused(field, value):
    out = _run(api.write_goals(api.GoalBody(**{field: value})))
    assert out["success"] is False and field in out["error"]


def test_pomodoro_status_route():
    goals.set_goals(pomodoro_enabled=True)
    out = _run(api.pomodoro_status())
    assert out["success"] and "ring" in out["pomodoro"]


def test_pomodoro_action_route():
    goals.set_goals(pomodoro_enabled=True)
    out = _run(api.pomodoro_action(api.PomodoroBody(action="rest", minutes=5)))
    assert out["success"]
