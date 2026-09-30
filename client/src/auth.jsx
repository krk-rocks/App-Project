import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const KEY = 'monsoon.token'
const AuthContext = createContext(null)

export function api(path, { method = 'GET', body, token } = {}) {
  const t = token ?? localStorage.getItem(KEY)
  return fetch(path, {
    method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(t ? { Authorization: `Bearer ${t}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  }).then(async (r) => {
    const data = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(data.error || 'Something went wrong. Try again.')
    return data
  })
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(KEY))
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!token) { setUser(null); setReady(true); return }
    api('/api/auth/me', { token })
      .then(setUser)
      .catch(() => { localStorage.removeItem(KEY); setToken(null); setUser(null) })
      .finally(() => setReady(true))
  }, [token])

  const accept = useCallback(({ token: t, user: u }) => {
    localStorage.setItem(KEY, t)
    setToken(t)
    setUser(u)
  }, [])

  const signIn = useCallback((email, password) =>
    api('/api/auth/login', { method: 'POST', body: { email, password } }).then(accept), [accept])

  const signUp = useCallback((body) =>
    api('/api/auth/register', { method: 'POST', body }).then(accept), [accept])

  const signOut = useCallback(() => {
    api('/api/auth/logout', { method: 'POST' }).catch(() => {})
    localStorage.removeItem(KEY)
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, ready, signIn, signUp, signOut }), [user, ready, signIn, signUp, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
