"""kairos_pomodoro: status / rest / skip, as the agent calls it.

Run with:  python -m pytest tests/
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kairos import coach_schemas, coach_tools, goals, pomodoro, storage  # noqa: E402


@pytest.fixture(autouse=True)
def db(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.executescript(storage._SCHEMA)
    monkeypatch.setattr(storage, "connect", lambda: con)
    goals.set_goals(pomodoro_enabled=True)


def _call(**params):
    return json.loads(coach_tools.kairos_pomodoro(params))


def test_schema_is_named_and_enumerated():
    s = coach_schemas.KAIROS_POMODORO
    assert s["name"] == "kairos_pomodoro"
    assert s["parameters"]["properties"]["action"]["enum"] == ["status", "rest", "skip"]


def test_status_is_the_default():
    out = _call()
    assert out["success"] and "why_silent" in out["pomodoro"]


def test_rest_resets_the_stretch():
    out = _call(action="rest", minutes=25)
    assert out["success"] and out["long_rest"] is True
    s = pomodoro.parse_state(storage.get_pomodoro_state())
    assert s["last_reset_reason"] == "rest declared"


def test_skip_today_pauses():
    out = _call(action="skip", scope="today")
    assert out["success"] and out["paused"] is True
    assert _call()["pomodoro"]["paused"] is True


def test_skip_block_changes_nothing():
    before = storage.get_pomodoro_state()
    assert _call(action="skip")["success"]
    assert storage.get_pomodoro_state() == before


def test_bad_input_is_an_error():
    assert not _call(action="nap")["success"]
    assert not _call(action="rest", minutes=0)["success"]
    assert not _call(action="skip", scope="forever")["success"]


def test_off_says_so():
    goals.set_goals(pomodoro_enabled=False)
    assert not _call(action="rest")["success"]
