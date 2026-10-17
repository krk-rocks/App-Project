"""HTTP routes for reviews, photo uploads and moderation."""

from flask import Blueprint, g, jsonify, request, send_from_directory

import auth
import reviews
import store

bp = Blueprint("reviews", __name__)


@bp.errorhandler(reviews.ReviewError)
def _review_error(e):
    return jsonify({"error": e.message}), e.status


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _require_admin():
    if not reviews.is_admin(g.user):
        raise reviews.ReviewError("Admins only.", 403)


@bp.get("/api/destinations/<place>/reviews")
def list_reviews(place):
    return jsonify(reviews.listing(place, auth.current_user(), request.args.get("sort", "helpful"),
                                   _int(request.args.get("limit"), 10), _int(request.args.get("offset"), 0)))


@bp.post("/api/destinations/<place>/reviews")
@auth.require_auth
def post_review(place):
    if request.is_json:                         # no photos: plain JSON (used by tests and simple clients)
        body = request.get_json(silent=True) or {}
        rating, title, text, files, remove = body.get("rating"), body.get("title"), body.get("text"), [], False
    else:                                       # multipart: the browser form, with up to three photos
        f = request.form
        rating = _int(f.get("rating"), None)
        title, text, remove = f.get("title"), f.get("text"), f.get("remove_photos") == "1"
        files = [p.read(reviews.MAX_PHOTO_BYTES + 1) for p in request.files.getlist("photos") if p and p.filename]
    rec, created = reviews.save(g.user, place, rating, title, text, files, remove)
    return jsonify({"review": reviews._view(rec, g.user), "summary": reviews.summary(place)}), 201 if created else 200


@bp.delete("/api/destinations/<place>/reviews/mine")
@auth.require_auth
def delete_review(place):
    reviews.delete_mine(g.user, place)
    return jsonify({"deleted": True, "summary": reviews.summary(place)})


@bp.post("/api/reviews/<review_id>/helpful")
@auth.require_auth
def helpful(review_id):
    return jsonify(reviews.toggle_helpful(g.user, review_id))


@bp.post("/api/reviews/<review_id>/report")
@auth.require_auth
def report(review_id):
    body = request.get_json(silent=True)
    return jsonify(reviews.report(g.user, review_id, (body or {}).get("reason") if isinstance(body, dict) else None))


@bp.get("/api/admin/reviews")
@auth.require_auth
def admin_queue():
    _require_admin()
    return jsonify(reviews.queue(request.args.get("status", reviews.FLAGGED)))


@bp.post("/api/admin/reviews/<review_id>/<action>")
@auth.require_auth
def admin_action(review_id, action):
    _require_admin()
    return jsonify({"status": reviews.moderate(review_id, action)})


@bp.get("/api/uploads/<name>")
def upload(name):
    path = reviews.safe_upload_path(name)
    if not path:
        return jsonify({"error": "Not found."}), 404
    resp = send_from_directory(store.UPLOAD_DIR, name, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"   # names are random and never reused
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp
