from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from polybot.config import PaperConfig
from polybot.market.book import available_ask_size, walk_asks
from polybot.market.fees import fee_amount, fee_per_share
from polybot.types import Leg, MarketSnapshot, Opportunity, Role, WalkFill


class Strategy(ABC):
    name = "base"

    @abstractmethod
    def scan(self, market: MarketSnapshot, config: PaperConfig) -> list[Opportunity]:
        """Return 0+ complete-set (or maker-hedged) opportunities for one event."""


def walk_taker(book, size: Decimal, market: MarketSnapshot) -> tuple[WalkFill, Decimal]:
    fill = walk_asks(book, size)
    fee = fee_amount(fill.size, fill.vwap, market.fee, "taker") if fill.size > 0 else Decimal("0")
    return fill, fee


def taker_edge(walks: list[WalkFill], fees: list[Decimal]) -> Decimal:
    """edge_taker = 1 − Σ walk_ask(size_i) − Σ fee  (per-share VWAP + fee/share)."""
    if not walks or any(w.size <= 0 for w in walks):
        return Decimal("-1")
    size = walks[0].size
    if any(w.size != size for w in walks):
        return Decimal("-1")
    vwap_sum = sum((w.vwap for w in walks), Decimal("0"))
    fee_sum = sum((fee / size for fee in fees), Decimal("0"))
    return Decimal("1") - vwap_sum - fee_sum


def depth_cap(market: MarketSnapshot) -> Decimal:
    if not market.outcomes:
        return Decimal("0")
    return min(available_ask_size(outcome) for outcome in market.outcomes)


def build_taker_legs(
    market: MarketSnapshot,
    size: Decimal,
    walks: list[WalkFill],
    fees: list[Decimal],
    role: Role = "taker",
) -> tuple[Leg, ...]:
    legs: list[Leg] = []
    for outcome, walk, fee in zip(market.outcomes, walks, fees, strict=True):
        legs.append(
            Leg(
                token_id=outcome.token_id,
                outcome=outcome.outcome,
                side="BUY",
                role=role,
                size=size,
                price=walk.vwap,
                fee=fee,
                notional=walk.cost + fee,
                levels_used=walk.levels_used,
            )
        )
    return tuple(legs)


def maker_fee_for(market: MarketSnapshot, price: Decimal, size: Decimal) -> Decimal:
    return fee_amount(size, price, market.fee, "maker")


def maker_fee_share(market: MarketSnapshot, price: Decimal) -> Decimal:
    return fee_per_share(price, market.fee, "maker")
