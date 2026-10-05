"""Tiny JSON-file store for users and bookings.

Not a database - this is a demo app, so a single file re-read under a lock is plenty and keeps
the project dependency-free. Everything is kept in memory and flushed on every write.
"""

import json
import os
import threading

# DATA_DIR lets a host point the store at a mounted disk. Serverless and container
# filesystems are often read-only or wiped on restart, so WRITABLE is probed once at
# startup and the app degrades to in-memory rather than crashing on the first signup.
DATA_DIR = os.environ.get("DATA_DIR") or os.path.dirname(__file__)
PATH = os.path.join(DATA_DIR, "store.json")
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


def _probe():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        probe = PATH + ".probe"
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


WRITABLE = _probe()


def commit():
    """Persist to disk when we can. On a read-only host the data stays in memory for the
    life of the process - fine for a demo, but accounts and bookings reset on restart."""
    if not WRITABLE:
        return False
    with _LOCK:
        tmp = PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_DB, f, indent=2)
            os.replace(tmp, PATH)
        except OSError:
            return False
    return True
