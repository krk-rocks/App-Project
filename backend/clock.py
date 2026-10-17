"""One place for "now", so a test can freeze time and a booking-hold expiry can be tested
without sleeping. Everything that cares about the current moment calls clock.now()."""

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_frozen = None


def now():
    return _frozen or datetime.now(IST)


def today():
    return now().date()


def freeze(dt):
    global _frozen
    _frozen = dt if dt.tzinfo else dt.replace(tzinfo=IST)


def unfreeze():
    global _frozen
    _frozen = None
