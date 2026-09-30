import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import Scene from '../components/Scene.jsx'
import Weather from '../components/Weather.jsx'
import GettingThere from '../components/GettingThere.jsx'

const ICON = { temple: '🛕', church: '⛪', mosque: '🕌' }
const to12 = (t) => {
  const [h, m] = t.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}
// Open if the destination's local time falls inside any session (temples often close at midday)
const isOpen = (p, hm) => p.sessions.some(([o, c]) => (o <= c ? hm >= o && hm <= c : hm >= o || hm <= c))

const reveal = { initial: { opacity: 0, y: 30 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true } }

export default function Destination() {
  const { id } = useParams()
  const [d, setD] = useState(null)
  const [weather, setWeather] = useState(null)
  const [wErr, setWErr] = useState(false)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    setD(null); setWeather(null); setWErr(false); setNotFound(false)
    fetch(`/api/destinations/${id}`).then((r) => (r.ok ? r.json() : Promise.reject())).then(setD).catch(() => setNotFound(true))
    fetch(`/api/destinations/${id}/weather`).then((r) => (r.ok ? r.json() : Promise.reject())).then(setWeather).catch(() => setWErr(true))
  }, [id])

  if (notFound) return <main className="section dark page"><h2 className="big">Destination not found</h2><Link to="/" className="btn btn-light">← Back home</Link></main>
  if (!d) return <main className="section dark page"><p className="muted-l">Loading…</p></main>
  const localHM = weather?.current.local_time.slice(11, 16)

  return (
    <main>
      <section className="hero detail-hero" style={{ '--h': d.hue }}>
        <div className="hero-scene"><Scene hue={d.hue} bubbles={false} /></div>
        <div className="hero-copy">
          <Link to="/" className="back">← All destinations</Link>
          <motion.h1 initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}>{d.name}</motion.h1>
          <p>{d.tagline} · {d.region}</p>
          <span className="chip light">{d.category}</span>
          <div className="hero-actions" style={{ marginTop: '18px' }}>
            <a href="#getting-there" className="btn btn-light">Book a train or bus →</a>
          </div>
        </div>
      </section>

      <section className="section dark page">
        <div className="detail-grid">
          <motion.article className="panel wide" {...reveal}>
            <h2>About</h2>
            <p>{d.summary}</p>
            <h3>History</h3>
            <p>{d.history}</p>
            <h3>Highlights</h3>
            <ul className="tags">{d.highlights.map((h) => <li key={h}>{h}</li>)}</ul>
            <p className="muted-l">Best time to visit: <strong>{d.best_time}</strong></p>
          </motion.article>

          <motion.aside className="panel blue" {...reveal}>
            <h2>Weather</h2>
            <Weather data={weather} error={wErr} />
          </motion.aside>

          <div id="getting-there" className="span-all">
            <GettingThere destId={d.id} destName={d.name} />
          </div>

          <motion.section className="panel wide" {...reveal}>
            <h2>Special events</h2>
            <div className="events">
              {d.events.map((e) => (
                <div className="event" key={e.name}>
                  <span className="when">{e.month}</span>
                  <h4>{e.name}</h4>
                  <p>{e.description}</p>
                </div>
              ))}
            </div>
          </motion.section>

          <motion.section className="panel" {...reveal}>
            <h2>Places of worship</h2>
            {weather && <p className="muted-l small">Local time {to12(localHM)}</p>}
            <ul className="worship">
              {d.worship.map((p) => {
                const open = localHM ? isOpen(p, localHM) : null
                return (
                  <li key={p.name}>
                    <span className="w-icon">{ICON[p.type]}</span>
                    <div>
                      <strong>{p.name}</strong>
                      {p.sessions.map(([o, c]) => (
                        <div className="times" key={o}>Opens {to12(o)} · Closes {to12(c)}</div>
                      ))}
                      {p.note && <div className="muted-l small">{p.note}</div>}
                    </div>
                    {open !== null && <span className={'badge ' + (open ? 'on' : 'off')}>{open ? 'Open now' : 'Closed'}</span>}
                  </li>
                )
              })}
            </ul>
            <p className="muted-l small">Timings are indicative and change on festival days.</p>
          </motion.section>
        </div>
      </section>
    </main>
  )
}
