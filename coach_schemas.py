"""Hypnos tool schemas (coaching surface)."""

HYPNOS_GOAL = {
    "name": "hypnos_goal",
    "description": (
        "Read or set the user's own sleep targets: bedtime, duration, an optional "
        "gradual-shift goal, tone, and morning check-in. There is no correct "
        "bedtime — 02:30 is as valid as 22:00, and Hypnos stays silent until the "
        "user sets one. Use when they describe what they want their sleep to look "
        "like ('I want to be in bed by 1', 'aiming for 8 hours')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "set", "start_ramp", "stop_ramp"],
                "description": "Default 'get'.",
            },
            "target_bedtime": {
                "type": "string",
                "description": "The bedtime they're aiming for now, 'HH:MM'.",
            },
            "target_duration_min": {
                "type": "integer",
                "description": "Hours of sleep they want, in minutes (450 = 7h30).",
            },
            "goal_bedtime": {
                "type": "string",
                "description": (
                    "An eventual bedtime to drift toward, 'HH:MM'. Combined with "
                    "start_ramp, Hypnos moves the target gradually."
                ),
            },
            "ramp_min_per_week": {
                "type": "integer",
                "description": "Minutes per week to shift the target. Default 15.",
            },
            "tone": {
                "type": "string",
                "enum": ["off", "gentle", "encouraging", "firm", "guardian"],
                "description": (
                    "How present the wind-down nudges are. 'gentle' (default) "
                    "speaks once, near bedtime, only at a clean stopping point."
                ),
            },
            "checkin_enabled": {
                "type": "boolean",
                "description": "Whether the morning check-in cron is wanted.",
            },
            "checkin_time": {"type": "string", "description": "'HH:MM' local."},
            "checkin_channel": {
                "type": "string",
                "description": "'desktop' for a notification, or a messaging target.",
            },
        },
    },
}

HYPNOS_COMMITMENT = {
    "name": "hypnos_commitment",
    "description": (
        "Record or clear something that genuinely needs an early start — a flight, "
        "a trip, an appointment. Hypnos works backwards from the wake time and "
        "eases the bedtime shift over the nights beforehand, then returns to the "
        "user's normal target. Use when they mention upcoming plans with a time "
        "('flight at 7 on Saturday', 'need to be up at 6 Tuesday')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove"],
                "description": "Default 'list'.",
            },
            "on_date": {"type": "string", "description": "ISO date of the obligation."},
            "wake_by": {
                "type": "string",
                "description": "'HH:MM' they need to be up by that morning.",
            },
            "label": {"type": "string", "description": "What it is, e.g. 'Flight to NYC'."},
            "prep_days": {
                "type": "integer",
                "description": (
                    "Nights to spread the shift across, including the night that "
                    "counts. Default 1 (no easing). 3 is kind for a big shift."
                ),
            },
            "id": {"type": "integer", "description": "For action='remove'."},
        },
    },
}

HYPNOS_WINDDOWN = {
    "name": "hypnos_winddown",
    "description": (
        "Check whether a wind-down nudge is due right now, mute tonight, or save "
        "the current thread so the user can stop cleanly. Call with "
        "action='snooze' the moment they say 'not tonight' or similar — honour it "
        "without comment. action='handoff' writes up where the work got to."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "snooze", "handoff"],
                "description": "Default 'status'.",
            },
            "summary": {
                "type": "string",
                "description": (
                    "For action='handoff': what was being worked on, where it "
                    "stopped, and the obvious next step."
                ),
            },
        },
    },
}

HYPNOS_CHECKIN = {
    "name": "hypnos_checkin",
    "description": (
        "Run or answer the morning check-in: one question, never a questionnaire. "
        "It never opens with a missed target — it asks how they slept. Use "
        "action='ask' from the scheduled job, action='answer' when they reply."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ask", "answer"],
                "description": "Default 'ask'.",
            },
            "answer": {
                "type": "string",
                "description": "Their reply, in their own words.",
            },
        },
    },
}
