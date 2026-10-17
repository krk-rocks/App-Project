import json
import unittest

from tests import base
import payments
import store


def luhn_complete(prefix):
    """A card number starting with `prefix` that passes the Luhn check (not one of our test cards)."""
    for check in range(10):
        if payments._luhn_ok(prefix + str(check)):
            return prefix + str(check)


GOOD = {"number": "4242 4242 4242 4242", "expiry": "12/30", "cvv": "123"}
DECLINED = {"number": "4000 0000 0000 0002", "expiry": "12/30", "cvv": "123"}


class PaymentBase(base.Base):
    def topup_order(self, h, rupees=1000, key=None):
        hdr = dict(h, **({"Idempotency-Key": key} if key else {}))
        r = self.c.post("/api/wallet/topup", json={"amount": rupees}, headers=hdr)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["order"]

    def pay(self, h, order_id, **body):
        return self.c.post(f"/api/orders/{order_id}/pay", json=body, headers=h)

    def assert_ledger_consistent(self):
        db = store.read()
        users = set(db["wallets"]) | {e["user"] for e in db["ledger"]}
        for u in users:
            total = sum(e["amount"] for e in db["ledger"] if e["user"] == u)
            self.assertEqual(db["wallets"].get(u, {"balance": 0})["balance"], total, f"ledger != balance for {u}")
            self.assertGreaterEqual(total, 0, f"negative wallet for {u}")

    def signed(self, event):
        raw = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        return raw, payments.sign(raw)

    def event(self, order, type_="payment.captured", amount=None, eid="evt_test1", pid="pay_test1"):
        return {"id": eid, "type": type_, "created": "x", "data": {
            "order_id": order["id"], "payment_id": pid, "amount": order["amount"] if amount is None else amount,
            "currency": "INR", "method": "card", "instrument": "Visa ending 4242"}}


class WalletTests(PaymentBase):
    def test_topup_with_a_test_card_credits_the_wallet_once(self):
        h = self.user()
        o = self.topup_order(h, 1000)
        r = self.pay(h, o["id"], method="card", card=GOOD)
        self.assertEqual(r.status_code, 200, r.get_json())
        j = r.get_json()
        self.assertEqual((j["order"]["status"], j["result"]["status"], j["wallet_balance"]), ("PAID", "captured", 100000))
        self.assertEqual(self.c.get("/api/wallet", headers=h).get_json()["balance"], 100000)
        again = self.pay(h, o["id"], method="card", card=GOOD)               # paying a paid order again
        self.assertEqual(again.status_code, 409)
        self.assertEqual(payments.balance("a@epic.test"), 100000)
        self.assert_ledger_consistent()

    def test_declined_card_records_the_failure_and_credits_nothing(self):
        h = self.user()
        o = self.topup_order(h, 500)
        j = self.pay(h, o["id"], method="card", card=DECLINED).get_json()
        self.assertEqual(j["result"]["status"], "failed")
        self.assertEqual(j["order"]["status"], "CREATED")                      # can retry
        self.assertEqual(j["order"]["attempts"][0]["code"], "card_declined")
        self.assertEqual(j["wallet_balance"], 0)
        retry = self.pay(h, o["id"], method="card", card=GOOD).get_json()      # same order, good card
        self.assertEqual(retry["order"]["status"], "PAID")
        self.assertEqual(retry["wallet_balance"], 50000)

    def test_a_real_looking_card_is_refused_and_nothing_is_stored(self):
        h = self.user()
        o = self.topup_order(h, 500)
        real = luhn_complete("453201511283036")
        self.assertNotIn(real, payments.TEST_CARDS)
        r = self.pay(h, o["id"], method="card", card={"number": real, "expiry": "12/30", "cvv": "123"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("test", r.get_json()["error"].lower())
        self.assertNotIn(real, json.dumps(store.read()), "a card number was persisted")
        self.assertEqual(store.read()["orders"][o["id"]]["attempts"], [])

    def test_card_field_validation(self):
        h = self.user()
        o = self.topup_order(h, 500)
        for card, fragment in [({"number": "4242 4242 4242 4241", "expiry": "12/30", "cvv": "123"}, "valid card"),
                               ({"number": "4242 4242 4242 4242", "expiry": "13/30", "cvv": "123"}, "MM/YY"),
                               ({"number": "4242 4242 4242 4242", "expiry": "01/20", "cvv": "123"}, "expired"),
                               ({"number": "4242 4242 4242 4242", "expiry": "12/30", "cvv": "12"}, "security code")]:
            r = self.pay(h, o["id"], method="card", card=card)
            self.assertEqual(r.status_code, 400)
            self.assertIn(fragment, r.get_json()["error"], card)

    def test_upi_test_ids(self):
        h = self.user()
        o = self.topup_order(h, 500)
        self.assertEqual(self.pay(h, o["id"], method="upi", upi={"vpa": "fail@epic"}).get_json()["result"]["status"], "failed")
        self.assertEqual(self.pay(h, o["id"], method="upi", upi={"vpa": "someone@okbank"}).status_code, 400)
        self.assertEqual(self.pay(h, o["id"], method="upi", upi={"vpa": "success@epic"}).get_json()["order"]["status"], "PAID")

    def test_topup_amount_limits(self):
        h = self.user()
        for bad in (50, 99, 50001, 0, -5, "1000", 12.5, None, True):
            r = self.c.post("/api/wallet/topup", json={"amount": bad}, headers=h)
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.c.post("/api/wallet/topup", json={"amount": 100}, headers=h).status_code, 201)
        self.assertEqual(self.c.post("/api/wallet/topup", json={"amount": 50000}, headers=h).status_code, 201)

    def test_wallet_cannot_fund_itself(self):
        h = self.user()
        o = self.topup_order(h)
        self.assertEqual(self.pay(h, o["id"], method="wallet").status_code, 400)

    def test_topup_is_idempotent(self):
        h = self.user()
        a, b = self.topup_order(h, 700, key="k-1"), self.topup_order(h, 700, key="k-1")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(store.read()["orders"]), 1)

    def test_orders_belong_to_their_owner(self):
        a, b = self.user("a@epic.test"), self.user("b@epic.test", "Bala")
        o = self.topup_order(a)
        self.assertEqual(self.pay(b, o["id"], method="card", card=GOOD).status_code, 404)
        self.assertEqual(self.c.get(f"/api/orders/{o['id']}", headers=b).status_code, 404)
        self.assertEqual(self.c.get(f"/api/orders/{o['id']}", headers=a).status_code, 200)

    def test_auth_required(self):
        for method, path in [("get", "/api/wallet"), ("post", "/api/wallet/topup"), ("get", "/api/bookings"), ("post", "/api/orders/x/pay")]:
            self.assertEqual(getattr(self.c, method)(path).status_code, 401, path)

    def test_money_is_integer_paise_and_ledger_adds_up(self):
        h = self.user()
        for rupees in (100, 250, 999):
            self.pay(h, self.topup_order(h, rupees)["id"], method="card", card=GOOD)
        self.assertEqual(payments.balance("a@epic.test"), (100 + 250 + 999) * 100)
        self.assertTrue(all(isinstance(e["amount"], int) for e in store.read()["ledger"]))
        self.assert_ledger_consistent()


class WebhookTests(PaymentBase):
    def setUp(self):
        super().setUp()
        self.h = self.user()
        self.order = store.read()["orders"][self.topup_order(self.h, 1000)["id"]]

    def post(self, raw, sig):
        return self.c.post("/api/payments/webhook", data=raw, headers={"X-Signature": sig, "Content-Type": "application/json"})

    def test_valid_signature_pays_the_order(self):
        raw, sig = self.signed(self.event(self.order))
        self.assertEqual(self.post(raw, sig).status_code, 200)
        self.assertEqual(self.order["status"], "PAID")
        self.assertEqual(payments.balance("a@epic.test"), 100000)

    def test_forged_or_missing_signature_is_rejected(self):
        raw, _ = self.signed(self.event(self.order))
        for sig in ("", "0" * 64, "not-hex", payments.sign(b"something else")):
            self.assertEqual(self.post(raw, sig).status_code, 401, sig)
        self.assertEqual(self.c.post("/api/payments/webhook", data=raw).status_code, 401)   # header absent
        self.assertEqual(self.order["status"], "CREATED")
        self.assertEqual(payments.balance("a@epic.test"), 0)

    def test_a_replayed_event_is_applied_once(self):
        raw, sig = self.signed(self.event(self.order))
        self.assertEqual(self.post(raw, sig).status_code, 200)
        second = self.post(raw, sig)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["duplicate"])
        self.assertEqual(payments.balance("a@epic.test"), 100000)
        self.assert_ledger_consistent()

    def test_amount_must_match_the_order(self):
        raw, sig = self.signed(self.event(self.order, amount=100))
        self.assertEqual(self.post(raw, sig).status_code, 400)
        self.assertEqual(self.order["status"], "CREATED")
        self.assertEqual(payments.balance("a@epic.test"), 0)

    def test_unknown_order_and_malformed_events(self):
        ghost = {"id": "order_nope", "amount": 5}
        raw, sig = self.signed(self.event(ghost))
        self.assertEqual(self.post(raw, sig).status_code, 404)
        raw = b'{"id": "x"}'
        self.assertEqual(self.post(raw, payments.sign(raw)).status_code, 400)
        raw = b"not json"
        self.assertEqual(self.post(raw, payments.sign(raw)).status_code, 400)
        raw, sig = self.signed(self.event(self.order, type_="payment.mystery"))
        self.assertEqual(self.post(raw, sig).status_code, 400)

    def test_failed_event_does_not_pay(self):
        ev = self.event(self.order, type_="payment.failed")
        ev["data"]["error"] = {"code": "card_declined", "message": "nope"}
        raw, sig = self.signed(ev)
        self.assertEqual(self.post(raw, sig).status_code, 200)
        self.assertEqual(self.order["status"], "CREATED")
        self.assertEqual(self.order["attempts"][0]["status"], "failed")

    def test_a_second_payment_for_a_paid_order_is_refunded(self):
        self.post(*self.signed(self.event(self.order, eid="evt_a", pid="pay_a")))
        self.post(*self.signed(self.event(self.order, eid="evt_b", pid="pay_b")))
        self.assertEqual(payments.balance("a@epic.test"), 100000 + 100000)      # credited once, plus the duplicate refunded
        self.assertEqual(store.read()["refunds"][0]["reason"].startswith("Refunded: payment arrived"), True)
        self.assert_ledger_consistent()


if __name__ == "__main__":
    unittest.main()
