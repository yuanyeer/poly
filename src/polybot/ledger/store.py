from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from polybot.types import LedgerFill, LedgerState, Leg, Opportunity

GENESIS_TYPE = "genesis"
FILL_TYPE = "fill"
ZERO_HASH = "0" * 64


class LedgerError(RuntimeError):
    """Ledger integrity or mutation error."""


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_record(prev_hash: str, body: dict[str, Any]) -> str:
    material = prev_hash + _dumps(body)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _leg_to_dict(leg: Leg) -> dict[str, Any]:
    return {
        "token_id": leg.token_id,
        "outcome": leg.outcome,
        "side": leg.side,
        "role": leg.role,
        "size": str(leg.size),
        "price": str(leg.price),
        "fee": str(leg.fee),
        "notional": str(leg.notional),
        "levels_used": leg.levels_used,
    }


def _leg_from_dict(raw: dict[str, Any]) -> Leg:
    return Leg(
        token_id=str(raw["token_id"]),
        outcome=str(raw["outcome"]),
        side=raw["side"],
        role=raw["role"],
        size=_dec(raw["size"]),
        price=_dec(raw["price"]),
        fee=_dec(raw["fee"]),
        notional=_dec(raw["notional"]),
        levels_used=int(raw["levels_used"]),
    )


class PaperLedger:
    """Append-only paper ledger. Balance is derived; never stored as an editable field."""

    def __init__(self, path: str | Path, starting_balance: Decimal) -> None:
        self.path = Path(path)
        self.starting_balance = starting_balance
        self._ensure_genesis()

    def _ensure_genesis(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > 0:
            return
        body = {
            "type": GENESIS_TYPE,
            "ts": _now(),
            "starting_balance": str(self.starting_balance),
        }
        record = {**body, "prev_hash": ZERO_HASH, "hash": _hash_record(ZERO_HASH, body)}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_dumps(record) + "\n")

    def _read_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    records.append(json.loads(text))
                except json.JSONDecodeError as exc:
                    raise LedgerError(f"corrupt ledger at line {line_no}: {exc}") from exc
        return records

    def verify(self) -> list[dict[str, Any]]:
        records = self._read_records()
        if not records:
            raise LedgerError("ledger is empty")
        genesis = records[0]
        if genesis.get("type") != GENESIS_TYPE:
            raise LedgerError("first record must be genesis")
        if "balance" in genesis or "cash" in genesis:
            raise LedgerError("genesis must not contain a mutable balance field")
        start = _dec(genesis.get("starting_balance", self.starting_balance))
        if start != self.starting_balance:
            raise LedgerError(
                f"genesis starting_balance {start} does not match configured {self.starting_balance}"
            )
        prev = ZERO_HASH
        for idx, record in enumerate(records):
            if "balance" in record:
                raise LedgerError("manual balance fields are forbidden")
            stored_prev = str(record.get("prev_hash", ""))
            stored_hash = str(record.get("hash", ""))
            body = {k: v for k, v in record.items() if k not in {"hash", "prev_hash"}}
            expected = _hash_record(prev, body)
            if stored_prev != prev or stored_hash != expected:
                raise LedgerError(f"hash chain broken at record {idx}")
            prev = stored_hash
        return records

    def state(self) -> LedgerState:
        records = self.verify()
        cash = self.starting_balance
        locked = Decimal("0")
        event_exposure: dict[str, Decimal] = {}
        fills: list[LedgerFill] = []
        for record in records:
            if record.get("type") != FILL_TYPE:
                continue
            fill = self._fill_from_record(record)
            cash -= fill.cash_debit
            cash += fill.cash_credit
            locked += fill.expected_payout
            event_exposure[fill.event_id] = event_exposure.get(fill.event_id, Decimal("0")) + fill.cash_debit
            fills.append(fill)
        return LedgerState(
            starting_balance=self.starting_balance,
            cash=cash,
            locked_payout=locked,
            open_count=len(fills),
            event_exposure=event_exposure,
            fills=fills,
        )

    def _fill_from_record(self, record: dict[str, Any]) -> LedgerFill:
        legs = tuple(_leg_from_dict(item) for item in record.get("legs") or [])
        return LedgerFill(
            fill_id=str(record["fill_id"]),
            ts=str(record["ts"]),
            opportunity_id=str(record["opportunity_id"]),
            event_id=str(record["event_id"]),
            strategy=str(record["strategy"]),
            question=str(record.get("question", "")),
            size=_dec(record["size"]),
            edge=_dec(record["edge"]),
            cash_debit=_dec(record["cash_debit"]),
            cash_credit=_dec(record["cash_credit"]),
            expected_payout=_dec(record["expected_payout"]),
            legs=legs,
            notes=str(record.get("notes", "")),
            prev_hash=str(record.get("prev_hash", "")),
            hash=str(record.get("hash", "")),
        )

    def append_fill(self, opportunity: Opportunity) -> LedgerFill:
        records = self.verify()
        prev_hash = str(records[-1]["hash"])
        if any(r.get("type") == FILL_TYPE and r.get("opportunity_id") == opportunity.opportunity_id for r in records):
            raise LedgerError(f"duplicate opportunity {opportunity.opportunity_id}")

        fill_id = uuid.uuid4().hex
        body: dict[str, Any] = {
            "type": FILL_TYPE,
            "fill_id": fill_id,
            "ts": _now(),
            "opportunity_id": opportunity.opportunity_id,
            "event_id": opportunity.event_id,
            "strategy": opportunity.strategy,
            "question": opportunity.question,
            "size": str(opportunity.size),
            "edge": str(opportunity.edge),
            "cash_debit": str(opportunity.notional),
            "cash_credit": "0",
            "expected_payout": str(opportunity.expected_payout),
            "legs": [_leg_to_dict(leg) for leg in opportunity.legs],
            "notes": opportunity.notes,
        }
        record = {**body, "prev_hash": prev_hash, "hash": _hash_record(prev_hash, body)}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_dumps(record) + "\n")
        return self._fill_from_record(record)

    def set_balance(self, *_args: Any, **_kwargs: Any) -> None:
        raise LedgerError("manual balance edits are forbidden")

    def rewrite(self, *_args: Any, **_kwargs: Any) -> None:
        raise LedgerError("ledger records are immutable")

    def open_opportunity_ids(self) -> set[str]:
        return {fill.opportunity_id for fill in self.state().fills}


def replay(records: Iterable[dict[str, Any]], starting_balance: Decimal) -> Decimal:
    cash = starting_balance
    for record in records:
        if record.get("type") != FILL_TYPE:
            continue
        cash -= _dec(record["cash_debit"])
        cash += _dec(record.get("cash_credit", 0))
    return cash
