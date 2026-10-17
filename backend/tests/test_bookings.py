import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from tests import base
from tests.test_payments import PaymentBase, GOOD
import bookings
import clock
import payments
import store
import transport

PAX = [{"name": "Asha Kumar", "age": 31, "gender": "F"}]
FROM, TO = "MAS", "madurai"


class BookingBase(PaymentBase):
    def search(self, h, date, quota="general", frm=FROM, to=TO):
        return self.c.get(f"/api/destinations/{to}/transport?from={frm}&date={date}&quota={quota}", headers=h).get_json()

    def find_train(self, h, quota="general", min_seats=2, days=(5, 6, 7, 8, 9)):
        """A train class with plenty of confirmed seats, on a date a few days ahead."""
        for d in days:
            date = (clock.today() + timedelta(days=d)).isoformat()
            for t in self.search(h, date, quota)["trains"]:
                for k in t["classes"]:
                    a = k["availability"]
                    if a["code"] == "AVL" and a["seats"] >= min_seats:
                        return date, t, k
        self.fail("no bookable train found")

    def train_payload(self, date, t, k, quota="general", pax=None):
        return {"kind": "train", "date": date, "quota": quota, "cls": k["cls"], "train_no": t["no"],
                "from": t["from"], "to": t["to"], "passengers": pax or PAX}

    def book(self, h, payload, key=None):
        hdr = dict(h, **({"Idempotency-Key": key} if key else {}))
        return self.c.post("/api/bookings", json=payload, headers=hdr)

    def book_ok(self, h, payload, key=None):
        r = self.book(h, payload, key)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def paid_train(self, h, **kw):
        date, t, k = self.find_train(h, **kw)
        j = self.book_ok(h, self.train_payload(date, t, k, kw.get("quota", "general")))
        self.fund("a@epic.test", 100000)
        r = self.pay(h, j["order"]["id"], method="wallet")
        self.assertEqual(r.status_code, 200, r.get_json())
        return date, t, k, r.get_json()["booking"]

    def held(self, date, t, k, quota="general"):
        return store.read()["held"].get(f"{t['no']}|{date}|{k['cls']}|{quota}", 0)


class TrainBookingTests(BookingBase):
    def test_booking_is_a_hold_not_a_confirmation(self):
        h = self.user()
        date, t, k = self.find_train(h)
        j = self.book_ok(h, self.train_payload(date, t, k))
        b, o = j["booking"], j["order"]
        self.assertEqual(b["status"], "PENDING_PAYMENT")
        self.assertNotIn("pnr", b)                                           # no PNR until paid
        self.assertEqual(o["amount"], k["fare"]["total"] * 100)
        self.assertGreater(b["hold_seconds_left"], 590)
        self.assertEqual(self.held(date, t, k), 1)
        after = [c for c in [x for x in self.search(h, date)["trains"] if x["no"] == t["no"]][0]["classes"] if c["cls"] == k["cls"]][0]
        self.assertEqual(after["availability"]["seats"], k["availability"]["seats"] - 1)

    def test_the_client_cannot_set_the_price_or_the_timings(self):
        h = self.user()
        date, t, k = self.find_train(h)
        p = dict(self.train_payload(date, t, k), fare=1, total=1, amount=1, depart="00:01", train_name="Free Express")
        j = self.book_ok(h, p)
        self.assertEqual(j["order"]["amount"], k["fare"]["total"] * 100)
        self.assertEqual(j["booking"]["depart"], t["depart"])
        self.assertEqual(j["booking"]["train_name"], t["name"])

    def test_paying_from_the_wallet_confirms_and_issues_a_pnr(self):
        h = self.user()
        date, t, k, b = self.paid_train(h)
        self.assertEqual(b["status"], "CONFIRMED")
        self.assertRegex(b["pnr"], r"^\d{10}$")
        self.assertEqual(payments.balance("a@epic.test"), 100000 * 100 - k["fare"]["total"] * 100)
        self.assertEqual([e["kind"] for e in store.read()["ledger"]], ["topup", "payment"])
        self.assert_ledger_consistent()

    def test_not_enough_wallet_money_leaves_the_hold_in_place(self):
        h = self.user()
        date, t, k = self.find_train(h)
        j = self.book_ok(h, self.train_payload(date, t, k))
        r = self.pay(h, j["order"]["id"], method="wallet")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(self.c.get(f"/api/bookings/{j['booking']['id']}", headers=h).get_json()["status"], "PENDING_PAYMENT")
        self.fund("a@epic.test", 100000)
        self.assertEqual(self.pay(h, j["order"]["id"], method="wallet").status_code, 200)

    def test_card_payment_confirms_through_the_webhook(self):
        h = self.user()
        date, t, k = self.find_train(h)
        j = self.book_ok(h, self.train_payload(date, t, k))
        r = self.pay(h, j["order"]["id"], method="card", card=GOOD).get_json()
        self.assertEqual((r["result"]["status"], r["booking"]["status"]), ("captured", "CONFIRMED"))
        self.assertEqual(len([e for e in store.read()["events"].values() if e["type"] == "payment.captured"]), 1)

    def test_a_failed_card_leaves_the_hold_so_the_user_can_retry(self):
        h = self.user()
        date, t, k = self.find_train(h)
        j = self.book_ok(h, self.train_payload(date, t, k))
        bad = self.pay(h, j["order"]["id"], method="card", card={"number": "4000 0000 0000 0002", "expiry": "12/30", "cvv": "123"}).get_json()
        self.assertEqual((bad["result"]["status"], bad["booking"]["status"]), ("failed", "PENDING_PAYMENT"))
        ok = self.pay(h, j["order"]["id"], method="card", card=GOOD).get_json()
        self.assertEqual(ok["booking"]["status"], "CONFIRMED")

    def test_an_unpaid_hold_expires_and_frees_the_seat(self):
        h = self.user()
        date, t, k = self.find_train(h)
        j = self.book_ok(h, self.train_payload(date, t, k))
        self.assertEqual(self.held(date, t, k), 1)
        clock.freeze(clock.now() + timedelta(seconds=bookings.HOLD_SECONDS + 5))
        rows = self.c.get("/api/bookings", headers=h).get_json()
        self.assertEqual(rows[0]["status"], "EXPIRED")
        self.assertEqual(self.held(date, t, k), 0)
        self.assertEqual(store.read()["orders"][j["order"]["id"]]["status"], "EXPIRED")
        r = self.pay(h, j["order"]["id"], method="wallet")
        self.assertEqual(r.status_code, 409)
        self.assertIn("expired", r.get_json()["error"])

    def test_a_late_payment_is_refunded_automatically(self):
        h = self.user()
        date, t, k = self.find_train(h)
        j = self.book_ok(h, self.train_payload(date, t, k))
        clock.freeze(clock.now() + timedelta(seconds=bookings.HOLD_SECONDS + 5))
        bookings.sweep()
        order = store.read()["orders"][j["order"]["id"]]
        ev = {"id": "evt_late", "type": "payment.captured", "created": "x", "data": {
            "order_id": order["id"], "payment_id": "pay_late", "amount": order["amount"], "currency": "INR", "method": "card", "instrument": "Visa ending 4242"}}
        raw = json.dumps(ev, separators=(",", ":"), sort_keys=True).encode()
        self.assertEqual(self.c.post("/api/payments/webhook", data=raw, headers={"X-Signature": payments.sign(raw)}).status_code, 200)
        self.assertEqual(payments.balance("a@epic.test"), order["amount"])        # money came back
        self.assertEqual(self.c.get(f"/api/bookings/{j['booking']['id']}", headers=h).get_json()["status"], "EXPIRED")
        self.assert_ledger_consistent()

    def test_double_click_returns_the_same_hold(self):
        h = self.user()
        date, t, k = self.find_train(h)
        a = self.book_ok(h, self.train_payload(date, t, k), key="click-1")
        b = self.book_ok(h, self.train_payload(date, t, k), key="click-1")
        self.assertEqual(a["booking"]["id"], b["booking"]["id"])
        self.assertEqual(self.held(date, t, k), 1)
        c = self.book_ok(h, self.train_payload(date, t, k), key="click-2")
        self.assertNotEqual(a["booking"]["id"], c["booking"]["id"])

    def test_cancelling_an_unpaid_booking_releases_the_hold(self):
        h = self.user()
        date, t, k = self.find_train(h)
        j = self.book_ok(h, self.train_payload(date, t, k))
        r = self.c.post(f"/api/bookings/{j['booking']['id']}/cancel", headers=h)
        self.assertEqual((r.status_code, r.get_json()["booking"]["status"]), (200, "CANCELLED"))
        self.assertEqual(self.held(date, t, k), 0)
        self.assertEqual(self.pay(h, j["order"]["id"], method="wallet").status_code, 409)

    def test_cancelling_a_confirmed_ticket_refunds_minus_the_flat_charge(self):
        h = self.user()
        date, t, k, b = self.paid_train(h)                                     # 5+ days ahead: the 48h+ tier
        before = payments.balance("a@epic.test")
        q = self.c.get(f"/api/bookings/{b['id']}/cancel-quote", headers=h).get_json()
        flat = bookings.RAIL_FLAT_PER_PASSENGER[k["cls"]] * 100
        self.assertEqual((q["charge"], q["refund"]), (min(flat, b["amount_paise"]), b["amount_paise"] - min(flat, b["amount_paise"])))
        r = self.c.post(f"/api/bookings/{b['id']}/cancel", headers=h).get_json()
        self.assertEqual(r["booking"]["status"], "CANCELLED")
        self.assertEqual(payments.balance("a@epic.test"), before + q["refund"])
        self.assertEqual(self.held(date, t, k), 0)                              # the seat is available again
        self.assertEqual(self.c.post(f"/api/bookings/{b['id']}/cancel", headers=h).status_code, 409)
        self.assert_ledger_consistent()

    def test_the_cancellation_charge_grows_as_departure_nears(self):
        h = self.user()
        date, t, k, b = self.paid_train(h)
        dep = bookings.departure(store.read()["bookings"][0])
        charges = []
        for hours in (60, 30, 8, 2):
            clock.freeze(dep - timedelta(hours=hours))
            charges.append(bookings.policy(store.read()["bookings"][0])["charge"])
        self.assertEqual(charges, sorted(charges))
        self.assertEqual(charges[-1], b["amount_paise"])                        # under 4h: nothing back
        self.assertLess(charges[0], charges[1])

    def test_tatkal_tickets_are_not_refundable(self):
        h = self.user()
        clock.freeze(datetime(2026, 10, 7, 12, 0))                              # Tatkal is open for tomorrow
        date, t, k = self.find_train(h, quota="tatkal", min_seats=1, days=(1,))
        j = self.book_ok(h, self.train_payload(date, t, k, "tatkal"))
        self.fund("a@epic.test", 100000)
        self.pay(h, j["order"]["id"], method="wallet")
        q = self.c.get(f"/api/bookings/{j['booking']['id']}/cancel-quote", headers=h).get_json()
        self.assertEqual((q["refund"], q["charge"]), (0, j["booking"]["amount_paise"]))

    def test_a_journey_that_has_left_cannot_be_cancelled(self):
        h = self.user()
        date, t, k, b = self.paid_train(h)
        clock.freeze(bookings.departure(store.read()["bookings"][0]) + timedelta(minutes=5))
        self.assertFalse(self.c.get(f"/api/bookings/{b['id']}/cancel-quote", headers=h).get_json()["cancellable"])
        self.assertEqual(self.c.post(f"/api/bookings/{b['id']}/cancel", headers=h).status_code, 409)

    def test_other_users_cannot_see_pay_or_cancel_a_booking(self):
        a, b = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        date, t, k = self.find_train(a)
        j = self.book_ok(a, self.train_payload(date, t, k))
        self.fund("b@epic.test", 100000)
        self.assertEqual(self.c.get(f"/api/bookings/{j['booking']['id']}", headers=b).status_code, 404)
        self.assertEqual(self.pay(b, j["order"]["id"], method="wallet").status_code, 404)
        self.assertEqual(self.c.post(f"/api/bookings/{j['booking']['id']}/cancel", headers=b).status_code, 404)
        self.assertEqual(self.c.get("/api/bookings", headers=b).get_json(), [])

    def test_validation_errors(self):
        h = self.user()
        date, t, k = self.find_train(h)
        good = self.train_payload(date, t, k)
        yesterday = (clock.today() - timedelta(days=1)).isoformat()
        for label, change in [("past date", {"date": yesterday}), ("no passengers", {"passengers": []}),
                              ("seven passengers", {"passengers": PAX * 7}), ("bad age", {"passengers": [{"name": "A", "age": 0}]}),
                              ("string age", {"passengers": [{"name": "A", "age": "31"}]}), ("blank name", {"passengers": [{"name": " ", "age": 30}]}),
                              ("bad class", {"cls": "ZZ"}), ("wrong train", {"train_no": "00000"}), ("same stations", {"to": good["from"]}),
                              ("unknown station", {"from": "XXX"}), ("bad kind", {"kind": "boat"})]:
            r = self.book(h, dict(good, **change))
            self.assertEqual(r.status_code, 400, label)
            self.assertIn("error", r.get_json())
        self.assertEqual(self.held(date, t, k), 0, "a rejected booking must not hold seats")

    def test_last_seats_cannot_be_oversold_under_concurrency(self):
        users = [self.user(f"u{i}@epic.test", f"User {i}") for i in range(8)]
        date, t, k = self.find_train(users[0])
        key = f"{t['no']}|{date}|{k['cls']}|general"
        store.read()["held"][key] = k["availability"]["seats"] - 2                # exactly two seats left
        payload = self.train_payload(date, t, k)

        def attempt(h):
            return base.A.app.test_client().post("/api/bookings", json=payload, headers=h).status_code

        # Make the gap between "is a seat free?" and "hold it" wide, so a missing lock is caught every
        # time instead of only on an unlucky thread switch.
        real_search = transport.search_trains

        def slow_search(*a, **k):
            result = real_search(*a, **k)
            time.sleep(0.03)
            return result

        transport.search_trains = slow_search
        try:
            with ThreadPoolExecutor(8) as pool:
                codes = list(pool.map(attempt, users))
        finally:
            transport.search_trains = real_search
        self.assertEqual(sorted(codes), [201, 201] + [400] * 6, codes)
        self.assertEqual(store.read()["held"][key], k["availability"]["seats"])


class BusBookingTests(BookingBase):
    def find_bus(self, h, frm="MAS", to="kodaikanal", min_left=8):
        date = (clock.today() + timedelta(days=4)).isoformat()
        for b in self.search(h, date, frm=frm, to=to)["buses"]:
            if b["seats_left"] >= min_left:
                return date, b
        self.fail("no bus")

    def bus_payload(self, date, b, seats, pax=None):
        return {"kind": "bus", "date": date, "bus_id": b["id"], "from": b["from"], "to": b["to"], "seats": seats,
                "passengers": pax or PAX * len(seats)}

    def free_seats(self, b, n):
        return [s for s in range(1, b["seats_total"] + 1) if s not in b["taken"]][:n]

    def test_bus_price_comes_from_the_server_and_the_seat_is_held(self):
        h = self.user()
        date, b = self.find_bus(h)
        seat = self.free_seats(b, 1)
        j = self.book_ok(h, dict(self.bus_payload(date, b, seat), fare=1, total=1))
        self.assertEqual(j["order"]["amount"], b["fare"] * 100)
        self.assertEqual(store.read()["held_seats"][b["key"]], seat)
        again = [x for x in self.search(h, date, to="kodaikanal")["buses"] if x["id"] == b["id"]][0]
        self.assertIn(seat[0], again["taken"])
        self.assertEqual(again["seats_left"], b["seats_left"] - 1)

    def test_two_people_cannot_take_the_same_seat(self):
        a, b_user = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        date, bus = self.find_bus(a)
        s1, s2 = self.free_seats(bus, 2)
        self.book_ok(a, self.bus_payload(date, bus, [s1]))
        r = self.book(b_user, self.bus_payload(date, bus, [s1]))
        self.assertEqual(r.status_code, 400)
        self.assertIn("just taken", r.get_json()["error"])
        self.assertEqual(self.book(b_user, self.bus_payload(date, bus, [s2])).status_code, 201)

    def test_a_lapsed_hold_gives_the_seat_back(self):
        a, b_user = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        date, bus = self.find_bus(a)
        seat = self.free_seats(bus, 1)
        self.book_ok(a, self.bus_payload(date, bus, seat))
        clock.freeze(clock.now() + timedelta(seconds=bookings.HOLD_SECONDS + 5))
        self.assertEqual(self.book(b_user, self.bus_payload(date, bus, seat)).status_code, 201)

    def test_seat_validation(self):
        h = self.user()
        date, bus = self.find_bus(h)
        free = self.free_seats(bus, 2)
        for label, seats, pax in [("duplicate", [free[0], free[0]], PAX * 2), ("zero", [0], PAX), ("too high", [bus["seats_total"] + 1], PAX),
                                  ("string", ["3"], PAX), ("wrong count", free, PAX), ("a seat already taken", [bus["taken"][0]], PAX)]:
            self.assertEqual(self.book(h, self.bus_payload(date, bus, seats, pax)).status_code, 400, label)
        self.assertEqual(store.read()["held_seats"].get(bus["key"], []), [])

    def test_cancel_confirmed_bus_releases_the_seat_and_refunds(self):
        h = self.user()
        date, bus = self.find_bus(h)
        seat = self.free_seats(bus, 1)
        j = self.book_ok(h, self.bus_payload(date, bus, seat))
        self.fund("a@epic.test", 100000)
        self.pay(h, j["order"]["id"], method="wallet")
        before = payments.balance("a@epic.test")
        r = self.c.post(f"/api/bookings/{j['booking']['id']}/cancel", headers=h).get_json()
        self.assertEqual(r["booking"]["status"], "CANCELLED")
        self.assertEqual(payments.balance("a@epic.test"), before + int(bus["fare"] * 100 * 0.9))       # 10% fee 24h+ before
        self.assertEqual(store.read()["held_seats"][bus["key"]], [])
        self.assert_ledger_consistent()


if __name__ == "__main__":
    unittest.main()


class LegacyBookingTests(BookingBase):
    def test_a_booking_made_before_payments_existed_can_still_be_quoted_and_cancelled(self):
        h = self.user()
        date = (clock.today() + timedelta(days=5)).isoformat()
        store.read()["bookings"].append({"id": "old1", "kind": "train", "user": "a@epic.test", "status": "CONFIRMED", "date": date, "depart": "20:00",
                                         "cls": "SL", "quota": "general", "passengers": PAX, "total": 500, "booked_at": "2026-09-01T10:00:00"})
        q = self.c.get("/api/bookings/old1/cancel-quote", headers=h).get_json()
        self.assertEqual((q["total"], q["cancellable"]), (50000, True))
        r = self.c.post("/api/bookings/old1/cancel", headers=h)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["wallet_balance"], q["refund"])
        self.assertEqual(self.c.get("/api/bookings", headers=h).get_json()[0]["hold_seconds_left"], 0)
