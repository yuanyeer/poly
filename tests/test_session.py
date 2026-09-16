from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polybot.ledger.store import PaperLedger
from polybot.runner.paper import PaperRunner, SessionWatch
from polybot.session import in_trading_window, local_now
from tests.conftest import binary_market, level, paper_config


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_ny_window_respects_edt_in_summer():
    # 2026-07-15 13:00 UTC = 09:00 EDT
    assert in_trading_window("America/New_York", "09:00", "22:00", _utc(2026, 7, 15, 13, 0))
    assert not in_trading_window("America/New_York", "09:00", "22:00", _utc(2026, 7, 15, 12, 59))
    # 02:00 UTC = 22:00 EDT → [start, end) so closed
    assert not in_trading_window("America/New_York", "09:00", "22:00", _utc(2026, 7, 16, 2, 0))
    assert in_trading_window("America/New_York", "09:00", "22:00", _utc(2026, 7, 16, 1, 59))


def test_ny_window_respects_est_in_winter():
    # 2026-01-15 14:00 UTC = 09:00 EST
    assert in_trading_window("America/New_York", "09:00", "22:00", _utc(2026, 1, 15, 14, 0))
    assert not in_trading_window("America/New_York", "09:00", "22:00", _utc(2026, 1, 15, 13, 59))
    # 03:00 UTC = 22:00 EST → closed
    assert not in_trading_window("America/New_York", "09:00", "22:00", _utc(2026, 1, 16, 3, 0))


def test_disabled_session_is_always_open():
    assert in_trading_window(
        "America/New_York",
        "09:00",
        "22:00",
        _utc(2026, 7, 15, 3, 0),
        enabled=False,
    )


def test_local_now_uses_dst_offset():
    edt = local_now("America/New_York", _utc(2026, 7, 15, 13, 0))
    est = local_now("America/New_York", _utc(2026, 1, 15, 14, 0))
    assert edt.hour == 9
    assert edt.utcoffset().total_seconds() == -4 * 3600
    assert est.hour == 9
    assert est.utcoffset().total_seconds() == -5 * 3600


class _StubMarket:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot
        self.list_calls = 0

    def list_condition_ids(self):
        self.list_calls += 1
        return [self._snapshot.condition_id]

    def snapshot(self, condition_id: str):
        return self._snapshot if condition_id == self._snapshot.condition_id else None


def test_runner_stops_scanning_outside_ny_window(tmp_path):
    cfg = paper_config(
        tmp_path,
        session_enabled=True,
        session_timezone="America/New_York",
        session_start="09:00",
        session_end="22:00",
    )
    market = binary_market(yes_asks=[level("0.30", "20")], no_asks=[level("0.30", "20")])
    stub = _StubMarket(market)
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
        now_fn=lambda: _utc(2026, 7, 15, 3, 0),  # 23:00 EDT
    )
    report = runner.run_cycle()
    assert stub.list_calls == 0
    assert report.booked == 0
    assert report.scanned == 0
    assert report.skipped_reason == "session_closed"
    assert report.in_session is False
    assert runner.watch.zero_book_cycles == 0
    assert "below_floor_n=" in report.daily_summary
    assert "median_net_edge=" in report.daily_summary


def test_zero_book_streak_ignores_off_hours(tmp_path):
    cfg = paper_config(
        tmp_path,
        session_enabled=True,
        session_timezone="America/New_York",
        session_start="09:00",
        session_end="22:00",
        poll_interval_seconds=0.0,
    )
    market = binary_market(yes_asks=[level("0.52", "20")], no_asks=[level("0.52", "20")])
    stub = _StubMarket(market)
    clock = {"now": _utc(2026, 7, 15, 14, 0)}  # 10:00 EDT, in window

    def now_fn() -> datetime:
        return clock["now"]

    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
        now_fn=now_fn,
    )
    inside = runner.run_cycle()
    assert inside.booked == 0
    assert runner.watch.zero_book_cycles == 1
    clock["now"] = _utc(2026, 7, 16, 3, 0)  # 23:00 EDT, closed
    outside = runner.run_cycle()
    assert outside.skipped_reason == "session_closed"
    assert runner.watch.zero_book_cycles == 1
    assert stub.list_calls == 1


def test_idle_zero_fill_trigger_after_two_sessions(tmp_path):
    cfg = paper_config(
        tmp_path,
        session_enabled=True,
        session_timezone="America/New_York",
        session_start="09:00",
        session_end="22:00",
        idle_zero_fill_sessions=2,
    )
    market = binary_market(yes_asks=[level("0.52", "20")], no_asks=[level("0.52", "20")])
    stub = _StubMarket(market)
    clock = {"now": _utc(2026, 7, 15, 14, 0)}

    def now_fn() -> datetime:
        return clock["now"]

    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
        now_fn=now_fn,
    )
    runner.run_cycle()
    clock["now"] = _utc(2026, 7, 16, 3, 0)
    first_close = runner.run_cycle()
    assert runner.watch.zero_fill_sessions == 1
    assert all("TRIGGER idle_zero_fill" not in line for line in first_close.messages)
    clock["now"] = _utc(2026, 7, 16, 14, 0)
    runner.run_cycle()
    clock["now"] = _utc(2026, 7, 17, 3, 0)
    second_close = runner.run_cycle()
    assert runner.watch.zero_fill_sessions == 2
    assert any("TRIGGER idle_zero_fill" in line for line in second_close.messages)


def test_drawdown_halt_uses_live_peak(tmp_path):
    cfg = paper_config(
        tmp_path,
        session_enabled=False,
        drawdown_halt_pct=Decimal("0.25"),
    )
    market = binary_market(yes_asks=[level("0.30", "20")], no_asks=[level("0.30", "20")])
    stub = _StubMarket(market)
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
    )
    runner.watch.peak_equity = Decimal("400")
    report = runner.run_cycle()
    assert report.skipped_reason == "drawdown_halt"
    assert stub.list_calls == 0
    assert report.peak_equity == Decimal("400")
    assert report.drawdown >= Decimal("0.25")


def test_session_watch_off_hours_do_not_count():
    watch = SessionWatch()
    watch.note_in_window(booked=0, did_scan=True)
    assert watch.zero_book_cycles == 1
    watch.note_off_window(idle_sessions=2)
    watch.note_off_window(idle_sessions=2)
    assert watch.zero_book_cycles == 1
    assert watch.zero_fill_sessions == 1
