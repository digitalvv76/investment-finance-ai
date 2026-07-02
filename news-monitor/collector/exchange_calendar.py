"""NYSE/NASDAQ trading calendar with session detection."""
from datetime import date, datetime, time, timedelta
from typing import Set, Tuple
import json
import os
from pathlib import Path


# Known NYSE holidays for 2026 (will be augmented with API)
KNOWN_HOLIDAYS_2026 = {
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Martin Luther King Jr. Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}

# Session boundaries in ET (Eastern Time)
# Overnight: 20:00-04:00 | Pre-market: 04:00-09:30 | Regular: 09:30-16:00 | After-hours: 16:00-20:00
SESSION_BOUNDARIES = [
    (time(4, 0), "pre-market"),
    (time(9, 30), "regular"),
    (time(16, 0), "after-hours"),
    (time(20, 0), "overnight"),
]


class ExchangeCalendar:
    def __init__(self, holidays_file: str = "data/holidays.json"):
        self.holidays_file = Path(holidays_file)
        self._holidays: Set[date] = set(KNOWN_HOLIDAYS_2026)
        self._load_persisted_holidays()

    def _load_persisted_holidays(self):
        if self.holidays_file.exists():
            with open(self.holidays_file) as f:
                data = json.load(f)
                for d_str in data.get("holidays", []):
                    self._holidays.add(date.fromisoformat(d_str))

    def _persist(self):
        self.holidays_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.holidays_file, 'w') as f:
            data = {"holidays": [d.isoformat() for d in sorted(self._holidays)]}
            json.dump(data, f, indent=2)

    def add_holiday(self, d: date):
        self._holidays.add(d)
        self._persist()

    def is_holiday(self, d: date) -> bool:
        return d in self._holidays or d.weekday() >= 5  # Sat=5, Sun=6

    def is_trading_day(self, d: date = None) -> bool:
        if d is None:
            d = date.today()
        return not self.is_holiday(d)

    def current_session(self, dt: datetime = None) -> str:
        """Return current market session for ET timezone.
        Returns one of: 'overnight', 'pre-market', 'regular', 'after-hours', 'weekend'
        """
        if dt is None:
            dt = datetime.utcnow() - timedelta(hours=4)  # Approximate ET (UTC-4 EDT)

        d = dt.date()
        if not self.is_trading_day(d):
            return "weekend"

        t = dt.time()
        # Check sessions in reverse order (latest boundary first)
        for boundary_time, session_name in reversed(SESSION_BOUNDARIES):
            if t >= boundary_time:
                return session_name
        return "overnight"  # before 4:00 AM

    def is_market_open(self, dt: datetime = None) -> bool:
        session = self.current_session(dt)
        return session not in ("weekend",)

    def is_weekend_mode(self, dt: datetime = None) -> bool:
        return not self.is_market_open(dt)

    def next_trading_day(self, d: date = None) -> date:
        if d is None:
            d = date.today()
        d += timedelta(days=1)
        while self.is_holiday(d):
            d += timedelta(days=1)
        return d
