// Kairos — Desktop half.
// Strictly inside the plugin SDK surface: no prototype patching, no eval,
// no app-markup queries, no DOM observers. Data comes from this package's
// own backend namespace via ctx.rest.
import { host, haptic, useValue } from '@hermes/plugin-sdk'
import * as sdk from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useCallback, useEffect, useState } from 'react'

const DAYS = 120

// A persistent sidebar row is an imposition for a plugin most people will
// open occasionally, so it is opt-in. Desktop-local (ctx.storage), not a
// backend goal: it is a UI preference, not part of the sleep record. The
// route, ⌘K command and pane are always registered — only the row is
// conditional, so nothing becomes unreachable when it is off.
const NAV_KEY = 'sidebarNav'
let _applyNav = () => {}

// ---------------------------------------------------------------- helpers

function fmtMinutes(m) {
  if (m == null) return '—'
  const h = Math.floor(m / 60)
  const r = Math.round(m % 60)
  return r ? `${h}h ${r}m` : `${h}h`
}

function verdictTone(v) {
  switch (v) {
    case 'ASSOCIATED':
      return 'var(--ui-text-primary)'
    case 'INSUFFICIENT_EVIDENCE':
    case 'INCONCLUSIVE':
    case 'NO_VARIANCE':
      return 'var(--ui-text-tertiary)'
    case 'PROVISIONAL':
      return 'var(--ui-text-secondary)'
    default:
      return 'var(--ui-text-secondary)'
  }
}

// ------------------------------------------------------------- histogram

function Histogram({ hist, peak }) {
  const max = Math.max(1, ...Object.values(hist || {}))
  const bars = []
  for (let h = 0; h < 24; h++) {
    const v = (hist && hist[h]) || 0
    const night = h >= 23 || h < 5
    bars.push(
      jsx('div', {
        key: h,
        title: `${String(h).padStart(2, '0')}:00 — ${v} messages`,
        style: {
          flex: '1 1 0',
          height: '100%',
          display: 'flex',
          alignItems: 'flex-end'
        },
        children: jsx('div', {
          style: {
            width: '100%',
            height: `${Math.max(v ? 6 : 0, (v / max) * 100)}%`,
            borderRadius: '1px 1px 0 0',
            background: night
              ? 'var(--ui-text-primary)'
              : 'var(--ui-border-strong, var(--ui-text-tertiary))',
            opacity: night ? 0.95 : 0.35,
            transition: 'height 160ms ease-out'
          }
        })
      })
    )
  }

  return jsxs('div', {
    children: [
      jsx('div', {
        style: { display: 'flex', gap: '1px', height: '64px', alignItems: 'flex-end' },
        children: bars
      }),
      jsxs('div', {
        style: {
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: '0.5625rem',
          color: 'var(--ui-text-tertiary)',
          marginTop: '3px'
        },
        children: [
          jsx('span', { children: '00' }),
          jsx('span', { children: '06' }),
          jsx('span', { children: '12' }),
          jsx('span', { children: '18' }),
          jsx('span', { children: '23' })
        ]
      }),
      peak != null
        ? jsxs('div', {
            style: {
              fontSize: '0.625rem',
              color: 'var(--ui-text-tertiary)',
              marginTop: '2px'
            },
            children: ['peak ', String(peak).padStart(2, '0'), ':00']
          })
        : null
    ]
  })
}

// ----------------------------------------------------------- sleep track

function SleepTrack({ rows }) {
  if (!rows || !rows.length) {
    return jsx('div', {
      style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)' },
      children: 'No nights logged yet.'
    })
  }
  const ordered = rows.slice().reverse()
  const max = Math.max(...ordered.map(r => r.duration_min), 480)
  return jsx('div', {
    style: { display: 'flex', gap: '2px', height: '36px', alignItems: 'flex-end' },
    children: ordered.map(r =>
      jsx('div', {
        key: r.night,
        title: `${r.night} — ${fmtMinutes(r.duration_min)}${
          r.quality ? ` (quality ${r.quality}/5)` : ''
        }`,
        style: {
          flex: '1 1 0',
          height: `${Math.max(8, (r.duration_min / max) * 100)}%`,
          background:
            r.duration_min < 360
              ? 'var(--ui-text-primary)'
              : 'var(--ui-text-tertiary)',
          opacity: r.duration_min < 360 ? 0.9 : 0.5,
          borderRadius: '1px'
        }
      })
    )
  })
}

// ---------------------------------------------------------- error states

// Never invent a cause. Show what actually failed, then the one fix that is
// usually right, and let the user retry without a restart.
function backendError(e) {
  const detail =
    (e && (e.message || e.error || e.detail)) || String(e || 'no detail given')
  return (
    'Could not reach the Kairos backend.\n\n' +
    detail +
    '\n\nIts API routes are mounted when the gateway starts. If Kairos was ' +
    'installed or updated since then, restarting the gateway (⌘K → Restart ' +
    'gateway) usually fixes it. If it persists, the Python half may be ' +
    'disabled — check Capabilities → Plugins.'
  )
}

function ErrorState({ message, onRetry }) {
  return jsxs('div', {
    style: {
      padding: '16px',
      fontSize: '0.75rem',
      color: 'var(--ui-text-tertiary)',
      lineHeight: 1.5,
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      alignItems: 'flex-start'
    },
    children: [
      jsx('div', { style: { whiteSpace: 'pre-wrap' }, children: message }),
      onRetry
        ? jsx('button', {
            onClick: () => void onRetry(),
            style: {
              border: '1px solid var(--ui-stroke-secondary, currentColor)',
              background: 'transparent',
              color: 'var(--ui-text-secondary)',
              borderRadius: '4px',
              padding: '4px 10px',
              fontSize: '0.6875rem',
              cursor: 'pointer'
            },
            children: 'Retry'
          })
        : null
    ]
  })
}

// ---------------------------------------------------------------- pane

function KairosPane({ ctx }) {
  const [data, setData] = useState(null)
  const [pom, setPom] = useState(null)
  const [err, setErr] = useState(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await ctx.rest(`/summary?days=${DAYS}`)
      if (d && d.ok === false) {
        setErr(backendError(d))
      } else {
        setData(d)
        setErr(null)
      }
    } catch (e) {
      setErr(backendError(e))
    }
    // Optional readout; an older backend without the route just hides it.
    try {
      const p = await ctx.rest('/pomodoro')
      setPom(p && p.success ? p.pomodoro : null)
    } catch (e) {
      setPom(null)
    }
  }, [ctx])

  useEffect(() => {
    void load()
    const stop = ctx.setInterval(() => void load(), 60000)
    const off = host.onEvent('plugin.kairos.sleep.logged', () => void load())
    return () => {
      stop()
      off()
    }
  }, [ctx, load])

  const submit = useCallback(async () => {
    const value = draft.trim()
    if (!value) return
    setBusy(true)
    try {
      const out = await ctx.rest('/sleep', {
        method: 'POST',
        body: { duration: value }
      })
      if (out && out.success) {
        haptic('tap')
        host.notify({ kind: 'info', message: `Logged ${out.hours}h for ${out.night}` })
        setDraft('')
        await load()
      } else {
        host.notifyError((out && out.error) || 'Could not log that.')
      }
    } catch (e) {
      host.notifyError('Logging failed.')
    } finally {
      setBusy(false)
    }
  }, [ctx, draft, load])

  if (err) {
    return jsx(ErrorState, { message: err, onRetry: load })
  }
  if (!data) {
    return jsx('div', {
      style: { padding: '12px', fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)' },
      children: 'Reading your session history…'
    })
  }

  const an = data.analysis || {}
  const share = Math.round((data.after_11pm_share || 0) * 100)

  const section = (label, child) =>
    jsxs('div', {
      style: { display: 'flex', flexDirection: 'column', gap: '4px' },
      children: [
        jsx('div', {
          style: {
            fontSize: '0.5625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            color: 'var(--ui-text-tertiary)'
          },
          children: label
        }),
        child
      ]
    })

  const correlations = (an.correlations || []).slice(0, 4).map(c =>
    jsxs('div', {
      key: c.feature,
      style: { fontSize: '0.625rem', lineHeight: 1.45 },
      children: [
        jsx('span', {
          style: { color: verdictTone(c.verdict), fontWeight: 500 },
          children: c.verdict
        }),
        jsxs('span', {
          style: { color: 'var(--ui-text-secondary)' },
          children: [
            '  ',
            c.label || c.feature,
            c.r != null ? `  r=${c.r}` : '',
            c.ci ? `  CI${c.ci_level || ''}[${c.ci[0]}, ${c.ci[1]}]` : ''
          ]
        })
      ]
    })
  )

  return jsxs('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '14px',
      padding: '12px',
      overflowY: 'auto',
      height: '100%'
    },
    children: [
      // headline
      jsxs('div', {
        children: [
          jsxs('div', {
            style: { fontSize: '1.375rem', fontWeight: 600, lineHeight: 1.1 },
            children: [share, '%']
          }),
          jsx('div', {
            style: {
              fontSize: '0.625rem',
              color: 'var(--ui-text-tertiary)',
              lineHeight: 1.4
            },
            children: 'of your agent work happens between 23:00 and 05:00'
          })
        ]
      }),

      section(
        'activity by hour',
        jsx(Histogram, { hist: data.hour_histogram, peak: data.peak_hour })
      ),

      section('sleep, most recent 21 nights', jsx(SleepTrack, { rows: data.recent_sleep })),

      // log box
      section(
        'log last night',
        jsxs('div', {
          style: { display: 'flex', gap: '4px' },
          children: [
            jsx('input', {
              value: draft,
              disabled: busy,
              placeholder: '7h20m',
              onChange: e => setDraft(e.target.value),
              onKeyDown: e => {
                if (e.key === 'Enter') void submit()
              },
              style: {
                flex: 1,
                minWidth: 0,
                background: 'var(--ui-bg-secondary, transparent)',
                border: '1px solid var(--ui-border, currentColor)',
                borderRadius: '3px',
                padding: '3px 6px',
                fontSize: '0.6875rem',
                color: 'var(--ui-text-primary)'
              }
            }),
            jsx('button', {
              type: 'button',
              disabled: busy || !draft.trim(),
              onClick: () => void submit(),
              style: {
                border: '1px solid var(--ui-border, currentColor)',
                borderRadius: '3px',
                padding: '3px 8px',
                fontSize: '0.6875rem',
                cursor: busy ? 'default' : 'pointer',
                color: 'var(--ui-text-primary)',
                opacity: busy || !draft.trim() ? 0.5 : 1
              },
              children: busy ? '…' : 'log'
            })
          ]
        })
      ),

      // verdict
      section(
        'correlation',
        jsxs('div', {
          style: { display: 'flex', flexDirection: 'column', gap: '3px' },
          children: [
            jsx('div', {
              style: {
                fontSize: '0.625rem',
                fontWeight: 600,
                color: verdictTone(an.verdict)
              },
              children: an.verdict || '—'
            }),
            jsx('div', {
              style: {
                fontSize: '0.5938rem',
                color: 'var(--ui-text-tertiary)',
                lineHeight: 1.45
              },
              children: an.message || ''
            }),
            ...correlations
          ]
        })
      ),

      // guard state
      data.guard
        ? jsx('div', {
            style: {
              fontSize: '0.5938rem',
              color: 'var(--ui-text-tertiary)',
              borderTop: '1px solid var(--ui-border, currentColor)',
              paddingTop: '8px'
            },
            children:
              data.guard.enabled === 'true'
                ? `guard on · ${data.guard.quiet_start}–${data.guard.quiet_end} · ${data.guard.mode}`
                : 'quiet-hours guard off'
          })
        : null,

      // pomodoro clock, only when switched on
      pom && pom.enabled
        ? jsx('div', {
            title: pom.why_silent || '',
            style: { fontSize: '0.5938rem', color: 'var(--ui-text-tertiary)' },
            children:
              `${pom.ring} · ${pom.stretch_min} min` +
              (pom.last_reset_reason ? ` · last reset: ${pom.last_reset_reason}` : '')
          })
        : null
    ]
  })
}

// ------------------------------------------------------------ status chip

function KairosChip({ ctx }) {
  const [share, setShare] = useState(null)

  useEffect(() => {
    let alive = true
    const read = async () => {
      try {
        const d = await ctx.rest(`/summary?days=${DAYS}`)
        if (alive && d && d.ok !== false) setShare(d.after_11pm_share)
      } catch (e) {
        /* backend off — chip stays quiet */
      }
    }
    void read()
    const stop = ctx.setInterval(read, 300000)
    return () => {
      alive = false
      stop()
    }
  }, [ctx])

  if (share == null) return null

  return jsx('button', {
    type: 'button',
    title: 'Kairos — share of agent work in the small hours',
    onClick: () => {
      haptic('tap')
      host.navigate('/kairos')
    },
    style: {
      padding: '0 6px',
      fontSize: '0.6875rem',
      color: 'var(--ui-text-tertiary)',
      cursor: 'pointer'
    },
    children: `☾ ${Math.round(share * 100)}%`
  })
}

// ------------------------------------------------------------- settings

const TONE_COPY = {
  off: 'Measures only. Never brings sleep up.',
  gentle:
    'One quiet note near your bedtime, and only when you are at a clean stopping point. Nothing else.',
  encouraging:
    'A short heads-up on the runway, at your bedtime, and once after. Always an offer, never an instruction.',
  firm:
    'Everything in Encouraging, plus a confirmation step on destructive commands during your quiet hours.',
  guardian:
    'Everything in Firm, and destructive commands can be refused outright in quiet hours. Fully opt-in.'
}

const DELIVERY_COPY = {
  inject: 'In the conversation, between your turns.',
  both: 'In the conversation, plus a desktop notification when Hermes is not the window in front.'
}
// Legacy stored value from when a notification-only option existed.
const deliveryValue = v => (v === 'notify' ? 'both' : v || 'inject')

// One sentence each, shown as the input's tooltip rather than a paragraph.
const POMODORO_FIELDS = [
  { key: 'pomodoro_work_min', label: 'block', dflt: 25, min: 15, max: 120, step: 5,
    copy: 'Minutes of attention per block. 25 is the classic.' },
  { key: 'pomodoro_break_min', label: 'rest', dflt: 5, min: 3, max: 15, step: 1,
    copy: "Minutes off the screen per rest. It's what the offer says, and the quiet after a turn ends that counts as one." },
  { key: 'pomodoro_away_min', label: 'away', dflt: 8, min: 3, max: 30, step: 1,
    copy: 'Silence from you this long while the agent is working counts as a rest. Raise it if you sit and watch long runs.' }
]

function Row({ label, hint, children }) {
  return jsxs('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '4px',
      paddingBottom: '14px'
    },
    children: [
      jsx('div', { style: { fontSize: '0.75rem', fontWeight: 500 }, children: label }),
      hint
        ? jsx('div', {
            style: {
              fontSize: '0.6875rem',
              color: 'var(--ui-text-tertiary)',
              lineHeight: 1.45
            },
            children: hint
          })
        : null,
      jsx('div', { style: { marginTop: '2px' }, children })
    ]
  })
}

const inputStyle = {
  background: 'var(--ui-bg-secondary, transparent)',
  border: '1px solid var(--ui-border, currentColor)',
  borderRadius: '3px',
  padding: '4px 7px',
  fontSize: '0.75rem',
  color: 'var(--ui-text-primary)'
}

// Shared by every settings sub-page: each loads the goals it shows and
// saves through the same route, so pages never disagree about a value.
function useGoals(ctx, opts = {}) {
  const [g, setG] = useState(null)
  const [commits, setCommits] = useState([])
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const load = useCallback(async () => {
    try {
      const [gr, cr] = await Promise.all([
        ctx.rest('/goals'),
        opts.commitments
          ? ctx.rest('/commitments', { method: 'POST', body: { action: 'list' } })
          : null
      ])
      if (gr && gr.success === false) { setErr(backendError(gr)); return }
      setG(gr.goals)
      setCommits((cr && cr.commitments) || [])
      setErr(null)
    } catch (e) {
      setErr(backendError(e))
    }
  }, [ctx, opts.commitments])

  useEffect(() => { void load() }, [load])

  const save = useCallback(
    async patch => {
      setSaving(true)
      try {
        const out = await ctx.rest('/goals', {
          method: 'POST',
          body: { action: 'set', ...patch }
        })
        if (out && out.success === false) host.notifyError(out.error)
        else if (out && out.goals) setG(out.goals)
      } catch (e) {
        host.notifyError('Could not save.')
      } finally {
        setSaving(false)
      }
    },
    [ctx]
  )

  const fallback = err
    ? jsx(ErrorState, { message: err, onRetry: load })
    : jsx('div', {
        style: { padding: '16px', fontSize: '0.75rem', color: 'var(--ui-text-tertiary)' },
        children: 'Loading…'
      })
  return { g, commits, save, saving, fallback }
}

function Page({ title, intro, saving, children }) {
  return jsxs('div', {
    style: { padding: '18px', maxWidth: '620px', display: 'flex', flexDirection: 'column' },
    children: [
      jsx('div', {
        style: { fontSize: '0.8125rem', fontWeight: 600, paddingBottom: '4px' },
        children: title
      }),
      jsx('div', {
        style: {
          fontSize: '0.6875rem',
          color: 'var(--ui-text-tertiary)',
          lineHeight: 1.5,
          paddingBottom: '18px'
        },
        children: intro
      }),
      ...children,
      saving
        ? jsx('div', {
            style: { fontSize: '0.625rem', color: 'var(--ui-text-tertiary)' },
            children: 'saving…'
          })
        : null
    ]
  })
}

// Deep link to another Kairos settings sub-page. Older desktop builds may
// not export the helper, in which case the text simply isn't a link.
function settingsLink(page, label) {
  const href = typeof sdk.pluginSettingsHref === 'function'
    ? sdk.pluginSettingsHref('kairos', page)
    : null
  if (!href) return label
  return jsx('a', {
    href: '#',
    onClick: e => { e.preventDefault(); host.navigate(href) },
    style: { color: 'inherit', textDecoration: 'underline', cursor: 'pointer' },
    children: label
  })
}

function KairosSettings({ ctx }) {
  const s = useGoals(ctx)
  const [navOn, setNavOn] = useState(() => ctx.storage.get(NAV_KEY, false))
  if (!s.g) return s.fallback
  const { g, save } = s
  const noTarget = !g.target_bedtime
  return Page({
    title: 'Kairos',
    intro: 'There is no correct bedtime — Kairos measures you only against the one you set.',
    saving: s.saving,
    children: [
      Row({
        label: 'Bedtime you are aiming for',
        hint: noTarget
          ? 'Yours, not anyone else’s. 24h, e.g. 02:30. Blank means Kairos stays quiet about bedtime and just keeps measuring.'
          : 'Yours, not anyone else’s. 24h, e.g. 02:30.',
        children: jsx('input', {
          defaultValue: g.target_bedtime || '',
          placeholder: '02:30',
          onBlur: e => void save({ target_bedtime: e.target.value.trim() }),
          style: { ...inputStyle, width: '90px' }
        })
      }),

      Row({
        label: 'Sleep you want',
        hint: 'Minutes. 450 is 7h30.',
        children: jsx('input', {
          type: 'number',
          defaultValue: g.target_duration_min || 450,
          min: 180,
          max: 900,
          step: 15,
          onBlur: e =>
            void save({ target_duration_min: parseInt(e.target.value, 10) }),
          style: { ...inputStyle, width: '90px' }
        })
      }),

      Row({
        label: 'How present should it be?',
        hint: TONE_COPY[g.tone] || '',
        children: jsx('select', {
          value: g.tone || 'gentle',
          onChange: e => void save({ tone: e.target.value }),
          style: { ...inputStyle, width: '180px' },
          children: ['off', 'gentle', 'encouraging', 'firm', 'guardian'].map(t =>
            jsx('option', { value: t, children: t }, t)
          )
        })
      }),

      Row({
        label: 'Show Kairos in the sidebar',
        hint:
          'Off by default — a permanent row for something you open now and then is clutter. However this is set, the page stays reachable from ⌘K (“Open Kairos”) and as a pane.',
        children: jsxs('label', {
          style: { display: 'flex', gap: '5px', alignItems: 'center', fontSize: '0.75rem' },
          children: [
            jsx('input', {
              type: 'checkbox',
              checked: navOn,
              onChange: e => {
                const on = e.target.checked
                ctx.storage.set(NAV_KEY, on)
                setNavOn(on)
                _applyNav()
              }
            }),
            'keep a sidebar link'
          ]
        })
      })
    ]
  })
}

function KairosNudges({ ctx }) {
  const s = useGoals(ctx)
  if (!s.g) return s.fallback
  const { g, save } = s

  return Page({
    title: 'Nudges',
    intro: 'How and when the bedtime wind-down reaches you.',
    saving: s.saving,
    children: [
      Row({
        label: 'Where nudges arrive',
        hint: DELIVERY_COPY[deliveryValue(g.nudge_delivery)] || '',
        children: jsx('select', {
          value: deliveryValue(g.nudge_delivery),
          onChange: e => void save({ nudge_delivery: e.target.value }),
          style: { ...inputStyle, width: '180px' },
          children: ['inject', 'both'].map(t =>
            jsx('option', { value: t, children: t }, t)
          )
        })
      }),

      Row({
        label: 'How often it may speak',
        hint:
          'Minimum minutes between any two nudges. Before your bedtime each stage is mentioned once and then dropped; past your bedtime it may come back on this interval. 0 removes the spacing.',
        children: jsxs('div', {
          style: { display: 'flex', gap: '6px', alignItems: 'center' },
          children: [
            jsx('input', {
              type: 'number',
              defaultValue: g.nudge_gap_min || 45,
              min: 0,
              max: 240,
              step: 5,
              onBlur: e => void save({ nudge_gap_min: parseInt(e.target.value, 10) }),
              style: { ...inputStyle, width: '80px' }
            }),
            jsx('span', {
              style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)' },
              children: 'minutes apart, at most'
            })
          ]
        })
      }),

      Row({
        label: 'Wait for a natural stopping point',
        hint:
          'When a nudge comes due while recent tool calls are failing, hold it back and speak when the work settles instead. If nothing settles within the patience window it speaks anyway. On Gentle it simply stays quiet and misses the window.',
        children: jsxs('div', {
          style: { display: 'flex', gap: '10px', alignItems: 'center' },
          children: [
            jsxs('label', {
              style: {
                display: 'flex',
                gap: '5px',
                alignItems: 'center',
                fontSize: '0.75rem'
              },
              children: [
                jsx('input', {
                  type: 'checkbox',
                  checked: g.prefer_clean_break !== 'false',
                  onChange: e => void save({ prefer_clean_break: e.target.checked })
                }),
                'hold for a clean break'
              ]
            }),
            jsx('input', {
              type: 'number',
              defaultValue: g.clean_break_patience_min || 20,
              min: 0,
              max: 120,
              step: 5,
              disabled: g.prefer_clean_break === 'false',
              onBlur: e =>
                void save({ clean_break_patience_min: parseInt(e.target.value, 10) }),
              style: {
                ...inputStyle,
                width: '70px',
                opacity: g.prefer_clean_break === 'false' ? 0.4 : 1
              }
            }),
            jsx('span', {
              style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)' },
              children: 'min patience'
            })
          ]
        })
      }),

      Row({
        label: 'Ping me when I\'m not in Hermes',
        hint:
          'The in-chat nudge only reaches you mid-conversation. With a cron job calling kairos_ping, a bedtime hint can also arrive while the laptop is shut — or on your phone, if you point cron at a messaging channel. This switch silences it without you having to delete the job.',
        children: jsxs('label', {
          style: { display: 'flex', gap: '5px', alignItems: 'center', fontSize: '0.75rem' },
          children: [
            jsx('input', {
              type: 'checkbox',
              checked: g.ping_enabled === 'true',
              onChange: e => void save({ ping_enabled: e.target.checked })
            }),
            'allow scheduled pings'
          ]
        })
      })
    ]
  })
}

// Live clock for the Pomodoro settings page, refreshed every half minute.
function usePomodoro(ctx) {
  const [pom, setPom] = useState(null)
  useEffect(() => {
    let alive = true
    const read = async () => {
      try {
        const p = await ctx.rest('/pomodoro')
        if (alive) setPom(p && p.success ? p.pomodoro : null)
      } catch (e) {
        if (alive) setPom(null)
      }
    }
    void read()
    const stop = ctx.setInterval(read, 30000)
    return () => { alive = false; stop() }
  }, [ctx])
  return pom
}

function PomodoroReadout(pom, g) {
  const shared = jsxs('div', {
    style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)', lineHeight: 1.5, paddingBottom: '14px' },
    children: [
      'Uses your tone (Off silences it; Gentle only speaks at a clean spot) and the stopping-point patience from ',
      settingsLink('nudges', 'Nudges'),
      '.'
    ]
  })
  if (!pom || !pom.enabled || g.pomodoro_enabled !== 'true') return shared
  return jsxs('div', {
    children: [
      jsx('div', {
        title: pom.why_silent || '',
        style: { fontSize: '0.75rem', paddingBottom: '4px' },
        children:
          `${pom.ring} · ${pom.stretch_min} of ${pom.block_min} min · block ${pom.block}` +
          (pom.last_reset_reason ? ` · last reset: ${pom.last_reset_reason}` : '')
      }),
      jsx('div', {
        style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)', paddingBottom: '10px' },
        children: pom.due ? 'Due — it will offer at your next message.' : pom.why_silent
      }),
      shared
    ]
  })
}

function KairosPomodoroSettings({ ctx }) {
  const s = useGoals(ctx)
  const pom = usePomodoro(ctx)
  if (!s.g) return s.fallback
  const { g, save } = s

  return Page({
    title: 'Pomodoro',
    intro: 'A short rest offered once per work block, and only when the work is at a clean spot. Off until you switch it on.',
    saving: s.saving,
    children: [
      Row({
        label: 'Rhythm',
        hint: 'Hover a number for what it does.',
        children: jsxs('div', {
          style: { display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' },
          children: [
            jsxs('label', {
              style: { display: 'flex', gap: '5px', alignItems: 'center', fontSize: '0.75rem' },
              children: [
                jsx('input', {
                  type: 'checkbox',
                  checked: g.pomodoro_enabled === 'true',
                  onChange: e => void save({ pomodoro_enabled: e.target.checked })
                }),
                'offer rests'
              ]
            }),
            ...POMODORO_FIELDS.map(f =>
              jsxs(
                'label',
                {
                  title: f.copy,
                  style: {
                    display: 'flex',
                    gap: '4px',
                    alignItems: 'center',
                    fontSize: '0.6875rem',
                    color: 'var(--ui-text-tertiary)',
                    opacity: g.pomodoro_enabled === 'true' ? 1 : 0.4
                  },
                  children: [
                    f.label,
                    jsx('input', {
                      type: 'number',
                      defaultValue: g[f.key] || f.dflt,
                      min: f.min,
                      max: f.max,
                      step: f.step,
                      disabled: g.pomodoro_enabled !== 'true',
                      onBlur: e => void save({ [f.key]: parseInt(e.target.value, 10) }),
                      style: { ...inputStyle, width: '56px' }
                    }),
                    'min'
                  ]
                },
                f.key
              )
            )
          ]
        })
      }),
      PomodoroReadout(pom, g)
    ]
  })
}

function KairosSchedule({ ctx }) {
  const s = useGoals(ctx, { commitments: true })
  if (!s.g) return s.fallback
  const { g, save } = s
  const commits = s.commits
  return Page({
    title: 'Schedule',
    intro: 'Changes to your target that happen over days, and the morning question.',
    saving: s.saving,
    children: [
      Row({
        label: 'Gradually shift to a different bedtime',
        hint:
          'Optional. Abrupt schedule changes do not hold; roughly 15 min a week does. Leave blank to keep your target where it is.',
        children: jsxs('div', {
          style: { display: 'flex', gap: '6px', alignItems: 'center' },
          children: [
            jsx('input', {
              defaultValue: g.goal_bedtime || '',
              placeholder: '01:00',
              onBlur: e => void save({ goal_bedtime: e.target.value.trim() }),
              style: { ...inputStyle, width: '90px' }
            }),
            jsx('span', {
              style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)' },
              children: 'at'
            }),
            jsx('input', {
              type: 'number',
              defaultValue: g.ramp_min_per_week || 15,
              min: 5,
              max: 60,
              step: 5,
              onBlur: e =>
                void save({ ramp_min_per_week: parseInt(e.target.value, 10) }),
              style: { ...inputStyle, width: '70px' }
            }),
            jsx('span', {
              style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)' },
              children: 'min/week'
            })
          ]
        })
      }),

      Row({
        label: 'Morning check-in',
        hint:
          'One question, asked on a schedule so it never interrupts the start of a focused session. It never opens with a missed target.',
        children: jsxs('div', {
          style: { display: 'flex', gap: '8px', alignItems: 'center' },
          children: [
            jsxs('label', {
              style: {
                display: 'flex',
                gap: '5px',
                alignItems: 'center',
                fontSize: '0.75rem'
              },
              children: [
                jsx('input', {
                  type: 'checkbox',
                  checked: g.checkin_enabled === 'true',
                  onChange: e => void save({ checkin_enabled: e.target.checked })
                }),
                'enabled'
              ]
            }),
            jsx('input', {
              defaultValue: g.checkin_time || '10:00',
              onBlur: e => void save({ checkin_time: e.target.value.trim() }),
              style: { ...inputStyle, width: '80px' }
            }),
            jsx('input', {
              defaultValue: g.checkin_channel || 'desktop',
              placeholder: 'desktop',
              onBlur: e => void save({ checkin_channel: e.target.value.trim() }),
              style: { ...inputStyle, width: '140px' }
            })
          ]
        })
      }),

      jsx('div', {
        style: {
          borderTop: '1px solid var(--ui-border, currentColor)',
          marginTop: '4px',
          paddingTop: '14px'
        },
        children: Row({
          label: 'Early starts',
          hint:
            'Things that genuinely need you up early. Kairos works backwards from the wake time and eases the shift over the nights before, then returns to your normal target. Ask the agent to add these in conversation.',
          children: commits.length
            ? jsx('div', {
                style: { display: 'flex', flexDirection: 'column', gap: '4px' },
                children: commits.map(c =>
                  jsxs('div', {
                    style: {
                      fontSize: '0.6875rem',
                      display: 'flex',
                      justifyContent: 'space-between',
                      gap: '8px'
                    },
                    children: [
                      jsx('span', {
                        children: `${c.on_date} · up by ${c.wake_by}${
                          c.label ? ` · ${c.label}` : ''
                        }`
                      }),
                      jsx('span', {
                        style: { color: 'var(--ui-text-tertiary)' },
                        children: `eased over ${c.prep_days} night(s)`
                      })
                    ]
                  }, String(c.id))
                )
              })
            : jsx('div', {
                style: { fontSize: '0.6875rem', color: 'var(--ui-text-tertiary)' },
                children: 'None upcoming.'
              })
        })
      })
    ]
  })
}

// ---------------------------------------------------------------- plugin

export default {
  id: 'kairos',
  name: 'Kairos',
  defaultEnabled: false,
  register(ctx) {
    ctx.registerMany([
      {
        id: 'pane',
        area: 'panes',
        title: 'kairos',
        data: { placement: 'right', width: '300px' },
        render: () => jsx(KairosPane, { ctx })
      },
      {
        id: 'page',
        area: 'routes',
        data: { path: '/kairos' },
        render: () => jsx(KairosPane, { ctx })
      },
      {
        id: 'chip',
        area: 'statusBar.right',
        order: 128,
        render: () => jsx(KairosChip, { ctx })
      },
      {
        id: 'open',
        area: 'palette',
        data: {
          id: 'kairos.open',
          label: 'Open Kairos',
          keywords: ['sleep', 'kairos', 'night', 'circadian'],
          run: () => host.navigate('/kairos')
        }
      }
    ])

    // The Python half cannot post an OS notification (ctx.os is a Desktop
    // door), so it broadcasts the moment and this is where it becomes one.
    // Subscribed at register time, not inside a pane, so it works with the
    // pane closed. The SDK only shows it while Hermes is not in front; the
    // conversation block is delivered either way.
    const offNudge = host.onEvent('plugin.kairos.nudge.due', ev => {
      const p = (ev && (ev.payload || ev.params || ev.data)) || ev || {}
      const body = p.bedtime ? `Wind-down · ${p.bedtime} target` : 'Wind-down'
      try {
        void ctx.os.notify({ title: 'Kairos', body, activate: '/kairos' })
      } catch (_) {
        /* the capability may be absent; the conversation block still lands */
      }
    })
    ctx.onDispose(offNudge)

    // Sidebar row: registered only while the user asks for it.
    let disposeNav = () => {}
    _applyNav = () => {
      disposeNav()
      disposeNav = ctx.storage.get(NAV_KEY, false)
        ? ctx.register({
            id: 'nav',
            area: 'sidebar.nav',
            data: { path: '/kairos', label: 'Kairos', codicon: 'pulse' }
          })
        : () => {}
    }
    _applyNav()
    ctx.onDispose(() => disposeNav())

    ctx.registerSettingsPage({
      id: 'kairos',
      title: 'Kairos',
      icon: 'pulse',
      render: () => jsx(KairosSettings, { ctx }),
      children: [
        { id: 'nudges', title: 'Nudges', render: () => jsx(KairosNudges, { ctx }) },
        { id: 'pomodoro', title: 'Pomodoro', render: () => jsx(KairosPomodoroSettings, { ctx }) },
        { id: 'schedule', title: 'Schedule', render: () => jsx(KairosSchedule, { ctx }) }
      ]
    })
  }
}
