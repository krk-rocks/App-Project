"""Verified reviews with photos, helpful votes, reporting and an admin moderation queue.

* VERIFIED: only someone with a paid, uncancelled booking for the town whose trip has already happened can
  review it. A booking is the proof; there is no "I swear I went".
* ONE review per person per town. Posting again edits it.
* PHOTOS are untrusted input. Each is decoded with Pillow (so a text file renamed .jpg is refused), rotated to
  upright, re-encoded as a fresh JPEG - which also drops EXIF, where phones hide GPS coordinates - and saved
  under a random name. Nothing from the upload's filename or content-type is used.
* RATINGS use a Bayesian average, so one 5-star review does not outrank forty 4.6-star ones.
* MODERATION is a queue, not a filter: spam heuristics reject the obvious at the door, readers can report, and
  three different reporters hide a review until an admin (ADMIN_EMAILS) restores or removes it.
"""

import io
import os
import re
import secrets
from datetime import datetime, timedelta

from PIL import Image, ImageOps

import bookings
import clock
import store
from data import DESTINATIONS

PLACES = {d["id"] for d in DESTINATIONS}
MIN_TEXT, MAX_TEXT, MAX_TITLE = 20, 1500, 80
MAX_PHOTOS, MAX_PHOTO_BYTES, MAX_SIDE = 3, 5 * 1024 * 1024, 1600
DAILY_LIMIT, REPORTS_TO_HIDE = 3, 3
PRIOR_WEIGHT, PRIOR_MEAN = 5, 4.0
VISIBLE, FLAGGED, REMOVED = "visible", "flagged", "removed"

Image.MAX_IMAGE_PIXELS = 40_000_000          # refuse decompression bombs
_LINK = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|in|net|org|co|io|xyz|info)\b", re.I)
_NAME_OK = re.compile(r"^[0-9a-f]{32}\.jpg$")


class ReviewError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def admins():
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(user):
    return bool(user) and user["email"].lower() in admins()


def display_name(email):
    name = (store.read()["users"].get(email) or {}).get("name") or email.split("@")[0]
    parts = name.split()
    return parts[0] if len(parts) < 2 else f"{parts[0]} {parts[-1][0]}."


# ------------------------------------------------------------------ eligibility

def eligibility(user, place):
    """(can_review, reason, booking_id). Proof of travel is a live booking for that town in the past."""
    if place not in PLACES:
        raise ReviewError("Unknown destination.", 404)
    if not user:
        return False, "Sign in to write a review.", None
    today = clock.today().isoformat()
    upcoming = False
    for b in store.read()["bookings"]:
        if b["user"] != user["email"] or b.get("place") != place or b["status"] not in bookings.LIVE:
            continue
        done = b["check_out"] <= today if b["kind"] == "hotel" else b["date"] <= today
        if done:
            return True, None, b["id"]
        upcoming = True
    if upcoming:
        return False, "You can review once your trip is done.", None
    return False, "Reviews come from travellers. Book a trip here and you can review it afterwards.", None


# ------------------------------------------------------------------ validation

def clean_text(rating, title, text, user_email, place):
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ReviewError("Choose a rating from 1 to 5.")
    title, text = (title or "").strip(), (text or "").strip()
    if len(title) > MAX_TITLE:
        raise ReviewError(f"Keep the title under {MAX_TITLE} characters.")
    if len(text) < MIN_TEXT:
        raise ReviewError(f"Tell us a little more: at least {MIN_TEXT} characters.")
    if len(text) > MAX_TEXT:
        raise ReviewError(f"Reviews are limited to {MAX_TEXT} characters.")
    if _LINK.search(title) or _LINK.search(text):
        raise ReviewError("Links aren't allowed in reviews.")
    letters = [c for c in text if c.isalpha()]
    if len(letters) > 30 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        raise ReviewError("Please don't write in all capitals.")
    if re.search(r"(.)\1{9,}", text) or re.search(r"\b(\w+)(?:\s+\1\b){5,}", text, re.I):
        raise ReviewError("That looks like spam. Please write a real review.")
    for r in store.read()["reviews"]:
        if r["user"] == user_email and r["place"] != place and r["text"].strip().lower() == text.lower() and r["status"] != REMOVED:
            raise ReviewError("You've already posted this exact review for another place.")
    return title, text


# ------------------------------------------------------------------ photos

def process_photo(raw):
    """Untrusted bytes in, a safe JPEG filename out. Raises ReviewError for anything that isn't a real image."""
    if len(raw) > MAX_PHOTO_BYTES:
        raise ReviewError(f"Each photo must be under {MAX_PHOTO_BYTES // (1024 * 1024)} MB.")
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ("JPEG", "PNG", "WEBP"):
            raise ReviewError("Photos must be JPEG, PNG or WebP.")
        probe.verify()                                   # catches truncated or corrupt data
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im)                 # honour the phone's rotation before we drop EXIF
        im = im.convert("RGB")
    except ReviewError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ReviewError("That file isn't a valid image.")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    os.makedirs(store.UPLOAD_DIR, exist_ok=True)
    name = secrets.token_hex(16) + ".jpg"
    im.save(os.path.join(store.UPLOAD_DIR, name), "JPEG", quality=82, optimize=True)   # no exif= argument: metadata is gone
    return name


def delete_photos(names):
    for n in names:
        if _NAME_OK.match(n):
            try:
                os.remove(os.path.join(store.UPLOAD_DIR, n))
            except OSError:
                pass


def safe_upload_path(name):
    return os.path.join(store.UPLOAD_DIR, name) if _NAME_OK.match(name or "") and os.path.exists(os.path.join(store.UPLOAD_DIR, name)) else None


# ------------------------------------------------------------------ create / edit / delete

def save(user, place, rating, title, text, photo_bytes=None, remove_photos=False):
    """Create or edit the caller's review of a place. Returns (review, created)."""
    ok, reason, booking_id = eligibility(user, place)
    if not ok:
        raise ReviewError(reason, 403)
    photo_bytes = photo_bytes or []
    if len(photo_bytes) > MAX_PHOTOS:
        raise ReviewError(f"Add up to {MAX_PHOTOS} photos.")
    title, text = clean_text(rating, title, text, user["email"], place)
    with store.TX:
        db = store.read()
        mine = next((r for r in db["reviews"] if r["user"] == user["email"] and r["place"] == place and r["status"] != REMOVED), None)
        if not mine:
            since = (clock.now() - timedelta(hours=24)).isoformat()
            if sum(1 for r in db["reviews"] if r["user"] == user["email"] and r["created"] >= since) >= DAILY_LIMIT:
                raise ReviewError(f"You can post up to {DAILY_LIMIT} reviews a day. Try again tomorrow.", 429)
        new_files = [process_photo(b) for b in photo_bytes]       # all-or-nothing: one bad photo rejects the lot
        now = clock.now().isoformat(timespec="seconds")
        if mine:
            if new_files or remove_photos:
                delete_photos(mine["photos"])
                mine["photos"] = new_files
            mine.update({"rating": rating, "title": title, "text": text, "edited": now})
            rec, created = mine, False
        else:
            rec = {"id": "rev_" + secrets.token_hex(6), "place": place, "user": user["email"], "rating": rating, "title": title,
                   "text": text, "photos": new_files, "created": now, "edited": None, "helpful": [], "reports": {},
                   "status": VISIBLE, "booking": booking_id}
            db["reviews"].append(rec)
            created = True
        store.commit()
        return rec, created


def delete_mine(user, place):
    with store.TX:
        db = store.read()
        mine = next((r for r in db["reviews"] if r["user"] == user["email"] and r["place"] == place), None)
        if not mine:
            raise ReviewError("You haven't reviewed this place.", 404)
        delete_photos(mine["photos"])
        db["reviews"].remove(mine)
        store.commit()


# ------------------------------------------------------------------ reading

def _view(r, viewer):
    email = viewer["email"] if viewer else None
    return {"id": r["id"], "place": r["place"], "name": display_name(r["user"]), "rating": r["rating"], "title": r["title"],
            "text": r["text"], "photos": [f"/api/uploads/{n}" for n in r["photos"]], "created": r["created"], "edited": r["edited"],
            "verified": True, "helpful": len(r["helpful"]), "mine": r["user"] == email, "voted": email in r["helpful"],
            "status": r["status"] if r["user"] == email else VISIBLE}


def summary(place):
    rs = [r for r in store.read()["reviews"] if r["place"] == place and r["status"] == VISIBLE]
    n = len(rs)
    dist = {str(i): sum(1 for r in rs if r["rating"] == i) for i in range(1, 6)}
    total = sum(r["rating"] for r in rs)
    return {"count": n, "average": round(total / n, 1) if n else None,
            "score": round((PRIOR_WEIGHT * PRIOR_MEAN + total) / (PRIOR_WEIGHT + n), 2) if n else None, "distribution": dist}


def listing(place, viewer, sort="helpful", limit=10, offset=0):
    if place not in PLACES:
        raise ReviewError("Unknown destination.", 404)
    rs = [r for r in store.read()["reviews"] if r["place"] == place and r["status"] == VISIBLE]
    rs.sort(key=(lambda r: r["created"]), reverse=True)                                   # newest first
    if sort != "newest":
        rs.sort(key=lambda r: len(r["helpful"]), reverse=True)                            # stable: ties stay newest first
    limit, offset = max(1, min(30, limit)), max(0, offset)
    mine = next((r for r in store.read()["reviews"] if viewer and r["user"] == viewer["email"] and r["place"] == place and r["status"] != REMOVED), None)
    ok, reason, _ = eligibility(viewer, place)
    return {"summary": summary(place), "reviews": [_view(r, viewer) for r in rs[offset:offset + limit]], "total": len(rs),
            "mine": _view(mine, viewer) if mine else None, "can_review": ok and not mine, "can_edit": bool(mine),
            "reason": None if ok else reason}


# ------------------------------------------------------------------ votes, reports, moderation

def _find(review_id):
    r = next((x for x in store.read()["reviews"] if x["id"] == review_id and x["status"] != REMOVED), None)
    if not r:
        raise ReviewError("Review not found.", 404)
    return r


def toggle_helpful(user, review_id):
    with store.TX:
        r = _find(review_id)
        if r["status"] != VISIBLE:
            raise ReviewError("Review not found.", 404)
        if r["user"] == user["email"]:
            raise ReviewError("You can't vote on your own review.")
        if user["email"] in r["helpful"]:
            r["helpful"].remove(user["email"])
        else:
            r["helpful"].append(user["email"])
        store.commit()
        return {"helpful": len(r["helpful"]), "voted": user["email"] in r["helpful"]}


def report(user, review_id, reason):
    with store.TX:
        r = _find(review_id)
        if r["user"] == user["email"]:
            raise ReviewError("You can't report your own review.")
        r["reports"][user["email"]] = (reason or "").strip()[:200] or "No reason given"      # one report per person
        if r["status"] == VISIBLE and len(r["reports"]) >= REPORTS_TO_HIDE:
            r["status"] = FLAGGED
        store.commit()
        return {"reported": True, "hidden": r["status"] == FLAGGED}


def queue(status=FLAGGED):
    rows = [r for r in store.read()["reviews"] if r["status"] == status]
    return [{**_view(r, None), "user": r["user"], "reports": r["reports"], "status": r["status"]} for r in rows]


def moderate(review_id, action):
    with store.TX:
        r = next((x for x in store.read()["reviews"] if x["id"] == review_id), None)
        if not r:
            raise ReviewError("Review not found.", 404)
        if action == "approve":
            r["status"], r["reports"] = VISIBLE, {}
        elif action == "remove":
            r["status"] = REMOVED
            delete_photos(r["photos"])
            r["photos"] = []
        else:
            raise ReviewError("Unknown action.")
        store.commit()
        return r["status"]
