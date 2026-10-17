import { useCallback, useEffect, useRef, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'
import { inr, inrPaise, newKey } from '../format.js'
import PaymentSheet from '../components/PaymentSheet.jsx'

const PRESETS = [500, 1000, 2000, 5000]
const KIND = { topup: 'Added money', payment: 'Payment', refund: 'Refund' }

export default function Wallet() {
  const { user, ready } = useAuth()
  const [wallet, setWallet] = useState(null)
  const [amount, setAmount] = useState('1000')
  const [order, setOrder] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const keyRef = useRef(newKey())

  const load = useCallback(() => api('/api/wallet').then(setWallet).catch((e) => setErr(e.message)), [])
  useEffect(() => { if (user) load() }, [user, load])

  async function start(e) {
    e.preventDefault()
    setErr(''); setMsg('')
    const rupees = Number(amount)
    if (!Number.isInteger(rupees)) return setErr('Enter a whole number of rupees.')
    try {
      const r = await api('/api/wallet/topup', { method: 'POST', body: { amount: rupees }, headers: { 'Idempotency-Key': keyRef.current } })
      setOrder(r.order)
    } catch (e2) {
      setErr(e2.message)
    }
  }

  if (!ready) return <main className="section dark page"><p className="muted-l">Loading…</p></main>
  if (!user) return <Navigate to="/login" replace state={{ next: '/wallet' }} />

  return (
    <main className="section dark page">
      <h1 className="big">Wallet</h1>
      <div className="wallet-grid">
        <section className="panel wallet-balance">
          <span className="muted small">Balance</span>
          <strong className="wallet-amt">{wallet ? inrPaise(wallet.balance) : '…'}</strong>
          <p className="muted-l small">Refunds from cancelled bookings land here instantly, and you can pay for new bookings from it.</p>
        </section>

        <form className="panel" onSubmit={start}>
          <h2>Add money</h2>
          <div className="pills presets">
            {PRESETS.map((p) => <button type="button" key={p} className={'pill' + (Number(amount) === p ? ' active' : '')} onClick={() => setAmount(String(p))}>{inr(p)}</button>)}
          </div>
          <label className="form-label">Amount (₹{wallet ? `${wallet.limits.min} to ${wallet.limits.max.toLocaleString('en-IN')}` : ''})
            <input className="search" inputMode="numeric" value={amount} onChange={(e) => { setAmount(e.target.value.replace(/\D/g, '')); keyRef.current = newKey() }} />
          </label>
          {err && <p className="notice" role="alert">{err}</p>}
          {msg && <p className="notice soft" role="status">{msg}</p>}
          <button className="btn btn-light">Add {amount ? inr(Number(amount)) : 'money'}</button>
          <p className="muted small demo-note">Demo wallet: test cards and UPI only, no real money.</p>
        </form>
      </div>

      <section className="panel ledger">
        <h2>Activity</h2>
        {wallet && wallet.ledger.length === 0 && <p className="muted-l">Nothing yet.</p>}
        <ul>
          {wallet?.ledger.map((e, i) => (
            <motion.li key={e.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i, 10) * 0.03 }}>
              <div><strong>{KIND[e.kind] || e.kind}</strong><span className="muted small"> · {e.note}</span><div className="muted small">{new Date(e.at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</div></div>
              <div className={'amt ' + (e.amount > 0 ? 'in' : 'out')}>{e.amount > 0 ? '+' : '−'}{inrPaise(Math.abs(e.amount))}<div className="muted small">{inrPaise(e.balance_after)}</div></div>
            </motion.li>
          ))}
        </ul>
      </section>

      <AnimatePresence>
        {order && (
          <PaymentSheet order={order} allowWallet={false} title="Add money" balance={wallet?.balance || 0} lines={['Added to your Epic TN wallet']}
            onClose={() => { setOrder(null); load() }}
            onPaid={() => { setOrder(null); keyRef.current = newKey(); setMsg('Money added.'); load() }} />
        )}
      </AnimatePresence>
    </main>
  )
}
