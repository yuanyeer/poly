from __future__ import annotations

from polybot.config import PaperConfig
from polybot.strategy.base import Strategy, evaluate_taker_lock
from polybot.types import MarketSnapshot, Opportunity


def _is_binary(market: MarketSnapshot) -> bool:
    return len(market.outcomes) == 2


class YesNoLockStrategy(Strategy):
    """Buy YES+NO when executable prices after taker fees sum to less than 1."""

    name = "yes_no_lock"

    def scan(self, market: MarketSnapshot, config: PaperConfig) -> list[Opportunity]:
        if not _is_binary(market):
            return []
        opp, _edge = evaluate_taker_lock(
            market,
            config,
            min_outcomes=2,
            max_outcomes=2,
            strategy="yes_no_lock",
            notes="YES+NO lock: 1 - Σ walk_ask - Σ fee/share",
        )
        return [opp] if opp else []

    def preview_edge(self, market: MarketSnapshot, config: PaperConfig):
        if not _is_binary(market):
            return None
        _opp, edge = evaluate_taker_lock(
            market,
            config,
            min_outcomes=2,
            max_outcomes=2,
            strategy="yes_no_lock",
            notes="",
        )
        return edge
