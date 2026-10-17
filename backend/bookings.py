"""Booking lifecycle shared by trains, buses and hotels.

    PENDING_PAYMENT --paid--> CONFIRMED (or RAC) --cancel--> CANCELLED
          |--(hold runs out)--> EXPIRED

A booking is created PENDING_PAYMENT with its seats or rooms held for HOLD_SECONDS and an order to pay.
Paying confirms it; letting the hold lapse releases everything; cancelling a confirmed booking refunds it to
the wallet minus the cancellation charge for how close the departure is.

Cancellation charges are MODELLED on typical Indian rail, bus and hotel rules. Real rules differ by operator.
"""

import math
import os
import secrets
from datetime import datetime

import clock
import payments
import store

HOLD_SECONDS = int(os.environ.get("HOLD_SECONDS", "600"))
PENDING, CONFIRMED, RAC, CANCELLED, EXPIRED = "PENDING_PAYMENT", "CONFIRMED", "RAC", "CANCELLED", "EXPIRED"
LIVE = (CONFIRMED, RAC)

RAIL_FLAT_PER_PASSENGER = {"1A": 240, "2A": 200, "3A": 180, "CC": 180, "SL": 120, "2S": 60}   # rupees


def _epoch():
    return clock.now().timestamp()


def find(booking_id, email=None):
    for b in store.read()["bookings"]:
        if b["id"] == booking_id and (email is None or b["user"] == email):
            return b
    return None


def find_idem(email, idem):
    if not idem:
        return None
    for b in store.read()["bookings"]:
        if b["user"] == email and b.get("idem") == idem:
            return b
    return None


def view(b):
    out = dict(b)
    out.pop("hold", None)
    out["hold_seconds_left"] = max(0, int(b["hold_expires"] - _epoch())) if b["status"] == PENDING and b.get("hold_expires") else 0
    return out


# ------------------------------------------------------------------ create / confirm / release

def add_pending(user, rec, idem=None):
    """Caller holds store.TX and has already reserved the inventory described by rec['hold']."""
    now = _epoch()
    rec.update({"status": PENDING, "hold_expires": now + HOLD_SECONDS, "idem": idem,
                "amount_paise": rec["total"] * 100, "booked_at": clock.now().isoformat(timespec="seconds")})
    order = payments.create_order(user["email"], "booking", rec["id"], rec["amount_paise"], rec["hold_expires"], idem)
    rec["order_id"] = order["id"]
    store.read()["bookings"].append(rec)
    store.commit()
    return rec, order


def _reference(kind):
    if kind == "train":
        return {"pnr": str(secrets.randbelow(9_000_000_000) + 1_000_000_000)}
    if kind == "bus":
        return {"ticket": "TN" + str(secrets.randbelow(900_000) + 100_000)}
    return {"confirmation": "EH" + str(secrets.randbelow(900_000) + 100_000)}


def on_paid(order):
    """payments calls this when a booking's order is paid. False means the hold is gone: the money is refunded."""
    b = find(order["ref"])
    if not b or b["status"] != PENDING:
        return False
    b.update(_reference(b["kind"]))
    b["status"], b["paid_at"] = b.get("final_status", CONFIRMED), clock.now().isoformat(timespec="seconds")
    return True


payments.register("booking", on_paid)


def release(b):
    """Give a booking's seats back. Rooms need nothing: hotel availability is counted from live bookings."""
    h, db = b.get("hold") or {}, store.read()
    if h.get("type") == "train":
        db["held"][h["key"]] = max(0, db["held"].get(h["key"], 0) - h["n"])
    elif h.get("type") == "bus":
        db["held_seats"][h["key"]] = [s for s in db["held_seats"].get(h["key"], []) if s not in h["seats"]]


def _expire_pending(now):
    changed = False
    for b in store.read()["bookings"]:
        if b["status"] == PENDING and b.get("hold_expires") and b["hold_expires"] <= now:
            b["status"] = EXPIRED
            release(b)
            changed = True
    return changed


payments.SWEEPERS.append(_expire_pending)


def sweep():
    payments.sweep()


def for_user(email):
    with store.TX:
        sweep()
        rows = [view(b) for b in store.read()["bookings"] if b["user"] == email]
    rows.sort(key=lambda b: b["booked_at"], reverse=True)
    return rows


# ------------------------------------------------------------------ cancellation

def departure(b):
    """When the journey or stay starts, as an aware IST datetime."""
    if b["kind"] == "hotel":
        hm, day = "14:00", b["check_in"]
    else:
        hm, day = (b.get("depart") or "00:00"), b["date"]
    h, m = (int(x) for x in hm.split(":"))
    return datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=clock.IST)


def _charge(total, charge):
    charge = max(0, min(total, int(math.ceil(charge))))
    return charge, total - charge


def policy(b, now=None):
    """{cancellable, hours_before, charge, refund, tier, tiers, note}, all money in paise."""
    now = now or clock.now()
    total = b.get("amount_paise") or b["total"] * 100          # bookings made before payments existed have no paise amount
    hours = (departure(b) - now).total_seconds() / 3600
    out = {"hours_before": round(hours, 1), "total": total}

    if b["kind"] == "train":
        tiers = [("48 hours or more before", "A flat charge per passenger"), ("12 to 48 hours before", "25% of the fare (at least the flat charge)"),
                 ("4 to 12 hours before", "50% of the fare (at least the flat charge)"), ("Less than 4 hours before", "No refund")]
        flat = RAIL_FLAT_PER_PASSENGER.get(b.get("cls"), 120) * 100 * len(b["passengers"])
        if b.get("quota") == "tatkal":
            (charge, refund), tier = _charge(total, total), "Tatkal tickets are not refundable"
        elif hours >= 48:
            (charge, refund), tier = _charge(total, flat), tiers[0][0]
        elif hours >= 12:
            (charge, refund), tier = _charge(total, max(total * 0.25, flat)), tiers[1][0]
        elif hours >= 4:
            (charge, refund), tier = _charge(total, max(total * 0.5, flat)), tiers[2][0]
        else:
            (charge, refund), tier = _charge(total, total), tiers[3][0]
    elif b["kind"] == "bus":
        tiers = [("24 hours or more before", "10% of the fare"), ("6 to 24 hours before", "50% of the fare"), ("Less than 6 hours before", "No refund")]
        if hours >= 24:
            (charge, refund), tier = _charge(total, total * 0.10), tiers[0][0]
        elif hours >= 6:
            (charge, refund), tier = _charge(total, total * 0.50), tiers[1][0]
        else:
            (charge, refund), tier = _charge(total, total), tiers[2][0]
    else:
        tiers = [("72 hours or more before check-in", "Free cancellation"), ("24 to 72 hours before", "One night is charged"),
                 ("Less than 24 hours before", "Non-refundable")]
        one_night = total // max(1, b["nights"])
        if hours >= 72:
            (charge, refund), tier = _charge(total, 0), tiers[0][0]
        elif hours >= 24:
            (charge, refund), tier = _charge(total, one_night), tiers[1][0]
        else:
            (charge, refund), tier = _charge(total, total), tiers[2][0]

    out.update({"cancellable": hours > 0, "charge": charge, "refund": refund, "tier": tier,
                "tiers": [{"when": w, "rule": r} for w, r in tiers],
                "note": "Charges are modelled on typical rules; real operators differ." if hours > 0 else "This has already started."})
    return out


def cancel_quote(email, booking_id):
    with store.TX:
        sweep()
        b = find(booking_id, email)
        if not b:
            raise payments.PaymentError("Booking not found.", 404)
        if b["status"] == PENDING:
            return {"cancellable": True, "pending": True, "charge": 0, "refund": 0, "total": b["amount_paise"], "tiers": [],
                    "tier": "Not paid yet", "note": "Cancelling releases your hold. Nothing was charged."}
        if b["status"] not in LIVE:
            raise payments.PaymentError(f"This booking is already {b['status'].lower()}.", 409)
        return policy(b)


def cancel(email, booking_id):
    with store.TX:
        sweep()
        b = find(booking_id, email)
        if not b:
            raise payments.PaymentError("Booking not found.", 404)
        if b["status"] == PENDING:
            b["status"] = CANCELLED
            release(b)
            o = store.read()["orders"].get(b.get("order_id"))
            if o and o["status"] == "CREATED":
                o["status"] = "CANCELLED"
            store.commit()
            return view(b)
        if b["status"] not in LIVE:
            raise payments.PaymentError(f"This booking is already {b['status'].lower()}.", 409)
        p = policy(b)
        if not p["cancellable"]:
            raise payments.PaymentError("This journey has already started, so it can't be cancelled.", 409)
        b["status"] = CANCELLED
        release(b)
        b["refund"] = {"amount": p["refund"], "charge": p["charge"], "tier": p["tier"], "at": clock.now().isoformat(timespec="seconds")}
        if p["refund"] > 0:
            payments.refund_to_wallet(email, p["refund"], b.get("order_id"), f"Cancelled {b['kind']} booking", b["id"])
        store.commit()
        return view(b)
