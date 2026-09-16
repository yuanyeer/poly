from __future__ import annotations

import logging
from dataclasses import dataclass

from polybot.config import CopyConfig
from polybot.copy.metrics import LeaderMetrics, MetricsProvider
from polybot.copy.rescan import LoggingRescanHook, RescanCriteria, RescanHook
from polybot.copy.watchlist import Watchlist

logger = logging.getLogger(__name__)

EVENT_STOP_FOLLOW = "STOP_FOLLOW"
EVENT_RESCAN_NEEDED = "RESCAN_NEEDED"


@dataclass(frozen=True)
class CopyEvent:
    name: str
    leader_id: str
    reason: str
    metrics: LeaderMetrics | None = None

    def line(self) -> str:
        extra = ""
        if self.metrics is not None:
            extra = (
                f" peak_dd={self.metrics.peak_dd} path_dd={self.metrics.path_dd} "
                f"month_pnl={self.metrics.month_pnl}"
            )
        return f"{self.name} leader={self.leader_id} reason={self.reason}{extra}"


def stop_follow_reason(metrics: LeaderMetrics, copy: CopyConfig) -> str | None:
    """Return the first trip reason, or None if the leader stays followable."""
    if metrics.peak_dd >= copy.stop_peak_dd:
        return f"peak_dd {metrics.peak_dd} >= {copy.stop_peak_dd}"
    if metrics.path_dd >= copy.stop_path_dd:
        return f"path_dd {metrics.path_dd} >= {copy.stop_path_dd}"
    if metrics.month_pnl < copy.month_pnl_below:
        return f"month_pnl {metrics.month_pnl} < {copy.month_pnl_below}"
    return None


class CopyMonitor:
    """Mark leaders inactive when stop-follow trips and request a rescan."""

    def __init__(
        self,
        copy: CopyConfig,
        watchlist: Watchlist,
        provider: MetricsProvider,
        rescan: RescanHook | None = None,
    ) -> None:
        self.copy = copy
        self.watchlist = watchlist
        self.provider = provider
        self.rescan = rescan or LoggingRescanHook()

    def poll(self) -> list[CopyEvent]:
        events: list[CopyEvent] = []
        for leader in list(self.watchlist.active_leaders()):
            metrics = self.provider.snapshot(leader.id)
            if metrics is None:
                continue
            reason = stop_follow_reason(metrics, self.copy)
            if reason is None:
                continue
            self.watchlist.mark_inactive(leader.id)
            stop = CopyEvent(EVENT_STOP_FOLLOW, leader.id, reason, metrics)
            rescan = CopyEvent(EVENT_RESCAN_NEEDED, leader.id, reason, metrics)
            events.extend((stop, rescan))
            logger.warning(stop.line())
            logger.info(rescan.line())
            self.rescan.request_candidates(RescanCriteria.from_config(self.copy))
        return events
