from __future__ import annotations

from decimal import Decimal

from polybot.config import PaperConfig
from polybot.strategy.base import Strategy, build_taker_legs, depth_cap, taker_edge, walk_taker
from polybot.types import MarketSnapshot, Opportunity


def _is_binary_yes_no(market: MarketSnapshot) -> bool:
    if len(market.outcomes) != 2:
        return False
    labels = {outcome.outcome.strip().lower() for outcome in market.outcomes}
    return labels == {"yes", "no"} or len(labels) == 2


class YesNoLockStrategy(Strategy):
    """Buy YES+NO when executable prices after taker fees sum to less than 1."""

    name = "yes_no_lock"

    def scan(self, market: MarketSnapshot, config: PaperConfig) -> list[Opportunity]:
        if not _is_binary_yes_no(market):
            return []
        cap = depth_cap(market)
        size = cap
        min_size = max(config.min_fill_size, market.min_order_size)
        if size < min_size:
            return []
        walks = []
        fees = []
        for outcome in market.outcomes:
            walk, fee = walk_taker(outcome, size, market)
            walks.append(walk)
            fees.append(fee)
        if any(not walk.fillable for walk in walks):
            return []
        edge = taker_edge(walks, fees)
        if edge < config.taker_edge_floor:
            return []
        notional = sum((walk.cost + fee for walk, fee in zip(walks, fees)), Decimal("0"))
        return [
            Opportunity(
                strategy="yes_no_lock",
                event_id=market.condition_id,
                question=market.question,
                edge=edge,
                size=size,
                notional=notional,
                expected_payout=size,
                legs=build_taker_legs(market, size, walks, fees),
                notes="YES+NO lock: 1 - Σ walk_ask - Σ fee/share",
            )
        ]
