import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'
import { dateLabel, inr, inrPaise, mmss, shortDate, to12 } from '../format.js'
import Overlay from '../components/Overlay.jsx'
import PaymentSheet from '../components/PaymentSheet.jsx'

const LABEL = { PENDING_PAYMENT: 'Awaiting payment', CONFIRMED: 'Confirmed', RAC: 'RAC', CANCELLED: 'Cancelled', EXPIRED: 'Expired' }
const TONE = { PENDING_PAYMENT: 'rac', CONFIRMED: 'on', RAC: 'rac', CANCELLED: 'off', EXPIRED: 'off' }
const KIND = { train: 'Train', bus: 'Bus', hotel: 'Hotel' }

const titleOf = (b) => (b.kind === 'train' ? `${b.train_no} ${b.train_name}` : b.kind === 'bus' ? `${b.operator} · ${b.type}` : `${b.hotel_name} · ${b.room_type}`)

function Hold({ seconds, onEnd }) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    if (left <= 0) { onEnd?.(); return undefined }
    const t = setTimeout(() => setLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [left, onEnd])
  return <span className={'hold' + (left < 60 ? ' hot' : '')}>Held for {mmss(Math.max(0, left))}</span>
}

function CancelSheet({ booking, onClose, onDone }) {
  const [quote, setQuote] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api(`/api/bookings/${booking.id}/cancel-quote`).then(setQuote).catch((e) => setErr(e.message))
  }, [booking.id])

  async function confirm() {
    setBusy(true)
    try {
      onDone(await api(`/api/bookings/${booking.id}/cancel`, { method: 'POST' }))
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }

  return (
    <Overlay onClose={onClose}>
      <motion.div className="sheet" onClick={(e) => e.stopPropagation()} initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}>
        <header className="sheet-head">
          <div><h3>Cancel this booking?</h3><p className="muted small">{titleOf(booking)}</p></div>
          <button type="button" className="x" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <div className="sheet-body">
          {!quote && !err && <p className="muted-l">Working out your refund…</p>}
          {err && <p className="notice" role="alert">{err}</p>}
          {quote && (
            <>
              <ul className="fare">
                <li><span>You paid</span><span>{inrPaise(quote.total)}</span></li>
                <li><span>Cancellation charge</span><span>−{inrPaise(quote.charge)}</span></li>
                <li className="fare-total"><span>Refund to your wallet</span><strong>{inrPaise(quote.refund)}</strong></li>
              </ul>
              {quote.tier && <p className="muted small">Charge tier: <strong>{quote.tier}</strong></p>}
              {quote.tiers?.length > 0 && (
                <>
                  <h4>How the charge works</h4>
                  <ul className="tiers">
                    {quote.tiers.map((t) => <li key={t.when} className={t.when === quote.tier ? 'now' : ''}><span>{t.when}</span><span className="muted small">{t.rule}</span></li>)}
                  </ul>
                </>
              )}
              <p className="muted small">{quote.note}</p>
            </>
          )}
        </div>
        <footer className="sheet-foot">
          <button type="button" className="pill" onClick={onClose}>Keep booking</button>
          <button type="button" className="btn btn-light" disabled={!quote || busy || quote.cancellable === false} onClick={confirm}>{busy ? 'Cancelling…' : 'Cancel booking'}</button>
        </footer>
      </motion.div>
    </Overlay>
  )
}

export default function Bookings() {
  const { user, ready } = useAuth()
  const [rows, setRows] = useState(null)
  const [balance, setBalance] = useState(0)
  const [err, setErr] = useState('')
  const [paying, setPaying] = useState(null)       // {booking, order}
  const [cancelling, setCancelling] = useState(null)
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    api('/api/bookings').then(setRows).catch((e) => setErr(e.message))
    api('/api/wallet').then((w) => setBalance(w.balance)).catch(() => {})
  }, [])
  useEffect(() => { if (user) load() }, [user, load])

  async function payNow(b) {
    setErr('')
    try {
      const [order, w] = await Promise.all([api(`/api/orders/${b.order_id}`), api('/api/wallet')])
      setBalance(w.balance)
      setPaying({ booking: b, order })
    } catch (e) {
      setErr(e.message)
    }
  }

  async function release(b) {
    try {
      await api(`/api/bookings/${b.id}/cancel`, { method: 'POST' })
      load()
    } catch (e) {
      setErr(e.message)
    }
  }

  if (!ready) return <main className="section dark page"><p className="muted-l">Loading…</p></main>
  if (!user) return <Navigate to="/login" replace state={{ next: '/bookings' }} />

  return (
    <main className="section dark page">
      <div className="page-head">
        <div>
          <h1 className="big">My bookings</h1>
          <p className="muted-l">Signed in as {user.email}</p>
        </div>
        <Link to="/wallet" className="wallet-chip"><span className="muted small">Wallet</span><strong>{inrPaise(balance)}</strong></Link>
      </div>
      {msg && <p className="notice soft" role="status">{msg}</p>}
      {err && <p className="notice" role="alert">{err}</p>}
      {rows && rows.length === 0 && (
        <p className="muted-l">Nothing booked yet. <Link to="/tickets" className="card-cta">Book a train or bus →</Link></p>
      )}
      <div className="ticket-list">
        {(rows || []).map((b, i) => (
          <motion.article key={b.id} className={'panel tick' + (b.status === 'CANCELLED' || b.status === 'EXPIRED' ? ' void' : '')}
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 8) * 0.04 }}>
            <header>
              <span className={'badge ' + TONE[b.status]}>{LABEL[b.status]}</span>
              <span className="chip">{KIND[b.kind]}</span>
              {b.status === 'PENDING_PAYMENT' && b.hold_seconds_left > 0 && <Hold seconds={b.hold_seconds_left} onEnd={load} />}
            </header>
            <h3>{titleOf(b)}</h3>
            <p className="muted-l">
              {b.kind === 'hotel' ? `${dateLabel(b.check_in)} → ${dateLabel(b.check_out)} · ${b.nights} night${b.nights > 1 ? 's' : ''}` : `${b.from_name} → ${b.to_name}`}
            </p>
            <dl className="tick-grid">
              {b.kind === 'hotel' ? (
                <>
                  <div><dt>Confirmation</dt><dd className="mono">{b.confirmation || '—'}</dd></div>
                  <div><dt>Rooms</dt><dd>{b.rooms} · {b.guests} guest{b.guests > 1 ? 's' : ''}</dd></div>
                </>
              ) : (
                <>
                  <div><dt>{b.kind === 'train' ? 'PNR' : 'Ticket'}</dt><dd className="mono">{b.pnr || b.ticket || '—'}</dd></div>
                  <div><dt>Date</dt><dd>{dateLabel(b.date)}</dd></div>
                  <div><dt>Departs</dt><dd>{to12(b.depart)}</dd></div>
                  {b.kind === 'train'
                    ? <div><dt>Class</dt><dd>{b.cls_label}{b.quota === 'tatkal' ? ' · Tatkal' : ''}</dd></div>
                    : <div><dt>Seats</dt><dd>{b.seats.join(', ')}</dd></div>}
                </>
              )}
              <div><dt>Total</dt><dd>{inr(b.total)}</dd></div>
            </dl>
            <ul className="tick-pax">
              {b.kind === 'hotel'
                ? <li><span>{b.guest.name}</span><span className="muted small">lead guest</span></li>
                : b.passengers.map((p, j) => <li key={j}><span>{p.name}</span><span className="muted small">{p.age} · {p.gender}</span></li>)}
            </ul>
            {b.refund && (
              <p className="muted small refund-line">
                Refunded {inrPaise(b.refund.amount)} to your wallet{b.refund.charge > 0 ? ` after a ${inrPaise(b.refund.charge)} charge` : ''} ({shortDate(b.refund.at.slice(0, 10))}).
              </p>
            )}
            <div className="tick-actions">
              {b.status === 'PENDING_PAYMENT' && b.hold_seconds_left > 0 && (
                <>
                  <button className="btn btn-light small-btn" onClick={() => payNow(b)}>Pay {inr(b.total)}</button>
                  <button className="pill" onClick={() => release(b)}>Release hold</button>
                </>
              )}
              {(b.status === 'CONFIRMED' || b.status === 'RAC') && <button className="pill" onClick={() => setCancelling(b)}>Cancel booking…</button>}
              {b.kind === 'hotel' && b.place && <Link className="pill" to={`/destination/${b.place}`}>View {b.place}</Link>}
            </div>
          </motion.article>
        ))}
      </div>
      <p className="muted small demo-note">Simulated bookings. Not valid for travel, not connected to IRCTC, any operator or hotel, and no real money is taken.</p>

      <AnimatePresence>
        {paying && (
          <PaymentSheet
            order={paying.order} balance={balance} bookingId={paying.booking.id}
            lines={[titleOf(paying.booking), paying.booking.kind === 'hotel' ? `${dateLabel(paying.booking.check_in)} → ${dateLabel(paying.booking.check_out)}` : `${paying.booking.from_name} → ${paying.booking.to_name}`]}
            onClose={() => { setPaying(null); load() }}
            onPaid={() => { setPaying(null); setMsg('Payment received. Your booking is confirmed.'); load() }}
          />
        )}
        {cancelling && (
          <CancelSheet booking={cancelling} onClose={() => setCancelling(null)}
            onDone={(r) => { setCancelling(null); setBalance(r.wallet_balance); setMsg('Booking cancelled. Your refund is in your wallet.'); load() }} />
        )}
      </AnimatePresence>
    </main>
  )
}
