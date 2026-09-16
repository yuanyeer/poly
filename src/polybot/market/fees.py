from __future__ import annotations

from decimal import Decimal

from polybot.types import FeeSchedule, Role

ZERO = Decimal("0")


def fee_per_share(price: Decimal, schedule: FeeSchedule, role: Role) -> Decimal:
    """Per-share platform fee: r * p * (1-p). Maker is 0 when fd.to is true."""
    if role == "maker" and schedule.taker_only:
        return ZERO
    price = Decimal(price)
    return schedule.rate * price * (Decimal("1") - price)


def fee_amount(size: Decimal, price: Decimal, schedule: FeeSchedule, role: Role) -> Decimal:
    """fee(p) = size * r * p * (1-p) for takers; maker=0 when fd.to."""
    return Decimal(size) * fee_per_share(price, schedule, role)
