from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from polybot.market.whiskas import parse_dt
from polybot.types import BookLevel, FeeSchedule, MarketSnapshot, OutcomeBook, ScanTarget

ZERO = Decimal("0")


def _levels(rows: list[Any]) -> tuple[BookLevel, ...]:
    out: list[BookLevel] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            out.append(BookLevel(price=Decimal(str(row[0])), size=Decimal(str(row[1]))))
        elif isinstance(row, dict):
            out.append(BookLevel(price=Decimal(str(row["price"])), size=Decimal(str(row["size"]))))
    return tuple(out)


def _outcome(token_id: str, name: str, asks: list[Any], fee: FeeSchedule) -> OutcomeBook:
    return OutcomeBook(
        token_id=token_id,
        outcome=name,
        bids=(),
        asks=_levels(asks),
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        fee=fee,
    )


def load_fixture(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("whiskas fixture root must be a mapping")
    return raw


def fixture_clock(raw: dict[str, Any], key: str) -> datetime:
    parsed = parse_dt(raw.get(key))
    if parsed is None:
        raise ValueError(f"fixture {key} must be an ISO timestamp")
    return parsed


def whiskas_snapshot(raw: dict[str, Any], *, resolved: bool = False, winner: str | None = None) -> MarketSnapshot:
    market = raw["market"]
    fee = FeeSchedule(
        rate=Decimal(str(market.get("fee_rate", "0.02"))),
        exponent=Decimal("2"),
        taker_only=bool(market.get("taker_only", True)),
    )
    up = market["up"]
    down = market["down"]
    return MarketSnapshot(
        condition_id=str(market["condition_id"]),
        question=str(market["question"]),
        fee=fee,
        outcomes=(
            _outcome(str(up["token_id"]), "Up", up["asks"], fee),
            _outcome(str(down["token_id"]), "Down", down["asks"], fee),
        ),
        min_order_size=Decimal(str(market.get("min_order_size", "1"))),
        kind="binary",
        slug=str(market.get("slug") or ""),
        round_open=parse_dt(market["round_open"]),
        round_end=parse_dt(market["round_end"]),
        resolved=resolved,
        winner=winner,
    )


def lock_arb_snapshot(raw: dict[str, Any]) -> MarketSnapshot | None:
    decoy = raw.get("lock_arb_decoy")
    if not isinstance(decoy, dict):
        return None
    fee = FeeSchedule(
        rate=Decimal(str(decoy.get("fee_rate", "0.02"))),
        exponent=Decimal("2"),
        taker_only=bool(decoy.get("taker_only", True)),
    )
    return MarketSnapshot(
        condition_id=str(decoy["condition_id"]),
        question=str(decoy.get("question") or decoy["condition_id"]),
        fee=fee,
        outcomes=(
            _outcome("tok-yes-decoy", "Yes", decoy["yes_asks"], fee),
            _outcome("tok-no-decoy", "No", decoy["no_asks"], fee),
        ),
        min_order_size=Decimal("1"),
        kind="binary",
    )


class FixtureMarket:
    """Recorded paper book. No CLOB calls. No live orders."""

    def __init__(self, raw: dict[str, Any], *, resolved: bool = False, winner: str | None = None) -> None:
        self.raw = raw
        self.resolved = resolved
        self.winner = winner
        self.last_screen = None
        self.whiskas_snap = whiskas_snapshot(raw, resolved=resolved, winner=winner)
        self.lock_snap = lock_arb_snapshot(raw)

    def list_scan_targets(self) -> list[ScanTarget]:
        if self.lock_snap is None:
            return []
        return [
            ScanTarget(
                kind="binary",
                event_id=self.lock_snap.condition_id,
                question=self.lock_snap.question,
                condition_ids=(self.lock_snap.condition_id,),
                token_ids=tuple(o.token_id for o in self.lock_snap.outcomes),
            )
        ]

    def list_whiskas_targets(self) -> list[ScanTarget]:
        snap = self.whiskas_snap
        return [
            ScanTarget(
                kind="binary",
                event_id=snap.condition_id,
                question=snap.question,
                condition_ids=(snap.condition_id,),
                token_ids=tuple(o.token_id for o in snap.outcomes),
                slug=snap.slug,
                round_open=snap.round_open,
                round_end=snap.round_end,
                resolved=snap.resolved,
                winner=snap.winner,
            )
        ]

    def snapshot_target(self, target: ScanTarget) -> MarketSnapshot | None:
        if target.event_id == self.whiskas_snap.condition_id:
            return self.whiskas_snap
        if self.lock_snap is not None and target.event_id == self.lock_snap.condition_id:
            return self.lock_snap
        return None

    def snapshot(self, condition_id: str) -> MarketSnapshot | None:
        if condition_id == self.whiskas_snap.condition_id:
            return self.whiskas_snap
        if self.lock_snap is not None and condition_id == self.lock_snap.condition_id:
            return self.lock_snap
        return None
