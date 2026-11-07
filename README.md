# Hypnos

**A sleep coach that happens to be your coding agent.**

Every sleep app is a bystander that asks what you did yesterday. Hermes was
*in the room at 3am, helping you do it.* It isn't an observer — it's the
accomplice. Which makes it the one honest candidate for this job.

```
> ☾ ████████░░ · bedtime 02:30 · 22 min out
>
> Good spot — nothing failing and nothing half-finished. If you want the
> full 7h30, this is an easy place to leave it. Want me to write up where
> we got to so you can start winding down?
>
> · say "not tonight" to mute
```

The bar fills with night as your bedtime approaches, so you read the runway
at a glance. The poppy — Hypnos's own attribute — appears only on the last
rung, so it stays meaningful by being rare.

## There is no correct bedtime

**02:30 is as valid as 22:00.** Plenty of people who use Hermes have no boss
and no clock-in; working till 3am and sleeping till noon is a way to live,
not a defect to be corrected.

So Hypnos has no opinion about when you sleep. It measures you against the
target *you* set, and until you set one it says nothing at all. Two further
rules fall out of that:

- **It never assumes you're tired.** The hour on the clock is not evidence
  about your body, and the copy never pretends otherwise.
- **Stopping mid-problem is not a failure.** Handing something to tomorrow-you
  is a real strategy — sleep does genuine consolidation work — and Hypnos is
  allowed to say so.

## How present it is, is your call

Five tones, set in **Settings → Plugins → Hypnos**. Nothing gates a tool call
below `firm`.

| Tone | Behaviour |
|---|---|
| `off` | Measures only. Never brings sleep up. |
| `gentle` *(default)* | One note near bedtime, and only when you're at a clean stopping point. |
| `encouraging` | Runway, bedtime, and once after. Always an offer. |
| `firm` | The above, plus a confirmation step on destructive commands in quiet hours. |
| `guardian` | The above, and destructive commands can be refused outright. Fully opt-in. |

Nudges arrive between your turns — never mid-tool-chain — as a quoted block
the agent speaks in its own voice, or as a desktop notification, or both.
**One nudge per rung per night, then silence.** Say *"not tonight"* and it's
muted without comment, no second attempt, no mention of it tomorrow.

## It knows whether you're at a clean break

This is the part no sleep app can do. Hypnos can see whether you're actually
at a natural stopping point — recent tool failures, uncommitted changes — so
instead of nagging on a timer it adapts:

> *"That's your bedtime, and you're at a natural break. I've got the thread —
> nothing's lost if you head to bed now."*

> *"That's your bedtime. Land whatever you're mid-way through and I'll note
> where we end up — it'll be waiting, with fresh eyes on it."*

And because the real reason people don't stop is fear of losing the thread,
it removes the reason: a bedtime handoff writes up what was in flight, where
it stopped, and the next step. Stopping costs nothing.

## Early starts, eased in

Mention plans with a time and Hypnos works backwards from the wake time,
easing the shift over the nights before, then releasing it. No arithmetic for
you.

> *"Hiking trip Saturday, need to be up at 6:30."*

```
2026-11-11  bedtime 01:20   easing in
2026-11-12  bedtime 00:10   easing in
2026-11-13  bedtime 23:00   the night that counts
2026-11-14  bedtime 02:30   back to normal
```

It can also drift your target gradually toward a different one — abrupt
schedule changes don't hold, roughly 15 min a week does.

## One question each morning

A scheduled check-in asks *how did you sleep?* and nothing else. It runs on
cron rather than at the start of your first session, because when you sit
down with a goal in mind you don't want to be derailed.

**It never opens with a missed target.** Patterns belong in the report, in
aggregate, where they're information rather than a scolding.

## It refuses to lie to you

Most quantified-self tooling will happily draw a confident trend line through
nine data points.

- Fewer than **10 matched nights** → `INSUFFICIENT_EVIDENCE`, and **no
  numbers at all**
- Under **21 nights** → every figure labelled `PROVISIONAL`
- Every correlation carries a **bootstrap 95% interval**; if it straddles
  zero the verdict is `INCONCLUSIVE`, not a direction
- Never a causal verb — "associated with", never "causes"

Verified against synthetic data: with a planted effect it finds it
(r = −0.93, CI [−0.96, −0.87]) and calls all four noise features
inconclusive. No false positives.

It also declines to dress up a tautology. "Worked late" against "slept less"
is nearly circular — if you were working at 3am you weren't asleep at 3am —
so the metrics that matter are the ones that aren't:

- **Consistency over earliness.** A steady 02:00 beats an erratic 23:00, so
  bedtime *spread* is the better target.
- **Open threads at stop**, recorded with no implied valence. If it turns out
  to correlate with better sleep for you, Hypnos will say that.

## Tools

| Tool | What it does |
|---|---|
| `hypnos_goal` | Your bedtime, duration, gradual-shift goal, tone, check-in. |
| `hypnos_commitment` | Early starts — worked backwards and eased in. |
| `hypnos_winddown` | Nudge status, `snooze`, and the bedtime `handoff`. |
| `hypnos_checkin` | The one-question morning check-in. |
| `sleep_log` | Log a night. Fuzzy durations: `7h20m`, `6.5h`, `7:20`, `400m`. |
| `sleep_import` | Bulk CSV — Gadgetbridge, Mi Fitness, Google Fit, Oura, hand-made. |
| `hypnos_activity` | Your work pattern from Hermes's own history. |
| `hypnos_report` | Correlate the two, honestly. `format="text"` for the chart. |
| `hypnos_guard` | Quiet-hours guard for destructive work. Off by default. |

## Any tracker, or none

Hypnos doesn't care what you wear. Sleep arrives through one small interface
— `night, duration, wake_count?, quality?` — with three adapters: **manual**
(`sleep_log`, zero hardware), **CSV** (any export with a date and a duration
column), and **Apple Health / Gadgetbridge** via their existing exports.

No account, no vendor API, no hardware requirement.

## Desktop half

One package, both SDKs. A right-hand pane and a `/hypnos` page with the live
hour histogram, a 21-night sleep track, an inline log box and the current
verdict; a `☾` status-bar chip; a ⌘K command; and a full settings page. Off
by default — enable in **Capabilities → Plugins**.

Strictly inside the plugin SDK surface: no prototype patching, no `eval`, no
app-markup queries, no DOM observers. All data arrives through this package's
own backend namespace, and the pane degrades to a message rather than
crashing when the Python half is disabled.

## Install

<a href="hermes://plugin/install?repo=Gens-ai/Hypnos&enable=1">Install in Hermes</a>

```bash
hermes plugins install Gens-ai/Hypnos
hermes plugins enable hypnos
```

Then just talk. *"I want to be in bed by 2:30, aiming for 7 and a half
hours"* → target set. *"Slept about five hours, woke up twice"* → logged.
*"Flight at 7 on Saturday"* → the week's targets shift and release.

## Disclosure

- **Reads** `state.db` (Hermes's own session store) **read-only**, with
  `mode=ro`, inside the active profile's home. Message timestamps, roles and
  tool names only — **never message content**. Degrades to empty if the file
  is missing or unreadable.
- **Writes** only to `<hermes home>/plugin-data/hypnos/` — a SQLite database
  via the sanctioned `plugin_db()` helper, plus bedtime handoff notes you
  asked it to write.
- **Reads git status** in the session's working directory, when there is one,
  purely to tell whether you're at a clean stopping point. Nothing is written
  and no git history is read.
- **No network calls.** No telemetry. No credentials read, stored or
  requested. No self-updater.
- **Backend routes** (`dashboard/plugin_api.py`) mount at
  `/api/plugins/hypnos/` and run in the gateway process: `GET /summary`,
  `/goals`, `/winddown` (read-only) and `POST /sleep`, `/goals`,
  `/commitments`, `/guard`. They import only this package's own modules.
- **Desktop half** uses only `@hermes/plugin-sdk`, `react` and
  `react/jsx-runtime`; it reads through `ctx.rest` and contributes a pane, a
  route, a nav row, a status chip, a palette command and a settings page. No
  prototype patching, no `eval`, no core-markup access.
- **The `pre_llm_call` hook** injects the wind-down block as context between
  turns. It is silent when no target is set, at tone `off`, when the rung has
  already fired tonight, or when snoozed.
- **The guard** can escalate or veto tool calls, but only when you enable it,
  only at tone `firm` or `guardian`, only for the listed tool names, only
  inside your declared window, and only on destructive argument patterns. It
  fails **open** — any internal error allows the call rather than wedging the
  agent.
- **The morning check-in** is a Hermes cron job you create, delivered where
  you choose. Off by default.
- Health correlations are observational, single-subject, and not medical
  advice. Hypnos does not diagnose sleep disorders.

MIT.
