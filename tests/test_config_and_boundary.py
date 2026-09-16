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
