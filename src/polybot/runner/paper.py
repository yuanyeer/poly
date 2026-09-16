from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from polybot.config import (
    PaperConfig,
    account_booking_paused,
    copy_runtime_enabled,
    whiskas_runtime_enabled,
)
from polybot.copy.metrics import InMemoryMetricsProvider, JsonFileMetricsProvider, MetricsProvider
from polybot.copy.monitor import EVENT_STOP_FOLLOW, CopyEvent, CopyMonitor
from polybot.copy.watchlist import Watchlist, load_watchlist
from polybot.ledger.accounts import (
    ARB_MAIN_ID,
    AccountBook,
    drawdown_params,
    open_account_book,
    race_primary_id,
    race_target,
)
from polybot.ledger.store import PaperLedger
from polybot.market.whiskas import normalize_winner
from polybot.strategy.whiskas_inventory import WhiskasInventoryStrategy, whiskas_window
from polybot.market.client import LiveOrderForbidden, PaperMarketClient
from polybot.risk.drawdown import DrawdownDecision, classify_drawdown
from polybot.runner.summary import (
    SessionStats,
    build_daily_snapshot,
    format_daily,
    format_rank_lines,
    format_summary,
    utc_now,
)
from polybot.session import in_trading_window, local_now, session_label
from polybot.strategy import default_strategies
from polybot.strategy.sizer import resize_to_book
from polybot.types import LedgerState, MarketSnapshot, MedianEdgeKind, Opportunity, ScanTarget, ScreenTape

logger = logging.getLogger(__name__)

NowFn = Callable[[], datetime]


def _copy_event_names(events: list[CopyEvent] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not events:
        return ()
    names: list[str] = []
    for item in events:
        names.append(item.name if isinstance(item, CopyEvent) else str(item))
    return tuple(names)


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
    copy_events: tuple[str, ...] = ()
    rank_lines: tuple[str, ...] = ()
    winner: str | None = None


@dataclass
class SessionWatch:
    """Wall-clock booked=0 streak + live peak/drawdown. 24h trading.

    TRIGGER idle_zero_fill after continuous wall-clock idle_zero_fill_hours
    (default 24) of booked=0. Not session-window accrual.
    REVIEW (finance freeze): peak DD ≥ 10% OR equity < 900 — keep scanning.
    HARD: peak DD ≥ 25% OR equity < 750 — SKIP that ledger. Per-ledger.
    """

    peak_equity: Decimal = Decimal("0")
    zero_book_cycles: int = 0
    zero_fill_sessions: int = 0
    zero_since: datetime | None = None

    def observe_equity(self, equity: Decimal) -> Decimal:
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity <= 0:
            return Decimal("0")
        return (self.peak_equity - equity) / self.peak_equity

    def idle_hours(self, now: datetime) -> float:
        if self.zero_since is None:
            return 0.0
        current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        start = self.zero_since if self.zero_since.tzinfo else self.zero_since.replace(tzinfo=timezone.utc)
        return max(0.0, (current - start).total_seconds() / 3600.0)

    def note_booked(self, booked: int, now: datetime, idle_hours: float) -> bool:
        """Record wall-clock booked=0. Returns True when continuous idle hours trip."""
        current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        if booked > 0:
            self.zero_book_cycles = 0
            self.zero_fill_sessions = 0
            self.zero_since = None
            return False
        self.zero_book_cycles += 1
        if self.zero_since is None:
            self.zero_since = current
            return False
        tripped = self.idle_hours(current) >= float(idle_hours)
        if tripped:
            self.zero_fill_sessions = 1
        return tripped


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
        self.book: AccountBook = open_account_book(config, arb_ledger=ledger)
        self.ledger = self.book.arb().ledger
        self.market = market or PaperMarketClient(config)
        self.risk = self.book.arb().risk
        self.strategies = default_strategies()
        self.whiskas_strategy = WhiskasInventoryStrategy() if whiskas_runtime_enabled(config.whiskas) else None
        self.race_id = race_primary_id(config)
        self.account_stats: dict[str, SessionStats] = {
            account.account_id: SessionStats() for account in self.book.accounts
        }
        self.watches: dict[str, SessionWatch] = {
            account.account_id: SessionWatch() for account in self.book.accounts
        }
        self.stats = self.account_stats[ARB_MAIN_ID]
        self.watch = self.watches[ARB_MAIN_ID]
        self._day_key: str | None = None
        self._now = now_fn or utc_now
        self.copy_watchlist: Watchlist | None = None
        self.copy_monitor: CopyMonitor | None = None
        if copy_runtime_enabled(config.copy):
            provider: MetricsProvider
            if config.copy.metrics_stub is not None:
                provider = JsonFileMetricsProvider(config.copy.metrics_stub)
            else:
                provider = InMemoryMetricsProvider()
            self.copy_watchlist = load_watchlist(config.copy)
            self.copy_monitor = CopyMonitor(config.copy, self.copy_watchlist, provider)

    def status_line(self, state: LedgerState, account_id: str = ARB_MAIN_ID) -> str:
        from polybot.runner.summary import distance_field

        goal = race_target(self.config, account_id)
        progress = (state.equity / goal) * Decimal("100") if goal else Decimal("0")
        target_txt = f"target={goal} ({progress:.2f}%)" if goal is not None else "target=n/a"
        cap = None
        if self.config.whiskas and account_id == self.config.whiskas.account_id:
            cap = self.config.whiskas.per_round_notional_cap
        cap_txt = f" round_cap={cap:.4f}" if cap is not None else ""
        return (
            f"account={account_id} cash={state.cash:.4f} locked={state.locked_payout:.4f} "
            f"equity={state.equity:.4f} {target_txt}{cap_txt} "
            f"{distance_field(state, goal)} "
            f"open={state.open_count}/{self.config.max_concurrent_open} "
            f"exposure={state.open_exposure:.4f}"
        )

    def _account_dd(self, account_id: str, state: LedgerState) -> DrawdownDecision:
        watch = self.watches[account_id]
        watch.observe_equity(state.equity)
        review_pct, halt_pct, review_floor, halt_floor = drawdown_params(self.config, account_id)
        return classify_drawdown(
            equity=state.equity,
            peak=watch.peak_equity,
            review_pct=review_pct,
            halt_pct=halt_pct,
            review_floor=review_floor,
            halt_floor=halt_floor,
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
        day_key = utc.date().isoformat()
        for stats in self.account_stats.values():
            stats.reset_daily_edges(day_key)
        state = self.ledger.state()
        dd = self._account_dd(ARB_MAIN_ID, state)
        messages = [self.status_line(state, ARB_MAIN_ID)]
        self._log_drawdown(messages, state, dd, account_id=ARB_MAIN_ID)
        whiskas_account = self.book.whiskas()
        if whiskas_account is not None:
            whiskas_state = whiskas_account.state()
            whiskas_dd = self._account_dd(whiskas_account.account_id, whiskas_state)
            messages.append(self.status_line(whiskas_state, whiskas_account.account_id))
            self._log_drawdown(messages, whiskas_state, whiskas_dd, account_id=whiskas_account.account_id)
            if whiskas_dd.halt and not whiskas_account.paused:
                whiskas_account.paused = True
                messages.append(
                    f"SKIP drawdown_halt account={whiskas_account.account_id} "
                    f"(HARD; whiskas-inv only)"
                )
        for account in self.book.copy_accounts():
            other = account.state()
            other_dd = self._account_dd(account.account_id, other)
            messages.append(self.status_line(other, account.account_id))
            self._log_drawdown(messages, other, other_dd, account_id=account.account_id)
            if other_dd.halt and not account.paused:
                account.paused = True
                messages.append(
                    f"SKIP drawdown_halt account={account.account_id} "
                    f"(HARD; that copy ledger only)"
                )
        copy_events = self._observe_copy(messages)
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
            triggered = self.watch.note_booked(0, now, self.config.idle_zero_fill_hours)
            reason = "session_closed"
            local_txt = local.strftime("%Y-%m-%d %H:%M")
            line = f"SKIP {reason} tz={self.config.session_timezone} local={local_txt} window={window} (no scan)"
            messages.append(line)
            logger.info(line)
            if triggered:
                trig = (
                    f"TRIGGER idle_zero_fill hours={self.watch.idle_hours(now):.2f} "
                    f"(wall-clock continuous booked=0; threshold={self.config.idle_zero_fill_hours})"
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
                copy_events=copy_events,
            )

        if dd.halt and not whiskas_runtime_enabled(self.config.whiskas):
            self.watch.note_booked(0, now, self.config.idle_zero_fill_hours)
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
                copy_events=copy_events,
            )

        targets = self._targets()
        screen = self._consume_screen_tape()
        diag_kind = self._ingest_screen_diagnostics(screen)
        booked = 0
        skipped = 0
        candidates = 0
        scanned = 0
        rejected_edges = 0
        rejected_risk = 0
        snapshot_failures = 0
        for target in targets:
            if (
                not self.book.arb().paused
                and not dd.halt
                and state.open_count + booked >= self.config.max_concurrent_open
            ):
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
            if diag_kind != "raw":
                self._record_market_edge(snapshot, count_below=screen is None)
            found = self._scan_market(snapshot)
            if not found:
                rejected_edges += 1
                skipped += 1
                self._log_rejected_edges(snapshot)
                continue
            for opportunity in found:
                candidates += 1
                if self.book.arb().paused or dd.halt:
                    skipped += 1
                    rejected_risk += 1
                    logger.info("SKIP book account=%s paused_or_halted", ARB_MAIN_ID)
                    continue
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
        if screen is not None and diag_kind == "walked":
            self._walk_below_floor_diagnostics(screen)
            if not self.stats.net_edges and screen.raw_edges:
                self.stats.record_diagnostic_edges(screen.raw_edges, kind="raw")
        if screen is None:
            self.stats.screened_n += scanned
            if self.stats.median_net_edge_kind is None:
                self.stats.median_net_edge_kind = "walked"
        arb_booked, arb_scanned, arb_candidates = booked, scanned, candidates
        whiskas_booked, whiskas_scanned, whiskas_candidates, whiskas_skip, whiskas_rej = self._run_whiskas(
            now, messages
        )
        booked += whiskas_booked
        scanned += whiskas_scanned
        candidates += whiskas_candidates
        skipped += whiskas_skip
        rejected_risk += whiskas_rej
        self.stats.record_cycle(
            scanned=arb_scanned,
            candidates=arb_candidates,
            booked=arb_booked,
            rejected_edges=rejected_edges,
            rejected_risk=rejected_risk - whiskas_rej,
            snapshot_failures=snapshot_failures,
        )
        if whiskas_account is not None:
            self.account_stats[whiskas_account.account_id].record_cycle(
                scanned=whiskas_scanned,
                candidates=whiskas_candidates,
                booked=whiskas_booked,
                rejected_edges=0,
                rejected_risk=whiskas_rej,
                snapshot_failures=0,
            )
        if whiskas_account is not None:
            idle_watch = self.watches[whiskas_account.account_id]
            idle_booked = whiskas_booked
            triggered = idle_watch.note_booked(idle_booked, now, self.config.idle_zero_fill_hours)
        else:
            idle_watch = self.watch
            idle_booked = booked
            triggered = idle_watch.note_booked(idle_booked, now, self.config.idle_zero_fill_hours)
        if idle_booked == 0:
            idle = (
                f"IDLE booked=0 streak_cycles={idle_watch.zero_book_cycles} "
                f"wall_clock_hours={idle_watch.idle_hours(now):.2f} "
                f"threshold={self.config.idle_zero_fill_hours}"
            )
            messages.append(idle)
            logger.info(idle)
        if triggered:
            trig = (
                f"TRIGGER idle_zero_fill hours={idle_watch.idle_hours(now):.2f} "
                f"(wall-clock continuous booked=0; threshold={self.config.idle_zero_fill_hours})"
            )
            messages.append(trig)
            logger.info(trig)
        if whiskas_account is not None:
            state = whiskas_account.state()
            after = self._account_dd(whiskas_account.account_id, state)
        else:
            state = self.ledger.state()
            self.watch.observe_equity(state.equity)
            after = self._account_dd(ARB_MAIN_ID, state)
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
            skipped_reason="drawdown_halt" if after.halt and whiskas_account is None else (
                "drawdown_halt" if whiskas_account is not None and after.halt else ""
            ),
            in_session=True,
            now=now,
            drawdown=after,
            copy_events=copy_events,
        )

    def _run_whiskas(self, now: datetime, messages: list[str]) -> tuple[int, int, int, int, int]:
        """Book inventory clips on whiskas-inv. Never writes arb-main. No sells."""
        account = self.book.whiskas()
        if account is None:
            return 0, 0, 0, 0, 0
        if (
            not whiskas_runtime_enabled(self.config.whiskas)
            or self.whiskas_strategy is None
            or self.config.whiskas is None
            or account.paused
            or account_booking_paused(self.config, account.account_id)
        ):
            reason = "disabled" if not whiskas_runtime_enabled(self.config.whiskas) else "paused"
            messages.append(f"SKIP whiskas booking account={account.account_id} {reason}")
            return 0, 0, 0, 1, 0
        booked = 0
        scanned = 0
        candidates = 0
        skipped = 0
        rejected = 0
        for target in self._whiskas_targets():
            snapshot = self._snapshot(target)
            scanned += 1
            if snapshot is None:
                skipped += 1
                continue
            redeemed = self._maybe_redeem_whiskas(account, snapshot, now, messages)
            if redeemed:
                continue
            spent = account.ledger.round_notional(snapshot.condition_id)
            found = self.whiskas_strategy.scan(
                snapshot, self.config, now=now, round_notional=spent
            )
            if not found:
                open_ok, reason = whiskas_window(snapshot, now, self.config.whiskas)
                if not open_ok:
                    logger.info("SKIP whiskas %s %s", reason, snapshot.question[:60])
                skipped += 1
                continue
            for opportunity in found:
                if any(leg.side == "SELL" for leg in opportunity.legs):
                    rejected += 1
                    logger.error("REJECT whiskas sell forbidden")
                    continue
                candidates += 1
                decision = account.risk.evaluate(opportunity, account.state())
                if not decision.allowed:
                    rejected += 1
                    logger.info("REJECT whiskas risk: %s", decision.reason)
                    continue
                fill = account.ledger.append_fill(opportunity, ts=now.isoformat())
                booked += 1
                self.watches[account.account_id].observe_equity(account.state().equity)
                line = (
                    f"BOOK whiskas_inventory {snapshot.question[:80]} "
                    f"size={opportunity.size} notional={opportunity.notional:.4f} "
                    f"legs={len(opportunity.legs)} hash={fill.hash[:12]}"
                )
                messages.append(line)
                logger.info(line)
        return booked, scanned, candidates, skipped, rejected

    def _whiskas_targets(self) -> list[ScanTarget]:
        if hasattr(self.market, "list_whiskas_targets"):
            return list(self.market.list_whiskas_targets())
        return []

    def _maybe_redeem_whiskas(self, account, snapshot: MarketSnapshot, now: datetime, messages: list[str]) -> bool:
        if self.config.whiskas is None:
            return False
        shares = account.ledger.inventory_shares(snapshot.condition_id)
        if shares["Up"] <= 0 and shares["Down"] <= 0:
            return False
        ended = False
        if snapshot.round_end is not None:
            end = snapshot.round_end if snapshot.round_end.tzinfo else snapshot.round_end.replace(tzinfo=timezone.utc)
            current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            ended = current >= end
        if not snapshot.resolved and not ended:
            return False
        winner = normalize_winner(snapshot.winner, self.config.whiskas)
        if winner is None:
            logger.info("WAIT whiskas settlement event=%s (no winner yet)", snapshot.condition_id)
            return False
        credit = shares.get(winner, Decimal("0"))
        fill = account.ledger.append_redemption(
            event_id=snapshot.condition_id,
            winner=winner,
            cash_credit=credit,
            question=snapshot.question,
            notes=f"redeem winner={winner}",
            ts=now.isoformat(),
        )
        line = (
            f"REDEEM whiskas_inventory {snapshot.question[:80]} winner={winner} "
            f"credit={credit:.4f} hash={fill.hash[:12]}"
        )
        messages.append(line)
        logger.info(line)
        return True

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
            copy_events=(),
        )

    def _log_drawdown(
        self,
        messages: list[str],
        state: LedgerState,
        dd: DrawdownDecision,
        *,
        account_id: str = ARB_MAIN_ID,
    ) -> None:
        watch = self.watches[account_id]
        review_pct, halt_pct, review_floor, halt_floor = drawdown_params(self.config, account_id)
        if dd.review:
            line = dd.review_line(
                peak=watch.peak_equity,
                equity=state.equity,
                review_pct=review_pct,
                review_floor=review_floor,
            )
            line = f"{line} account={account_id}"
            messages.append(line)
            logger.warning(line)
        if dd.halt:
            line = dd.halt_line(
                peak=watch.peak_equity,
                equity=state.equity,
                halt_pct=halt_pct,
                halt_floor=halt_floor,
            )
            line = f"{line} account={account_id}"
            messages.append(line)
            logger.error(line)

    def _daily_snapshot(self, state: LedgerState, now: datetime, *, stats: SessionStats | None = None):
        tape = stats or self.stats
        return build_daily_snapshot(
            state,
            now,
            screened_n=tape.screened_n,
            below_floor_n=tape.below_floor_n,
            median_net_edge=tape.median_net_edge,
            median_net_edge_kind=tape.median_net_edge_kind,
            best_binary=tape.best_binary,
            best_set=tape.best_set,
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
        copy_events: list[CopyEvent] | tuple[str, ...] | None = None,
    ) -> CycleReport:
        messages.append(self.status_line(state, ARB_MAIN_ID))
        summary = ""
        daily = ""
        daily_snap = self._daily_snapshot(state, now, stats=self.stats)
        day_key = daily_snap.date
        if self._day_key is None:
            self._day_key = day_key
        elif day_key != self._day_key:
            logger.info("DAILY close %s — rolling to %s", self._day_key, day_key)
            self._day_key = day_key
        rank_rows: list[tuple[int, str, LedgerState]] = []
        emit = self.stats.cycles % self.config.summary_every_cycles == 0 or skipped_reason
        for rank, account, acc_state in self.book.ranked():
            rank_rows.append((rank, account.account_id, acc_state))
            acc_stats = self.account_stats[account.account_id]
            acc_dd = self._account_dd(account.account_id, acc_state)
            goal = race_target(self.config, account.account_id)
            cap = None
            if self.config.whiskas and account.account_id == self.config.whiskas.account_id:
                cap = self.config.whiskas.per_round_notional_cap
            acc_summary = format_summary(
                "SUMMARY",
                self.config,
                acc_state,
                acc_stats,
                drawdown=acc_dd.drawdown,
                drawdown_review=acc_dd.review,
                drawdown_halt=acc_dd.halt,
                account_id=account.account_id,
                paused=account.paused,
                target_balance=goal,
                round_cap=cap,
            )
            acc_daily = format_daily(
                self._daily_snapshot(acc_state, now, stats=acc_stats),
                self.config,
                drawdown=acc_dd.drawdown,
                drawdown_review=acc_dd.review,
                drawdown_halt=acc_dd.halt,
                account_id=account.account_id,
                paused=account.paused,
                target_balance=goal,
                round_cap=cap,
            )
            if account.account_id == self.race_id:
                summary = acc_summary
                daily = acc_daily
            if emit:
                messages.append(acc_summary)
                messages.append(acc_daily)
                logger.info(acc_summary)
                logger.info(acc_daily)
        target_map = {account.account_id: race_target(self.config, account.account_id) for account in self.book.accounts}
        rank_lines = tuple(format_rank_lines(rank_rows, self.config.target_balance, targets=target_map))
        winner = self.book.winner(self.config.target_balance, targets=target_map)
        if emit:
            for line in rank_lines:
                messages.append(line)
                logger.info(line)
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
            copy_events=_copy_event_names(copy_events),
            rank_lines=rank_lines,
            winner=winner.account_id if winner is not None else None,
        )

    def _observe_copy(self, messages: list[str]) -> list[CopyEvent]:
        if self.copy_monitor is None:
            return []
        events = self.copy_monitor.poll()
        for event in events:
            messages.append(event.line())
            if event.name == EVENT_STOP_FOLLOW:
                account = self.book.copy_for(event.leader_id)
                if account is not None:
                    account.paused = True
                    messages.append(
                        f"PAUSE account={account.account_id} leader={event.leader_id} "
                        f"(other copy ledgers keep running)"
                    )
        return events

    def _record_market_edge(self, snapshot: MarketSnapshot, *, count_below: bool = True) -> None:
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
        self.stats.record_net_edge(best[0], best[1], count_below=count_below)
        if self.stats.median_net_edge_kind is None:
            self.stats.median_net_edge_kind = "walked"

    def _targets(self) -> list[ScanTarget]:
        if hasattr(self.market, "list_scan_targets"):
            return list(self.market.list_scan_targets())
        return [
            ScanTarget(kind="binary", event_id=cid, question=cid, condition_ids=(cid,))
            for cid in self.market.list_condition_ids()
        ]

    def _consume_screen_tape(self) -> ScreenTape | None:
        tape = getattr(self.market, "last_screen", None)
        return tape if isinstance(tape, ScreenTape) else None

    def _ingest_screen_diagnostics(self, tape: ScreenTape | None) -> MedianEdgeKind | None:
        """Record SCREEN counters. Booking skip stays on walk_targets only.

        Prefer a complete walked diagnostic sample when every below-floor
        book is cheap enough to walk (`N <= diag_walk_limit`). Otherwise use
        the already-fetched raw SCREEN edges and label kind=raw.
        """
        if tape is None:
            return None
        cheap_below = len(tape.below_floor_targets) <= self.config.diag_walk_limit
        kind: MedianEdgeKind = "walked" if cheap_below else "raw"
        self.stats.note_screen(
            screened_n=tape.screened_n,
            below_floor_n=tape.below_floor_n,
            best_binary=tape.best_binary,
            best_set=tape.best_set,
            kind=kind,
        )
        if kind == "raw":
            self.stats.record_diagnostic_edges(tape.raw_edges, kind="raw")
        return kind

    def _walk_below_floor_diagnostics(self, tape: ScreenTape) -> None:
        """Depth-walk below-floor markets for SUMMARY only. Never books."""
        already = {item.event_id for item in tape.walk_targets}
        for target in tape.below_floor_targets:
            if target.event_id in already:
                continue
            snapshot = self._snapshot(target)
            if snapshot is None:
                continue
            self._record_market_edge(snapshot, count_below=False)

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
        if self.book.arb().paused:
            logger.info("SKIP book account=%s (booking paused; read-only scan)", ARB_MAIN_ID)
            return None
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
