"""The storage-backed pomodoro flow, end to end, on an in-memory database.

Walks the clock through real sequences of messages and turn ends -- the
gates are covered in test_pomodoro.py; this is about the wiring between
them and the persisted state.

Run with:  python -m pytest tests/
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kairos import goals, pomodoro, storage  # noqa: E402

MIN = 60.0
T0 = 1_800_000_000.0  # a fixed instant; nights are derived from it
NIGHT = None


@pytest.fixture(autouse=True)
def db(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.executescript(storage._SCHEMA)
    monkeypatch.setattr(storage, "connect", lambda: con)
    # No bedtime target in this database, so no bedtime band to stay out of.
    yield con


def _enable(**kw):
    goals.set_goals(pomodoro_enabled=True, tone=kw.pop("tone", "encouraging"), **kw)


def _state():
    return pomodoro.parse_state(storage.get_pomodoro_state())


def _work(start, until, step=3 * MIN):
    """Tight but thoughtful loop: a message, a 1-minute turn, a 2-minute read."""
    t = start
    out = []
    while t < until:
        out.append(pomodoro.on_user_turn(t, recent=[]))
        pomodoro.on_turn_end(t + MIN, completed=True, interrupted=False, failed=False,
                             calls=4, turn_min=1)
        t += step
    return t, [o for o in out if o]


def test_disabled_writes_nothing():
    assert pomodoro.on_user_turn(T0, recent=[]) is None
    pomodoro.on_turn_end(T0 + MIN, completed=True, interrupted=False, failed=False,
                         calls=1, turn_min=1)
    assert storage.get_pomodoro_state() == {}


def test_one_offer_per_block():
    _enable()
    t, offers = _work(T0, T0 + 30 * MIN)
    assert len(offers) == 1
    assert "\u25cf\u25cb\u25cb\u25cb" in offers[0]["text"]
    s = _state()
    assert s["ignored_streak"] == 1 and s["blocks_done"] == 1
    assert s["last_reset_reason"] == "offer"
    assert storage.moment_count("pomodoro", offers[0]["night"]) == 1


def test_three_ignored_offers_then_quiet():
    _enable()
    t, offers = _work(T0, T0 + 140 * MIN)
    assert len(offers) == 3
    assert [o["repeat"] for o in offers] == [0, 1, 2]
    st = pomodoro.status(t, recent=[])
    assert not st["due"] and "untaken" in st["why_silent"]


def test_an_idle_rest_restarts_the_count():
    _enable()
    t, offers = _work(T0, T0 + 30 * MIN)
    assert len(offers) == 1
    # They took it: nothing for six minutes after the last handback, which
    # was one minute after their last message -- 7 min, under away_min.
    t = (t - 3 * MIN) + MIN + 6 * MIN
    pomodoro.on_user_turn(t, recent=[])
    s = _state()
    assert s["ignored_streak"] == 0 and s["stretch_start"] == t
    assert s["last_reset_reason"].startswith("idle")
    assert s["blocks_done"] == 1  # short rest: the cycle carries on


def test_a_silent_long_run_is_a_rest_not_a_stretch():
    _enable()
    pomodoro.on_user_turn(T0, recent=[])
    # Sent it off on a 20-minute job, came back 30 s after it finished.
    pomodoro.on_turn_end(T0 + 20 * MIN, completed=True, interrupted=False,
                         failed=False, calls=40, turn_min=20)
    assert pomodoro.on_user_turn(T0 + 20.5 * MIN, recent=[]) is None
    assert _state()["last_reset_reason"].startswith("away")


def test_mid_flight_holds_then_patience_speaks():
    _enable(clean_break_patience_min=10)
    pomodoro.on_user_turn(T0, recent=[])
    # Ping-pong: every reply lands 20 s after handback.
    t = T0
    offers = []
    while t < T0 + 45 * MIN:
        pomodoro.on_turn_end(t + 2 * MIN, completed=True, interrupted=False,
                             failed=False, calls=2, turn_min=2)
        t += 2 * MIN + 20
        out = pomodoro.on_user_turn(t, recent=[])
        if out:
            offers.append((t, out))
    assert len(offers) == 1
    fired_at, out = offers[0]
    assert out["clean"] is False and "back and forth" in out["text"]
    assert fired_at - T0 >= (25 + 10) * MIN


def test_gentle_holds_forever_mid_flight():
    _enable(tone="gentle", clean_break_patience_min=5)
    t = T0
    pomodoro.on_user_turn(t, recent=[])
    for _ in range(30):
        pomodoro.on_turn_end(t + 2 * MIN, completed=True, interrupted=False,
                             failed=False, calls=2, turn_min=2)
        t += 2 * MIN + 20
        assert pomodoro.on_user_turn(t, recent=[]) is None


def test_another_moment_this_turn_still_moves_the_clock():
    _enable()
    pomodoro.on_user_turn(T0, recent=[])
    pomodoro.on_turn_end(T0 + MIN, completed=True, interrupted=False, failed=False,
                         calls=1, turn_min=1)
    out = pomodoro.on_user_turn(T0 + 30 * MIN, recent=[], may_speak=False)
    assert out is None
    assert _state()["last_human_at"] == T0 + 30 * MIN


def test_stop_is_a_human_action():
    _enable()
    pomodoro.on_user_turn(T0, recent=[])
    pomodoro.on_turn_end(T0 + 4 * MIN, completed=False, interrupted=True, failed=False,
                         calls=3, turn_min=4)
    s = _state()
    assert s["last_human_at"] == T0 + 4 * MIN and s["last_turn_ok"] is False


def test_declared_rest():
    _enable()
    _work(T0, T0 + 30 * MIN)
    out = pomodoro.declare_rest(T0 + 31 * MIN, minutes=25)
    assert out["long_rest"] is True
    s = _state()
    assert (s["ignored_streak"], s["blocks_done"]) == (0, 0)
    assert s["last_reset_reason"] == "rest declared"
    assert storage.moment_count("pomodoro_rest", out["night"]) == 1


def test_skip_today_pauses_until_a_long_absence():
    _enable()
    pomodoro.on_user_turn(T0, recent=[])
    pomodoro.skip(T0 + MIN, scope="today")
    _, offers = _work(T0 + 2 * MIN, T0 + 80 * MIN)
    assert offers == []
    assert "not today" in pomodoro.status(T0 + 80 * MIN, recent=[])["why_silent"]
    pomodoro.on_user_turn(T0 + 80 * MIN + 5 * 3600, recent=[])
    assert _state()["paused"] == 0


def test_status_is_read_only_and_explains():
    _enable()
    pomodoro.on_user_turn(T0, recent=[])
    before = storage.get_pomodoro_state()
    st = pomodoro.status(T0 + 10 * MIN, recent=[])
    assert storage.get_pomodoro_state() == before
    assert st["enabled"] and st["stretch_min"] == 10 and st["block"] == "1 of 4"
    assert "10 of 25" in st["why_silent"]
    for key in ("at_boundary", "ignored_streak", "last_reset_reason",
                "offers_today", "resets_today"):
        assert key in st
