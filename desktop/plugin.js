// Hypnos — Desktop half.
// Strictly inside the plugin SDK surface: no prototype patching, no eval,
// no app-markup queries, no DOM observers. Data comes from this package's
// own backend namespace via ctx.rest.
import { host, haptic, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useCallback, useEffect, useState } from 'react'

const DAYS = 120

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

// ---------------------------------------------------------------- pane

function HypnosPane({ ctx }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await ctx.rest(`/summary?days=${DAYS}`)
      if (d && d.ok === false) {
        setErr(d.error || 'backend unavailable')
      } else {
        setData(d)
        setErr(null)
      }
    } catch (e) {
      setErr('Python half not enabled — see Capabilities → Plugins.')
    }
  }, [ctx])

  useEffect(() => {
    void load()
    const stop = ctx.setInterval(() => void load(), 60000)
    const off = host.onEvent('plugin.hypnos.sleep.logged', () => void load())
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
    return jsx('div', {
      style: {
        padding: '12px',
        fontSize: '0.6875rem',
        color: 'var(--ui-text-tertiary)',
        lineHeight: 1.5
      },
      children: err
    })
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
            c.ci95 ? `  CI[${c.ci95[0]}, ${c.ci95[1]}]` : ''
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
        : null
    ]
  })
}

// ------------------------------------------------------------ status chip

function HypnosChip({ ctx }) {
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
    title: 'Hypnos — share of agent work in the small hours',
    onClick: () => {
      haptic('tap')
      host.navigate('/hypnos')
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
  notify: 'A desktop notification.',
  both: 'Both.'
}

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

function HypnosSettings({ ctx }) {
  const [g, setG] = useState(null)
  const [commits, setCommits] = useState([])
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const load = useCallback(async () => {
    try {
      const [gr, cr] = await Promise.all([
        ctx.rest('/goals'),
        ctx.rest('/commitments', { method: 'POST', body: { action: 'list' } })
      ])
      if (gr && gr.success === false) { setErr(gr.error); return }
      setG(gr.goals)
      setCommits((cr && cr.commitments) || [])
      setErr(null)
    } catch (e) {
      setErr('Hypnos backend unavailable. Enable the plugin in config.yaml.')
    }
  }, [ctx])

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

  if (err) {
    return jsx('div', {
      style: { padding: '16px', fontSize: '0.75rem', color: 'var(--ui-text-tertiary)' },
      children: err
    })
  }
  if (!g) {
    return jsx('div', {
      style: { padding: '16px', fontSize: '0.75rem', color: 'var(--ui-text-tertiary)' },
      children: 'Loading…'
    })
  }

  const noTarget = !g.target_bedtime

  return jsxs('div', {
    style: {
      padding: '18px',
      maxWidth: '620px',
      display: 'flex',
      flexDirection: 'column'
    },
    children: [
      jsx('div', {
        style: { fontSize: '0.8125rem', fontWeight: 600, paddingBottom: '4px' },
        children: 'Hypnos'
      }),
      jsx('div', {
        style: {
          fontSize: '0.6875rem',
          color: 'var(--ui-text-tertiary)',
          lineHeight: 1.5,
          paddingBottom: '18px'
        },
        children:
          'There is no correct bedtime. 02:30 is as valid as 22:00 — Hypnos only ever measures you against the target you set here, and stays silent until you set one.'
      }),

      noTarget
        ? jsx('div', {
            style: {
              fontSize: '0.6875rem',
              border: '1px solid var(--ui-border, currentColor)',
              borderRadius: '4px',
              padding: '8px 10px',
              marginBottom: '16px',
              color: 'var(--ui-text-secondary)'
            },
            children:
              'No target set, so Hypnos is currently silent. It will keep measuring your work pattern either way.'
          })
        : null,

      Row({
        label: 'Bedtime you are aiming for',
        hint: 'Yours, not anyone else’s. 24h, e.g. 02:30.',
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
        label: 'Where nudges arrive',
        hint: DELIVERY_COPY[g.nudge_delivery] || '',
        children: jsx('select', {
          value: g.nudge_delivery || 'inject',
          onChange: e => void save({ nudge_delivery: e.target.value }),
          style: { ...inputStyle, width: '180px' },
          children: ['inject', 'notify', 'both'].map(t =>
            jsx('option', { value: t, children: t }, t)
          )
        })
      }),

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
            'Things that genuinely need you up early. Hypnos works backwards from the wake time and eases the shift over the nights before, then returns to your normal target. Ask the agent to add these in conversation.',
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
      }),

      saving
        ? jsx('div', {
            style: { fontSize: '0.625rem', color: 'var(--ui-text-tertiary)' },
            children: 'saving…'
          })
        : null
    ]
  })
}

// ---------------------------------------------------------------- plugin

export default {
  id: 'hypnos',
  name: 'Hypnos',
  defaultEnabled: false,
  register(ctx) {
    ctx.registerMany([
      {
        id: 'pane',
        area: 'panes',
        title: 'hypnos',
        data: { placement: 'right', width: '300px' },
        render: () => jsx(HypnosPane, { ctx })
      },
      {
        id: 'page',
        area: 'routes',
        data: { path: '/hypnos' },
        render: () => jsx(HypnosPane, { ctx })
      },
      {
        id: 'nav',
        area: 'sidebar.nav',
        data: { path: '/hypnos', label: 'Hypnos', codicon: 'pulse' }
      },
      {
        id: 'chip',
        area: 'statusBar.right',
        order: 128,
        render: () => jsx(HypnosChip, { ctx })
      },
      {
        id: 'open',
        area: 'palette',
        data: {
          id: 'hypnos.open',
          label: 'Open Hypnos',
          keywords: ['sleep', 'hypnos', 'night', 'circadian'],
          run: () => host.navigate('/hypnos')
        }
      }
    ])

    ctx.registerSettingsPage({
      id: 'hypnos',
      title: 'Hypnos',
      icon: 'pulse',
      render: () => jsx(HypnosSettings, { ctx })
    })
  }
}
