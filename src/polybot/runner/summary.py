from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from polybot.config import PaperConfig
from polybot.types import LedgerFill, LedgerState


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class SessionStats:
    started_at: datetime = field(default_factory=_utc_now)
    cycles: int = 0
    scanned: int = 0
    candidates: int = 0
    booked: int = 0
    rejected_edges: int = 0
    rejected_risk: int = 0
    snapshot_failures: int = 0

    def record_cycle(
        self,
        *,
        scanned: int,
        candidates: int,
        booked: int,
        rejected_edges: int,
        rejected_risk: int,
        snapshot_failures: int,
    ) -> None:
        self.cycles += 1
        self.scanned += scanned
        self.candidates += candidates
        self.booked += booked
        self.rejected_edges += rejected_edges
        self.rejected_risk += rejected_risk
        self.snapshot_failures += snapshot_failures


def _fills_since(fills: list[LedgerFill], start: datetime) -> list[LedgerFill]:
    out: list[LedgerFill] = []
    for fill in fills:
        ts = _parse_ts(fill.ts)
        if ts is None or ts >= start:
            out.append(fill)
    return out


def _win_rate(fills: list[LedgerFill]) -> Decimal | None:
    if not fills:
        return None
    wins = sum(1 for fill in fills if fill.expected_payout > fill.cash_debit)
    return (Decimal(wins) / Decimal(len(fills))) * Decimal("100")


def format_summary(
    label: str,
    config: PaperConfig,
    state: LedgerState,
    stats: SessionStats,
    *,
    fills: list[LedgerFill] | None = None,
) -> str:
    window_fills = fills if fills is not None else state.fills
    pnl = state.equity - state.starting_balance
    pnl_pct = (pnl / state.starting_balance) * Decimal("100") if state.starting_balance else Decimal("0")
    progress = (state.equity / config.target_balance) * Decimal("100")
    win = _win_rate(window_fills)
    win_txt = f"{win:.1f}%" if win is not None else "n/a"
    return (
        f"{label} cycles={stats.cycles} scanned={stats.scanned} "
        f"candidates={stats.candidates} booked={stats.booked} "
        f"rejected_edge={stats.rejected_edges} rejected_risk={stats.rejected_risk} "
        f"cash={state.cash:.4f} equity={state.equity:.4f} "
        f"pnl={pnl:+.4f} ({pnl_pct:+.2f}%) win_rate={win_txt} "
        f"open={state.open_count}/{config.max_concurrent_open} "
        f"exposure={state.open_exposure:.4f} target={config.target_balance} ({progress:.2f}%)"
    )


def daily_fills(state: LedgerState, now: datetime | None = None) -> list[LedgerFill]:
    now = now or _utc_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _fills_since(state.fills, start)
