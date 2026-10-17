import unittest
from datetime import date

from tests import base  # noqa: F401  (sets up the temp store)
import crowd


class CrowdTests(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(crowd.months_in("April/May"), {4, 5})
        self.assertEqual(crowd.months_in("January & July"), {1, 7})
        self.assertEqual(crowd.months_in("Thai Poosam (Jan/Feb)"), {1, 2})
        self.assertEqual(crowd.months_in("Winter"), {12, 1, 2})
        self.assertEqual(crowd.months_in("Once every 12 years"), set())
        self.assertEqual(crowd.months_in("Jumada al-Thani (varies)"), set())

    def test_best_months_ranges_wrap_the_year(self):
        self.assertEqual(crowd.best_months("November to February"), {11, 12, 1, 2})
        self.assertEqual(crowd.best_months("March to June and September to November"), {3, 4, 5, 6, 9, 10, 11})

    def test_exact_window_and_wrapping(self):
        self.assertEqual(crowd.exact_window("Aug 29 - Sep 8"), ((8, 29), (9, 8)))
        self.assertIsNone(crowd.exact_window("April/May"))
        self.assertTrue(crowd.in_window(date(2026, 1, 1), (12, 24), (1, 2)))       # wraps the new year
        self.assertFalse(crowd.in_window(date(2026, 6, 1), (12, 24), (1, 2)))

    def test_pongal_day_is_high_and_explains_itself(self):
        r = crowd.day_forecast("madurai", date(2027, 1, 15))
        self.assertEqual(r["level"], "High")
        self.assertIn("Pongal holidays", [f["label"] for f in r["factors"]])

    def test_quiet_weekday_in_season_is_low(self):
        self.assertEqual(crowd.day_forecast("madurai", date(2026, 10, 14))["level"], "Low")

    def test_weekend_scores_higher_than_the_weekday_before_it(self):
        self.assertGreater(crowd.score_day("madurai", date(2026, 10, 17))[0], crowd.score_day("madurai", date(2026, 10, 14))[0])

    def test_velankanni_feast_is_high_even_though_it_is_off_season(self):
        self.assertEqual(crowd.day_forecast("velankanni", date(2026, 9, 3))["level"], "High")

    def test_summer_holidays_hit_hill_stations_harder_than_cities(self):
        self.assertGreater(crowd.score_day("ooty", date(2027, 5, 12))[0] - crowd.score_day("ooty", date(2027, 3, 10))[0],
                           crowd.score_day("chennai", date(2027, 5, 12))[0] - crowd.score_day("chennai", date(2027, 5, 1))[0] - 0.5)

    def test_every_day_of_a_year_for_every_town_scores_and_most_days_are_not_high(self):
        for dest in crowd.BY_ID:
            days = crowd.forecast(dest, date(2027, 1, 1), 365)
            self.assertEqual(len(days), 365)
            self.assertLess(sum(d["level"] == "High" for d in days) / 365, 0.2, dest)
            self.assertTrue(all(d["level"] in crowd.LEVELS for d in days))

    def test_quieter_dates_are_lower_nearer_first_and_never_in_the_past(self):
        target = date(2027, 1, 16)                                   # a Saturday in the Pongal window
        out = crowd.quieter_dates("madurai", target, today=date(2027, 1, 1))
        self.assertTrue(out)
        base_score = crowd.score_day("madurai", target)[0]
        self.assertTrue(all(o["score"] < base_score for o in out))
        self.assertEqual(out, sorted(out, key=lambda o: (o["score"], o["days_away"])))
        past = crowd.quieter_dates("madurai", target, today=date(2027, 1, 30))
        self.assertEqual(past, [])

    def test_price_factor_orders_levels(self):
        self.assertLess(crowd.price_factor("Low"), crowd.price_factor("Medium"))
        self.assertLess(crowd.price_factor("Medium"), crowd.price_factor("High"))

    def test_unknown_town_raises(self):
        with self.assertRaises(KeyError):
            crowd.forecast("atlantis", date(2027, 1, 1), 3)


if __name__ == "__main__":
    unittest.main()
