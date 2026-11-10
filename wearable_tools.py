"""Wearable sync and the out-of-session bedtime ping.

Two capabilities that both exist because Kairos should be useful when you are
*not* talking to Hermes:

``kairos_wearable`` reads sleep from a health MCP server the user already
runs, so nobody has to type last night in by hand.

``kairos_ping`` is what a cron job calls. The ``pre_llm_call`` nudge only
reaches you mid-conversation, which is no use if you have shut the laptop and
picked up your phone. A scheduled ping evaluates exactly the same gates and
prints the nudge only when one is genuinely due, so cron's empty-payload rule
means silence costs nothing.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
from typing import Any, Optional

from . import goals as _goals
from . import storage as _storage
from . import winddown as _winddown

# Set by register() so tools can reach ctx.call_mcp.
_CTX: Any = None


def bind_ctx(ctx: Any) -> None:
    global _CTX
    _CTX = ctx


def _err(msg: str, **extra: Any) -> str:
    return _json.dumps({"success": False, "error": msg, **extra}, indent=2)


def kairos_wearable(params: dict[str, Any]) -> str:
    """Configure and read a server-backed sleep source (MCP health servers).

    File-based bridges go through ``sleep_import``; this one owns the
    sources that need a live call. Both end in ``normalize.ingest``, so the
    manual-protection and plausibility rules are the same either way.
    """
    from . import sleep_sources as _src  # noqa: PLC0415

    action = (params.get("action") or "status").lower()
    g = _goals.get_goals()

    if action in ("presets", "sources"):
        return _json.dumps({
            "success": True,
            "sources": _src.describe_sources(),
            "mcp_presets": _src.McpSource.PRESETS,
            "how_to": (
                "These preset tool names are informed guesses, not verified "
                "against live servers. Grant the server in config.yaml under "
                "plugins.entries.kairos.mcp_allowlist, then run action='probe' "
                "and check what came back before importing anything."
            ),
        }, indent=2)

    if action == "configure":
        server = (params.get("server") or "").strip()
        if not server:
            return _err("configure needs a server name. See action='presets'.")
        tool = (params.get("tool") or "").strip()
        if not tool:
            tool = str(_src.McpSource.PRESETS.get(server, {}).get("tool") or "")
        if not tool:
            return _err(f"No preset tool for '{server}' — pass tool= explicitly.")
        args = params.get("args")
        if isinstance(args, str):
            try:
                args = _json.loads(args)
            except ValueError:
                return _err("args must be a JSON object.")
        if args is None:
            args = _src.McpSource.PRESETS.get(server, {}).get("args") or {}
        _goals.set_goals(
            wearable_server=server,
            wearable_tool=tool,
            wearable_args=_json.dumps(args),
            wearable_enabled=True,
        )
        return _json.dumps({
            "success": True,
            "configured": {"server": server, "tool": tool, "args": args},
            "next": "Run action='probe' — it writes nothing and shows what parsed.",
        }, indent=2)

    if action == "disable":
        _goals.set_goals(wearable_enabled=False)
        return _json.dumps({"success": True, "wearable_enabled": False}, indent=2)

    server = (params.get("server") or g.get("wearable_server") or "").strip()
    tool = (params.get("tool") or g.get("wearable_tool") or "").strip()

    if action == "status":
        return _json.dumps({
            "success": True,
            "enabled": str(g.get("wearable_enabled", "false")).lower() == "true",
            "server": server or None,
            "tool": tool or None,
            "last_sync": g.get("wearable_last_sync") or None,
            "imported_nights": [
                r for r in _storage.list_sleep(limit=21)
                if r.get("source") in ("mcp", "gadgetbridge")
                or str(r.get("source", "")).startswith("mcp:")
            ][:7],
        }, indent=2, default=str)

    if action not in ("probe", "sync"):
        return _err("action must be presets, configure, probe, sync, status or disable")
    if not server:
        return _err(
            "No wearable source configured. Run action='presets' to see what "
            "Kairos knows about, then action='configure'."
        )

    raw_args = params.get("args") or g.get("wearable_args") or "{}"
    try:
        args = _json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except ValueError:
        args = {}

    source = _src.get_source("mcp")
    cfg = {"server": server, "tool": tool, "args": args, "_ctx": _CTX}
    out = source.probe(cfg) if action == "probe" else source.fetch(cfg)
    if not out.get("ok"):
        return _err(out.get("error", "unknown error"), server=server, tool=tool)
    if action == "sync":
        _goals.set_goals(
            wearable_last_sync=_dt.datetime.now().isoformat(timespec="seconds")
        )
        if out.get("conflicts"):
            out["note"] = (
                "Your own entries are never overwritten. Where the device "
                "disagrees it is listed above so you can decide."
            )
    return _json.dumps({"success": True, **out}, indent=2, default=str)


def kairos_ping(params: dict[str, Any]) -> str:
    """Evaluate the wind-down gates out of session. Silent unless one is due.

    Called by a cron job, so it must be cheap and it must say nothing at all
    when nothing is due — cron refuses to deliver an empty payload, which is
    exactly the behaviour we want.
    """
    dry = bool(params.get("dry_run"))
    now = _dt.datetime.now()

    # The settings toggle must actually work, so a user can silence the
    # scheduled ping without hunting down and deleting their cron job.
    g0 = _goals.get_goals()
    if str(g0.get("ping_enabled", "false")).lower() != "true" and not dry:
        return _json.dumps({
            "success": True,
            "nudge": None,
            "say_nothing": True,
            "why": "Scheduled ping is switched off in Kairos settings.",
        }, indent=2)

    # Out of session there is no in-flight work to interrupt, so the
    # clean-break machinery has nothing to weigh; an empty history reads as
    # "at rest", which is the honest description of someone not working.
    due = _winddown.should_nudge(now=now, recent=[])
    if not due:
        g = _goals.get_goals()
        target = _goals.resolve_target(_winddown_night(now))
        return _json.dumps({
            "success": True,
            "nudge": None,
            "say_nothing": True,
            "why": _why_silent(g, target, now),
        }, indent=2, default=str)

    if not dry:
        _storage.record_nudge(due["night"], due["rung"])
    return _json.dumps({
        "success": True,
        "nudge": due["text"],
        "rung": due["rung"],
        "say_nothing": False,
        "delivery": _goals.get_goals().get("nudge_delivery", "inject"),
    }, indent=2, default=str)


def _winddown_night(now: _dt.datetime) -> str:
    from . import activity as _activity

    return _activity.night_of(now.timestamp())


def _why_silent(g: dict[str, Any], target: dict[str, Any], now: _dt.datetime) -> str:
    if target.get("source") == "none" or not target.get("bedtime"):
        return "No target bedtime set, so Kairos has nothing to measure against."
    if target.get("tone") == "off":
        return "Tone is 'off' — measurement only."
    night = _winddown_night(now)
    if _storage.is_snoozed(night):
        return "Snoozed for tonight."
    r = _winddown.current_rung(target["bedtime"], now)
    if not r:
        return f"Nowhere near the {target['bedtime']} target yet."
    last = _storage.last_nudge_at(night)
    if last is not None:
        mins = int((now.timestamp() - last) / 60)
        return f"Already spoke {mins} min ago; inside the {g.get('nudge_gap_min', 45)} min gap."
    return f"Stage '{r[0]}' is not one this tone speaks on."
