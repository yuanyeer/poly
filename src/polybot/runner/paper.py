from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal

from polybot.config import PaperConfig
from polybot.ledger.store import PaperLedger
from polybot.market.client import LiveOrderForbidden, PaperMarketClient
from polybot.risk.gates import RiskEngine
from polybot.strategy import default_strategies
from polybot.strategy.sizer import resize_to_book
from polybot.types import LedgerState, MarketSnapshot, Opportunity

logger = logging.getLogger(__name__)


@dataclass
class CycleReport:
    scanned: int
    candidates: int
    booked: int
    skipped: int
    state: LedgerState
    messages: list[str]


class PaperRunner:
    def __init__(
        self,
        config: PaperConfig,
        ledger: PaperLedger | None = None,
        market: PaperMarketClient | None = None,
    ) -> None:
        if config.mode != "paper":
            raise LiveOrderForbidden("runner only accepts paper mode")
        self.config = config
        self.ledger = ledger or PaperLedger(config.ledger_path, config.starting_balance)
        self.market = market or PaperMarketClient(config)
        self.risk = RiskEngine(config)
        self.strategies = default_strategies()

    def status_line(self, state: LedgerState) -> str:
        progress = (state.equity / self.config.target_balance) * Decimal("100")
        return (
            f"cash={state.cash:.4f} locked={state.locked_payout:.4f} "
            f"equity={state.equity:.4f} target={self.config.target_balance} "
            f"({progress:.2f}%) open={state.open_count}/{self.config.max_concurrent_open}"
        )

    def run_forever(self, max_loops: int | None = None, once: bool = False) -> CycleReport:
        loops = 0
        last: CycleReport | None = None
        while True:
            last = self.run_cycle()
            loops += 1
            if once or (max_loops is not None and loops >= max_loops):
                return last
            time.sleep(self.config.poll_interval_seconds)

    def run_cycle(self) -> CycleReport:
        state = self.ledger.state()
        messages = [self.status_line(state)]
        condition_ids = self.market.list_condition_ids()
        booked = 0
        skipped = 0
        candidates = 0
        scanned = 0
        for condition_id in condition_ids:
            if state.open_count + booked >= self.config.max_concurrent_open:
                messages.append("hit concurrent-open cap; stopping this cycle")
                break
            snapshot = self.market.snapshot(condition_id)
            scanned += 1
            if snapshot is None:
                skipped += 1
                continue
            for opportunity in self._scan_market(snapshot):
                candidates += 1
                accepted = self._maybe_book(snapshot, opportunity)
                if accepted:
                    booked += 1
                    state = self.ledger.state()
                    messages.append(
                        f"BOOK {opportunity.strategy} {snapshot.question[:80]} "
                        f"edge={accepted.edge:.4f} size={accepted.size} notional={accepted.notional:.4f}"
                    )
                else:
                    skipped += 1
        messages.append(self.status_line(self.ledger.state()))
        report = CycleReport(
            scanned=scanned,
            candidates=candidates,
            booked=booked,
            skipped=skipped,
            state=self.ledger.state(),
            messages=messages,
        )
        for line in messages:
            logger.info(line)
        return report

    def _scan_market(self, snapshot: MarketSnapshot) -> list[Opportunity]:
        found: list[Opportunity] = []
        for strategy in self.strategies:
            try:
                found.extend(strategy.scan(snapshot, self.config))
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s failed on %s: %s", strategy.name, snapshot.condition_id, exc)
        found.sort(key=lambda item: item.edge, reverse=True)
        return found

    def _maybe_book(self, snapshot: MarketSnapshot, opportunity: Opportunity) -> Opportunity | None:
        state = self.ledger.state()
        decision = self.risk.evaluate(opportunity, state)
        working = opportunity
        if not decision.allowed:
            cap = self.risk.cap_size(opportunity, state)
            min_size = max(self.config.min_fill_size, snapshot.min_order_size)
            if cap < min_size:
                logger.info("skip %s: %s", opportunity.strategy, decision.reason)
                return None
            resized = resize_to_book(snapshot, opportunity, cap)
            if resized is None:
                logger.info("skip %s: resize failed (%s)", opportunity.strategy, decision.reason)
                return None
            floor = (
                self.config.maker_edge_floor
                if resized.strategy == "maker_spread"
                else self.config.taker_edge_floor
            )
            if resized.edge < floor:
                logger.info("skip %s: resized edge %s < %s", opportunity.strategy, resized.edge, floor)
                return None
            decision = self.risk.evaluate(resized, state)
            if not decision.allowed:
                logger.info("skip %s: %s", opportunity.strategy, decision.reason)
                return None
            working = resized
        fill = self.ledger.append_fill(working)
        logger.info("paper fill %s hash=%s", fill.fill_id, fill.hash[:12])
        return working
