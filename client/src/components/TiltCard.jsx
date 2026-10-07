import { useRef } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { COVERS } from '../data/covers.js'

// Card that tilts in 3D toward the cursor
export default function TiltCard({ d, index }) {
  const ref = useRef()
  const move = (e) => {
    const r = ref.current.getBoundingClientRect()
    const x = (e.clientX - r.left) / r.width - 0.5
    const y = (e.clientY - r.top) / r.height - 0.5
    ref.current.style.transform = `perspective(900px) rotateY(${x * 14}deg) rotateX(${-y * 14}deg) translateZ(8px)`
  }
  const reset = () => (ref.current.style.transform = '')
  const cover = COVERS[d.id]
  return (
    <motion.div initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-60px' }} transition={{ delay: (index % 3) * 0.08, duration: 0.6 }}>
      <Link to={`/destination/${d.id}`} ref={ref} className="card" onMouseMove={move} onMouseLeave={reset}
        style={{ '--h': d.hue }}>
        <div className="card-art">
          {cover
            ? <img src={cover.src} alt={cover.alt} title={`Photo: ${cover.author} · ${cover.license}`} width="720" height="360" loading="lazy" decoding="async" />
            : <><div className="orb" /><div className="orb small" /></>}
        </div>
        <span className="chip">{d.category}</span>
        <h3>{d.name}</h3>
        <p className="muted">{d.region}, {d.country}</p>
        <p>{d.tagline}</p>
        <span className="card-cta">Explore →</span>
      </Link>
    </motion.div>
  )
}
