"""Live rail timetable: parsing, caching, quota, fallback. The network is replaced by a fake `requests.get`."""

import os
import unittest
from datetime import date
from unittest import mock

from tests import base  # noqa: F401  (sets the test environment)

import railapi
import transport

PAYLOAD = {"success": True, "data": {"trains": [
    {"train": {"number": "20602", "name": "Chennai SF", "type": "Superfast Express", "runDays": ["mon", "tue"]},
     "from": {"departure": "22:45", "day": 1}, "to": {"arrival": "07:55", "day": 2}, "distance": 555.9},
    {"train": {"number": "06154", "name": "Special", "type": "Mail/Express", "runDays": ["thu"]},
     "from": {"departure": "15:30", "day": 1}, "to": {"arrival": "03:30", "day": 2}, "distance": 556},
    {"bad": "row"}]}}


class Resp:
    def __init__(self, code=200, body=PAYLOAD):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class RailApiTests(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("RAIL_API_KEY")
        os.environ["RAIL_API_KEY"] = "test-key"
        try:
            os.remove(railapi._path())
        except OSError:
            pass

    def tearDown(self):
        os.environ["RAIL_API_KEY"] = self.old or ""

    def test_disabled_without_key(self):
        os.environ["RAIL_API_KEY"] = ""
        with mock.patch("railapi.requests.get") as g:
            self.assertIsNone(railapi.between("MDU", "MAS"))
            g.assert_not_called()

    def test_parse_cache_and_header(self):
        with mock.patch("railapi.requests.get", return_value=Resp()) as g:
            rows = railapi.between("MDU", "MAS")
            self.assertEqual([r["no"] for r in rows], ["20602", "06154"])          # malformed row skipped
            self.assertEqual(railapi.between("MDU", "MAS"), rows)
            self.assertEqual(g.call_count, 1)                                       # second call came from the cache
            self.assertEqual(g.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_failure_falls_back_and_is_remembered(self):
        with mock.patch("railapi.requests.get", return_value=Resp(500, {})) as g:
            self.assertIsNone(railapi.between("MDU", "MAS"))
            self.assertIsNone(railapi.between("MDU", "MAS"))
            self.assertEqual(g.call_count, 1)

    def test_monthly_budget_stops_calls(self):
        with mock.patch("railapi.requests.get", return_value=Resp()) as g:
            with mock.patch.object(railapi, "MONTHLY_BUDGET", 2):
                for a, b in (("MDU", "MAS"), ("TPJ", "MAS"), ("CBE", "MAS")):
                    railapi.between(a, b)
            self.assertEqual(g.call_count, 2)

    def test_search_uses_live_rows_for_the_weekday(self):
        monday, thursday = date(2030, 1, 7), date(2030, 1, 10)
        with mock.patch("railapi.requests.get", return_value=Resp()):
            mon = transport.search_trains("MDU", "MAS", monday)
            thu = transport.search_trains("MDU", "MAS", thursday)
        self.assertEqual([t["no"] for t in mon], ["20602"])
        self.assertEqual([t["no"] for t in thu], ["06154"])
        self.assertTrue(mon[0]["live"] and mon[0]["arrive_next_day"])
        self.assertEqual(mon[0]["duration"], "9h 10m")

    def test_static_timetable_when_live_has_nothing(self):
        with mock.patch("railapi.requests.get", return_value=Resp(500, {})):
            rows = transport.search_trains("MAS", "MDU", date(2030, 1, 7))
        self.assertTrue(rows and not rows[0].get("live"))


if __name__ == "__main__":
    unittest.main()
