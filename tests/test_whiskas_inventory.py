from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from polybot.config import load_config
from polybot.ledger.accounts import ARB_MAIN_ID, WHISKAS_INV_ID, open_account_book
from polybot.ledger.store import PaperLedger
from polybot.market.whiskas import is_btc_5m_updown, whiskas_target_from_row
from polybot.risk.gates import RiskEngine
from polybot.runner.paper import PaperRunner
from polybot.strategy.whiskas_inventory import WhiskasInventoryStrategy, whiskas_window
from polybot.types import Leg, Opportunity, ScanTarget
from tests.conftest import btc_updown_market, level, paper_config, whiskas_cfg


OPEN = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _now(seconds: float) -> datetime:
    return OPEN + timedelta(seconds=seconds)


def _cfg(tmp_path: Path, **overrides):
    return paper_config(
        tmp_path,
        whiskas=whiskas_cfg(ledger_path=tmp_path / "whiskas-inv.jsonl"),
        race_primary_account="whiskas-inv",
        **overrides,
    )


def _scan(market, cfg, now: datetime, spent: str = "0"):
    return WhiskasInventoryStrategy().scan(
        market, cfg, now=now, round_notional=Decimal(spent)
    )


def test_yaml_copy_stays_disabled_and_session_is_24h():
    cfg = load_config("config/paper.yaml")
    assert cfg.copy is not None
    assert cfg.copy.enabled is False
    assert cfg.session_enabled is False
    assert "08:00" not in Path("config/paper.yaml").read_text(encoding="utf-8")
    assert cfg.whiskas is not None
    assert cfg.whiskas.enabled is True


def test_timing_gate_too_early_and_too_late(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.40", "80")],
        [level("0.40", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    assert whiskas_window(market, _now(5), cfg.whiskas)[1] == "too_early"
    assert _scan(market, cfg, _now(5)) == []
    assert whiskas_window(market, _now(200), cfg.whiskas)[1] == "too_late"
    assert _scan(market, cfg, _now(200)) == []
    assert whiskas_window(market, _now(199), cfg.whiskas) == (True, "ok")
    assert whiskas_window(market, _now(6), cfg.whiskas) == (True, "ok")
    assert _scan(market, cfg, _now(6))


def test_price_cap_blocks_expensive_leg_cheap_continues(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.91", "80")],
        [level("0.40", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    opps = _scan(market, cfg, _now(30))
    assert len(opps) == 1
    assert [leg.outcome for leg in opps[0].legs] == ["Down"]
    assert all(leg.side == "BUY" for leg in opps[0].legs)
    assert opps[0].legs[0].price <= Decimal("0.89")


def test_combo_cap_rejects_paired_extreme_book(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.54", "80")],
        [level("0.54", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    assert Decimal("0.54") + Decimal("0.54") > Decimal("1.05")
    assert _scan(market, cfg, _now(30)) == []


def test_pairs_both_legs_inside_caps(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.48", "80")],
        [level("0.46", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    opps = _scan(market, cfg, _now(30))
    assert len(opps) == 1
    assert {leg.outcome for leg in opps[0].legs} == {"Up", "Down"}
    assert all(leg.side == "BUY" for leg in opps[0].legs)
    assert all(leg.size == Decimal("50") for leg in opps[0].legs)
    assert all(leg.levels_used >= 1 for leg in opps[0].legs)
    assert sum(leg.price for leg in opps[0].legs) <= Decimal("1.05")


def test_no_sells_from_strategy_or_ledger(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.40", "80")],
        [level("0.40", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    opp = _scan(market, cfg, _now(30))[0]
    assert all(leg.side == "BUY" for leg in opp.legs)
    ledger = PaperLedger(tmp_path / "w.jsonl", Decimal("2300"))
    fill = ledger.append_fill(opp)
    assert all(leg.side == "BUY" for leg in fill.legs)
    sell = Opportunity(
        strategy="whiskas_inventory",
        event_id="0xbtc5m",
        question="q",
        edge=Decimal("0"),
        size=Decimal("50"),
        notional=Decimal("20"),
        expected_payout=Decimal("0"),
        legs=(
            Leg("tok-up", "Up", "SELL", "taker", Decimal("50"), Decimal("0.40"), Decimal("0"), Decimal("20"), 1),
        ),
        clip_id="sell-forbidden",
    )
    decision = RiskEngine(cfg).evaluate(sell, ledger.state())
    assert not decision.allowed
    assert "sell" in decision.reason


def test_per_round_cap_and_depth_walk_fees(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.40", "30"), level("0.41", "40")],
        [level("0.40", "30"), level("0.42", "40")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    opps = _scan(market, cfg, _now(30), spent="1190")
    assert opps == []
    opp = _scan(market, cfg, _now(30), spent="0")[0]
    assert opp.legs[0].levels_used >= 2
    assert opp.notional == sum((leg.notional for leg in opp.legs), Decimal("0"))
    assert opp.notional > Decimal("40")


def test_arb_main_booking_paused_whiskas_books(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.30", "80")],
        [level("0.30", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    lockish = btc_updown_market(
        [level("0.30", "80")],
        [level("0.30", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
        condition_id="0xlock",
    )

    class _Market:
        def list_scan_targets(self):
            return [
                ScanTarget(kind="binary", event_id="0xlock", question=lockish.question, condition_ids=("0xlock",))
            ]

        def snapshot_target(self, target):
            if target.event_id == market.condition_id:
                return market
            return lockish if target.event_id == "0xlock" else None

        def list_whiskas_targets(self):
            return [
                ScanTarget(
                    kind="binary",
                    event_id=market.condition_id,
                    question=market.question,
                    condition_ids=(market.condition_id,),
                    slug=market.slug,
                    round_open=market.round_open,
                    round_end=market.round_end,
                )
            ]

        def snapshot(self, condition_id: str):
            if condition_id == market.condition_id:
                return market
            if condition_id == "0xlock":
                return lockish
            return None

    runner = PaperRunner(
        cfg,
        ledger=PaperLedger(cfg.ledger_path, cfg.starting_balance),
        market=_Market(),  # type: ignore[arg-type]
        now_fn=lambda: _now(30),
    )
    assert runner.book.arb().paused is True
    report = runner.run_cycle()
    assert runner.book.arb().state().fills == []
    assert runner.book.arb().state().cash == cfg.starting_balance
    whiskas = runner.book.whiskas()
    assert whiskas is not None
    assert whiskas.state().cash < Decimal("2300")
    assert whiskas.state().fills
    assert all(leg.side == "BUY" for fill in whiskas.state().fills for leg in fill.legs)
    assert report.booked >= 1
    assert any("whiskas_inventory" in line for line in report.messages)
    assert any("paused=1" in line and "account=arb-main" in line for line in report.messages)
    assert "distance_to_start=" in report.summary
    assert "round_cap=1200.0000" in report.summary


def test_redemption_credits_winner_without_sell(tmp_path):
    cfg = _cfg(tmp_path)
    market = btc_updown_market(
        [level("0.40", "80")],
        [level("0.40", "80")],
        round_open=OPEN,
        round_end=OPEN + timedelta(seconds=300),
    )
    ledger = PaperLedger(tmp_path / "w.jsonl", Decimal("2300"))
    opp = _scan(market, cfg, _now(30))[0]
    ledger.append_fill(opp)
    before = ledger.state().cash
    fill = ledger.append_redemption(
        event_id=market.condition_id,
        winner="Up",
        cash_credit=Decimal("50"),
        question=market.question,
        notes="redeem winner=Up",
    )
    assert fill.cash_credit == Decimal("50")
    assert fill.legs == ()
    assert ledger.state().cash == before + Decimal("50")
    assert ledger.inventory_shares(market.condition_id) == {"Up": Decimal("0"), "Down": Decimal("0")}


def test_whiskas_review_and_hard_floors(tmp_path):
    cfg = _cfg(tmp_path)

    class _Empty:
        def list_condition_ids(self):
            return []

        def snapshot(self, condition_id: str):
            return None

        def list_whiskas_targets(self):
            return []

    runner = PaperRunner(cfg, market=_Empty())  # type: ignore[arg-type]
    whiskas = runner.book.whiskas()
    assert whiskas is not None
    runner.watches[whiskas.account_id].peak_equity = Decimal("2300")
    review = runner._account_dd(whiskas.account_id, whiskas.state())
    assert review.review is False
    assert review.halt is False
    # 10% from 2300 = 2070; equity 2069 trips REVIEW but not HARD 1725
    class _State:
        equity = Decimal("2069")

    mid = runner._account_dd(whiskas.account_id, _State())  # type: ignore[arg-type]
    assert mid.review is True
    assert mid.halt is False
    hard = runner._account_dd(whiskas.account_id, type("S", (), {"equity": Decimal("1724")})())  # type: ignore[arg-type]
    assert hard.halt is True


def test_default_book_pauses_arb_and_opens_whiskas_inv(tmp_path: Path):
    cfg = load_config("config/paper.yaml")
    cfg = cfg.__class__(**{**cfg.__dict__, "ledger_path": tmp_path / "arb-main.jsonl"})
    book = open_account_book(cfg)
    assert book.arb().account_id == ARB_MAIN_ID
    assert book.arb().paused is True
    assert book.whiskas() is not None
    assert book.whiskas().account_id == WHISKAS_INV_ID
    assert book.whiskas().state().starting_balance == Decimal("2300")


def test_discovery_filters_btc_5m_updown():
    cfg = whiskas_cfg()
    assert is_btc_5m_updown("Bitcoin Up or Down - 8:00AM-8:05AM ET", cfg)
    assert not is_btc_5m_updown("Bitcoin Up or Down - 8:00AM-9:00AM ET", cfg)
    assert is_btc_5m_updown("btc-updown-5m-123", cfg)
    row = {
        "conditionId": "0xabc",
        "question": "Bitcoin Up or Down - September 16, 8:00AM-8:05AM ET",
        "slug": "btc-updown-5m-1",
        "endDate": "2026-09-16T12:05:00Z",
        "eventStartTime": "2026-09-16T12:00:00Z",
    }
    target = whiskas_target_from_row(row, cfg)
    assert target is not None
    assert target.event_id == "0xabc"
    hourly = dict(row, question="Bitcoin Up or Down - 8:00AM-9:00AM ET", slug="btc-updown-1h")
    hourly.pop("eventStartTime")
    hourly["endDate"] = "2026-09-16T13:00:00Z"
    hourly["eventStartTime"] = "2026-09-16T12:00:00Z"
    assert whiskas_target_from_row(hourly, cfg) is None
