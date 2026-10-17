import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'
import { inrPaise, shortDate, toPaise } from '../format.js'
import Overlay from '../components/Overlay.jsx'

const POLL_MS = 4000
const TABS = ['Itinerary', 'Polls', 'Expenses', 'Settle up', 'People']

/* Shown when two people changed the same thing at once. Nobody's edit is lost silently. */
function Conflict({ info, onTheirs, onMine }) {
  return (
    <Overlay onClose={onTheirs}>
      <motion.div className="sheet" onClick={(e) => e.stopPropagation()} initial={{ y: 30, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
        <header className="sheet-head"><div><h3>Someone changed this at the same time</h3><p className="muted small">Your edit was based on an older version.</p></div></header>
        <div className="sheet-body">
          <div className="conflict-grid">
            <div><h4>Their version</h4><p>{info.theirs}</p></div>
            <div><h4>Your version</h4><p>{info.mine}</p></div>
          </div>
        </div>
        <footer className="sheet-foot">
          <button type="button" className="pill" onClick={onTheirs}>Keep theirs</button>
          <button type="button" className="btn btn-light" onClick={onMine}>Overwrite with mine</button>
        </footer>
      </motion.div>
    </Overlay>
  )
}

function Itinerary({ trip, act, placeNames }) {
  const [form, setForm] = useState({ day: 1, time: '', title: '', place: '', notes: '' })
  const [edit, setEdit] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const days = [...new Set(trip.items.map((i) => i.day))].sort((a, b) => a - b)

  async function add(e) {
    e.preventDefault()
    const ok = await act(() => api(`/api/trips/${trip.id}/items`, { method: 'POST', body: { ...form, day: Number(form.day), place: form.place || null } }))
    if (ok) setForm((f) => ({ ...f, time: '', title: '', notes: '' }))
  }

  async function save(item) {
    // base_rev is the version this edit was STARTED from (edit.rev), not whatever the latest poll brought in.
    // If someone else changed the item since, the server answers 409 and the conflict dialog appears.
    const body = { day: Number(edit.day), time: edit.time, title: edit.title, place: edit.place || null, notes: edit.notes }
    const run = (rev) => api(`/api/trips/${trip.id}/items/${item.id}`, { method: 'PATCH', body: { ...body, base_rev: rev } })
    const ok = await act(() => run(edit.rev), {
      mine: `${edit.title}${edit.time ? ' at ' + edit.time : ''} on day ${edit.day}`, retry: run,
      theirs: (c) => `${c.title}${c.time ? ' at ' + c.time : ''} on day ${c.day}`, onKeep: () => setEdit(null), onDone: () => setEdit(null),
    })
    if (ok) setEdit(null)
  }

  return (
    <div className="trip-pane">
      <form className="panel add-form" onSubmit={add}>
        <h3>Add to the itinerary</h3>
        <div className="row-fields">
          <label>Day<input type="number" min="1" max="60" value={form.day} onChange={set('day')} required /></label>
          <label>Time<input type="time" value={form.time} onChange={set('time')} /></label>
          <label className="grow">What<input value={form.title} onChange={set('title')} placeholder="Meenakshi Amman Temple" maxLength={120} required /></label>
        </div>
        <div className="row-fields">
          <label>Place<select value={form.place} onChange={set('place')}><option value="">Anywhere</option>{Object.entries(placeNames).map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select></label>
          <label className="grow">Notes<input value={form.notes} onChange={set('notes')} maxLength={500} placeholder="Optional" /></label>
          <button className="btn btn-light">Add</button>
        </div>
      </form>

      {days.length === 0 && <p className="muted-l">Nothing planned yet. Add the first stop above, or build a plan with the <Link to="/planner">trip planner</Link> and save it here.</p>}
      {days.map((d) => (
        <section key={d} className="panel day-block">
          <h3>Day {d}</h3>
          <ul className="it-list">
            {trip.items.filter((i) => i.day === d).map((i) => (
              <li key={i.id}>
                {edit?.id === i.id ? (
                  <div className="edit-row">
                    <input type="number" min="1" max="60" value={edit.day} onChange={(e) => setEdit({ ...edit, day: e.target.value })} aria-label="Day" />
                    <input type="time" value={edit.time || ''} onChange={(e) => setEdit({ ...edit, time: e.target.value })} aria-label="Time" />
                    <input className="grow" value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} aria-label="Title" />
                    <input className="grow" value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} placeholder="Notes" aria-label="Notes" />
                    <button className="btn btn-light small-btn" onClick={() => save(i)}>Save</button>
                    <button className="pill" onClick={() => setEdit(null)}>Cancel</button>
                  </div>
                ) : (
                  <>
                    <span className="it-time">{i.time || '—'}</span>
                    <div className="it-main"><strong>{i.title}</strong>{i.place && <span className="chip">{placeNames[i.place] || i.place}</span>}{i.notes && <p className="muted small">{i.notes}</p>}</div>
                    <span className="it-actions">
                      <button className="chipbtn" onClick={() => setEdit({ id: i.id, rev: i.rev, day: i.day, time: i.time, title: i.title, place: i.place, notes: i.notes })}>Edit</button>
                      <button className="chipbtn" onClick={() => act(() => api(`/api/trips/${trip.id}/items/${i.id}`, { method: 'DELETE' }))}>Delete</button>
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function Polls({ trip, act }) {
  const [q, setQ] = useState('')
  const [opts, setOpts] = useState('')
  async function add(e) {
    e.preventDefault()
    const ok = await act(() => api(`/api/trips/${trip.id}/polls`, { method: 'POST', body: { question: q, options: opts.split('\n').map((x) => x.trim()).filter(Boolean) } }))
    if (ok) { setQ(''); setOpts('') }
  }
  return (
    <div className="trip-pane">
      <form className="panel add-form" onSubmit={add}>
        <h3>Ask the group</h3>
        <label>Question<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Where shall we have dinner?" maxLength={160} required /></label>
        <label>Options <span className="muted small">(one per line, 2 to 8)</span><textarea rows={3} value={opts} onChange={(e) => setOpts(e.target.value)} placeholder={'Murugan Idli Shop\nTemple City'} required /></label>
        <button className="btn btn-light">Start poll</button>
      </form>
      {trip.polls.length === 0 && <p className="muted-l">No polls yet.</p>}
      {trip.polls.map((p) => {
        const top = Math.max(1, ...Object.values(p.tally))
        return (
          <section key={p.id} className="panel poll">
            <header><h3>{p.question}</h3>{p.closed ? <span className="chip">Closed</span> : <button className="chipbtn" onClick={() => act(() => api(`/api/trips/${trip.id}/polls/${p.id}/close`, { method: 'POST' }))}>Close poll</button>}</header>
            <ul>
              {p.options.map((o) => (
                <li key={o.id}>
                  <button className={'poll-opt' + (p.my_vote === o.id ? ' mine' : '')} disabled={p.closed} aria-pressed={p.my_vote === o.id}
                    onClick={() => act(() => api(`/api/trips/${trip.id}/polls/${p.id}/vote`, { method: 'POST', body: { option_id: o.id } }))}>
                    <i style={{ width: `${(p.tally[o.id] / top) * 100}%` }} />
                    <span>{o.text}</span><strong>{p.tally[o.id]}</strong>
                  </button>
                </li>
              ))}
            </ul>
            <p className="muted small">{p.voters} of {trip.members.filter((m) => m.active).length} voted. Tap your choice again to withdraw.</p>
          </section>
        )
      })}
    </div>
  )
}

function Expenses({ trip, act }) {
  const active = trip.members.filter((m) => m.active)
  const [f, setF] = useState({ description: '', amount: '', paid_by: trip.me, mode: 'equal', among: [], weights: {}, amounts: {} })
  const [err, setErr] = useState('')
  const [edit, setEdit] = useState(null)
  const nameOf = (id) => trip.names[id] || 'Someone'

  const split = () => {
    if (f.mode === 'shares') return { mode: 'shares', weights: Object.fromEntries(active.map((m) => [m.id, Number(f.weights[m.id] ?? 1)]).filter(([, w]) => w > 0)) }
    if (f.mode === 'exact') return { mode: 'exact', amounts: Object.fromEntries(active.map((m) => [m.id, toPaise(f.amounts[m.id]) || 0]).filter(([, a]) => a > 0)) }
    return { mode: 'equal', among: f.among.length ? f.among : active.map((m) => m.id) }
  }

  async function add(e) {
    e.preventDefault()
    setErr('')
    const paise = toPaise(f.amount)
    if (!paise) return setErr('Enter the amount in rupees, for example 450 or 450.50.')
    const ok = await act(() => api(`/api/trips/${trip.id}/expenses`, { method: 'POST', body: { description: f.description, amount: paise, paid_by: f.paid_by, split: split() } }))
    if (ok) setF((x) => ({ ...x, description: '', amount: '', among: [], weights: {}, amounts: {} }))
  }

  async function saveEdit(x) {
    const paise = toPaise(edit.amount)
    if (!paise) return
    const run = (rev) => api(`/api/trips/${trip.id}/expenses/${x.id}`, { method: 'PATCH', body: { base_rev: rev, description: edit.description, amount: paise } })
    const ok = await act(() => run(edit.rev), {
      mine: `${edit.description}, ${inrPaise(paise)}`, retry: run, theirs: (c) => `${c.description}, ${inrPaise(c.amount)}`,
      onKeep: () => setEdit(null), onDone: () => setEdit(null),
    })
    if (ok) setEdit(null)
  }

  const toggle = (id) => setF((x) => ({ ...x, among: x.among.includes(id) ? x.among.filter((m) => m !== id) : [...x.among, id] }))

  return (
    <div className="trip-pane">
      <form className="panel add-form" onSubmit={add}>
        <h3>Add an expense</h3>
        <div className="row-fields">
          <label className="grow">What for<input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="Fuel, dinner, tickets" maxLength={120} required /></label>
          <label>Amount (₹)<input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} placeholder="450.50" required /></label>
          <label>Paid by<select value={f.paid_by} onChange={(e) => setF({ ...f, paid_by: e.target.value })}>{active.map((m) => <option key={m.id} value={m.id}>{m.name}{m.id === trip.me ? ' (you)' : ''}</option>)}</select></label>
        </div>
        <div className="seg" role="radiogroup" aria-label="How to split">
          {[['equal', 'Equally'], ['shares', 'By shares'], ['exact', 'Exact amounts']].map(([k, l]) => <button key={k} type="button" role="radio" aria-checked={f.mode === k} className={f.mode === k ? 'on' : ''} onClick={() => setF({ ...f, mode: k })}>{l}</button>)}
        </div>
        <div className="split-box">
          {f.mode === 'equal' && (
            <>
              <p className="muted small">Split equally between {f.among.length || active.length} {(f.among.length || active.length) === 1 ? 'person' : 'people'}. Tick people to leave others out.</p>
              <div className="pills">{active.map((m) => <button key={m.id} type="button" className={'pill' + (f.among.includes(m.id) ? ' active' : '')} aria-pressed={f.among.includes(m.id)} onClick={() => toggle(m.id)}>{m.name}</button>)}</div>
            </>
          )}
          {f.mode === 'shares' && active.map((m) => <label key={m.id} className="split-row">{m.name}<input type="number" min="0" max="1000" value={f.weights[m.id] ?? 1} onChange={(e) => setF({ ...f, weights: { ...f.weights, [m.id]: e.target.value } })} /></label>)}
          {f.mode === 'exact' && active.map((m) => <label key={m.id} className="split-row">{m.name}<input inputMode="decimal" placeholder="0" value={f.amounts[m.id] ?? ''} onChange={(e) => setF({ ...f, amounts: { ...f.amounts, [m.id]: e.target.value } })} /></label>)}
        </div>
        {err && <p className="notice" role="alert">{err}</p>}
        <button className="btn btn-light">Add expense</button>
      </form>

      {trip.expenses.length === 0 && <p className="muted-l">No expenses yet.</p>}
      <ul className="exp-list">
        {trip.expenses.map((x) => (
          <li key={x.id} className={'panel exp' + (x.kind === 'settlement' ? ' pay' : '')}>
            {edit?.id === x.id ? (
              <div className="edit-row">
                <input className="grow" value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} aria-label="Description" />
                <input value={edit.amount} onChange={(e) => setEdit({ ...edit, amount: e.target.value })} inputMode="decimal" aria-label="Amount" />
                <button className="btn btn-light small-btn" onClick={() => saveEdit(x)}>Save</button>
                <button className="pill" onClick={() => setEdit(null)}>Cancel</button>
              </div>
            ) : (
              <>
                <div className="exp-main">
                  <strong>{x.description}</strong>
                  <span className="muted small">{shortDate(x.date)} · {x.kind === 'settlement' ? 'recorded payment' : `paid by ${nameOf(x.paid_by)}`}</span>
                  <div className="exp-shares">{Object.entries(x.shares).map(([id, v]) => <span key={id} className="chip">{nameOf(id)} {inrPaise(v)}</span>)}</div>
                </div>
                <div className="exp-side">
                  <strong>{inrPaise(x.amount)}</strong>
                  <span className="it-actions">
                    {x.kind === 'expense' && <button className="chipbtn" onClick={() => setEdit({ id: x.id, rev: x.rev, description: x.description, amount: String(x.amount / 100) })}>Edit</button>}
                    <button className="chipbtn" onClick={() => act(() => api(`/api/trips/${trip.id}/expenses/${x.id}`, { method: 'DELETE' }))}>Delete</button>
                  </span>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Settle({ trip, act }) {
  const name = (id) => trip.names[id] || 'Someone'
  return (
    <div className="trip-pane">
      <section className="panel">
        <h3>Who owes what</h3>
        <ul className="bal-list">
          {trip.members.filter((m) => m.active || m.balance !== 0).map((m) => (
            <li key={m.id}><span>{m.name}{m.id === trip.me ? ' (you)' : ''}</span>
              <strong className={m.balance > 0 ? 'in' : m.balance < 0 ? 'out' : ''}>{m.balance === 0 ? 'Settled' : m.balance > 0 ? `is owed ${inrPaise(m.balance)}` : `owes ${inrPaise(-m.balance)}`}</strong></li>
          ))}
        </ul>
        <p className="muted small">Total spent {inrPaise(trip.totals.spent)} · about {inrPaise(trip.totals.per_person)} each.</p>
      </section>
      <section className="panel">
        <h3>Settle up</h3>
        {trip.transfers.length === 0 ? <p className="muted-l">Everyone is square. 🎉</p> : (
          <>
            <p className="muted small">The fewest payments that clear every balance:</p>
            <ul className="bal-list">
              {trip.transfers.map((t) => (
                <li key={t.from + t.to}>
                  <span><strong>{name(t.from)}</strong> pays <strong>{name(t.to)}</strong></span>
                  <span className="it-actions"><strong>{inrPaise(t.amount)}</strong>
                    {(t.from === trip.me || t.to === trip.me || trip.role === 'owner') && <button className="chipbtn" onClick={() => act(() => api(`/api/trips/${trip.id}/settle`, { method: 'POST', body: { from: t.from, to: t.to, amount: t.amount } }))}>Mark as paid</button>}
                  </span>
                </li>
              ))}
            </ul>
            <p className="muted small">Pay each other however you like, then tap "Mark as paid" so the balances update. No money moves through Epic TN.</p>
          </>
        )}
      </section>
    </div>
  )
}

function People({ trip, act, nav }) {
  const link = trip.join ? `${window.location.origin}/trips/join/${trip.join.code}` : ''
  const [copied, setCopied] = useState(false)
  async function copy() {
    try { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1800) } catch { /* the code is shown too */ }
  }
  return (
    <div className="trip-pane">
      {trip.join && (
        <section className="panel">
          <h3>Invite friends</h3>
          <p className="invite-code mono" aria-label="Invite code">{trip.join.code}</p>
          <p className="muted small">{trip.join.active ? 'Anyone with this code can join. Share the link or the code.' : 'The code is switched off, so nobody new can join.'}</p>
          <div className="it-actions">
            <button className="btn btn-light small-btn" onClick={copy} disabled={!trip.join.active}>{copied ? 'Copied!' : 'Copy invite link'}</button>
            <button className="pill" onClick={() => act(() => api(`/api/trips/${trip.id}/code`, { method: 'POST', body: { action: trip.join.active ? 'disable' : 'enable' } }))}>{trip.join.active ? 'Switch off' : 'Switch on'}</button>
            <button className="pill" onClick={() => act(() => api(`/api/trips/${trip.id}/code`, { method: 'POST', body: { action: 'regenerate' } }))}>New code</button>
          </div>
        </section>
      )}
      <section className="panel">
        <h3>People</h3>
        <ul className="bal-list">
          {trip.members.filter((m) => m.active).map((m) => (
            <li key={m.id}><span>{m.name}{m.id === trip.me ? ' (you)' : ''} {m.role === 'owner' && <span className="chip">Owner</span>}</span>
              {m.role !== 'owner' && (m.id === trip.me || trip.role === 'owner') && (
                <button className="chipbtn" onClick={() => act(() => api(`/api/trips/${trip.id}/members/${m.id}`, { method: 'DELETE' }), { leave: m.id === trip.me })}>{m.id === trip.me ? 'Leave trip' : 'Remove'}</button>
              )}
            </li>
          ))}
        </ul>
        {trip.role === 'owner' && (
          <button className="pill danger" onClick={async () => { if (window.confirm('Delete this trip for everyone?')) { await api(`/api/trips/${trip.id}`, { method: 'DELETE' }); nav('/trips') } }}>Delete trip</button>
        )}
      </section>
    </div>
  )
}

export default function Trip() {
  const { id } = useParams()
  const { user, ready } = useAuth()
  const nav = useNavigate()
  const [trip, setTrip] = useState(null)
  const [tab, setTab] = useState('Itinerary')
  const [err, setErr] = useState('')
  const [gone, setGone] = useState(false)
  const [offline, setOffline] = useState(false)
  const [synced, setSynced] = useState(null)
  const [conflict, setConflict] = useState(null)
  const [places, setPlaces] = useState({})
  const rev = useRef(0)

  useEffect(() => {
    api('/api/destinations?q=&category=').then((d) => setPlaces(Object.fromEntries((Array.isArray(d) ? d : []).map((p) => [p.id, p.name])))).catch(() => {})
  }, [])

  const pull = useCallback(async (force) => {
    try {
      const j = await api(`/api/trips/${id}${force ? '' : `?since=${rev.current}`}`)
      if (j.changed !== false) { setTrip(j); rev.current = j.rev }
      setOffline(false)
      setSynced(Date.now())
    } catch (e) {
      if (e.status === 404) setGone(true)
      else setOffline(true)
    }
  }, [id])

  // Near-real-time sync: ask "anything new since rev N?" every few seconds (and straight away when the tab comes back).
  useEffect(() => {
    if (!user) return undefined
    let live = true, timer
    const tick = async () => {
      if (!document.hidden || rev.current === 0) await pull(false)      // a hidden tab pauses polling, but never skips the first load
      if (live) timer = setTimeout(tick, POLL_MS)
    }
    const wake = () => { if (!document.hidden) pull(false) }
    tick()
    document.addEventListener('visibilitychange', wake)
    return () => { live = false; clearTimeout(timer); document.removeEventListener('visibilitychange', wake) }
  }, [user, pull])

  /* Runs a change, refreshes, and turns a 409 into the conflict dialog. Returns true on success. */
  const act = useCallback(async (fn, c) => {
    setErr('')
    try {
      await fn()
      await pull(true)
      if (c?.leave) nav('/trips')
      return true
    } catch (e) {
      if (e.status === 409 && e.data?.current && c?.retry) {
        setConflict({
          theirs: c.theirs(e.data.current), mine: c.mine, keep: c.onKeep,
          overwrite: async () => { try { await c.retry(e.data.current.rev); await pull(true); c.onDone?.(); setConflict(null) } catch (e2) { setErr(e2.message); setConflict(null) } },
        })
      } else {
        setErr(e.message)
      }
      return false
    }
  }, [pull, nav])

  if (!ready) return <main className="section dark page"><p className="muted-l">Loading…</p></main>
  if (!user) return <Navigate to="/login" replace state={{ next: `/trips/${id}` }} />
  if (gone) return <main className="section dark page"><h1 className="big">Trip not found</h1><p className="muted-l">It may have been deleted, or you're no longer part of it.</p><Link to="/trips" className="btn btn-light">Back to trips</Link></main>
  if (!trip) return <main className="section dark page"><p className="muted-l">Loading trip…</p></main>

  return (
    <main className="section dark page">
      <Link to="/trips" className="back-link">← All trips</Link>
      <div className="page-head">
        <div>
          <h1 className="big">{trip.name}</h1>
          <p className="muted-l">{trip.start_date ? `Starts ${shortDate(trip.start_date)} · ` : ''}{trip.members.filter((m) => m.active).map((m) => m.name).join(', ')}</p>
        </div>
        <span className={'sync' + (offline ? ' off' : '')} role="status">{offline ? 'Offline. Retrying…' : synced ? 'Live · updates every few seconds' : 'Connecting…'}</span>
      </div>
      {err && <p className="notice" role="alert">{err}</p>}

      <div className="seg trip-tabs" role="tablist">
        {TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}
      </div>

      {tab === 'Itinerary' && <Itinerary trip={trip} act={act} placeNames={places} />}
      {tab === 'Polls' && <Polls trip={trip} act={act} />}
      {tab === 'Expenses' && <Expenses key={trip.members.length} trip={trip} act={act} />}
      {tab === 'Settle up' && <Settle trip={trip} act={act} />}
      {tab === 'People' && <People trip={trip} act={act} nav={nav} />}

      <AnimatePresence>
        {conflict && <Conflict info={conflict} onTheirs={() => { conflict.keep?.(); setConflict(null); pull(true) }} onMine={conflict.overwrite} />}
      </AnimatePresence>
    </main>
  )
}
