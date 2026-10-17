"""HTTP routes for hotels and the crowd forecast."""

from datetime import date

from flask import Blueprint, g, jsonify, request

import auth
import bookings
import clock
import crowd
import hotels
import payments

bp = Blueprint("stay", __name__)


@bp.errorhandler(hotels.HotelError)
def _hotel_error(e):
    return jsonify({"error": e.message}), e.status


def _int(name, default):
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        raise hotels.HotelError(f"{name} must be a whole number.")


@bp.get("/api/destinations/<dest_id>/hotels")
def hotel_search(dest_id):
    return jsonify(hotels.search(dest_id, request.args.get("check_in"), request.args.get("check_out"),
                                 _int("guests", 2), _int("rooms", 1)))


@bp.post("/api/hotels/book")
@auth.require_auth
def hotel_book():
    body = request.get_json(silent=True)
    key = (request.headers.get("Idempotency-Key") or "").strip()[:80] or None
    rec, order = hotels.book(g.user, body if isinstance(body, dict) else {}, key)
    return jsonify({"booking": bookings.view(rec), "order": payments.public_order(order),
                    "wallet_balance": payments.balance(g.user["email"])}), 201


@bp.get("/api/destinations/<dest_id>/crowd")
def crowd_forecast(dest_id):
    if dest_id not in crowd.BY_ID:
        return jsonify({"error": "Unknown destination."}), 404
    try:
        start = clock.today() if not request.args.get("from") else date.fromisoformat(request.args["from"])
    except ValueError:
        return jsonify({"error": "from must be YYYY-MM-DD."}), 400
    days = max(1, min(120, _int("days", 60)))
    rows = crowd.forecast(dest_id, start, days)
    return jsonify({"destination": dest_id, "from": start.isoformat(), "days": rows,
                    "note": "A guide to relative busyness built from weekends, holidays, festival months and season. "
                            "Lunar festival dates move each year, so festival seasons are approximate."})
