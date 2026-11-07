---
name: hypnos-coaching
description: "Use when the user mentions sleep, tiredness, or late-night work habits. How to log sleep and read Hypnos reports honestly."
---

# Hypnos coaching

Hypnos measures the user's own work pattern (from Hermes's session
history) against their logged sleep. Your job is to keep it honest.

## Logging sleep

When the user mentions sleep in passing — "slept like garbage", "got about
six hours", "woke up at 4 again" — call `sleep_log` immediately. Don't
interrogate them. Record what they said:

- `duration` accepts fuzzy input: `7h20m`, `6.5h`, `7:20`, `400m`
- omit `night` for last night
- add `quality` (1-5) and `wake_count` only if they actually said so
- put their own phrasing in `note`

One call, no follow-up questions. If they volunteer more later, call it
again for the same night — it upserts.

## Reading reports

`hypnos_report` returns a verdict. Respect it:

| Verdict | What you may say |
|---|---|
| `INSUFFICIENT_EVIDENCE` | Say how many more nights are needed. Quote **no** numbers, not even "it looks like". |
| `PROVISIONAL` | Numbers are allowed, but label them provisional every time. |
| `REPORTED` | Report normally, still without causal language. |
| `INCONCLUSIVE` (per feature) | Say the direction is not established. Do not pick a side because the sign is suggestive. |
| `NO_VARIANCE` | The feature never changed; there is nothing to correlate. |

**Never use causal verbs.** "Associated with", "tracks alongside", "tends to
accompany" — never "causes", "because of", "is making you".

A correlation over 14 nights of one person's life is a hint, not a finding.
Say so when you present it.

## Activity without sleep data

`hypnos_activity` is useful on its own and needs no sleep log at all.
The hour-of-day histogram is often the most striking thing the user sees —
if 80% of their agent work happens after midnight, show them that plainly
and let it speak. That is an observation about their behaviour, not a
health claim.

## The guard

`hypnos_guard` is **off by default** and the user turns it on
themselves. It asks for confirmation on destructive operations during their
declared quiet hours. If they ask you to enable it, confirm the window back
to them. Never enable it unprompted, and never disable it because a call
got blocked — tell the user it fired and let them decide.

## What this is not

Not medical advice. Hypnos does not diagnose sleep disorders and
neither do you. If the user describes something clinical — persistent
insomnia, apnoea symptoms, sleep paralysis — say plainly that this is
outside what the data can speak to and suggest a doctor.
