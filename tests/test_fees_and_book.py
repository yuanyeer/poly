from __future__ import annotations

from decimal import Decimal

from polybot.market.book import available_ask_size, walk_asks
from polybot.market.fees import fee_amount, fee_per_share
from polybot.types import FeeSchedule
from tests.conftest import binary_market, level, outcome


def test_taker_fee_formula():
    schedule = FeeSchedule(rate=Decimal("0.02"), exponent=Decimal("2"), taker_only=True)
    # fee = size * r * p * (1-p) = 10 * 0.02 * 0.4 * 0.6 = 0.048
    assert fee_amount(Decimal("10"), Decimal("0.4"), schedule, "taker") == Decimal("0.048")
    assert fee_per_share(Decimal("0.4"), schedule, "taker") == Decimal("0.0048")


def test_maker_fee_zero_when_fd_to():
    schedule = FeeSchedule(rate=Decimal("0.02"), exponent=Decimal("2"), taker_only=True)
    assert fee_amount(Decimal("10"), Decimal("0.4"), schedule, "maker") == Decimal("0")


def test_maker_pays_when_not_taker_only():
    schedule = FeeSchedule(rate=Decimal("0.02"), exponent=Decimal("2"), taker_only=False)
    assert fee_amount(Decimal("10"), Decimal("0.4"), schedule, "maker") == Decimal("0.048")


def test_walk_asks_uses_multiple_levels():
    market = binary_market(
        yes_asks=[level("0.40", "5"), level("0.50", "10")],
        no_asks=[level("0.40", "100")],
    )
    yes = market.outcomes[0]
    fill = walk_asks(yes, Decimal("12"))
    assert fill.fillable
    assert fill.levels_used == 2
    assert fill.cost == Decimal("5") * Decimal("0.40") + Decimal("7") * Decimal("0.50")
    assert fill.vwap == fill.cost / Decimal("12")


def test_walk_asks_does_not_fill_beyond_depth():
    book = outcome("t", "Yes", [level("0.40", "3")])
    fill = walk_asks(book, Decimal("10"))
    assert fill.exhausted
    assert not fill.fillable
    assert fill.size == Decimal("3")
    assert available_ask_size(book) == Decimal("3")
