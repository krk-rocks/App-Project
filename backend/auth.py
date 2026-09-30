"""Email + password accounts with bearer tokens.

Passwords are stored only as salted hashes (werkzeug's scrypt default); tokens are random and
opaque. Good enough for a demo app - but this is a JSON file, not a hardened auth service.
"""

import re
import secrets
import time
from functools import wraps

from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

import store

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOKEN_TTL = 60 * 60 * 24 * 14  # 14 days


def public(user):
    return {"email": user["email"], "name": user["name"], "phone": user.get("phone", "")}


def register(email, password, name, phone=""):
    email = (email or "").strip().lower()
    name = (name or "").strip()
    if not EMAIL_RE.match(email):
        return None, "Enter a valid email address."
    if len(password or "") < 8:
        return None, "Password must be at least 8 characters."
    if not name:
        return None, "Enter your name."
    db = store.read()
    if email in db["users"]:
        return None, "An account with that email already exists."
    db["users"][email] = {
        "email": email, "name": name, "phone": phone.strip(),
        "password": generate_password_hash(password), "created": time.time(),
    }
    store.commit()
    return db["users"][email], None


def login(email, password):
    db = store.read()
    user = db["users"].get((email or "").strip().lower())
    if not user or not check_password_hash(user["password"], password or ""):
        return None, "Email or password is incorrect."
    return user, None


def issue_token(user):
    token = secrets.token_urlsafe(32)
    db = store.read()
    db["tokens"][token] = {"email": user["email"], "expires": time.time() + TOKEN_TTL}
    store.commit()
    return token


def revoke(token):
    db = store.read()
    if db["tokens"].pop(token, None):
        store.commit()


def user_for_token(token):
    db = store.read()
    rec = db["tokens"].get(token or "")
    if not rec:
        return None
    if rec["expires"] < time.time():
        db["tokens"].pop(token, None)
        store.commit()
        return None
    return db["users"].get(rec["email"])


def current_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return user_for_token(header[7:])


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Sign in to continue."}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper
