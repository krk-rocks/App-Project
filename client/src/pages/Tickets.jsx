import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api } from '../auth.jsx'
import TransportResults from '../components/TransportResults.jsx'

const tomorrow = () => new Date(Date.now() + 864e5).toISOString().slice(0, 10)

// Straight-line distance in km between two lat/lon points.
const distanceKm = (a, b) => {
  const rad = (x) => (x * Math.PI) / 180
  const h = Math.sin(rad(b.lat - a.lat) / 2) ** 2
    + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(rad(b.lon - a.lon) / 2) ** 2
  return 12742 * Math.asin(Math.sqrt(h))
}

/* Book a train or bus between any two places on the site. */
export default function Tickets() {
  const [params, setParams] = useSearchParams()
  const [places, setPlaces] = useState([])
  const [from, setFrom] = useState(params.get('from') || 'chennai')
  const [to, setTo] = useState(params.get('to') || 'madurai')
  const [date, setDate] = useState(params.get('date') || tomorrow())
  const [quota, setQuota] = useState('general')
  const [tab, setTab] = useState('train')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [geo, setGeo] = useState({ state: 'idle', msg: '' })
  const [nonce, setNonce] = useState(0)  // bumped after a booking so seat counts re-fetch
  const lastRoute = useRef('')

  useEffect(() => {
    api('/api/destinations?q=&category=')
      .then((d) => setPlaces((Array.isArray(d) ? d : []).sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setError('Could not load the list of places. Is the backend running?'))
  }, [])

  const byId = useMemo(() => Object.fromEntries(places.map((p) => [p.id, p])), [places])

  // A link can carry any ?from=&to= - fall back to sensible places if they are not on the site.
  useEffect(() => {
    if (!places.length) return
    const ok = (id) => !!byId[id]
    const f = ok(from) ? from : 'chennai'
    let t = ok(to) ? to : 'madurai'
    if (f === t) t = places.find((p) => p.id !== f).id
    if (f !== from) setFrom(f)
    if (t !== to) setTo(t)
  }, [places, byId, from, to])

  useEffect(() => {
    if (places.length) setParams({ from, to, date }, { replace: true })
  }, [places.length, from, to, date, setParams])

  useEffect(() => {
    if (!byId[from] || !byId[to] || from === to) return undefined
    let live = true
    setLoading(true)
    setError('')
    api(`/api/destinations/${to}/transport?from=${from}&date=${date}&quota=${quota}`)
      .then((d) => {
        if (!live) return
        setData(d)
        const route = `${from}>${to}`
        if (d.no_rail_link || d.trains_sold_out) setTab('bus')
        else if (route !== lastRoute.current) setTab('train')
        lastRoute.current = route
      })
      .catch((e) => { if (live) { setData(null); setError(e.message) } })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [byId, from, to, date, quota, nonce])

  // Picking the place that is already on the other end swaps them instead of making a route to itself.
  const pickFrom = (v) => { if (v === to) setTo(from); setFrom(v) }
  const pickTo = (v) => { if (v === from) setFrom(to); setTo(v) }
  const swap = () => { setFrom(to); setTo(from) }

  const locate = () => {
    if (!navigator.geolocation) return setGeo({ state: 'off', msg: 'This browser cannot share a location.' })
    setGeo({ state: 'locating', msg: '' })
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const here = { lat: coords.latitude, lon: coords.longitude }
        const near = places.filter((p) => p.id !== to)
          .map((p) => ({ ...p, km: distanceKm(here, p) }))
          .sort((a, b) => a.km - b.km)[0]
        setFrom(near.id)
        setGeo({ state: 'ok', msg: `Nearest place on Epic TN: ${near.name} · about ${Math.round(near.km)} km from you` })
      },
      (e) => setGeo({ state: 'denied', msg: e.code === 1 ? 'Location permission denied. Pick where you are leaving from instead.' : 'Could not read your location.' }),
      { timeout: 10000, maximumAge: 300000 },
    )
  }

  const fromName = byId[from]?.name || ''
  const toName = byId[to]?.name || ''

  return (
    <main className="section dark page tk-page">
      <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: 'easeOut' }}>
        <h1 className="big">Book tickets</h1>
        <p className="muted-l">Choose where you are leaving from and where you are going. We will show the trains, with Tatkal, and the buses between them.</p>

        <section className="panel tk-panel">
          <div className="tk-controls">
            <label className="gt-field">
              <span>From</span>
              <select value={from} onChange={(e) => pickFrom(e.target.value)} disabled={!places.length}>
                {places.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <button type="button" className="tk-swap" onClick={swap} aria-label="Swap From and To" title="Swap From and To">⇄</button>
            <label className="gt-field">
              <span>To</span>
              <select value={to} onChange={(e) => pickTo(e.target.value)} disabled={!places.length}>
                {places.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label className="gt-field tk-date">
              <span>Journey date</span>
              <input type="date" value={date} min={data?.today} onChange={(e) => setDate(e.target.value)} />
            </label>
            <button type="button" className="pill locate" onClick={locate} disabled={geo.state === 'locating' || !places.length}>
              {geo.state === 'locating' ? 'Locating…' : '◎ Use my location'}
            </button>
          </div>
          {geo.msg && <p className={'muted small geo ' + geo.state}>{geo.msg}</p>}

          {error && <p className="notice">{error}</p>}

          {fromName && toName && <h2 className="tk-route">{fromName} <span aria-hidden="true">→</span><span className="sr-only"> to </span> {toName}</h2>}

          <TransportResults
            data={data} loading={loading} tab={tab} setTab={setTab} quota={quota} setQuota={setQuota} date={date}
            noTrainText={`No direct train between ${fromName} and ${toName}.`}
            onBooked={() => setNonce((n) => n + 1)}
          />
        </section>
      </motion.div>
    </main>
  )
}
