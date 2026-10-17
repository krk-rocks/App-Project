"""HTTP routes for the trip planner."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from flask import Blueprint, jsonify, request

import activities
import clock
import intent
import llm
import narration
import planner

bp = Blueprint("planner", __name__)
_hits = {}                      # (ip, bucket) -> [timestamps]
_rain_cache = {}                # place -> (monotonic time, {iso date: rain %})
RAIN_TTL, FORECAST_DAYS = 600, 5


@bp.errorhandler(planner.PlanError)
def _plan_error(e):
    return jsonify({"error": str(e)}), 400


def _limited(bucket, limit, window=600):
    """A tiny per-IP rate limit. In memory, so it resets on restart, which is fine for a courtesy limit."""
    now = time.monotonic()
    key = (request.remote_addr or "?", bucket)
    recent = [t for t in _hits.get(key, []) if now - t < window]
    if len(recent) >= limit:
        _hits[key] = recent
        return True
    _hits[key] = recent + [now]
    return False


def _body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _rain_for(place):
    hit = _rain_cache.get(place)
    if hit and time.monotonic() - hit[0] < RAIN_TTL:
        return hit[1]
    import app as _app                                    # late import: app imports this module
    j, _ = _app.fetch_forecast(_app.BY_ID[place])
    out = {}
    if j:
        try:
            out = dict(zip(j["daily"]["time"], j["daily"]["precipitation_probability_max"]))
        except (KeyError, TypeError):
            out = {}
    _rain_cache[place] = (time.monotonic(), out)
    return out


def rain_hints(start_date):
    """Rain chances for every town, but only when the trip starts inside the forecast window and the weather
    service answers quickly. The planner works the same without them."""
    if os.environ.get("PLANNER_WEATHER", "1") == "0":
        return {}
    d = date.fromisoformat(start_date)
    if not 0 <= (d - clock.today()).days < FORECAST_DAYS:
        return {}
    try:
        with ThreadPoolExecutor(5) as pool:
            rows = list(pool.map(_rain_for, planner.PLACES, timeout=6))
    except Exception:
        return {}
    return {(p, day): prob for p, row in zip(planner.PLACES, rows) for day, prob in row.items() if prob is not None}


def _request_from(body):
    """Accept {"request": {...}} or {"text": "..."} (or both: explicit fields win over what the sentence said)."""
    explicit = body.get("request") if isinstance(body.get("request"), dict) else {}
    text = body.get("text")
    if isinstance(text, str) and text.strip():
        parsed = intent.parse(text)
        return {**parsed["request"], **explicit}, parsed["understood"]
    return explicit, []


@bp.get("/api/planner/options")
def options():
    return jsonify({"places": [{"id": p, "name": planner.NAMES[p]} for p in planner.PLACES], "interests": list(activities.INTERESTS),
                    "paces": list(planner.PACES), "comforts": list(planner.COMFORTS), "max_days": planner.MAX_DAYS, "llm": llm.status()})


@bp.post("/api/planner/parse")
def parse():
    if _limited("parse", 60):
        return jsonify({"error": "Too many requests. Try again in a few minutes."}), 429
    text = _body().get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Describe your trip in a sentence."}), 400
    text = text[:600]
    parsed = intent.parse(text)
    merged, source = llm.refine_request(text, parsed["request"])
    return jsonify({"request": merged, "understood": parsed["understood"], "source": source})


@bp.post("/api/planner/plan")
def make_plan():
    if _limited("plan", 60):
        return jsonify({"error": "Too many requests. Try again in a few minutes."}), 429
    raw, understood = _request_from(_body())
    n = planner.normalize(raw)
    plan = planner.plan(n, rain_hints(n["start_date"]))
    return jsonify({"plan": plan, "narration": narration.template(plan), "understood": understood, "llm": llm.status()})


@bp.post("/api/planner/narrate")
def narrate():
    """Rewrite the descriptions with the local model. The plan is rebuilt from the REQUEST on the server, so
    nothing the browser sends reaches the model's prompt except validated planner fields."""
    if _limited("narrate", 8):
        return jsonify({"error": "Too many requests. Try again in a few minutes."}), 429
    raw, _ = _request_from(_body())
    n = planner.normalize(raw)
    plan = planner.plan(n, rain_hints(n["start_date"]))
    try:
        return jsonify({"narration": llm.narrate(plan)})
    except llm.LlmBusy:
        return jsonify({"error": "The model is busy writing another trip. Try again in a minute."}), 429
    except llm.LlmUnavailable as e:
        return jsonify({"error": str(e), "narration": narration.template(plan)}), 503
