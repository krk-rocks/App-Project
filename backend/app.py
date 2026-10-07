import os
import time

import requests
from flask import Flask, g, jsonify, request, abort
from flask_cors import CORS

import auth
import store
import transport
from data import DESTINATIONS

app = Flask(__name__)

# In production the frontend is served from another origin, so it must be allowed explicitly.
# CORS_ORIGINS is a comma-separated list; "*" (the default) suits a public read-mostly demo.
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
CORS(app, resources={r"/api/*": {"origins": _origins}}, supports_credentials=False)

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


WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_HEADERS = {"User-Agent": "EpicTN/1.0 (+https://github.com/krk-rocks/App-Project)"}


def fetch_forecast(d):
    """One call to Open-Meteo, retried once. Returns (json, None) or (None, reason).

    Free hosts share an outgoing IP that Open-Meteo rate-limits (HTTP 429), so the reason matters:
    it is logged and returned instead of being swallowed.
    """
    reason = "unknown"
    for attempt in range(2):
        try:
            r = requests.get(
                WEATHER_URL,
                params={
                    "latitude": d["lat"], "longitude": d["lon"], "timezone": "auto", "forecast_days": 5,
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                },
                headers=WEATHER_HEADERS, timeout=8,
            )
            if r.status_code == 429 or r.status_code >= 500:
                reason = f"Open-Meteo responded {r.status_code}"
                time.sleep(0.6)
                continue
            r.raise_for_status()
            return r.json(), None
        except requests.RequestException as e:
            reason = f"{type(e).__name__}: {str(e)[:100]}"
    return None, reason


@app.get("/api/destinations/<dest_id>/weather")
def weather(dest_id):
    d = BY_ID.get(dest_id) or abort(404)
    hit = WEATHER_CACHE.get(dest_id)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return jsonify(hit[1])
    j, reason = fetch_forecast(d)
    if j is None:
        app.logger.warning("weather upstream failed for %s: %s", dest_id, reason)
        if hit:  # an old forecast beats none
            return jsonify({**hit[1], "stale": True})
        return jsonify({"error": "Weather service unavailable", "detail": reason}), 502
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


# ------------------------------------------------------------------ accounts

@app.post("/api/auth/register")
def register():
    b = request.get_json(silent=True) or {}
    user, err = auth.register(b.get("email"), b.get("password"), b.get("name"), b.get("phone", ""))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"token": auth.issue_token(user), "user": auth.public(user)}), 201


@app.post("/api/auth/login")
def login():
    b = request.get_json(silent=True) or {}
    user, err = auth.login(b.get("email"), b.get("password"))
    if err:
        return jsonify({"error": err}), 401
    return jsonify({"token": auth.issue_token(user), "user": auth.public(user)})


@app.post("/api/auth/logout")
def logout():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        auth.revoke(header[7:])
    return jsonify({"ok": True})


@app.get("/api/auth/me")
@auth.require_auth
def me():
    return jsonify(auth.public(g.user))


# ------------------------------------------------------------------ getting there

@app.get("/api/transport/hubs")
def hubs():
    """Boarding points near the traveller. lat/lon come from the browser's geolocation."""
    lat, lon = request.args.get("lat", type=float), request.args.get("lon", type=float)
    if lat is None or lon is None:
        rows = [{"code": c, "name": h["name"], "city": h["city"], "rail": h["rail"], "km": None}
                for c, h in transport.HUBS.items()]
        return jsonify({"located": False, "hubs": sorted(rows, key=lambda r: r["city"])})
    near = transport.nearest_hubs(lat, lon, limit=6)
    return jsonify({"located": True, "nearest": near[0], "hubs": near})


@app.get("/api/destinations/<dest_id>/transport")
def transport_options(dest_id):
    """Trains and buses to this destination for one date.

    `from` is either a boarding-point code (MAS, MDU, ...) or the id of another place in the
    app (madurai, kodaikanal, ...). A place with no station of its own uses its railhead for
    trains and its own bus stand for buses.
    """
    d = BY_ID.get(dest_id) or abort(404)
    info = transport.DEST_HUB.get(dest_id, {})
    dest_hub = info.get("hub")
    railhead = info.get("railhead", dest_hub)

    raw = request.args.get("from", "")
    journey = transport.parse_date(request.args.get("date", ""))
    quota = request.args.get("quota", "general")
    if journey is None:
        journey = transport.now_ist().date()

    notes, origin_place = [], None
    if raw in BY_ID:
        if raw == dest_id:
            return jsonify({"error": "Choose two different places."}), 400
        origin_place = raw
        o = transport.DEST_HUB[raw]
        frm, rail_from = o["hub"], o.get("railhead", o["hub"])
        if o.get("note"):
            notes.append(o["note"])
    elif raw in transport.HUBS:
        frm = rail_from = raw
    else:
        return jsonify({"error": "Choose a boarding point."}), 400
    if info.get("note") and info["note"] not in notes:
        notes.append(info["note"])

    trains = []
    if transport.HUBS[rail_from]["rail"] and railhead and transport.HUBS[railhead]["rail"] and rail_from != railhead:
        trains = transport.search_trains(rail_from, railhead, journey, quota)
    buses = transport.search_buses(frm, dest_hub, journey) if dest_hub and frm != dest_hub else []

    return jsonify({
        "destination": {"id": d["id"], "name": d["name"], "hub": dest_hub, "railhead": railhead},
        "from": {"code": frm, "place": origin_place, "name": BY_ID[origin_place]["name"] if origin_place else None,
                 **{k: transport.HUBS[frm][k] for k in ("city", "rail")}, "stop": transport.HUBS[frm]["name"]},
        "date": journey.isoformat(), "quota": quota,
        "tatkal": transport.tatkal_window(journey),
        "rail_note": " ".join(notes) or None,
        "trains": trains,
        "trains_sold_out": bool(trains) and not any(t["any_bookable"] for t in trains),
        "no_rail_link": not trains,
        "buses": buses,
        "today": transport.now_ist().date().isoformat(),
        "server_time_ist": transport.now_ist().strftime("%H:%M"),
    })


# ------------------------------------------------------------------ bookings

@app.post("/api/bookings")
@auth.require_auth
def create_booking():
    rec, err = transport.book(g.user, request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    return jsonify(rec), 201


@app.get("/api/bookings")
@auth.require_auth
def my_bookings():
    return jsonify(transport.bookings_for(g.user["email"]))


@app.post("/api/bookings/<booking_id>/cancel")
@auth.require_auth
def cancel_booking(booking_id):
    rec, err = transport.cancel(g.user["email"], booking_id)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(rec)


@app.get("/api/health")
def health():
    """Platform health checks hit this; it also tells you whether the store is writable."""
    return jsonify({"ok": True, "persistent": store.WRITABLE, "destinations": len(DESTINATIONS)})


if __name__ == "__main__":
    # PORT is injected by Render/Railway/Fly; default matches the Vite dev proxy.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "1") == "1")
