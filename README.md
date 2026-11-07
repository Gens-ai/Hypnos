# Hypnos

In the myth, Hypnos is the one who put Zeus to sleep. He did it twice, at
Hera's request, and the second time Zeus wanted him drowned in the sea for
it. He got away with it by hiding behind his mother, Night, whom Zeus was
afraid of.

A minor god with a track record of switching off something much larger than
himself, and the sense to have backup. That's the job here.

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
runway without reading a sentence. The poppy, Hypnos's actual attribute in
the iconography, only turns up on the last rung. It stays meaningful by being
rare.

## Your agent was there

This is the part I think is actually new. Every other sleep app is a
bystander that asks what you did yesterday. Hermes was in the room at 3am,
handing you the commands, and it has timestamps on all of it.

It isn't a witness. It's an accessory. Hypnos is what happens when the
accessory starts taking notes.

Here's real output from my machine, before I had logged a single night:

```
  00:00 ██████████████████ 53
  02:00 ████████████ 35
  03:00 █████████████████████████████████████ 109
  04:00 ████████████████████████████████████████ 117
  23:00 ██ 2
```

Nothing between 05:00 and 22:00. Not one message. No watch, no subscription
and no correlation coefficient required to find that interesting.

## There is no correct bedtime

I want to be blunt about this, because most things in this category get it
wrong. **02:30 is as valid as 22:00.** Plenty of people running Hermes have no
boss and no clock to punch, and working till three then sleeping till noon is
a schedule, not a symptom.

So Hypnos has no opinion about when you sleep. It measures you against the
target you set, and until you set one it says nothing at all. Two things fall
out of that, and both are load-bearing.

It never decides you're tired. The hour on the clock tells you nothing about
anybody's body and the copy never pretends otherwise. You will not get a
single "you must be exhausted" out of this plugin.

Stopping mid-problem is not a failure either. Sleep does real consolidation
work, so handing something to tomorrow-you is a strategy rather than a
surrender, and Hypnos is allowed to say so when it's past your mark and
you're still chewing.

## You pick how much it talks

Five settings, in Settings → Plugins → Hypnos. Nothing touches a tool call
below `firm`.

| Tone | What you get |
|---|---|
| `off` | Measurement only. Sleep never comes up. |
| `gentle` (default) | One note near bedtime, and only if you're at a clean stopping point. |
| `encouraging` | Runway, bedtime, and once after. Always phrased as an offer. |
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

A timer can't do this and neither can your watch. Hypnos looks at whether the
work is actually at rest right now, from recent tool failures and uncommitted
changes, then adapts instead of nagging.

If you're clear:

> *That's your bedtime, and you're at a natural break. I've got the thread —
> nothing's lost if you head to bed now.*

If you're mid-surgery:

> *That's your bedtime. Land whatever you're mid-way through and I'll note
> where we end up — it'll be waiting, with fresh eyes on it.*

Nobody stays up out of love for the bug. They stay up because stopping feels
like losing the thread. So Hypnos writes the thread down: what was in flight,
where it stopped, the obvious next move. Lethe runs through the cave in the
myth, which is a terrible property in a note-taking system, so the file goes
on disk.

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
you sleep better after walking away from an unsolved problem, Hypnos will
report that cheerfully and I'll have learned something.

## Tools

| Tool | What it does |
|---|---|
| `hypnos_goal` | Bedtime, duration, the slow-shift target, tone, check-in. |
| `hypnos_commitment` | Early starts, worked backwards and eased in. |
| `hypnos_winddown` | Nudge status, `snooze`, and the bedtime `handoff`. |
| `hypnos_checkin` | The one morning question. |
| `sleep_log` | Log a night. Takes `7h20m`, `6.5h`, `7:20`, `400m`. |
| `sleep_import` | Bulk CSV. Gadgetbridge, Mi Fitness, Google Fit, Oura, handmade. |
| `hypnos_activity` | Your work pattern, out of Hermes's own history. |
| `hypnos_report` | The honest correlation. `format="text"` for the chart. |
| `hypnos_guard` | Quiet-hours guard on destructive work. Off unless you say so. |

## Any tracker, or none at all

Hypnos does not care what's on your wrist. Sleep comes in through one small
interface (`night, duration, wake_count?, quality?`) with three ways to fill
it: type it at the agent, import a CSV from whatever your device exports, or
point it at an Apple Health or Gadgetbridge dump. No account, no vendor API,
no hardware.

I built this against a Mi Band 7 that I then failed to locate for two days,
which is exactly why manual entry is a first-class path and not a fallback.

## The desktop half

One package, both SDKs. A right-hand pane and a `/hypnos` page with the live
histogram, a 21-night sleep track, an inline log box and the current verdict,
plus a `☾` chip in the status bar, a ⌘K command, and a settings page. Off
until you enable it in Capabilities → Plugins.

It stays inside the plugin SDK surface: no prototype patching, no `eval`, no
querying the app's own markup, no DOM observers. Everything arrives through
this package's own backend namespace, and if the Python half is switched off
the pane says so instead of exploding.

## Pipeline

The thing Hypnos wants next is more context about the body attached to the
keyboard. That does not mean writing a vendor integration for every watch on
the market, and it very deliberately does not mean Hypnos holding anybody's
OAuth tokens.

**One adapter, every device.** Hermes plugins can call a configured MCP server
through `ctx.call_mcp`, gated by a per-plugin, per-server allowlist the user
sets themselves. Several health MCP servers already exist in the Hermes
catalog. So the next real feature is a generic reader that pulls last night's
sleep from whichever of them you already run, under your own allowlist, with
no vendor code and no credentials inside Hypnos:

| Already in the catalog | Covers |
|---|---|
| `athletedata` | Garmin, Oura, WHOOP, Hevy, Intervals.icu and ~35 more, hosted, paid |
| `apple-health-mcp` | Apple Health export on disk: sleep, HRV, heart rate |
| `healthrelay` | Apple Health through a receiver you host yourself |
| `health-data`, `health-insights`, `healthcare` | local health stores with their own query tools |

Grant one of those in `mcp_allowlist` and sleep arrives on its own. That is
the whole integration.

**Direct, where it's genuinely easy.** Oura and WHOOP both publish documented
REST APIs with sleep collections, so a thin reader for either is a small job.
The honest caveat is that Hermes's declarative OAuth machinery is aimed at
inference providers rather than plugins calling third-party services, so the
realistic shape today is a token you supply through `requires_env` and
Hypnos reads but never stores. Garmin has no public consumer API, only an
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

<a href="hermes://plugin/install?repo=Gens-ai/Hypnos&enable=1">Install in Hermes</a>

```bash
hermes plugins install Gens-ai/Hypnos
hermes plugins enable hypnos
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
- **Writes** only inside `<hermes home>/plugin-data/hypnos/`: a SQLite
  database through the sanctioned `plugin_db()` helper, plus the handoff notes
  you asked for.
- **Reads git status** in the session's working directory when there is one,
  purely to work out whether you're at a clean stopping point. Nothing is
  written and no history is read.
- **No network calls at all.** No telemetry, no credentials read or stored or
  requested, no self-updater.
- **Backend routes** (`dashboard/plugin_api.py`) mount at
  `/api/plugins/hypnos/` and run in the gateway process. `GET /summary`,
  `/goals` and `/winddown` are reads; `POST /sleep`, `/goals`, `/commitments`
  and `/guard` are writes. They import nothing but this package's own modules.
- **Desktop half** imports only `@hermes/plugin-sdk`, `react` and
  `react/jsx-runtime`. It reads through `ctx.rest` and contributes a pane, a
  route, a nav row, a status chip, a palette command and a settings page.
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
  advice and Hypnos diagnoses nothing. If something clinical is going on, see
  an actual doctor rather than a plugin named after a Greek god.

MIT.
