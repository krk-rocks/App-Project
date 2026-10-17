"""HTTP routes for group trips."""

from flask import Blueprint, g, jsonify, request

import auth
import trips

bp = Blueprint("trips", __name__)


@bp.errorhandler(trips.TripError)
def _trip_error(e):
    return jsonify({"error": e.message, **e.extra}), e.status


def _json():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@bp.get("/api/trips")
@auth.require_auth
def my_trips():
    return jsonify(trips.mine(g.user))


@bp.post("/api/trips")
@auth.require_auth
def create_trip():
    b = _json()
    return jsonify(trips.create(g.user, b.get("name"), b.get("start_date"))), 201


@bp.post("/api/trips/join")
@auth.require_auth
def join_trip():
    return jsonify(trips.join(g.user, _json().get("code")))


@bp.get("/api/trips/<trip_id>")
@auth.require_auth
def get_trip(trip_id):
    since = request.args.get("since", type=int)
    return jsonify(trips.get(g.user, trip_id, since))


@bp.delete("/api/trips/<trip_id>")
@auth.require_auth
def delete_trip(trip_id):
    return jsonify(trips.delete_trip(g.user, trip_id))


@bp.post("/api/trips/<trip_id>/code")
@auth.require_auth
def trip_code(trip_id):
    return jsonify(trips.set_code(g.user, trip_id, _json().get("action")))


@bp.delete("/api/trips/<trip_id>/members/<member_id>")
@auth.require_auth
def remove_member(trip_id, member_id):
    return jsonify(trips.remove_member(g.user, trip_id, member_id))


# ---- itinerary
@bp.post("/api/trips/<trip_id>/items")
@auth.require_auth
def add_item(trip_id):
    return jsonify(trips.add_item(g.user, trip_id, _json())), 201


@bp.post("/api/trips/<trip_id>/items/import")
@auth.require_auth
def import_items(trip_id):
    return jsonify(trips.import_items(g.user, trip_id, _json().get("items"))), 201


@bp.patch("/api/trips/<trip_id>/items/<item_id>")
@auth.require_auth
def edit_item(trip_id, item_id):
    return jsonify(trips.edit_item(g.user, trip_id, item_id, _json()))


@bp.delete("/api/trips/<trip_id>/items/<item_id>")
@auth.require_auth
def delete_item(trip_id, item_id):
    return jsonify(trips.delete_item(g.user, trip_id, item_id))


# ---- polls
@bp.post("/api/trips/<trip_id>/polls")
@auth.require_auth
def add_poll(trip_id):
    b = _json()
    return jsonify(trips.add_poll(g.user, trip_id, b.get("question"), b.get("options"))), 201


@bp.post("/api/trips/<trip_id>/polls/<poll_id>/vote")
@auth.require_auth
def vote(trip_id, poll_id):
    return jsonify(trips.vote(g.user, trip_id, poll_id, _json().get("option_id")))


@bp.post("/api/trips/<trip_id>/polls/<poll_id>/close")
@auth.require_auth
def close_poll(trip_id, poll_id):
    return jsonify(trips.close_poll(g.user, trip_id, poll_id))


# ---- expenses
@bp.post("/api/trips/<trip_id>/expenses")
@auth.require_auth
def add_expense(trip_id):
    return jsonify(trips.add_expense(g.user, trip_id, _json())), 201


@bp.patch("/api/trips/<trip_id>/expenses/<expense_id>")
@auth.require_auth
def edit_expense(trip_id, expense_id):
    return jsonify(trips.edit_expense(g.user, trip_id, expense_id, _json()))


@bp.delete("/api/trips/<trip_id>/expenses/<expense_id>")
@auth.require_auth
def delete_expense(trip_id, expense_id):
    return jsonify(trips.delete_expense(g.user, trip_id, expense_id))


@bp.post("/api/trips/<trip_id>/settle")
@auth.require_auth
def settle(trip_id):
    b = _json()
    return jsonify(trips.settle(g.user, trip_id, b.get("from"), b.get("to"), b.get("amount"))), 201
