import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { api, API_BASE, useAuth } from '../auth.jsx'
import { dateLabel } from '../format.js'
import Overlay from './Overlay.jsx'

const MAX_PHOTOS = 3
const MAX_BYTES = 5 * 1024 * 1024
const photoUrl = (p) => (p.startsWith('http') ? p : API_BASE + p)

function Stars({ value, size = 'md' }) {
  return (
    <span className={'stars ' + size} role="img" aria-label={`${value} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((n) => <span key={n} className={n <= Math.round(value) ? 'on' : ''} aria-hidden="true">★</span>)}
    </span>
  )
}

function StarPicker({ value, onChange }) {
  return (
    <div className="star-pick" role="radiogroup" aria-label="Your rating">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} star${n > 1 ? 's' : ''}`} className={n <= value ? 'on' : ''} onClick={() => onChange(n)}>★</button>
      ))}
    </div>
  )
}

function Editor({ place, mine, onSaved, onCancel }) {
  const [rating, setRating] = useState(mine?.rating || 0)
  const [title, setTitle] = useState(mine?.title || '')
  const [text, setText] = useState(mine?.text || '')
  const [files, setFiles] = useState([])
  const [previews, setPreviews] = useState([])
  const [removeOld, setRemoveOld] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const urls = files.map((f) => URL.createObjectURL(f))
    setPreviews(urls)
    return () => urls.forEach((u) => URL.revokeObjectURL(u))
  }, [files])

  function pick(e) {
    const chosen = [...e.target.files]
    e.target.value = ''
    const bad = chosen.find((f) => !/^image\/(jpeg|png|webp)$/.test(f.type) || f.size > MAX_BYTES)
    if (bad) return setErr(`${bad.name}: photos must be JPEG, PNG or WebP, under 5 MB.`)
    setErr('')
    setFiles((cur) => [...cur, ...chosen].slice(0, MAX_PHOTOS))
  }

  async function submit(e) {
    e.preventDefault()
    if (!rating) return setErr('Choose a star rating.')
    setErr(''); setBusy(true)
    const fd = new FormData()
    fd.append('rating', rating)
    fd.append('title', title)
    fd.append('text', text)
    files.forEach((f) => fd.append('photos', f))
    if (removeOld && !files.length) fd.append('remove_photos', '1')
    try {
      await api(`/api/destinations/${place}/reviews`, { method: 'POST', body: fd })
      onSaved()
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="review-form" onSubmit={submit}>
      <h3>{mine ? 'Edit your review' : 'Write a review'}</h3>
      <StarPicker value={rating} onChange={setRating} />
      <label>Title <span className="muted small">(optional)</span><input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} placeholder="Sum it up" /></label>
      <label>Your experience
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} maxLength={1500} required minLength={20} placeholder="What was it like? What would you tell a friend?" />
        <span className={'muted small count' + (text.trim().length < 20 ? ' short' : '')}>{text.trim().length}/1500 · at least 20 characters</span>
      </label>
      <div className="photo-pick">
        <label className="pill file-btn">Add photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={pick} disabled={files.length >= MAX_PHOTOS} /></label>
        <span className="muted small">Up to {MAX_PHOTOS}. Location data is removed from every photo.</span>
        {mine?.photos?.length > 0 && !files.length && (
          <label className="muted small"><input type="checkbox" checked={removeOld} onChange={(e) => setRemoveOld(e.target.checked)} /> Remove my current {mine.photos.length} photo{mine.photos.length > 1 ? 's' : ''}</label>
        )}
        <div className="thumbs">
          {previews.map((u, i) => (
            <span key={u} className="thumb"><img src={u} alt={`Selected photo ${i + 1}`} /><button type="button" aria-label={`Remove photo ${i + 1}`} onClick={() => setFiles((f) => f.filter((_, j) => j !== i))}>✕</button></span>
          ))}
        </div>
      </div>
      {err && <p className="notice" role="alert">{err}</p>}
      <div className="review-actions">
        <button className="btn btn-light" disabled={busy}>{busy ? 'Posting…' : mine ? 'Save changes' : 'Post review'}</button>
        {onCancel && <button type="button" className="pill" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  )
}

export default function Reviews({ place, placeName }) {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const [sort, setSort] = useState('helpful')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [editing, setEditing] = useState(false)
  const [zoom, setZoom] = useState(null)
  const [reporting, setReporting] = useState(null)
  const [note, setNote] = useState('')
  const reason = useRef('')

  const load = useCallback(() => {
    api(`/api/destinations/${place}/reviews?sort=${sort}&limit=20`).then((d) => { setData(d); setErr('') }).catch((e) => setErr(e.message))
  }, [place, sort, user?.email])                                                           // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [load])

  async function vote(r) {
    try {
      const j = await api(`/api/reviews/${r.id}/helpful`, { method: 'POST' })
      setData((d) => ({ ...d, reviews: d.reviews.map((x) => (x.id === r.id ? { ...x, helpful: j.helpful, voted: j.voted } : x)) }))
    } catch (e) {
      setNote(e.message)
    }
  }

  async function sendReport(r) {
    try {
      const j = await api(`/api/reviews/${r.id}/report`, { method: 'POST', body: { reason: reason.current } })
      setReporting(null)
      setNote(j.hidden ? 'Thanks. That review has been hidden pending a check.' : 'Thanks. Your report was sent.')
      if (j.hidden) load()
    } catch (e) {
      setNote(e.message)
    }
  }

  async function remove() {
    if (!window.confirm('Delete your review?')) return
    try {
      await api(`/api/destinations/${place}/reviews/mine`, { method: 'DELETE' })
      setEditing(false)
      load()
    } catch (e) {
      setNote(e.message)
    }
  }

  if (err) return <p className="muted-l">Reviews aren't available right now.</p>
  if (!data) return <p className="muted-l">Loading reviews…</p>
  const s = data.summary
  const max = Math.max(1, ...Object.values(s.distribution))

  return (
    <div className="reviews">
      <div className="rev-summary">
        <div className="rev-score">
          <strong>{s.average ?? '–'}</strong>
          {s.average && <Stars value={s.average} />}
          <span className="muted small">{s.count} review{s.count === 1 ? '' : 's'}</span>
        </div>
        <ul className="rev-dist" aria-label="Rating breakdown">
          {[5, 4, 3, 2, 1].map((n) => (
            <li key={n}><span>{n}★</span><span className="bar"><i style={{ width: `${(s.distribution[n] / max) * 100}%` }} /></span><span className="muted small">{s.distribution[n]}</span></li>
          ))}
        </ul>
        {s.count > 0 && <p className="muted small rev-bayes">Ranked fairly: a handful of reviews is weighed against the overall average, so one 5-star rating can't top a well-reviewed place.</p>}
      </div>

      {note && <p className="notice soft" role="status">{note}</p>}

      <div className="rev-write">
        {!user && <p className="muted-l"><Link to="/login" state={{ next: pathname }}>Sign in</Link> to write a review.</p>}
        {user && data.reason && !data.can_edit && <p className="muted-l">{data.reason}</p>}
        {user && data.can_review && !editing && <button className="btn btn-light" onClick={() => setEditing(true)}>Write a review</button>}
        {editing && <Editor place={place} mine={data.mine} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); setNote('Thanks. Your review is live.'); load() }} />}
      </div>

      {data.mine && !editing && (
        <div className="rev-mine">
          <span className="chip">Your review{data.mine.status === 'flagged' ? ' · under review' : ''}</span>
          <button className="pill" onClick={() => setEditing(true)}>Edit</button>
          <button className="pill" onClick={remove}>Delete</button>
        </div>
      )}

      {s.count > 0 && (
        <div className="rev-sort"><label className="muted small">Sort <select value={sort} onChange={(e) => setSort(e.target.value)}><option value="helpful">Most helpful</option><option value="newest">Newest</option></select></label></div>
      )}
      {s.count === 0 && <p className="muted-l">No reviews of {placeName} yet. Be the first once you've been.</p>}

      <ul className="rev-list">
        {data.reviews.map((r) => (
          <li key={r.id} className="rev">
            <header>
              <Stars value={r.rating} size="sm" />
              {r.title && <strong>{r.title}</strong>}
              <span className="badge on verified">Verified traveller</span>
            </header>
            <p>{r.text}</p>
            {r.photos.length > 0 && (
              <div className="rev-photos">{r.photos.map((p, i) => <button key={p} type="button" onClick={() => setZoom(photoUrl(p))} aria-label={`Open photo ${i + 1}`}><img src={photoUrl(p)} alt={`Traveller photo ${i + 1} of ${placeName}`} loading="lazy" /></button>)}</div>
            )}
            <footer>
              <span className="muted small">{r.name} · {dateLabel(r.created.slice(0, 10))}{r.edited ? ' · edited' : ''}</span>
              <span className="rev-btns">
                {!r.mine && user && <button type="button" className={'chipbtn' + (r.voted ? ' on' : '')} aria-pressed={r.voted} onClick={() => vote(r)}>Helpful · {r.helpful}</button>}
                {!r.mine && !user && <span className="muted small">{r.helpful} found this helpful</span>}
                {r.mine && <span className="muted small">{r.helpful} found this helpful</span>}
                {!r.mine && user && (reporting === r.id
                  ? <span className="report-box"><select defaultValue="" onChange={(e) => { reason.current = e.target.value }}><option value="">Reason…</option><option>Spam or advertising</option><option>Offensive</option><option>Not about this place</option><option>Fake review</option></select>
                      <button type="button" className="chipbtn" onClick={() => sendReport(r)}>Send</button><button type="button" className="chipbtn" onClick={() => setReporting(null)}>Cancel</button></span>
                  : <button type="button" className="chipbtn" onClick={() => { reason.current = ''; setReporting(r.id) }}>Report</button>)}
              </span>
            </footer>
          </li>
        ))}
      </ul>

      <AnimatePresence>
        {zoom && (
          <Overlay onClose={() => setZoom(null)}>
            <motion.div className="lightbox" initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ opacity: 0 }}>
              <img src={zoom} alt="Traveller photo, enlarged" />
              <button type="button" className="x" onClick={() => setZoom(null)} aria-label="Close photo">✕</button>
            </motion.div>
          </Overlay>
        )}
      </AnimatePresence>
    </div>
  )
}
