// Weather fetched straight from Open-Meteo by the visitor's browser.
//
// The API server used to be the only caller, but free hosts share one outgoing IP among many
// apps and Open-Meteo rate-limits it, which left every page showing "Weather is unavailable".
// Each visitor has their own IP, so calling from the browser avoids that. The result has the
// same shape as the backend's /api/destinations/<id>/weather, so either source can feed the page.

const WMO = {
  0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Rime fog',
  51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
  71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 80: 'Rain showers', 81: 'Rain showers', 82: 'Violent showers',
  95: 'Thunderstorm', 96: 'Thunderstorm with hail', 99: 'Thunderstorm with hail',
}

const TTL = 10 * 60 * 1000
const cache = new Map()   // "lat,lon" -> { at, data }

export async function fetchWeather(lat, lon) {
  const key = `${lat},${lon}`
  const hit = cache.get(key)
  if (hit && Date.now() - hit.at < TTL) return hit.data

  const q = new URLSearchParams({
    latitude: lat, longitude: lon, timezone: 'auto', forecast_days: 5,
    current: 'temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day',
    daily: 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
  })
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), 8000)
  try {
    const r = await fetch(`https://api.open-meteo.com/v1/forecast?${q}`, { signal: ctl.signal })
    if (!r.ok) throw new Error(`Open-Meteo responded ${r.status}`)
    const j = await r.json()
    const cur = j.current
    const day = j.daily
    const data = {
      timezone: j.timezone,
      current: {
        temp: cur.temperature_2m, feels_like: cur.apparent_temperature, humidity: cur.relative_humidity_2m,
        wind: cur.wind_speed_10m, code: cur.weather_code, condition: WMO[cur.weather_code] || '—',
        is_day: !!cur.is_day, local_time: cur.time,
      },
      forecast: day.time.map((date, i) => ({
        date, max: day.temperature_2m_max[i], min: day.temperature_2m_min[i],
        rain: day.precipitation_probability_max[i], condition: WMO[day.weather_code[i]] || '—', code: day.weather_code[i],
      })),
    }
    cache.set(key, { at: Date.now(), data })
    return data
  } finally {
    clearTimeout(timer)
  }
}
