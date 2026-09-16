from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from polybot.config import PaperConfig
from polybot.types import BookLevel, FeeSchedule, MarketSnapshot, OutcomeBook


def paper_config(tmp_path: Path | None = None, **overrides: object) -> PaperConfig:
    values = dict(
        mode="paper",
        starting_balance=Decimal("200"),
        target_balance=Decimal("1000"),
        ledger_path=Path("data/paper_ledger.jsonl"),
        clob_host="https://clob.polymarket.com",
        gamma_host="https://gamma-api.polymarket.com",
        chain_id=137,
        max_markets=8,
        poll_interval_seconds=1.0,
        condition_ids=(),
        taker_edge_floor=Decimal("0.005"),
        maker_edge_floor=Decimal("0.002"),
        max_trade_notional_pct=Decimal("0.25"),
        max_same_event_exposure_pct=Decimal("0.40"),
        max_concurrent_open=3,
        max_unhedged_inventory=Decimal("0"),
        assume_taker_only_if_fd_missing=True,
        min_fill_size=Decimal("1"),
    )
    values.update(overrides)
    if tmp_path is not None:
        values["ledger_path"] = tmp_path / "ledger.jsonl"
    return PaperConfig(**values)  # type: ignore[arg-type]


def level(price: str, size: str) -> BookLevel:
    return BookLevel(price=Decimal(price), size=Decimal(size))


def outcome(
    token_id: str,
    name: str,
    asks: list[BookLevel],
    bids: list[BookLevel] | None = None,
) -> OutcomeBook:
    return OutcomeBook(
        token_id=token_id,
        outcome=name,
        bids=tuple(bids or []),
        asks=tuple(asks),
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
    )


def binary_market(
    yes_asks: list[BookLevel],
    no_asks: list[BookLevel],
    rate: str = "0.02",
    taker_only: bool = True,
    yes_bids: list[BookLevel] | None = None,
    no_bids: list[BookLevel] | None = None,
    condition_id: str = "0xevent",
) -> MarketSnapshot:
    return MarketSnapshot(
        condition_id=condition_id,
        question="Will it happen?",
        fee=FeeSchedule(rate=Decimal(rate), exponent=Decimal("2"), taker_only=taker_only),
        outcomes=(
            outcome("tok-yes", "Yes", yes_asks, yes_bids),
            outcome("tok-no", "No", no_asks, no_bids),
        ),
        min_order_size=Decimal("1"),
    )


@pytest.fixture
def cfg(tmp_path: Path) -> PaperConfig:
    return paper_config(tmp_path)
