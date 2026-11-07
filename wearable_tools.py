"""Wearable sync and the out-of-session bedtime ping.

Two capabilities that both exist because Hypnos should be useful when you are
*not* talking to Hermes:

``hypnos_wearable`` reads sleep from a health MCP server the user already
runs, so nobody has to type last night in by hand.

``hypnos_ping`` is what a cron job calls. The ``pre_llm_call`` nudge only
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
from . import sources as _sources
from . import storage as _storage
from . import winddown as _winddown

# Set by register() so tools can reach ctx.call_mcp.
_CTX: Any = None


def bind_ctx(ctx: Any) -> None:
    global _CTX
    _CTX = ctx


def _err(msg: str, **extra: Any) -> str:
    return _json.dumps({"success": False, "error": msg, **extra}, indent=2)


def hypnos_wearable(params: dict[str, Any]) -> str:
    """probe | sync | status | configure a health MCP server as a sleep source."""
    action = (params.get("action") or "status").lower()
    g = _goals.get_goals()

    if action == "presets":
        return _json.dumps({
            "success": True,
            "presets": _sources.PRESETS,
            "how_to": (
                "Pick the server you already have installed, then grant it to "
                "Hypnos in config.yaml under "
                "plugins.entries.hypnos.mcp_allowlist: [\"<server>\"]. "
                "Then run action='probe' to confirm the shape before syncing."
            ),
        }, indent=2)

    if action == "configure":
        server = (params.get("server") or "").strip()
        if not server:
            return _err("configure needs a server name. See action='presets'.")
        tool = (params.get("tool") or "").strip()
        if not tool:
            tool = str(_sources.PRESETS.get(server, {}).get("tool") or "")
        if not tool:
            return _err(f"No preset tool for '{server}' — pass tool= explicitly.")
        args = params.get("args")
        if isinstance(args, str):
            try:
                args = _json.loads(args)
            except ValueError:
                return _err("args must be a JSON object.")
        if args is None:
            args = _sources.PRESETS.get(server, {}).get("args") or {}
        _goals.set_goals(
            wearable_server=server,
            wearable_tool=tool,
            wearable_args=_json.dumps(args),
            wearable_enabled=True,
        )
        return _json.dumps({
            "success": True,
            "configured": {"server": server, "tool": tool, "args": args},
            "next": "Run action='probe' to check Hypnos can actually read it.",
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
            "recent_wearable_nights": [
                r for r in _storage.list_sleep(limit=14)
                if r.get("source", "").startswith("mcp:")
            ][:7],
        }, indent=2, default=str)

    if action not in ("probe", "sync"):
        return _err("action must be presets, configure, probe, sync, status or disable")
    if not server or not tool:
        return _err(
            "No wearable source configured. Run action='presets' to see the "
            "health MCP servers Hypnos knows about, then action='configure'."
        )

    raw_args = params.get("args") or g.get("wearable_args") or "{}"
    try:
        args = _json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except ValueError:
        args = {}

    res = _sources.fetch(_CTX, server, tool, args)
    if not res.get("ok"):
        return _err(res.get("error", "unknown error"), server=server, tool=tool)

    nights = res["nights"]
    if action == "probe":
        return _json.dumps({
            "success": True,
            "server": server,
            "tool": tool,
            "nights_parsed": len(nights),
            "nights": nights[-7:],
            "raw_preview": res["raw_preview"],
            "verdict": (
                f"Parsed {len(nights)} night(s). Nothing was written — run "
                f"action='sync' when the numbers look right."
                if nights else
                "Parsed nothing. Check raw_preview: the tool may need "
                "different args, or the response may not contain sleep rows."
            ),
        }, indent=2, default=str)

    added = updated = skipped = 0
    conflicts: list[dict[str, Any]] = []
    for n in nights:
        out = _storage.upsert_sleep(
            n["night"], n["duration_min"],
            sleep_start=n.get("sleep_start"), sleep_end=n.get("sleep_end"),
            wake_count=n.get("wake_count"),
            source=f"mcp:{server}", note=None, protect_manual=True,
        )
        if out["status"] == "inserted":
            added += 1
        elif out["status"] == "updated":
            updated += 1
        else:
            skipped += 1
            prev = out["previous"] or {}
            if prev.get("duration_min") != n["duration_min"]:
                conflicts.append({
                    "night": n["night"],
                    "you_logged_min": prev.get("duration_min"),
                    "device_says_min": n["duration_min"],
                })

    _goals.set_goals(wearable_last_sync=_dt.datetime.now().isoformat(timespec="seconds"))
    return _json.dumps({
        "success": True,
        "server": server,
        "added": added,
        "updated": updated,
        "skipped_you_logged_these": skipped,
        "conflicts": conflicts,
        "note": (
            "Your own entries are never overwritten. Where the device "
            "disagrees it is listed above so you can decide."
            if conflicts else None
        ),
    }, indent=2, default=str)


def hypnos_ping(params: dict[str, Any]) -> str:
    """Evaluate the wind-down gates out of session. Silent unless one is due.

    Called by a cron job, so it must be cheap and it must say nothing at all
    when nothing is due — cron refuses to deliver an empty payload, which is
    exactly the behaviour we want.
    """
    dry = bool(params.get("dry_run"))
    now = _dt.datetime.now()

    # Out of session there is no in-flight work to interrupt, so the
    # clean-break machinery has nothing to weigh; an empty history reads as
    # "at rest", which is the honest description of someone not working.
    due = _winddown.should_nudge(now=now, recent=[], cwd=None)
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
        return "No target bedtime set, so Hypnos has nothing to measure against."
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
