from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from polybot.config import CopyConfig
from polybot.copy.metrics import LeaderMetrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RescanCriteria:
    """Replacement filter: peak & path dd below the stop line, still profitable."""

    max_peak_dd: Decimal
    max_path_dd: Decimal
    require_profitable: bool = True

    @classmethod
    def from_config(cls, copy: CopyConfig) -> RescanCriteria:
        return cls(
            max_peak_dd=copy.stop_peak_dd,
            max_path_dd=copy.stop_path_dd,
            require_profitable=True,
        )


class RescanHook(ABC):
    """Callback that requests new candidates. Live scanner is not implemented."""

    @abstractmethod
    def request_candidates(self, criteria: RescanCriteria) -> list[LeaderMetrics]:
        """Return candidates matching `criteria`. Default implementations return []."""


class LoggingRescanHook(RescanHook):
    """Logs the rescan request. Does not invent live Polymarket wallet candidates."""

    def request_candidates(self, criteria: RescanCriteria) -> list[LeaderMetrics]:
        logger.info(
            "RESCAN_NEEDED request peak_dd<%s path_dd<%s profitable=%s (no live scanner)",
            criteria.max_peak_dd,
            criteria.max_path_dd,
            criteria.require_profitable,
        )
        return []


def filter_candidates(
    candidates: list[LeaderMetrics],
    criteria: RescanCriteria,
) -> list[LeaderMetrics]:
    """Keep rows with peak_dd < max AND path_dd < max AND (optional) month_pnl > 0."""
    kept: list[LeaderMetrics] = []
    for row in candidates:
        if row.peak_dd >= criteria.max_peak_dd:
            continue
        if row.path_dd >= criteria.max_path_dd:
            continue
        if criteria.require_profitable and row.month_pnl <= 0:
            continue
        kept.append(row)
    return kept
