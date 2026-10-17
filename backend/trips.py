"""Group trips: a shared itinerary, polls, expense splitting and a settle-up that minimises transfers.

SYNC. There are no websockets here (they don't suit a single sync worker on a free host). Instead every change
bumps the trip's `rev`; clients poll `GET /api/trips/<id>?since=<rev>` every few seconds and get either
"unchanged" or the full snapshot. Edits carry the `rev` they were based on, and an edit based on a stale rev is
refused with 409 and the current version, so two people editing the same thing never silently overwrite each
other. It is near-real-time, not instant.

MONEY. Integer paise throughout. Splits are APPORTIONED: each person's share is floored, then the leftover
paise go to the people with the largest fractional remainders, so the shares always add up to the total exactly.

SETTLE-UP. Net each person to (paid - owed), then repeatedly pair the biggest debtor with the biggest
creditor. That needs at most (people - 1) payments and zeroes every balance. (Finding the true minimum is
NP-hard; this greedy method is the standard, and is optimal unless some subset of balances cancels out.)

PRIVACY. Members are shown by an opaque id and first name; emails never leave the server.
"""

import heapq
import re
import secrets
import time
from datetime import date

import clock
import store
from data import DESTINATIONS

PLACES = {d["id"] for d in DESTINATIONS}
MAX_MEMBERS, MAX_ITEMS, MAX_EXPENSES, MAX_POLLS, MAX_TRIPS_PER_USER = 20, 200, 500, 30, 25
MAX_AMOUNT = 100_000_000                       # Rs 10 lakh, in paise
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # no 0/O/1/I
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_JOIN_FAILS = {}                               # email -> [timestamps]; slows down guessing join codes


class TripError(Exception):
    def __init__(self, message, status=400, extra=None):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra or {}


def _now():
    return clock.now().isoformat(timespec="seconds")


def _id(prefix):
    return prefix + secrets.token_hex(5)


def _text(value, label, lo, hi):
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    if not lo <= len(s) <= hi:
        raise TripError(f"{label} must be {lo}-{hi} characters." if lo else f"{label} must be at most {hi} characters.")
    return s


def _int(value, label, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise TripError(f"{label} must be a whole number from {lo} to {hi}.")
    return value


def first_name(email):
    name = (store.read()["users"].get(email) or {}).get("name") or email.split("@")[0]
    return name.split()[0]


# ------------------------------------------------------------------ lookup and permissions

def _trip(trip_id):
    t = store.read()["trips"].get(trip_id)
    if not t:
        raise TripError("Trip not found.", 404)
    return t


def _me(trip, user):
    m = next((m for m in trip["members"] if m["email"] == user["email"] and m["active"]), None)
    if not m:
        raise TripError("Trip not found.", 404)           # not a member: don't reveal that it exists
    return m


def _member(trip, member_id, active=True):
    m = next((m for m in trip["members"] if m["id"] == member_id and (m["active"] or not active)), None)
    if not m:
        raise TripError("That person isn't in this trip.")
    return m


def _touch(trip):
    trip["rev"] += 1
    return trip["rev"]


def _can_change(trip, me, record):
    return me["role"] == "owner" or record.get("by") == me["id"]


def _find(trip, kind, record_id):
    r = next((x for x in trip[kind] if x["id"] == record_id and not x.get("deleted")), None)
    if not r:
        raise TripError("Not found.", 404)
    return r


def _check_rev(record, base_rev):
    if base_rev != record["rev"]:
        raise TripError("conflict", 409, {"current": record})


# ------------------------------------------------------------------ money

def apportion(total, weights):
    """Split `total` paise in proportion to integer `weights` so the parts sum to exactly `total`."""
    if not weights or any(w <= 0 for w in weights.values()):
        raise TripError("Every share must be above zero.")
    w_sum = sum(weights.values())
    parts = {k: total * w // w_sum for k, w in weights.items()}
    leftover = total - sum(parts.values())
    for k in sorted(weights, key=lambda k: (-((total * weights[k]) % w_sum), k))[:leftover]:
        parts[k] += 1
    assert sum(parts.values()) == total
    return parts


def _shares(trip, amount, split):
    mode = (split or {}).get("mode", "equal")
    if mode == "equal":
        ids = split.get("among") or [m["id"] for m in trip["members"] if m["active"]]
        for i in ids:
            _member(trip, i)
        return apportion(amount, {i: 1 for i in dict.fromkeys(ids)})
    if mode == "shares":
        raw = split.get("weights") or {}
        for i, w in raw.items():
            _member(trip, i)
            _int(w, "Each share", 1, 1000)
        return apportion(amount, dict(raw))
    if mode == "exact":
        raw = split.get("amounts") or {}
        for i, a in raw.items():
            _member(trip, i)
            _int(a, "Each amount", 0, MAX_AMOUNT)
        if sum(raw.values()) != amount:
            raise TripError("The amounts must add up to the total.")
        return {i: a for i, a in raw.items() if a > 0}
    raise TripError("Choose equal, shares or exact.")


def balances(trip):
    """member id -> net paise (positive: is owed money; negative: owes). Always sums to zero."""
    net = {m["id"]: 0 for m in trip["members"]}
    for e in trip["expenses"]:
        if e.get("deleted"):
            continue
        net[e["paid_by"]] += e["amount"]
        for i, share in e["shares"].items():
            net[i] -= share
    assert sum(net.values()) == 0
    return net


def transfers(net):
    """Who pays whom to clear every balance: [{from, to, amount}], at most len(people) - 1 of them."""
    owed = [(-b, i) for i, b in net.items() if b > 0]           # heap of creditors, biggest first
    owes = [(b, i) for i, b in net.items() if b < 0]            # heap of debtors, biggest debt first (most negative)
    heapq.heapify(owed)
    heapq.heapify(owes)
    out = []
    while owed and owes:
        c_neg, c = heapq.heappop(owed)
        d_neg, d = heapq.heappop(owes)
        pay = min(-c_neg, -d_neg)
        out.append({"from": d, "to": c, "amount": pay})
        if -c_neg > pay:
            heapq.heappush(owed, (c_neg + pay, c))
        if -d_neg > pay:
            heapq.heappush(owes, (d_neg + pay, d))
    return out


# ------------------------------------------------------------------ views

def snapshot(trip, user):
    me = _me(trip, user)
    net = balances(trip)
    names = {m["id"]: m["name"] for m in trip["members"]}
    items = sorted((i for i in trip["items"] if not i.get("deleted")), key=lambda i: (i["day"], i["time"] or "99:99", i["created"]))
    polls = []
    for p in trip["polls"]:
        tally = {o["id"]: 0 for o in p["options"]}
        for opt in p["votes"].values():
            tally[opt] += 1
        polls.append({**{k: p[k] for k in ("id", "question", "options", "closed", "by", "created", "rev")}, "tally": tally,
                      "voters": len(p["votes"]), "my_vote": p["votes"].get(me["id"])})
    exps = sorted((e for e in trip["expenses"] if not e.get("deleted")), key=lambda e: (e["date"], e["created"]), reverse=True)
    spent = sum(e["amount"] for e in exps if e["kind"] == "expense")
    out = {"id": trip["id"], "name": trip["name"], "start_date": trip["start_date"], "rev": trip["rev"], "me": me["id"], "role": me["role"],
           "members": [{"id": m["id"], "name": m["name"], "role": m["role"], "active": m["active"], "balance": net[m["id"]]} for m in trip["members"]],
           "items": items, "polls": polls, "expenses": exps, "transfers": transfers(net),
           "totals": {"spent": spent, "per_person": spent // max(1, sum(1 for m in trip["members"] if m["active"]))},
           "names": names}
    if me["role"] == "owner":
        out["join"] = {"code": trip["code"], "active": trip["code_active"]}
    return out


def summary_row(trip, user):
    me = _me(trip, user)
    return {"id": trip["id"], "name": trip["name"], "start_date": trip["start_date"], "role": me["role"],
            "members": sum(1 for m in trip["members"] if m["active"]), "items": sum(1 for i in trip["items"] if not i.get("deleted")),
            "balance": balances(trip)[me["id"]]}


def mine(user):
    rows = []
    for t in store.read()["trips"].values():
        if any(m["email"] == user["email"] and m["active"] for m in t["members"]):
            rows.append(summary_row(t, user))
    return sorted(rows, key=lambda r: r["name"].lower())


def get(user, trip_id, since=None):
    t = _trip(trip_id)
    _me(t, user)
    if since is not None and since == t["rev"]:
        return {"rev": t["rev"], "changed": False}
    return {**snapshot(t, user), "changed": True}


# ------------------------------------------------------------------ trips and members

def _new_code():
    taken = {t["code"] for t in store.read()["trips"].values()}
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        if code not in taken:
            return code


def create(user, name, start_date=None):
    name = _text(name, "Trip name", 1, 80)
    if start_date:
        try:
            date.fromisoformat(start_date)
        except (TypeError, ValueError):
            raise TripError("Enter the start date as YYYY-MM-DD.")
    with store.TX:
        db = store.read()
        if sum(1 for t in db["trips"].values() if t["owner_email"] == user["email"]) >= MAX_TRIPS_PER_USER:
            raise TripError(f"You can own up to {MAX_TRIPS_PER_USER} trips.")
        me = {"id": _id("m_"), "email": user["email"], "name": first_name(user["email"]), "role": "owner", "active": True, "joined": _now()}
        t = {"id": _id("trip_"), "name": name, "owner_email": user["email"], "start_date": start_date or None, "created": _now(), "rev": 1,
             "code": _new_code(), "code_active": True, "members": [me], "items": [], "polls": [], "expenses": []}
        db["trips"][t["id"]] = t
        store.commit()
        return snapshot(t, user)


def join(user, code):
    code = str(code or "").strip().upper()
    now = time.time()
    recent = [x for x in _JOIN_FAILS.get(user["email"], []) if now - x < 3600]
    if len(recent) >= 10:
        raise TripError("Too many wrong codes. Try again in an hour.", 429)
    with store.TX:
        t = next((t for t in store.read()["trips"].values() if t["code"] == code and t["code_active"]), None)
        if not t:
            _JOIN_FAILS[user["email"]] = recent + [now]
            raise TripError("That invite code isn't valid.", 404)
        m = next((m for m in t["members"] if m["email"] == user["email"]), None)
        if m and m["active"]:
            return snapshot(t, user)
        if sum(1 for x in t["members"] if x["active"]) >= MAX_MEMBERS:
            raise TripError(f"This trip is full ({MAX_MEMBERS} people).")
        if m:
            m["active"] = True                                  # coming back keeps their old balance and history
        else:
            t["members"].append({"id": _id("m_"), "email": user["email"], "name": first_name(user["email"]), "role": "member", "active": True, "joined": _now()})
        _touch(t)
        store.commit()
        return snapshot(t, user)


def set_code(user, trip_id, action):
    with store.TX:
        t = _trip(trip_id)
        if _me(t, user)["role"] != "owner":
            raise TripError("Only the trip owner can change the invite code.", 403)
        if action == "regenerate":
            t["code"], t["code_active"] = _new_code(), True
        elif action in ("enable", "disable"):
            t["code_active"] = action == "enable"
        else:
            raise TripError("Unknown action.")
        _touch(t)
        store.commit()
        return snapshot(t, user)


def remove_member(user, trip_id, member_id):
    """The owner removes someone, or a member leaves. Nobody leaves while still owing or owed money."""
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        target = _member(t, member_id)
        if target["id"] != me["id"] and me["role"] != "owner":
            raise TripError("Only the owner can remove other people.", 403)
        if target["role"] == "owner":
            raise TripError("The owner can't leave. Delete the trip instead.")
        if balances(t)[target["id"]] != 0:
            raise TripError("Settle up first: this person still owes or is owed money.")
        target["active"] = False
        _touch(t)
        store.commit()
        return {"removed": True}


def delete_trip(user, trip_id):
    with store.TX:
        t = _trip(trip_id)
        if _me(t, user)["role"] != "owner":
            raise TripError("Only the trip owner can delete it.", 403)
        del store.read()["trips"][trip_id]
        store.commit()
        return {"deleted": True}


# ------------------------------------------------------------------ itinerary

def _item_fields(body):
    day = _int(body.get("day"), "Day", 1, 60)
    t = (body.get("time") or "").strip() or None
    if t and not _TIME.match(t):
        raise TripError("Enter the time as HH:MM.")
    place = body.get("place") or None
    if place and place not in PLACES:
        place = None
    return {"day": day, "time": t, "title": _text(body.get("title"), "Title", 1, 120), "place": place, "notes": _text(body.get("notes"), "Notes", 0, 500)}


def _live(trip, kind):
    return sum(1 for x in trip[kind] if not x.get("deleted"))


def add_item(user, trip_id, body):
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        if _live(t, "items") >= MAX_ITEMS:
            raise TripError(f"A trip holds up to {MAX_ITEMS} itinerary items.")
        f = _item_fields(body)
        rev = _touch(t)
        item = {"id": _id("it_"), **f, "by": me["id"], "created": _now(), "rev": rev, "deleted": False}
        t["items"].append(item)
        store.commit()
        return item


def import_items(user, trip_id, items):
    if not isinstance(items, list) or not items or len(items) > 60:
        raise TripError("Send between 1 and 60 items.")
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        if _live(t, "items") + len(items) > MAX_ITEMS:
            raise TripError(f"A trip holds up to {MAX_ITEMS} itinerary items.")
        fields = [_item_fields(i if isinstance(i, dict) else {}) for i in items]       # validate all before adding any
        rev = _touch(t)
        for f in fields:
            t["items"].append({"id": _id("it_"), **f, "by": me["id"], "created": _now(), "rev": rev, "deleted": False})
        store.commit()
        return {"added": len(fields)}


def edit_item(user, trip_id, item_id, body):
    with store.TX:
        t = _trip(trip_id)
        _me(t, user)
        item = _find(t, "items", item_id)
        _check_rev(item, body.get("base_rev"))
        item.update(_item_fields({**item, **{k: body[k] for k in ("day", "time", "title", "place", "notes") if k in body}}))
        item["rev"] = _touch(t)
        store.commit()
        return item


def delete_item(user, trip_id, item_id):
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        item = _find(t, "items", item_id)
        if not _can_change(t, me, item):
            raise TripError("Only the person who added this, or the owner, can delete it.", 403)
        item["deleted"], item["rev"] = True, _touch(t)
        store.commit()
        return {"deleted": True}


# ------------------------------------------------------------------ polls

def add_poll(user, trip_id, question, options):
    if not isinstance(options, list) or not 2 <= len(options) <= 8:
        raise TripError("Give between 2 and 8 options.")
    texts = [_text(o, "Option", 1, 80) for o in options]
    if len({x.lower() for x in texts}) != len(texts):
        raise TripError("Options must be different from each other.")
    q = _text(question, "Question", 1, 160)
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        if len(t["polls"]) >= MAX_POLLS:
            raise TripError(f"A trip holds up to {MAX_POLLS} polls.")
        rev = _touch(t)
        p = {"id": _id("pl_"), "question": q, "options": [{"id": _id("o_"), "text": x} for x in texts], "votes": {}, "closed": False,
             "by": me["id"], "created": _now(), "rev": rev}
        t["polls"].append(p)
        store.commit()
        return {"id": p["id"]}


def vote(user, trip_id, poll_id, option_id):
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        p = next((x for x in t["polls"] if x["id"] == poll_id), None)
        if not p:
            raise TripError("Poll not found.", 404)
        if p["closed"]:
            raise TripError("This poll is closed.", 409)
        if option_id not in {o["id"] for o in p["options"]}:
            raise TripError("Choose one of the options.")
        if p["votes"].get(me["id"]) == option_id:
            del p["votes"][me["id"]]                            # tapping your choice again withdraws it
        else:
            p["votes"][me["id"]] = option_id
        p["rev"] = _touch(t)
        store.commit()
        return {"voted": p["votes"].get(me["id"])}


def close_poll(user, trip_id, poll_id):
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        p = next((x for x in t["polls"] if x["id"] == poll_id), None)
        if not p:
            raise TripError("Poll not found.", 404)
        if not _can_change(t, me, p):
            raise TripError("Only the person who asked, or the owner, can close this.", 403)
        p["closed"], p["rev"] = True, _touch(t)
        store.commit()
        return {"closed": True}


# ------------------------------------------------------------------ expenses

def _expense_fields(trip, body):
    desc = _text(body.get("description"), "Description", 1, 120)
    amount = _int(body.get("amount"), "Amount", 1, MAX_AMOUNT)
    paid_by = body.get("paid_by")
    _member(trip, paid_by)
    d = body.get("date") or clock.today().isoformat()
    try:
        date.fromisoformat(d)
    except (TypeError, ValueError):
        raise TripError("Enter the date as YYYY-MM-DD.")
    shares = _shares(trip, amount, body.get("split") or {})
    return {"description": desc, "amount": amount, "paid_by": paid_by, "date": d, "shares": shares, "split": body.get("split") or {"mode": "equal"}}


def add_expense(user, trip_id, body):
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        if _live(t, "expenses") >= MAX_EXPENSES:
            raise TripError(f"A trip holds up to {MAX_EXPENSES} expenses.")
        f = _expense_fields(t, body)
        rev = _touch(t)
        e = {"id": _id("ex_"), "kind": "expense", **f, "by": me["id"], "created": _now(), "rev": rev, "deleted": False}
        t["expenses"].append(e)
        store.commit()
        return e


def edit_expense(user, trip_id, expense_id, body):
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        e = _find(t, "expenses", expense_id)
        if e["kind"] != "expense":
            raise TripError("A recorded payment can't be edited. Delete it and record it again.")
        if not _can_change(t, me, e):
            raise TripError("Only the person who added this, or the owner, can edit it.", 403)
        _check_rev(e, body.get("base_rev"))
        e.update(_expense_fields(t, {**{k: e[k] for k in ("description", "amount", "paid_by", "date", "split")}, **body}))
        e["rev"] = _touch(t)
        store.commit()
        return e


def delete_expense(user, trip_id, expense_id):
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        e = _find(t, "expenses", expense_id)
        if not _can_change(t, me, e):
            raise TripError("Only the person who added this, or the owner, can delete it.", 403)
        e["deleted"], e["rev"] = True, _touch(t)
        store.commit()
        return {"deleted": True}


def settle(user, trip_id, from_id, to_id, amount):
    """Record that `from` paid `to` in real life, which moves both balances toward zero."""
    with store.TX:
        t = _trip(trip_id)
        me = _me(t, user)
        a, b = _member(t, from_id), _member(t, to_id)
        if a["id"] == b["id"]:
            raise TripError("Choose two different people.")
        if me["id"] not in (a["id"], b["id"]) and me["role"] != "owner":
            raise TripError("Only the two people involved, or the owner, can record this.", 403)
        amount = _int(amount, "Amount", 1, MAX_AMOUNT)
        rev = _touch(t)
        e = {"id": _id("ex_"), "kind": "settlement", "description": f"{a['name']} paid {b['name']}", "amount": amount, "paid_by": a["id"],
             "date": clock.today().isoformat(), "shares": {b["id"]: amount}, "split": {"mode": "exact"}, "by": me["id"],
             "created": _now(), "rev": rev, "deleted": False}
        t["expenses"].append(e)
        store.commit()
        return e
