"""Trip planner: picks which towns to visit, in what order, for how long, and schedules each day.

This is an OPTIMISER, not a language model. It decides everything that has to be right - which towns, the route,
opening hours, travel time, cost - and an LLM (llm.py) is only ever asked to describe the result in friendlier words.

How it decides:
  1. TRAVEL TIMES between every pair of the ten towns, taking the better of bus and train (train journey times
     come from the timetable, plus the road hop for towns with no station) by a "time is money" cost.
  2. ROUTE. Held-Karp dynamic programming finds the quickest tour of EVERY subset of towns in one pass
     (2^10 x 10 x 10 ~ 100k steps), starting from where you are and optionally ending back there.
  3. WHICH TOWNS. Every subset that fits the number of days is scored on how much of what you like it contains
     (see activities.value) minus a penalty per hour spent travelling. The best candidates are then costed, and
     the best one that fits your budget wins; if none does, comfort is stepped down, and if that fails it says so.
  4. DAYS PER TOWN are handed out greedily to whichever town gains the most from one more day.
  5. EACH DAY is built on a clock. Activities are placed into the real opening sessions (temples close midday),
     around lunch, with a gap for getting about; a daytime journey eats the end of a day, a night journey doesn't.

Heuristic, not exhaustive: the route and the choice of towns are optimal for the model; durations, non-worship
opening hours and costs are estimates, and the plan says so.
"""

import math
from datetime import date, timedelta
from functools import lru_cache

import activities as AC
import clock
import crowd
import hotels
import transport
from data import DESTINATIONS

PLACES = [d["id"] for d in DESTINATIONS]
BY_ID = {d["id"]: d for d in DESTINATIONS}
NAMES = {d["id"]: d["name"].split(" (")[0] for d in DESTINATIONS}
HUB = {p: transport.DEST_HUB[p]["hub"] for p in PLACES}
RAILHEAD = {p: transport.DEST_HUB[p].get("railhead", HUB[p]) for p in PLACES}

PACE = {"relaxed": {"start": 9.5, "end": 18.0, "cap": 2}, "balanced": {"start": 9.0, "end": 19.5, "cap": 3},
        "packed": {"start": 8.0, "end": 21.0, "cap": 4}}
PACES, COMFORTS = tuple(PACE), ("budget", "standard", "comfort")
VALUE_OF_TIME = 150          # rupees per hour: how much a faster journey is worth when choosing bus or train
OVERNIGHT_HOURS = 6.0        # journeys at least this long are taken overnight
TRAVEL_PENALTY = 1.0         # value lost per hour of travelling, when choosing which towns to visit
MAX_TOWNS, MAX_DAYS, GAP, LUNCH = 5, 7, 0.33, (13.0, 14.0)
FOOD_PER_DAY = {"budget": 350, "standard": 650, "comfort": 1100}        # rupees per person
LOCAL_PER_DAY = {"budget": 250, "standard": 400, "comfort": 700}        # rupees per group
BUS_TYPE = {"budget": "Non-AC Seater", "standard": "AC Seater", "comfort": "Volvo Multi-Axle AC"}
NIGHT_BUS_TYPE = {"budget": "Non-AC Sleeper", "standard": "AC Sleeper", "comfort": "Volvo Multi-Axle AC"}
TRAIN_CLASS = {"budget": "SL", "standard": "3A", "comfort": "2A"}
HOTEL_TIER = {"budget": 0, "standard": 1, "comfort": 2}


class PlanError(Exception):
    pass


def inr(n):
    """12345678 -> '₹1,23,45,678' (lakh/crore grouping, as Indian readers expect)."""
    s = str(abs(int(n)))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ("-" if n < 0 else "") + "₹" + ",".join(groups + [tail])


# ------------------------------------------------------------------ request

def _place(value):
    v = str(value or "").strip().lower()
    if v in BY_ID:
        return v
    return next((p for p in PLACES if NAMES[p].lower() == v or BY_ID[p]["name"].lower() == v), None)


def _int(raw, key, default, lo, hi):
    v = raw.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise PlanError(f"{key} must be a whole number from {lo} to {hi}.")
    return v


def normalize(raw):
    r = raw if isinstance(raw, dict) else {}
    start = _place(r.get("start") or "chennai")
    if not start:
        raise PlanError("Choose a start town from the list.")
    days = _int(r, "days", 3, 1, MAX_DAYS)
    travellers = _int(r, "travellers", 2, 1, 6)
    interests = [i for i in dict.fromkeys(r.get("interests") or []) if i in AC.INTERESTS] or list(AC.INTERESTS)
    pace, comfort = r.get("pace", "balanced"), r.get("comfort", "standard")
    if pace not in PACES or comfort not in COMFORTS:
        raise PlanError("Choose a valid pace and comfort level.")
    budget = r.get("budget")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or not 1000 <= budget <= 1_000_000):
        raise PlanError("Budget must be between 1,000 and 10,00,000 rupees.")
    try:
        start_date = date.fromisoformat(r["start_date"]) if r.get("start_date") else clock.today() + timedelta(days=1)
    except (TypeError, ValueError):
        raise PlanError("Enter the start date as YYYY-MM-DD.")
    if not clock.today() <= start_date <= clock.today() + timedelta(days=365):
        raise PlanError("Pick a start date within the next year.")
    must = [p for p in (_place(x) for x in (r.get("must") or [])) if p]
    avoid = [p for p in (_place(x) for x in (r.get("avoid") or [])) if p]
    if set(must) & set(avoid):
        raise PlanError("A place can't be both required and avoided.")
    if set(avoid) >= set(PLACES):
        raise PlanError("There's nothing left to visit after your exclusions.")
    must = list(dict.fromkeys(must))
    if len(must) > min(days, MAX_TOWNS):
        raise PlanError(f"{len(must)} places won't fit in {days} day(s). Allow more days or choose fewer places.")
    return_home = r.get("return_home", True)
    if not isinstance(return_home, bool):
        raise PlanError("return_home must be true or false.")
    return {"start": start, "days": days, "travellers": travellers, "interests": interests, "pace": pace, "comfort": comfort,
            "budget": budget, "start_date": start_date.isoformat(), "must": must, "avoid": avoid, "return_home": return_home}


# ------------------------------------------------------------------ travel between towns

def _clock(x):
    m = int(round((x % 24) * 60))
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def _hours(hm):
    h, m = hm.split(":")
    return int(h) + int(m) / 60


@lru_cache(maxsize=None)
def leg(a, b, comfort):
    """Best way to go a -> b: {mode, hours, fare (rupees, per person), km, overnight, desc}."""
    if a == b:
        return {"mode": "none", "hours": 0.0, "fare": 0, "km": 0, "overnight": False, "desc": ""}
    km = transport.road_km(HUB[a], HUB[b])
    bus_h = km / 45 + 0.4
    options = [{"mode": "bus", "hours": bus_h, "km": km, "bus_h": bus_h}]
    ra, rb = RAILHEAD[a], RAILHEAD[b]
    trains = transport.rail_options(ra, rb) if ra != rb else []
    if trains:
        best = min(trains, key=lambda t: t["minutes"])
        hours, extra_fare = best["minutes"] / 60 + 0.5, 0
        for p, rail in ((a, ra), (b, rb)):                      # towns with no station of their own need a road hop
            if HUB[p] != rail:
                t_km = transport.DEST_HUB[p]["transfer_km"]
                hours += t_km / 40 + 0.4
                extra_fare += transport.bus_fare("Non-AC Seater", t_km)
        rail_km = transport.rail_km(ra, rb)
        fare = transport.train_fare(TRAIN_CLASS[comfort], rail_km, False)["total"] + extra_fare
        options.append({"mode": "train", "hours": hours, "fare": fare, "km": rail_km,
                        "desc": f"Train {best['no']} {best['name']}", "train_minutes": best["minutes"]})
    for o in options:
        if o["mode"] == "bus":
            o["fare"] = transport.bus_fare(NIGHT_BUS_TYPE[comfort] if o["hours"] >= OVERNIGHT_HOURS else BUS_TYPE[comfort], km)
            o["desc"] = f"{NIGHT_BUS_TYPE[comfort] if o['hours'] >= OVERNIGHT_HOURS else BUS_TYPE[comfort]} bus, about {km} km"
    pick = min(options, key=lambda o: o["hours"] * VALUE_OF_TIME + o["fare"])
    return {"mode": pick["mode"], "hours": round(pick["hours"], 2), "fare": pick["fare"], "km": pick["km"],
            "overnight": pick["hours"] >= OVERNIGHT_HOURS, "desc": pick["desc"]}


def _t(a, b):
    return leg(a, b, "standard")["hours"]


# ------------------------------------------------------------------ route search

def tours(origin, towns, return_home):
    """Held-Karp: the quickest route from `origin` through every subset of `towns`.

    Returns (best, order) where best[mask] = (hours, last town index) and order(mask) lists the towns in visiting order.
    """
    n, INF = len(towns), float("inf")
    dp = [[INF] * n for _ in range(1 << n)]
    parent = [[-1] * n for _ in range(1 << n)]
    for i in range(n):
        dp[1 << i][i] = _t(origin, towns[i])
    for mask in range(1, 1 << n):
        for last in range(n):
            here = dp[mask][last]
            if here == INF:
                continue
            for nxt in range(n):
                if mask >> nxt & 1:
                    continue
                nm, c = mask | 1 << nxt, here + _t(towns[last], towns[nxt])
                if c < dp[nm][nxt]:
                    dp[nm][nxt], parent[nm][nxt] = c, last
    best = {}
    for mask in range(1, 1 << n):
        options = [(dp[mask][last] + (_t(towns[last], origin) if return_home else 0), last) for last in range(n) if mask >> last & 1]
        best[mask] = min(options)

    def order(mask):
        path, last = [], best[mask][1]
        while last != -1:
            path.append(towns[last])
            mask, last = mask & ~(1 << last), parent[mask][last]
        return path[::-1]

    return best, order


# ------------------------------------------------------------------ choosing days and activities

def _vals(town, tags):
    return sorted((AC.value(a, tags) for a in AC.ACTIVITIES[town]), reverse=True)


def allocate(towns, days, cap, tags):
    """One day each, then every spare day to whichever town gains the most from it. Returns ({town: days}, value)."""
    vals = {t: _vals(t, tags) for t in towns}
    alloc = {t: 1 for t in towns}
    total = sum(sum(vals[t][:cap]) for t in towns)
    for _ in range(days - len(towns)):
        gains = {t: sum(vals[t][alloc[t] * cap:(alloc[t] + 1) * cap]) for t in towns}
        pick = max(towns, key=lambda t: gains[t])
        alloc[pick] += 1
        total += gains[pick]
    return alloc, total


def _slot(activity, w0, w1, busy):
    """Earliest start in the activity's real opening sessions that fits the window and clashes with nothing."""
    dur = activity["hours"]
    for o1, o2 in activity["open"]:
        s, hi = max(_hours(o1), w0), min(_hours(o2), w1)
        while s + dur <= hi + 1e-9:
            if all(s >= b1 + GAP - 1e-9 or s + dur + GAP <= b0 + 1e-9 for b0, b1 in busy):
                return s
            s = round(s + 0.25, 2)
    return None


def schedule_day(town, w0, w1, cap, pool, tags, rain):
    """Fill one day's window from `pool` (a list, consumed in place). Returns timed items, best value first."""
    placed, busy = [], []
    for a in sorted(pool, key=lambda a: -AC.value(a, tags, rain)):
        if len(placed) >= cap or w1 - w0 < 1.0:
            break
        is_food = "food" in a["tags"]
        s = _slot(a, w0, w1, [b for b in busy if not (is_food and b == LUNCH)] + ([] if is_food else [LUNCH]))
        if s is None:
            continue
        placed.append((s, a))
        busy.append((s, s + a["hours"]))
    for s, a in placed:
        pool.remove(a)
    items = [{"type": "activity", "start": _clock(s), "end": _clock(s + a["hours"]), "title": a["name"], "id": a["id"], "tags": a["tags"],
              "indicative": a["indicative"], "note": a["note"], "outdoor": a["outdoor"]} for s, a in sorted(placed, key=lambda p: p[0])]
    if w0 <= LUNCH[0] and w1 >= LUNCH[1] and not any(12.0 <= s <= 14.5 and "food" in a["tags"] for s, a in placed):
        items.append({"type": "meal", "start": _clock(LUNCH[0]), "end": _clock(LUNCH[1]), "title": "Lunch break"})
        items.sort(key=lambda i: i["start"])
    return items


# ------------------------------------------------------------------ the calendar

def calendar(order, alloc, legs, pace):
    """One record per day with its clock window, shortened by any journey that starts or ends that day."""
    p, days, n = PACE[pace], [], 0
    for i, town in enumerate(order):
        for j in range(alloc[town]):
            n += 1
            w0, w1, arrive, depart = p["start"], p["end"], None, None
            if j == 0 and legs[i] and legs[i]["hours"] > 0:
                lg = legs[i]
                if lg["overnight"]:
                    at = (21.5 + lg["hours"]) % 24
                    w0, arrive = max(w0, at + 1.5), {"leg": lg, "kind": "overnight", "at": at}
                elif i == 0:                                      # the trip opens with a daytime journey
                    w0, arrive = p["start"] + lg["hours"] + 0.5, {"leg": lg, "kind": "day", "from": p["start"], "at": p["start"] + lg["hours"]}
            if j == alloc[town] - 1 and legs[i + 1] and legs[i + 1]["hours"] > 0:
                lg = legs[i + 1]
                if lg["overnight"]:
                    w1, depart = min(w1, 20.5), {"leg": lg, "kind": "overnight", "at": 21.5}
                else:
                    w1 = max(w0, min(w1, 17.5 - lg["hours"]))
                    depart = {"leg": lg, "kind": "day", "at": w1}
            days.append({"day": n, "town": town, "first": j == 0, "last": j == alloc[town] - 1, "w0": w0, "w1": w1, "arrive": arrive, "depart": depart})
    return days


def nights(order, alloc, legs, return_home):
    """Hotel nights per town. A night on a train or bus is not a hotel night, and the last evening is spent travelling home."""
    out = {}
    for i, town in enumerate(order):
        last = i == len(order) - 1
        n = alloc[town] - (1 if last else 0) - (1 if (not last and legs[i + 1] and legs[i + 1]["overnight"]) else 0)
        out[town] = max(0, n)
    return out


def _hotel_for(town, comfort):
    prop = hotels.PROPERTIES[town][HOTEL_TIER[comfort]]
    return prop, prop["rooms"][0]


# ------------------------------------------------------------------ costing

def cost(order, alloc, legs, req, comfort, day_of_town_start):
    rooms = math.ceil(req["travellers"] / 2)
    start = date.fromisoformat(req["start_date"])
    n_by_town = nights(order, alloc, legs, req["return_home"])
    stays, hotel_total = [], 0
    for town in order:
        k = n_by_town[town]
        if not k:
            continue
        prop, room = _hotel_for(town, comfort)
        dates = [start + timedelta(days=day_of_town_start[town] - 1 + i) for i in range(k)]
        nightly = hotels.nightly_prices(prop, room, dates)
        sub = sum(r["price"] for r in nightly) * rooms
        hotel_total += int(round(sub * (1 + hotels.TAX_RATE)))
        stays.append({"town": town, "nights": k, "hotel": prop["name"], "room": room["type"], "rooms": rooms, "from": dates[0].isoformat(),
                      "to": (dates[-1] + timedelta(days=1)).isoformat(), "avg_per_night": sub // (k * rooms), "total": int(round(sub * (1 + hotels.TAX_RATE)))})
    travel = sum(lg["fare"] for lg in legs if lg) * req["travellers"]
    days = sum(alloc.values())
    food = FOOD_PER_DAY[comfort] * req["travellers"] * days
    local = LOCAL_PER_DAY[comfort] * days * (1 if req["travellers"] <= 4 else 2)
    total = travel + hotel_total + food + local
    return {"total": total, "per_person": total // req["travellers"],
            "breakdown": {"travel": travel, "stay": hotel_total, "food": food, "local": local}}, stays


def _leg_list(origin, order, comfort, return_home):
    legs = [leg(origin, order[0], comfort)]
    legs += [leg(a, b, comfort) for a, b in zip(order, order[1:])]
    legs.append(leg(order[-1], origin, comfort) if return_home else None)
    return legs


def _starts(order, alloc):
    day, out = 1, {}
    for t in order:
        out[t] = day
        day += alloc[t]
    return out


# ------------------------------------------------------------------ the plan

def plan(raw, rain=None):
    """Build a full plan. `rain` optionally maps (town, 'YYYY-MM-DD') -> probability of rain, in percent."""
    req = normalize(raw)
    rain = rain or {}
    tags = AC.interest_tags(req["interests"])
    cap, origin = PACE[req["pace"]]["cap"], req["start"]
    towns = [p for p in PLACES if p not in req["avoid"]]
    if not towns:
        raise PlanError("There's nothing left to visit after your exclusions.")
    must_mask = sum(1 << towns.index(m) for m in req["must"] if m in towns)
    best, order_of = tours(origin, towns, req["return_home"])
    kmax = min(req["days"], MAX_TOWNS)

    scored = []
    for mask in range(1, 1 << len(towns)):
        if bin(mask).count("1") > kmax or mask & must_mask != must_mask:
            continue
        order = order_of(mask)
        _, value = allocate(order, req["days"], cap, tags)
        scored.append((value - TRAVEL_PENALTY * best[mask][0], mask))
    scored.sort(reverse=True)
    candidates = [m for _, m in scored[:40]]

    chosen = None
    asked = COMFORTS.index(req["comfort"])
    levels = [COMFORTS[i] for i in range(asked, -1, -1)]
    cheapest = None
    for comfort in levels:
        for mask in candidates:
            order = order_of(mask)
            alloc, _ = allocate(order, req["days"], cap, tags)
            legs = _leg_list(origin, order, comfort, req["return_home"])
            c, stays = cost(order, alloc, legs, req, comfort, _starts(order, alloc))
            row = (c["total"], comfort, order, alloc, legs, c, stays)
            cheapest = row if cheapest is None or c["total"] < cheapest[0] else cheapest
            if req["budget"] is None or c["total"] <= req["budget"]:
                chosen = row
                break
        if chosen:
            break
    over_budget = chosen is None
    if over_budget:
        chosen = cheapest
    _, comfort, order, alloc, legs, costs, stays = chosen
    return _assemble(req, comfort, order, alloc, legs, costs, stays, rain, over_budget, tags)


def _assemble(req, comfort, order, alloc, legs, costs, stays, rain, over_budget, tags):
    start, origin = date.fromisoformat(req["start_date"]), req["start"]
    cap = PACE[req["pace"]]["cap"]
    pools = {t: list(AC.ACTIVITIES[t]) for t in order}
    days_out = []
    for d in calendar(order, alloc, legs, req["pace"]):
        when = start + timedelta(days=d["day"] - 1)
        town = d["town"]
        forecast = crowd.day_forecast(town, when)
        rain_p = rain.get((town, when.isoformat()))
        wet = rain_p is not None and rain_p >= 70
        items = []
        if d["arrive"]:
            a = d["arrive"]
            items.append({"type": "travel", "start": _clock(a.get("from", a["at"])), "end": _clock(a["at"]), "title": f"Arrive in {NAMES[town]}",
                          "detail": a["leg"]["desc"], "overnight": a["kind"] == "overnight"})
        items += schedule_day(town, d["w0"], d["w1"], cap, pools[town], tags, wet)
        if d["depart"]:
            dp = d["depart"]
            target = _next_town(order, town) or origin
            items.append({"type": "travel", "start": _clock(dp["at"]), "end": _clock(dp["at"] + dp["leg"]["hours"]),
                          "title": f"{'Return' if target == origin and d['last'] and town == order[-1] else 'Travel'} to {NAMES[target]}",
                          "detail": dp["leg"]["desc"], "overnight": dp["kind"] == "overnight"})
        d_notes = []
        if forecast["level"] == "High":
            top = max(forecast["factors"], key=lambda f: f["points"])["label"]
            d_notes.append(f"Expect crowds in {NAMES[town]} ({top.split(' (')[0].lower()}). Start early.")
        if wet:
            d_notes.append(f"Rain is likely ({int(rain_p)}%), so outdoor stops were moved down the list.")
        if not any(i["type"] == "activity" for i in items):
            d_notes.append("A travel day, with little time for sightseeing.")
        days_out.append({"day": d["day"], "date": when.isoformat(), "weekday": when.strftime("%A"), "town": town, "town_name": NAMES[town],
                         "items": items, "crowd": forecast["level"], "rain": rain_p, "notes": d_notes})

    notes = []
    for t in order:
        if start.month not in crowd._BEST[t]:
            notes.append(f"{NAMES[t]} is out of its best season ({BY_ID[t]['best_time']}), so expect fewer crowds and possibly rain.")
    if legs[0]["overnight"]:
        notes.append(f"Your first journey is overnight, so leave the evening before Day 1 to be in {NAMES[order[0]]} by morning.")
    if any(lg and lg["overnight"] for lg in legs):
        notes.append("Night journeys save a hotel night. Book them in advance.")
    if any(i.get("indicative") for d in days_out for i in d["items"]):
        notes.append("Opening hours are real for places of worship. For everything else they are typical hours, so confirm locally.")
    if over_budget:
        notes.insert(0, f"Even the cheapest plan for these days costs about {inr(costs['total'])}, which is over your {inr(req['budget'])} budget.")
    elif req["budget"] is not None and comfort != req["comfort"]:
        notes.insert(0, f"To fit your budget the plan uses {comfort} travel and stays instead of {req['comfort']}.")

    route = [origin] + order + ([origin] if req["return_home"] else [])
    legs_out = [{"from": a, "to": b, "from_name": NAMES[a], "to_name": NAMES[b],
                 **{k: lg[k] for k in ("mode", "hours", "fare", "km", "overnight", "desc")}}
                for lg, a, b in zip([x for x in legs if x], route, route[1:]) if lg["hours"] > 0]
    return {"request": req, "comfort": comfort,
            "summary": {"days": len(days_out), "towns": order, "town_names": [NAMES[t] for t in order], "over_budget": over_budget,
                        "within_budget": None if req["budget"] is None else not over_budget, "cost": costs,
                        "unused_activities": sum(len(p) for p in pools.values())},
            "legs": legs_out, "stays": stays, "days": days_out, "notes": notes}


def _next_town(order, town):
    i = order.index(town)
    return order[i + 1] if i + 1 < len(order) else None
