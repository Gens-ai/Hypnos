# Getting your sleep into Kairos

Kairos does not care what's on your wrist. Everything below is optional:
manual entry is a first-class path and always will be.

Back to the [README](../README.md).

---

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

