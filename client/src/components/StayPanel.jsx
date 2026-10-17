import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'
import { addDays, dateLabel, inr, newKey, shortDate, todayISO } from '../format.js'
import Overlay from './Overlay.jsx'
import PaymentSheet from './PaymentSheet.jsx'

/* Hotels and homestays. The listings are SAMPLES generated so the booking engine has something to book, and the
   page says so. Availability is counted per night on the server, so two stays can share a changeover day. */

function BookSheet({ prop, option, search, onClose, onDone }) {
  const { user } = useAuth()
  const keyRef = useRef(newKey())
  const [name, setName] = useState(user?.name || '')
  const [phone, setPhone] = useState('')
  const [held, setHeld] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function hold(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      setHeld(await api('/api/hotels/book', {
        method: 'POST', headers: { 'Idempotency-Key': keyRef.current },
        body: { hotel_id: prop.id, room_type: option.type, check_in: search.check_in, check_out: search.check_out, rooms: search.rooms, guests: search.guests, guest: { name, phone } },
      }))
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  if (held) {
    return (
      <PaymentSheet order={held.order} balance={held.wallet_balance} bookingId={held.booking.id} onClose={onClose}
        lines={[`${prop.name} · ${option.type}`, `${dateLabel(search.check_in)} → ${dateLabel(search.check_out)} · ${search.nights} night${search.nights > 1 ? 's' : ''}`,
                `${search.rooms} room${search.rooms > 1 ? 's' : ''} · ${search.guests} guest${search.guests > 1 ? 's' : ''}`]}
        onPaid={(r) => onDone(r.booking)} />
    )
  }
  return (
    <Overlay onClose={onClose}>
      <motion.form className="sheet" onClick={(e) => e.stopPropagation()} onSubmit={hold} initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}>
        <header className="sheet-head">
          <div><h3>{prop.name}</h3><p className="muted small">{option.type} · {dateLabel(search.check_in)} → {dateLabel(search.check_out)}</p></div>
          <button type="button" className="x" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <div className="sheet-body">
          <div className="form">
            <label>Lead guest's name<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} placeholder="As on ID" /></label>
            <label>Phone <span className="muted small">(optional)</span><input value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={20} inputMode="tel" /></label>
          </div>
          <ul className="fare">
            {option.nightly.map((n) => <li key={n.date}><span>{shortDate(n.date)} <i className={'dot c-' + n.level.toLowerCase()} title={n.level + ' demand'} /></span><span>{inr(n.price * search.rooms)}</span></li>)}
            <li><span>Taxes (modelled)</span><span>{inr(option.tax)}</span></li>
            <li className="fare-total"><span>Total</span><strong>{inr(option.total)}</strong></li>
          </ul>
          <p className="muted small">Free cancellation until 72 hours before check-in; one night is charged between 72 and 24 hours; non-refundable after that.</p>
          {err && <p className="notice" role="alert">{err}</p>}
        </div>
        <footer className="sheet-foot">
          <div><strong className="total">{inr(option.total)}</strong></div>
          <button className="btn btn-light" disabled={busy || !name.trim()}>{busy ? 'Holding…' : 'Continue to payment'}</button>
        </footer>
        <p className="muted small demo-note">Rooms are held for 10 minutes while you pay. Sample listing: nothing real is reserved.</p>
      </motion.form>
    </Overlay>
  )
}

function Voucher({ b, onClose }) {
  return (
    <Overlay onClose={onClose}>
      <motion.div className="sheet ticket" onClick={(e) => e.stopPropagation()} initial={{ scale: 0.94, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.94, opacity: 0 }}>
        <div className="tick-top"><span className="badge on">CONFIRMED</span><h3>{b.hotel_name}</h3><p className="muted">{b.room_type}</p></div>
        <dl className="tick-grid">
          <div><dt>Confirmation</dt><dd className="mono">{b.confirmation}</dd></div>
          <div><dt>Check-in</dt><dd>{dateLabel(b.check_in)}</dd></div>
          <div><dt>Check-out</dt><dd>{dateLabel(b.check_out)}</dd></div>
          <div><dt>Rooms</dt><dd>{b.rooms} · {b.guests} guest{b.guests > 1 ? 's' : ''}</dd></div>
          <div><dt>Total paid</dt><dd>{inr(b.total)}</dd></div>
        </dl>
        <ul className="tick-pax"><li><span>{b.guest.name}</span><span className="muted small">lead guest</span></li></ul>
        <div className="sheet-foot"><Link to="/bookings" className="pill">My bookings</Link><button className="btn btn-light" onClick={onClose}>Done</button></div>
        <p className="muted small demo-note">Simulated booking. Not a real reservation.</p>
      </motion.div>
    </Overlay>
  )
}

export default function StayPanel({ destId, destName, checkIn, onCheckIn }) {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const [ci, setCi] = useState(checkIn || addDays(todayISO(), 14))
  const [nights, setNights] = useState(2)
  const [guests, setGuests] = useState(2)
  const [rooms, setRooms] = useState(1)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [pick, setPick] = useState(null)
  const [voucher, setVoucher] = useState(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => { if (checkIn && checkIn !== ci) setCi(checkIn) }, [checkIn])          // eslint-disable-line react-hooks/exhaustive-deps
  const co = addDays(ci, nights)

  useEffect(() => {
    setLoading(true)
    const t = setTimeout(() => {
      api(`/api/destinations/${destId}/hotels?check_in=${ci}&check_out=${co}&guests=${guests}&rooms=${rooms}`)
        .then((d) => { setData(d); setErr('') })
        .catch((e) => { setData(null); setErr(e.message) })
        .finally(() => setLoading(false))
    }, 350)
    return () => clearTimeout(t)
  }, [destId, ci, co, guests, rooms, nonce])

  const move = (v) => { setCi(v); onCheckIn?.(v) }

  return (
    <section className="panel wide stay">
      <h2>Where to stay in {destName}</h2>
      <p className="muted-l small">Hotels and homestays, priced night by night: busy nights cost more and quiet ones a little less. These are sample listings for the demo.</p>

      <div className="stay-controls">
        <label className="gt-field"><span>Check-in</span><input type="date" value={ci} min={todayISO()} onChange={(e) => e.target.value && move(e.target.value)} /></label>
        <label className="gt-field"><span>Nights</span><input type="number" min="1" max="14" value={nights} onChange={(e) => setNights(Math.min(14, Math.max(1, Number(e.target.value) || 1)))} /></label>
        <label className="gt-field"><span>Rooms</span><input type="number" min="1" max="4" value={rooms} onChange={(e) => setRooms(Math.min(4, Math.max(1, Number(e.target.value) || 1)))} /></label>
        <label className="gt-field"><span>Guests</span><input type="number" min="1" max="12" value={guests} onChange={(e) => setGuests(Math.min(12, Math.max(1, Number(e.target.value) || 1)))} /></label>
      </div>
      <p className="muted small">Check-out {dateLabel(co)}</p>

      {err && <p className="notice" role="alert">{err}</p>}
      {loading && !data && <p className="muted-l">Searching…</p>}

      {data?.crowd.high_nights > 0 && (
        <div className="notice soft busy-note">
          <strong>{data.crowd.high_nights} of your {data.nights} night{data.nights > 1 ? 's' : ''} {data.crowd.high_nights > 1 ? 'are' : 'is'} expected to be busy</strong>, so prices are higher.
          {data.quieter?.length > 0 && (
            <span> Quieter nearby start dates: {data.quieter.map((q) => <button key={q.date} type="button" className="chipbtn" onClick={() => move(q.date)}>{shortDate(q.date)} ({q.level.toLowerCase()})</button>)}</span>
          )}
        </div>
      )}

      <div className={'stay-list' + (loading ? ' loading' : '')}>
        {data?.properties.map((p) => (
          <article key={p.id} className="prop">
            <header>
              <div><h3>{p.name}</h3><p className="muted small">{p.blurb}</p></div>
              <span className="chip">{p.kind} · {p.tier}</span>
            </header>
            <ul className="tags small">{p.amenities.map((a) => <li key={a}>{a}</li>)}</ul>
            {p.options.map((o) => (
              <div key={o.type} className={'room' + (o.bookable ? '' : ' off')}>
                <div className="room-main">
                  <strong>{o.type}</strong>
                  <span className="muted small"> sleeps {o.max_guests}</span>
                  <span className={'badge ' + (o.free === 0 ? 'off' : o.free <= 2 ? 'rac' : 'on')}>{o.free === 0 ? 'Sold out' : `${o.free} left`}</span>
                  <details>
                    <summary className="muted small">Nightly prices</summary>
                    <ul className="nightly">{o.nightly.map((n) => <li key={n.date}><span>{shortDate(n.date)}</span><i className={'dot c-' + n.level.toLowerCase()} title={n.level + ' demand'} /><span>{inr(n.price)}</span></li>)}</ul>
                  </details>
                </div>
                <div className="room-price">
                  <strong>{inr(o.total)}</strong>
                  <span className="muted small">{data.nights} night{data.nights > 1 ? 's' : ''}{data.rooms > 1 ? ` · ${data.rooms} rooms` : ''}, with taxes</span>
                  {user
                    ? <button className="btn btn-light small-btn" disabled={!o.bookable} onClick={() => setPick({ prop: p, option: o })}>
                        {o.bookable ? 'Book' : !o.fits_guests ? 'Too many guests' : o.free === 0 ? 'Sold out' : `Only ${o.free} left`}
                      </button>
                    : <Link to="/login" state={{ next: pathname }} className="pill">Sign in to book</Link>}
                </div>
              </div>
            ))}
          </article>
        ))}
      </div>
      <p className="muted small demo-note">Sample listings, not real properties. Taxes are modelled. No real money is taken.</p>

      <AnimatePresence>
        {pick && data && <BookSheet prop={pick.prop} option={pick.option} search={data} onClose={() => { setPick(null); setNonce((n) => n + 1) }}
          onDone={(b) => { setPick(null); setVoucher(b); setNonce((n) => n + 1) }} />}
        {voucher && <Voucher b={voucher} onClose={() => setVoucher(null)} />}
      </AnimatePresence>
    </section>
  )
}
