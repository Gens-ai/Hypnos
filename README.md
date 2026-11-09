# Kairos

**Kairos helps you stop working at night.**

It's a Hermes Agent plugin that reads your agent's own session history, offers
a wind-down when you're at a natural break rather than mid-thought, and
refuses to claim your sleep affects your output unless the sample actually
supports it.

```
> ☾ ████████░░ · bedtime 02:30 · 22 min out
>
> Good spot — nothing failing and nothing half-finished. If you want the
> full 7h30, this is an easy place to leave it. Want me to write up where
> we got to so you can start winding down?
>
> · say "not tonight" to mute
```

The bar fills with night as your bedtime gets closer, so you can read the
runway without reading a sentence. The flower only turns up on the last rung,
once the mark has already gone past. It stays meaningful by being rare.

## Why it's called Kairos

The Greeks had three words for time. Chronos is the clock: measured,
sequential, indifferent. Aion is the cycle, the year coming back around.
Kairos is the third one — the right moment, the narrow window where an action
lands instead of bouncing off. In the iconography he has wings on his feet and
a single lock of hair at the front of an otherwise bald head: you can catch
him on the way in, and once he has gone past there is nothing left to grab.

The clock knows what time it is and nothing else. It doesn't know whether
you're mid-thought or finished, whether the build is green, whether you'd
thank anyone at all for interrupting. This is named after the other one.

## Your agent was there

This is the part I think is actually new. Every other sleep app is a
bystander that asks what you did yesterday. Hermes was in the room at 3am,
handing you the commands, and it has timestamps on all of it.

It isn't a witness. It's an accessory. Kairos is what happens when the
accessory starts taking notes.

Here's real output from my machine, unedited, after four days of use:

```
  00:00 █████ 53
  02:00 ███ 35
  03:00 ███████████ 110
  04:00 ██████████████████████████ 244
  05:00 ████████ 77
  06:00 ████████████████████████████████████████ 371
  07:00 ███████████████████████ 217
  13:00 ▌ 6
  14:00 ██████ 58
  15:00 ██ 25
  16:00 ▌ 8
  23:00 ▌ 2
```

Ninety-two percent of it lands outside 08:00–22:00, and the peak hour is
06:00. There are no messages at all between 08:00 and 13:00, or after 17:00.
No watch, no subscription and no correlation coefficient required to find that
interesting.

Two honest caveats, since this is the number the whole plugin rests on. It is
**four days** of data — enough to see a shape, nowhere near enough for the
report to say anything, which is why `kairos_report` still returns
`INSUFFICIENT_EVIDENCE` on this machine. And the peak moved: it was 04:00 when
I started writing this, and 06:00 by the time I finished, because the thing
that pushed it later was building Kairos. The measurement perturbed the
measured. Both facts argue for the plugin rather than against it.

## There is no correct bedtime

I want to be blunt about this, because most things in this category get it
wrong. **02:30 is as valid as 22:00.** Plenty of people running Hermes have no
boss and no clock to punch, and working till three then sleeping till noon is
a schedule, not a symptom.

So Kairos has no opinion about when you sleep. It measures you against the
target you set, and until you set one it says nothing at all. Two things fall
out of that, and both are load-bearing.

It never decides you're tired. The hour on the clock tells you nothing about
anybody's body and the copy never pretends otherwise. You will not get a
single "you must be exhausted" out of this plugin.

Stopping mid-problem is not a failure either. Sleep does real consolidation
work, so handing something to tomorrow-you is a strategy rather than a
surrender, and Kairos is allowed to say so when it's past your mark and
you're still chewing.

## You pick how much it talks

Five settings, in Settings → Plugins → Kairos. Nothing touches a tool call
below `firm`.

| Tone | What you get |
|---|---|
| `off` | Measurement only. Sleep never comes up. |
| `gentle` | One note near bedtime, and only if you're at a clean stopping point. |
| `encouraging` *(default)* | Runway, bedtime, and once after. Always phrased as an offer. |
| `firm` | Same, plus a confirmation step on destructive commands in quiet hours. |
| `guardian` | Same, and those commands can be refused outright. Entirely your call. |

Nudges land between your turns, never in the middle of a tool chain, either
as a quoted block the agent reads out or a desktop notification or both.

You set the spacing. A minimum gap (45 minutes by default, anywhere from 0 to
240) applies between any two nudges whatever the stage. Each stage before
your bedtime gets mentioned once and is then dropped, because "22 min out"
does not bear repeating. Only the past-your-bedtime message is allowed to
come back, on that same interval.

It also tries to catch you at a sensible moment rather than cutting in. If a
nudge comes due while something is failing or half-finished it waits, and
speaks when the work settles. That wait is bounded by a patience window (20
minutes by default) after which it speaks anyway, except on `gentle`, which
would rather miss the window than interrupt you. Turn the whole behaviour off
if you want it punctual instead of polite.

Say "not tonight" and it's gone without a word of argument, no second
attempt, nothing about it in the morning.

## It can tell whether you're at a clean break

A timer can't do this and neither can your watch. Kairos looks at whether the
work is actually at rest right now, from recent tool failures and uncommitted
changes, then adapts instead of nagging.

If you're clear:

> *That's your bedtime, and you're at a natural break. I've got the thread —
> nothing's lost if you head to bed now.*

If you're mid-surgery:

> *That's your bedtime. Land whatever you're mid-way through and I'll note
> where we end up — it'll be waiting, with fresh eyes on it.*

Nobody stays up out of love for the bug. They stay up because stopping feels
like losing the thread. So Kairos writes the thread down: what was in flight,
where it stopped, the obvious next move. The moment passes whether or not you
were ready for it, which is a terrible property in a note-taking system, so
the file goes on disk.

## Early starts, worked backwards

Tell it about plans with a time in them. It does the arithmetic, eases the
shift across the nights before, and then lets go.

> *Hiking trip Saturday, need to be up at 6:30.*

```
2026-11-11  bedtime 01:20   easing in
2026-11-12  bedtime 00:10   easing in
2026-11-13  bedtime 23:00   the night that counts
2026-11-14  bedtime 02:30   released, back to normal
```

It can also walk your usual target somewhere else over weeks. Yanking a sleep
schedule two hours in one night doesn't hold. Fifteen minutes a week does.

## One question in the morning

A scheduled job asks how you slept. That's the whole interaction.

It runs on cron rather than waiting for your first session, because when you
sit down with something specific in mind the last thing you want is a
wellness interview. And it never opens with your miss. Not "you were up till
four again." Patterns belong in the report, in aggregate, where they're
information instead of a telling-off.

## It would rather say nothing than lie

Most quantified-self software will cheerfully run a trend line through nine
data points.

- Under 10 matched nights you get `INSUFFICIENT_EVIDENCE` and no numbers at
  all, not even hedged ones
- Under 21 nights every figure is stamped `PROVISIONAL`
- Every correlation carries a bootstrap 95% interval, and if that interval
  contains zero the answer is `INCONCLUSIVE` rather than a direction
- No causal verbs anywhere. "Associated with", never "causes"

Tested against synthetic data with a known effect planted in it: finds the
real one at r = −0.93, CI [−0.96, −0.87], and calls all four noise features
inconclusive. No false positives.

It also won't dress a tautology up as a discovery. "Worked late" against
"slept less" is nearly circular, because if you were working at 3am you
weren't asleep at 3am. The numbers worth having are the ones that aren't:

**Spread beats earliness.** A reliable 02:00 does more for you than a 23:00
that swings by two hours, so the variance is the target rather than the mean.

**Open threads at stop** are recorded with no moral attached. If it turns out
you sleep better after walking away from an unsolved problem, Kairos will
report that cheerfully and I'll have learned something.

## Tools

| Tool | What it does |
|---|---|
| `kairos_goal` | Bedtime, duration, the slow-shift target, tone, check-in. |
| `kairos_commitment` | Early starts, worked backwards and eased in. |
| `kairos_winddown` | Nudge status, `snooze`, and the bedtime `handoff`. |
| `kairos_checkin` | The one morning question. |
| `sleep_log` | Log a night. Takes `7h20m`, `6.5h`, `7:20`, `400m`. |
| `sleep_import` | Import sleep — a Xiaomi/Mi Fitness export, a Gadgetbridge database, or any CSV. Format sniffed. `probe` shows what parsed and writes nothing. |
| `kairos_activity` | Your work pattern, out of Hermes's own history. |
| `kairos_report` | The honest correlation. `format="text"` for the chart. |
| `kairos_guard` | Quiet-hours guard on destructive work. Off unless you say so. |
| `kairos_wearable` | Read sleep from a health MCP server you already run. |
| `kairos_ping` | For a cron job: is a nudge due right now, out of session? |

## Any tracker, or none at all

Kairos does not care what's on your wrist. Sleep comes in through one small
interface (`night, duration, wake_count?, quality?`) with three ways to fill
it: type it at the agent, import a CSV from whatever your device exports, or
point it at an Apple Health or Gadgetbridge dump. No account, no vendor API,
no hardware.

I built this against a Mi Band 7 that I then failed to locate for two days,
which is exactly why manual entry is a first-class path and not a fallback.

## Connecting a watch

Every bridge lands on the same seam. A source answers three questions —
what config it needs, what it parsed (`probe`, which writes nothing), and
the nights themselves — and that's all. Field aliases, unit coercion,
plausibility bounds, dedupe, provenance and the rule that **your own entries
are never overwritten** live in one place and apply to every source
identically. Adding a bridge is a class and a line, and it inherits all of
that.

| Source | What it reads | Supplies beyond duration |
|---|---|---|
| `csv` | Any tracker's CSV export, or one you typed | wake count, quality |
| `xiaomi` | A Mi Fitness / Xiaomi account export | bedtime, wake time, wake count, sleep score, stage breakdown |
| `gadgetbridge` | A Gadgetbridge SQLite export (Mi Band, Amazfit) | onset/offset times, wake count |
| `mcp` | A health MCP server you already run | onset/offset times, wake count, quality |

Each declares what it can supply, so the report can say *"this source has no
onset latency"* rather than treating absent as zero.

### A Mi Fitness / Xiaomi export

Xiaomi's export is not a sleep file — it is a key/value table where each
`Value` is a JSON blob and sleep is the rows keyed `sleep`, plus a second
per-device table carrying the `awake_count` the first one lacks. The `xiaomi`
source merges them, and point it at the extracted folder:

```
"import my sleep from ~/sync/xiaomi/..._data_copy"
```

Real output from the author's own export: 85 rows across two tables, 31 with
no duration, 2 outside the plausibility bound, 19 nights described by both
tables and merged → **27 nights, 2022-07-11 to 2025-08-11**, with sleep
scores and deep/light/REM minutes carried through in `extra`.

One judgement call worth knowing: Xiaomi's `total_duration` is all sleep in
the day including naps, so a night with a 20-minute nap and a 443-minute
sleep reports 463. For correlating against a working day the main sleep is
the honest number, so the **longest segment** becomes the night and the daily
total is kept in `extra`.

Request it at **account.xiaomi.com → Privacy → Manage Your Data → Mi Fitness
→ Download**. Xiaomi quotes fifteen days; it can arrive the next.

### A file: CSV or Gadgetbridge

```
"import my sleep from ~/sync/gadgetbridge.db"
```

The format is sniffed — a SQLite header means Gadgetbridge, anything else is
CSV — so you don't have to name it. **Probe an unfamiliar export first**; it
writes nothing and shows you what was understood.

Gadgetbridge doesn't store nights. It stores one row per minute tagged with a
device-specific activity kind, so a night is reassembled: select sleep-kind
samples, group contiguous runs, collapse each into a duration plus the
interruptions inside it. The raw-kind encoding differs per model and isn't
documented per device, so nothing is hardcoded blind — the table and columns
are discovered, the sleep kinds are overridable, and `probe` hands back the
**kind histogram** it found:

```
table: HUAMI_EXTENDED_ACTIVITY_SAMPLE   kind_histogram: {"2": 1017, "4": 504, "1": 90}
2026-11-01  429min  wakes=1
2026-11-02  359min  wakes=0
```

If the nights look wrong, the sleep kinds are wrong — pass `sleep_kinds`
explicitly rather than trusting the default.

Auto-sync, once set up and then never again: Gadgetbridge's **Settings →
Automations → Auto export** writes its database on an interval, Syncthing
carries it to your machine, and a cron job imports it. No account, no cloud,
nothing to click.

### A guessed unit is reported, never presented as a reading

A column called `duration` holding `6.5` means hours. Holding `12` it could
mean either, and reading that as a twelve-hour night would be inventing data.
So the guess is surfaced instead of buried:

```
assumed_units: [{night: 2026-11-09, minutes: 720,
                 assumption: "read 12 as hours — rename the column to
                              duration_min if it meant minutes"}]
```

`duration_min` and `duration_hours` are unambiguous and carry no assumption.

### A health MCP server

Kairos writes no vendor integrations and holds no credentials. It reads from a
server you already run, through `ctx.call_mcp`, which Hermes gates behind an
allowlist you control. Three steps.

**1. Install whichever health plugin matches your device.**

| If you have | Install | Cost |
|---|---|---|
| Garmin, Oura, WHOOP, Hevy, Intervals.icu | `athletedata` | paid, trial available |
| An iPhone or Apple Watch | `apple-health-mcp` | free, reads a local export |
| An iPhone and a server you host | `healthrelay` | free |
| Something already in a local health store | `health-data` | free |
| A Mi Band or Redmi Watch on **Mi Fitness** | `account.xiaomi.com` → Privacy → Manage Your Data → Mi Fitness → Download, then `sleep_import` | free |
| Anything **Gadgetbridge** supports | auto-export + `sleep_import` (reads the SQLite directly) | free |
| None of the above | `sleep_log`, by typing | free |

**2. Grant it to Kairos.** Nothing happens without this, by design:

```yaml
# ~/.hermes/config.yaml
plugins:
  entries:
    kairos:
      mcp_allowlist: ["athletedata"]
```

**3. Point Kairos at it and check before trusting it.**

```
"connect my wearable"            -> kairos_wearable action=presets
"use athletedata for sleep"      -> kairos_wearable action=configure
"check it can read my sleep"     -> kairos_wearable action=probe
```

`probe` writes nothing. It calls the server, shows the nights it parsed and a
preview of the raw response, and tells you if it got nothing.

**The preset tool names are informed guesses, not verified against live
servers.** These servers each return a different shape and rename their tools
between versions, so probing is not a formality — it is how you find out
whether the mapping is right before any of it lands in your history.

**Your own entries always win.** A watch is guessing at how long you slept;
you know whether you lay there for an hour. Anything you logged by hand is
never overwritten by a sync. Where the device disagrees, the sync reports it
and leaves the decision to you:

```
skipped_you_logged_these: 1
conflicts: [{night: 2026-11-03, you_logged_min: 300, device_says_min: 330}]
```

Imported nights are tagged `mcp:<server>` so the source of every number stays
visible, and implausible rows (under 30 minutes, over 18 hours) are dropped
rather than averaged in.

## Being useful when you've shut the laptop

The in-session nudge rides `pre_llm_call`, which only reaches you while
you're actually talking to Hermes. That is the wrong assumption for a bedtime
hint: the most likely reason you're awake at 1am and not winding down is that
you stopped working an hour ago and picked up your phone.

So `kairos_ping` exists for a scheduled job to call. It evaluates exactly the
same gates — switched on, target set, tone, snooze, spacing, stage — and
returns `say_nothing: true` when nothing is due. Cron refuses to deliver an
empty payload, so silence costs nothing and you only hear from it when
there's something to say.

```bash
# the window around a 04:00 bedtime, checked every 20 minutes
hermes cron create "*/20 2-6 * * *" \
  "Call kairos_ping. If say_nothing is true, output nothing at all. \
   Otherwise deliver the nudge text verbatim and stop." \
  --name "Kairos evening ping" --deliver local --timezone America/Chicago
```

Checking often and speaking rarely is the point. On the author's machine that
schedule is fifteen evaluations a night and, at `gentle`, exactly one that
says anything:

```
02:00 .   02:20 .   02:40 .   03:00 .   03:20 SPEAK   03:40 .   04:00 .
04:20 .   04:40 .   05:00 .   05:20 .   05:40 .   06:00 .   06:20 .  06:40 .
```

Point `--deliver` at a messaging channel instead and it reaches your phone,
which is where you are if the laptop is shut.

Both delivery paths share one `nudge_log`, so the spacing rule holds across
them. You will not get a desktop notification and an in-chat nudge for the
same moment. The ping has its own switch in settings, so you can silence it
without going back to hunt down the cron job.

**Out of session it will not pretend to know what you're doing.** The
in-session copy can say "nothing failing and nothing half-finished" because
it checked. The scheduled ping has nothing to check, and says so:

> *You'd set 02:30 as the mark. No pressure and no idea what you're up to —
> but if you're winding down anyway, this is me saying goodnight.*

A second job can pull last night off your watch each morning, so the
check-in has the number before it asks you anything:

```bash
hermes cron create "30 13 * * *" \
  "Call kairos_wearable action=sync, then kairos_checkin action=ask." \
  --name "Kairos morning check-in" --deliver local \
  --timezone America/Chicago --skill kairos:kairos-coaching
```

## The desktop half

One package, both SDKs. A right-hand pane and a `/kairos` page with the live
histogram, a 21-night sleep track, an inline log box and the current verdict,
plus a `☾` chip in the status bar, a ⌘K command, and a settings page. Off
until you enable it in Capabilities → Plugins.

Reach the page with ⌘K → **Open Kairos**, or turn on a sidebar link in
settings. That link is **off by default**: a permanent row for something you
open now and then is clutter, and the page is reachable without it.

It stays inside the plugin SDK surface: no prototype patching, no `eval`, no
querying the app's own markup, no DOM observers. Everything arrives through
this package's own backend namespace, and if the Python half is switched off
the pane says so instead of exploding.

## Pipeline

More context about the body attached to the keyboard, without writing a
vendor integration for every watch on the market. Three bridges ship today
(CSV, Gadgetbridge, MCP) behind one seam, so what follows is a matter of
adding modules rather than redesigning anything.

**Verified status, plainly:** the Gadgetbridge and CSV readers are tested
end-to-end against real file formats. The MCP reader's parser is tested
against eight recorded response shapes, but its preset tool names have never
been run against a live server — `probe` exists precisely because of that.

**Direct, where it's genuinely easy.** Oura and WHOOP both publish documented
REST APIs with sleep collections, so a thin reader for either is a small job.
The honest caveat is that Hermes's declarative OAuth machinery is aimed at
inference providers rather than plugins calling third-party services, so the
realistic shape today is a token you supply through `requires_env` and
Kairos reads but never stores. Garmin has no public consumer API, only an
unofficial scraping library, so that one waits for `athletedata` to do the
dirty work.

**Gadgetbridge, for the stubborn.** Mi Band and friends talk to Gadgetbridge,
which keeps a local SQLite database and can export it. A parser for that is
small, needs no account, and sends nothing anywhere. This is the path for
anyone whose device has no API at all.

**What the extra context buys.** Duration is the least interesting thing a
watch knows. Sleep onset latency, how long it actually took you to drop off
after closing the laptop, is the number that would make the wind-down advice
specific rather than general. Resting heart rate and HRV on the nights after
a hard session would say something about recovery that no amount of session
telemetry can. And an actual measured wake time would let the commitment
arithmetic check itself instead of assuming you got up when you said you
would.

**Aggregators, probably not.** Terra, Vital and Rook each turn one
integration into thirty. They also mean routing your sleep through a third
party's servers, and that is a poor trade for a plugin whose whole pitch is
that it makes no network calls. If it ever happens it will be opt-in,
disclosed in full, and off by default.

Explicit non-goals: no account, no hosted service, no telemetry, and no
reading a credential store that belongs to something else. Manual entry stays
a first-class path forever, because the most reliable sleep tracker is a
person saying "about five hours, badly".

## Install

<a href="hermes://plugin/install?repo=Gens-ai/Kairos&enable=1">Install in Hermes</a>

```bash
hermes plugins install Gens-ai/Kairos
hermes plugins enable kairos
```

Then talk to it like a person. *"I want to be in bed by 2:30, aiming for
seven and a half hours"* sets the target. *"Slept about five hours, woke up
twice"* logs the night. *"Flight at 7 on Saturday"* reshapes the week and
then puts it back.

## Disclosure

- **Reads** `state.db`, Hermes's own session store, read-only via `mode=ro`,
  inside the active profile's home. Message timestamps, roles and tool names
  only. **Never message content.** If the file is missing or unreadable it
  degrades to empty rather than failing.
- **Writes** only inside `<hermes home>/plugin-data/kairos/`: a SQLite
  database through the sanctioned `plugin_db()` helper, plus the handoff notes
  you asked for.
- **Reads sleep files you point it at**, read-only: a CSV, or a Gadgetbridge
  SQLite export opened with `mode=ro`. Nothing is written back to either, and
  an import never overwrites a night you logged yourself. It **fails closed on
  anything that isn't a sleep export** and echoes none of its contents, so the
  importer cannot be used as a general file reader; a SQLite file without a
  Gadgetbridge sample table is refused without its schema being listed. The
  table name is validated against the database's own catalogue before it
  reaches a query, and kind filters are bound parameters.
- **Reads git status** in the session's working directory when there is one,
  purely to work out whether you're at a clean stopping point. Nothing is
  written and no history is read.
- **No network calls of its own.** No telemetry, no credentials read, stored
  or requested, no self-updater. The one outbound path is `ctx.call_mcp` to a
  health MCP server, which does nothing until the operator names that server
  in `plugins.entries.kairos.mcp_allowlist`. Kairos never sees that server's
  credentials, and a server it has not been granted raises `PermissionError`
  with the exact config key to set. Imported rows are tagged `mcp:<server>`;
  anything you logged yourself is never overwritten.
- **`kairos_ping`** reads the clock and the gates and returns text. It sends
  nothing itself — delivery is whatever cron job you chose to create, under
  your own schedule and channel.
- **Backend routes** (`dashboard/plugin_api.py`) mount at
  `/api/plugins/kairos/` and run in the gateway process. `GET /summary`,
  `/goals` and `/winddown` are reads; `POST /sleep`, `/goals`, `/commitments`
  and `/guard` are writes. They import nothing but this package's own modules.
- **Desktop half** imports only `@hermes/plugin-sdk`, `react` and
  `react/jsx-runtime`. It reads through `ctx.rest` and contributes a pane, a
  route, a status chip, a palette command, a settings page, and — only if you
  switch it on — one sidebar row. The sidebar preference is the single thing
  it stores locally, under its own `ctx.storage` namespace; everything else
  lives in the plugin's own database.
- **The `pre_llm_call` hook** injects the wind-down block as context between
  turns. Silent when no target is set, at tone `off`, when that rung already
  fired tonight, or when you've snoozed.
- **The guard** can escalate or veto a tool call, but only once you enable
  it, only at tone `firm` or `guardian`, only for the tools listed above,
  only inside the window you set, and only on destructive argument patterns.
  It fails open: any internal error lets the call through rather than wedging
  your agent.
- **The morning check-in** is a Hermes cron job you create, delivered where
  you choose. Off by default.
- Correlations here are observational and single-subject. This is not medical
  advice and Kairos diagnoses nothing. If something clinical is going on, see
  an actual doctor rather than a plugin named after a Greek god.

MIT.
