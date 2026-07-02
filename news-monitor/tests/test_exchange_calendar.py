"""Tests for exchange calendar."""
import pytest
from datetime import date, datetime
from collector.exchange_calendar import ExchangeCalendar


@pytest.fixture
def cal():
    return ExchangeCalendar()


def test_weekend_not_trading_day(cal):
    saturday = date(2026, 7, 4)  # Saturday
    assert not cal.is_trading_day(saturday)

    sunday = date(2026, 7, 5)  # Sunday
    assert not cal.is_trading_day(sunday)


def test_weekday_is_trading_day(cal):
    wednesday = date(2026, 7, 1)  # Wednesday
    assert cal.is_trading_day(wednesday)


def test_known_holiday_not_trading_day(cal):
    # July 3, 2026 -- Independence Day observed
    assert not cal.is_trading_day(date(2026, 7, 3))


def test_add_custom_holiday(cal):
    custom = date(2026, 12, 31)
    cal.add_holiday(custom)
    assert not cal.is_trading_day(custom)


def test_weekend_mode(cal):
    # Saturday midnight ET
    saturday_dt = datetime(2026, 7, 4, 12, 0)
    assert cal.is_weekend_mode(saturday_dt)

    # Wednesday noon
    wednesday_dt = datetime(2026, 7, 1, 12, 0)
    assert not cal.is_weekend_mode(wednesday_dt)


def test_current_session_detection(cal):
    # Pre-market: 8:00 AM ET
    premarket = datetime(2026, 7, 1, 8, 0)
    assert cal.current_session(premarket) == "pre-market"

    # Regular: 11:00 AM ET
    regular = datetime(2026, 7, 1, 11, 0)
    assert cal.current_session(regular) == "regular"

    # After-hours: 17:00 ET
    after = datetime(2026, 7, 1, 17, 0)
    assert cal.current_session(after) == "after-hours"

    # Overnight: 2:00 AM ET
    overnight = datetime(2026, 7, 1, 2, 0)
    assert cal.current_session(overnight) == "overnight"


def test_next_trading_day(cal):
    wed = date(2026, 7, 1)
    next_day = cal.next_trading_day(wed)
    assert next_day == date(2026, 7, 2)  # Thursday (July 3 is holiday)


def test_is_market_open(cal):
    # Wednesday 10am -- open
    assert cal.is_market_open(datetime(2026, 7, 1, 10, 0))
    # Sunday -- closed
    assert not cal.is_market_open(datetime(2026, 7, 5, 10, 0))
