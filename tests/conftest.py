from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from datetime import datetime, timezone

from polybot.config import PaperConfig, WhiskasConfig
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
        # Unit tests pin the clock themselves; disable the live NY gate by default.
        session_enabled=False,
        # Production freeze is 900/750; unit fixtures keep 180/150 so start=200 still scans.
        drawdown_review_floor_usd=Decimal("180"),
        drawdown_halt_floor_usd=Decimal("150"),
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


def whiskas_cfg(**overrides: object) -> WhiskasConfig:
    values = dict(
        enabled=True,
        account_id="whiskas-inv",
        starting_balance=Decimal("2300"),
        target_balance=None,
        clip_size=Decimal("50"),
        enter_after_open_seconds=6.0,
        stop_remaining_seconds=100.0,
        max_buy_price=Decimal("0.89"),
        combo_sum_cap=Decimal("1.05"),
        per_round_notional_cap=Decimal("1200"),
        pause_arb_main_booking=True,
        drawdown_review_floor_usd=Decimal("2070"),
        drawdown_halt_floor_usd=Decimal("1725"),
    )
    values.update(overrides)
    return WhiskasConfig(**values)  # type: ignore[arg-type]


def btc_updown_market(
    up_asks: list[BookLevel],
    down_asks: list[BookLevel],
    *,
    rate: str = "0.02",
    taker_only: bool = True,
    condition_id: str = "0xbtc5m",
    round_open: datetime | None = None,
    round_end: datetime | None = None,
    resolved: bool = False,
    winner: str | None = None,
) -> MarketSnapshot:
    opened = round_open or datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    ends = round_end or datetime(2026, 9, 16, 12, 5, tzinfo=timezone.utc)
    return MarketSnapshot(
        condition_id=condition_id,
        question="Bitcoin Up or Down - 8:00AM-8:05AM ET",
        fee=FeeSchedule(rate=Decimal(rate), exponent=Decimal("2"), taker_only=taker_only),
        outcomes=(
            outcome("tok-up", "Up", up_asks),
            outcome("tok-down", "Down", down_asks),
        ),
        min_order_size=Decimal("1"),
        kind="binary",
        slug="btc-updown-5m-test",
        round_open=opened,
        round_end=ends,
        resolved=resolved,
        winner=winner,
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
