"""Crowd forecast: how busy a town is likely to be on a given date.

A transparent scoring model, not machine learning - every point it awards is shown to the user as a
reason ("Weekend", "Festival season: ..."). There is no visitor-count data behind this, so the output is
a guide to relative busyness, never a measured figure.

Honest limits, which the UI repeats:
  * Festival dates in data.py are month-level ("April/May") because lunar festivals move every year, so
    those add a modest "festival season" bump rather than pointing at an exact day.
  * Only solar-calendar holidays (Pongal, Republic Day, Christmas ...) and the one exact window in the data
    (Velankanni's feast, Aug 29 - Sep 8) are dated precisely.
"""

import re
from datetime import date, timedelta

from data import DESTINATIONS

BY_ID = {d["id"]: d for d in DESTINATIONS}
LEVELS = ("Low", "Medium", "High")
LOW_BELOW, HIGH_FROM = 1.6, 2.8

_MONTH_NUM = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTH_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_WINDOW_RE = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})\s*[-–]\s*([A-Za-z]{3,9})\s+(\d{1,2})\b")


def months_in(text):
    """'April/May' -> {4, 5}; 'January & July' -> {1, 7}; 'Winter' -> {12, 1, 2}; 'Once every 12 years' -> {}."""
    found = {_MONTH_NUM[m.group(1).lower()] for m in _MONTH_RE.finditer(text or "")}
    if "winter" in (text or "").lower():
        found |= {12, 1, 2}
    return found


def best_months(text):
    """'March to June and September to November' -> {3,4,5,6,9,10,11}. Ranges wrap the year end."""
    out = set()
    for part in re.split(r"\band\b", text or ""):
        ms = [_MONTH_NUM[m.group(1).lower()] for m in _MONTH_RE.finditer(part)]
        if " to " in part and len(ms) == 2:
            m = ms[0]
            while True:
                out.add(m)
                if m == ms[1]:
                    break
                m = m % 12 + 1
        else:
            out |= set(ms)
    return out


def exact_window(text):
    """'Aug 29 - Sep 8' -> ((8, 29), (9, 8)), otherwise None."""
    m = _WINDOW_RE.search(text or "")
    if not m:
        return None
    a, b = _MONTH_NUM.get(m.group(1)[:3].lower()), _MONTH_NUM.get(m.group(3)[:3].lower())
    return ((a, int(m.group(2))), (b, int(m.group(4)))) if a and b else None


def in_window(d, start, end):
    """Is (month, day) of d inside [start, end], where the window may wrap the year end?"""
    md = (d.month, d.day)
    return start <= md <= end if start <= end else md >= start or md <= end


# (label, start, end, points, only for these categories - None means everywhere)
HOLIDAYS = [
    ("New Year's Day", (1, 1), (1, 1), 1.5, None),
    ("Pongal holidays", (1, 14), (1, 17), 2.0, None),
    ("Republic Day", (1, 26), (1, 26), 1.0, None),
    ("Tamil New Year", (4, 14), (4, 14), 1.5, None),
    ("Summer school holidays (approx.)", (4, 20), (6, 5), 1.0, {"Hill Station", "Coastal"}),
    ("Summer school holidays (approx.)", (4, 20), (6, 5), 0.5, {"City", "Heritage", "Temple Town", "Pilgrimage"}),
    ("Independence Day", (8, 15), (8, 15), 1.0, None),
    ("Gandhi Jayanti", (10, 2), (10, 2), 1.0, None),
    ("Diwali season (exact date varies)", (10, 17), (11, 14), 1.0, None),
    ("Christmas and year-end holidays", (12, 24), (12, 31), 1.5, None),
]

# Parsed once from the destination data.
_BEST = {d["id"]: best_months(d["best_time"]) for d in DESTINATIONS}
_EVENTS = {}
for _d in DESTINATIONS:
    _rows = []
    for _e in _d["events"]:
        _rows.append({"name": _e["name"], "label": _e["month"], "months": months_in(_e["month"]), "window": exact_window(_e["month"])})
    _EVENTS[_d["id"]] = _rows


def score_day(dest_id, d):
    """Returns (score, factors) for one date. factors is a list of {label, points}."""
    dest = BY_ID[dest_id]
    f = []
    if d.weekday() >= 5:
        f.append(("Weekend", 1.0))
    for label, a, b, pts, cats in HOLIDAYS:
        if (cats is None or dest["category"] in cats) and in_window(d, a, b):
            f.append((label, pts))
    if d.month in _BEST[dest_id]:
        f.append(("Peak travel season", 0.8))
    else:
        f.append(("Off-season", -0.5))
    season = [e for e in _EVENTS[dest_id] if not e["window"] and d.month in e["months"]]
    if season:
        names = ", ".join(e["name"] for e in season[:2]) + (f" +{len(season) - 2} more" if len(season) > 2 else "")
        f.append((f"Festival season: {names} (exact dates vary)", min(1.2, 0.6 * len(season))))
    for e in _EVENTS[dest_id]:
        if e["window"] and in_window(d, *e["window"]):
            f.append((f"{e['name']} ({e['label']})", 3.5))   # a dated, headline event outweighs the off-season dip
    return round(sum(p for _, p in f), 2), [{"label": l, "points": p} for l, p in f]


def level_of(score):
    return "Low" if score < LOW_BELOW else "High" if score >= HIGH_FROM else "Medium"


def day_forecast(dest_id, d):
    score, factors = score_day(dest_id, d)
    return {"date": d.isoformat(), "level": level_of(score), "score": score, "factors": factors}


def forecast(dest_id, start, days):
    if dest_id not in BY_ID:
        raise KeyError(dest_id)
    return [day_forecast(dest_id, start + timedelta(days=i)) for i in range(days)]


def price_factor(level):
    """Used by hotel pricing: busy nights cost more, quiet ones slightly less."""
    return {"Low": 0.92, "Medium": 1.0, "High": 1.25}[level]


def quieter_dates(dest_id, target, window=7, limit=3, today=None):
    """Nearby dates that are less busy than `target`, quietest first, then nearest to it."""
    base = score_day(dest_id, target)[0]
    out = []
    for off in range(-window, window + 1):
        d = target + timedelta(days=off)
        if off == 0 or (today and d < today):
            continue
        sc = score_day(dest_id, d)[0]
        if sc < base:
            out.append((sc, abs(off), d))
    out.sort()
    return [{"date": d.isoformat(), "score": sc, "level": level_of(sc), "days_away": off} for sc, off, d in out[:limit]]
