from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polybot.ledger.store import PaperLedger
from polybot.risk.drawdown import classify_drawdown
from polybot.runner.paper import PaperRunner, SessionWatch
from polybot.session import in_trading_window, local_now
from tests.conftest import binary_market, level, paper_config


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_ny_window_respects_edt_in_summer():
    # 2026-07-15 12:00 UTC = 08:00 EDT
    assert in_trading_window("America/New_York", "08:00", "23:00", _utc(2026, 7, 15, 12, 0))
    assert not in_trading_window("America/New_York", "08:00", "23:00", _utc(2026, 7, 15, 11, 59))
    # 03:00 UTC = 23:00 EDT → [start, end) so closed
    assert not in_trading_window("America/New_York", "08:00", "23:00", _utc(2026, 7, 16, 3, 0))
    assert in_trading_window("America/New_York", "08:00", "23:00", _utc(2026, 7, 16, 2, 59))


def test_ny_window_respects_est_in_winter():
    # 2026-01-15 13:00 UTC = 08:00 EST
    assert in_trading_window("America/New_York", "08:00", "23:00", _utc(2026, 1, 15, 13, 0))
    assert not in_trading_window("America/New_York", "08:00", "23:00", _utc(2026, 1, 15, 12, 59))
    # 04:00 UTC = 23:00 EST → closed
    assert not in_trading_window("America/New_York", "08:00", "23:00", _utc(2026, 1, 16, 4, 0))


def test_yaml_timezone_asia_shanghai_is_honored_when_configured():
    # Start inclusive: 10:00 CST = 02:00 UTC. Stop at 23:00 CST = 15:00 UTC.
    # Weekends use the same hours (Saturday 2026-07-18).
    assert in_trading_window("Asia/Shanghai", "10:00", "23:00", _utc(2026, 7, 18, 2, 0))
    assert not in_trading_window("Asia/Shanghai", "10:00", "23:00", _utc(2026, 7, 18, 1, 59))
    assert not in_trading_window("Asia/Shanghai", "10:00", "23:00", _utc(2026, 7, 18, 15, 0))
    assert in_trading_window("Asia/Shanghai", "10:00", "23:00", _utc(2026, 7, 18, 14, 59))


def test_disabled_session_is_always_open():
    assert in_trading_window(
        "America/New_York",
        "08:00",
        "23:00",
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
        session_start="08:00",
        session_end="23:00",
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
        session_start="08:00",
        session_end="23:00",
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
        session_start="08:00",
        session_end="23:00",
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


def _dd(**kwargs):
    values = dict(
        review_pct=Decimal("0.10"),
        halt_pct=Decimal("0.25"),
        review_floor=Decimal("180"),
        halt_floor=Decimal("150"),
    )
    values.update(kwargs)
    return classify_drawdown(**values)


def test_classify_review_is_not_silent_halt():
    mid = _dd(equity=Decimal("200"), peak=Decimal("250"))
    assert mid.drawdown == Decimal("0.2")
    assert mid.review is True
    assert mid.halt is False

    halt = _dd(equity=Decimal("200"), peak=Decimal("400"))
    assert halt.review is True
    assert halt.halt is True

    below_180 = _dd(equity=Decimal("179"), peak=Decimal("200"))
    assert below_180.below_review_floor is True
    assert below_180.review is True
    assert below_180.halt is False  # 180 is review-only; 179 is not < 150
    assert below_180.below_halt_floor is False

    exact_180 = _dd(equity=Decimal("180"), peak=Decimal("200"))
    assert exact_180.review is True  # 10% from peak
    assert exact_180.halt is False
    assert exact_180.below_review_floor is False

    below_150 = _dd(equity=Decimal("149"), peak=Decimal("200"))
    assert below_150.below_halt_floor is True
    assert below_150.review is True
    assert below_150.halt is True


def test_review_10pct_keeps_scanning(tmp_path):
    cfg = paper_config(
        tmp_path,
        session_enabled=False,
        drawdown_review_pct=Decimal("0.10"),
        drawdown_review_floor_usd=Decimal("180"),
        drawdown_halt_pct=Decimal("0.25"),
        drawdown_halt_floor_usd=Decimal("150"),
    )
    market = binary_market(yes_asks=[level("0.52", "20")], no_asks=[level("0.52", "20")])
    stub = _StubMarket(market)
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
    )
    runner.watch.peak_equity = Decimal("250")  # 20% dd, review only
    report = runner.run_cycle()
    assert report.drawdown_review is True
    assert report.drawdown_halt is False
    assert report.skipped_reason == ""
    assert stub.list_calls == 1
    assert any(line.startswith("REVIEW drawdown") for line in report.messages)
    assert all("drawdown_halt" not in line for line in report.messages)
    assert "review=1" in report.summary
    assert "halt=0" in report.summary


def test_equity_below_180_reviews_but_keeps_scanning(tmp_path):
    cfg = paper_config(
        tmp_path,
        session_enabled=False,
        drawdown_review_pct=Decimal("0.90"),
        drawdown_review_floor_usd=Decimal("201"),
        drawdown_halt_pct=Decimal("0.95"),
        drawdown_halt_floor_usd=Decimal("150"),
    )
    market = binary_market(yes_asks=[level("0.52", "20")], no_asks=[level("0.52", "20")])
    stub = _StubMarket(market)
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
    )
    report = runner.run_cycle()
    assert report.drawdown_review is True  # 200 < 201
    assert report.drawdown_halt is False
    assert report.skipped_reason == ""
    assert stub.list_calls == 1
    assert any("keep scanning" in line for line in report.messages)


def test_drawdown_halt_uses_hard_floor(tmp_path):
    # Starting equity is 200; halt floor 201 trips even when pct halt is loose.
    cfg = paper_config(
        tmp_path,
        session_enabled=False,
        drawdown_review_floor_usd=Decimal("250"),
        drawdown_halt_pct=Decimal("0.90"),
        drawdown_halt_floor_usd=Decimal("201"),
    )
    market = binary_market(yes_asks=[level("0.30", "20")], no_asks=[level("0.30", "20")])
    stub = _StubMarket(market)
    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
    )
    report = runner.run_cycle()
    assert report.skipped_reason == "drawdown_halt"
    assert stub.list_calls == 0


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
    assert report.drawdown_review is True
    assert report.drawdown_halt is True
    assert any(line.startswith("REVIEW drawdown") for line in report.messages)
    assert any("SKIP drawdown_halt" in line and "hard stop" in line for line in report.messages)
    assert "review=1" in report.summary
    assert "halt=1" in report.summary


def test_overnight_idle_cycles_do_not_grow_booked_zero_streak(tmp_path):
    """Wall-clock overnight (end→next start) is not a 24h booked=0 meter."""
    cfg = paper_config(
        tmp_path,
        session_enabled=True,
        session_timezone="America/New_York",
        session_start="08:00",
        session_end="23:00",
        poll_interval_seconds=0.0,
    )
    market = binary_market(yes_asks=[level("0.52", "20")], no_asks=[level("0.52", "20")])
    stub = _StubMarket(market)
    clock = {"now": _utc(2026, 7, 16, 3, 0)}  # 23:00 EDT, closed

    def now_fn() -> datetime:
        return clock["now"]

    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=stub,  # type: ignore[arg-type]
        now_fn=now_fn,
    )
    runner.watch.zero_book_cycles = 4
    runner.watch.peak_equity = Decimal("200")
    for hour in range(3, 12):  # 23:00 EDT … 07:00 EDT; 08:00 EDT = 12:00 UTC is open
        clock["now"] = _utc(2026, 7, 16, hour, 0)
        report = runner.run_cycle()
        assert report.skipped_reason == "session_closed"
        assert runner.watch.zero_book_cycles == 4
        assert stub.list_calls == 0
    # Drawdown still ticks off-hours against live ledger vs peak.
    assert runner.watch.peak_equity == Decimal("200")
    assert report.drawdown == Decimal("0")


def test_session_watch_off_hours_do_not_count():
    watch = SessionWatch()
    watch.note_in_window(booked=0, did_scan=True)
    assert watch.zero_book_cycles == 1
    watch.note_off_window(idle_sessions=2)
    watch.note_off_window(idle_sessions=2)
    assert watch.zero_book_cycles == 1
    assert watch.zero_fill_sessions == 1
