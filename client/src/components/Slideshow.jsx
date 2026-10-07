import { useCallback, useEffect, useRef, useState } from 'react'
import { PHOTOS } from '../data/photos.js'

const INTERVAL = 6000

/* Photo slideshow for a destination's hero. Slides crossfade; only the current photo and the
   next one are mounted, so opening a page does not download all five at once. */
export default function Slideshow({ placeId, placeName }) {
  const slides = PHOTOS[placeId] || []
  const count = slides.length
  const [i, setI] = useState(0)
  const [seen, setSeen] = useState(() => new Set([0, 1]))
  const [userPaused, setUserPaused] = useState(false)
  const [hold, setHold] = useState(false)       // pointer over, or focus inside
  const [hidden, setHidden] = useState(false)   // tab in the background
  const swipe = useRef(null)
  const reduceMotion = useRef(
    typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
  )

  const playing = count > 1 && !userPaused && !hold && !hidden && !reduceMotion.current

  const go = useCallback((n) => setI(((n % count) + count) % count), [count])

  // Keep the next photo ready before it is needed.
  useEffect(() => {
    setSeen((s) => {
      const next = (i + 1) % count
      if (s.has(i) && s.has(next)) return s
      return new Set(s).add(i).add(next)
    })
  }, [i, count])

  // Depends on i, so choosing a slide by hand restarts the countdown.
  useEffect(() => {
    if (!playing) return undefined
    const t = setTimeout(() => setI((c) => (c + 1) % count), INTERVAL)
    return () => clearTimeout(t)
  }, [playing, i, count])

  useEffect(() => {
    const onVis = () => setHidden(document.hidden)
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  if (!count) return null
  const cur = slides[i]

  const onKeyDown = (e) => {
    if (e.key === 'ArrowRight') { go(i + 1); e.preventDefault() }
    if (e.key === 'ArrowLeft') { go(i - 1); e.preventDefault() }
  }
  const onTouchEnd = (e) => {
    if (swipe.current == null) return
    const dx = e.changedTouches[0].clientX - swipe.current
    swipe.current = null
    if (Math.abs(dx) > 45) go(i + (dx < 0 ? 1 : -1))
  }

  return (
    <div
      className="slides"
      role="region"
      aria-roledescription="carousel"
      aria-label={`Photos of ${placeName}`}
      onMouseEnter={() => setHold(true)}
      onMouseLeave={() => setHold(false)}
      onFocus={() => setHold(true)}
      onBlur={() => setHold(false)}
      onKeyDown={onKeyDown}
      onTouchStart={(e) => { swipe.current = e.touches[0].clientX }}
      onTouchEnd={onTouchEnd}
    >
      <div className="slide-stack" aria-live={playing ? 'off' : 'polite'}>
        {slides.map((s, n) => (
          <div
            key={s.src}
            className={'slide' + (n === i ? ' on' : '')}
            role="group"
            aria-roledescription="slide"
            aria-label={`${n + 1} of ${count}`}
            aria-hidden={n !== i}
          >
            {seen.has(n) && (
              <img
                src={s.src}
                alt={n === i ? s.alt : ''}
                width={s.w}
                height={s.h}
                decoding="async"
                fetchpriority={n === 0 ? 'high' : 'auto'}
              />
            )}
          </div>
        ))}
      </div>
      <div className="slides-scrim" />

      <div className="slides-ui">
        <p className="slides-credit">
          Photo: <a href={cur.page} target="_blank" rel="noopener noreferrer">{cur.author}</a>
          {' · '}
          {cur.licenseUrl
            ? <a href={cur.licenseUrl} target="_blank" rel="noopener noreferrer">{cur.license}</a>
            : cur.license}
          {' · Wikimedia Commons'}
        </p>
        {count > 1 && (
          <div className="slides-controls">
            <button type="button" className="sl-btn" aria-label="Previous photo" onClick={() => go(i - 1)}>‹</button>
            <div className="sl-dots">
              {slides.map((s, n) => (
                <button
                  key={s.src}
                  type="button"
                  className="sl-dot"
                  aria-label={`Show photo ${n + 1}`}
                  aria-current={n === i}
                  onClick={() => go(n)}
                />
              ))}
            </div>
            <button type="button" className="sl-btn" aria-label="Next photo" onClick={() => go(i + 1)}>›</button>
            <button
              type="button"
              className="sl-btn"
              aria-label={userPaused ? 'Play slideshow' : 'Pause slideshow'}
              onClick={() => setUserPaused((p) => !p)}
            >
              {userPaused ? '▶' : '❚❚'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
