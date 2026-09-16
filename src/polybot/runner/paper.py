from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal

from polybot.config import PaperConfig
from polybot.ledger.store import PaperLedger
from polybot.market.client import LiveOrderForbidden, PaperMarketClient
from polybot.risk.gates import RiskEngine
from polybot.runner.summary import SessionStats, build_daily_snapshot, format_daily, format_summary
from polybot.strategy import default_strategies
from polybot.strategy.sizer import resize_to_book
from polybot.types import LedgerState, MarketSnapshot, Opportunity, ScanTarget

logger = logging.getLogger(__name__)


@dataclass
class CycleReport:
    scanned: int
    candidates: int
    booked: int
    skipped: int
    rejected_edges: int
    rejected_risk: int
    state: LedgerState
    messages: list[str]
    summary: str = ""
    daily_summary: str = ""


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
        self.stats = SessionStats()
        self._day_key: str | None = None

    def status_line(self, state: LedgerState) -> str:
        progress = (state.equity / self.config.target_balance) * Decimal("100")
        return (
            f"cash={state.cash:.4f} locked={state.locked_payout:.4f} "
            f"equity={state.equity:.4f} target={self.config.target_balance} "
            f"({progress:.2f}%) open={state.open_count}/{self.config.max_concurrent_open} "
            f"exposure={state.open_exposure:.4f}"
        )

    def run_forever(self, max_loops: int | None = None, once: bool = False) -> CycleReport:
        loops = 0
        last: CycleReport | None = None
        try:
            while True:
                last = self.run_cycle()
                loops += 1
                if once or (max_loops is not None and loops >= max_loops):
                    return last
                time.sleep(max(0.0, self.config.poll_interval_seconds))
        except KeyboardInterrupt:
            logger.info("paper loop stopped by operator")
            if last is None:
                state = self.ledger.state()
                last = CycleReport(
                    scanned=0,
                    candidates=0,
                    booked=0,
                    skipped=0,
                    rejected_edges=0,
                    rejected_risk=0,
                    state=state,
                    messages=["interrupted before first cycle"],
                    summary=format_summary("SUMMARY", self.config, state, self.stats),
                    daily_summary=format_daily(build_daily_snapshot(state), self.config),
                )
            return last

    def run_cycle(self) -> CycleReport:
        state = self.ledger.state()
        messages = [self.status_line(state)]
        targets = self._targets()
        booked = 0
        skipped = 0
        candidates = 0
        scanned = 0
        rejected_edges = 0
        rejected_risk = 0
        snapshot_failures = 0
        for target in targets:
            if state.open_count + booked >= self.config.max_concurrent_open:
                messages.append("hit concurrent-open cap; stopping this cycle")
                logger.info("CYCLE stop: concurrent-open cap")
                break
            snapshot = self._snapshot(target)
            scanned += 1
            if snapshot is None:
                skipped += 1
                snapshot_failures += 1
                logger.info("SCAN miss %s %s", target.kind, target.question[:80])
                continue
            logger.info(
                "SCAN %s outcomes=%s %s",
                snapshot.kind,
                len(snapshot.outcomes),
                snapshot.question[:80],
            )
            found = self._scan_market(snapshot)
            if not found:
                rejected_edges += 1
                skipped += 1
                self._log_rejected_edges(snapshot)
                continue
            for opportunity in found:
                candidates += 1
                accepted = self._maybe_book(snapshot, opportunity)
                if accepted:
                    booked += 1
                    state = self.ledger.state()
                    line = (
                        f"BOOK {accepted.strategy} {snapshot.question[:80]} "
                        f"edge={accepted.edge:.4f} size={accepted.size} notional={accepted.notional:.4f}"
                    )
                    messages.append(line)
                    logger.info(line)
                else:
                    skipped += 1
                    rejected_risk += 1
        self.stats.record_cycle(
            scanned=scanned,
            candidates=candidates,
            booked=booked,
            rejected_edges=rejected_edges,
            rejected_risk=rejected_risk,
            snapshot_failures=snapshot_failures,
        )
        state = self.ledger.state()
        messages.append(self.status_line(state))
        summary = format_summary("SUMMARY", self.config, state, self.stats)
        daily_snap = build_daily_snapshot(state)
        daily = format_daily(daily_snap, self.config)
        day_key = daily_snap.date
        if self._day_key is None:
            self._day_key = day_key
        elif day_key != self._day_key:
            logger.info("DAILY close %s — rolling to %s", self._day_key, day_key)
            self._day_key = day_key
        if self.stats.cycles % self.config.summary_every_cycles == 0:
            messages.append(summary)
            messages.append(daily)
            logger.info(summary)
            logger.info(daily)
        return CycleReport(
            scanned=scanned,
            candidates=candidates,
            booked=booked,
            skipped=skipped,
            rejected_edges=rejected_edges,
            rejected_risk=rejected_risk,
            state=state,
            messages=messages,
            summary=summary,
            daily_summary=daily,
        )

    def _targets(self) -> list[ScanTarget]:
        if hasattr(self.market, "list_scan_targets"):
            return list(self.market.list_scan_targets())
        return [
            ScanTarget(kind="binary", event_id=cid, question=cid, condition_ids=(cid,))
            for cid in self.market.list_condition_ids()
        ]

    def _snapshot(self, target: ScanTarget) -> MarketSnapshot | None:
        if hasattr(self.market, "snapshot_target"):
            return self.market.snapshot_target(target)
        return self.market.snapshot(target.condition_ids[0] if target.condition_ids else target.event_id)

    def _scan_market(self, snapshot: MarketSnapshot) -> list[Opportunity]:
        found: list[Opportunity] = []
        for strategy in self.strategies:
            try:
                found.extend(strategy.scan(snapshot, self.config))
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s failed on %s: %s", strategy.name, snapshot.condition_id, exc)
        found.sort(key=lambda item: item.edge, reverse=True)
        return found

    def _log_rejected_edges(self, snapshot: MarketSnapshot) -> None:
        for strategy in self.strategies:
            preview = getattr(strategy, "preview_edge", None)
            if preview is None:
                continue
            edge = preview(snapshot, self.config)
            if edge is None:
                continue
            floor = (
                self.config.maker_edge_floor
                if strategy.name == "maker_spread"
                else self.config.taker_edge_floor
            )
            logger.info(
                "REJECT %s %s edge=%s floor=%s",
                strategy.name,
                snapshot.question[:60],
                f"{edge:.4f}",
                floor,
            )

    def _maybe_book(self, snapshot: MarketSnapshot, opportunity: Opportunity) -> Opportunity | None:
        state = self.ledger.state()
        decision = self.risk.evaluate(opportunity, state)
        working = opportunity
        if not decision.allowed:
            cap = self.risk.cap_size(opportunity, state)
            min_size = max(self.config.min_fill_size, snapshot.min_order_size)
            if cap < min_size:
                logger.info("REJECT risk %s: %s", opportunity.strategy, decision.reason)
                return None
            resized = resize_to_book(snapshot, opportunity, cap)
            if resized is None:
                logger.info("REJECT risk %s: resize failed (%s)", opportunity.strategy, decision.reason)
                return None
            floor = (
                self.config.maker_edge_floor
                if resized.strategy == "maker_spread"
                else self.config.taker_edge_floor
            )
            if resized.edge < floor:
                logger.info(
                    "REJECT edge %s resized edge=%s < %s",
                    opportunity.strategy,
                    resized.edge,
                    floor,
                )
                return None
            decision = self.risk.evaluate(resized, state)
            if not decision.allowed:
                logger.info("REJECT risk %s: %s", opportunity.strategy, decision.reason)
                return None
            working = resized
        fill = self.ledger.append_fill(working)
        logger.info("paper fill %s hash=%s", fill.fill_id, fill.hash[:12])
        return working
