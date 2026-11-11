"""Cron and subagent turns are not the user working (D4).

A cron job at 03:00 must not receive a wind-down nudge or consume the
handoff meant for the user's next session, and a subagent's tool failures
must not count toward the thrash detector or the activity table.

Run with:  python -m pytest tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import kairos  # noqa: E402
from kairos import storage  # noqa: E402


class _Ctx:
    """Just enough of the plugin context to capture the hooks."""

    def __init__(self):
        self.hooks = {}
        self.tools = []

    def register_tool(self, **kw):
        self.tools.append(kw["name"])

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_skill(self, *_a, **_kw):
        pass


def _register(monkeypatch):
    monkeypatch.setattr(kairos._wtools, "bind_ctx", lambda ctx: None)
    ctx = _Ctx()
    kairos.register(ctx)
    return ctx


def _hooks(monkeypatch):
    return _register(monkeypatch).hooks


def _forbid_storage(monkeypatch):
    """Record storage calls. The hooks swallow exceptions, so raising proves nothing."""
    calls = []
    for name in ("recent_outcomes", "record_outcome", "upsert_activity", "connect"):
        monkeypatch.setattr(
            storage, name, lambda *_a, _n=name, **_kw: calls.append(_n) or []
        )
    return calls


def test_predicate():
    assert kairos._human_turn(platform="desktop")
    assert kairos._human_turn(platform="")
    assert kairos._human_turn()
    assert not kairos._human_turn(platform="cron")
    assert not kairos._human_turn(platform="subagent")
    assert not kairos._human_turn(platform="desktop", parent_session_id="abc")


def test_cron_turn_gets_no_moment_and_touches_nothing(monkeypatch):
    hooks = _hooks(monkeypatch)
    calls = _forbid_storage(monkeypatch)
    out = hooks["pre_llm_call"](session_id="cron-1", turn_id="t1", platform="cron")
    assert out is None
    assert calls == []


def test_subagent_turn_gets_no_moment(monkeypatch):
    hooks = _hooks(monkeypatch)
    calls = _forbid_storage(monkeypatch)
    out = hooks["pre_llm_call"](
        session_id="child-1", turn_id="t1", platform="cli", parent_session_id="p"
    )
    assert out is None
    assert calls == []


def test_tool_calls_in_a_non_human_session_are_not_recorded(monkeypatch):
    hooks = _hooks(monkeypatch)
    calls = _forbid_storage(monkeypatch)
    # post_tool_call carries no platform: the session must have been seen as
    # non-human by pre_llm_call first.
    hooks["pre_llm_call"](session_id="cron-2", turn_id="t1", platform="cron")
    hooks["post_tool_call"](
        tool_name="terminal", result="error: boom", session_id="cron-2", turn_id="t1"
    )
    assert calls == []


def test_tool_calls_in_a_human_session_are_recorded(monkeypatch):
    hooks = _hooks(monkeypatch)
    seen = []
    monkeypatch.setattr(storage, "record_outcome", lambda t, e: seen.append((t, e)))
    monkeypatch.setattr(storage, "upsert_activity", lambda *a, **k: None)
    monkeypatch.setattr(kairos._activity, "minutes_past_target", lambda now: None)
    hooks["post_tool_call"](
        tool_name="terminal", result="ok", session_id="human-1", turn_id="t1"
    )
    assert seen == [("terminal", False)]
