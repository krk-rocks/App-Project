import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../auth.jsx'

export default function Login() {
  const { signIn, signUp } = useAuth()
  const nav = useNavigate()
  const { state } = useLocation()
  const next = state?.next || '/'

  const [mode, setMode] = useState('signin')
  const [form, setForm] = useState({ name: '', email: '', phone: '', password: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      if (mode === 'signin') await signIn(form.email, form.password)
      else await signUp(form)
      nav(next, { replace: true })
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-wrap">
      <motion.div className="auth-card" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: 'easeOut' }}>
        <Link to="/" className="back">← Back to Monsoon</Link>
        <h1>{mode === 'signin' ? 'Welcome back' : 'Create your account'}</h1>
        <p className="muted-l">
          {mode === 'signin'
            ? 'Sign in to book trains and buses, and to see your tickets.'
            : 'An account keeps your bookings and passenger details in one place.'}
        </p>

        <div className="seg">
          <button className={mode === 'signin' ? 'on' : ''} onClick={() => { setMode('signin'); setErr('') }} type="button">Sign in</button>
          <button className={mode === 'signup' ? 'on' : ''} onClick={() => { setMode('signup'); setErr('') }} type="button">Create account</button>
        </div>

        <form onSubmit={submit} className="form">
          {mode === 'signup' && (
            <label>Full name
              <input value={form.name} onChange={set('name')} autoComplete="name" required placeholder="Your name" />
            </label>
          )}
          <label>Email
            <input type="email" value={form.email} onChange={set('email')} autoComplete="email" required placeholder="you@example.com" />
          </label>
          {mode === 'signup' && (
            <label>Phone <span className="muted small">(optional)</span>
              <input value={form.phone} onChange={set('phone')} autoComplete="tel" placeholder="For ticket updates" />
            </label>
          )}
          <label>Password
            <input type="password" value={form.password} onChange={set('password')}
                   autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} required
                   placeholder={mode === 'signup' ? 'At least 8 characters' : ''} minLength={mode === 'signup' ? 8 : undefined} />
          </label>

          {err && <p className="notice">{err}</p>}
          <button className="btn btn-light block" disabled={busy}>
            {busy ? 'Just a moment…' : mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="muted small demo-note">
          Demo app. Accounts are stored locally on your own machine and no real payment is ever taken.
        </p>
      </motion.div>
    </main>
  )
}
