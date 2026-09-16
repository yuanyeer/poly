from __future__ import annotations

from polybot.config import PaperConfig
from polybot.strategy.base import Strategy, evaluate_taker_lock
from polybot.types import MarketSnapshot, Opportunity


class CompleteSetStrategy(Strategy):
    """Buy every outcome on a multi-outcome market when total cost after fees < 1."""

    name = "complete_set"

    def scan(self, market: MarketSnapshot, config: PaperConfig) -> list[Opportunity]:
        if len(market.outcomes) < 3:
            return []
        opp, _edge = evaluate_taker_lock(
            market,
            config,
            min_outcomes=3,
            max_outcomes=None,
            strategy="complete_set",
            notes="complete-set lock: buy all outcomes, 1 - Σ walk_ask - Σ fee/share",
        )
        return [opp] if opp else []

    def preview_edge(self, market: MarketSnapshot, config: PaperConfig):
        if len(market.outcomes) < 3:
            return None
        _opp, edge = evaluate_taker_lock(
            market,
            config,
            min_outcomes=3,
            max_outcomes=None,
            strategy="complete_set",
            notes="",
        )
        return edge
