from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Role = Literal["taker", "maker"]
Side = Literal["BUY", "SELL"]
StrategyName = Literal["yes_no_lock", "complete_set", "maker_spread"]


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class WalkFill:
    """Result of walking a book for an exact size (never top-of-book only)."""

    size: Decimal
    cost: Decimal
    vwap: Decimal
    fee: Decimal
    levels_used: int
    exhausted: bool
    residual_size: Decimal

    @property
    def fillable(self) -> bool:
        return not self.exhausted and self.size > 0


@dataclass(frozen=True)
class OutcomeBook:
    token_id: str
    outcome: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    tick_size: Decimal
    min_order_size: Decimal
    fee: FeeSchedule | None = None
    condition_id: str = ""


@dataclass(frozen=True)
class FeeSchedule:
    """CLOB fee curve from getClobMarketInfo().fd."""

    rate: Decimal
    exponent: Decimal
    taker_only: bool


@dataclass(frozen=True)
class MarketSnapshot:
    condition_id: str
    question: str
    fee: FeeSchedule
    outcomes: tuple[OutcomeBook, ...]
    min_order_size: Decimal
    kind: str = "binary"


@dataclass(frozen=True)
class ScanTarget:
    """A binary condition or a multi-market complete-set bundle."""

    kind: Literal["binary", "complete_set"]
    event_id: str
    question: str
    condition_ids: tuple[str, ...]
    token_ids: tuple[str, ...] = ()
    raw_edge: Decimal | None = None


@dataclass(frozen=True)
class Leg:
    token_id: str
    outcome: str
    side: Side
    role: Role
    size: Decimal
    price: Decimal
    fee: Decimal
    notional: Decimal
    levels_used: int


@dataclass(frozen=True)
class Opportunity:
    strategy: StrategyName
    event_id: str
    question: str
    edge: Decimal
    size: Decimal
    notional: Decimal
    expected_payout: Decimal
    legs: tuple[Leg, ...]
    notes: str = ""

    @property
    def opportunity_id(self) -> str:
        tokens = ",".join(sorted(leg.token_id for leg in self.legs))
        return f"{self.strategy}:{self.event_id}:{tokens}"


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    capped_size: Decimal | None = None


@dataclass(frozen=True)
class LedgerFill:
    fill_id: str
    ts: str
    opportunity_id: str
    event_id: str
    strategy: str
    question: str
    size: Decimal
    edge: Decimal
    cash_debit: Decimal
    cash_credit: Decimal
    expected_payout: Decimal
    legs: tuple[Leg, ...]
    notes: str = ""
    prev_hash: str = ""
    hash: str = ""


@dataclass
class LedgerState:
    starting_balance: Decimal
    cash: Decimal
    locked_payout: Decimal
    open_count: int
    event_exposure: dict[str, Decimal] = field(default_factory=dict)
    fills: list[LedgerFill] = field(default_factory=list)

    @property
    def equity(self) -> Decimal:
        return self.cash + self.locked_payout

    @property
    def open_exposure(self) -> Decimal:
        return sum(self.event_exposure.values(), Decimal("0"))
