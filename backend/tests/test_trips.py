import json
import random
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests import base
import store
import trips


class TripBase(base.Base):
    def setUp(self):
        super().setUp()
        trips._JOIN_FAILS.clear()

    def make(self, h, name="Pongal road trip"):
        r = self.c.post("/api/trips", json={"name": name}, headers=h)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def group(self, n=3):
        """An owner plus n-1 members who joined by code. Returns (trip id, [headers], [member ids])."""
        hs = [self.user(f"u{i}@epic.test", f"Person {chr(65 + i)} Kumar") for i in range(n)]
        t = self.make(hs[0])
        for h in hs[1:]:
            self.assertEqual(self.c.post("/api/trips/join", json={"code": t["join"]["code"]}, headers=h).status_code, 200)
        snap = self.get(hs[0], t["id"])
        return t["id"], hs, [m["id"] for m in snap["members"]]

    def get(self, h, tid, since=None):
        q = f"?since={since}" if since is not None else ""
        return self.c.get(f"/api/trips/{tid}{q}", headers=h).get_json()

    def expense(self, h, tid, amount, paid_by, **split):
        body = {"description": "Dinner", "amount": amount, "paid_by": paid_by, "split": split or {"mode": "equal"}}
        return self.c.post(f"/api/trips/{tid}/expenses", json=body, headers=h)

    def balances(self, h, tid):
        return {m["id"]: m["balance"] for m in self.get(h, tid)["members"]}


class MembershipTests(TripBase):
    def test_create_list_and_join_by_code(self):
        a, b = self.user("a@epic.test", "Asha Kumar"), self.user("b@epic.test", "Bala Raman")
        t = self.make(a)
        self.assertEqual((t["role"], len(t["members"]), len(t["join"]["code"])), ("owner", 1, 8))
        self.assertEqual(self.c.get("/api/trips", headers=b).get_json(), [])
        j = self.c.post("/api/trips/join", json={"code": t["join"]["code"].lower()}, headers=b).get_json()   # codes are case-insensitive
        self.assertEqual((j["role"], len(j["members"])), ("member", 2))
        self.assertEqual(self.c.post("/api/trips/join", json={"code": t["join"]["code"]}, headers=b).get_json()["rev"], j["rev"])   # joining twice is harmless
        self.assertEqual([r["name"] for r in self.c.get("/api/trips", headers=b).get_json()], ["Pongal road trip"])
        self.assertNotIn("join", j)                                  # only the owner sees the code

    def test_members_are_shown_by_opaque_id_and_first_name_never_by_email(self):
        tid, hs, ids = self.group(3)
        blob = json.dumps(self.get(hs[1], tid))
        for i in range(3):
            self.assertNotIn(f"u{i}@epic.test", blob)
        self.assertEqual(sorted(m["name"] for m in self.get(hs[1], tid)["members"]), ["Person", "Person", "Person"])
        self.assertTrue(all(i.startswith("m_") for i in ids))

    def test_strangers_cannot_see_or_touch_a_trip(self):
        tid, hs, ids = self.group(2)
        out = self.user("out@epic.test", "Outsider")
        calls = [("get", f"/api/trips/{tid}", None), ("post", f"/api/trips/{tid}/items", {"day": 1, "title": "x"}),
                 ("post", f"/api/trips/{tid}/expenses", {"description": "x", "amount": 100, "paid_by": ids[0]}),
                 ("post", f"/api/trips/{tid}/polls", {"question": "q?", "options": ["a", "b"]}),
                 ("post", f"/api/trips/{tid}/settle", {"from": ids[0], "to": ids[1], "amount": 5}), ("delete", f"/api/trips/{tid}", None),
                 ("post", f"/api/trips/{tid}/code", {"action": "disable"})]
        for method, path, body in calls:
            r = getattr(self.c, method)(path, headers=out, **({"json": body} if body else {}))
            self.assertEqual(r.status_code, 404, path)           # 404, not 403: it does not even confirm the trip exists
        self.assertEqual(self.c.get(f"/api/trips/{tid}").status_code, 401)

    def test_wrong_codes_are_refused_and_guessing_is_rate_limited(self):
        t = self.make(self.user("a@epic.test"))
        g = self.user("g@epic.test", "Guesser")
        for _ in range(10):
            self.assertEqual(self.c.post("/api/trips/join", json={"code": "ZZZZZZZZ"}, headers=g).status_code, 404)
        self.assertEqual(self.c.post("/api/trips/join", json={"code": "ZZZZZZZZ"}, headers=g).status_code, 429)
        self.assertEqual(self.c.post("/api/trips/join", json={"code": t["join"]["code"]}, headers=g).status_code, 429)   # even the right code, until the hour is up

    def test_the_owner_can_rotate_or_disable_the_code(self):
        a, b, c = self.user("a@epic.test"), self.user("b@epic.test", "Bala"), self.user("c@epic.test", "Chitra")
        t = self.make(a)
        old = t["join"]["code"]
        new = self.c.post(f"/api/trips/{t['id']}/code", json={"action": "regenerate"}, headers=a).get_json()["join"]["code"]
        self.assertNotEqual(old, new)
        self.assertEqual(self.c.post("/api/trips/join", json={"code": old}, headers=b).status_code, 404)
        self.c.post(f"/api/trips/{t['id']}/code", json={"action": "disable"}, headers=a)
        self.assertEqual(self.c.post("/api/trips/join", json={"code": new}, headers=b).status_code, 404)
        self.c.post(f"/api/trips/{t['id']}/code", json={"action": "enable"}, headers=a)
        self.assertEqual(self.c.post("/api/trips/join", json={"code": new}, headers=b).status_code, 200)
        self.assertEqual(self.c.post(f"/api/trips/{t['id']}/code", json={"action": "disable"}, headers=b).status_code, 403)

    def test_the_trip_has_a_size_limit(self):
        hs = [self.user(f"m{i}@epic.test", f"M {i}") for i in range(trips.MAX_MEMBERS + 1)]
        t = self.make(hs[0])
        codes = [self.c.post("/api/trips/join", json={"code": t["join"]["code"]}, headers=h).status_code for h in hs[1:]]
        self.assertEqual(codes, [200] * (trips.MAX_MEMBERS - 1) + [400])

    def test_validation_of_trip_creation(self):
        h = self.user()
        for body in ({}, {"name": ""}, {"name": " " * 5}, {"name": "x" * 81}, {"name": "ok", "start_date": "next week"}):
            self.assertEqual(self.c.post("/api/trips", json=body, headers=h).status_code, 400, body)

    def test_leaving_and_removal_need_a_settled_balance(self):
        tid, hs, ids = self.group(3)
        self.expense(hs[0], tid, 9000, ids[0])                        # the owner paid; the other two each owe 3000
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[1]}", headers=hs[1]).status_code, 400)   # can't leave in debt
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[1]}", headers=hs[0]).status_code, 400)
        self.assertEqual(self.c.post(f"/api/trips/{tid}/settle", json={"from": ids[1], "to": ids[0], "amount": 3000}, headers=hs[1]).status_code, 201)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[1]}", headers=hs[1]).status_code, 200)
        self.assertEqual(self.c.get(f"/api/trips/{tid}", headers=hs[1]).status_code, 404)                          # gone for them
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[2]}", headers=hs[1]).status_code, 404)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[0]}", headers=hs[0]).status_code, 400)      # the owner can't leave
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[2]}", headers=hs[2]).status_code, 400)      # still owes 3000

    def test_only_the_owner_can_remove_someone_else_and_a_returning_member_keeps_their_history(self):
        tid, hs, ids = self.group(3)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[2]}", headers=hs[1]).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/members/{ids[2]}", headers=hs[0]).status_code, 200)
        code = self.get(hs[0], tid)["join"]["code"]
        back = self.c.post("/api/trips/join", json={"code": code}, headers=hs[2]).get_json()
        self.assertEqual(back["me"], ids[2])                          # same member id: their old shares still add up

    def test_only_the_owner_can_delete_the_trip(self):
        tid, hs, ids = self.group(2)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}", headers=hs[1]).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}", headers=hs[0]).status_code, 200)
        self.assertEqual(self.c.get(f"/api/trips/{tid}", headers=hs[0]).status_code, 404)


class ItineraryTests(TripBase):
    def add(self, h, tid, **kw):
        return self.c.post(f"/api/trips/{tid}/items", json={"day": 1, "title": "Visit the temple", **kw}, headers=h)

    def test_items_are_ordered_by_day_then_time(self):
        tid, hs, _ = self.group(2)
        for kw in ({"day": 2, "time": "09:00", "title": "d2 morning"}, {"day": 1, "time": "16:00", "title": "d1 evening"},
                   {"day": 1, "time": "08:30", "title": "d1 early"}, {"day": 1, "title": "d1 untimed"}):
            self.assertEqual(self.add(hs[1], tid, **kw).status_code, 201)
        self.assertEqual([i["title"] for i in self.get(hs[0], tid)["items"]], ["d1 early", "d1 evening", "d1 untimed", "d2 morning"])

    def test_item_validation(self):
        tid, hs, _ = self.group(1)
        for kw in ({"day": 0}, {"day": 61}, {"day": "1"}, {"day": True}, {"time": "25:00"}, {"time": "9am"}, {"title": ""}, {"title": "x" * 121}, {"notes": "n" * 501}):
            self.assertEqual(self.add(hs[0], tid, **kw).status_code, 400, kw)
        ok = self.add(hs[0], tid, place="atlantis", notes="  a   note  ").get_json()
        self.assertEqual((ok["place"], ok["notes"]), (None, "a note"))                           # unknown places are dropped, spaces tidied

    def test_two_people_editing_the_same_item_do_not_overwrite_each_other(self):
        tid, hs, _ = self.group(2)
        item = self.add(hs[0], tid).get_json()
        first = self.c.patch(f"/api/trips/{tid}/items/{item['id']}", json={"base_rev": item["rev"], "title": "Moved to 10am"}, headers=hs[0])
        self.assertEqual(first.status_code, 200)
        stale = self.c.patch(f"/api/trips/{tid}/items/{item['id']}", json={"base_rev": item["rev"], "title": "My different idea"}, headers=hs[1])
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["error"], "conflict")
        self.assertEqual(stale.get_json()["current"]["title"], "Moved to 10am")                    # they get the latest to merge against
        retry = self.c.patch(f"/api/trips/{tid}/items/{item['id']}", json={"base_rev": stale.get_json()["current"]["rev"], "title": "My different idea"}, headers=hs[1])
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(self.c.patch(f"/api/trips/{tid}/items/{item['id']}", json={"title": "no rev"}, headers=hs[1]).status_code, 409)

    def test_editing_keeps_the_fields_you_did_not_send(self):
        tid, hs, _ = self.group(1)
        item = self.add(hs[0], tid, time="09:15", notes="bring water").get_json()
        out = self.c.patch(f"/api/trips/{tid}/items/{item['id']}", json={"base_rev": item["rev"], "title": "New title"}, headers=hs[0]).get_json()
        self.assertEqual((out["title"], out["time"], out["notes"], out["day"]), ("New title", "09:15", "bring water", 1))

    def test_only_the_author_or_owner_can_delete(self):
        tid, hs, _ = self.group(3)
        item = self.add(hs[1], tid).get_json()
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/items/{item['id']}", headers=hs[2]).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/items/{item['id']}", headers=hs[1]).status_code, 200)
        item2 = self.add(hs[1], tid).get_json()
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/items/{item2['id']}", headers=hs[0]).status_code, 200)    # the owner can
        self.assertEqual(self.get(hs[0], tid)["items"], [])
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/items/{item2['id']}", headers=hs[0]).status_code, 404)

    def test_import_is_all_or_nothing(self):
        tid, hs, _ = self.group(1)
        good = {"day": 1, "title": "Meenakshi Amman Temple", "time": "07:00", "place": "madurai"}
        self.assertEqual(self.c.post(f"/api/trips/{tid}/items/import", json={"items": [good, {"day": 99, "title": "bad"}]}, headers=hs[0]).status_code, 400)
        self.assertEqual(self.get(hs[0], tid)["items"], [])
        self.assertEqual(self.c.post(f"/api/trips/{tid}/items/import", json={"items": [good, dict(good, day=2)]}, headers=hs[0]).get_json(), {"added": 2})
        for bad in ([], None, "x", [1], [good] * 61):
            self.assertEqual(self.c.post(f"/api/trips/{tid}/items/import", json={"items": bad}, headers=hs[0]).status_code, 400)


class PollTests(TripBase):
    def poll(self, h, tid, q="Where to eat?", options=("Murugan Idli", "Meenakshi Bhavan")):
        return self.c.post(f"/api/trips/{tid}/polls", json={"question": q, "options": list(options)}, headers=h)

    def test_voting_changing_and_withdrawing(self):
        tid, hs, ids = self.group(3)
        self.poll(hs[0], tid)
        p = self.get(hs[0], tid)["polls"][0]
        a, b = (o["id"] for o in p["options"])
        vote = lambda h, o: self.c.post(f"/api/trips/{tid}/polls/{p['id']}/vote", json={"option_id": o}, headers=h)
        for h, o in ((hs[0], a), (hs[1], a), (hs[2], b)):
            self.assertEqual(vote(h, o).status_code, 200)
        snap = self.get(hs[1], tid)["polls"][0]
        self.assertEqual((snap["tally"][a], snap["tally"][b], snap["voters"], snap["my_vote"]), (2, 1, 3, a))
        vote(hs[2], a)                                                                     # change a vote
        self.assertEqual(self.get(hs[0], tid)["polls"][0]["tally"], {a: 3, b: 0})
        vote(hs[2], a)                                                                     # tap again: withdraw
        self.assertEqual(self.get(hs[0], tid)["polls"][0]["tally"], {a: 2, b: 0})
        self.assertEqual(vote(hs[0], "o_fake").status_code, 400)

    def test_poll_validation_and_closing(self):
        tid, hs, _ = self.group(2)
        for q, opts in (("", ["a", "b"]), ("q?", ["only one"]), ("q?", ["a", "A"]), ("q?", ["a"] * 2), ("q?", list("abcdefghi")), ("q?", [" ", "b"])):
            self.assertEqual(self.poll(hs[0], tid, q, opts).status_code, 400, (q, opts))
        for raw in ("ab", None, {"a": 1}, 5):                      # not a list at all
            self.assertEqual(self.c.post(f"/api/trips/{tid}/polls", json={"question": "q?", "options": raw}, headers=hs[0]).status_code, 400, raw)
        self.poll(hs[1], tid)
        pid = self.get(hs[0], tid)["polls"][0]["id"]
        oid = self.get(hs[0], tid)["polls"][0]["options"][0]["id"]
        self.assertEqual(self.c.post(f"/api/trips/{tid}/polls/{pid}/close", headers=hs[0]).status_code, 200)     # the owner may close it
        self.assertEqual(self.c.post(f"/api/trips/{tid}/polls/{pid}/vote", json={"option_id": oid}, headers=hs[1]).status_code, 409)
        self.assertTrue(self.get(hs[1], tid)["polls"][0]["closed"])


class SyncTests(TripBase):
    def test_polling_with_the_current_rev_returns_nothing_new(self):
        tid, hs, _ = self.group(2)
        snap = self.get(hs[1], tid)
        self.assertEqual(self.get(hs[1], tid, since=snap["rev"]), {"rev": snap["rev"], "changed": False})
        self.c.post(f"/api/trips/{tid}/items", json={"day": 1, "title": "New thing"}, headers=hs[0])
        fresh = self.get(hs[1], tid, since=snap["rev"])
        self.assertTrue(fresh["changed"])
        self.assertGreater(fresh["rev"], snap["rev"])
        self.assertEqual([i["title"] for i in fresh["items"]], ["New thing"])

    def test_every_kind_of_change_advances_the_rev(self):
        tid, hs, ids = self.group(2)
        revs = [self.get(hs[0], tid)["rev"]]
        steps = [lambda: self.c.post(f"/api/trips/{tid}/items", json={"day": 1, "title": "x"}, headers=hs[0]),
                 lambda: self.c.post(f"/api/trips/{tid}/polls", json={"question": "q?", "options": ["a", "b"]}, headers=hs[0]),
                 lambda: self.expense(hs[0], tid, 500, ids[0]),
                 lambda: self.c.post(f"/api/trips/{tid}/code", json={"action": "regenerate"}, headers=hs[0])]
        for step in steps:
            self.assertEqual(step().status_code in (200, 201), True)
            revs.append(self.get(hs[0], tid)["rev"])
        self.assertEqual(revs, sorted(set(revs)))

    def test_many_people_writing_at_once_lose_nothing(self):
        tid, hs, ids = self.group(5)
        start = self.get(hs[0], tid)["rev"]

        def go(i):
            return base.A.app.test_client().post(f"/api/trips/{tid}/expenses", headers=hs[i % 5],
                                                 json={"description": f"E{i}", "amount": 100 + i, "paid_by": ids[i % 5]}).status_code

        with ThreadPoolExecutor(10) as pool:
            codes = list(pool.map(go, range(20)))
        snap = self.get(hs[0], tid)
        self.assertEqual((codes.count(201), len(snap["expenses"]), snap["rev"] - start), (20, 20, 20))
        self.assertEqual(sum(self.balances(hs[0], tid).values()), 0)


class ExpenseTests(TripBase):
    def test_equal_split_adds_up_exactly_with_leftover_paise_shared_out(self):
        tid, hs, ids = self.group(3)
        e = self.expense(hs[0], tid, 100, ids[0]).get_json()                       # Rs 1.00 between three people
        self.assertEqual(sorted(e["shares"].values()), [33, 33, 34])
        self.assertEqual(sum(e["shares"].values()), 100)
        bal = self.balances(hs[0], tid)
        self.assertEqual(sum(bal.values()), 0)
        self.assertEqual(bal[ids[0]], 100 - e["shares"][ids[0]])

    def test_equal_split_among_some_members_only(self):
        tid, hs, ids = self.group(4)
        e = self.expense(hs[0], tid, 1000, ids[0], mode="equal", among=[ids[0], ids[1]]).get_json()
        self.assertEqual(e["shares"], {ids[0]: 500, ids[1]: 500})
        self.assertEqual(self.balances(hs[0], tid)[ids[2]], 0)

    def test_split_by_shares(self):
        tid, hs, ids = self.group(3)
        e = self.expense(hs[0], tid, 10000, ids[1], mode="shares", weights={ids[0]: 2, ids[1]: 1, ids[2]: 1}).get_json()
        self.assertEqual((e["shares"][ids[0]], e["shares"][ids[1]], e["shares"][ids[2]]), (5000, 2500, 2500))
        self.assertEqual(self.balances(hs[0], tid), {ids[0]: -5000, ids[1]: 7500, ids[2]: -2500})

    def test_exact_split_must_add_up(self):
        tid, hs, ids = self.group(3)
        self.assertEqual(self.expense(hs[0], tid, 1000, ids[0], mode="exact", amounts={ids[0]: 400, ids[1]: 500}).status_code, 400)
        ok = self.expense(hs[0], tid, 1000, ids[0], mode="exact", amounts={ids[0]: 400, ids[1]: 600}).get_json()
        self.assertEqual(ok["shares"], {ids[0]: 400, ids[1]: 600})

    def test_expense_validation(self):
        tid, hs, ids = self.group(2)
        good = {"description": "Fuel", "amount": 500, "paid_by": ids[0]}
        for label, change in [("zero", {"amount": 0}), ("negative", {"amount": -5}), ("float", {"amount": 12.5}), ("string", {"amount": "500"}), ("bool", {"amount": True}),
                              ("too big", {"amount": trips.MAX_AMOUNT + 1}), ("no description", {"description": " "}), ("unknown payer", {"paid_by": "m_nobody"}),
                              ("bad date", {"date": "yesterday"}), ("unknown member in split", {"split": {"mode": "equal", "among": ["m_nobody"]}}),
                              ("bad mode", {"split": {"mode": "random"}}), ("zero weight", {"split": {"mode": "shares", "weights": {ids[0]: 0}}}),
                              ("empty shares", {"split": {"mode": "shares", "weights": {}}})]:
            self.assertEqual(self.c.post(f"/api/trips/{tid}/expenses", json={**good, **change}, headers=hs[0]).status_code, 400, label)
        self.assertEqual(self.get(hs[0], tid)["expenses"], [])

    def test_editing_and_deleting_expenses_recomputes_the_balances(self):
        tid, hs, ids = self.group(3)
        e = self.expense(hs[1], tid, 1000, ids[1], mode="equal", among=[ids[0], ids[1]]).get_json()
        self.assertEqual(self.balances(hs[0], tid), {ids[0]: -500, ids[1]: 500, ids[2]: 0})
        edit = self.c.patch(f"/api/trips/{tid}/expenses/{e['id']}", json={"base_rev": e["rev"], "amount": 3000}, headers=hs[1])
        self.assertEqual(edit.status_code, 200, edit.get_json())
        self.assertEqual(self.balances(hs[0], tid), {ids[0]: -1500, ids[1]: 1500, ids[2]: 0})
        self.assertEqual(self.c.patch(f"/api/trips/{tid}/expenses/{e['id']}", json={"base_rev": e["rev"], "amount": 1}, headers=hs[1]).status_code, 409)   # stale
        self.assertEqual(self.c.patch(f"/api/trips/{tid}/expenses/{e['id']}", json={"base_rev": edit.get_json()["rev"], "amount": 5}, headers=hs[2]).status_code, 403)   # a bystander
        self.assertEqual(self.c.patch(f"/api/trips/{tid}/expenses/{e['id']}", json={"base_rev": edit.get_json()["rev"], "amount": 4000}, headers=hs[0]).status_code, 200)   # the owner may
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/expenses/{e['id']}", headers=hs[1]).status_code, 200)
        self.assertEqual(self.balances(hs[0], tid), {ids[0]: 0, ids[1]: 0, ids[2]: 0})
        self.assertEqual(self.get(hs[0], tid)["expenses"], [])

    def test_totals_ignore_recorded_payments(self):
        tid, hs, ids = self.group(2)
        self.expense(hs[0], tid, 2000, ids[0])
        self.c.post(f"/api/trips/{tid}/settle", json={"from": ids[1], "to": ids[0], "amount": 1000}, headers=hs[1])
        t = self.get(hs[0], tid)
        self.assertEqual((t["totals"]["spent"], t["totals"]["per_person"], len(t["expenses"])), (2000, 1000, 2))
        self.assertEqual(t["transfers"], [])


class SettleUpTests(TripBase):
    def test_apportion_always_adds_up_and_stays_within_a_paisa_of_fair(self):
        rng = random.Random(7)
        for _ in range(500):
            n = rng.randint(1, 9)
            weights = {f"m{i}": rng.randint(1, 20) for i in range(n)}
            total = rng.randint(1, 10_000_000)
            parts = trips.apportion(total, weights)
            self.assertEqual(sum(parts.values()), total)
            w = sum(weights.values())
            for k, v in parts.items():
                self.assertLess(abs(v - total * weights[k] / w), 1.0 + 1e-9)

    def test_transfers_clear_every_balance_in_at_most_n_minus_1_payments(self):
        rng = random.Random(11)
        for _ in range(300):
            n = rng.randint(2, 10)
            net = {f"m{i}": 0 for i in range(n)}
            for _ in range(rng.randint(1, 25)):                      # random expenses, each shared out among a random group
                payer = f"m{rng.randrange(n)}"
                group = {f"m{i}": 1 for i in rng.sample(range(n), rng.randint(1, n))}
                amount = rng.randint(1, 500_000)
                net[payer] += amount
                for k, v in trips.apportion(amount, group).items():
                    net[k] -= v
            self.assertEqual(sum(net.values()), 0)
            moves = trips.transfers(net)
            self.assertLessEqual(len(moves), max(0, n - 1))
            after = dict(net)
            for m in moves:
                self.assertGreater(m["amount"], 0)
                after[m["from"]] += m["amount"]
                after[m["to"]] -= m["amount"]
            self.assertEqual(set(after.values()) - {0}, set(), "balances not cleared")

    def test_a_chain_of_debts_collapses_to_fewer_payments(self):
        # A owes B 10, B owes C 10: instead of two payments, A just pays C.
        moves = trips.transfers({"A": -10, "B": 0, "C": 10})
        self.assertEqual(moves, [{"from": "A", "to": "C", "amount": 10}])

    def test_recording_a_payment_moves_balances_toward_zero(self):
        tid, hs, ids = self.group(3)
        self.expense(hs[0], tid, 9000, ids[0])
        t = self.get(hs[0], tid)
        self.assertEqual(sorted((x["amount"]) for x in t["transfers"]), [3000, 3000])
        self.assertEqual(self.c.post(f"/api/trips/{tid}/settle", json={"from": ids[1], "to": ids[0], "amount": 3000}, headers=hs[1]).status_code, 201)
        t = self.get(hs[0], tid)
        self.assertEqual(self.balances(hs[0], tid), {ids[0]: 3000, ids[1]: 0, ids[2]: -3000})
        self.assertEqual(t["transfers"], [{"from": ids[2], "to": ids[0], "amount": 3000}])
        self.assertEqual(self.c.post(f"/api/trips/{tid}/settle", json={"from": ids[2], "to": ids[0], "amount": 3000}, headers=hs[2]).status_code, 201)
        self.assertEqual(self.get(hs[0], tid)["transfers"], [])

    def test_who_may_record_a_payment(self):
        tid, hs, ids = self.group(3)
        body = {"from": ids[1], "to": ids[0], "amount": 100}
        self.assertEqual(self.c.post(f"/api/trips/{tid}/settle", json=body, headers=hs[2]).status_code, 403)     # a bystander
        self.assertEqual(self.c.post(f"/api/trips/{tid}/settle", json=body, headers=hs[0]).status_code, 201)     # the owner (also a party)
        for bad in ({"from": ids[0], "to": ids[0], "amount": 5}, {"from": ids[0], "to": "m_x", "amount": 5}, {"from": ids[1], "to": ids[0], "amount": 0},
                    {"from": ids[1], "to": ids[0], "amount": 1.5}):
            self.assertEqual(self.c.post(f"/api/trips/{tid}/settle", json=bad, headers=hs[0]).status_code, 400, bad)

    def test_a_recorded_payment_cannot_be_edited_only_deleted(self):
        tid, hs, ids = self.group(2)
        s = self.c.post(f"/api/trips/{tid}/settle", json={"from": ids[1], "to": ids[0], "amount": 100}, headers=hs[1]).get_json()
        self.assertEqual(self.c.patch(f"/api/trips/{tid}/expenses/{s['id']}", json={"base_rev": s["rev"], "amount": 5}, headers=hs[1]).status_code, 400)
        self.assertEqual(self.c.delete(f"/api/trips/{tid}/expenses/{s['id']}", headers=hs[1]).status_code, 200)


if __name__ == "__main__":
    unittest.main()
