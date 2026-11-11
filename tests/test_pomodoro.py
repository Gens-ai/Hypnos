"""The timer that doesn't tick: stretch clock, boundary facts, gates, copy.

Everything here is pure: state goes in, state or a decision comes out. The
storage-backed wrapper in pomodoro.py is exercised by the manual checklist.

Run with:  python -m pytest tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kairos import pomodoro  # noqa: E402

CFG = {"work_min": 25, "break_min": 5, "away_min": 8}


def _state(**kw):
    s = pomodoro.blank_state()
    s.update(kw)
    return s


# ------------------------------------------------------------ stretch clock


def test_first_touch_starts_the_stretch():
    out = pomodoro.touch(_state(), CFG, now=5000.0)
    assert out["stretch_start"] == 5000.0
    assert out["last_human_at"] == 5000.0
    assert out["last_reset_reason"] == ""


def test_short_gap_keeps_the_stretch():
    s = _state(stretch_start=1000.0, last_human_at=1000.0 + 20 * 60)
    out = pomodoro.touch(s, CFG, now=1000.0 + 24 * 60)
    assert out["stretch_start"] == 1000.0
    assert out["last_human_at"] == 1000.0 + 24 * 60


def test_away_gap_resets_stretch_and_ignored_streak():
    s = _state(stretch_start=1000.0, last_human_at=1000.0 + 20 * 60,
               ignored_streak=2, blocks_done=2)
    now = 1000.0 + 20 * 60 + CFG["away_min"] * 60
    out = pomodoro.touch(s, CFG, now=now)
    assert out["stretch_start"] == now
    assert out["ignored_streak"] == 0
    assert out["blocks_done"] == 2  # short rest keeps the cycle
    assert out["last_reset_reason"] == "away 8m"


def test_long_gap_resets_cycle():
    s = _state(stretch_start=1000.0, last_human_at=1000.0 + 20 * 60, blocks_done=3)
    out = pomodoro.touch(s, CFG, now=1000.0 + 20 * 60 + pomodoro.LONG_REST_MIN * 60)
    assert out["blocks_done"] == 0


def test_agent_run_between_human_actions_is_a_rest():
    # You sent it on a 15-minute task and came back when it finished. The agent
    # was busy the whole time; YOU were not. That is a rest.
    t0 = 1000.0 + 20 * 60
    s = _state(stretch_start=1000.0, last_human_at=t0, last_turn_ended=t0 + 15 * 60)
    out = pomodoro.touch(s, CFG, now=t0 + 15 * 60 + 30)
    assert out["stretch_start"] == t0 + 15 * 60 + 30


def test_idle_after_handback_is_a_rest_at_the_shorter_threshold():
    # A by-the-book five: the agent finished, then nothing happened for break_min.
    t0 = 1000.0 + 20 * 60
    s = _state(stretch_start=1000.0, last_human_at=t0, last_turn_ended=t0 + 90)
    now = t0 + 90 + CFG["break_min"] * 60 + 10
    out = pomodoro.touch(s, CFG, now=now)
    assert out["stretch_start"] == now
    assert out["last_reset_reason"] == "idle 5m"


def test_idle_rule_cannot_fire_while_the_turn_is_still_running():
    # last_turn_ended predates your last message: that turn is still going
    # (or ended in another session). Only the away rule may judge this gap.
    t0 = 1000.0 + 20 * 60
    s = _state(stretch_start=1000.0, last_human_at=t0, last_turn_ended=t0 - 60)
    out = pomodoro.touch(s, CFG, now=t0 + 6 * 60)  # 6 < away_min, > break_min
    assert out["stretch_start"] == 1000.0


def test_stop_then_walk_away_is_idle():
    # Hitting stop touches the clock and ends the turn at the same instant.
    t0 = 1000.0 + 20 * 60
    s = _state(stretch_start=1000.0, last_human_at=t0, last_turn_ended=t0)
    now = t0 + 6 * 60
    assert pomodoro.touch(s, CFG, now=now)["stretch_start"] == now


def test_raising_away_min_keeps_a_watched_run_in_the_stretch():
    t0 = 1000.0 + 20 * 60
    s = _state(stretch_start=1000.0, last_human_at=t0, last_turn_ended=t0 + 12 * 60)
    watcher = dict(CFG, away_min=15)
    out = pomodoro.touch(s, watcher, now=t0 + 12 * 60 + 20)
    assert out["stretch_start"] == 1000.0


def test_rest_clears_a_pending_hold():
    # A hold from the last block must not make the next one fire on patience.
    s = _state(stretch_start=1000.0, last_human_at=2000.0, pending_since=1900.0)
    out = pomodoro.touch(s, CFG, now=2000.0 + 9 * 60)
    assert out["pending_since"] == 0.0


def test_rests_are_counted_per_night():
    s = _state(stretch_start=1000.0, last_human_at=2000.0,
               resets_night="2026-11-10", resets_today=2)
    out = pomodoro.touch(s, CFG, now=2000.0 + 9 * 60, night="2026-11-10")
    assert out["resets_today"] == 3
    out = pomodoro.touch(s, CFG, now=2000.0 + 9 * 60, night="2026-11-11")
    assert (out["resets_night"], out["resets_today"]) == ("2026-11-11", 1)


def test_a_long_absence_lifts_not_today():
    # "not today" lasts until you have plainly been gone a while (slept, left),
    # whatever the clock says -- a 05:00 rollover would end it mid-session for
    # anyone who works nights.
    s = _state(stretch_start=1000.0, last_human_at=2000.0, paused=1)
    assert pomodoro.touch(s, CFG, now=2000.0 + 60 * 60)["paused"] == 1
    later = 2000.0 + pomodoro.PAUSE_LIFTS_AFTER_H * 3600
    assert pomodoro.touch(s, CFG, now=later)["paused"] == 0


def test_stretch_minutes():
    assert pomodoro.stretch_min(_state(stretch_start=1000.0), now=1000.0 + 52 * 60) == 52
    assert pomodoro.stretch_min(_state(), now=1000.0) == 0


def test_config_clamps_to_the_settings_ranges():
    cfg = pomodoro.config({"pomodoro_enabled": "true", "pomodoro_work_min": "500",
                           "pomodoro_break_min": "1", "pomodoro_away_min": "x"})
    assert cfg["enabled"] is True
    assert (cfg["work_min"], cfg["break_min"], cfg["away_min"]) == (120, 3, 8)
    assert pomodoro.config({})["enabled"] is False


def test_state_round_trips_through_strings():
    s = _state(stretch_start=1.5, blocks_done=2, last_turn_ok=False,
               last_reset_reason="idle 6m")
    raw = {k: str(v) for k, v in pomodoro.dump_state(s).items()}
    assert pomodoro.parse_state(raw) == s


def test_not_today_has_a_hard_backstop():
    # Someone who never steps away for three hours still gets it back.
    s = _state(stretch_start=1000.0, last_human_at=2000.0, paused=1, paused_until=2100.0)
    assert pomodoro.touch(s, CFG, now=2200.0)["paused"] == 0


# ------------------------------------------------------------ boundary facts

OK = [{"tool": "terminal", "error": False, "at": 0}] * 3
BAD = OK + [{"tool": "terminal", "error": True, "at": 0}]
T = 100_000.0


def test_clean_ok_and_a_pause_is_a_boundary():
    s = _state(last_turn_ended=T - 180, last_turn_ok=True, last_turn_calls=7,
               last_turn_min=3)
    b = pomodoro.boundary_state(OK, s, now=T)
    assert b["at_boundary"]
    assert (b["last_turn_calls"], b["last_turn_min"]) == (7, 3)
    assert b["observed"]


def test_tight_loop_is_not_a_boundary():
    s = _state(last_turn_ended=T - 20)
    b = pomodoro.boundary_state(OK, s, now=T)
    assert not b["at_boundary"] and b["tight_loop"]


def test_instant_reply_after_a_long_run_is_not_a_boundary():
    # Idle is measured from handback, not from your last message: a 3-minute
    # run answered 10 s after it finished is someone waiting on it.
    s = _state(last_human_at=T - 190, last_turn_ended=T - 10)
    assert not pomodoro.boundary_state(OK, s, now=T)["at_boundary"]


def test_stopped_turn_is_not_a_boundary():
    s = _state(last_turn_ended=T - 300, last_turn_ok=False)
    assert not pomodoro.boundary_state(OK, s, now=T)["at_boundary"]


def test_failures_are_not_a_boundary():
    s = _state(last_turn_ended=T - 300)
    b = pomodoro.boundary_state(BAD, s, now=T)
    assert not b["at_boundary"] and not b["clean"]


# ------------------------------------------------------------------- gates

ON = dict(pomodoro.config({"pomodoro_enabled": "true", "tone": "encouraging"}))


def _ask(state=None, recent=OK, cfg=ON, **kw):
    args = dict(now=T, state=state or _due(), recent=recent, cfg=cfg,
                snoozed=False, bedtime_delta=None, last_break_at=None)
    args.update(kw)
    return pomodoro.should_suggest_pomodoro(**args)


def _due(minutes=25, **kw):
    base = dict(stretch_start=T - minutes * 60, last_human_at=T - 240,
                last_turn_ended=T - 180, last_turn_ok=True)
    base.update(kw)
    return _state(**base)


def test_due_at_a_boundary_speaks():
    out = _ask()
    assert out["speak"]
    assert (out["block"], out["long_rest"], out["repeat"]) == (1, False, 0)
    assert out["clean"] is True
    assert out["next_blocks_done"] == 1


def test_disabled_is_silent():
    out = _ask(cfg=dict(ON, enabled=False))
    assert not out["speak"] and out["why"]


def test_tone_off_is_silent():
    assert not _ask(cfg=dict(ON, tone="off"))["speak"]


def test_snoozed_is_silent():
    assert not _ask(snoozed=True)["speak"]


def test_paused_is_silent():
    assert not _ask(state=_due(paused=1))["speak"]


def test_bedtime_band_belongs_to_the_wind_down():
    assert not _ask(bedtime_delta=-30)["speak"]
    assert not _ask(bedtime_delta=100)["speak"]
    assert _ask(bedtime_delta=-300)["speak"]


def test_not_due_until_the_block_is_up():
    assert not _ask(state=_due(24))["speak"]
    assert _ask(state=_due(25))["speak"]


def test_three_ignored_offers_go_quiet():
    assert not _ask(state=_due(ignored_streak=3))["speak"]


def test_a_recent_break_offer_counts_as_this_block():
    assert not _ask(last_break_at=T - 10 * 60)["speak"]
    assert _ask(last_break_at=T - 30 * 60)["speak"]


def test_mid_flight_holds():
    out = _ask(state=_due(last_turn_ended=T - 15))
    assert not out["speak"] and out["hold"]


def test_patience_exhausted_speaks_anyway():
    s = _due(last_turn_ended=T - 15, pending_since=T - ON["patience_min"] * 60)
    out = _ask(state=s)
    assert out["speak"] and out["clean"] is False


def test_gentle_never_speaks_mid_flight():
    s = _due(last_turn_ended=T - 15, pending_since=T - 999 * 60)
    out = _ask(state=s, cfg=dict(ON, tone="gentle"))
    assert not out["speak"]


def test_not_holding_for_a_clean_break_speaks_mid_flight():
    out = _ask(state=_due(last_turn_ended=T - 15), cfg=dict(ON, prefer_clean=False))
    assert out["speak"]


def test_the_fourth_block_is_the_long_rest():
    out = _ask(state=_due(blocks_done=3))
    assert (out["block"], out["long_rest"], out["next_blocks_done"]) == (4, True, 0)


def test_repeat_follows_the_ignored_streak():
    assert _ask(state=_due(ignored_streak=2))["repeat"] == 2
