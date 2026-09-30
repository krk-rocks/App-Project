import { Link, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../auth.jsx'

const INK = '#1f1f1f'
const navLinks = [
  { label: 'Destinations', href: '/#destinations' },
  { label: 'Features', href: '/#features' },
  { label: 'Explore', href: '/#explore' },
]

export default function Nav() {
  const { user, signOut } = useAuth()
  const { pathname } = useLocation()
  const linkStyle = { fontSize: '13px', fontWeight: 500, color: 'rgba(40,40,40,0.72)', textDecoration: 'none', whiteSpace: 'nowrap', transition: 'color 0.2s ease' }
  const dim = (e) => { e.currentTarget.style.color = 'rgba(40,40,40,0.72)' }
  const lift = (e) => { e.currentTarget.style.color = INK }
  return (
    <div style={{ position: 'fixed', top: '18px', left: 0, right: 0, zIndex: 50, display: 'flex', justifyContent: 'center', padding: '0 20px' }}>
      <motion.nav
        initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: 'easeOut' }}
        style={{
          display: 'flex', alignItems: 'center', gap: '36px',
          padding: '11px 22px',
          borderRadius: '999px',
          background: 'rgba(255,255,255,0.55)',
          border: '1px solid rgba(255,255,255,0.65)',
          backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)',
          boxShadow: '0 6px 24px rgba(0,0,0,0.12)',
        }}
      >
        <Link to="/" style={{ fontSize: '17px', fontWeight: 700, color: INK, letterSpacing: '-0.01em', textDecoration: 'none' }}>Monsoon</Link>
        <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              style={{ fontSize: '13px', fontWeight: 500, color: 'rgba(40,40,40,0.72)', textDecoration: 'none', whiteSpace: 'nowrap', transition: 'color 0.2s ease' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = INK }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(40,40,40,0.72)' }}
            >
              {link.label}
            </a>
          ))}
          <span style={{ width: '1px', height: '16px', background: 'rgba(40,40,40,0.18)' }} />
          {user ? (
            <>
              <Link to="/bookings" style={linkStyle} onMouseEnter={lift} onMouseLeave={dim}>My tickets</Link>
              <button
                type="button"
                onClick={signOut}
                style={{ ...linkStyle, background: 'none', border: 0, padding: 0, font: 'inherit', cursor: 'pointer' }}
                onMouseEnter={lift} onMouseLeave={dim}
              >
                Sign out
              </button>
            </>
          ) : (
            <Link to="/login" state={{ next: pathname }} style={{ ...linkStyle, fontWeight: 600, color: INK }}>Sign in</Link>
          )}
        </div>
      </motion.nav>
    </div>
  )
}
