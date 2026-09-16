from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from polybot.config import PaperConfig
from polybot.ledger.store import PaperLedger
from polybot.market.client import LiveOrderForbidden, PaperMarketClient
from polybot.risk.drawdown import DrawdownDecision, classify_drawdown
from polybot.risk.gates import RiskEngine
from polybot.runner.summary import SessionStats, build_daily_snapshot, format_daily, format_summary, utc_now
from polybot.session import in_trading_window, local_now, session_label
from polybot.strategy import default_strategies
from polybot.strategy.sizer import resize_to_book
from polybot.types import LedgerState, MarketSnapshot, Opportunity, ScanTarget

logger = logging.getLogger(__name__)

NowFn = Callable[[], datetime]


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
    skipped_reason: str = ""
    in_session: bool = True
    zero_book_cycles: int = 0
    zero_fill_sessions: int = 0
    peak_equity: Decimal = Decimal("0")
    drawdown: Decimal = Decimal("0")
    drawdown_review: bool = False
    drawdown_halt: bool = False


@dataclass
class SessionWatch:
    """Team metric: booked=0 streak is in-window only (not wall-clock 24h).

    Overnight idle (session end → next start) must not increment zero_book_cycles
    or zero_fill_sessions. Drawdown is live ledger equity vs peak every cycle.
    """

    peak_equity: Decimal = Decimal("0")
    zero_book_cycles: int = 0
    zero_fill_sessions: int = 0
    session_booked: int = 0
    session_scanned: bool = False
    in_window_prev: bool = False

    def observe_equity(self, equity: Decimal) -> Decimal:
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity <= 0:
            return Decimal("0")
        return (self.peak_equity - equity) / self.peak_equity

    def note_in_window(self, booked: int, did_scan: bool) -> None:
        if did_scan:
            self.session_scanned = True
            self.session_booked += booked
            if booked == 0:
                self.zero_book_cycles += 1
            else:
                self.zero_book_cycles = 0
                self.zero_fill_sessions = 0
        self.in_window_prev = True

    def note_off_window(self, idle_sessions: int) -> bool:
        """Close a session on in→out transition. Returns True if idle trigger fires."""
        triggered = False
        if self.in_window_prev:
            if self.session_scanned and self.session_booked == 0:
                self.zero_fill_sessions += 1
                triggered = self.zero_fill_sessions >= idle_sessions
            elif self.session_booked > 0:
                self.zero_fill_sessions = 0
            self.session_booked = 0
            self.session_scanned = False
        self.in_window_prev = False
        return triggered


class PaperRunner:
    def __init__(
        self,
        config: PaperConfig,
        ledger: PaperLedger | None = None,
        market: PaperMarketClient | None = None,
        now_fn: NowFn | None = None,
    ) -> None:
        if config.mode != "paper":
            raise LiveOrderForbidden("runner only accepts paper mode")
        self.config = config
        self.ledger = ledger or PaperLedger(config.ledger_path, config.starting_balance)
        self.market = market or PaperMarketClient(config)
        self.risk = RiskEngine(config)
        self.strategies = default_strategies()
        self.stats = SessionStats()
        self.watch = SessionWatch()
        self._day_key: str | None = None
        self._now = now_fn or utc_now

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
                last = self._empty_report(state, "interrupted before first cycle")
            return last

    def run_cycle(self) -> CycleReport:
        now = self._now()
        utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
        self.stats.reset_daily_edges(utc.date().isoformat())
        state = self.ledger.state()
        self.watch.observe_equity(state.equity)
        dd = classify_drawdown(
            equity=state.equity,
            peak=self.watch.peak_equity,
            review_pct=self.config.drawdown_review_pct,
            halt_pct=self.config.drawdown_halt_pct,
            hard_floor=self.config.drawdown_hard_floor_usd,
        )
        messages = [self.status_line(state)]
        self._log_drawdown(messages, state, dd)
        in_window = in_trading_window(
            self.config.session_timezone,
            self.config.session_start,
            self.config.session_end,
            now,
            enabled=self.config.session_enabled,
        )
        window = session_label(
            self.config.session_timezone,
            self.config.session_start,
            self.config.session_end,
        )
        local = local_now(self.config.session_timezone, now)

        if not in_window:
            triggered = self.watch.note_off_window(self.config.idle_zero_fill_sessions)
            reason = "session_closed"
            local_txt = local.strftime("%Y-%m-%d %H:%M")
            line = f"SKIP {reason} tz={self.config.session_timezone} local={local_txt} window={window} (no scan)"
            messages.append(line)
            logger.info(line)
            if triggered:
                trig = (
                    f"TRIGGER idle_zero_fill sessions={self.watch.zero_fill_sessions} "
                    f"(booked=0 counted only inside {window})"
                )
                messages.append(trig)
                logger.info(trig)
            return self._finish_cycle(
                state=state,
                messages=messages,
                scanned=0,
                candidates=0,
                booked=0,
                skipped=1,
                rejected_edges=0,
                rejected_risk=0,
                skipped_reason=reason,
                in_session=False,
                now=now,
                drawdown=dd,
            )

        if dd.halt:
            self.watch.note_in_window(booked=0, did_scan=False)
            return self._finish_cycle(
                state=state,
                messages=messages,
                scanned=0,
                candidates=0,
                booked=0,
                skipped=1,
                rejected_edges=0,
                rejected_risk=0,
                skipped_reason="drawdown_halt",
                in_session=True,
                now=now,
                drawdown=dd,
            )

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
            self._record_market_edge(snapshot)
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
                    self.watch.observe_equity(state.equity)
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
        self.watch.note_in_window(booked=booked, did_scan=True)
        if booked == 0:
            idle = (
                f"IDLE booked=0 streak_cycles={self.watch.zero_book_cycles} "
                f"streak_sessions={self.watch.zero_fill_sessions} window={window}"
            )
            messages.append(idle)
            logger.info(idle)
        state = self.ledger.state()
        self.watch.observe_equity(state.equity)
        after = classify_drawdown(
            equity=state.equity,
            peak=self.watch.peak_equity,
            review_pct=self.config.drawdown_review_pct,
            halt_pct=self.config.drawdown_halt_pct,
            hard_floor=self.config.drawdown_hard_floor_usd,
        )
        if (after.review, after.halt) != (dd.review, dd.halt):
            self._log_drawdown(messages, state, after)
        return self._finish_cycle(
            state=state,
            messages=messages,
            scanned=scanned,
            candidates=candidates,
            booked=booked,
            skipped=skipped,
            rejected_edges=rejected_edges,
            rejected_risk=rejected_risk,
            skipped_reason="drawdown_halt" if after.halt else "",
            in_session=True,
            now=now,
            drawdown=after,
        )

    def _empty_report(self, state: LedgerState, message: str) -> CycleReport:
        now = self._now()
        daily_snap = self._daily_snapshot(state, now)
        return CycleReport(
            scanned=0,
            candidates=0,
            booked=0,
            skipped=0,
            rejected_edges=0,
            rejected_risk=0,
            state=state,
            messages=[message],
            summary=format_summary("SUMMARY", self.config, state, self.stats),
            daily_summary=format_daily(daily_snap, self.config),
            peak_equity=self.watch.peak_equity,
        )

    def _log_drawdown(self, messages: list[str], state: LedgerState, dd: DrawdownDecision) -> None:
        if dd.review:
            line = dd.review_line(
                peak=self.watch.peak_equity,
                equity=state.equity,
                review_pct=self.config.drawdown_review_pct,
                floor=self.config.drawdown_hard_floor_usd,
            )
            messages.append(line)
            logger.warning(line)
        if dd.halt:
            line = dd.halt_line(
                peak=self.watch.peak_equity,
                equity=state.equity,
                halt_pct=self.config.drawdown_halt_pct,
                floor=self.config.drawdown_hard_floor_usd,
            )
            messages.append(line)
            logger.error(line)

    def _daily_snapshot(self, state: LedgerState, now: datetime):
        return build_daily_snapshot(
            state,
            now,
            below_floor_n=self.stats.below_floor_n,
            median_net_edge=self.stats.median_net_edge,
        )

    def _finish_cycle(
        self,
        *,
        state: LedgerState,
        messages: list[str],
        scanned: int,
        candidates: int,
        booked: int,
        skipped: int,
        rejected_edges: int,
        rejected_risk: int,
        skipped_reason: str,
        in_session: bool,
        now: datetime,
        drawdown: DrawdownDecision,
    ) -> CycleReport:
        messages.append(self.status_line(state))
        summary = format_summary(
            "SUMMARY",
            self.config,
            state,
            self.stats,
            drawdown=drawdown.drawdown,
            drawdown_review=drawdown.review,
            drawdown_halt=drawdown.halt,
        )
        daily_snap = self._daily_snapshot(state, now)
        daily = format_daily(
            daily_snap,
            self.config,
            drawdown=drawdown.drawdown,
            drawdown_review=drawdown.review,
            drawdown_halt=drawdown.halt,
        )
        day_key = daily_snap.date
        if self._day_key is None:
            self._day_key = day_key
        elif day_key != self._day_key:
            logger.info("DAILY close %s — rolling to %s", self._day_key, day_key)
            self._day_key = day_key
        if self.stats.cycles % self.config.summary_every_cycles == 0 or skipped_reason:
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
            skipped_reason=skipped_reason,
            in_session=in_session,
            zero_book_cycles=self.watch.zero_book_cycles,
            zero_fill_sessions=self.watch.zero_fill_sessions,
            peak_equity=self.watch.peak_equity,
            drawdown=drawdown.drawdown,
            drawdown_review=drawdown.review,
            drawdown_halt=drawdown.halt,
        )

    def _record_market_edge(self, snapshot: MarketSnapshot) -> None:
        best: tuple[Decimal, Decimal] | None = None
        for strategy in self.strategies:
            preview = getattr(strategy, "preview_edge", None)
            if preview is None:
                continue
            try:
                edge = preview(snapshot, self.config)
            except Exception as exc:  # noqa: BLE001
                logger.debug("preview_edge %s failed: %s", strategy.name, exc)
                continue
            if edge is None or edge <= Decimal("-1"):
                continue
            floor = (
                self.config.maker_edge_floor
                if strategy.name == "maker_spread"
                else self.config.taker_edge_floor
            )
            if best is None or edge > best[0]:
                best = (edge, floor)
        if best is None:
            return
        self.stats.record_net_edge(best[0], best[1])

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
