from __future__ import annotations

from decimal import Decimal

from polybot.ledger.store import PaperLedger
from polybot.runner.paper import PaperRunner
from datetime import datetime, timezone

from polybot.runner.summary import SessionStats, build_daily_snapshot, format_daily, format_summary
from polybot.types import LedgerFill, LedgerState, Leg
from tests.conftest import binary_market, level, paper_config


def test_summary_reports_pnl_and_win_rate():
    cfg = paper_config()
    fill = LedgerFill(
        fill_id="f1",
        ts="2026-09-16T00:00:00+00:00",
        opportunity_id="x",
        event_id="0xe",
        strategy="yes_no_lock",
        question="q",
        size=Decimal("10"),
        edge=Decimal("0.02"),
        cash_debit=Decimal("8"),
        cash_credit=Decimal("0"),
        expected_payout=Decimal("10"),
        legs=(
            Leg("a", "Yes", "BUY", "taker", Decimal("10"), Decimal("0.4"), Decimal("0"), Decimal("4"), 1),
            Leg("b", "No", "BUY", "taker", Decimal("10"), Decimal("0.4"), Decimal("0"), Decimal("4"), 1),
        ),
    )
    state = LedgerState(
        starting_balance=Decimal("200"),
        cash=Decimal("192"),
        locked_payout=Decimal("10"),
        open_count=1,
        event_exposure={"0xe": Decimal("8")},
        fills=[fill],
    )
    stats = SessionStats(cycles=3, scanned=30, candidates=2, booked=1, rejected_edges=28, rejected_risk=1)
    line = format_summary("SUMMARY", cfg, state, stats)
    assert "pnl=+2.0000" in line
    assert "win_rate=100.0%" in line
    assert "exposure=8.0000" in line
    assert "open=1/3" in line


def test_daily_snapshot_uses_utc_day_window_only():
    cfg = paper_config()
    today = LedgerFill(
        fill_id="today",
        ts="2026-09-16T12:00:00+00:00",
        opportunity_id="t",
        event_id="0xe",
        strategy="yes_no_lock",
        question="q",
        size=Decimal("10"),
        edge=Decimal("0.02"),
        cash_debit=Decimal("8"),
        cash_credit=Decimal("0"),
        expected_payout=Decimal("10"),
        legs=(),
    )
    yesterday = LedgerFill(
        fill_id="yday",
        ts="2026-09-15T23:59:00+00:00",
        opportunity_id="y",
        event_id="0xe",
        strategy="yes_no_lock",
        question="q",
        size=Decimal("5"),
        edge=Decimal("0.02"),
        cash_debit=Decimal("4"),
        cash_credit=Decimal("0"),
        expected_payout=Decimal("5"),
        legs=(),
    )
    state = LedgerState(
        starting_balance=Decimal("200"),
        cash=Decimal("188"),
        locked_payout=Decimal("15"),
        open_count=2,
        event_exposure={"0xe": Decimal("12")},
        fills=[yesterday, today],
    )
    snap = build_daily_snapshot(state, datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc))
    assert snap.date == "2026-09-16"
    assert snap.fills == 1
    assert snap.locked_edge == Decimal("2")
    assert snap.booked_notional == Decimal("8")
    assert snap.win_rate == Decimal("100")
    line = format_daily(snap, cfg)
    assert line.startswith("DAILY 2026-09-16")
    assert "fills=1" in line
    assert "win_rate=100.0%" in line
    assert "exposure=12.0000" in line
    assert "below_floor_n=0" in line
    assert "median_net_edge=n/a" in line


def test_daily_line_includes_below_floor_and_median():
    cfg = paper_config()
    state = LedgerState(
        starting_balance=Decimal("200"),
        cash=Decimal("200"),
        locked_payout=Decimal("0"),
        open_count=0,
    )
    snap = build_daily_snapshot(
        state,
        datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc),
        below_floor_n=7,
        median_net_edge=Decimal("-0.0140"),
    )
    line = format_daily(snap, cfg)
    assert "below_floor_n=7" in line
    assert "median_net_edge=-0.0140" in line


class _StubMarket:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot
        self.cycles = 0

    def list_condition_ids(self):
        self.cycles += 1
        return [self._snapshot.condition_id]

    def snapshot(self, condition_id: str):
        return self._snapshot if condition_id == self._snapshot.condition_id else None


def test_loop_runs_multiple_cycles(tmp_path):
    cfg = paper_config(tmp_path, poll_interval_seconds=0.0)
    market = binary_market(
        yes_asks=[level("0.52", "10")],
        no_asks=[level("0.52", "10")],
    )
    stub = _StubMarket(market)
    runner = PaperRunner(cfg, ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance), market=stub)  # type: ignore[arg-type]
    report = runner.run_forever(max_loops=2, once=False)
    assert stub.cycles == 2
    assert runner.stats.cycles == 2
    assert report.booked == 0
    assert report.summary.startswith("SUMMARY")
    assert report.daily_summary.startswith("DAILY ")
    assert "cash=" in report.daily_summary
    assert "win_rate=" in report.daily_summary
    assert "exposure=" in report.daily_summary
    assert "below_floor_n=" in report.daily_summary
    assert "median_net_edge=" in report.daily_summary
    assert report.rejected_edges >= 1


def test_daily_counts_below_floor_net_edges(tmp_path):
    cfg = paper_config(tmp_path)
    market = binary_market(
        yes_asks=[level("0.52", "10")],
        no_asks=[level("0.52", "10")],
    )
    stub = _StubMarket(market)
    runner = PaperRunner(cfg, ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance), market=stub)  # type: ignore[arg-type]
    report = runner.run_cycle()
    assert report.booked == 0
    assert "below_floor_n=1" in report.daily_summary
    assert "median_net_edge=n/a" not in report.daily_summary
    assert runner.stats.below_floor_n == 1
    assert runner.stats.median_net_edge is not None
    assert runner.stats.median_net_edge < cfg.taker_edge_floor
