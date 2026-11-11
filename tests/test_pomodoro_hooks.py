"""The pomodoro as the hooks drive it: messages, tool calls, turn ends.

Run with:  python -m pytest tests/
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import kairos  # noqa: E402
from kairos import goals, pomodoro, storage  # noqa: E402
from test_human_turn import _hooks  # noqa: E402

MIN = 60.0


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.executescript(storage._SCHEMA)
    monkeypatch.setattr(storage, "connect", lambda: con)
    monkeypatch.setattr(storage, "_OUTCOMES", [])
    monkeypatch.setattr(kairos._activity, "sync_activity", lambda **kw: None)
    clock = _Clock(1_800_000_000.0)
    monkeypatch.setattr(kairos, "_now_ts", clock)
    goals.set_goals(pomodoro_enabled=True)
    return _hooks(monkeypatch), clock


def _turn(hooks, clock, n, platform="desktop", session="s1", calls=2, run_min=1.0):
    out = hooks["pre_llm_call"](session_id=session, turn_id=f"t{n}", platform=platform)
    for _ in range(calls):
        hooks["post_tool_call"](tool_name="read_file", result="ok",
                                session_id=session, turn_id=f"t{n}")
    clock.t += run_min * MIN
    hooks["on_session_end"](session_id=session, turn_id=f"t{n}", completed=True,
                            failed=False, interrupted=False, platform=platform)
    return out


def test_on_session_end_is_registered(env):
    hooks, _ = env
    assert "on_session_end" in hooks


def test_an_offer_arrives_as_context_after_a_block(env):
    hooks, clock = env
    offers = []
    for n in range(12):
        out = _turn(hooks, clock, n)
        if out:
            offers.append(out["context"])
        clock.t += 2 * MIN
    assert len(offers) == 1
    ctx = offers[0]
    assert ctx.startswith("[Kairos]")
    assert "carry on with the user's request" in ctx
    assert "kairos_pomodoro" in ctx
    assert "\u25cf\u25cb\u25cb\u25cb" in ctx


def test_turn_facts_are_recorded(env):
    hooks, clock = env
    _turn(hooks, clock, 0, calls=5, run_min=3)
    s = pomodoro.parse_state(storage.get_pomodoro_state())
    assert (s["last_turn_calls"], s["last_turn_min"], s["last_turn_ok"]) == (5, 3, True)


def test_cron_turns_leave_the_clock_alone(env):
    hooks, clock = env
    _turn(hooks, clock, 0)
    before = storage.get_pomodoro_state()
    clock.t += 30 * MIN
    _turn(hooks, clock, 1, platform="cron", session="cron-1")
    assert storage.get_pomodoro_state() == before


def test_the_wind_down_still_wins_the_turn(env, monkeypatch):
    hooks, clock = env
    monkeypatch.setattr(kairos._winddown, "should_nudge", lambda **kw: {
        "night": "n", "rung": "approach", "text": "WIND"})
    monkeypatch.setattr(storage, "record_nudge", lambda *a: None)
    outs = []
    for n in range(12):
        outs.append(_turn(hooks, clock, n))
        clock.t += 2 * MIN
    assert all("WIND" in o["context"] for o in outs)
    # ...and the clock kept moving underneath it.
    s = pomodoro.parse_state(storage.get_pomodoro_state())
    assert s["last_human_at"] >= clock.t - 5 * MIN
