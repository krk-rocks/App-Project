"""Tiny JSON-file store for users and bookings.

Not a database - this is a demo app, so a single file re-read under a lock is plenty and keeps
the project dependency-free. Everything is kept in memory and flushed on every write.
"""

import json
import os
import threading

PATH = os.path.join(os.path.dirname(__file__), "store.json")
_LOCK = threading.Lock()
_EMPTY = {"users": {}, "tokens": {}, "bookings": [], "held": {}}


def _read():
    if not os.path.exists(PATH):
        return json.loads(json.dumps(_EMPTY))
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_EMPTY))
    for k, v in _EMPTY.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


_DB = _read()


def read():
    return _DB


def commit():
    with _LOCK:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_DB, f, indent=2)
        os.replace(tmp, PATH)
