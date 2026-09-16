from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from polybot.config import ConfigError, load_config
from polybot.market.client import LiveOrderForbidden, PaperMarketClient
from polybot.runner.cli import main
from tests.conftest import paper_config


def test_load_default_config():
    cfg = load_config("config/paper.yaml")
    assert cfg.mode == "paper"
    assert cfg.starting_balance == Decimal("200")
    assert cfg.target_balance == Decimal("1000")
    assert cfg.taker_edge_floor == Decimal("0.005")
    assert cfg.maker_edge_floor == Decimal("0.002")
    assert cfg.max_trade_notional_pct == Decimal("0.25")
    assert cfg.max_same_event_exposure_pct == Decimal("0.40")
    assert cfg.max_concurrent_open == 3
    assert cfg.session_enabled is True
    assert cfg.session_timezone == "America/New_York"
    assert cfg.session_start == "09:00"
    assert cfg.session_end == "22:00"
    assert cfg.idle_zero_fill_sessions == 2
    assert cfg.drawdown_review_pct == Decimal("0.10")
    assert cfg.drawdown_review_floor_usd == Decimal("180")
    assert cfg.drawdown_halt_pct == Decimal("0.25")
    assert cfg.drawdown_halt_floor_usd == Decimal("150")


def test_rejects_loosened_position_cap(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["risk"]["max_trade_notional_pct"] = 0.50
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="max_trade_notional_pct"):
        load_config(path)


def test_rejects_lowered_edge_floor(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["edge"]["taker_floor"] = 0.001
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="taker_edge_floor"):
        load_config(path)


def test_rejects_too_fast_polling(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["scan"]["poll_interval_seconds"] = 1
    path = tmp_path / "fast.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="poll_interval_seconds"):
        load_config(path)


def test_session_window_is_yaml_editable(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["session"]["timezone"] = "Asia/Shanghai"
    raw["session"]["start"] = "10:00"
    raw["session"]["end"] = "23:00"
    path = tmp_path / "shanghai.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.session_timezone == "Asia/Shanghai"
    assert cfg.session_start == "10:00"
    assert cfg.session_end == "23:00"
    assert cfg.session_enabled is True


def test_rejects_review_pct_above_halt(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["session"]["drawdown_review_pct"] = 0.30
    raw["session"]["drawdown_halt_pct"] = 0.25
    path = tmp_path / "raised.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="drawdown_review_pct"):
        load_config(path)


def test_rejects_halt_floor_at_review_180(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["session"]["drawdown_review_floor_usd"] = 180
    raw["session"]["drawdown_halt_floor_usd"] = 180
    path = tmp_path / "samefloor.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="review-only"):
        load_config(path)


def test_rejects_24h_session_window(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["session"]["start"] = "00:00"
    raw["session"]["end"] = "00:00"
    path = tmp_path / "allday.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="24h"):
        load_config(path)


def test_rejects_non_paper_mode(tmp_path: Path):
    raw = yaml.safe_load(Path("config/paper.yaml").read_text(encoding="utf-8"))
    raw["mode"] = "live"
    path = tmp_path / "live.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="paper"):
        load_config(path)


class _FakeClob:
    signer = None
    creds = None

    def create_and_post_order(self, *args, **kwargs):
        raise AssertionError("should be unreachable")


def test_paper_client_blocks_live_order_methods():
    client = PaperMarketClient(paper_config(), clob=_FakeClob())
    with pytest.raises(LiveOrderForbidden, match="create_and_post_order"):
        client.create_and_post_order()
    with pytest.raises(LiveOrderForbidden, match="post_order"):
        client.post_order()


def test_cli_rejects_live_flag():
    assert main(["--live"]) == 2
