// Small formatting and parsing helpers shared across the pages. Money on the server is integer paise; these
// convert at the edge so the rest of the UI never does floating-point money arithmetic.

export const inr = (rupees) => '₹' + Number(rupees || 0).toLocaleString('en-IN')

export const inrPaise = (paise) => {
  const r = (paise || 0) / 100
  return '₹' + r.toLocaleString('en-IN', { minimumFractionDigits: Number.isInteger(r) ? 0 : 2, maximumFractionDigits: 2 })
}

/** "450.50" -> 45050 paise. Returns null for anything that is not a positive amount with at most 2 decimals. */
export const toPaise = (text) => {
  const s = String(text ?? '').trim().replace(/,/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null
  const [whole, frac = ''] = s.split('.')
  const p = Number(whole) * 100 + Number((frac + '00').slice(0, 2))
  return p > 0 ? p : null
}

export const to12 = (t) => {
  if (!t) return ''
  const [h, m] = t.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`
}

export const dateLabel = (iso) => (iso ? new Date(iso + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '')
export const shortDate = (iso) => new Date(iso + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
export const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
export const newKey = () => (globalThis.crypto?.randomUUID ? crypto.randomUUID() : `k${Date.now()}${Math.random().toString(16).slice(2)}`)

export const addDays = (iso, n) => {
  const d = new Date(iso + 'T00:00')
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
export const todayISO = () => addDays(new Date().toISOString().slice(0, 10), 0)
