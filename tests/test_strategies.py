from __future__ import annotations

from decimal import Decimal

from polybot.strategy.complete_set import CompleteSetStrategy
from polybot.strategy.maker_spread import MakerSpreadStrategy
from polybot.strategy.yes_no_lock import YesNoLockStrategy
from polybot.types import FeeSchedule, MarketSnapshot
from tests.conftest import binary_market, level, outcome, paper_config


def test_yes_no_lock_detects_clear_taker_edge(cfg):
    # VWAP 0.40 + 0.40 = 0.80; fee/share each = 0.02*0.4*0.6=0.0048; edge=1-0.80-0.0096=0.1904
    market = binary_market(
        yes_asks=[level("0.40", "50"), level("0.41", "50")],
        no_asks=[level("0.40", "50"), level("0.42", "50")],
    )
    opps = YesNoLockStrategy().scan(market, cfg)
    assert len(opps) == 1
    assert opps[0].strategy == "yes_no_lock"
    assert opps[0].edge >= Decimal("0.005")
    assert opps[0].legs[0].levels_used >= 1
    assert opps[0].expected_payout == opps[0].size


def test_yes_no_lock_uses_shallow_size_when_deep_book_kills_edge(cfg):
    # Top 5 shares lock; the rest of the book is untradeable for a complete set.
    market = binary_market(
        yes_asks=[level("0.40", "5"), level("0.90", "200")],
        no_asks=[level("0.40", "5"), level("0.90", "200")],
    )
    opps = YesNoLockStrategy().scan(market, cfg)
    assert len(opps) == 1
    assert opps[0].size < Decimal("10")
    assert opps[0].edge >= Decimal("0.005")


def test_yes_no_lock_skips_when_sum_near_one(cfg):
    market = binary_market(
        yes_asks=[level("0.51", "20")],
        no_asks=[level("0.51", "20")],
    )
    assert YesNoLockStrategy().scan(market, cfg) == []


def test_complete_set_three_outcomes(cfg):
    fee = FeeSchedule(rate=Decimal("0.02"), exponent=Decimal("2"), taker_only=True)
    market = MarketSnapshot(
        condition_id="0xmulti",
        question="Who wins?",
        fee=fee,
        outcomes=(
            outcome("a", "A", [level("0.20", "30")]),
            outcome("b", "B", [level("0.20", "30")]),
            outcome("c", "C", [level("0.20", "30")]),
        ),
        min_order_size=Decimal("1"),
    )
    opps = CompleteSetStrategy().scan(market, cfg)
    assert len(opps) == 1
    assert opps[0].strategy == "complete_set"
    assert len(opps[0].legs) == 3
    assert opps[0].edge >= Decimal("0.005")


def test_complete_set_ignores_binary(cfg):
    market = binary_market([level("0.30", "10")], [level("0.30", "10")])
    assert CompleteSetStrategy().scan(market, cfg) == []


def test_maker_spread_requires_hedge_and_edge(cfg):
    market = binary_market(
        yes_asks=[level("0.70", "20")],
        no_asks=[level("0.20", "40")],
        yes_bids=[level("0.30", "40")],
        no_bids=[level("0.19", "10")],
    )
    opps = MakerSpreadStrategy().scan(market, cfg)
    assert len(opps) == 1
    roles = {leg.role for leg in opps[0].legs}
    assert "maker" in roles and "taker" in roles
    assert opps[0].edge >= Decimal("0.002")
    assert all(leg.size == opps[0].size for leg in opps[0].legs)


def test_maker_spread_skips_without_clear_edge(cfg):
    market = binary_market(
        yes_asks=[level("0.51", "20")],
        no_asks=[level("0.51", "20")],
        yes_bids=[level("0.49", "20")],
        no_bids=[level("0.49", "20")],
    )
    assert MakerSpreadStrategy().scan(market, cfg) == []
