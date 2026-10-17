import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api, useAuth } from '../auth.jsx'
import { addDays, dateLabel, inr, shortDate, todayISO } from '../format.js'
import Overlay from '../components/Overlay.jsx'

const INTEREST_LABEL = { temples: 'Temples', heritage: 'Heritage', nature: 'Nature', beaches: 'Beaches', food: 'Food' }
const PACE_LABEL = { relaxed: 'Relaxed', balanced: 'Balanced', packed: 'Packed' }
const COMFORT_LABEL = { budget: 'Budget', standard: 'Standard', comfort: 'Comfortable' }
const COST_LABEL = { travel: 'Travel', stay: 'Hotels', food: 'Food', local: 'Local transport' }
const EXAMPLES = ['4 days from Chennai, temples and beaches, budget 20k for two', 'A relaxed weekend in Kodaikanal for my wife and me', 'Family of 4, 5 days, Madurai and Rameswaram, no return']

/* start -> every stop -> back to the start, without repeating the start when it is also the first stop */
const routeOf = (p) => {
  const { start, return_home } = p.request
  const stops = p.summary.towns
  const route = stops[0] === start ? [...stops] : [start, ...stops]
  return return_home && route[route.length - 1] !== start ? [...route, start] : route
}

const blank = () => ({ start: 'chennai', days: 3, travellers: 2, interests: ['temples', 'heritage'], pace: 'balanced', comfort: 'standard', budget: '', start_date: addDays(todayISO(), 1), return_home: true, must: [], avoid: [] })

function SaveSheet({ plan, onClose }) {
  const nav = useNavigate()
  const [trips, setTrips] = useState(null)
  const [pick, setPick] = useState('new')
  const [name, setName] = useState(`${plan.summary.town_names.join(' & ')} trip`)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/trips').then(setTrips).catch((e) => setErr(e.message)) }, [])

  const items = useMemo(() => plan.days.flatMap((d) => d.items
    .filter((i) => i.type === 'activity' || i.type === 'travel')
    .map((i) => ({ day: d.day, time: i.start, title: i.title, place: d.town,
                   notes: i.type === 'travel' ? i.detail || '' : i.indicative ? 'Typical hours, confirm locally' : i.note || '' }))).slice(0, 60), [plan])

  async function save() {
    setBusy(true); setErr('')
    try {
      let id = pick
      if (pick === 'new') id = (await api('/api/trips', { method: 'POST', body: { name, start_date: plan.request.start_date } })).id
      await api(`/api/trips/${id}/items/import`, { method: 'POST', body: { items } })
      nav(`/trips/${id}`)
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }

  return (
    <Overlay onClose={onClose}>
      <motion.div className="sheet" onClick={(e) => e.stopPropagation()} initial={{ y: 30, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 30, opacity: 0 }}>
        <header className="sheet-head"><div><h3>Save this plan to a trip</h3><p className="muted small">{items.length} stops go onto the shared itinerary for your group to edit.</p></div><button type="button" className="x" onClick={onClose} aria-label="Close">✕</button></header>
        <div className="sheet-body">
          <label className="form-label">Add to
            <select className="search" value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="new">A new trip…</option>
              {(trips || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          {pick === 'new' && <label className="form-label">Trip name<input className="search" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>}
          {err && <p className="notice" role="alert">{err}</p>}
        </div>
        <footer className="sheet-foot"><button type="button" className="pill" onClick={onClose}>Cancel</button><button className="btn btn-light" onClick={save} disabled={busy || (pick === 'new' && !name.trim())}>{busy ? 'Saving…' : 'Save to trip'}</button></footer>
      </motion.div>
    </Overlay>
  )
}

export default function Planner() {
  const { user } = useAuth()
  const [opts, setOpts] = useState(null)
  const [f, setF] = useState(blank)
  const [text, setText] = useState('')
  const [understood, setUnderstood] = useState([])
  const [result, setResult] = useState(null)        // {plan, narration}
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [writing, setWriting] = useState(false)
  const [aiNote, setAiNote] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => { api('/api/planner/options').then(setOpts).catch(() => setErr('The planner is not reachable right now.')) }, [])
  const placeName = (id) => opts?.places.find((p) => p.id === id)?.name || id
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  const toggle = (k, v) => setF((x) => ({ ...x, [k]: x[k].includes(v) ? x[k].filter((y) => y !== v) : [...x[k], v] }))
  const flip = (k, other, id) => setF((x) => ({ ...x, [k]: x[k].includes(id) ? x[k].filter((y) => y !== id) : [...x[k], id], [other]: x[other].filter((y) => y !== id) }))

  async function understand(e) {
    e?.preventDefault()
    if (!text.trim()) return
    setErr('')
    try {
      const j = await api('/api/planner/parse', { method: 'POST', body: { text } })
      const r = j.request
      setF((x) => ({ ...x, ...(r.start && { start: r.start }), ...(r.days && { days: r.days }), ...(r.travellers && { travellers: r.travellers }),
        ...(r.budget && { budget: String(r.budget) }), ...(r.interests && { interests: r.interests }), ...(r.pace && { pace: r.pace }), ...(r.comfort && { comfort: r.comfort }),
        ...(r.must && { must: r.must }), ...(r.avoid && { avoid: r.avoid }), ...('return_home' in r && { return_home: r.return_home }) }))
      setUnderstood(j.understood)
    } catch (e2) {
      setErr(e2.message)
    }
  }

  async function plan(e) {
    e.preventDefault()
    setBusy(true); setErr(''); setAiNote('')
    try {
      const body = { ...f, days: Number(f.days), travellers: Number(f.travellers), budget: f.budget ? Number(f.budget) : null }
      setResult(await api('/api/planner/plan', { method: 'POST', body: { request: body } }))
      setTimeout(() => document.getElementById('plan-result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  async function rewrite() {
    setWriting(true); setAiNote('')
    try {
      const j = await api('/api/planner/narrate', { method: 'POST', body: { request: result.plan.request } })
      setResult((r) => ({ ...r, narration: j.narration }))
    } catch (e) {
      setAiNote(e.message)
    } finally {
      setWriting(false)
    }
  }

  const p = result?.plan
  const n = result?.narration
  const leg = (l) => {
    const last = [...p.days].reverse().find((d) => d.town === l.from)
    return l.from === p.request.start && l.from !== p.days[0].town ? p.request.start_date : last?.date || p.request.start_date
  }

  return (
    <main className="section dark page planner">
      <h1 className="big">Plan a trip</h1>
      <p className="muted-l">Tell us what you like. The planner picks the towns, the route and the days, and respects temple opening hours, travel time, crowds and your budget.</p>

      <form className="panel nl-box" onSubmit={understand}>
        <label className="form-label">Describe your trip <span className="muted small">(or just use the controls below)</span>
          <textarea className="search" rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={EXAMPLES[0]} maxLength={600} />
        </label>
        <div className="nl-actions">
          <button className="btn btn-light small-btn" disabled={!text.trim()}>Fill the form from this</button>
          {EXAMPLES.map((x) => <button key={x} type="button" className="chipbtn" onClick={() => setText(x)}>{x.length > 38 ? x.slice(0, 36) + '…' : x}</button>)}
        </div>
        {understood.length > 0 && <p className="understood"><span className="muted small">Understood:</span> {understood.map((u) => <span key={u} className="chip">{u}</span>)}</p>}
      </form>

      <form className="panel planner-form" onSubmit={plan}>
        <div className="pf-grid">
          <label className="gt-field"><span>Starting from</span>
            <select value={f.start} onChange={(e) => set('start', e.target.value)}>{opts?.places.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
          <label className="gt-field"><span>Days</span><input type="number" min="1" max={opts?.max_days || 7} value={f.days} onChange={(e) => set('days', e.target.value)} /></label>
          <label className="gt-field"><span>Travellers</span><input type="number" min="1" max="6" value={f.travellers} onChange={(e) => set('travellers', e.target.value)} /></label>
          <label className="gt-field"><span>Start date</span><input type="date" min={todayISO()} value={f.start_date} onChange={(e) => set('start_date', e.target.value)} /></label>
          <label className="gt-field"><span>Budget (₹, optional)</span><input inputMode="numeric" value={f.budget} placeholder="No limit" onChange={(e) => set('budget', e.target.value.replace(/\D/g, ''))} /></label>
          <label className="gt-field"><span>Pace</span><select value={f.pace} onChange={(e) => set('pace', e.target.value)}>{Object.entries(PACE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="gt-field"><span>Comfort</span><select value={f.comfort} onChange={(e) => set('comfort', e.target.value)}>{Object.entries(COMFORT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="check-field"><input type="checkbox" checked={f.return_home} onChange={(e) => set('return_home', e.target.checked)} /> Return to the start</label>
        </div>

        <fieldset><legend>I enjoy</legend>
          <div className="pills">{Object.entries(INTEREST_LABEL).map(([k, v]) => <button type="button" key={k} className={'pill' + (f.interests.includes(k) ? ' active' : '')} aria-pressed={f.interests.includes(k)} onClick={() => toggle('interests', k)}>{v}</button>)}</div>
        </fieldset>
        <details className="more">
          <summary>Must-see and skip places</summary>
          <p className="muted small">Must-see:</p>
          <div className="pills">{opts?.places.map((o) => <button type="button" key={o.id} className={'pill' + (f.must.includes(o.id) ? ' active' : '')} aria-pressed={f.must.includes(o.id)} onClick={() => flip('must', 'avoid', o.id)}>{o.name}</button>)}</div>
          <p className="muted small">Skip:</p>
          <div className="pills">{opts?.places.map((o) => <button type="button" key={o.id} className={'pill' + (f.avoid.includes(o.id) ? ' active skip' : '')} aria-pressed={f.avoid.includes(o.id)} onClick={() => flip('avoid', 'must', o.id)}>{o.name}</button>)}</div>
        </details>

        {err && <p className="notice" role="alert">{err}</p>}
        <button className="btn btn-light plan-btn" disabled={busy || !opts}>{busy ? 'Planning…' : 'Plan my trip'}</button>
      </form>

      {p && (
        <section id="plan-result" className="plan-result">
          <div className="plan-summary">
            <div className="panel ps-main">
              <span className="muted small">{p.summary.days} days · {p.request.travellers} traveller{p.request.travellers > 1 ? 's' : ''} · {dateLabel(p.request.start_date)}</span>
              <div className="route-chain">{routeOf(p).map((t, i, a) => (
                <span key={i} className="route-stop">{placeName(t)}{i < a.length - 1 && <em aria-hidden="true">→</em>}</span>))}</div>
              <div className="ps-total"><strong>{inr(p.summary.cost.total)}</strong><span className="muted small"> about {inr(p.summary.cost.per_person)} each</span>
                {p.summary.within_budget === true && <span className="badge on">Within budget</span>}{p.summary.over_budget && <span className="badge off">Over budget</span>}</div>
              <ul className="cost-bars">{Object.entries(p.summary.cost.breakdown).map(([k, v]) => (
                <li key={k}><span>{COST_LABEL[k]}</span><span className="bar"><i style={{ width: `${(v / p.summary.cost.total) * 100}%` }} /></span><strong>{inr(v)}</strong></li>))}</ul>
              <p className="muted small">An estimate: fares and hotel rates are modelled, and sightseeing entry fees aren't included.</p>
            </div>
            <div className="panel ps-side">
              {p.notes.length > 0 && <><h3>Good to know</h3><ul className="plain">{p.notes.map((x) => <li key={x}>{x}</li>)}</ul></>}
            </div>
          </div>

          <div className="panel narr">
            <div className="narr-head">
              <h2>Your trip in words</h2>
              <span className={'badge ' + (n.source === 'template' ? 'rac' : 'on')} title={n.llm_parts ? `${n.llm_parts.used} of ${n.llm_parts.of} parts passed the fact-check` : ''}>
                {n.source === 'template' ? 'Written from templates' : `Written by ${n.model}${n.source === 'mixed' ? ' (partly)' : ''}`}</span>
            </div>
            <p>{n.intro}</p>
            <div className="narr-actions">
              <button className="btn btn-light small-btn" onClick={rewrite} disabled={writing || (opts && !opts.llm.available)}>{writing ? 'The model is writing…' : 'Rewrite with the local AI'}</button>
              {opts && !opts.llm.available && <span className="muted small">Local AI is off: {opts.llm.reason}</span>}
              {writing && <span className="muted small">This can take a minute or two on a CPU.</span>}
              {aiNote && <span className="muted small" role="status">{aiNote}</span>}
              {user ? <button className="pill" onClick={() => setSaving(true)}>Save to a trip</button> : <Link to="/login" state={{ next: '/planner' }} className="pill">Sign in to save</Link>}
            </div>
            {n.llm_parts && <p className="muted small">Every sentence the AI writes is checked against the plan. Anything mentioning a time, price, number or place that isn't in the plan is replaced with the template text.</p>}
          </div>

          <div className="plan-days">
            {p.days.map((d, i) => (
              <motion.article key={d.day} className="panel pday" initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}>
                <header>
                  <div><span className="muted small">Day {d.day} · {d.weekday} {shortDate(d.date)}</span><h3>{d.town_name}</h3></div>
                  <div className="pday-chips"><span className={'lvl c-' + d.crowd.toLowerCase()}>{d.crowd === 'High' ? 'Busy' : d.crowd === 'Medium' ? 'Moderate' : 'Quiet'}</span>{d.rain != null && d.rain >= 50 && <span className="chip">Rain {Math.round(d.rain)}%</span>}</div>
                </header>
                <p className="pday-sum">{n.days[i]?.summary}</p>
                <ol className="timeline">
                  {d.items.map((it, j) => (
                    <li key={j} className={'tl-' + it.type}>
                      <span className="tl-time">{it.start}{it.end !== it.start && <>–{it.end}</>}</span>
                      <div><strong>{it.title}</strong>{it.detail && <span className="muted small"> · {it.detail}</span>}{it.indicative && <span className="est" title="Typical hours, confirm locally">~</span>}{it.overnight && <span className="chip">Overnight</span>}
                        {it.note && <p className="muted small">{it.note}</p>}</div>
                    </li>
                  ))}
                </ol>
                {d.notes.map((x) => <p key={x} className="notice soft small-note">{x}</p>)}
                {n.days[i]?.tip && <p className="tip">💡 {n.days[i].tip}</p>}
              </motion.article>
            ))}
          </div>

          <div className="plan-book">
            <div className="panel">
              <h3>Book the journeys</h3>
              <ul className="plain">{p.legs.map((l) => (
                <li key={l.from + l.to + l.hours}><span>{l.from_name} → {l.to_name} · {l.mode} · {l.hours}h{l.overnight ? ' overnight' : ''} · about {inr(l.fare)} each</span>
                  <Link className="chipbtn" to={`/tickets?from=${l.from}&to=${l.to}&date=${leg(l)}`}>Find tickets</Link></li>))}</ul>
            </div>
            <div className="panel">
              <h3>Where you'd stay</h3>
              {p.stays.length === 0 ? <p className="muted-l">No hotel nights needed.</p> : (
                <ul className="plain">{p.stays.map((s) => (
                  <li key={s.town}><span>{s.nights} night{s.nights > 1 ? 's' : ''} in {placeName(s.town)} · {s.hotel} · about {inr(s.avg_per_night)}/night</span>
                    <Link className="chipbtn" to={`/destination/${s.town}?checkin=${s.from}#stay`}>See stays</Link></li>))}</ul>
              )}
              <p className="muted small">Hotel names are sample listings.</p>
            </div>
          </div>
          <p className="muted small demo-note">The planner chooses and orders the stops itself. Durations and non-worship opening hours are estimates, marked ~. Fares and hotel prices are modelled.</p>
        </section>
      )}

      <AnimatePresence>{saving && p && <SaveSheet plan={p} onClose={() => setSaving(false)} />}</AnimatePresence>
    </main>
  )
}
