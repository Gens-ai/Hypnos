"""Hypnos backend routes — mounted at /api/plugins/hypnos/.

Runs inside the gateway process, so it can import the plugin's own modules.
Read-only except for POST /sleep, which is the same upsert the agent tool uses.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()

# The plugin package sits one level up from dashboard/.
_PKG_ROOT = Path(__file__).resolve().parent.parent
_PARENT = str(_PKG_ROOT.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

_PKG = _PKG_ROOT.name  # "hypnos"


def _mod(name: str):
    return importlib.import_module(f"{_PKG}.{name}")


@router.get("/summary")
async def summary(days: int = 60) -> dict[str, Any]:
    """Everything the pane needs in one round trip."""
    days = max(1, min(int(days), 365))
    try:
        activity = _mod("activity")
        analysis = _mod("analysis")
        storage = _mod("storage")

        activity.sync_activity(days=days)
        hist = activity.hour_histogram(days=days)
        sleep_rows = storage.list_sleep(limit=days)
        act_rows = storage.list_activity(limit=days)
        result = analysis.analyze(sleep_rows, act_rows)

        total = sum(hist.values())
        night = sum(v for h, v in hist.items() if h >= 23 or h < 5)
        peak = max(hist.items(), key=lambda kv: kv[1])[0] if total else None

        return {
            "ok": True,
            "hour_histogram": hist,
            "peak_hour": peak,
            "after_11pm_share": round(night / total, 3) if total else 0.0,
            "guard": storage.get_guard_config(),
            "recent_sleep": [
                {
                    "night": r["night"],
                    "duration_min": r["duration_min"],
                    "quality": r.get("quality"),
                    "source": r.get("source"),
                }
                for r in sleep_rows[:21]
            ],
            "recent_activity": [
                {
                    "day": r["day"],
                    "late_minutes": r["late_minutes"],
                    "tool_calls": r["tool_calls"],
                    "terminal_calls": r["terminal_calls"],
                }
                for r in act_rows[:21]
            ],
            "analysis": result,
        }
    except Exception as exc:  # degrade, never 500 the pane
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class SleepBody(BaseModel):
    duration: str = Field(..., description="e.g. '7h20m', '6.5h', '400m', '7:20'")
    night: Optional[str] = None
    quality: Optional[int] = None
    wake_count: Optional[int] = None
    note: Optional[str] = None


@router.post("/sleep")
async def log_sleep(body: SleepBody) -> dict[str, Any]:
    """Log a night from the pane. Same validation path as the agent tool."""
    try:
        tools = _mod("tools")
        import json as _json  # noqa: PLC0415

        raw = tools.sleep_log(
            {
                "duration": body.duration,
                "night": body.night,
                "quality": body.quality,
                "wake_count": body.wake_count,
                "note": body.note,
            }
        )
        out = _json.loads(raw)
        if out.get("success"):
            try:
                from hermes_cli.plugin_events import (  # noqa: PLC0415
                    broadcast_plugin_event,
                )

                broadcast_plugin_event(
                    "hypnos", "sleep.logged", {"night": out.get("night")}
                )
            except Exception:
                pass
        return out
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


class GuardBody(BaseModel):
    action: str = "status"
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    mode: Optional[str] = None


@router.post("/guard")
async def guard(body: GuardBody) -> dict[str, Any]:
    try:
        tools = _mod("tools")
        import json as _json  # noqa: PLC0415

        return _json.loads(tools.hypnos_guard(body.model_dump(exclude_none=True)))
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
