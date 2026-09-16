from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median

from polybot.config import PaperConfig
from polybot.types import LedgerFill, LedgerState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_day_start(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass
class SessionStats:
    started_at: datetime = field(default_factory=utc_now)
    cycles: int = 0
    scanned: int = 0
    candidates: int = 0
    booked: int = 0
    rejected_edges: int = 0
    rejected_risk: int = 0
    snapshot_failures: int = 0
    below_floor_n: int = 0
    net_edges: list[Decimal] = field(default_factory=list)
    _edge_day: str | None = None

    def reset_daily_edges(self, day_key: str) -> None:
        if self._edge_day != day_key:
            self._edge_day = day_key
            self.below_floor_n = 0
            self.net_edges = []

    def record_net_edge(self, edge: Decimal, floor: Decimal) -> None:
        self.net_edges.append(edge)
        if edge < floor:
            self.below_floor_n += 1

    @property
    def median_net_edge(self) -> Decimal | None:
        if not self.net_edges:
            return None
        return Decimal(str(median(self.net_edges)))

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


@dataclass(frozen=True)
class DailySnapshot:
    date: str
    fills: int
    win_rate: Decimal | None
    booked_notional: Decimal
    locked_edge: Decimal
    cash: Decimal
    equity: Decimal
    pnl: Decimal
    open_count: int
    open_exposure: Decimal
    below_floor_n: int = 0
    median_net_edge: Decimal | None = None


def _fills_since(fills: list[LedgerFill], start: datetime) -> list[LedgerFill]:
    out: list[LedgerFill] = []
    for fill in fills:
        ts = _parse_ts(fill.ts)
        if ts is None or ts >= start:
            out.append(fill)
    return out


def daily_fills(state: LedgerState, now: datetime | None = None) -> list[LedgerFill]:
    return _fills_since(state.fills, utc_day_start(now))


def win_rate(fills: list[LedgerFill]) -> Decimal | None:
    if not fills:
        return None
    wins = sum(1 for fill in fills if fill.expected_payout > fill.cash_debit)
    return (Decimal(wins) / Decimal(len(fills))) * Decimal("100")


def build_daily_snapshot(
    state: LedgerState,
    now: datetime | None = None,
    *,
    below_floor_n: int = 0,
    median_net_edge: Decimal | None = None,
) -> DailySnapshot:
    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    fills = daily_fills(state, current)
    locked_edge = sum((fill.expected_payout - fill.cash_debit for fill in fills), Decimal("0"))
    booked_notional = sum((fill.cash_debit for fill in fills), Decimal("0"))
    return DailySnapshot(
        date=current.date().isoformat(),
        fills=len(fills),
        win_rate=win_rate(fills),
        booked_notional=booked_notional,
        locked_edge=locked_edge,
        cash=state.cash,
        equity=state.equity,
        pnl=state.equity - state.starting_balance,
        open_count=state.open_count,
        open_exposure=state.open_exposure,
        below_floor_n=below_floor_n,
        median_net_edge=median_net_edge,
    )


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
    win = win_rate(window_fills)
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


def format_daily(snapshot: DailySnapshot, config: PaperConfig) -> str:
    win_txt = f"{snapshot.win_rate:.1f}%" if snapshot.win_rate is not None else "n/a"
    median_txt = f"{snapshot.median_net_edge:.4f}" if snapshot.median_net_edge is not None else "n/a"
    return (
        f"DAILY {snapshot.date} fills={snapshot.fills} "
        f"cash={snapshot.cash:.4f} equity={snapshot.equity:.4f} "
        f"pnl={snapshot.pnl:+.4f} locked_edge={snapshot.locked_edge:+.4f} "
        f"win_rate={win_txt} open={snapshot.open_count}/{config.max_concurrent_open} "
        f"exposure={snapshot.open_exposure:.4f} booked_notional={snapshot.booked_notional:.4f} "
        f"below_floor_n={snapshot.below_floor_n} median_net_edge={median_txt}"
    )
