from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_DOWN

from polybot.config import PaperConfig
from polybot.market.book import available_ask_size, best_ask, walk_asks
from polybot.market.fees import fee_amount, fee_per_share
from polybot.types import FeeSchedule, Leg, MarketSnapshot, Opportunity, Role, StrategyName, WalkFill

ZERO = Decimal("0")


class Strategy(ABC):
    name = "base"

    @abstractmethod
    def scan(self, market: MarketSnapshot, config: PaperConfig) -> list[Opportunity]:
        """Return 0+ complete-set (or maker-hedged) opportunities for one event."""


def fee_schedule(market: MarketSnapshot, book) -> FeeSchedule:
    return getattr(book, "fee", None) or market.fee


def walk_taker(book, size: Decimal, market: MarketSnapshot) -> tuple[WalkFill, Decimal]:
    fill = walk_asks(book, size)
    sched = fee_schedule(market, book)
    fee = fee_amount(fill.size, fill.vwap, sched, "taker") if fill.size > 0 else ZERO
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


def top_ask_size(market: MarketSnapshot) -> Decimal:
    sizes = []
    for outcome in market.outcomes:
        top = best_ask(outcome)
        if top is None:
            return ZERO
        sizes.append(top.size)
    return min(sizes) if sizes else ZERO


def probe_sizes(min_size: Decimal, cap: Decimal, steps: int, extra: Decimal | None = None) -> list[Decimal]:
    """Ascending size probes. Always includes min_size, optional first-level size, and cap."""
    if cap < min_size:
        return []
    found: set[Decimal] = {min_size.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)}
    if extra is not None and min_size <= extra <= cap:
        found.add(extra.quantize(Decimal("0.0001"), rounding=ROUND_DOWN))
    if steps > 2:
        span = cap - min_size
        for i in range(1, steps - 1):
            raw = min_size + span * Decimal(i) / Decimal(steps - 1)
            found.add(raw.quantize(Decimal("0.0001"), rounding=ROUND_DOWN))
    found.add(cap.quantize(Decimal("0.0001"), rounding=ROUND_DOWN))
    return sorted(size for size in found if size >= min_size)


def evaluate_taker_lock(
    market: MarketSnapshot,
    config: PaperConfig,
    *,
    min_outcomes: int,
    max_outcomes: int | None,
    strategy: StrategyName,
    notes: str,
) -> tuple[Opportunity | None, Decimal]:
    """Walk several sizes and keep the largest that still clears the taker floor."""
    count = len(market.outcomes)
    if count < min_outcomes or (max_outcomes is not None and count > max_outcomes):
        return None, Decimal("-1")
    cap = depth_cap(market)
    min_size = max(config.min_fill_size, market.min_order_size)
    if cap < min_size:
        return None, Decimal("-1")
    best_edge = Decimal("-1")
    chosen: Opportunity | None = None
    for size in probe_sizes(min_size, cap, config.size_probe_steps, extra=top_ask_size(market)):
        walks: list[WalkFill] = []
        fees: list[Decimal] = []
        fillable = True
        for outcome in market.outcomes:
            walk, fee = walk_taker(outcome, size, market)
            if not walk.fillable:
                fillable = False
                break
            walks.append(walk)
            fees.append(fee)
        if not fillable:
            continue
        edge = taker_edge(walks, fees)
        if edge > best_edge:
            best_edge = edge
        if edge < config.taker_edge_floor:
            continue
        notional = sum((walk.cost + fee for walk, fee in zip(walks, fees)), ZERO)
        chosen = Opportunity(
            strategy=strategy,
            event_id=market.condition_id,
            question=market.question,
            edge=edge,
            size=size,
            notional=notional,
            expected_payout=size,
            legs=build_taker_legs(market, size, walks, fees),
            notes=notes,
        )
    return chosen, best_edge
