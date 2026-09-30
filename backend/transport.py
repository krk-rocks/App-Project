"""Train and bus search, Tatkal rules, and booking against simulated inventory.

IMPORTANT: this is NOT connected to IRCTC or to any bus operator, because neither exposes a
public booking API - rail booking requires an authorised IRCTC B2B partnership. Routes, station
codes, class rules, Tatkal windows and the fare model below follow the real ones, but seats and
PNRs are generated locally. Nothing here reserves a real ticket.

Availability is derived from a hash of (service, date, class) so a given search returns the same
answer on every refresh instead of flickering on each poll.
"""

import hashlib
import math
import random
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import store

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------- places

# Boarding points a traveller is likely to start from. `rail` marks a hub with a railway station.
HUBS = {
    "MAS": {"name": "Chennai Central / Egmore", "city": "Chennai", "lat": 13.0827, "lon": 80.2707, "rail": True},
    "CGL": {"name": "Chengalpattu Junction", "city": "Chengalpattu", "lat": 12.6819, "lon": 79.9888, "rail": True},
    "CJ":  {"name": "Kanchipuram", "city": "Kanchipuram", "lat": 12.8342, "lon": 79.7036, "rail": True},
    "VM":  {"name": "Villupuram Junction", "city": "Villupuram", "lat": 11.9401, "lon": 79.4861, "rail": True},
    "PDY": {"name": "Puducherry", "city": "Puducherry", "lat": 11.9416, "lon": 79.8083, "rail": True},
    "TPJ": {"name": "Tiruchirappalli Junction", "city": "Trichy", "lat": 10.7905, "lon": 78.7047, "rail": True},
    "TJ":  {"name": "Thanjavur Junction", "city": "Thanjavur", "lat": 10.7870, "lon": 79.1378, "rail": True},
    "VLNK": {"name": "Velankanni", "city": "Velankanni", "lat": 10.6813, "lon": 79.8506, "rail": True},
    "MDU": {"name": "Madurai Junction", "city": "Madurai", "lat": 9.9252, "lon": 78.1198, "rail": True},
    "RMM": {"name": "Rameswaram", "city": "Rameswaram", "lat": 9.2876, "lon": 79.3129, "rail": True},
    "TEN": {"name": "Tirunelveli Junction", "city": "Tirunelveli", "lat": 8.7139, "lon": 77.7567, "rail": True},
    "CAPE": {"name": "Kanyakumari", "city": "Kanyakumari", "lat": 8.0883, "lon": 77.5385, "rail": True},
    "KQN": {"name": "Kodai Road", "city": "Kodai Road", "lat": 10.2333, "lon": 77.8833, "rail": True},
    "DG":  {"name": "Dindigul Junction", "city": "Dindigul", "lat": 10.3624, "lon": 77.9695, "rail": True},
    "SA":  {"name": "Salem Junction", "city": "Salem", "lat": 11.6643, "lon": 78.1460, "rail": True},
    "ED":  {"name": "Erode Junction", "city": "Erode", "lat": 11.3410, "lon": 77.7172, "rail": True},
    "CBE": {"name": "Coimbatore Junction", "city": "Coimbatore", "lat": 11.0168, "lon": 76.9558, "rail": True},
    "MTP": {"name": "Mettupalayam", "city": "Mettupalayam", "lat": 11.2996, "lon": 76.9366, "rail": True},
    "UAM": {"name": "Udagamandalam (Ooty)", "city": "Ooty", "lat": 11.4102, "lon": 76.6950, "rail": True},
    "SBC": {"name": "KSR Bengaluru", "city": "Bengaluru", "lat": 12.9716, "lon": 77.5946, "rail": True},
    "KOD": {"name": "Kodaikanal bus stand", "city": "Kodaikanal", "lat": 10.2381, "lon": 77.4892, "rail": False},
    "MAH": {"name": "Mahabalipuram bus stand", "city": "Mahabalipuram", "lat": 12.6269, "lon": 80.1927, "rail": False},
}

# Where each destination is actually reached from. Kodaikanal and Mahabalipuram have no station -
# their nearest railhead is a road transfer away, which is why the bus tab matters there.
DEST_HUB = {
    "madurai": {"hub": "MDU"},
    "rameswaram": {"hub": "RMM"},
    "thanjavur": {"hub": "TJ"},
    "kanyakumari": {"hub": "CAPE"},
    "ooty": {"hub": "UAM", "note": "Reached by the Nilgiri Mountain Railway from Mettupalayam (MTP)."},
    "kodaikanal": {"hub": "KOD", "railhead": "KQN", "transfer_km": 80,
                   "note": "Kodaikanal has no railway station. Trains run to Kodai Road (KQN), then it is a 3 hr ghat road transfer."},
    "mahabalipuram": {"hub": "MAH", "railhead": "CGL", "transfer_km": 29,
                      "note": "Mahabalipuram has no railway station. The nearest railhead is Chengalpattu (CGL), 29 km away."},
    "chennai": {"hub": "MAS"},
    "velankanni": {"hub": "VLNK"},
    "kanchipuram": {"hub": "CJ"},
}

# ---------------------------------------------------------------- trains

CLASSES = {
    "1A": {"label": "AC First (1A)", "rate": 2.90, "ac": True,  "tatkal": False},
    "2A": {"label": "AC 2-Tier (2A)", "rate": 1.72, "ac": True,  "tatkal": True},
    "3A": {"label": "AC 3-Tier (3A)", "rate": 1.20, "ac": True,  "tatkal": True},
    "CC": {"label": "AC Chair Car (CC)", "rate": 1.28, "ac": True,  "tatkal": True},
    "SL": {"label": "Sleeper (SL)", "rate": 0.46, "ac": False, "tatkal": True},
    "2S": {"label": "Second Sitting (2S)", "rate": 0.32, "ac": False, "tatkal": True},
}

# Tatkal premium: 30% of base fare for every class except 2S (10%), inside the real floor/ceiling.
TATKAL_CHARGE = {
    "2A": (400, 500), "3A": (300, 400), "CC": (125, 225), "SL": (100, 200), "2S": (10, 15),
}

# route entries are (hub code, departure HH:MM, day offset from origin)
TRAINS = [
    {"no": "12635", "name": "Vaigai SF Express", "days": "Daily", "classes": ["CC", "2S"],
     "route": [("MAS", "13:40", 0), ("CGL", "14:28", 0), ("VM", "15:33", 0), ("TPJ", "18:03", 0), ("DG", "19:38", 0), ("KQN", "20:14", 0), ("MDU", "21:10", 0)]},
    {"no": "12637", "name": "Pandian SF Express", "days": "Daily", "classes": ["1A", "2A", "3A", "SL"],
     "route": [("MAS", "21:30", 0), ("CGL", "22:18", 0), ("VM", "23:28", 0), ("TPJ", "02:05", 1), ("DG", "03:48", 1), ("KQN", "04:26", 1), ("MDU", "05:40", 1)]},
    {"no": "16101", "name": "Sethu Express", "days": "Daily", "classes": ["2A", "3A", "SL", "2S"],
     "route": [("MAS", "20:15", 0), ("CGL", "21:05", 0), ("VM", "22:20", 0), ("TPJ", "01:10", 1), ("MDU", "04:30", 1), ("RMM", "08:45", 1)]},
    {"no": "12633", "name": "Kanyakumari SF Express", "days": "Daily", "classes": ["2A", "3A", "SL"],
     "route": [("MAS", "17:25", 0), ("CGL", "18:14", 0), ("VM", "19:28", 0), ("TPJ", "22:15", 0), ("MDU", "01:35", 1), ("TEN", "04:20", 1), ("CAPE", "06:30", 1)]},
    {"no": "16177", "name": "Rockfort Express", "days": "Daily", "classes": ["2A", "3A", "SL", "2S"],
     "route": [("MAS", "22:30", 0), ("CGL", "23:20", 0), ("VM", "00:38", 1), ("TJ", "03:40", 1), ("TPJ", "05:15", 1)]},
    {"no": "16853", "name": "Cholan Express", "days": "Daily", "classes": ["3A", "SL", "2S"],
     "route": [("MAS", "08:00", 0), ("CGL", "08:52", 0), ("VM", "10:05", 0), ("TJ", "13:35", 0), ("TPJ", "15:10", 0)]},
    {"no": "16183", "name": "Uzhavan Express", "days": "Daily", "classes": ["3A", "SL", "2S"],
     "route": [("MAS", "22:45", 0), ("CGL", "23:35", 0), ("VM", "00:55", 1), ("TJ", "04:05", 1), ("VLNK", "06:20", 1)]},
    {"no": "12631", "name": "Nellai SF Express", "days": "Daily", "classes": ["2A", "3A", "SL"],
     "route": [("MAS", "19:00", 0), ("CGL", "19:48", 0), ("VM", "21:00", 0), ("TPJ", "23:45", 0), ("MDU", "03:05", 1), ("TEN", "05:45", 1)]},
    {"no": "12675", "name": "Kovai SF Express", "days": "Daily", "classes": ["CC", "2S"],
     "route": [("MAS", "06:15", 0), ("CGL", "07:02", 0), ("SA", "10:28", 0), ("ED", "11:20", 0), ("CBE", "13:05", 0)]},
    {"no": "12671", "name": "Nilgiri SF Express", "days": "Daily", "classes": ["1A", "2A", "3A", "SL"],
     "route": [("MAS", "21:15", 0), ("CGL", "22:05", 0), ("SA", "01:35", 1), ("ED", "02:30", 1), ("CBE", "04:20", 1), ("MTP", "05:45", 1)]},
    {"no": "56136", "name": "Nilgiri Mountain Railway", "days": "Daily", "classes": ["1A", "2S"],
     "route": [("MTP", "07:10", 0), ("UAM", "12:00", 0)]},
    {"no": "16723", "name": "Anantapuri Express", "days": "Daily", "classes": ["2A", "3A", "SL"],
     "route": [("MAS", "19:45", 0), ("CGL", "20:35", 0), ("VM", "21:50", 0), ("TPJ", "00:40", 1), ("MDU", "04:00", 1), ("TEN", "06:35", 1)]},
    {"no": "16232", "name": "Mayiladuthurai Express", "days": "Daily", "classes": ["SL", "2S"],
     "route": [("MDU", "06:00", 0), ("DG", "07:20", 0), ("TPJ", "09:05", 0), ("TJ", "10:30", 0)]},
    {"no": "16849", "name": "Trichy - Rameswaram Express", "days": "Daily", "classes": ["3A", "SL", "2S"],
     "route": [("TPJ", "17:30", 0), ("DG", "19:00", 0), ("MDU", "20:45", 0), ("RMM", "00:35", 1)]},
    {"no": "20681", "name": "Bengaluru - Madurai SF", "days": "Daily", "classes": ["2A", "3A", "SL"],
     "route": [("SBC", "20:50", 0), ("SA", "01:15", 1), ("DG", "04:40", 1), ("MDU", "06:15", 1)]},
    {"no": "22671", "name": "Coimbatore - Kodai Road Express", "days": "Daily", "classes": ["3A", "SL", "2S"],
     "route": [("CBE", "05:40", 0), ("ED", "07:05", 0), ("DG", "09:30", 0), ("KQN", "10:35", 0)]},
    {"no": "16860", "name": "Chennai - Kanchipuram Passenger", "days": "Daily", "classes": ["2S"],
     "route": [("MAS", "07:20", 0), ("CGL", "08:30", 0), ("CJ", "09:25", 0)]},
    {"no": "12693", "name": "Pearl City SF Express", "days": "Daily", "classes": ["2A", "3A", "SL"],
     "route": [("MAS", "19:30", 0), ("CGL", "20:20", 0), ("VM", "21:35", 0), ("TPJ", "00:25", 1), ("MDU", "03:45", 1)]},
]

# ---------------------------------------------------------------- buses

BUS_OPERATORS = [
    {"name": "TNSTC", "kind": "Government", "types": ["Non-AC Seater", "Super Deluxe"]},
    {"name": "SETC Tamil Nadu", "kind": "Government", "types": ["AC Seater", "Super Deluxe"]},
    {"name": "KPN Travels", "kind": "Private", "types": ["AC Sleeper", "Volvo Multi-Axle AC"]},
    {"name": "SRM Transports", "kind": "Private", "types": ["AC Sleeper", "Non-AC Sleeper"]},
    {"name": "Rathimeena Travels", "kind": "Private", "types": ["AC Seater", "Non-AC Seater"]},
    {"name": "Parveen Travels", "kind": "Private", "types": ["Volvo Multi-Axle AC", "AC Sleeper"]},
    {"name": "YBM Travels", "kind": "Private", "types": ["AC Sleeper", "Super Deluxe"]},
]

BUS_TYPE_RATE = {
    "Non-AC Seater": 1.05, "Super Deluxe": 1.35, "AC Seater": 1.75,
    "Non-AC Sleeper": 1.60, "AC Sleeper": 2.30, "Volvo Multi-Axle AC": 2.70,
}


# ---------------------------------------------------------------- helpers

def haversine(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _rng(*parts):
    """A generator seeded by the arguments, so the same query always yields the same result."""
    seed = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:12], 16))


def rail_km(a, b):
    return round(haversine(HUBS[a]["lat"], HUBS[a]["lon"], HUBS[b]["lat"], HUBS[b]["lon"]) * 1.22)


def road_km(a, b):
    return round(haversine(HUBS[a]["lat"], HUBS[a]["lon"], HUBS[b]["lat"], HUBS[b]["lon"]) * 1.32)


def now_ist():
    return datetime.now(IST)


def parse_date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- fares

def train_fare(cls, km, tatkal):
    c = CLASSES[cls]
    base = 40 + km * c["rate"]
    base = round(base / 5) * 5
    extra = 0
    if tatkal and c["tatkal"]:  # 1A has no Tatkal quota, so it never carries the premium
        lo, hi = TATKAL_CHARGE[cls]
        pct = 0.10 if cls == "2S" else 0.30
        extra = min(max(round(base * pct), lo), hi)
    reservation = {"1A": 60, "2A": 50, "3A": 40, "CC": 40, "SL": 20, "2S": 15}[cls]
    gst = round((base + extra) * 0.05) if c["ac"] else 0
    return {"base": base, "tatkal": extra, "reservation": reservation, "gst": gst,
            "total": base + extra + reservation + gst}


def bus_fare(bus_type, km):
    return round((60 + km * BUS_TYPE_RATE[bus_type]) / 5) * 5


# ---------------------------------------------------------------- tatkal window

def tatkal_window(journey):
    """Real IRCTC rule: Tatkal opens one day before the journey - 10:00 for AC, 11:00 for non-AC."""
    opens_on = journey - timedelta(days=1)
    now = now_ist()
    out = {"opens_on": opens_on.isoformat(), "ac_time": "10:00", "non_ac_time": "11:00"}
    if journey <= now.date():
        out.update(ac_open=False, non_ac_open=False,
                   status="closed", message="Tatkal is not available on the day of travel.")
        return out
    if now.date() < opens_on:
        out.update(ac_open=False, non_ac_open=False, status="upcoming",
                   message=f"Tatkal opens on {opens_on.strftime('%d %b')} - 10:00 AM for AC classes, 11:00 AM for Sleeper and Second Sitting.")
        return out
    hhmm = now.strftime("%H:%M")
    ac_open, non_ac_open = hhmm >= "10:00", hhmm >= "11:00"
    if ac_open and non_ac_open:
        msg = "Tatkal booking is open now."
    elif ac_open:
        msg = "Tatkal is open for AC classes. Sleeper and Second Sitting open at 11:00 AM."
    else:
        msg = "Tatkal opens at 10:00 AM for AC classes and 11:00 AM for Sleeper and Second Sitting."
    out.update(ac_open=ac_open, non_ac_open=non_ac_open,
               status="open" if (ac_open or non_ac_open) else "waiting", message=msg)
    return out


# ---------------------------------------------------------------- availability

def _held(key):
    return store.read()["held"].get(key, 0)


def availability(train_no, journey, cls, quota):
    """Returns a status dict. Deterministic per (train, date, class, quota), minus anything booked."""
    r = _rng(train_no, journey.isoformat(), cls, quota)
    if quota == "tatkal":
        if not CLASSES[cls]["tatkal"]:
            return {"code": "NA", "label": "Tatkal not offered in this class", "seats": 0, "bookable": False}
        pool = r.choice([0, 0, 2, 4, 6, 9, 12, 18])
    else:
        roll = r.random()
        if roll < 0.34:
            pool = 0
        elif roll < 0.5:
            pool = -r.randint(1, 26)  # negative pool means RAC / waitlist
        else:
            pool = r.randint(3, 120)
    key = f"{train_no}|{journey.isoformat()}|{cls}|{quota}"
    if pool > 0:
        left = max(pool - _held(key), 0)
        if left:
            return {"code": "AVL", "label": f"AVAILABLE {left}", "seats": left, "bookable": True}
        return {"code": "WL", "label": "WL 1", "seats": 0, "bookable": False}
    if pool == 0:
        if quota == "tatkal":
            return {"code": "REGRET", "label": "REGRET / NO ROOM", "seats": 0, "bookable": False}
        n = r.randint(4, 88)
        return {"code": "WL", "label": f"WL {n}", "seats": 0, "bookable": False}
    n = -pool
    if n <= 12 and cls in ("SL", "3A"):
        return {"code": "RAC", "label": f"RAC {n}", "seats": 0, "bookable": True,
                "note": "RAC gives you a shared side-lower berth; it usually clears before departure."}
    return {"code": "WL", "label": f"WL {n}", "seats": 0, "bookable": False}


# ---------------------------------------------------------------- search

def _leg(train, frm, to):
    codes = [s[0] for s in train["route"]]
    if frm not in codes or to not in codes or codes.index(frm) >= codes.index(to):
        return None
    a, b = train["route"][codes.index(frm)], train["route"][codes.index(to)]
    return a, b


def _arrive(dep_hm, dep_day, arr_hm, arr_day):
    d0 = datetime.strptime(dep_hm, "%H:%M") + timedelta(days=dep_day)
    d1 = datetime.strptime(arr_hm, "%H:%M") + timedelta(days=arr_day)
    mins = int((d1 - d0).total_seconds() // 60)
    return mins


def search_trains(frm, to, journey, quota="general"):
    out = []
    for t in TRAINS:
        leg = _leg(t, frm, to)
        if not leg:
            continue
        (_, dep, dep_day), (_, arr, arr_day) = leg
        mins = _arrive(dep, dep_day, arr, arr_day)
        km = rail_km(frm, to)
        classes = []
        for cls in t["classes"]:
            av = availability(t["no"], journey, cls, quota)
            classes.append({"cls": cls, "label": CLASSES[cls]["label"], "ac": CLASSES[cls]["ac"],
                            "fare": train_fare(cls, km, quota == "tatkal"),
                            "availability": av})
        out.append({
            "no": t["no"], "name": t["name"], "days": t["days"],
            "from": frm, "from_name": HUBS[frm]["name"], "to": to, "to_name": HUBS[to]["name"],
            "depart": dep, "arrive": arr, "arrive_next_day": arr_day > dep_day,
            "duration": f"{mins // 60}h {mins % 60:02d}m", "km": km, "classes": classes,
            "any_bookable": any(c["availability"]["bookable"] for c in classes),
        })
    out.sort(key=lambda t: t["depart"])
    return out


def search_buses(frm, to, journey):
    km = road_km(frm, to)
    if km < 8:
        return []
    r = _rng("bus", frm, to, journey.isoformat())
    count = r.randint(5, 9)
    out = []
    for i in range(count):
        op = r.choice(BUS_OPERATORS)
        bus_type = r.choice(op["types"])
        hour = r.choice([6, 7, 8, 9, 11, 14, 16, 19, 20, 21, 21, 22, 22, 23])
        minute = r.choice([0, 15, 20, 30, 40, 45])
        mins = int(km / r.uniform(38, 52) * 60) + r.randint(10, 45)
        dep = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M")
        arr = dep + timedelta(minutes=mins)
        seats_total = 36 if "Sleeper" in bus_type else 44
        key = f"BUS|{op['name']}|{bus_type}|{frm}|{to}|{journey.isoformat()}|{i}"
        taken = sorted(r.sample(range(1, seats_total + 1), r.randint(2, seats_total - 6)))
        left = seats_total - len(taken) - _held(key)
        out.append({
            "id": f"{frm}-{to}-{i}", "key": key, "operator": op["name"], "kind": op["kind"],
            "type": bus_type, "ac": "AC" in bus_type or "Volvo" in bus_type,
            "sleeper": "Sleeper" in bus_type,
            "from": frm, "from_name": HUBS[frm]["name"], "to": to, "to_name": HUBS[to]["name"],
            "depart": dep.strftime("%H:%M"), "arrive": arr.strftime("%H:%M"),
            "arrive_next_day": arr.day > dep.day,
            "duration": f"{mins // 60}h {mins % 60:02d}m", "km": km,
            "fare": bus_fare(bus_type, km), "rating": round(r.uniform(3.2, 4.8), 1),
            "seats_total": seats_total, "taken": taken, "seats_left": max(left, 0),
        })
    out.sort(key=lambda b: b["depart"])
    return out


def nearest_hubs(lat, lon, limit=6, rail_only=False):
    rows = []
    for code, h in HUBS.items():
        if rail_only and not h["rail"]:
            continue
        rows.append({"code": code, "name": h["name"], "city": h["city"], "rail": h["rail"],
                     "km": round(haversine(lat, lon, h["lat"], h["lon"]), 1)})
    rows.sort(key=lambda x: x["km"])
    return rows[:limit]


# ---------------------------------------------------------------- booking

def _pnr():
    return str(secrets.randbelow(9_000_000_000) + 1_000_000_000)


def _ticket_no():
    return "TN" + str(secrets.randbelow(900_000) + 100_000)


def book(user, payload):
    kind = payload.get("kind")
    passengers = payload.get("passengers") or []
    if kind not in ("train", "bus"):
        return None, "Unknown booking type."
    if not 1 <= len(passengers) <= 6:
        return None, "Add between 1 and 6 passengers."
    for p in passengers:
        if not (p.get("name") or "").strip():
            return None, "Every passenger needs a name."
        age = p.get("age")
        if not isinstance(age, int) or not 1 <= age <= 120:
            return None, "Enter a valid age for every passenger."
    journey = parse_date(payload.get("date"))
    if not journey or journey < now_ist().date():
        return None, "Choose a journey date that has not passed."

    db = store.read()
    if kind == "train":
        quota = payload.get("quota", "general")
        cls = payload.get("cls")
        if cls not in CLASSES:
            return None, "Choose a travel class."
        if quota == "tatkal":
            win = tatkal_window(journey)
            open_now = win["ac_time" if CLASSES[cls]["ac"] else "non_ac_time"]
            if not (win["ac_open"] if CLASSES[cls]["ac"] else win["non_ac_open"]):
                return None, f"Tatkal for {CLASSES[cls]['label']} is not open yet - it opens at {open_now} on {win['opens_on']}."
            if len(passengers) > 4:
                return None, "Tatkal allows a maximum of 4 passengers per booking."
        av = availability(payload["train_no"], journey, cls, quota)
        if not av["bookable"]:
            return None, f"That class is {av['label']} - no seats to confirm."
        if av["code"] == "AVL" and av["seats"] < len(passengers):
            return None, f"Only {av['seats']} seat(s) left in that class."
        key = f"{payload['train_no']}|{journey.isoformat()}|{cls}|{quota}"
        db["held"][key] = db["held"].get(key, 0) + len(passengers)
        km = rail_km(payload["from"], payload["to"])
        fare = train_fare(cls, km, quota == "tatkal")
        rec = {
            "id": secrets.token_hex(8), "kind": "train", "pnr": _pnr(), "user": user["email"],
            "train_no": payload["train_no"], "train_name": payload.get("train_name", ""),
            "from": payload["from"], "from_name": HUBS[payload["from"]]["name"],
            "to": payload["to"], "to_name": HUBS[payload["to"]]["name"],
            "date": journey.isoformat(), "depart": payload.get("depart"), "arrive": payload.get("arrive"),
            "cls": cls, "cls_label": CLASSES[cls]["label"], "quota": quota,
            "status": "RAC" if av["code"] == "RAC" else "CONFIRMED",
            "passengers": passengers, "fare_each": fare, "total": fare["total"] * len(passengers),
            "booked_at": now_ist().isoformat(timespec="seconds"),
        }
    else:
        seats = payload.get("seats") or []
        if len(seats) != len(passengers):
            return None, "Pick one seat per passenger."
        key = payload.get("key", "")
        db["held"][key] = db["held"].get(key, 0) + len(passengers)
        rec = {
            "id": secrets.token_hex(8), "kind": "bus", "ticket": _ticket_no(), "user": user["email"],
            "operator": payload.get("operator"), "type": payload.get("type"),
            "from": payload["from"], "from_name": HUBS[payload["from"]]["name"],
            "to": payload["to"], "to_name": HUBS[payload["to"]]["name"],
            "date": journey.isoformat(), "depart": payload.get("depart"), "arrive": payload.get("arrive"),
            "seats": seats, "status": "CONFIRMED", "passengers": passengers,
            "fare_each": {"total": payload.get("fare", 0)},
            "total": (payload.get("fare") or 0) * len(passengers),
            "booked_at": now_ist().isoformat(timespec="seconds"),
        }
    db["bookings"].append(rec)
    store.commit()
    return rec, None


def bookings_for(email):
    rows = [b for b in store.read()["bookings"] if b["user"] == email]
    rows.sort(key=lambda b: b["booked_at"], reverse=True)
    return rows


def cancel(email, booking_id):
    db = store.read()
    for b in db["bookings"]:
        if b["id"] == booking_id and b["user"] == email:
            if b["status"] == "CANCELLED":
                return None, "That booking is already cancelled."
            b["status"] = "CANCELLED"
            store.commit()
            return b, None
    return None, "Booking not found."
