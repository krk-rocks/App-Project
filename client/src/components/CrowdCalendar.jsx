import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../auth.jsx'
import { dateLabel, shortDate, todayISO } from '../format.js'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const LEVEL_TEXT = { Low: 'Quiet', Medium: 'Moderate', High: 'Busy' }

/* A 12-week heat calendar of how busy the town is likely to be. It is a transparent estimate (weekends, holidays,
   festival months, season), not measured visitor numbers, and every reason is listed when you pick a day. */
export default function CrowdCalendar({ destId, destName, onPickDate }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(false)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    let live = true
    setData(null); setErr(false); setSel(null)
    api(`/api/destinations/${destId}/crowd?days=84`).then((d) => { if (live) setData(d) }).catch(() => { if (live) setErr(true) })
    return () => { live = false }
  }, [destId])

  const quiet = useMemo(
    () => (data ? [...data.days].filter((d) => d.level === 'Low').sort((a, b) => a.score - b.score || a.date.localeCompare(b.date)).slice(0, 4) : []),
    [data],
  )
  if (err) return <p className="muted-l">The crowd forecast isn't available right now.</p>
  if (!data) return <p className="muted-l">Loading the calendar…</p>

  const lead = (new Date(data.days[0].date + 'T00:00').getDay() + 6) % 7           // Monday-first grid
  const today = todayISO()
  const picked = sel && data.days.find((d) => d.date === sel)

  return (
    <div className="crowd">
      <div className="crowd-legend" aria-hidden="true">
        {Object.entries(LEVEL_TEXT).map(([k, v]) => <span key={k}><i className={'dot c-' + k.toLowerCase()} /> {v}</span>)}
      </div>

      <div className="crowd-grid" role="grid" aria-label={`Expected crowds in ${destName}`}>
        {WEEKDAYS.map((w) => <span key={w} className="crowd-h" role="columnheader">{w}</span>)}
        {Array.from({ length: lead }, (_, i) => <span key={'p' + i} className="crowd-pad" />)}
        {data.days.map((d, i) => {
          const day = Number(d.date.slice(8))
          return (
            <button key={d.date} type="button" role="gridcell"
              className={`crowd-cell c-${d.level.toLowerCase()}${sel === d.date ? ' sel' : ''}${d.date === today ? ' today' : ''}`}
              aria-label={`${dateLabel(d.date)}: ${LEVEL_TEXT[d.level]}`} aria-pressed={sel === d.date} onClick={() => setSel(d.date)}>
              {(day === 1 || i === 0) && <small>{new Date(d.date + 'T00:00').toLocaleDateString('en-IN', { month: 'short' })}</small>}
              {day}
            </button>
          )
        })}
      </div>

      {quiet.length > 0 && (
        <p className="crowd-quiet">
          <span className="muted small">Quietest days coming up:</span>{' '}
          {quiet.map((q) => <button key={q.date} type="button" className="chipbtn" onClick={() => setSel(q.date)}>{shortDate(q.date)}</button>)}
        </p>
      )}

      {picked && (
        <motion.div key={picked.date} className="crowd-detail" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <div className="crowd-detail-head">
            <strong>{new Date(picked.date + 'T00:00').toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}</strong>
            <span className={'lvl c-' + picked.level.toLowerCase()}>{LEVEL_TEXT[picked.level]}</span>
          </div>
          <ul>
            {picked.factors.map((f) => <li key={f.label}><span>{f.label}</span><span className={f.points < 0 ? 'neg' : 'pos'}>{f.points > 0 ? '+' : ''}{f.points}</span></li>)}
          </ul>
          {onPickDate && picked.date >= today && <button type="button" className="pill" onClick={() => onPickDate(picked.date)}>Use {shortDate(picked.date)} as my check-in</button>}
        </motion.div>
      )}
      <p className="muted small">{data.note}</p>
    </div>
  )
}
