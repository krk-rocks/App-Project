"""HTTP routes for bookings, orders, the wallet and the payment webhook."""

from flask import Blueprint, g, jsonify, request

import auth
import bookings
import payments
import store
import transport

bp = Blueprint("money", __name__)


@bp.errorhandler(payments.PaymentError)
def _payment_error(e):
    return jsonify({"error": e.message}), e.status


def _json():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _idem():
    key = (request.headers.get("Idempotency-Key") or "").strip()
    return key[:80] or None


def _wallet(email):
    return payments.balance(email)


# ------------------------------------------------------------------ bookings

@bp.post("/api/bookings")
@auth.require_auth
def create_booking():
    result, err = transport.book(g.user, _json(), _idem())
    if err:
        return jsonify({"error": err}), 400
    rec, order = result
    return jsonify({"booking": bookings.view(rec), "order": payments.public_order(order), "wallet_balance": _wallet(g.user["email"])}), 201


@bp.get("/api/bookings")
@auth.require_auth
def my_bookings():
    return jsonify(bookings.for_user(g.user["email"]))


@bp.get("/api/bookings/<booking_id>")
@auth.require_auth
def one_booking(booking_id):
    with store.TX:
        bookings.sweep()
        b = bookings.find(booking_id, g.user["email"])
        if not b:
            raise payments.PaymentError("Booking not found.", 404)
        return jsonify(bookings.view(b))


@bp.get("/api/bookings/<booking_id>/cancel-quote")
@auth.require_auth
def cancel_quote(booking_id):
    return jsonify(bookings.cancel_quote(g.user["email"], booking_id))


@bp.post("/api/bookings/<booking_id>/cancel")
@auth.require_auth
def cancel_booking(booking_id):
    b = bookings.cancel(g.user["email"], booking_id)
    return jsonify({"booking": b, "wallet_balance": _wallet(g.user["email"])})


# ------------------------------------------------------------------ orders and wallet

@bp.get("/api/orders/<order_id>")
@auth.require_auth
def one_order(order_id):
    with store.TX:
        bookings.sweep()
        return jsonify(payments.public_order(payments.get_order(g.user["email"], order_id)))


@bp.post("/api/orders/<order_id>/pay")
@auth.require_auth
def pay_order(order_id):
    body = _json()
    order, result = payments.pay(g.user["email"], order_id, body.get("method"), body)
    out = {"order": payments.public_order(order), "result": result, "wallet_balance": _wallet(g.user["email"])}
    if order["purpose"] == "booking":
        b = bookings.find(order["ref"])
        out["booking"] = bookings.view(b) if b else None
    return jsonify(out)


@bp.get("/api/wallet")
@auth.require_auth
def wallet():
    email = g.user["email"]
    return jsonify({"balance": _wallet(email), "ledger": payments.ledger_for(email),
                    "limits": {"min": payments.TOPUP_MIN, "max": payments.TOPUP_MAX}})


@bp.post("/api/wallet/topup")
@auth.require_auth
def topup():
    order = payments.start_topup(g.user["email"], _json().get("amount"), _idem())
    store.commit()
    return jsonify({"order": payments.public_order(order)}), 201


@bp.post("/api/payments/webhook")
def webhook():
    """Where a real gateway would POST. The body must be the raw bytes the signature was computed over."""
    status, body = payments.handle_webhook(request.get_data(), request.headers.get("X-Signature", ""))
    return jsonify(body), status
