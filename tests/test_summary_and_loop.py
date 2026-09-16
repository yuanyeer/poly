from __future__ import annotations

from decimal import Decimal

from polybot.ledger.store import PaperLedger
from polybot.runner.paper import PaperRunner
from datetime import datetime, timezone

from polybot.runner.summary import SessionStats, build_daily_snapshot, format_daily, format_summary
from polybot.types import LedgerFill, LedgerState, Leg, ScanTarget, ScreenTape
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
    assert "review=0" in line
    assert "halt=0" in line
    assert "screened_n=0" in line
    assert "median_net_edge_kind=n/a" in line
    assert "best_binary=n/a" in line
    assert "best_set=n/a" in line


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
    assert "screened_n=0" in line
    assert "below_floor_n=0" in line
    assert "median_net_edge=n/a" in line
    assert "median_net_edge_kind=n/a" in line
    assert "best_binary=n/a" in line
    assert "best_set=n/a" in line


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
        screened_n=3059,
        below_floor_n=7,
        median_net_edge=Decimal("-0.0140"),
        median_net_edge_kind="raw",
        best_binary=Decimal("-0.0020"),
        best_set=Decimal("-0.0800"),
    )
    line = format_daily(snap, cfg)
    assert "screened_n=3059" in line
    assert "below_floor_n=7" in line
    assert "median_net_edge=-0.0140" in line
    assert "median_net_edge_kind=raw" in line
    assert "best_binary=-0.0020" in line
    assert "best_set=-0.0800" in line


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
    assert "screened_n=" in report.daily_summary
    assert "median_net_edge_kind=" in report.daily_summary
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
    assert "screened_n=1" in report.summary
    assert "median_net_edge_kind=walked" in report.summary
    assert runner.stats.below_floor_n == 1
    assert runner.stats.screened_n == 1
    assert runner.stats.median_net_edge is not None
    assert runner.stats.median_net_edge < cfg.taker_edge_floor
    assert runner.stats.median_net_edge_kind == "walked"


def test_session_stats_record_screen_diagnostics_without_double_counting_below_floor():
    stats = SessionStats()
    stats.note_screen(
        screened_n=3059,
        below_floor_n=3059,
        best_binary=Decimal("-0.0020"),
        best_set=Decimal("-0.0800"),
        kind="raw",
    )
    stats.record_diagnostic_edges(
        [Decimal("-0.0200"), Decimal("-0.0140"), Decimal("-0.0100")],
        kind="raw",
    )
    assert stats.screened_n == 3059
    assert stats.below_floor_n == 3059
    assert stats.median_net_edge == Decimal("-0.0140")
    assert stats.median_net_edge_kind == "raw"
    assert stats.best_binary == Decimal("-0.0020")
    assert stats.best_set == Decimal("-0.0800")
    stats.record_net_edge(Decimal("-0.50"), Decimal("0.005"), count_below=False)
    assert stats.below_floor_n == 3059
    stats.reset_daily_edges("2026-09-17")
    assert stats.screened_n == 0
    assert stats.below_floor_n == 0
    assert stats.net_edges == []
    assert stats.best_binary is None
    assert stats.best_set is None
    assert stats.median_net_edge_kind is None


class _ScreenMarket:
    """Booking list comes from walk_targets; SCREEN tape is separate."""

    def __init__(self, tape: ScreenTape, snapshots: dict[str, object] | None = None) -> None:
        self.last_screen = tape
        self._snapshots = snapshots or {}
        self.snapshot_ids: list[str] = []

    def list_scan_targets(self):
        return list(self.last_screen.walk_targets)

    def snapshot_target(self, target: ScanTarget):
        self.snapshot_ids.append(target.event_id)
        return self._snapshots.get(target.event_id)

    def snapshot(self, condition_id: str):
        self.snapshot_ids.append(condition_id)
        return self._snapshots.get(condition_id)


def _below_floor_target(event_id: str, raw_edge: str) -> ScanTarget:
    return ScanTarget(
        kind="binary",
        event_id=event_id,
        question=event_id,
        condition_ids=(event_id,),
        token_ids=("y", "n"),
        raw_edge=Decimal(raw_edge),
    )


def test_skip_walk_reports_raw_screen_tape_without_looking_empty(tmp_path):
    cfg = paper_config(tmp_path, diag_walk_limit=12)
    edges = [Decimal("-0.0200") + Decimal(i) * Decimal("0.0001") for i in range(40)]
    below = [_below_floor_target(f"m{i}", str(edge)) for i, edge in enumerate(edges)]
    tape = ScreenTape(
        screened_n=40,
        below_floor_n=40,
        best_binary=max(edges),
        best_set=Decimal("-0.0800"),
        raw_edges=tuple(edges),
        walk_targets=(),
        below_floor_targets=tuple(below),
    )
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=_ScreenMarket(tape),  # type: ignore[arg-type]
    )
    report = runner.run_cycle()
    assert report.booked == 0
    assert report.scanned == 0
    assert report.candidates == 0
    assert runner.stats.screened_n == 40
    assert runner.stats.below_floor_n == 40
    assert runner.stats.median_net_edge_kind == "raw"
    assert runner.stats.median_net_edge is not None
    assert runner.stats.median_net_edge < cfg.taker_edge_floor
    assert runner.stats.best_binary == max(edges)
    assert runner.stats.best_set == Decimal("-0.0800")
    assert "screened_n=40" in report.summary
    assert "below_floor_n=40" in report.summary
    assert "median_net_edge_kind=raw" in report.summary
    assert "median_net_edge=n/a" not in report.summary
    assert "best_binary=" in report.summary
    assert "best_set=-0.0800" in report.summary
    assert "screened_n=40" in report.daily_summary
    assert "median_net_edge_kind=raw" in report.daily_summary


def test_cheap_below_floor_diag_walk_is_walked_kind_and_does_not_book(tmp_path):
    cfg = paper_config(tmp_path, diag_walk_limit=12)
    snap = binary_market(
        yes_asks=[level("0.52", "10")],
        no_asks=[level("0.52", "10")],
        condition_id="below",
    )
    target = _below_floor_target("below", "-0.0400")
    tape = ScreenTape(
        screened_n=1,
        below_floor_n=1,
        best_binary=Decimal("-0.0400"),
        best_set=None,
        raw_edges=(Decimal("-0.0400"),),
        walk_targets=(),
        below_floor_targets=(target,),
    )
    market = _ScreenMarket(tape, snapshots={"below": snap})
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=market,  # type: ignore[arg-type]
    )
    report = runner.run_cycle()
    assert report.booked == 0
    assert report.scanned == 0
    assert report.candidates == 0
    assert market.snapshot_ids == ["below"]
    assert runner.stats.screened_n == 1
    assert runner.stats.below_floor_n == 1
    assert runner.stats.median_net_edge_kind == "walked"
    assert runner.stats.median_net_edge is not None
    assert runner.stats.median_net_edge < cfg.taker_edge_floor
    assert "median_net_edge_kind=walked" in report.summary
    assert ledger_cash_unchanged(runner)


def ledger_cash_unchanged(runner: PaperRunner) -> bool:
    return runner.ledger.state().cash == runner.config.starting_balance


def test_screen_tape_still_books_only_walk_targets(tmp_path):
    cfg = paper_config(tmp_path, diag_walk_limit=12)
    good = binary_market(
        yes_asks=[level("0.30", "20"), level("0.32", "20")],
        no_asks=[level("0.30", "20"), level("0.33", "20")],
        condition_id="cheap",
    )
    walk = ScanTarget(
        kind="binary",
        event_id="cheap",
        question="cheap",
        condition_ids=("cheap",),
        token_ids=("y", "n"),
        raw_edge=Decimal("0.20"),
    )
    below = [_below_floor_target(f"b{i}", "-0.04") for i in range(20)]
    tape = ScreenTape(
        screened_n=21,
        below_floor_n=20,
        best_binary=Decimal("0.20"),
        best_set=None,
        raw_edges=(Decimal("0.20"),) + tuple(Decimal("-0.04") for _ in below),
        walk_targets=(walk,),
        below_floor_targets=tuple(below),
    )
    market = _ScreenMarket(tape, snapshots={"cheap": good})
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=market,  # type: ignore[arg-type]
    )
    report = runner.run_cycle()
    assert report.booked == 1
    assert report.scanned == 1
    assert runner.stats.screened_n == 21
    assert runner.stats.below_floor_n == 20
    assert runner.stats.median_net_edge_kind == "raw"
    assert set(market.snapshot_ids) == {"cheap"}
    assert runner.ledger.state().open_count == 1
