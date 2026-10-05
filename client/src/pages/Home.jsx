import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import TiltCard from '../components/TiltCard.jsx'
import { api } from '../auth.jsx'

const INK = '#1f1f1f'
const FEATURED = ['Madurai', 'Rameswaram', 'Ooty', 'Thanjavur', 'Mahabalipuram']

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

  useEffect(() => {
    api('/api/categories').then(setCats).catch(() => setError(true))
  }, [])
  useEffect(() => {
    const t = setTimeout(() => {
      const p = new URLSearchParams({ q, category: cat })
      api('/api/destinations?' + p).then((d) => { setItems(d); setError(false) }).catch(() => setError(true))
    }, 200)
    return () => clearTimeout(t)
  }, [q, cat])

  return (
    <main>
      <section style={{ position: 'relative', width: '100%', height: '100vh', overflow: 'hidden' }}>
        <video style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} src="/hero.mp4" autoPlay muted loop playsInline />
        {/* Overlays — opacity reduced by 70% */}
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.13)' }} />
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(to bottom, rgba(0,0,0,0.17) 0%, transparent 22%, transparent 60%, rgba(0,0,0,0.25) 100%)' }} />
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(to right, rgba(0,0,0,0.10) 0%, transparent 18%, transparent 82%, rgba(0,0,0,0.10) 100%)' }} />
        <div style={{ position: 'absolute', top: '-14%', left: '50%', transform: 'translateX(-50%)', width: '1000px', height: '720px', background: 'radial-gradient(ellipse at 50% 30%, rgba(55,48,163,0.05) 0%, transparent 68%)', pointerEvents: 'none' }} />

        {/* Top-anchored content */}
        <div style={{ position: 'relative', zIndex: 10, height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: '15vh 24px 0' }}>
          <motion.span
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.1, ease: 'easeOut' }}
            style={{ display: 'inline-flex', alignItems: 'center', padding: '5px 13px', borderRadius: '999px', background: 'rgba(255,255,255,0.35)', border: '1px solid rgba(255,255,255,0.5)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)', fontSize: '11px', fontWeight: 500, color: 'rgba(40,40,40,0.78)', marginBottom: '20px' }}
          >
            Temples, hills and coast
          </motion.span>

          <motion.h1
            initial={{ opacity: 0, y: 22 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.22, ease: 'easeOut' }}
            style={{ margin: 0, fontFamily: "'Inter', sans-serif", fontWeight: 600, fontSize: 'clamp(1.9rem, 4.4vw, 3.1rem)', lineHeight: 1.08, letterSpacing: '-0.025em', color: INK }}
          >
            Discover Tamil Nadu
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.38, ease: 'easeOut' }}
            style={{ margin: '16px 0 0', maxWidth: '460px', fontSize: '14px', lineHeight: 1.6, color: 'rgba(40,40,40,0.7)', fontWeight: 500 }}
          >
            Deep guides to temple towns, hill stations and coasts, with live weather, local festivals and temple, church and mosque timings.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.52, ease: 'easeOut' }}
            style={{ display: 'flex', alignItems: 'center', gap: '13px', marginTop: '28px' }}
          >
            <motion.a
              href="#destinations"
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.97 }}
              style={{ padding: '12px 24px', borderRadius: '9px', fontSize: '14px', fontWeight: 600, fontFamily: "'Inter', sans-serif", color: '#fff', textDecoration: 'none', background: '#1a1a1a', boxShadow: '0 6px 20px rgba(0,0,0,0.22)' }}
            >
              Browse destinations
            </motion.a>
            <motion.a
              href="#features"
              whileHover={{ scale: 1.04, background: 'rgba(255,255,255,0.85)' }}
              whileTap={{ scale: 0.97 }}
              style={{ padding: '12px 24px', borderRadius: '9px', fontSize: '14px', fontWeight: 600, fontFamily: "'Inter', sans-serif", color: INK, textDecoration: 'none', background: 'rgba(255,255,255,0.65)', border: '1px solid rgba(255,255,255,0.7)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' }}
            >
              What you get
            </motion.a>
          </motion.div>
        </div>

        {/* Featured strip */}
        <motion.div
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.7, ease: 'easeOut' }}
          style={{ position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 10, padding: '20px 24px 30px', textAlign: 'center' }}
        >
          <p style={{ margin: '0 0 16px', fontSize: '11px', letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.6)', textShadow: '0 1px 10px rgba(0,0,0,0.5)' }}>
            Featured destinations
          </p>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '44px', flexWrap: 'wrap', maxWidth: '820px', margin: '0 auto' }}>
            {FEATURED.map((name) => (
              <span
                key={name}
                style={{ fontSize: '18px', fontWeight: 700, letterSpacing: '0.02em', color: 'rgba(255,255,255,0.72)', transition: 'color 0.25s ease', cursor: 'default', textShadow: '0 1px 10px rgba(0,0,0,0.5)' }}
                onMouseEnter={(e) => { e.currentTarget.style.color = '#fff' }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.72)' }}
              >
                {name}
              </span>
            ))}
          </div>
        </motion.div>
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
