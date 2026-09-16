from __future__ import annotations

from decimal import Decimal

from polybot.config import PaperConfig
from polybot.strategy.base import Strategy, build_taker_legs, depth_cap, taker_edge, walk_taker
from polybot.types import MarketSnapshot, Opportunity


class CompleteSetStrategy(Strategy):
    """Buy every outcome on a multi-outcome market when total cost after fees < 1."""

    name = "complete_set"

    def scan(self, market: MarketSnapshot, config: PaperConfig) -> list[Opportunity]:
        if len(market.outcomes) < 3:
            return []
        size = depth_cap(market)
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
                strategy="complete_set",
                event_id=market.condition_id,
                question=market.question,
                edge=edge,
                size=size,
                notional=notional,
                expected_payout=size,
                legs=build_taker_legs(market, size, walks, fees),
                notes="complete-set lock: buy all outcomes, 1 - Σ walk_ask - Σ fee/share",
            )
        ]
