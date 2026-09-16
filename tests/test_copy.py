from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from polybot import COPY_MAX_CHASE, COPY_MAX_SLEEVE_PCT, COPY_STOP_PATH_DD, COPY_STOP_PEAK_DD
from polybot.config import ConfigError, CopyConfig, load_config
from polybot.copy.executor import (
    MirrorExecutor,
    MirrorIntent,
    chase_slippage,
    validate_v1_mirror_chase,
)
from polybot.copy.metrics import InMemoryMetricsProvider, JsonFileMetricsProvider, LeaderMetrics
from polybot.copy.monitor import EVENT_RESCAN_NEEDED, EVENT_STOP_FOLLOW, CopyMonitor, stop_follow_reason
from polybot.copy.rescan import LoggingRescanHook, RescanCriteria, filter_candidates
from polybot.copy.watchlist import load_watchlist
from polybot.ledger.store import PaperLedger
from polybot.runner.paper import PaperRunner
from polybot.types import LedgerState
from tests.conftest import paper_config


def _state(**kwargs) -> LedgerState:
    values = dict(
        starting_balance=Decimal("200"),
        cash=Decimal("200"),
        locked_payout=Decimal("0"),
        open_count=0,
        event_exposure={},
        fills=[],
    )
    values.update(kwargs)
    return LedgerState(**values)


def _metrics(
    leader_id: str = "x-MoneyForWhiskas",
    *,
    peak_dd: str = "0.01",
    path_dd: str = "0.01",
    month_pnl: str = "10",
) -> LeaderMetrics:
    return LeaderMetrics(
        leader_id=leader_id,
        peak_dd=Decimal(peak_dd),
        path_dd=Decimal(path_dd),
        month_pnl=Decimal(month_pnl),
    )


def _intent(**kwargs) -> MirrorIntent:
    values = dict(
        leader_id="x-MoneyForWhiskas",
        event_id="0xbtc5m",
        notional=Decimal("20"),
        size=Decimal("40"),
        delay_seconds=Decimal("2"),
        depth_walked=True,
        fees_applied=True,
        leader_px=Decimal("0.50"),
        fill_px=Decimal("0.50"),
        fee_per_share=Decimal("0.001"),
    )
    values.update(kwargs)
    return MirrorIntent(**values)


def test_copy_follow_rules_v1_encoded_in_config():
    """Pin config + constants to docs/copy_follow_rules.md (算法 v1)."""
    assert COPY_MAX_CHASE == "0.01"
    assert COPY_MAX_SLEEVE_PCT == "0.30"
    assert COPY_STOP_PEAK_DD == "0.05"
    assert COPY_STOP_PATH_DD == "0.05"
    cfg = load_config("config/paper.yaml")
    assert cfg.session_timezone == "America/New_York"
    assert cfg.session_start == "08:00"
    assert cfg.session_end == "23:00"
    assert cfg.session_start < cfg.session_end
    copy = cfg.copy
    assert copy is not None
    assert copy.max_chase_slippage == Decimal(COPY_MAX_CHASE)
    assert copy.max_sleeve_pct == Decimal("0.30")
    assert copy.stop_peak_dd == Decimal("0.05")
    assert copy.stop_path_dd == Decimal("0.05")
    assert copy.month_pnl_below == Decimal("0")
    assert [leader.id for leader in copy.leaders] == [
        "x-MoneyForWhiskas",
        "0xcd30457c79",
        "goldfisherrr",
    ]
    assert copy.leaders[0].primary is True


def test_watchlist_loads_from_paper_config():
    cfg = load_config("config/paper.yaml")
    assert cfg.copy is not None
    watch = load_watchlist(cfg.copy)
    assert [leader.id for leader in watch.leaders] == [
        "x-MoneyForWhiskas",
        "0xcd30457c79",
        "goldfisherrr",
    ]
    assert watch.primary() is not None
    assert watch.primary().id == "x-MoneyForWhiskas"
    assert watch.primary().strategy_tag == "BTC_5m"
    assert watch.leaders[1].label == "0xcd30457c79"
    assert watch.leaders[1].strategy_tag == "BTC_5m"
    assert watch.leaders[2].strategy_tag == "BTC_15m"
    assert all(leader.wallet is None for leader in watch.leaders)
    assert all(leader.active for leader in watch.leaders)


def test_watchlist_inline_copy_section(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["copy"] = {
        "enabled": True,
        "max_sleeve_pct": 0.30,
        "stop_follow": {"peak_dd": 0.05, "path_dd": 0.05, "month_pnl_below": 0},
        "leaders": [
            {"id": "solo", "label": "solo", "strategy_tag": "BTC_5m", "priority": 1, "primary": True}
        ],
    }
    path = tmp_path / "paper.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.copy is not None
    assert [leader.id for leader in cfg.copy.leaders] == ["solo"]


def test_rejects_loosened_copy_sleeve(tmp_path: Path):
    raw = yaml.safe_load(Path("config/copy.yaml").read_text(encoding="utf-8"))
    raw["max_sleeve_pct"] = 0.50
    copy_path = tmp_path / "copy.yaml"
    copy_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    paper = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    paper["copy"] = {"path": str(copy_path)}
    path = tmp_path / "paper.yaml"
    path.write_text(yaml.safe_dump(paper), encoding="utf-8")
    with pytest.raises(ConfigError, match="max_sleeve_pct"):
        load_config(path)


def test_rejects_unquoted_hex_leader_id(tmp_path: Path):
    raw = yaml.safe_load(Path("config/copy.yaml").read_text(encoding="utf-8"))
    raw["leaders"][1]["id"] = 0xCD30457C79
    raw["leaders"][1]["label"] = "0xcd30457c79"
    copy_path = tmp_path / "copy.yaml"
    copy_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    paper = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    paper["copy"] = {"path": str(copy_path)}
    path = tmp_path / "paper.yaml"
    path.write_text(yaml.safe_dump(paper), encoding="utf-8")
    with pytest.raises(ConfigError, match="quote"):
        load_config(path)


def test_rejects_loosened_chase_slippage(tmp_path: Path):
    raw = yaml.safe_load(Path("config/copy.yaml").read_text(encoding="utf-8"))
    raw["max_chase_slippage"] = 0.02
    copy_path = tmp_path / "copy.yaml"
    copy_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    paper = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    paper["copy"] = {"path": str(copy_path)}
    path = tmp_path / "paper.yaml"
    path.write_text(yaml.safe_dump(paper), encoding="utf-8")
    with pytest.raises(ConfigError, match="max_chase_slippage"):
        load_config(path)


def test_rejects_loosened_stop_follow_dd(tmp_path: Path):
    raw = yaml.safe_load(Path("config/copy.yaml").read_text(encoding="utf-8"))
    raw["stop_follow"]["peak_dd"] = 0.10
    copy_path = tmp_path / "copy.yaml"
    copy_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    paper = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    paper["copy"] = {"path": str(copy_path)}
    path = tmp_path / "paper.yaml"
    path.write_text(yaml.safe_dump(paper), encoding="utf-8")
    with pytest.raises(ConfigError, match="peak_dd"):
        load_config(path)


@pytest.mark.parametrize(
    ("peak_dd", "path_dd", "month_pnl", "expect"),
    [
        ("0.05", "0.01", "10", "peak_dd"),
        ("0.01", "0.05", "10", "path_dd"),
        ("0.01", "0.01", "-0.01", "month_pnl"),
        ("0.01", "0.01", "0", "month_pnl"),
        ("0.049", "0.049", "0.01", None),
        ("0.00", "0.00", "0.01", None),
    ],
)
def test_stop_follow_triggers(peak_dd: str, path_dd: str, month_pnl: str, expect: str | None):
    copy = load_config("config/paper.yaml").copy
    assert copy is not None
    reason = stop_follow_reason(
        _metrics(peak_dd=peak_dd, path_dd=path_dd, month_pnl=month_pnl),
        copy,
    )
    if expect is None:
        assert reason is None
    else:
        assert reason is not None
        assert expect in reason


def test_monitor_marks_inactive_and_emits_stop_and_rescan():
    cfg = load_config("config/paper.yaml")
    assert cfg.copy is not None
    watch = load_watchlist(cfg.copy)
    calls: list[RescanCriteria] = []

    class _Hook(LoggingRescanHook):
        def request_candidates(self, criteria: RescanCriteria) -> list[LeaderMetrics]:
            calls.append(criteria)
            return super().request_candidates(criteria)

    provider = InMemoryMetricsProvider(
        {"x-MoneyForWhiskas": _metrics(peak_dd="0.06", path_dd="0.01", month_pnl="8")}
    )
    monitor = CopyMonitor(cfg.copy, watch, provider, rescan=_Hook())
    events = monitor.poll()
    names = [event.name for event in events]
    assert names == [EVENT_STOP_FOLLOW, EVENT_RESCAN_NEEDED]
    assert watch.by_id("x-MoneyForWhiskas") is not None
    assert watch.by_id("x-MoneyForWhiskas").active is False
    assert watch.by_id("goldfisherrr").active is True
    assert any("STOP_FOLLOW" in event.line() for event in events)
    assert any("RESCAN_NEEDED" in event.line() for event in events)
    assert calls
    assert calls[0].max_peak_dd == Decimal("0.05")
    assert calls[0].max_path_dd == Decimal("0.05")
    assert calls[0].require_profitable is True
    assert monitor.poll() == []


def test_json_metrics_provider_roundtrip(tmp_path: Path):
    path = tmp_path / "metrics.json"
    path.write_text(
        """
        {
          "x-MoneyForWhiskas": {
            "peak_dd": "0.02",
            "path_dd": "0.01",
            "month_pnl": "12.5",
            "last_seen_active": "2026-09-16T12:00:00+00:00"
          }
        }
        """,
        encoding="utf-8",
    )
    provider = JsonFileMetricsProvider(path)
    snap = provider.snapshot("x-MoneyForWhiskas")
    assert snap is not None
    assert snap.peak_dd == Decimal("0.02")
    assert snap.path_dd == Decimal("0.01")
    assert snap.month_pnl == Decimal("12.5")
    assert snap.last_seen_active is not None
    assert provider.snapshot("missing") is None


def test_rescan_filter_keeps_tight_dd_and_profit():
    criteria = RescanCriteria(
        max_peak_dd=Decimal("0.05"),
        max_path_dd=Decimal("0.05"),
        require_profitable=True,
    )
    kept = filter_candidates(
        [
            _metrics("ok", peak_dd="0.04", path_dd="0.03", month_pnl="1"),
            _metrics("peak", peak_dd="0.05", path_dd="0.01", month_pnl="4"),
            _metrics("path", peak_dd="0.01", path_dd="0.05", month_pnl="4"),
            _metrics("red", peak_dd="0.01", path_dd="0.01", month_pnl="-1"),
            _metrics("flat", peak_dd="0.01", path_dd="0.01", month_pnl="0"),
        ],
        criteria,
    )
    assert [row.leader_id for row in kept] == ["ok"]


def test_sleeve_cap_rejects_over_30_percent_equity():
    cfg = paper_config()
    copy = CopyConfig(enabled=True, max_sleeve_pct=Decimal("0.30"))
    exe = MirrorExecutor(cfg, copy=copy)
    decision = exe.evaluate(
        _intent(notional=Decimal("40")),
        _state(),
        sleeve_used=Decimal("30"),
    )
    assert not decision.allowed
    assert "sleeve" in decision.reason


def test_sleeve_cap_allows_within_30_percent_equity():
    cfg = paper_config()
    copy = CopyConfig(enabled=True, max_sleeve_pct=Decimal("0.30"))
    exe = MirrorExecutor(cfg, copy=copy)
    # equity 200 * 30% = 60; used 20 + 20 = 40
    decision = exe.evaluate(
        _intent(notional=Decimal("20")),
        _state(),
        sleeve_used=Decimal("20"),
    )
    assert decision.allowed
    assert "no order" in decision.reason or "no fill" in decision.reason


def test_mirror_still_respects_25_percent_trade_cap():
    cfg = paper_config()
    copy = CopyConfig(enabled=True, max_sleeve_pct=Decimal("0.30"))
    exe = MirrorExecutor(cfg, copy=copy)
    # 51 > 25% of 200 cash, even though 51 < 30% of 200 equity
    decision = exe.evaluate(_intent(notional=Decimal("51")), _state())
    assert not decision.allowed
    assert "notional" in decision.reason


def test_mirror_still_respects_same_event_and_concurrent():
    cfg = paper_config()
    copy = CopyConfig(enabled=True, max_sleeve_pct=Decimal("0.30"))
    exe = MirrorExecutor(cfg, copy=copy)
    event = exe.evaluate(
        _intent(notional=Decimal("20")),
        _state(event_exposure={"0xbtc5m": Decimal("70")}),
    )
    assert not event.allowed
    assert "same-event" in event.reason
    concurrent = exe.evaluate(_intent(notional=Decimal("20")), _state(open_count=3))
    assert not concurrent.allowed
    assert "concurrent" in concurrent.reason


def test_v1_validator_requires_delay_walk_fee_then_abandons_over_one_cent():
    """after delay Δt, walk book; fill_px=VWAP; fee per fd; >1¢ → abandon, no copy."""
    ready = _intent(
        delay_seconds=Decimal("2"),
        depth_walked=True,
        fees_applied=True,
        leader_px=Decimal("0.50"),
        fill_px=Decimal("0.50"),
        fee_per_share=Decimal("0.001"),
    )
    assert validate_v1_mirror_chase(ready) is None
    assert validate_v1_mirror_chase(_intent(delay_seconds=None)) is not None
    assert validate_v1_mirror_chase(_intent(depth_walked=False)) is not None
    assert validate_v1_mirror_chase(_intent(fees_applied=False)) is not None
    # |0.51 − 0.50| + 0.002 = 0.012 > 0.01 → abandon
    over = _intent(leader_px=Decimal("0.50"), fill_px=Decimal("0.51"), fee_per_share=Decimal("0.002"))
    reason = validate_v1_mirror_chase(over)
    assert reason is not None
    assert "abandon" in reason
    assert "do not copy" in reason
    # Exactly 1¢ is still copyable
    at_cap = _intent(leader_px=Decimal("0.50"), fill_px=Decimal("0.505"), fee_per_share=Decimal("0.005"))
    assert validate_v1_mirror_chase(at_cap) is None


def test_chase_slippage_formula():
    assert chase_slippage(Decimal("0.50"), Decimal("0.50"), Decimal("0.01")) == Decimal("0.01")
    assert chase_slippage(Decimal("0.52"), Decimal("0.50"), Decimal("0.002")) == Decimal("0.022")


def test_mirror_allows_chase_at_one_cent():
    cfg = paper_config()
    copy = CopyConfig(enabled=True, max_chase_slippage=Decimal("0.01"))
    exe = MirrorExecutor(cfg, copy=copy)
    # |0.505 - 0.50| + 0.005 = 0.01 → allowed (not greater than 1¢)
    decision = exe.evaluate(
        _intent(leader_px=Decimal("0.50"), fill_px=Decimal("0.505"), fee_per_share=Decimal("0.005")),
        _state(),
    )
    assert decision.allowed


def test_mirror_abandons_chase_over_one_cent():
    cfg = paper_config()
    copy = CopyConfig(enabled=True, max_chase_slippage=Decimal("0.01"))
    exe = MirrorExecutor(cfg, copy=copy)
    # |0.51 - 0.50| + 0.002 = 0.012 > 0.01
    decision = exe.evaluate(
        _intent(leader_px=Decimal("0.50"), fill_px=Decimal("0.51"), fee_per_share=Decimal("0.002")),
        _state(),
    )
    assert not decision.allowed
    assert "chase" in decision.reason
    assert "abandon" in decision.reason
    assert exe.execute(
        _intent(leader_px=Decimal("0.50"), fill_px=Decimal("0.52"), fee_per_share=Decimal("0")),
        _state(),
    ).rejected


def test_mirror_rejects_missing_chase_prices():
    cfg = paper_config()
    copy = CopyConfig(enabled=True)
    exe = MirrorExecutor(cfg, copy=copy)
    decision = exe.evaluate(_intent(leader_px=None, fill_px=None, fee_per_share=None), _state())
    assert not decision.allowed
    assert "leader_px" in decision.reason


def test_mirror_rejects_missing_delay_depth_or_fees():
    cfg = paper_config()
    copy = CopyConfig(enabled=True)
    exe = MirrorExecutor(cfg, copy=copy)
    assert not exe.evaluate(_intent(delay_seconds=None), _state()).allowed
    assert not exe.evaluate(_intent(depth_walked=False), _state()).allowed
    assert not exe.evaluate(_intent(fees_applied=False), _state()).allowed


def test_mirror_executor_does_not_write_fills(tmp_path: Path):
    cfg = paper_config(tmp_path)
    copy = CopyConfig(enabled=True)
    ledger = PaperLedger(cfg.ledger_path, cfg.starting_balance)
    before = ledger.state()
    exe = MirrorExecutor(cfg, copy=copy)
    decision = exe.execute(_intent(notional=Decimal("20")), before)
    assert decision.allowed
    after = ledger.state()
    assert after.cash == before.cash
    assert after.fills == []
    assert after.open_count == 0


def test_paper_runner_emits_stop_follow_from_json_stub(tmp_path: Path):
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(
        '{"x-MoneyForWhiskas": {"peak_dd": "0.09", "path_dd": "0.01", "month_pnl": "3"}}',
        encoding="utf-8",
    )
    copy = CopyConfig(
        enabled=True,
        leaders=load_config("config/paper.yaml").copy.leaders,  # type: ignore[union-attr]
        metrics_stub=metrics_path,
    )
    cfg = paper_config(tmp_path, copy=copy, session_enabled=False)

    class _EmptyMarket:
        def list_condition_ids(self):
            return []

        def snapshot(self, condition_id: str):
            return None

    runner = PaperRunner(cfg, market=_EmptyMarket())  # type: ignore[arg-type]
    report = runner.run_cycle()
    assert EVENT_STOP_FOLLOW in report.copy_events
    assert EVENT_RESCAN_NEEDED in report.copy_events
    assert any("STOP_FOLLOW" in line for line in report.messages)
    assert runner.copy_watchlist is not None
    assert runner.copy_watchlist.by_id("x-MoneyForWhiskas").active is False
    assert runner.ledger.state().fills == []
