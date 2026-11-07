"""Model-facing tool schemas."""

SLEEP_LOG = {
    "name": "sleep_log",
    "description": (
        "Record one night's sleep for Hypnos. Use when the user mentions how "
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
        "Bulk-import nights from a CSV export (Gadgetbridge, Mi Fitness, Google "
        "Fit, Oura, or hand-made). Needs a date column and a duration column."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the CSV file."},
            "source": {
                "type": "string",
                "description": "Label for provenance, e.g. 'gadgetbridge'.",
            },
        },
        "required": ["path"],
    },
}

HYPNOS_ACTIVITY = {
    "name": "hypnos_activity",
    "description": (
        "Show the user's own work pattern derived from Hermes's session history: "
        "hour-of-day histogram, how much activity falls after 23:00, and per-night "
        "intensity. Read-only. Use when asked 'when do I actually work?' or before "
        "a sleep report."
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

HYPNOS_REPORT = {
    "name": "hypnos_report",
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

HYPNOS_GUARD = {
    "name": "hypnos_guard",
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
