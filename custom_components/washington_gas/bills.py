"""Bill handling without Home Assistant dependencies."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
import math


@dataclass(frozen=True)
class Bill:
    """One bill; end is exclusive."""

    start: date
    end: date
    usage: float
    cost: float

    @property
    def days(self) -> int:
        """Return the number of days billed."""
        return (self.end - self.start).days


def check(bills: list[Bill]) -> None:
    """Raise ValueError on implausible data, before anything is stored."""
    if len(bills) > 500:
        raise ValueError("too many bills")
    previous_end = None
    for bill in sorted(bills, key=lambda b: b.start):
        if not 1 <= bill.days <= 120:
            raise ValueError(f"bill period of {bill.days} days")
        if previous_end and bill.start < previous_end:
            raise ValueError("overlapping bills")
        if not (math.isfinite(bill.usage) and 0 <= bill.usage <= 5000):
            raise ValueError("implausible usage")
        if not (math.isfinite(bill.cost) and abs(bill.cost) <= 10000):
            raise ValueError("implausible cost")
        previous_end = bill.end


def merge(stored: list[Bill], fetched: list[Bill]) -> list[Bill]:
    """Fetched bills replace stored ones; older stored history is kept."""
    fetched = sorted(fetched, key=lambda b: b.start)
    if not fetched:
        return stored
    return [b for b in stored if b.end <= fetched[0].start] + fetched


def daily_rows(
    bills: list[Bill], tz: tzinfo
) -> list[tuple[datetime, float, float, float, float]]:
    """Spread bills evenly: (local midnight, usage, usage sum, cost, cost sum)."""
    rows = []
    usage_sum = cost_sum = 0.0
    for bill in bills:
        for i in range(bill.days):
            # Cumulative from the bill total, so rounding cannot drift.
            frac = (i + 1) / bill.days
            rows.append(
                (
                    datetime.combine(bill.start + timedelta(days=i), time(), tz),
                    bill.usage / bill.days,
                    usage_sum + bill.usage * frac,
                    bill.cost / bill.days,
                    cost_sum + bill.cost * frac,
                )
            )
        usage_sum += bill.usage
        cost_sum += bill.cost
    return rows
