from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from polybot.config import PaperConfig, whiskas_runtime_enabled
from polybot.ledger.store import PaperLedger
from polybot.market.fixture import FixtureMarket, fixture_clock, load_fixture
from polybot.runner.paper import CycleReport, PaperRunner
from polybot.types import LedgerState


@dataclass
class FixtureDryRun:
    booked: int
    redeemed: int
    book_report: CycleReport
    settle_report: CycleReport
    whiskas_path: Path
    arb_path: Path
    whiskas_state: LedgerState
    arb_state: LedgerState


def run_fixture_dryrun(
    config: PaperConfig,
    fixture_path: str | Path,
    *,
    whiskas_ledger: Path | None = None,
    arb_ledger: Path | None = None,
) -> FixtureDryRun:
    """Book a recorded BTC 5m clip, then stub-settle the winner. Paper only."""
    if not whiskas_runtime_enabled(config.whiskas) or config.whiskas is None:
        raise ValueError("whiskas fixture dry-run requires whiskas.enabled")
    raw = load_fixture(fixture_path)
    book_now = fixture_clock(raw, "now")
    settle_now = fixture_clock(raw, "settle_now")
    winner = str(raw.get("winner") or "Up")

    arb_path = arb_ledger or config.ledger_path
    whiskas_path = whiskas_ledger or config.whiskas.ledger_path or Path("data/whiskas-inv.jsonl")
    if config.whiskas.ledger_path != whiskas_path:
        from dataclasses import replace

        config = replace(config, whiskas=replace(config.whiskas, ledger_path=whiskas_path))

    clock = {"now": book_now}
    market = FixtureMarket(raw, resolved=False, winner=None)
    runner = PaperRunner(
        config,
        ledger=PaperLedger(arb_path, config.starting_balance),
        market=market,  # type: ignore[arg-type]
        now_fn=lambda: clock["now"],
    )
    book_report = runner.run_cycle()

    market.resolved = True
    market.winner = winner
    market.whiskas_snap = market.whiskas_snap.__class__(
        **{**market.whiskas_snap.__dict__, "resolved": True, "winner": winner}
    )
    clock["now"] = settle_now
    settle_report = runner.run_cycle()

    whiskas = runner.book.whiskas()
    if whiskas is None:
        raise RuntimeError("whiskas-inv account missing")
    return FixtureDryRun(
        booked=book_report.booked,
        redeemed=sum(1 for fill in whiskas.state().fills if "redeem" in fill.notes),
        book_report=book_report,
        settle_report=settle_report,
        whiskas_path=whiskas.ledger.path,
        arb_path=runner.book.arb().ledger.path,
        whiskas_state=whiskas.state(),
        arb_state=runner.book.arb().state(),
    )


def format_dryrun_proof(result: FixtureDryRun) -> str:
    lines = [
        "=== paper fixture dry-run (NOT live / on-chain) ===",
        f"whiskas ledger: {result.whiskas_path}",
        f"arb-main ledger: {result.arb_path}",
        f"booked={result.booked} redeemed={result.redeemed}",
        f"whiskas cash={result.whiskas_state.cash:.4f} equity={result.whiskas_state.equity:.4f} "
        f"pnl={result.whiskas_state.equity - result.whiskas_state.starting_balance:+.4f}",
        f"arb-main fills={len(result.arb_state.fills)} cash={result.arb_state.cash:.4f} "
        f"(booking paused; must stay at starting {result.arb_state.starting_balance})",
    ]
    for fill in result.whiskas_state.fills:
        sides = ",".join(f"{leg.outcome}:{leg.side}@{leg.price}x{leg.size}" for leg in fill.legs) or "none"
        lines.append(
            f"FILL type_notes={fill.notes} ts={fill.ts} debit={fill.cash_debit} "
            f"credit={fill.cash_credit} legs={sides}"
        )
    return "\n".join(lines)
