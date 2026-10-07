import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../auth.jsx'
import TransportResults from './TransportResults.jsx'

const tomorrow = () => new Date(Date.now() + 864e5).toISOString().slice(0, 10)

/* The "Getting to <place>" panel on a destination page: pick a boarding point and a date.
   Searching and booking live in TransportResults, which the Tickets page shares. */
export default function GettingThere({ destId, destName }) {
  const [hubs, setHubs] = useState([])
  const [from, setFrom] = useState('')
  const [geo, setGeo] = useState({ state: 'idle', msg: '' })
  const [date, setDate] = useState(tomorrow())
  const [quota, setQuota] = useState('general')
  const [tab, setTab] = useState('train')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [nonce, setNonce] = useState(0)  // bumped after a booking so seat counts re-fetch

  /* Boarding points: ask the browser where the traveller is, and fall back to a full list. */
  const locate = useCallback(() => {
    if (!navigator.geolocation) return setGeo({ state: 'off', msg: 'This browser cannot share a location.' })
    setGeo({ state: 'locating', msg: '' })
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        api(`/api/transport/hubs?lat=${coords.latitude}&lon=${coords.longitude}`)
          .then((d) => {
            setHubs(d.hubs)
            setFrom((f) => f || d.nearest.code)
            setGeo({ state: 'ok', msg: `${d.nearest.city} · ${d.nearest.km} km from you` })
          })
          .catch(() => setGeo({ state: 'off', msg: 'Could not load boarding points.' }))
      },
      (e) => {
        setGeo({ state: 'denied', msg: e.code === 1 ? 'Location permission denied — pick a boarding point instead.' : 'Could not read your location.' })
        api('/api/transport/hubs').then((d) => setHubs(d.hubs)).catch(() => {})
      },
      { timeout: 10000, maximumAge: 300000 },
    )
  }, [])

  useEffect(() => {
    api('/api/transport/hubs').then((d) => { setHubs(d.hubs); setFrom((f) => f || 'MAS') }).catch(() => {})
    if (navigator.permissions?.query) {
      navigator.permissions.query({ name: 'geolocation' })
        .then((p) => { if (p.state === 'granted') locate() })
        .catch(() => {})
    }
  }, [locate])

  useEffect(() => {
    if (!from) return
    setLoading(true)
    api(`/api/destinations/${destId}/transport?from=${from}&date=${date}&quota=${quota}`)
      .then((d) => {
        setData(d)
        if (d.no_rail_link || d.trains_sold_out) setTab('bus')
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [destId, from, date, quota, nonce])

  const hubOptions = useMemo(
    () => hubs.map((h) => <option key={h.code} value={h.code}>{h.city} — {h.name}{h.km != null ? ` (${h.km} km)` : ''}</option>),
    [hubs],
  )

  return (
    <motion.section className="panel wide getting" initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}>
      <h2>Getting to {destName}</h2>
      <p className="muted-l small">
        Book a train — with Tatkal when you are travelling tomorrow — or fall back to a bus from wherever you are.
      </p>

      <div className="gt-controls">
        <label className="gt-field">
          <span>Boarding from</span>
          <select value={from} onChange={(e) => setFrom(e.target.value)}>
            {hubOptions}
          </select>
        </label>
        <label className="gt-field">
          <span>Journey date</span>
          <input type="date" value={date} min={data?.today} onChange={(e) => setDate(e.target.value)} />
        </label>
        <button type="button" className="pill locate" onClick={locate} disabled={geo.state === 'locating'}>
          {geo.state === 'locating' ? 'Locating…' : '◎ Use my location'}
        </button>
      </div>
      {geo.msg && <p className={'muted small geo ' + geo.state}>{geo.msg}</p>}

      <TransportResults
        data={data} loading={loading} tab={tab} setTab={setTab} quota={quota} setQuota={setQuota} date={date}
        noTrainText={`No train runs all the way to ${destName}.`}
        onBooked={() => setNonce((n) => n + 1)}
      />
    </motion.section>
  )
}
