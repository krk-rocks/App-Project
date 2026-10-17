import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../auth.jsx'

const SECTIONS = [
  { label: 'Destinations', href: '/#destinations' },
  { label: 'Features', href: '/#features' },
  { label: 'Explore', href: '/#explore' },
]
const MAIN = [
  { to: '/tickets', label: 'Tickets' },
  { to: '/planner', label: 'Plan a trip' },
  { to: '/trips', label: 'Trips' },
]

export default function Nav() {
  const { user, signOut } = useAuth()
  const { pathname, search } = useLocation()
  const [open, setOpen] = useState(false)
  const box = useRef(null)

  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => {
    if (!open) return undefined
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])

  const account = user ? (
    <>
      <NavLink to="/wallet">Wallet</NavLink>
      <NavLink to="/bookings">My bookings</NavLink>
      <button type="button" className="nl" onClick={signOut}>Sign out</button>
    </>
  ) : (
    <Link to="/login" state={{ next: pathname + search }} className="signin">Sign in</Link>
  )

  return (
    <div className="epic-nav">
      <motion.nav ref={box} className="bar" aria-label="Main" initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: 'easeOut' }}>
        <Link to="/" className="brand">Epic TN</Link>

        <div className="group nav-sections">
          {SECTIONS.map((l) => <a key={l.label} href={l.href}>{l.label}</a>)}
        </div>
        <span className="sep nav-sections" />
        <div className="group nav-inline">
          {MAIN.map((l) => <NavLink key={l.to} to={l.to}>{l.label}</NavLink>)}
        </div>
        <span className="sep nav-inline" />
        <div className="group nav-inline">{account}</div>

        <button type="button" className="menu-btn" aria-expanded={open} aria-controls="nav-panel" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen((o) => !o)}>
          <span aria-hidden="true">{open ? '✕' : '☰'}</span>
        </button>

        {open && (
          <div id="nav-panel" className="menu-panel">
            {MAIN.map((l) => <NavLink key={l.to} to={l.to}>{l.label}</NavLink>)}
            <hr />
            {account}
            <hr />
            {SECTIONS.map((l) => <a key={l.label} href={l.href}>{l.label}</a>)}
          </div>
        )}
      </motion.nav>
    </div>
  )
}
