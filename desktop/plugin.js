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
  }
}
