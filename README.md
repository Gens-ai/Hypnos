# Hypnos

**Your agent already knows you were up at 3am. Hypnos makes it tell you.**

Every sleep app asks what you did yesterday. Hermes was *there*. It has a
timestamped record of every session, every command, every build you fought
at 4am — and nobody has ever used it as a lifestyle sensor.

Hypnos reads Hermes's own session store, derives your real work pattern,
logs your sleep beside it, and reports only the correlations your sample can
actually support.

```
Agent activity by hour of day:
  00:00 ################## 53
  02:00 ############ 35
  03:00 ##################################### 109
  04:00 ######################################## 117
  23:00 # 2

Verdict: INSUFFICIENT_EVIDENCE
Only 3 nights have both sleep and activity data. Hypnos needs at least
10 before it will report a correlation, and about 21 before the number is
worth acting on. Log 7 more nights.
```

That histogram is real output from the author's machine: 100% of his agent
work falls between 23:00 and 05:00, peaking at 4am.

## It refuses to lie to you

This is the whole design. Most quantified-self tooling will happily draw a
confident trend line through nine data points.

- Fewer than **10 matched nights** → `INSUFFICIENT_EVIDENCE`, and **no
  numbers at all**
- Under **21 nights** → every figure labelled `PROVISIONAL`
- Each correlation carries a **bootstrap 95% interval**; if it straddles
  zero the verdict is `INCONCLUSIVE`, not a direction
- Never a causal verb — "associated with", never "causes"

Verified against synthetic data: with a planted effect it finds it
(r = −0.93, CI [−0.96, −0.87]) and calls all four noise features
inconclusive. No false positives.

## Tools

| Tool | What it does |
|---|---|
| `sleep_log` | Log a night. Fuzzy durations: `7h20m`, `6.5h`, `7:20`, `400m`. Defaults to last night. |
| `sleep_import` | Bulk CSV import — Gadgetbridge, Mi Fitness, Google Fit, Oura, or hand-made. |
| `hypnos_activity` | Your work pattern from Hermes's own history. Hour histogram, late-night share, per-night intensity. |
| `hypnos_report` | Correlate the two, honestly. `format="text"` for the ASCII report. |
| `hypnos_guard` | Quiet-hours guard: confirm or refuse destructive work in the small hours. Off by default. |

## The guard

Opt-in. When enabled, a `terminal` call matching `rm -rf`, `git push
--force`, `DROP TABLE`, `migrate`, `git reset --hard` and friends inside
your declared quiet hours escalates to the human-approval gate (or is
blocked outright in `mode: block`).

Everything else passes untouched. `ls -la` at 3am is fine. Your judgement at
3am is the problem, and past-you gets a vote.

```
hypnos_guard(action="enable")
hypnos_guard(action="configure", quiet_start="23:30", quiet_end="06:00", mode="approve")
```

## Any tracker, or none

Hypnos doesn't care what you wear. Sleep arrives through one small
interface — `night, duration, wake_count?, quality?` — with three adapters:

1. **Manual** — `sleep_log`, works for everyone with zero hardware
2. **CSV** — any export with a date column and a duration column
3. **Apple Health / Gadgetbridge** — via their existing exports

No account, no vendor API, no hardware requirement.

## Desktop pane

Ships a Desktop half (`desktop/plugin.js`) — one package, both SDKs. A right-hand
pane and a `/hypnos` page with the live hour histogram, a 21-night sleep track,
an inline log box, and the current verdict. Plus a `☾ 100%` status-bar chip and a
⌘K command. Off by default; enable in **Capabilities → Plugins**.

Strictly inside the plugin SDK surface: no prototype patching, no `eval`, no
app-markup queries, no DOM observers. All data arrives through this package's own
backend namespace (`/api/plugins/hypnos/`), and the pane degrades to a message
rather than crashing when the Python half is disabled.

## Install

<a href="hermes://plugin/install?repo=Gens-ai/Hypnos&enable=1">Install in Hermes</a>

```bash
hermes plugins install Gens-ai/Hypnos
hermes plugins enable hypnos
```

Then just talk: *"slept about five hours, woke up twice"* → logged.
*"when do I actually work?"* → the histogram.

## Disclosure

- **Reads** `state.db` (Hermes's own session store) **read-only**, with
  `mode=ro`, inside the active profile's home. Message timestamps, roles and
  tool names only — **never message content**. Degrades to empty if the file
  is missing or unreadable.
- **Writes** only to `<hermes home>/plugin-data/hypnos/data.db` via the
  sanctioned `plugin_db()` helper.
- **No network calls.** No telemetry. No credentials read, stored or
  requested. No subprocesses. No self-updater.
- **Backend routes** (`dashboard/plugin_api.py`) mount at
  `/api/plugins/hypnos/` and run in the gateway process: `GET /summary`
  (read-only), `POST /sleep` (same upsert as the agent tool), `POST /guard`
  (guard config). They import only this package's own modules.
- **Desktop half** uses only `@hermes/plugin-sdk`, `react` and
  `react/jsx-runtime`; it reads through `ctx.rest` and contributes a pane, a
  route, a nav row, a status chip and a palette command. No prototype
  patching, no `eval`, no core-markup access.
- **The guard** can escalate or veto tool calls, but only when you enable
  it, only for the tool names listed above, only inside your declared
  window, and only on destructive argument patterns. It fails **open** — any
  internal error allows the call rather than wedging the agent.
- Health correlations are observational, single-subject, and not medical
  advice.

MIT.
