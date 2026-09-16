"""Polymarket paper-trading arbitrage bot."""

__version__ = "0.1.0"

PAPER_MODE = "paper"
STARTING_BALANCE_USD = "200"
TARGET_BALANCE_USD = "1000"
TAKER_EDGE_FLOOR = "0.005"
MAKER_EDGE_FLOOR = "0.002"
MAX_TRADE_NOTIONAL_PCT = "0.25"
MAX_SAME_EVENT_EXPOSURE_PCT = "0.40"
MAX_CONCURRENT_OPEN = 3
# Copy-trading observation sleeve / stop-follow (paper-only). Cannot be loosened.
COPY_MAX_SLEEVE_PCT = "0.30"
COPY_STOP_PEAK_DD = "0.05"
COPY_STOP_PATH_DD = "0.05"
# |fill_px − leader_px| + fee/share; cannot be loosened above 1¢.
# Alias matches docs/copy_follow_rules.md (`COPY_MAX_CHASE`).
COPY_MAX_CHASE_SLIPPAGE = "0.01"
COPY_MAX_CHASE = COPY_MAX_CHASE_SLIPPAGE
