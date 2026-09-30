const ICON = (c, day = true) => {
  if (c === 0 || c === 1) return day ? '☀️' : '🌙'
  if (c === 2) return '⛅'
  if (c === 3) return '☁️'
  if (c === 45 || c === 48) return '🌫️'
  if (c >= 51 && c <= 65) return '🌧️'
  if (c >= 71 && c <= 77) return '❄️'
  if (c >= 80 && c <= 82) return '🌦️'
  if (c >= 95) return '⛈️'
  return '🌡️'
}

export default function Weather({ data, error }) {
  if (error) return <p>Weather is unavailable right now.</p>
  if (!data) return <p>Loading forecast…</p>
  const c = data.current
  return (
    <div className="weather">
      <div className="w-now">
        <span className="w-emoji">{ICON(c.code, c.is_day)}</span>
        <div><div className="w-temp">{Math.round(c.temp)}°C</div><div>{c.condition}</div></div>
      </div>
      <div className="w-stats">
        <span>Feels {Math.round(c.feels_like)}°</span><span>Humidity {c.humidity}%</span><span>Wind {Math.round(c.wind)} km/h</span>
      </div>
      <ul className="w-days">
        {data.forecast.map((f) => (
          <li key={f.date}>
            <span>{new Date(f.date + 'T00:00').toLocaleDateString(undefined, { weekday: 'short' })}</span>
            <span>{ICON(f.code)}</span>
            <span>{Math.round(f.max)}° / {Math.round(f.min)}°</span>
            <span className="rain">💧{f.rain ?? 0}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
