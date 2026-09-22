import time

import requests
from flask import Flask, jsonify, request, abort
from flask_cors import CORS

from data import DESTINATIONS

app = Flask(__name__)
CORS(app)

BY_ID = {d["id"]: d for d in DESTINATIONS}
WEATHER_CACHE = {}
CACHE_SECONDS = 600

WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def summary(d):
    return {k: d[k] for k in ("id", "name", "country", "region", "category", "tagline", "hue", "lat", "lon")}


@app.get("/api/destinations")
def list_destinations():
    q = request.args.get("q", "").strip().lower()
    cat = request.args.get("category", "").strip().lower()
    items = [
        d for d in DESTINATIONS
        if (not q or q in (d["name"] + d["country"] + d["region"] + d["tagline"]).lower())
        and (not cat or cat == d["category"].lower())
    ]
    return jsonify([summary(d) for d in items])


@app.get("/api/categories")
def categories():
    return jsonify(sorted({d["category"] for d in DESTINATIONS}))


@app.get("/api/destinations/<dest_id>")
def destination(dest_id):
    # Open/closed is computed in the client against the destination's local time from the weather API.
    return jsonify(BY_ID.get(dest_id) or abort(404))


@app.get("/api/destinations/<dest_id>/weather")
def weather(dest_id):
    d = BY_ID.get(dest_id) or abort(404)
    hit = WEATHER_CACHE.get(dest_id)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return jsonify(hit[1])
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": d["lat"], "longitude": d["lon"], "timezone": "auto", "forecast_days": 5,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            },
            timeout=8,
        )
        r.raise_for_status()
        j = r.json()
    except requests.RequestException:
        return jsonify({"error": "Weather service unavailable"}), 502
    cur, day = j["current"], j["daily"]
    out = {
        "timezone": j.get("timezone"),
        "current": {
            "temp": cur["temperature_2m"], "feels_like": cur["apparent_temperature"],
            "humidity": cur["relative_humidity_2m"], "wind": cur["wind_speed_10m"],
            "code": cur["weather_code"], "condition": WMO.get(cur["weather_code"], "—"), "is_day": bool(cur["is_day"]),
            "local_time": cur["time"],
        },
        "forecast": [
            {"date": day["time"][i], "max": day["temperature_2m_max"][i], "min": day["temperature_2m_min"][i],
             "rain": day["precipitation_probability_max"][i], "condition": WMO.get(day["weather_code"][i], "—"),
             "code": day["weather_code"][i]}
            for i in range(len(day["time"]))
        ],
    }
    WEATHER_CACHE[dest_id] = (time.time(), out)
    return jsonify(out)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
