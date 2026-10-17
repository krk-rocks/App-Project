import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { api } from '../auth.jsx'
import { inrPaise, mmss } from '../format.js'
import Overlay from './Overlay.jsx'

const TEST_CARD = { number: '4242 4242 4242 4242', expiry: '12/30', cvv: '123' }
const blankCard = { number: '', expiry: '', cvv: '' }

const groupCard = (v) => v.replace(/\D/g, '').slice(0, 19).replace(/(.{4})/g, '$1 ').trim()
const fixExpiry = (v) => {
  const d = v.replace(/\D/g, '').slice(0, 4)
  return d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d
}

/* Pays an order. Used for bookings (wallet, card or UPI) and for adding money (card or UPI only).

   DEMO PAYMENTS: nothing here moves real money. The server accepts only published test cards and UPI ids and
   refuses anything else, and a card number only ever lives in this component's state: it is cleared the moment
   it is sent and the server never stores it. */
export default function PaymentSheet({ order, lines = [], balance = 0, allowWallet = true, bookingId, onPaid, onClose, title = 'Complete your payment' }) {
  const canWallet = allowWallet && balance >= order.amount
  const [method, setMethod] = useState(canWallet ? 'wallet' : 'card')
  const [card, setCard] = useState(blankCard)
  const [vpa, setVpa] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [left, setLeft] = useState(order.seconds_left)          // null = no time limit
  const [released, setReleased] = useState(false)
  const timer = useRef()

  useEffect(() => {
    if (left == null) return undefined
    timer.current = setInterval(() => setLeft((s) => (s > 0 ? s - 1 : 0)), 1000)
    return () => clearInterval(timer.current)
  }, [left == null])                                          // eslint-disable-line react-hooks/exhaustive-deps

  const expired = left === 0
  const lowBalance = allowWallet && balance < order.amount

  async function pay(e) {
    e.preventDefault()
    setErr('')
    setBusy(true)
    const body = method === 'wallet' ? { method } : method === 'card' ? { method, card } : { method, upi: { vpa } }
    try {
      const r = await api(`/api/orders/${order.id}/pay`, { method: 'POST', body })
      setCard(blankCard)                                       // never keep card details around
      if (r.result.status === 'captured') onPaid(r)
      else setErr(r.result.message || 'The payment was declined. Try another method.')
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  async function release() {
    try {
      if (bookingId) await api(`/api/bookings/${bookingId}/cancel`, { method: 'POST' })
      setReleased(true)
    } catch (e) {
      setErr(e.message)
    }
  }

  const dead = expired || released
  return (
    <Overlay onClose={onClose}>
      <motion.form className="sheet pay" onClick={(e) => e.stopPropagation()} onSubmit={pay}
        initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }} transition={{ duration: 0.28, ease: 'easeOut' }}>
        <header className="sheet-head">
          <div>
            <h3>{title}</h3>
            {lines.map((l, i) => <p key={i} className="muted small">{l}</p>)}
          </div>
          <button type="button" className="x" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="pay-amount">
          <strong>{inrPaise(order.amount)}</strong>
          {left != null && !dead && <span className={'hold' + (left < 60 ? ' hot' : '')} role="timer" aria-label="Time left to pay">Held for {mmss(left)}</span>}
        </div>

        {dead ? (
          <div className="sheet-body">
            <p className="notice">{released ? 'Your hold was released. Nothing was charged.' : 'The hold ran out and your booking was released. Nothing was charged. Please start again.'}</p>
            <button type="button" className="btn btn-light" onClick={onClose}>Close</button>
          </div>
        ) : (
          <>
            <div className="seg pay-methods" role="tablist" aria-label="Payment method">
              {allowWallet && <button type="button" role="tab" aria-selected={method === 'wallet'} className={method === 'wallet' ? 'on' : ''} onClick={() => setMethod('wallet')}>Wallet {inrPaise(balance)}</button>}
              <button type="button" role="tab" aria-selected={method === 'card'} className={method === 'card' ? 'on' : ''} onClick={() => setMethod('card')}>Test card</button>
              <button type="button" role="tab" aria-selected={method === 'upi'} className={method === 'upi' ? 'on' : ''} onClick={() => setMethod('upi')}>Test UPI</button>
            </div>

            <div className="sheet-body">
              {method === 'wallet' && (
                canWallet
                  ? <p className="muted-l small">Pay {inrPaise(order.amount)} from your wallet. You'll have {inrPaise(balance - order.amount)} left.</p>
                  : <p className="notice soft">Your wallet has {inrPaise(balance)}, which isn't enough. <Link to="/wallet" onClick={onClose}>Add money</Link> or pay by card or UPI.</p>
              )}

              {method === 'card' && (
                <div className="form pay-form">
                  <label>Card number
                    <input inputMode="numeric" autoComplete="off" placeholder="4242 4242 4242 4242" value={card.number} onChange={(e) => setCard((c) => ({ ...c, number: groupCard(e.target.value) }))} required />
                  </label>
                  <div className="pay-row">
                    <label>Expiry
                      <input inputMode="numeric" autoComplete="off" placeholder="MM/YY" value={card.expiry} onChange={(e) => setCard((c) => ({ ...c, expiry: fixExpiry(e.target.value) }))} required />
                    </label>
                    <label>CVV
                      <input inputMode="numeric" autoComplete="off" placeholder="123" maxLength={4} value={card.cvv} onChange={(e) => setCard((c) => ({ ...c, cvv: e.target.value.replace(/\D/g, '') }))} required />
                    </label>
                  </div>
                  <button type="button" className="pill" onClick={() => setCard(TEST_CARD)}>Fill the test card</button>
                </div>
              )}

              {method === 'upi' && (
                <div className="form pay-form">
                  <label>UPI id
                    <input autoComplete="off" placeholder="success@epic" value={vpa} onChange={(e) => setVpa(e.target.value)} required />
                  </label>
                  <button type="button" className="pill" onClick={() => setVpa('success@epic')}>Use success@epic</button>
                </div>
              )}

              {err && <p className="notice" role="alert">{err}</p>}
              <p className="muted small demo-note pay-demo">Demo payments: no real money moves. Only test cards and UPI ids work, so please don't enter a real card.</p>
            </div>

            <footer className="sheet-foot">
              {bookingId ? <button type="button" className="pill" onClick={release}>Release hold</button> : <span />}
              <button className="btn btn-light" disabled={busy || (method === 'wallet' && lowBalance)}>{busy ? 'Paying…' : `Pay ${inrPaise(order.amount)}`}</button>
            </footer>
          </>
        )}
      </motion.form>
    </Overlay>
  )
}
