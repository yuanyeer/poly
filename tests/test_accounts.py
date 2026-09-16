from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from polybot.config import CopyConfig, CopyLeaderConfig, load_config
from polybot.copy.executor import MirrorExecutor
from polybot.copy.metrics import InMemoryMetricsProvider, LeaderMetrics
from polybot.copy.monitor import EVENT_STOP_FOLLOW, CopyMonitor
from polybot.copy.watchlist import load_watchlist
from polybot.ledger.accounts import ARB_MAIN_ID, copy_account_id, open_account_book
from polybot.ledger.store import PaperLedger
from polybot.runner.paper import PaperRunner
from polybot.runner.summary import DailySnapshot, format_daily, format_rank_lines, format_summary
from polybot.types import LedgerState, Leg, Opportunity
from tests.conftest import paper_config


def _opp(event: str = "0xevent", notional: str = "10", payout: str = "12", note: str = "a") -> Opportunity:
    size = Decimal("12")
    legs = (
        Leg("tok-yes", "Yes", "BUY", "taker", size, Decimal("0.40"), Decimal("0.1"), Decimal("5"), 2),
        Leg("tok-no", "No", "BUY", "taker", size, Decimal("0.40"), Decimal("0.1"), Decimal("5"), 2),
    )
    return Opportunity(
        strategy="yes_no_lock",
        event_id=event,
        question="q",
        edge=Decimal("0.02"),
        size=size,
        notional=Decimal(notional),
        expected_payout=Decimal(payout),
        legs=legs,
        notes=note,
    )


def _leaders() -> tuple[CopyLeaderConfig, ...]:
    return (
        CopyLeaderConfig("x-MoneyForWhiskas", "x-MoneyForWhiskas", "BTC_5m", 1, True),
        CopyLeaderConfig("0xcd30457c79", "0xcd30457c79", "BTC_5m", 2, False),
        CopyLeaderConfig("goldfisherrr", "goldfisherrr", "BTC_15m", 3, False),
    )


def test_default_config_opens_only_arb_main(tmp_path: Path):
    cfg = load_config("config/paper.yaml")
    assert cfg.copy is not None
    assert cfg.copy.enabled is False
    cfg = cfg.__class__(**{**cfg.__dict__, "ledger_path": tmp_path / "arb-main.jsonl"})
    book = open_account_book(cfg)
    ids = [account.account_id for account in book.accounts]
    assert ids == [ARB_MAIN_ID]
    assert book.copy_accounts() == []
    assert book.copy_for("x-MoneyForWhiskas") is None
    assert book.arb().state().cash == Decimal("1000")
    book.arb().ledger.append_fill(_opp())
    assert book.arb().state().cash == Decimal("990")


def test_disabled_copy_skips_runtime_modules(tmp_path: Path):
    cfg = load_config("config/paper.yaml")
    cfg = cfg.__class__(
        **{**cfg.__dict__, "ledger_path": tmp_path / "arb-main.jsonl", "session_enabled": False}
    )

    class _EmptyMarket:
        def list_condition_ids(self):
            return []

        def snapshot(self, condition_id: str):
            return None

    runner = PaperRunner(cfg, market=_EmptyMarket())  # type: ignore[arg-type]
    assert runner.copy_watchlist is None
    assert runner.copy_monitor is None
    assert [account.account_id for account in runner.book.accounts] == [ARB_MAIN_ID]
    report = runner.run_cycle()
    assert report.copy_events == ()
    assert all("copy-" not in line for line in report.messages)


def test_copy_ledgers_do_not_share_risk_rooms(tmp_path: Path):
    cfg = paper_config(
        tmp_path,
        copy=CopyConfig(enabled=True, leaders=_leaders()),
        starting_balance=Decimal("1000"),
        target_balance=Decimal("2000"),
    )
    book = open_account_book(cfg)
    a = book.copy_for("x-MoneyForWhiskas")
    b = book.copy_for("goldfisherrr")
    assert a is not None and b is not None
    a.ledger.append_fill(_opp(event="0xbtc", notional="40", note="a"))
    exe = MirrorExecutor(cfg, copy=cfg.copy)
    # 25% of 1000 = 250; 40 used on A does not consume B's 25% room
    from polybot.copy.executor import MirrorIntent

    intent = MirrorIntent(
        leader_id="goldfisherrr",
        event_id="0xbtc",
        notional=Decimal("40"),
        size=Decimal("40"),
        delay_seconds=Decimal("1"),
        depth_walked=True,
        fees_applied=True,
        leader_px=Decimal("0.50"),
        fill_px=Decimal("0.50"),
        fee_per_share=Decimal("0.001"),
    )
    assert exe.evaluate(intent, b.state(), sleeve_used=Decimal("0")).allowed
    # sleeve 30% of B equity 1000 = 300; A usage is irrelevant
    blocked = exe.evaluate(intent, a.state(), sleeve_used=Decimal("280"))
    assert not blocked.allowed
    assert "sleeve" in blocked.reason
    still_ok = exe.evaluate(intent, b.state(), sleeve_used=Decimal("0"))
    assert still_ok.allowed


def test_stop_follow_pauses_only_that_copy_ledger(tmp_path: Path):
    cfg = paper_config(
        tmp_path,
        copy=CopyConfig(
            enabled=True,
            leaders=_leaders(),
            metrics_stub=None,
        ),
        starting_balance=Decimal("1000"),
        target_balance=Decimal("2000"),
        session_enabled=False,
    )
    provider = InMemoryMetricsProvider(
        {
            "x-MoneyForWhiskas": LeaderMetrics(
                "x-MoneyForWhiskas",
                Decimal("0.09"),
                Decimal("0.01"),
                Decimal("3"),
            )
        }
    )
    class _EmptyMarket:
        def list_condition_ids(self):
            return []

        def snapshot(self, condition_id: str):
            return None

    runner = PaperRunner(cfg, market=_EmptyMarket())  # type: ignore[arg-type]
    assert runner.copy_monitor is not None
    runner.copy_monitor.provider = provider
    report = runner.run_cycle()
    whisk = runner.book.copy_for("x-MoneyForWhiskas")
    gold = runner.book.copy_for("goldfisherrr")
    assert whisk is not None and gold is not None
    assert whisk.paused is True
    assert gold.paused is False
    assert runner.book.arb().paused is False
    assert EVENT_STOP_FOLLOW in report.copy_events
    assert any("PAUSE account=copy-x-MoneyForWhiskas" in line for line in report.messages)
    assert any("RANK 1" in line for line in report.messages)
    assert any("distance_to_2000=" in line for line in report.messages)


def test_hard_floor_pauses_only_that_copy_ledger(tmp_path: Path):
    cfg = paper_config(
        tmp_path,
        copy=CopyConfig(enabled=True, leaders=_leaders()),
        starting_balance=Decimal("1000"),
        target_balance=Decimal("2000"),
        drawdown_review_floor_usd=Decimal("900"),
        drawdown_halt_floor_usd=Decimal("750"),
        session_enabled=False,
    )
    class _EmptyMarket:
        def list_condition_ids(self):
            return []

        def snapshot(self, condition_id: str):
            return None

    runner = PaperRunner(cfg, market=_EmptyMarket())  # type: ignore[arg-type]
    whisk = runner.book.copy_for("x-MoneyForWhiskas")
    gold = runner.book.copy_for("goldfisherrr")
    assert whisk is not None and gold is not None
    # Drain only the primary copy ledger below HARD 750 (equity = cash + locked).
    whisk.ledger.append_fill(_opp(event="0xdrain", notional="300", payout="0", note="drain"))
    assert whisk.state().equity == Decimal("700")
    report = runner.run_cycle()
    assert whisk.paused is True
    assert gold.paused is False
    assert runner.book.arb().paused is False
    assert runner.book.arb().state().equity == Decimal("1000")
    assert gold.state().equity == Decimal("1000")
    assert any("account=copy-x-MoneyForWhiskas" in line and "hard stop" in line for line in report.messages)


def test_summary_and_daily_include_distance_to_2000_and_rank():
    cfg = paper_config(target_balance=Decimal("2000"), starting_balance=Decimal("1000"))
    state = LedgerState(
        starting_balance=Decimal("1000"),
        cash=Decimal("1000"),
        locked_payout=Decimal("0"),
        open_count=0,
    )
    from polybot.runner.summary import SessionStats

    stats = SessionStats()
    summary = format_summary("SUMMARY", cfg, state, stats, account_id="arb-main")
    assert "account=arb-main" in summary
    assert "distance_to_2000=1000.0000" in summary
    assert "below_floor_n=0" in summary
    snap = DailySnapshot(
        date="2026-09-16",
        fills=0,
        win_rate=None,
        booked_notional=Decimal("0"),
        locked_edge=Decimal("0"),
        cash=Decimal("1000"),
        equity=Decimal("1000"),
        pnl=Decimal("0"),
        open_count=0,
        open_exposure=Decimal("0"),
    )
    daily = format_daily(snap, cfg, account_id="arb-main")
    assert "account=arb-main" in daily
    assert "distance_to_2000=1000.0000" in daily
    rich = LedgerState(
        starting_balance=Decimal("1000"),
        cash=Decimal("500"),
        locked_payout=Decimal("1600"),
        open_count=1,
    )
    lines = format_rank_lines(
        [(1, "copy-x-MoneyForWhiskas", rich), (2, ARB_MAIN_ID, state)],
        Decimal("2000"),
    )
    assert lines[0].startswith("RANK 1 account=copy-x-MoneyForWhiskas")
    assert "distance_to_2000=-100.0000" in lines[0] or "WINNER" in "\n".join(lines)
    assert any(line.startswith("WINNER account=copy-x-MoneyForWhiskas") for line in lines)
