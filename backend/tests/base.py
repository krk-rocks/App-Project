"""Shared test setup. Points the store at a throw-away folder BEFORE the app is imported, so tests never
touch the real backend/store.json, and gives each test a clean store and a clock it can freeze."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

_TMP = tempfile.mkdtemp(prefix="epictn-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("FLASK_DEBUG", "0")
os.environ["ADMIN_EMAILS"] = "admin@epic.test"
os.environ["LLM_PROVIDER"] = "none"          # tests never call a real model
os.environ["RAIL_API_KEY"] = ""                       # nor the live rail timetable (empty also stops .env filling it in)
os.environ["PLANNER_WEATHER"] = "0"         # nor the weather service
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clock    # noqa: E402
import store    # noqa: E402
import app as A  # noqa: E402

NOON = datetime(2026, 10, 7, 12, 0)   # a fixed "now" (Wed) - IST


def reset_store():
    with store.TX:
        fresh = json.loads(json.dumps(store._EMPTY))
        store._DB.clear()
        store._DB.update(fresh)


class Base(unittest.TestCase):
    def setUp(self):
        reset_store()
        clock.freeze(NOON)
        self.c = A.app.test_client()
        A.WEATHER_CACHE.clear()

    def tearDown(self):
        clock.unfreeze()

    def user(self, email="a@epic.test", name="Asha Kumar", password="longenough1"):
        r = self.c.post("/api/auth/register", json={"email": email, "password": password, "name": name})
        self.assertEqual(r.status_code, 201, r.get_json())
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def fund(self, email, rupees):
        """Credit a wallet directly (tests of other things should not need the payment UI)."""
        import payments
        with store.TX:
            payments.wallet_credit(email, rupees * 100, "topup", "test-credit", "Test credit")
