"""Hotel and homestay booking: date-range inventory, crowd-aware pricing, cancellation tiers.

THE LISTINGS ARE SAMPLES. They are generated for the ten towns on the site so the booking engine has something
to book; they are not real properties and nothing here talks to any hotel. Names are deliberately generic.

What is real is the hard part: availability is counted PER NIGHT. A stay occupies the nights from check-in up
to, but not including, check-out, so back-to-back stays share a day without colliding, and a room type is
bookable only if every night of the stay has a free room. The check and the hold happen under one lock so two
people cannot both take the last room.
"""

import hashlib
import secrets
from datetime import date, timedelta

import bookings
import clock
import crowd
import store
from data import DESTINATIONS

BY_ID = {d["id"]: d for d in DESTINATIONS}
TAX_RATE = 0.12            # modelled; real hotel tax depends on the room rate
MAX_NIGHTS, MAX_ROOMS, MAX_GUESTS, MAX_ADVANCE_DAYS = 14, 4, 12, 365

CATEGORY_RATE = {"City": 1.15, "Hill Station": 1.10, "Coastal": 1.0, "Heritage": 0.95, "Temple Town": 0.9, "Pilgrimage": 0.85}

# (name suffix by category group, kind, tier, base rupees, amenities, [(room type, max guests, rooms, price x)])
_TIERS = [
    ("Courtyard Homestay", "Homestay", "Budget", 1100,
     ["Free Wi-Fi", "Hot water", "Home-cooked breakfast on request", "Parking"],
     [("Standard Room", 2, 4, 1.0), ("Family Room", 4, 2, 1.6)]),
    ("Residency", "Hotel", "Standard", 2600,
     ["Free Wi-Fi", "Air-conditioned rooms", "Restaurant", "24-hour front desk", "Parking"],
     [("Deluxe Room", 2, 10, 1.0), ("Executive Room", 3, 5, 1.4)]),
    ("Retreat", "Resort", "Premium", 5200,
     ["Free Wi-Fi", "Breakfast included", "Restaurant and bar", "Pickup on request", "Parking"],
     [("Superior Room", 2, 6, 1.0), ("Suite", 4, 2, 2.0)]),
]
_PREMIUM_SUFFIX = {"Hill Station": "Hillside Cottages", "Coastal": "Seaview Resort", "Heritage": "Heritage House",
                   "Temple Town": "Heritage House", "Pilgrimage": "Grand Residency", "City": "Grand Hotel"}


def _jitter(key):
    """A stable +/-8% so listings are not all priced identically."""
    return 0.92 + (int(hashlib.md5(key.encode()).hexdigest()[:6], 16) % 1600) / 10000


def _build():
    out = {}
    for d in DESTINATIONS:
        town = d["name"].split(" (")[0]
        props = []
        for i, (suffix, kind, tier, base, amenities, rooms) in enumerate(_TIERS):
            name = f"{town} {_PREMIUM_SUFFIX[d['category']] if tier == 'Premium' else suffix}"
            pid = f"{d['id']}-{tier.lower()}"
            mult = CATEGORY_RATE[d["category"]] * _jitter(pid)
            props.append({
                "id": pid, "destination": d["id"], "name": name, "kind": kind, "tier": tier, "sample": True,
                "blurb": f"A {tier.lower()} {kind.lower()} in {town}. Sample listing for demonstration.",
                "amenities": amenities,
                "rooms": [{"type": rt, "max_guests": mg, "count": n, "base": int(round(base * mult * pm / 10.0) * 10)}
                          for rt, mg, n, pm in rooms],
            })
        out[d["id"]] = props
    return out


PROPERTIES = _build()
BY_PROPERTY = {p["id"]: p for props in PROPERTIES.values() for p in props}


class HotelError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


# ------------------------------------------------------------------ dates and inventory

def _parse(s, what):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise HotelError(f"Enter a valid {what} date.")


def _stay(check_in, check_out):
    ci, co = _parse(check_in, "check-in"), _parse(check_out, "check-out")
    nights = (co - ci).days
    if nights < 1:
        raise HotelError("Check-out must be after check-in.")
    if nights > MAX_NIGHTS:
        raise HotelError(f"Stays are limited to {MAX_NIGHTS} nights.")
    today = clock.today()
    if ci < today:
        raise HotelError("Check-in can't be in the past.")
    if ci > today + timedelta(days=MAX_ADVANCE_DAYS):
        raise HotelError("Bookings open up to a year ahead.")
    return ci, co, [(ci + timedelta(days=i)) for i in range(nights)]


def nights_between(check_in, check_out):
    ci, co = date.fromisoformat(check_in), date.fromisoformat(check_out)
    return [(ci + timedelta(days=i)).isoformat() for i in range((co - ci).days)]


def _free_rooms(prop_id, room, nights):
    """Rooms of this type free on EVERY night of the stay. Holds count as taken until they lapse."""
    wanted = {n.isoformat(): 0 for n in nights}
    for b in store.read()["bookings"]:
        if b["kind"] != "hotel" or b["hotel_id"] != prop_id or b["room_type"] != room["type"]:
            continue
        if b["status"] not in (bookings.PENDING, *bookings.LIVE):
            continue
        for n in nights_between(b["check_in"], b["check_out"]):
            if n in wanted:
                wanted[n] += b["rooms"]
    return max(0, min(room["count"] - used for used in wanted.values()))


# ------------------------------------------------------------------ pricing

def _round10(x):
    return int(round(x / 10.0) * 10)


def nightly_prices(prop, room, nights):
    """Per-night price: the room's base rate scaled by how busy that night is forecast to be."""
    rows = []
    for n in nights:
        f = crowd.day_forecast(prop["destination"], n)
        rows.append({"date": n.isoformat(), "level": f["level"], "price": _round10(room["base"] * crowd.price_factor(f["level"]))})
    return rows


def quote(prop, room, nights, rooms):
    per_night = nightly_prices(prop, room, nights)
    subtotal = sum(r["price"] for r in per_night) * rooms
    tax = int(round(subtotal * TAX_RATE))
    return {"nightly": per_night, "rooms": rooms, "subtotal": subtotal, "tax": tax, "total": subtotal + tax}


# ------------------------------------------------------------------ search

def search(dest_id, check_in, check_out, guests, rooms):
    if dest_id not in BY_ID:
        raise HotelError("Unknown destination.", 404)
    if not isinstance(guests, int) or not 1 <= guests <= MAX_GUESTS:
        raise HotelError(f"Choose between 1 and {MAX_GUESTS} guests.")
    if not isinstance(rooms, int) or not 1 <= rooms <= MAX_ROOMS:
        raise HotelError(f"Choose between 1 and {MAX_ROOMS} rooms.")
    ci, co, nights = _stay(check_in, check_out)
    with store.TX:
        bookings.sweep()
        out = []
        for prop in PROPERTIES[dest_id]:
            options = []
            for room in prop["rooms"]:
                free = _free_rooms(prop["id"], room, nights)
                fits = guests <= rooms * room["max_guests"]
                q = quote(prop, room, nights, rooms)
                options.append({"type": room["type"], "max_guests": room["max_guests"], "free": free, "fits_guests": fits,
                                "bookable": fits and free >= rooms, **q, "avg_per_night": q["total"] // max(1, len(nights) * rooms)})
            out.append({**{k: prop[k] for k in ("id", "name", "kind", "tier", "blurb", "amenities", "sample")}, "options": options})
    levels = [r["level"] for r in (crowd.day_forecast(dest_id, n) for n in nights)]
    busy = levels.count("High")
    result = {"destination": dest_id, "check_in": ci.isoformat(), "check_out": co.isoformat(), "nights": len(nights),
              "guests": guests, "rooms": rooms, "properties": out,
              "crowd": {"high_nights": busy, "levels": levels, "tax_rate": TAX_RATE}}
    if busy:
        result["quieter"] = crowd.quieter_dates(dest_id, ci, today=clock.today())
    return result


# ------------------------------------------------------------------ booking

def book(user, payload, idem=None):
    """Validate, price server-side and hold rooms. Returns (booking, order)."""
    prop = BY_PROPERTY.get(payload.get("hotel_id"))
    if not prop:
        raise HotelError("Choose a property.", 404)
    room = next((r for r in prop["rooms"] if r["type"] == payload.get("room_type")), None)
    if not room:
        raise HotelError("Choose a room type.")
    rooms, guests = payload.get("rooms"), payload.get("guests")
    if not isinstance(rooms, int) or isinstance(rooms, bool) or not 1 <= rooms <= MAX_ROOMS:
        raise HotelError(f"Choose between 1 and {MAX_ROOMS} rooms.")
    if not isinstance(guests, int) or isinstance(guests, bool) or not 1 <= guests <= MAX_GUESTS:
        raise HotelError(f"Choose between 1 and {MAX_GUESTS} guests.")
    if guests > rooms * room["max_guests"]:
        raise HotelError(f"{room['type']} sleeps {room['max_guests']}. Add rooms or choose a bigger room.")
    guest = payload.get("guest") or {}
    name = str(guest.get("name", "")).strip()
    if not name or len(name) > 80:
        raise HotelError("Enter the lead guest's name.")
    ci, co, nights = _stay(payload.get("check_in"), payload.get("check_out"))

    from bookings import add_pending, find_idem          # local: keeps the import order simple
    with store.TX:
        bookings.sweep()
        prior = find_idem(user["email"], idem)
        if prior:
            return prior, store.read()["orders"][prior["order_id"]]
        free = _free_rooms(prop["id"], room, nights)
        if free < rooms:
            raise HotelError("Sold out for those dates." if free == 0 else f"Only {free} room(s) left for those dates.", 409)
        q = quote(prop, room, nights, rooms)
        rec = {"id": secrets.token_hex(8), "kind": "hotel", "user": user["email"], "place": prop["destination"],
               "hotel_id": prop["id"], "hotel_name": prop["name"], "room_type": room["type"], "rooms": rooms, "guests": guests,
               "guest": {"name": name, "phone": str(guest.get("phone", ""))[:20]},
               "check_in": ci.isoformat(), "check_out": co.isoformat(), "nights": len(nights), "date": ci.isoformat(),
               "nightly": q["nightly"], "subtotal": q["subtotal"], "tax": q["tax"], "total": q["total"],
               "final_status": bookings.CONFIRMED, "hold": {"type": "hotel"}}
        return add_pending(user, rec, idem)
