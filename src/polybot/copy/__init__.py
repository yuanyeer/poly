"""Paper-only copy-trading observation hooks.

No live wallet scraper. No fabricated fills. No CLOB orders.
"""

from polybot.copy.executor import MirrorDecision, MirrorExecutor, MirrorIntent
from polybot.copy.metrics import (
    InMemoryMetricsProvider,
    JsonFileMetricsProvider,
    LeaderMetrics,
    MetricsProvider,
)
from polybot.copy.monitor import (
    EVENT_RESCAN_NEEDED,
    EVENT_STOP_FOLLOW,
    CopyEvent,
    CopyMonitor,
    stop_follow_reason,
)
from polybot.copy.rescan import (
    LoggingRescanHook,
    RescanCriteria,
    RescanHook,
    filter_candidates,
)
from polybot.copy.watchlist import WatchedLeader, Watchlist, load_watchlist

__all__ = [
    "CopyEvent",
    "CopyMonitor",
    "EVENT_RESCAN_NEEDED",
    "EVENT_STOP_FOLLOW",
    "InMemoryMetricsProvider",
    "JsonFileMetricsProvider",
    "LeaderMetrics",
    "LoggingRescanHook",
    "MetricsProvider",
    "MirrorDecision",
    "MirrorExecutor",
    "MirrorIntent",
    "RescanCriteria",
    "RescanHook",
    "WatchedLeader",
    "Watchlist",
    "filter_candidates",
    "load_watchlist",
    "stop_follow_reason",
]
