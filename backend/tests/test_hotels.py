import re
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from tests import base
from tests.test_payments import PaymentBase
import bookings
import clock
import hotels
import payments
import store

HOTEL = "madurai-premium"      # "Suite": 2 rooms, sleeps 4 - small enough to exhaust
SUITE = "Suite"


class HotelBase(PaymentBase):
    def stay(self, h, check_in, check_out, rooms=1, guests=2, room=SUITE, hotel=HOTEL, **extra):
        body = {"hotel_id": hotel, "room_type": room, "check_in": check_in, "check_out": check_out, "rooms": rooms,
                "guests": guests, "guest": {"name": "Asha Kumar", "phone": "9876543210"}, **extra}
        return self.c.post("/api/hotels/book", json=body, headers=h)

    def stay_ok(self, h, *a, **k):
        r = self.stay(h, *a, **k)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def search(self, check_in, check_out, guests=2, rooms=1, dest="madurai"):
        return self.c.get(f"/api/destinations/{dest}/hotels?check_in={check_in}&check_out={check_out}&guests={guests}&rooms={rooms}")

    def suite(self, result):
        prop = next(p for p in result["properties"] if p["id"] == HOTEL)
        return next(o for o in prop["options"] if o["type"] == SUITE)


class HotelSearchTests(HotelBase):
    def test_every_town_has_three_sample_properties_with_rooms(self):
        self.assertEqual(len(hotels.BY_PROPERTY), 30)
        for dest, props in hotels.PROPERTIES.items():
            self.assertEqual(len(props), 3, dest)
            for p in props:
                self.assertTrue(p["sample"])
                self.assertTrue(all(r["count"] >= 1 and r["base"] >= 500 for r in p["rooms"]))

    def test_search_prices_each_night_and_adds_up(self):
        j = self.search("2026-11-10", "2026-11-13", guests=2, rooms=2).get_json()
        self.assertEqual((j["nights"], len(j["properties"])), (3, 3))
        o = self.suite(j)
        self.assertEqual(len(o["nightly"]), 3)
        self.assertEqual(o["subtotal"], sum(n["price"] for n in o["nightly"]) * 2)
        self.assertEqual(o["total"], o["subtotal"] + o["tax"])
        self.assertEqual(o["tax"], round(o["subtotal"] * hotels.TAX_RATE))
        self.assertTrue(o["bookable"])

    def test_busy_nights_cost_more_and_a_quieter_date_is_suggested(self):
        quiet = self.suite(self.search("2026-12-02", "2026-12-03").get_json())["nightly"][0]
        busy_search = self.search("2027-01-15", "2027-01-16").get_json()
        busy = self.suite(busy_search)["nightly"][0]
        self.assertEqual((quiet["level"], busy["level"]), ("Low", "High"))
        self.assertGreater(busy["price"], quiet["price"] * 1.2)
        self.assertEqual(busy_search["crowd"]["high_nights"], 1)
        self.assertTrue(busy_search["quieter"])
        self.assertNotIn("quieter", self.search("2026-12-02", "2026-12-03").get_json())

    def test_a_party_too_big_for_the_rooms_is_not_bookable(self):
        o = self.suite(self.search("2026-11-10", "2026-11-11", guests=9, rooms=2).get_json())      # 2 suites sleep 8
        self.assertFalse(o["fits_guests"])
        self.assertFalse(o["bookable"])

    def test_search_validation(self):
        for q, label in [("check_in=2026-11-10&check_out=2026-11-10", "same day"), ("check_in=2026-11-12&check_out=2026-11-10", "backwards"),
                         ("check_in=2026-10-01&check_out=2026-10-03", "past"), ("check_in=2026-11-01&check_out=2026-11-20", "too long"),
                         ("check_in=junk&check_out=2026-11-10", "bad date"), ("check_in=2026-11-10&check_out=2026-11-12&guests=0", "no guests"),
                         ("check_in=2026-11-10&check_out=2026-11-12&rooms=9", "too many rooms"), ("check_in=2026-11-10&check_out=2026-11-12&guests=x", "non-numeric"),
                         ("check_in=2028-11-10&check_out=2028-11-12", "too far ahead")]:
            r = self.c.get(f"/api/destinations/madurai/hotels?{q}")
            self.assertEqual(r.status_code, 400, label)
        self.assertEqual(self.c.get("/api/destinations/atlantis/hotels?check_in=2026-11-10&check_out=2026-11-12").status_code, 404)


class HotelInventoryTests(HotelBase):
    def test_back_to_back_stays_share_the_changeover_day_but_overlaps_do_not(self):
        a, b, c = self.user("a@epic.test"), self.user("b@epic.test", "Bala"), self.user("c@epic.test", "Chitra")
        self.stay_ok(a, "2026-11-10", "2026-11-13", rooms=2)                          # nights 10, 11, 12 - both suites
        r = self.stay(b, "2026-11-12", "2026-11-14")                                  # night 12 clashes
        self.assertEqual(r.status_code, 409)
        self.assertIn("Sold out", r.get_json()["error"])
        self.assertEqual(self.stay(b, "2026-11-13", "2026-11-15").status_code, 201)   # starts the day A leaves
        self.assertEqual(self.stay(c, "2026-11-09", "2026-11-10").status_code, 201)   # ends the day A arrives
        self.assertEqual(self.stay(c, "2026-11-09", "2026-11-11").status_code, 409)   # but not a night into A's stay

    def test_a_partly_free_stay_reports_how_many_rooms_are_left(self):
        a, b = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        self.stay_ok(a, "2026-11-20", "2026-11-22", rooms=1)
        r = self.stay(b, "2026-11-20", "2026-11-22", rooms=2)
        self.assertEqual(r.status_code, 409)
        self.assertIn("Only 1 room", r.get_json()["error"])
        self.assertEqual(self.suite(self.search("2026-11-20", "2026-11-22").get_json())["free"], 1)
        self.assertEqual(self.suite(self.search("2026-11-22", "2026-11-24").get_json())["free"], 2)    # after A leaves

    def test_availability_is_the_scarcest_night_not_the_first(self):
        a, b = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        self.stay_ok(a, "2026-11-12", "2026-11-13", rooms=2)                          # only the middle night is full
        self.assertEqual(self.suite(self.search("2026-11-11", "2026-11-14").get_json())["free"], 0)
        self.assertEqual(self.stay(b, "2026-11-11", "2026-11-14").status_code, 409)

    def test_an_unpaid_hold_blocks_the_room_then_lapses(self):
        a, b = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        self.stay_ok(a, "2026-11-10", "2026-11-12", rooms=2)
        self.assertEqual(self.stay(b, "2026-11-10", "2026-11-12").status_code, 409)
        clock.freeze(clock.now() + timedelta(seconds=bookings.HOLD_SECONDS + 5))
        self.assertEqual(self.stay(b, "2026-11-10", "2026-11-12").status_code, 201)

    def test_cancelling_frees_the_rooms_for_someone_else(self):
        a, b = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        j = self.stay_ok(a, "2026-11-10", "2026-11-12", rooms=2)
        self.fund("a@epic.test", 1000000)
        self.pay(a, j["order"]["id"], method="wallet")
        self.assertEqual(self.stay(b, "2026-11-10", "2026-11-12").status_code, 409)
        self.c.post(f"/api/bookings/{j['booking']['id']}/cancel", headers=a)
        self.assertEqual(self.stay(b, "2026-11-10", "2026-11-12", rooms=2).status_code, 201)

    def test_the_last_room_cannot_be_double_booked_under_concurrency(self):
        users = [self.user(f"u{i}@epic.test", f"User {i}") for i in range(6)]
        real_quote = hotels.quote

        def slow_quote(*a, **k):                       # widen the gap between "is it free?" and "hold it"
            time.sleep(0.03)
            return real_quote(*a, **k)

        def attempt(h):
            return self.stay(h, "2026-12-05", "2026-12-07", rooms=1).status_code

        hotels.quote = slow_quote
        try:
            with ThreadPoolExecutor(6) as pool:
                codes = list(pool.map(attempt, users))
        finally:
            hotels.quote = real_quote
        self.assertEqual(sorted(codes), [201, 201, 409, 409, 409, 409], codes)       # the suite has exactly 2 rooms


class HotelBookingTests(HotelBase):
    def test_the_price_is_computed_on_the_server(self):
        h = self.user()
        quoted = self.suite(self.search("2026-11-10", "2026-11-12").get_json())
        j = self.stay_ok(h, "2026-11-10", "2026-11-12", total=1, subtotal=1, price=1, amount=1)
        b, o = j["booking"], j["order"]
        self.assertEqual(b["total"], quoted["total"])
        self.assertEqual(o["amount"], quoted["total"] * 100)
        self.assertEqual((b["status"], b["nights"], b["place"]), ("PENDING_PAYMENT", 2, "madurai"))

    def test_paying_confirms_with_a_confirmation_code(self):
        h = self.user()
        j = self.stay_ok(h, "2026-11-10", "2026-11-12")
        self.fund("a@epic.test", 1000000)
        b = self.pay(h, j["order"]["id"], method="wallet").get_json()["booking"]
        self.assertEqual(b["status"], "CONFIRMED")
        self.assertTrue(re.fullmatch(r"EH\d{6}", b["confirmation"]))
        self.assert_ledger_consistent()

    def test_validation(self):
        h = self.user()
        good = dict(hotel_id=HOTEL, room_type=SUITE, check_in="2026-11-10", check_out="2026-11-12", rooms=1, guests=2, guest={"name": "A"})
        for label, change, code in [("unknown hotel", {"hotel_id": "nope"}, 404), ("unknown room", {"room_type": "Barn"}, 400),
                                    ("no rooms", {"rooms": 0}, 400), ("five rooms", {"rooms": 5}, 400), ("string rooms", {"rooms": "1"}, 400),
                                    ("bool rooms", {"rooms": True}, 400), ("zero guests", {"guests": 0}, 400), ("too many for the room", {"guests": 5}, 400),
                                    ("no name", {"guest": {"name": " "}}, 400), ("long name", {"guest": {"name": "x" * 81}}, 400),
                                    ("past", {"check_in": "2026-10-06", "check_out": "2026-10-08"}, 400),
                                    ("backwards", {"check_in": "2026-11-12", "check_out": "2026-11-10"}, 400),
                                    ("two weeks plus", {"check_in": "2026-11-01", "check_out": "2026-11-16"}, 400)]:
            r = self.c.post("/api/hotels/book", json=dict(good, **change), headers=h)
            self.assertEqual(r.status_code, code, label)
        self.assertEqual(self.c.post("/api/hotels/book", json=good).status_code, 401)
        self.assertEqual(store.read()["bookings"], [], "rejected bookings must not leave anything behind")

    def test_double_click_is_idempotent(self):
        h = self.user()
        a = self.c.post("/api/hotels/book", json=dict(hotel_id=HOTEL, room_type=SUITE, check_in="2026-11-10", check_out="2026-11-12", rooms=1,
                                                     guests=2, guest={"name": "A"}), headers=dict(h, **{"Idempotency-Key": "k1"})).get_json()
        b = self.c.post("/api/hotels/book", json=dict(hotel_id=HOTEL, room_type=SUITE, check_in="2026-11-10", check_out="2026-11-12", rooms=1,
                                                     guests=2, guest={"name": "A"}), headers=dict(h, **{"Idempotency-Key": "k1"})).get_json()
        self.assertEqual(a["booking"]["id"], b["booking"]["id"])
        self.assertEqual(len(store.read()["bookings"]), 1)

    def test_cancellation_tiers_follow_the_time_before_check_in(self):
        h = self.user()
        j = self.stay_ok(h, "2026-11-10", "2026-11-13", rooms=1)                       # 3 nights
        self.fund("a@epic.test", 1000000)
        self.pay(h, j["order"]["id"], method="wallet")
        rec = store.read()["bookings"][0]
        total, one_night = rec["amount_paise"], rec["amount_paise"] // 3
        check_in = bookings.departure(rec)
        free = bookings.policy(rec, now=check_in - timedelta(hours=100))
        part = bookings.policy(rec, now=check_in - timedelta(hours=48))
        none = bookings.policy(rec, now=check_in - timedelta(hours=10))
        gone = bookings.policy(rec, now=check_in + timedelta(hours=1))
        self.assertEqual((free["charge"], free["refund"]), (0, total))
        self.assertEqual((part["charge"], part["refund"]), (one_night, total - one_night))
        self.assertEqual((none["charge"], none["refund"]), (total, 0))
        self.assertFalse(gone["cancellable"])

    def test_cancelling_a_free_cancellation_stay_refunds_everything_to_the_wallet(self):
        h = self.user()
        j = self.stay_ok(h, "2026-11-10", "2026-11-12")
        self.fund("a@epic.test", 1000000)
        paid = self.pay(h, j["order"]["id"], method="wallet").get_json()
        after_pay = paid["wallet_balance"]
        r = self.c.post(f"/api/bookings/{j['booking']['id']}/cancel", headers=h).get_json()
        self.assertEqual(r["booking"]["status"], "CANCELLED")
        self.assertEqual(r["wallet_balance"], after_pay + j["order"]["amount"])
        self.assert_ledger_consistent()


if __name__ == "__main__":
    unittest.main()
