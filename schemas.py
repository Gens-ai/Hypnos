"""Model-facing tool schemas."""

SLEEP_LOG = {
    "name": "sleep_log",
    "description": (
        "Record one night's sleep for Kairos. Use when the user mentions how "
        "they slept ('slept about 6 hours', 'woke up twice, feel rough'). Accepts "
        "fuzzy durations like '7h20m', '6.5h' or '7:20'. Defaults to last night."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "duration": {
                "type": "string",
                "description": "Time asleep: '7h20m', '6.5h', '400m' or '7:20'.",
            },
            "night": {
                "type": "string",
                "description": (
                    "ISO date of the night they went to bed (2026-11-07). "
                    "Omit for last night."
                ),
            },
            "quality": {
                "type": "integer",
                "description": "Subjective quality 1 (terrible) to 5 (great).",
            },
            "wake_count": {
                "type": "integer",
                "description": "Number of times they woke up, if mentioned.",
            },
            "note": {
                "type": "string",
                "description": "Anything else they said about the night.",
            },
        },
        "required": ["duration"],
    },
}

SLEEP_IMPORT = {
    "name": "sleep_import",
    "description": (
        "Import nights from a file: a CSV from any tracker, or a Gadgetbridge "
        "SQLite export (Mi Band, Amazfit). The format is auto-detected. Your "
        "own hand-logged nights are never overwritten."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the CSV file."},
            "source": {
                "type": "string",
                "enum": ["auto", "csv", "gadgetbridge", "xiaomi"],
                "description": (
                    "Format. Default 'auto' sniffs the file: a SQLite header "
                    "means gadgetbridge, anything else csv."
                ),
            },
            "probe": {
                "type": "boolean",
                "description": (
                    "Parse and report WITHOUT writing. Always probe an "
                    "unfamiliar export first \u2014 it shows what was understood "
                    "and, for Gadgetbridge, the raw activity-kind histogram."
                ),
            },
        },
        "required": ["path"],
    },
}

KAIROS_ACTIVITY = {
    "name": "kairos_activity",
    "description": (
        "Show the user's own work pattern derived from Hermes's session history: "
        "hour-of-day histogram, how much activity falls after 23:00, per-night "
        "intensity, and the share of tool calls that failed on the day after each "
        "logged night. That last one is a plain observation, never a correlation "
        "and never evidence about anyone's judgement. Read-only. Use when asked "
        "'when do I actually work?' or before a sleep report."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days back to scan (default 30, max 365).",
            }
        },
    },
}

KAIROS_REPORT = {
    "name": "kairos_report",
    "description": (
        "Correlate logged sleep against work-pattern features and report only what "
        "the sample supports. Returns INSUFFICIENT_EVIDENCE rather than a guess "
        "when too few nights are matched. Pass format='text' for a printable chart."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Window in days (default 60)."},
            "format": {
                "type": "string",
                "enum": ["json", "text"],
                "description": "'text' renders an ASCII report.",
            },
        },
    },
}

KAIROS_GUARD = {
    "name": "kairos_guard",
    "description": (
        "Inspect or configure the quiet-hours guard, which asks for confirmation "
        "(or refuses) on risky operations during the user's declared sleep window. "
        "Disabled by default; the user must turn it on."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "enable", "disable", "configure"],
                "description": "What to do. Default 'status'.",
            },
            "quiet_start": {"type": "string", "description": "e.g. '23:30'"},
            "quiet_end": {"type": "string", "description": "e.g. '06:00'"},
            "mode": {
                "type": "string",
                "enum": ["approve", "block"],
                "description": "'approve' escalates to the human gate; 'block' vetoes.",
            },
        },
    },
}
