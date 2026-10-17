"""Wallet, orders, a mock payment gateway with signed webhooks, and refunds.

A real card payment needs a licensed gateway and live keys, and this project has neither, so the gateway
here is a MOCK. It follows the same shape as a real integration:

    create order -> payment attempt -> gateway sends a signed webhook -> we verify it -> state changes

so moving to Razorpay or Stripe in test mode means replacing the mock section of `pay()` and pointing the
provider's webhook at POST /api/payments/webhook, which already verifies signatures and ignores replays.

No money moves, and no card number is ever stored: the demo accepts only published test numbers, and the
only thing kept from an attempt is the brand and last four digits.

All amounts are integers in paise (1/100 rupee) so sums are exact.
"""

import hashlib
import hmac
import json
import os
import re
import secrets

import clock
import store

# A forged "payment succeeded" webhook is the classic way to get free goods, so the secret is random per
# process unless the host sets one. The in-process mock signs with the same value.
SECRET = (os.environ.get("PAYMENT_WEBHOOK_SECRET") or secrets.token_hex(32)).encode()
TOPUP_MIN, TOPUP_MAX = 100, 50_000       # rupees
TOPUP_ORDER_SECONDS = 30 * 60

# Published-style test instruments: (outcome, error code, message, brand)
TEST_CARDS = {
    "4242424242424242": ("captured", None, None, "Visa"),
    "4111111111111111": ("captured", None, None, "Visa"),
    "5555555555554444": ("captured", None, None, "Mastercard"),
    "4000000000000002": ("failed", "card_declined", "Your card was declined.", "Visa"),
    "4000000000009995": ("failed", "insufficient_funds", "Your card has insufficient funds.", "Visa"),
}
TEST_UPI = {
    "success@epic": ("captured", None, None),
    "fail@epic": ("failed", "upi_declined", "The UPI request was declined."),
}
TEST_HINT = ("This demo takes test instruments only. Cards: 4242 4242 4242 4242 (succeeds), "
             "4000 0000 0000 0002 (declined), 4000 0000 0000 9995 (insufficient funds), any future expiry and any CVV. "
             "UPI: success@epic or fail@epic.")


class PaymentError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


HANDLERS = {}    # order purpose -> fn(order) -> bool (True = applied)
SWEEPERS = []    # fns run before anything reads bookings: fn(now_epoch) -> changed?


def register(purpose, fn):
    HANDLERS[purpose] = fn


def _id(prefix):
    return prefix + secrets.token_hex(8)


def _iso():
    return clock.now().isoformat(timespec="seconds")


def _epoch():
    return clock.now().timestamp()


# ------------------------------------------------------------------ wallet

def balance(email):
    return store.read()["wallets"].get(email, {"balance": 0})["balance"]


def _move(email, delta, kind, ref, note):
    """Apply one signed amount to a wallet and write the ledger line. Caller holds store.TX."""
    db = store.read()
    w = db["wallets"].setdefault(email, {"balance": 0})
    if w["balance"] + delta < 0:
        raise PaymentError("Not enough wallet balance.", 402)
    w["balance"] += delta
    entry = {"id": _id("txn_"), "user": email, "amount": delta, "balance_after": w["balance"],
             "kind": kind, "ref": ref, "note": note, "at": _iso()}
    db["ledger"].append(entry)
    return entry


def wallet_credit(email, paise, kind, ref, note):
    assert paise > 0
    with store.TX:
        e = _move(email, paise, kind, ref, note)
        store.commit()
        return e


def wallet_debit(email, paise, kind, ref, note):
    assert paise > 0
    with store.TX:
        e = _move(email, -paise, kind, ref, note)
        store.commit()
        return e


def ledger_for(email, limit=50):
    rows = [e for e in store.read()["ledger"] if e["user"] == email]
    return rows[-limit:][::-1]


def refund_to_wallet(email, paise, ref, reason, booking_id=None):
    """Money back goes to the wallet instantly; a real integration would reverse the original payment."""
    with store.TX:
        entry = _move(email, paise, "refund", ref, reason)
        store.read()["refunds"].append({"id": _id("rfnd_"), "user": email, "amount": paise, "booking": booking_id,
                                         "order": ref, "reason": reason, "destination": "wallet", "at": _iso()})
        store.commit()
        return entry


# ------------------------------------------------------------------ orders

def create_order(email, purpose, ref, amount, expires=None, idem=None):
    assert isinstance(amount, int) and amount > 0
    with store.TX:
        o = {"id": _id("order_"), "user": email, "purpose": purpose, "ref": ref, "amount": amount, "currency": "INR",
             "status": "CREATED", "created": _iso(), "expires": expires, "attempts": [], "idem": idem}
        store.read()["orders"][o["id"]] = o
        return o


def public_order(o):
    left = None if not o.get("expires") else max(0, int(o["expires"] - _epoch()))
    return {"id": o["id"], "purpose": o["purpose"], "ref": o["ref"], "amount": o["amount"], "currency": o["currency"],
            "status": o["status"], "seconds_left": left,
            "attempts": [{k: a.get(k) for k in ("method", "instrument", "status", "code", "message", "at")} for a in o["attempts"]]}


def get_order(email, order_id):
    o = store.read()["orders"].get(order_id)
    if not o or o["user"] != email:
        raise PaymentError("Order not found.", 404)
    return o


def sweep():
    """Close orders whose time is up and run each module's own expiry (booking holds). Cheap and idempotent,
    so every read or write that depends on holds calls it first."""
    with store.TX:
        now, changed = _epoch(), False
        for o in store.read()["orders"].values():
            if o["status"] == "CREATED" and o.get("expires") and o["expires"] <= now:
                o["status"], changed = "EXPIRED", True
        for fn in SWEEPERS:
            changed = bool(fn(now)) or changed
        if changed:
            store.commit()


def start_topup(email, rupees, idem=None):
    if not isinstance(rupees, int) or isinstance(rupees, bool) or not TOPUP_MIN <= rupees <= TOPUP_MAX:
        raise PaymentError(f"Add between ₹{TOPUP_MIN} and ₹{TOPUP_MAX:,}.")
    with store.TX:
        if idem:
            for o in store.read()["orders"].values():
                if o["user"] == email and o.get("idem") == idem:
                    return o
        o = create_order(email, "topup", None, rupees * 100, _epoch() + TOPUP_ORDER_SECONDS, idem)
        store.commit()
        return o


def _topup_paid(order):
    wallet_credit(order["user"], order["amount"], "topup", order["id"], "Added to wallet")
    return True


register("topup", _topup_paid)


# ------------------------------------------------------------------ test instruments

def _luhn_ok(num):
    total, flip = 0, False
    for ch in reversed(num):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, flip = total + d, not flip
    return total % 10 == 0


def _check_card(card):
    num = re.sub(r"[\s-]", "", str(card.get("number", "")))
    if not num.isdigit() or not 12 <= len(num) <= 19 or not _luhn_ok(num):
        raise PaymentError("Enter a valid card number.")
    m = re.fullmatch(r"(\d{2})\s*/\s*(\d{2})", str(card.get("expiry", "")).strip())
    if not m or not 1 <= int(m.group(1)) <= 12:
        raise PaymentError("Enter the expiry as MM/YY.")
    now = clock.now()
    if (2000 + int(m.group(2)), int(m.group(1))) < (now.year, now.month):
        raise PaymentError("This card has expired.")
    if not re.fullmatch(r"\d{3,4}", str(card.get("cvv", ""))):
        raise PaymentError("Enter the 3 or 4 digit security code.")
    if num not in TEST_CARDS:      # a real card number: refuse it and keep nothing
        raise PaymentError(TEST_HINT)
    return num


def _check_upi(upi):
    vpa = str(upi.get("vpa", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{2,}@[a-z]{2,}", vpa):
        raise PaymentError("Enter a UPI id such as name@bank.")
    if vpa not in TEST_UPI:
        raise PaymentError(TEST_HINT)
    return vpa


# ------------------------------------------------------------------ webhook

def sign(raw):
    return hmac.new(SECRET, raw, hashlib.sha256).hexdigest()


def _paid(order, payment_id, method):
    """An order has been paid: apply its purpose. If the purpose can no longer be honoured (a booking whose
    hold ran out), the money goes straight back to the wallet instead of being kept."""
    order["status"], order["paid_at"], order["payment_id"], order["method"] = "PAID", _iso(), payment_id, method
    if not HANDLERS[order["purpose"]](order):
        order["status"] = "REFUNDED"
        refund_to_wallet(order["user"], order["amount"], order["id"], "Refunded: this booking could no longer be held", order.get("ref"))


def _captured(order, data):
    order["attempts"].append({"id": data["payment_id"], "method": data["method"], "instrument": data.get("instrument"),
                              "status": "captured", "code": None, "message": None, "at": _iso()})
    if order["status"] != "CREATED":
        # arrived after the order was closed, or a second payment for an order already paid
        refund_to_wallet(order["user"], order["amount"], order["id"], "Refunded: payment arrived after the order closed", order.get("ref"))
        return
    _paid(order, data["payment_id"], data["method"])


def handle_webhook(raw, signature):
    """The single entry point a gateway would call. Verifies the HMAC signature, applies each event id at most
    once, and checks the amount against the order, never against anything the browser sent."""
    if not isinstance(signature, str) or not hmac.compare_digest(sign(raw).encode(), signature.encode()):
        return 401, {"error": "Invalid signature."}
    try:
        ev = json.loads(raw)
        data, ev_id, ev_type = ev["data"], ev["id"], ev["type"]
        data["order_id"], data["amount"], data["payment_id"], data["method"]
    except (ValueError, KeyError, TypeError):
        return 400, {"error": "Malformed event."}
    with store.TX:
        db = store.read()
        if ev_id in db["events"]:
            return 200, {"ok": True, "duplicate": True}
        order = db["orders"].get(data["order_id"])
        if not order:
            return 404, {"error": "Unknown order."}
        if data["amount"] != order["amount"]:
            return 400, {"error": "Amount does not match the order."}
        if ev_type == "payment.captured":
            _captured(order, data)
        elif ev_type == "payment.failed":
            err = data.get("error") or {}
            order["attempts"].append({"id": data["payment_id"], "method": data["method"], "instrument": data.get("instrument"),
                                      "status": "failed", "code": err.get("code"), "message": err.get("message"), "at": _iso()})
        else:
            return 400, {"error": "Unsupported event type."}
        db["events"][ev_id] = {"at": _iso(), "type": ev_type, "order": order["id"]}
        store.commit()
    return 200, {"ok": True}


# ------------------------------------------------------------------ paying

def pay(email, order_id, method, details):
    """Returns (order, result). result = {"status": "captured"|"failed", "message"}."""
    with store.TX:
        sweep()
        order = get_order(email, order_id)
        if order["status"] != "CREATED":
            raise PaymentError(f"This order is {order['status'].lower()}.", 409)

        if method == "wallet":
            if order["purpose"] == "topup":
                raise PaymentError("Pick a card or UPI to add money.")
            if balance(email) < order["amount"]:
                raise PaymentError("Not enough wallet balance. Add money first.", 402)
            _move(email, -order["amount"], "payment", order["id"], "Paid from wallet")
            pid = _id("pay_")
            order["attempts"].append({"id": pid, "method": "wallet", "instrument": "Wallet", "status": "captured",
                                      "code": None, "message": None, "at": _iso()})
            _paid(order, pid, "wallet")
            store.commit()
            return order, {"status": "captured", "message": None}

        if method == "card":
            num = _check_card(details.get("card") or {})
            outcome, code, message, brand = TEST_CARDS[num]
            instrument = f"{brand} ending {num[-4:]}"
        elif method == "upi":
            vpa = _check_upi(details.get("upi") or {})
            outcome, code, message = TEST_UPI[vpa]
            instrument = vpa
        else:
            raise PaymentError("Choose a payment method.")

        # --- the mock gateway: decide, then tell us by webhook exactly as a real one would ---
        data = {"order_id": order["id"], "payment_id": _id("pay_"), "amount": order["amount"], "currency": "INR",
                "method": method, "instrument": instrument}
        if outcome == "failed":
            data["error"] = {"code": code, "message": message}
        event = {"id": _id("evt_"), "type": "payment.captured" if outcome == "captured" else "payment.failed",
                 "created": _iso(), "data": data}
        raw = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        status, body = handle_webhook(raw, sign(raw))
        if status != 200:
            raise PaymentError(body.get("error", "Payment could not be processed."), 502)
        return order, {"status": outcome, "message": message}
