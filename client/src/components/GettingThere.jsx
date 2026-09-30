import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'

const tomorrow = () => new Date(Date.now() + 864e5).toISOString().slice(0, 10)
const rupees = (n) => '₹' + Number(n || 0).toLocaleString('en-IN')
const to12 = (t) => {
  if (!t) return ''
  const [h, m] = t.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`
}

const AV_TONE = { AVL: 'on', RAC: 'rac', WL: 'off', REGRET: 'off', NA: 'na' }

/* The panel sits inside a stacking context, so overlays go to <body> to stay on top. */
const Overlay = ({ children, onClose }) => createPortal(
  <motion.div className="sheet-back" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
    {children}
  </motion.div>,
  document.body,
)

/* ---------------------------------------------------------------- seat map */

function SeatMap({ bus, picked, onPick, max }) {
  const taken = new Set(bus.taken)
  const rows = []
  const perRow = bus.sleeper ? 3 : 4
  for (let i = 1; i <= bus.seats_total; i += perRow) {
    rows.push(Array.from({ length: perRow }, (_, k) => i + k).filter((n) => n <= bus.seats_total))
  }
  return (
    <div className="seatmap">
      <div className="seat-legend">
        <span><i className="sw free" /> Free</span>
        <span><i className="sw sel" /> Yours</span>
        <span><i className="sw gone" /> Taken</span>
      </div>
      <div className="seat-rows">
        {rows.map((row, ri) => (
          <div className="seat-row" key={ri}>
            {row.map((n, ci) => {
              const gone = taken.has(n)
              const sel = picked.includes(n)
              return (
                <button
                  type="button"
                  key={n}
                  className={'seat' + (gone ? ' gone' : sel ? ' sel' : '') + (ci === (bus.sleeper ? 1 : 1) ? ' aisle' : '')}
                  disabled={gone || (!sel && picked.length >= max)}
                  onClick={() => onPick(n)}
                  aria-label={`Seat ${n}${gone ? ', taken' : ''}`}
                >{n}</button>
              )
            })}
          </div>
        ))}
      </div>
      <p className="muted small">{bus.sleeper ? 'Sleeper berths, 2 + 1 layout' : 'Seater, 2 + 2 layout'}</p>
    </div>
  )
}

/* ---------------------------------------------------------------- booking sheet */

const blankPax = () => ({ name: '', age: '', gender: 'M' })

function BookingSheet({ offer, date, onClose, onDone }) {
  const [pax, setPax] = useState([blankPax()])
  const [seats, setSeats] = useState([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const isBus = offer.kind === 'bus'
  const max = offer.quota === 'tatkal' ? 4 : 6

  const each = isBus ? offer.bus.fare : offer.cls.fare.total
  const total = each * pax.length

  const setP = (i, k, v) => setPax((p) => p.map((x, j) => (j === i ? { ...x, [k]: v } : x)))
  const addP = () => setPax((p) => (p.length < max ? [...p, blankPax()] : p))
  const delP = (i) => setPax((p) => (p.length > 1 ? p.filter((_, j) => j !== i) : p))

  const pickSeat = (n) =>
    setSeats((s) => (s.includes(n) ? s.filter((x) => x !== n) : s.length < pax.length ? [...s, n] : s))

  async function confirm(e) {
    e.preventDefault()
    setErr('')
    if (isBus && seats.length !== pax.length) return setErr(`Pick ${pax.length} seat${pax.length > 1 ? 's' : ''} — one per passenger.`)
    setBusy(true)
    const passengers = pax.map((p) => ({ name: p.name.trim(), age: Number(p.age), gender: p.gender }))
    const body = isBus
      ? { kind: 'bus', date, seats, key: offer.bus.key, operator: offer.bus.operator, type: offer.bus.type,
          from: offer.bus.from, to: offer.bus.to, depart: offer.bus.depart, arrive: offer.bus.arrive,
          fare: offer.bus.fare, passengers }
      : { kind: 'train', date, quota: offer.quota, cls: offer.cls.cls, train_no: offer.train.no,
          train_name: offer.train.name, from: offer.train.from, to: offer.train.to,
          depart: offer.train.depart, arrive: offer.train.arrive, passengers }
    try {
      onDone(await api('/api/bookings', { method: 'POST', body }))
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Overlay onClose={onClose}>
      <motion.form
        className="sheet" onClick={(e) => e.stopPropagation()} onSubmit={confirm}
        initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}
        transition={{ duration: 0.28, ease: 'easeOut' }}
      >
        <header className="sheet-head">
          <div>
            <h3>{isBus ? `${offer.bus.operator} · ${offer.bus.type}` : `${offer.train.no} ${offer.train.name}`}</h3>
            <p className="muted small">
              {isBus ? offer.bus.from_name : offer.train.from_name} → {isBus ? offer.bus.to_name : offer.train.to_name}
              {' · '}{to12(isBus ? offer.bus.depart : offer.train.depart)}
              {' · '}{date}
              {!isBus && <> · {offer.cls.label}{offer.quota === 'tatkal' && <span className="chip tatkal">TATKAL</span>}</>}
            </p>
          </div>
          <button type="button" className="x" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="sheet-body">
          <h4>Passengers <span className="muted small">up to {max}</span></h4>
          {pax.map((p, i) => (
            <div className="pax" key={i}>
              <input placeholder="Full name (as on ID)" value={p.name} onChange={(e) => setP(i, 'name', e.target.value)} required />
              <input type="number" placeholder="Age" min="1" max="120" value={p.age} onChange={(e) => setP(i, 'age', e.target.value)} required />
              <select value={p.gender} onChange={(e) => setP(i, 'gender', e.target.value)}>
                <option value="M">Male</option><option value="F">Female</option><option value="O">Other</option>
              </select>
              {pax.length > 1 && <button type="button" className="x" onClick={() => delP(i)} aria-label="Remove passenger">✕</button>}
            </div>
          ))}
          {pax.length < max && <button type="button" className="pill" onClick={addP}>+ Add passenger</button>}

          {isBus && (
            <>
              <h4>Choose {pax.length} seat{pax.length > 1 ? 's' : ''}</h4>
              <SeatMap bus={offer.bus} picked={seats} onPick={pickSeat} max={pax.length} />
            </>
          )}

          {!isBus && (
            <>
              <h4>Fare breakdown <span className="muted small">per passenger</span></h4>
              <ul className="fare">
                <li><span>Base fare</span><span>{rupees(offer.cls.fare.base)}</span></li>
                {offer.cls.fare.tatkal > 0 && <li><span>Tatkal charge</span><span>{rupees(offer.cls.fare.tatkal)}</span></li>}
                <li><span>Reservation fee</span><span>{rupees(offer.cls.fare.reservation)}</span></li>
                {offer.cls.fare.gst > 0 && <li><span>GST</span><span>{rupees(offer.cls.fare.gst)}</span></li>}
              </ul>
            </>
          )}

          {err && <p className="notice">{err}</p>}
        </div>

        <footer className="sheet-foot">
          <div>
            <strong className="total">{rupees(total)}</strong>
            <span className="muted small"> for {pax.length} passenger{pax.length > 1 ? 's' : ''}</span>
          </div>
          <button className="btn btn-light" disabled={busy}>{busy ? 'Booking…' : 'Confirm booking'}</button>
        </footer>
        <p className="muted small demo-note">Simulated booking — no payment is taken and no real seat is reserved.</p>
      </motion.form>
    </Overlay>
  )
}

/* ---------------------------------------------------------------- ticket */

function Ticket({ b, onClose }) {
  return (
    <Overlay onClose={onClose}>
      <motion.div className="sheet ticket" onClick={(e) => e.stopPropagation()}
        initial={{ scale: 0.94, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.94, opacity: 0 }}>
        <div className="tick-top">
          <span className={'badge ' + (b.status === 'CONFIRMED' ? 'on' : 'rac')}>{b.status}</span>
          <h3>{b.kind === 'train' ? `${b.train_no} ${b.train_name}` : `${b.operator} · ${b.type}`}</h3>
          <p className="muted">{b.from_name} → {b.to_name}</p>
        </div>
        <dl className="tick-grid">
          <div><dt>{b.kind === 'train' ? 'PNR' : 'Ticket'}</dt><dd className="mono">{b.pnr || b.ticket}</dd></div>
          <div><dt>Date</dt><dd>{b.date}</dd></div>
          <div><dt>Departs</dt><dd>{to12(b.depart)}</dd></div>
          {b.kind === 'train'
            ? <><div><dt>Class</dt><dd>{b.cls_label}</dd></div><div><dt>Quota</dt><dd>{b.quota === 'tatkal' ? 'Tatkal' : 'General'}</dd></div></>
            : <div><dt>Seats</dt><dd>{b.seats.join(', ')}</dd></div>}
          <div><dt>Total paid</dt><dd>{rupees(b.total)}</dd></div>
        </dl>
        <ul className="tick-pax">
          {b.passengers.map((p, i) => <li key={i}><span>{p.name}</span><span className="muted small">{p.age} · {p.gender}</span></li>)}
        </ul>
        <div className="sheet-foot">
          <Link to="/bookings" className="pill">All my tickets</Link>
          <button className="btn btn-light" onClick={onClose}>Done</button>
        </div>
        <p className="muted small demo-note">Simulated ticket. Not valid for travel.</p>
      </motion.div>
    </Overlay>
  )
}

/* ---------------------------------------------------------------- main panel */

export default function GettingThere({ destId, destName }) {
  const { user } = useAuth()
  const { pathname } = useLocation()

  const [hubs, setHubs] = useState([])
  const [from, setFrom] = useState('')
  const [geo, setGeo] = useState({ state: 'idle', msg: '' })
  const [date, setDate] = useState(tomorrow())
  const [quota, setQuota] = useState('general')
  const [tab, setTab] = useState('train')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [offer, setOffer] = useState(null)
  const [ticket, setTicket] = useState(null)
  const [nonce, setNonce] = useState(0)  // bumped after a booking so seat counts re-fetch

  /* Boarding points: ask the browser where the traveller is, and fall back to a full list. */
  const locate = useCallback(() => {
    if (!navigator.geolocation) return setGeo({ state: 'off', msg: 'This browser cannot share a location.' })
    setGeo({ state: 'locating', msg: '' })
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        api(`/api/transport/hubs?lat=${coords.latitude}&lon=${coords.longitude}`)
          .then((d) => {
            setHubs(d.hubs)
            setFrom((f) => f || d.nearest.code)
            setGeo({ state: 'ok', msg: `${d.nearest.city} · ${d.nearest.km} km from you` })
          })
          .catch(() => setGeo({ state: 'off', msg: 'Could not load boarding points.' }))
      },
      (e) => {
        setGeo({ state: 'denied', msg: e.code === 1 ? 'Location permission denied — pick a boarding point instead.' : 'Could not read your location.' })
        api('/api/transport/hubs').then((d) => setHubs(d.hubs)).catch(() => {})
      },
      { timeout: 10000, maximumAge: 300000 },
    )
  }, [])

  useEffect(() => {
    api('/api/transport/hubs').then((d) => { setHubs(d.hubs); setFrom((f) => f || 'MAS') }).catch(() => {})
    if (navigator.permissions?.query) {
      navigator.permissions.query({ name: 'geolocation' })
        .then((p) => { if (p.state === 'granted') locate() })
        .catch(() => {})
    }
  }, [locate])

  useEffect(() => {
    if (!from) return
    setLoading(true)
    api(`/api/destinations/${destId}/transport?from=${from}&date=${date}&quota=${quota}`)
      .then((d) => {
        setData(d)
        if (d.no_rail_link || d.trains_sold_out) setTab('bus')
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [destId, from, date, quota, nonce])

  const fallback = data && (data.no_rail_link || data.trains_sold_out)
  const tw = data?.tatkal
  const signInFirst = !user

  const hubOptions = useMemo(
    () => hubs.map((h) => <option key={h.code} value={h.code}>{h.city} — {h.name}{h.km != null ? ` (${h.km} km)` : ''}</option>),
    [hubs],
  )

  function openOffer(next) {
    if (signInFirst) return
    setOffer(next)
  }

  return (
    <motion.section className="panel wide getting" initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}>
      <h2>Getting to {destName}</h2>
      <p className="muted-l small">
        Book a train — with Tatkal when you are travelling tomorrow — or fall back to a bus from wherever you are.
      </p>

      {/* controls */}
      <div className="gt-controls">
        <label className="gt-field">
          <span>Boarding from</span>
          <select value={from} onChange={(e) => setFrom(e.target.value)}>
            {hubOptions}
          </select>
        </label>
        <label className="gt-field">
          <span>Journey date</span>
          <input type="date" value={date} min={data?.today} onChange={(e) => setDate(e.target.value)} />
        </label>
        <button type="button" className="pill locate" onClick={locate} disabled={geo.state === 'locating'}>
          {geo.state === 'locating' ? 'Locating…' : '◎ Use my location'}
        </button>
      </div>
      {geo.msg && <p className={'muted small geo ' + geo.state}>{geo.msg}</p>}

      {/* tabs */}
      <div className="seg gt-seg">
        <button className={tab === 'train' ? 'on' : ''} onClick={() => setTab('train')} type="button">
          Trains {data ? `(${data.trains.length})` : ''}
        </button>
        <button className={tab === 'bus' ? 'on' : ''} onClick={() => setTab('bus')} type="button">
          Buses {data ? `(${data.buses.length})` : ''}
        </button>
      </div>

      {loading && <p className="muted-l">Searching…</p>}

      {!loading && data && tab === 'train' && (
        <>
          <div className="seg quota-seg">
            <button className={quota === 'general' ? 'on' : ''} onClick={() => setQuota('general')} type="button">General quota</button>
            <button className={quota === 'tatkal' ? 'on' : ''} onClick={() => setQuota('tatkal')} type="button">Tatkal</button>
          </div>

          {quota === 'tatkal' && tw && (
            <p className={'tatkal-bar ' + tw.status}>
              <strong>Tatkal</strong> {tw.message}
              {tw.status === 'open' && <span className="muted small"> · Indian Standard Time is {data.server_time_ist}</span>}
            </p>
          )}

          {data.rail_note && <p className="notice soft">{data.rail_note}</p>}

          {data.trains.length === 0 && <p className="muted-l">No direct train on this route. Try the bus tab.</p>}

          <ul className="trains">
            {data.trains.map((t) => (
              <li key={t.no} className="train">
                <div className="train-top">
                  <div>
                    <strong>{t.no} {t.name}</strong>
                    <div className="muted small">{t.days} · {t.km} km · {t.from_name} → {t.to_name}</div>
                  </div>
                  <div className="train-time">
                    <span>{to12(t.depart)}</span>
                    <em>{t.duration}</em>
                    <span>{to12(t.arrive)}{t.arrive_next_day && <sup>+1</sup>}</span>
                  </div>
                </div>
                <div className="cls-row">
                  {t.classes.map((c) => {
                    const a = c.availability
                    return (
                      <button
                        key={c.cls} type="button"
                        className={'cls ' + (AV_TONE[a.code] || '') + (a.bookable ? ' can' : '')}
                        disabled={!a.bookable || signInFirst}
                        onClick={() => openOffer({ kind: 'train', train: t, cls: c, quota })}
                        title={a.note || ''}
                      >
                        <span className="cls-name">{c.cls}</span>
                        <span className="cls-av">{a.label}</span>
                        <span className="cls-fare">{rupees(c.fare.total)}</span>
                      </button>
                    )
                  })}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {!loading && data && tab === 'bus' && (
        <>
          {fallback && (
            <p className="notice soft">
              {data.no_rail_link
                ? `No train runs all the way to ${destName}. These buses leave from ${data.from.city}.`
                : `Every class is waitlisted on ${date}. These buses from ${data.from.city} still have seats.`}
            </p>
          )}
          {data.buses.length === 0 && <p className="muted-l">No bus service found on this route.</p>}
          <ul className="buses">
            {data.buses.map((b) => (
              <li key={b.id} className="bus">
                <div className="bus-main">
                  <div>
                    <strong>{b.operator}</strong> <span className={'chip ' + (b.kind === 'Government' ? 'gov' : 'priv')}>{b.kind}</span>
                    <div className="muted small">{b.type} · ★ {b.rating} · {b.km} km</div>
                  </div>
                  <div className="train-time">
                    <span>{to12(b.depart)}</span>
                    <em>{b.duration}</em>
                    <span>{to12(b.arrive)}{b.arrive_next_day && <sup>+1</sup>}</span>
                  </div>
                </div>
                <div className="bus-cta">
                  <span className={'badge ' + (b.seats_left > 6 ? 'on' : b.seats_left ? 'rac' : 'off')}>
                    {b.seats_left ? `${b.seats_left} seats` : 'Sold out'}
                  </span>
                  <strong>{rupees(b.fare)}</strong>
                  <button className="btn btn-light small-btn" disabled={!b.seats_left || signInFirst}
                          onClick={() => openOffer({ kind: 'bus', bus: b })} type="button">
                    Select seats
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {signInFirst && (
        <p className="notice soft signin-cta">
          <Link to="/login" state={{ next: pathname }} className="btn btn-light small-btn">Sign in to book</Link>
          <span>You need an account to hold a seat.</span>
        </p>
      )}

      <p className="muted small demo-note">
        Demo booking system — not connected to IRCTC or any bus operator. Timings and fares are modelled, not live.
      </p>

      <AnimatePresence>
        {offer && <BookingSheet offer={offer} date={date} onClose={() => setOffer(null)}
                                onDone={(b) => { setOffer(null); setTicket(b); setNonce((n) => n + 1) }} />}
        {ticket && <Ticket b={ticket} onClose={() => setTicket(null)} />}
      </AnimatePresence>
    </motion.section>
  )
}
