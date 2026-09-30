import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'

const rupees = (n) => '₹' + Number(n || 0).toLocaleString('en-IN')
const to12 = (t) => {
  if (!t) return ''
  const [h, m] = t.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`
}

export default function Bookings() {
  const { user, ready } = useAuth()
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!user) return
    api('/api/bookings').then(setRows).catch((e) => setErr(e.message))
  }, [user])

  async function cancel(id) {
    try {
      const updated = await api(`/api/bookings/${id}/cancel`, { method: 'POST' })
      setRows((r) => r.map((b) => (b.id === id ? updated : b)))
    } catch (e) {
      setErr(e.message)
    }
  }

  if (!ready) return <main className="section dark page"><p className="muted-l">Loading…</p></main>
  if (!user) return <Navigate to="/login" replace state={{ next: '/bookings' }} />

  return (
    <main className="section dark page">
      <h1 className="big">Your tickets</h1>
      <p className="muted-l">Signed in as {user.email}</p>
      {err && <p className="notice">{err}</p>}
      {rows && rows.length === 0 && (
        <p className="muted-l">Nothing booked yet. Open a destination and look for <strong>Getting there</strong>. <Link to="/" className="card-cta">Browse destinations →</Link></p>
      )}
      <div className="ticket-list">
        {(rows || []).map((b, i) => (
          <motion.article key={b.id} className={'panel tick' + (b.status === 'CANCELLED' ? ' void' : '')}
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <header>
              <span className={'badge ' + (b.status === 'CONFIRMED' ? 'on' : b.status === 'RAC' ? 'rac' : 'off')}>{b.status}</span>
              <span className="chip">{b.kind === 'train' ? 'Train' : 'Bus'}</span>
            </header>
            <h3>{b.kind === 'train' ? `${b.train_no} ${b.train_name}` : `${b.operator} · ${b.type}`}</h3>
            <p className="muted-l">{b.from_name} → {b.to_name}</p>
            <dl className="tick-grid">
              <div><dt>{b.kind === 'train' ? 'PNR' : 'Ticket'}</dt><dd className="mono">{b.pnr || b.ticket}</dd></div>
              <div><dt>Date</dt><dd>{b.date}</dd></div>
              <div><dt>Departs</dt><dd>{to12(b.depart)}</dd></div>
              {b.kind === 'train'
                ? <><div><dt>Class</dt><dd>{b.cls_label}</dd></div><div><dt>Quota</dt><dd>{b.quota === 'tatkal' ? 'Tatkal' : 'General'}</dd></div></>
                : <div><dt>Seats</dt><dd>{b.seats.join(', ')}</dd></div>}
              <div><dt>Total</dt><dd>{rupees(b.total)}</dd></div>
            </dl>
            <ul className="tick-pax">
              {b.passengers.map((p, j) => <li key={j}><span>{p.name}</span><span className="muted small">{p.age} · {p.gender}</span></li>)}
            </ul>
            {b.status !== 'CANCELLED' && (
              <button className="pill" onClick={() => cancel(b.id)}>Cancel booking</button>
            )}
          </motion.article>
        ))}
      </div>
      <p className="muted small demo-note">Simulated tickets. Not valid for travel and not connected to IRCTC or any operator.</p>
    </main>
  )
}
