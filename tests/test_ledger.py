from __future__ import annotations

from decimal import Decimal

import pytest

from polybot.ledger.store import LedgerError, PaperLedger
from polybot.types import Leg, Opportunity


def _opp(event: str = "0xevent", notional: str = "10", payout: str = "12", oid: str | None = None) -> Opportunity:
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
        notes=oid or "test",
    )


def test_genesis_and_derived_balance(tmp_path):
    ledger = PaperLedger(tmp_path / "l.jsonl", Decimal("200"))
    state = ledger.state()
    assert state.cash == Decimal("200")
    assert state.equity == Decimal("200")
    assert state.open_count == 0
    assert state.fills == []


def test_append_fill_updates_cash_and_exposure(tmp_path):
    ledger = PaperLedger(tmp_path / "l.jsonl", Decimal("200"))
    ledger.append_fill(_opp())
    state = ledger.state()
    assert state.cash == Decimal("190")
    assert state.locked_payout == Decimal("12")
    assert state.equity == Decimal("202")
    assert state.event_exposure["0xevent"] == Decimal("10")
    assert state.open_count == 1


def test_manual_balance_edit_forbidden(tmp_path):
    ledger = PaperLedger(tmp_path / "l.jsonl", Decimal("200"))
    with pytest.raises(LedgerError, match="forbidden"):
        ledger.set_balance(Decimal("999"))
    with pytest.raises(LedgerError, match="immutable"):
        ledger.rewrite([])


def test_hash_chain_detects_tamper(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = PaperLedger(path, Decimal("200"))
    ledger.append_fill(_opp())
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"cash_debit":"10"', '"cash_debit":"1"'), encoding="utf-8")
    with pytest.raises(LedgerError, match="hash chain"):
        ledger.state()


def test_balance_field_in_file_is_rejected(tmp_path):
    path = tmp_path / "l.jsonl"
    PaperLedger(path, Decimal("200"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"type":"fill","balance":"999","hash":"x","prev_hash":"0"}\n')
    with pytest.raises(LedgerError, match="manual balance"):
        PaperLedger(path, Decimal("200")).state()


def test_duplicate_opportunity_rejected(tmp_path):
    ledger = PaperLedger(tmp_path / "l.jsonl", Decimal("200"))
    ledger.append_fill(_opp())
    with pytest.raises(LedgerError, match="duplicate"):
        ledger.append_fill(_opp())
