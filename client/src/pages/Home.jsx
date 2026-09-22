import { useEffect, useState } from 'react'
import { motion, useScroll, useTransform } from 'framer-motion'
import Scene from '../components/Scene.jsx'
import TiltCard from '../components/TiltCard.jsx'

const FEATURES = [
  { tag: 'Live', title: 'Weather, right now', text: 'Current conditions and a 5-day forecast for every Tamil Nadu destination, pulled live.' },
  { tag: 'Local', title: 'Events & festivals', text: 'Chithirai, Pongal, Margazhi and more: the special events in each area, month by month.' },
  { tag: 'Sacred', title: 'Worship timings', text: 'Opening and closing times for temples, churches and mosques, including midday breaks, with an open-now badge.' },
]

export default function Home() {
  const [items, setItems] = useState([])
  const [cats, setCats] = useState([])
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const [error, setError] = useState(false)
  const { scrollY } = useScroll()
  const sceneY = useTransform(scrollY, [0, 700], [0, 160])
  const sceneOpacity = useTransform(scrollY, [0, 600], [1, 0.15])

  useEffect(() => {
    fetch('/api/categories').then((r) => r.json()).then(setCats).catch(() => setError(true))
  }, [])
  useEffect(() => {
    const t = setTimeout(() => {
      const p = new URLSearchParams({ q, category: cat })
      fetch('/api/destinations?' + p).then((r) => r.json()).then((d) => { setItems(d); setError(false) }).catch(() => setError(true))
    }, 200)
    return () => clearTimeout(t)
  }, [q, cat])

  return (
    <main>
      <section className="hero">
        <motion.div className="hero-scene" style={{ y: sceneY, opacity: sceneOpacity }}><Scene hue={275} extras /></motion.div>
        <div className="hero-copy">
          <motion.h1 initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.9 }}>
            Discover<br />Tamil Nadu in 3D.
          </motion.h1>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}>
            Deep guides to temple towns, hill stations and coasts, with live weather, local festivals and temple, church and mosque timings.
          </motion.p>
          <motion.div className="hero-actions" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }}>
            <a href="#destinations" className="btn btn-dark">Browse destinations</a>
            <a href="#features" className="btn btn-light">What you get</a>
          </motion.div>
        </div>
        <a href="#features" className="dive">Scroll down &amp; dive in <span>↓</span></a>
      </section>

      <section id="features" className="section dark">
        <div className="feature-row">
          {FEATURES.map((f, i) => (
            <motion.div key={f.title} className={`feature f${i}`} initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.12 }}>
              <span className="muted-l">{f.tag}</span>
              <h2>{f.title}</h2>
              <p>{f.text}</p>
            </motion.div>
          ))}
        </div>
      </section>

      <section id="destinations" className="section dark">
        <h2 className="big">Explore Tamil Nadu</h2>
        <div className="filters">
          <input className="search" placeholder="Search a town, temple or hill station..." value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="pills">
            {['', ...cats].map((c) => (
              <button key={c || 'all'} className={'pill' + (cat === c ? ' active' : '')} onClick={() => setCat(c)}>{c || 'All'}</button>
            ))}
          </div>
        </div>
        {error && <p className="notice">Can't reach the backend. Start it with <code>python app.py</code> in the backend folder.</p>}
        <div className="grid" id="explore">
          {items.map((d, i) => <TiltCard key={d.id} d={d} index={i} />)}
        </div>
        {!error && items.length === 0 && <p className="muted-l">No destinations match your search.</p>}
      </section>
    </main>
  )
}
