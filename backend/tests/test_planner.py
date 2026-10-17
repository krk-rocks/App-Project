import itertools
import random
import unittest
from datetime import date, timedelta

from tests import base
import activities as AC
import clock
import planner as P
import transport

BASE = {"start_date": "2026-11-20", "travellers": 2}


def hm(s):
    h, m = s.split(":")
    return int(h) + int(m) / 60


def req(**kw):
    return {**BASE, **kw}


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        clock.freeze(base.NOON)

    def tearDown(self):
        clock.unfreeze()

    def test_defaults(self):
        r = P.normalize({})
        self.assertEqual((r["start"], r["days"], r["travellers"], r["pace"], r["comfort"], r["budget"], r["return_home"]),
                         ("chennai", 3, 2, "balanced", "standard", None, True))
        self.assertEqual(r["start_date"], "2026-10-08")                              # tomorrow
        self.assertEqual(set(r["interests"]), set(AC.INTERESTS))

    def test_places_can_be_given_by_id_or_name_in_any_case(self):
        self.assertEqual(P.normalize({"start": "OOTY"})["start"], "ooty")
        self.assertEqual(P.normalize({"start": "Ooty (Udhagamandalam)"})["start"], "ooty")
        self.assertEqual(P.normalize({"must": ["Madurai", "kodaikanal", "atlantis"]})["must"], ["madurai", "kodaikanal"])

    def test_bad_requests_are_refused_with_a_reason(self):
        bad = [{"start": "atlantis"}, {"days": 0}, {"days": 8}, {"days": "3"}, {"days": True}, {"travellers": 0}, {"travellers": 7},
               {"pace": "frantic"}, {"comfort": "royal"}, {"budget": 10}, {"budget": 5_000_000}, {"budget": "lots"}, {"budget": True},
               {"start_date": "tomorrow"}, {"start_date": "2020-01-01"}, {"start_date": "2030-01-01"},
               {"must": ["ooty"], "avoid": ["ooty"]}, {"days": 2, "must": ["ooty", "madurai", "chennai"]}, {"return_home": "yes"}]
        for b in bad:
            with self.assertRaises(P.PlanError, msg=str(b)):
                P.normalize(b)
        self.assertRaises(P.PlanError, P.normalize, {"avoid": P.PLACES})                      # everything avoided
        self.assertEqual(P.normalize("not a dict")["days"], 3)

    def test_unknown_interests_are_ignored_and_empty_means_everything(self):
        self.assertEqual(P.normalize({"interests": ["temples", "karaoke"]})["interests"], ["temples"])
        self.assertEqual(set(P.normalize({"interests": ["karaoke"]})["interests"]), set(AC.INTERESTS))


class RouteSearchTests(unittest.TestCase):
    def test_held_karp_matches_brute_force_over_every_ordering(self):
        rng = random.Random(3)
        for _ in range(25):
            origin = rng.choice(P.PLACES)
            towns = rng.sample(P.PLACES, rng.randint(2, 6))
            for back in (True, False):
                best, _ = P.tours(origin, towns, back)
                for size in range(1, len(towns) + 1):
                    for subset in itertools.combinations(range(len(towns)), size):
                        mask = sum(1 << i for i in subset)
                        want = min(P._t(origin, towns[p[0]]) + sum(P._t(towns[a], towns[b]) for a, b in zip(p, p[1:]))
                                   + (P._t(towns[p[-1]], origin) if back else 0) for p in itertools.permutations(subset))
                        self.assertAlmostEqual(best[mask][0], want, places=6)

    def test_the_reported_order_realises_the_reported_time(self):
        towns = P.PLACES[:7]
        best, order = P.tours("chennai", towns, True)
        for mask in (0b1010101, 0b0001111, 0b1000001):
            path = order(mask)
            self.assertEqual(sorted(path), sorted(towns[i] for i in range(7) if mask >> i & 1))
            hours = P._t("chennai", path[0]) + sum(P._t(a, b) for a, b in zip(path, path[1:])) + P._t(path[-1], "chennai")
            self.assertAlmostEqual(hours, best[mask][0], places=6)

    def test_travel_legs_are_sane(self):
        for a, b in itertools.permutations(P.PLACES, 2):
            for comfort in P.COMFORTS:
                lg = P.leg(a, b, comfort)
                self.assertGreater(lg["hours"], 0.4, (a, b))
                self.assertGreater(lg["fare"], 0)
                self.assertEqual(lg["overnight"], lg["hours"] >= P.OVERNIGHT_HOURS)
                self.assertIn(lg["mode"], ("bus", "train"))
        self.assertEqual(P.leg("madurai", "madurai", "standard")["hours"], 0)
        self.assertLess(P.leg("chennai", "mahabalipuram", "standard")["hours"], 3)             # 68 km
        self.assertGreater(P.leg("chennai", "kanyakumari", "standard")["hours"], 8)
        for a, b in (("chennai", "madurai"), ("madurai", "thanjavur")):                          # more comfort never costs less
            fares = [P.leg(a, b, c)["fare"] for c in P.COMFORTS]
            self.assertEqual(fares, sorted(fares))

    def test_a_town_without_a_station_adds_a_road_hop_to_the_train_time(self):
        direct = transport.rail_options("MAS", "KQN")
        self.assertTrue(direct)
        lg = P.leg("chennai", "kodaikanal", "standard")
        self.assertEqual(lg["mode"], "train")
        rail = min(o["minutes"] for o in direct) / 60 + 0.5                                      # best train + station buffer
        hop = transport.DEST_HUB["kodaikanal"]["transfer_km"] / 40 + 0.4                         # then the ghat road to the town
        self.assertAlmostEqual(lg["hours"], rail + hop, places=2)
        self.assertGreater(lg["hours"], rail + 2)

    def test_allocation_gives_every_town_a_day_and_hands_out_the_rest_where_it_helps(self):
        tags = AC.interest_tags(["temples"])
        alloc, value = P.allocate(["madurai", "kodaikanal"], 5, 3, tags)
        self.assertEqual((sum(alloc.values()), min(alloc.values()) >= 1), (5, True))
        self.assertGreater(alloc["madurai"], alloc["kodaikanal"])                                # temples: Madurai has the temples
        one, _ = P.allocate(["madurai"], 1, 3, tags)
        self.assertEqual(one, {"madurai": 1})


class PlanInvariantTests(base.Base):
    """Properties that must hold for EVERY plan, checked on a spread of generated requests."""

    def check(self, plan, r):
        s, cap = plan["summary"], P.PACE[r["pace"]]["cap"]
        pace = P.PACE[r["pace"]]
        self.assertEqual(s["days"], r["days"])
        self.assertEqual(len(plan["days"]), r["days"])
        self.assertLessEqual(len(s["towns"]), P.MAX_TOWNS)
        self.assertEqual(len(set(s["towns"])), len(s["towns"]))
        self.assertTrue(set(r["must"]) <= set(s["towns"]), "a required town was dropped")
        self.assertFalse(set(r["avoid"]) & set(s["towns"]), "an avoided town was visited")
        seen = set()
        for d in plan["days"]:
            self.assertEqual(date.fromisoformat(d["date"]), date.fromisoformat(r["start_date"]) + timedelta(days=d["day"] - 1))
            acts = [i for i in d["items"] if i["type"] == "activity"]
            self.assertLessEqual(len(acts), cap)
            timed = [i for i in d["items"] if i["type"] in ("activity", "meal")]
            for a, b in zip(timed, timed[1:]):
                self.assertLessEqual(hm(a["end"]), hm(b["start"]) + 1e-6, f"overlap on day {d['day']}: {a['title']} / {b['title']}")
            for i in acts:
                self.assertGreaterEqual(hm(i["start"]), pace["start"] - 1e-6)
                self.assertLessEqual(hm(i["end"]), pace["end"] + 1e-6)
                self.assertNotIn(i["id"], seen, "an activity was scheduled twice")
                seen.add(i["id"])
                a = AC.BY_ID[i["id"]]
                self.assertEqual(a["place"], d["town"])
                self.assertTrue(any(hm(o1) - 1e-6 <= hm(i["start"]) and hm(i["end"]) <= hm(o2) + 1e-6 for o1, o2 in a["open"]),
                                f"{i['title']} {i['start']}-{i['end']} is outside its opening hours {a['open']}")
        c = s["cost"]
        self.assertEqual(sum(c["breakdown"].values()), c["total"])
        self.assertEqual(c["per_person"], c["total"] // r["travellers"])
        self.assertEqual(c["breakdown"]["travel"], sum(l["fare"] for l in plan["legs"]) * r["travellers"])
        self.assertTrue(all(st["nights"] >= 1 for st in plan["stays"]))
        if r["budget"] is not None:
            self.assertEqual(s["over_budget"], c["total"] > r["budget"])
        chain = [r["start"]] + s["towns"] + ([r["start"]] if r["return_home"] else [])
        legs = [(l["from"], l["to"]) for l in plan["legs"]]
        self.assertEqual(legs, [(a, b) for a, b in zip(chain, chain[1:]) if a != b])

    def test_a_spread_of_random_requests_all_satisfy_the_invariants(self):
        rng = random.Random(42)
        for _ in range(120):
            r = {"start": rng.choice(P.PLACES), "days": rng.randint(1, 7), "travellers": rng.randint(1, 6),
                 "interests": rng.sample(list(AC.INTERESTS), rng.randint(1, 5)), "pace": rng.choice(P.PACES), "comfort": rng.choice(P.COMFORTS),
                 "budget": rng.choice([None, None, 4000, 9000, 20000, 60000]), "return_home": rng.random() < 0.7,
                 "start_date": (clock.today() + timedelta(days=rng.randint(1, 300))).isoformat()}
            if rng.random() < 0.3:
                r["must"] = rng.sample(P.PLACES, rng.randint(1, min(r["days"], 3)))
            if rng.random() < 0.3:
                r["avoid"] = rng.sample([p for p in P.PLACES if p not in r.get("must", [])], 3)
            plan = P.plan(r)
            self.check(plan, P.normalize(r))

    def test_the_same_request_always_gives_the_same_plan(self):
        r = req(start="madurai", days=5, interests=["temples", "nature"], budget=30000)
        self.assertEqual(P.plan(r), P.plan(dict(r)))

    def test_without_a_budget_the_plan_is_the_best_scoring_choice_of_towns(self):
        r = P.normalize(req(start="chennai", days=4, interests=["temples", "heritage"]))
        tags = AC.interest_tags(r["interests"])
        towns = list(P.PLACES)
        best, order = P.tours("chennai", towns, True)
        top = max(((P.allocate(order(m), 4, 3, tags)[1] - P.TRAVEL_PENALTY * best[m][0]), m) for m in range(1, 1 << len(towns))
                  if bin(m).count("1") <= 4)
        self.assertEqual(sorted(P.plan(req(start="chennai", days=4, interests=["temples", "heritage"]))["summary"]["towns"]), sorted(order(top[1])))

    def test_one_day_trip_has_no_hotel(self):
        p = P.plan(req(start="chennai", days=1))
        self.assertEqual((p["stays"], p["summary"]["days"]), ([], 1))
        self.assertEqual(p["summary"]["cost"]["breakdown"]["stay"], 0)

    def test_nights_are_days_minus_the_last_evening_and_minus_night_journeys(self):
        for r in (req(start="chennai", days=4, must=["kanyakumari"]), req(start="madurai", days=5), req(start="chennai", days=3, return_home=False)):
            p = P.plan(r)
            n = P.normalize(r)
            order, alloc = p["summary"]["towns"], {t: sum(1 for d in p["days"] if d["town"] == t) for t in p["summary"]["towns"]}
            legs = P._leg_list(n["start"], order, p["comfort"], n["return_home"])
            expected = P.nights(order, alloc, legs, n["return_home"])
            self.assertEqual({s["town"]: s["nights"] for s in p["stays"]}, {t: k for t, k in expected.items() if k})
            overnight_between = sum(1 for lg in legs[1:-1] if lg and lg["overnight"])
            self.assertEqual(sum(expected.values()), n["days"] - 1 - overnight_between)


class PlanBehaviourTests(base.Base):
    def test_temples_are_scheduled_in_their_real_sessions_around_the_midday_closure(self):
        p = P.plan(req(start="madurai", days=2, interests=["temples"]))
        meenakshi = [(i["start"], i["end"]) for d in p["days"] for i in d["items"] if i["title"] == "Meenakshi Amman Temple"]
        self.assertEqual(len(meenakshi), 1)
        s = hm(meenakshi[0][0])
        self.assertTrue(5 <= s <= 11 or 16 <= s <= 20.5, meenakshi)                              # sessions are 05:00-12:30 and 16:00-22:00

    def test_a_night_journey_does_not_use_up_the_day_but_a_daytime_one_does(self):
        p = P.plan(req(start="chennai", days=4, must=["kanyakumari"]))
        night = [i for d in p["days"] for i in d["items"] if i["type"] == "travel" and i.get("overnight")]
        self.assertTrue(night)
        self.assertTrue(all(hm(i["start"]) >= 21 or hm(i["start"]) < 12 for i in night))
        p2 = P.plan(req(start="chennai", days=2, must=["mahabalipuram"], interests=["heritage"]))
        day_travel = [(d, i) for d in p2["days"] for i in d["items"] if i["type"] == "travel" and not i.get("overnight")]
        self.assertTrue(day_travel)
        for d, i in day_travel:
            before = [x for x in d["items"] if x["type"] == "activity" and hm(x["end"]) > hm(i["start"]) + 1e-6]
            self.assertEqual(before, [], "an activity runs into the journey")

    def test_must_and_avoid_are_honoured(self):
        p = P.plan(req(start="chennai", days=5, must=["rameswaram", "ooty"], avoid=["madurai"]))
        self.assertTrue({"rameswaram", "ooty"} <= set(p["summary"]["towns"]))
        self.assertNotIn("madurai", p["summary"]["towns"])

    def test_not_returning_home_drops_the_last_leg(self):
        a = P.plan(req(start="chennai", days=4, must=["rameswaram"], return_home=True))
        b = P.plan(req(start="chennai", days=4, must=["rameswaram"], return_home=False))
        self.assertEqual(a["legs"][-1]["to"], "chennai")
        self.assertNotEqual(b["legs"][-1]["to"], "chennai") if b["legs"] else None
        self.assertLess(len(b["legs"]), len(a["legs"]) + 1)

    def test_a_tight_budget_steps_comfort_down_then_admits_defeat(self):
        loose = P.plan(req(start="chennai", days=4, comfort="comfort", budget=None))
        fits = P.plan(req(start="chennai", days=4, comfort="comfort", budget=int(loose["summary"]["cost"]["total"] * 0.6)))
        self.assertNotEqual(fits["comfort"], "comfort")
        self.assertFalse(fits["summary"]["over_budget"])
        self.assertLessEqual(fits["summary"]["cost"]["total"], int(loose["summary"]["cost"]["total"] * 0.6))
        self.assertTrue(any("to fit your budget" in n.lower() for n in fits["notes"]))
        hopeless = P.plan(req(start="chennai", days=4, budget=1000))
        self.assertTrue(hopeless["summary"]["over_budget"])
        self.assertEqual(hopeless["comfort"], "budget")
        self.assertIn("over your", hopeless["notes"][0])

    def test_more_comfort_costs_more_for_the_same_trip(self):
        costs = [P.plan(req(start="chennai", days=3, must=["madurai"], comfort=c))["summary"]["cost"]["total"] for c in P.COMFORTS]
        self.assertEqual(costs, sorted(costs))
        self.assertLess(costs[0], costs[2])

    def test_more_travellers_cost_more_but_not_proportionally_for_rooms(self):
        two, four = (P.plan(req(start="chennai", days=3, travellers=n))["summary"]["cost"]["total"] for n in (2, 4))
        self.assertGreater(four, two)
        self.assertLess(four, two * 2)

    def test_a_pace_changes_how_much_is_packed_in(self):
        counts = {}
        for pace in P.PACES:
            p = P.plan(req(start="madurai", days=2, pace=pace, interests=["temples", "heritage"]))
            counts[pace] = sum(1 for d in p["days"] for i in d["items"] if i["type"] == "activity")
        self.assertLessEqual(counts["relaxed"], counts["balanced"])
        self.assertLessEqual(counts["balanced"], counts["packed"])
        self.assertLess(counts["relaxed"], counts["packed"])

    def test_rain_moves_outdoor_stops_down_the_list(self):
        r = req(start="kodaikanal", days=1, interests=["nature"], pace="balanced")
        dry = P.plan(r)
        wet = P.plan(r, rain={("kodaikanal", r["start_date"]): 90})
        outdoor = lambda p: sum(1 for d in p["days"] for i in d["items"] if i.get("outdoor"))
        self.assertLess(outdoor(wet), outdoor(dry))
        self.assertTrue(any("Rain is likely" in n for d in wet["days"] for n in d["notes"]))
        self.assertFalse(any("Rain is likely" in n for d in dry["days"] for n in d["notes"]))
        mild = P.plan(r, rain={("kodaikanal", r["start_date"]): 40})
        self.assertEqual(outdoor(mild), outdoor(dry))                                           # only strong rain changes the plan

    def test_busy_days_are_flagged_and_off_season_is_mentioned(self):
        busy = P.plan(req(start="madurai", days=1, start_date="2027-01-15"))
        self.assertTrue(any("crowds" in n for n in busy["days"][0]["notes"]))
        self.assertEqual(busy["days"][0]["crowd"], "High")
        off = P.plan(req(start="ooty", days=1, start_date="2026-12-10", must=["ooty"]))
        self.assertTrue(any("out of its best season" in n for n in off["notes"]))

    def test_estimates_are_labelled(self):
        p = P.plan(req(start="chennai", days=2, interests=["heritage"]))
        self.assertTrue(any("typical hours" in n for n in p["notes"]))

    def test_leaving_the_evening_before_is_called_out_when_the_trip_opens_with_a_night_journey(self):
        p = P.plan(req(start="chennai", days=3, must=["kanyakumari"], avoid=["chennai", "kanchipuram", "mahabalipuram"]))
        self.assertEqual((p["legs"][0]["from"], p["legs"][0]["overnight"]), ("chennai", True))
        self.assertTrue(any("evening before Day 1" in n for n in p["notes"]))
        local = P.plan(req(start="chennai", days=2, must=["chennai"]))                           # starts where you already are
        self.assertFalse(any("evening before" in n for n in local["notes"]))

    def test_planning_is_fast(self):
        import time
        t = time.time()
        for s in P.PLACES:
            P.plan(req(start=s, days=7, pace="packed"))
        self.assertLess(time.time() - t, 3.0)


if __name__ == "__main__":
    unittest.main()
