"""Things to do in each town, derived from data.py - nothing here is invented.

Every activity comes from a town's `highlights` or its `worship` list. What this module ADDS is a rough guess at
how long each takes and what kind of thing it is, using keyword rules. Those two guesses (duration, tags) are
estimates, and so are the opening windows of anything that is not a place of worship. Places of worship keep the
real opening sessions from the data (many close at midday), and everything else is marked `indicative`.
"""

import re

from data import DESTINATIONS

# user-facing interest -> internal tags
INTERESTS = {"temples": {"religious"}, "heritage": {"heritage", "craft"}, "nature": {"nature"}, "beaches": {"beach"}, "food": {"food"}}

_RULES = [
    ("food", r"\b(idli|dosai|dosa|jigarthanda|filter coffee|biryani|meals)\b"),
    ("beach", r"\b(beach|sea-shore|dhanushkodi|sangamam|sunrise)\b"),
    ("nature", r"\b(lake|falls|cascade|garden|park|peak|rocks|walk|river|boating|valley|tea factory|bridge|railway)\b"),
    ("craft", r"\b(workshops?|weaving|cooperatives|painting)\b"),
    ("heritage", r"\b(palace|fort|museum|library|memorial|mandapam|rathas|penance|butter ball|ghost town|statue|nearby)\b"),
    ("religious", r"\b(temple|church|basilica|dargah|masjid|mosque|theerthams|bathing|kovil|corridors)\b"),
]
_DURATION = {"food": 1.0, "beach": 1.5, "nature": 2.0, "craft": 1.0, "heritage": 1.5, "religious": 1.5}
_STOP = {"temple", "church", "masjid", "mosque", "dargah", "basilica", "amman", "the", "of", "and", "towers", "corridors", "big", "good", "health", "our", "lady", "km"}
DEFAULT_OPEN = [("09:00", "17:30")]
BEACH_OPEN = [("06:00", "19:00")]
FOOD_OPEN = [("12:00", "14:30"), ("19:00", "21:30")]


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _key(text):
    """Words that identify a place, for spotting a highlight that is the same place as a worship entry."""
    words = re.sub(r"[^a-z ]", " ", text.lower()).split()
    return {w for w in words if w not in _STOP}


def _tags(text):
    t = {tag for tag, rx in _RULES if re.search(rx, text.lower())}
    return t or {"heritage"}


def _build():
    out = {}
    for d in DESTINATIONS:
        acts, worship = [], list(d["worship"])
        dup = set()
        for w in worship:                                           # places of worship: the data's real opening sessions
            kind_hours = 1.5 if w["type"] == "temple" else 1.0
            acts.append({"id": f"{d['id']}:{_slug(w['name'])}", "place": d["id"], "name": w["name"], "tags": ["religious"],
                         "hours": kind_hours, "open": [(a, b) for a, b in w["sessions"]], "indicative": False, "outdoor": False,
                         "note": w.get("note") or "", "iconic": False, "excursion": False, "kind": w["type"]})
        for idx, text in enumerate(d["highlights"]):
            same = next((a for a in acts if a["kind"] in ("temple", "church", "mosque") and (a["name"].lower() == text.lower() or
                                                                                              (_key(text) and _key(text) == _key(a["name"])))), None)
            if same:
                same["iconic"] = same["iconic"] or idx == 0         # the highlight IS this place: keep the real hours, remember it is a headline sight
                continue
            tags = _tags(text)
            low = text.lower()
            excursion = "nearby" in low
            hours = 3.5 if excursion else 3.0 if "railway" in low else 1.0 if "sunrise" in low else max(_DURATION[t] for t in tags)
            if "sunrise" in low:
                window = [("05:30", "07:30")]
            elif "food" in tags:
                window = FOOD_OPEN
            elif "beach" in tags and "dhanushkodi" not in low:
                window = BEACH_OPEN
            else:
                window = DEFAULT_OPEN
            acts.append({"id": f"{d['id']}:{_slug(text)}", "place": d["id"], "name": text, "tags": sorted(tags), "hours": hours, "open": window,
                         "indicative": True, "outdoor": bool(tags & {"nature", "beach"}), "note": "", "iconic": idx == 0, "excursion": excursion, "kind": "sight"})
        out[d["id"]] = acts
    return out


ACTIVITIES = _build()
BY_ID = {a["id"]: a for acts in ACTIVITIES.values() for a in acts}


def interest_tags(interests):
    tags = set()
    for i in interests:
        tags |= INTERESTS.get(i, set())
    return tags


def value(activity, tags, rain=False):
    """How much this activity is worth to this traveller. Matching an interest triples it; a town's headline
    sight gets a bonus; outdoor things are heavily discounted when rain is forecast."""
    v = 3.0 if (set(activity["tags"]) & tags) else 1.0
    if activity["iconic"]:
        v += 1.5
    if activity["excursion"]:
        v -= 0.5
    if rain and activity["outdoor"]:
        v *= 0.3
    return v
