import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'
import { dateLabel, inrPaise } from '../format.js'

function Balance({ paise }) {
  if (!paise) return <span className="chip">Settled</span>
  return <span className={'chip ' + (paise > 0 ? 'owed' : 'owes')}>{paise > 0 ? `You're owed ${inrPaise(paise)}` : `You owe ${inrPaise(-paise)}`}</span>
}

/* Your trips, plus creating one or joining a friend's with their code. */
export default function Trips() {
  const { user, ready } = useAuth()
  const nav = useNavigate()
  const [rows, setRows] = useState(null)
  const [name, setName] = useState('')
  const [start, setStart] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => api('/api/trips').then(setRows).catch((e) => setErr(e.message)), [])
  useEffect(() => { if (user) load() }, [user, load])

  async function create(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const t = await api('/api/trips', { method: 'POST', body: { name, start_date: start || null } })
      nav(`/trips/${t.id}`)
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  async function join(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const t = await api('/api/trips/join', { method: 'POST', body: { code } })
      nav(`/trips/${t.id}`)
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  if (!ready) return <main className="section dark page"><p className="muted-l">Loading…</p></main>
  if (!user) return <Navigate to="/login" replace state={{ next: '/trips' }} />

  return (
    <main className="section dark page">
      <h1 className="big">Group trips</h1>
      <p className="muted-l">Plan together: a shared itinerary, polls to settle arguments, and expenses split fairly with a simple way to settle up.</p>

      <div className="trips-forms">
        <form className="panel" onSubmit={create}>
          <h2>Start a trip</h2>
          <label className="form-label">Trip name<input className="search" value={name} onChange={(e) => setName(e.target.value)} placeholder="Pongal road trip" maxLength={80} required /></label>
          <label className="form-label">Start date <span className="muted small">(optional)</span><input className="search" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <button className="btn btn-light" disabled={busy}>Create trip</button>
        </form>
        <form className="panel" onSubmit={join}>
          <h2>Join with a code</h2>
          <label className="form-label">Invite code<input className="search mono" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="ABCD2345" maxLength={8} required /></label>
          <button className="btn btn-light" disabled={busy || code.length < 8}>Join trip</button>
        </form>
      </div>
      {err && <p className="notice" role="alert">{err}</p>}

      <h2 className="section-title">Your trips</h2>
      {rows && rows.length === 0 && <p className="muted-l">No trips yet. Start one above, or ask a friend for their code.</p>}
      <div className="trip-cards">
        {(rows || []).map((t, i) => (
          <motion.div key={t.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 8) * 0.05 }}>
            <Link to={`/trips/${t.id}`} className="panel trip-card">
              <header><h3>{t.name}</h3>{t.role === 'owner' && <span className="chip">Owner</span>}</header>
              <p className="muted small">{t.start_date ? dateLabel(t.start_date) + ' · ' : ''}{t.members} {t.members === 1 ? 'person' : 'people'} · {t.items} item{t.items === 1 ? '' : 's'}</p>
              <Balance paise={t.balance} />
            </Link>
          </motion.div>
        ))}
      </div>
    </main>
  )
}

/* A shared link: /trips/join/ABCD2345 */
export function TripJoin() {
  const { code } = useParams()
  const { user, ready } = useAuth()
  const nav = useNavigate()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function join() {
    setErr(''); setBusy(true)
    try {
      const t = await api('/api/trips/join', { method: 'POST', body: { code } })
      nav(`/trips/${t.id}`, { replace: true })
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }

  if (!ready) return <main className="section dark page"><p className="muted-l">Loading…</p></main>
  if (!user) return <Navigate to="/login" replace state={{ next: `/trips/join/${code}` }} />
  return (
    <main className="section dark page">
      <div className="panel join-card">
        <h1>You've been invited to a trip</h1>
        <p className="muted-l">Join to see the itinerary and shared expenses. Invite code <span className="mono">{code}</span></p>
        {err && <p className="notice" role="alert">{err}</p>}
        <button className="btn btn-light" onClick={join} disabled={busy}>{busy ? 'Joining…' : 'Join this trip'}</button>
        <Link to="/trips" className="pill">Not now</Link>
      </div>
    </main>
  )
}
