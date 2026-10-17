"""Live train timetables from RailRadar (https://railradar.in), with a disk cache and a safe fallback.

What is live: which trains run between two stations, their real numbers, names, times and running days.
What is NOT live: seat availability and fares. RailRadar's free plan has no seat data, so those stay simulated.

The free plan allows 100 requests a month, so every answer is cached for a day, a failure is remembered for an hour,
and the module stops calling at MONTHLY_BUDGET. Whenever the key is missing, the quota is spent or the service is down,
`between` returns None and the caller uses the built-in timetable instead. The key is read from RAIL_API_KEY
(set it in backend/.env, which git ignores) and is never logged or sent anywhere except api.railradar.in.
"""

import json
import os
import time

import requests

import store

BASE = "https://api.railradar.in/v1"
TTL, FAIL_TTL, MONTHLY_BUDGET = 24 * 3600, 3600, 90
_CACHE_FILE = "rail_cache.json"


def load_env(path=None):
    """Read KEY=value lines from backend/.env into the environment, never overriding what is already set."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except OSError:
        pass


def key():
    return (os.environ.get("RAIL_API_KEY") or "").strip()


def enabled():
    return bool(key())


def _path():
    return os.path.join(os.environ.get("DATA_DIR") or store.DATA_DIR, _CACHE_FILE)


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(cache):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, _path())


def _parse(payload):
    """RailRadar's trains-between answer -> a short list of {no, name, type, days, depart, arrive, dep_day, arr_day, km}."""
    rows = []
    for item in (payload.get("data") or {}).get("trains") or []:
        try:
            t, a, b = item["train"], item["from"], item["to"]
            rows.append({"no": str(t["number"]), "name": t["name"], "type": t.get("type") or "",
                         "days": [d.lower() for d in t.get("runDays") or []],
                         "depart": a["departure"], "dep_day": int(a.get("day") or 1) - 1,
                         "arrive": b["arrival"], "arr_day": int(b.get("day") or 1) - 1,
                         "km": float(item.get("distance") or 0)})
        except (KeyError, TypeError, ValueError):
            continue                                              # skip a malformed row, keep the rest
    return rows


def between(frm, to, now=None):
    """Live trains from station code `frm` to `to`, or None when live data is unavailable (use the static timetable)."""
    if not enabled():
        return None
    now = now if now is not None else time.time()
    k = f"{frm}>{to}"
    cache = _load()
    hit = cache.get("routes", {}).get(k)
    if hit and now - hit["at"] < (TTL if hit["ok"] else FAIL_TTL):
        return hit["rows"] if hit["ok"] else None
    month = time.strftime("%Y-%m", time.gmtime(now))
    used = cache.get("usage", {})
    if used.get("month") != month:
        used = {"month": month, "calls": 0}
    if used["calls"] >= MONTHLY_BUDGET:
        return None
    rows, ok = [], False
    used["calls"] += 1                                            # count the attempt: a failed call may still use quota
    try:
        r = requests.get(f"{BASE}/trains/between/{frm}/{to}", headers={"Authorization": f"Bearer {key()}"}, timeout=8)
        if r.status_code == 200:
            payload = r.json()
            if payload.get("success"):
                rows, ok = _parse(payload), True
    except (requests.RequestException, ValueError):
        pass
    cache["usage"] = used
    cache.setdefault("routes", {})[k] = {"at": now, "ok": ok, "rows": rows}
    try:
        _save(cache)
    except OSError:
        pass
    return rows if ok else None


def status():
    cache = _load()
    return {"enabled": enabled(), "usage": cache.get("usage"), "budget": MONTHLY_BUDGET}
