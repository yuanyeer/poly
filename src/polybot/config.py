from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from polybot import (
    MAKER_EDGE_FLOOR,
    MAX_CONCURRENT_OPEN,
    MAX_SAME_EVENT_EXPOSURE_PCT,
    MAX_TRADE_NOTIONAL_PCT,
    PAPER_MODE,
    STARTING_BALANCE_USD,
    TAKER_EDGE_FLOOR,
    TARGET_BALANCE_USD,
)


class ConfigError(ValueError):
    """Invalid or loosened paper-mode configuration."""


@dataclass(frozen=True)
class PaperConfig:
    mode: str
    starting_balance: Decimal
    target_balance: Decimal
    ledger_path: Path
    clob_host: str
    gamma_host: str
    chain_id: int
    max_markets: int
    poll_interval_seconds: float
    condition_ids: tuple[str, ...]
    taker_edge_floor: Decimal
    maker_edge_floor: Decimal
    max_trade_notional_pct: Decimal
    max_same_event_exposure_pct: Decimal
    max_concurrent_open: int
    max_unhedged_inventory: Decimal
    assume_taker_only_if_fd_missing: bool
    min_fill_size: Decimal
    clob_pages: int = 2
    include_gamma: bool = True
    max_complete_set_events: int = 10
    max_complete_set_outcomes: int = 12
    size_probe_steps: int = 8
    summary_every_cycles: int = 1
    skip_walk_if_raw_below_floor: bool = True
    # FINAL default from poly 负责人: America/New_York 09:00–22:00 local (DST).
    # Not 24h. Outside the window the loop must not scan.
    session_enabled: bool = True
    session_timezone: str = "America/New_York"
    session_start: str = "09:00"
    session_end: str = "22:00"
    # booked=0 streak counts only in-window cycles (not wall-clock 24h).
    # Overnight idle between end and next start does not increment it.
    # ~two in-window sessions of booked=0 trips TRIGGER idle_zero_fill.
    idle_zero_fill_sessions: int = 2
    # Hard halt protection only (default 25%). Does not replace the
    # escalate / strategy-review line (peak DD ≥ 10% OR balance < 180).
    drawdown_halt_pct: Decimal = Decimal("0.25")
    # Escalate floor (ops questions poly金融): balance < 180. Not a substitute
    # for the 10% peak-drawdown escalate line, and not the 25% hard halt.
    drawdown_hard_floor_usd: Decimal = Decimal("180")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _parse_hhmm(value: Any) -> None:
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ConfigError(f"session time must be HH:MM (got {value!r})")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ConfigError(f"session time must be HH:MM (got {value!r})") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ConfigError(f"session time out of range: {value!r}")


def _enforce_session(cfg: PaperConfig) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(cfg.session_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"unknown session timezone: {cfg.session_timezone!r}") from exc
    _parse_hhmm(cfg.session_start)
    _parse_hhmm(cfg.session_end)
    start = tuple(int(x) for x in cfg.session_start.split(":"))
    end = tuple(int(x) for x in cfg.session_end.split(":"))
    if cfg.session_enabled and start >= end:
        raise ConfigError("session window must be a same-day interval (start < end); 24h trading is disabled")


def _require_mode(raw: dict[str, Any]) -> None:
    mode = str(raw.get("mode", "")).strip().lower()
    if mode != PAPER_MODE:
        raise ConfigError(
            f"only mode={PAPER_MODE!r} is supported; live/real-money paths are not implemented"
        )


def _enforce_floors(cfg: PaperConfig) -> None:
    if cfg.starting_balance != _d(STARTING_BALANCE_USD):
        raise ConfigError(
            f"starting_balance must be {STARTING_BALANCE_USD} USD (got {cfg.starting_balance})"
        )
    if cfg.target_balance != _d(TARGET_BALANCE_USD):
        raise ConfigError(
            f"target_balance is a report-only milestone and must stay {TARGET_BALANCE_USD}"
        )
    if cfg.taker_edge_floor < _d(TAKER_EDGE_FLOOR):
        raise ConfigError(f"taker_edge_floor cannot be below {TAKER_EDGE_FLOOR}")
    if cfg.maker_edge_floor < _d(MAKER_EDGE_FLOOR):
        raise ConfigError(f"maker_edge_floor cannot be below {MAKER_EDGE_FLOOR}")
    if cfg.max_trade_notional_pct > _d(MAX_TRADE_NOTIONAL_PCT):
        raise ConfigError(f"max_trade_notional_pct cannot exceed {MAX_TRADE_NOTIONAL_PCT}")
    if cfg.max_same_event_exposure_pct > _d(MAX_SAME_EVENT_EXPOSURE_PCT):
        raise ConfigError(
            f"max_same_event_exposure_pct cannot exceed {MAX_SAME_EVENT_EXPOSURE_PCT}"
        )
    if cfg.max_concurrent_open > MAX_CONCURRENT_OPEN:
        raise ConfigError(f"max_concurrent_open cannot exceed {MAX_CONCURRENT_OPEN}")
    if cfg.max_unhedged_inventory < 0:
        raise ConfigError("max_unhedged_inventory cannot be negative")
    if cfg.idle_zero_fill_sessions < 1:
        raise ConfigError("idle_zero_fill_sessions must be >= 1")
    if cfg.drawdown_halt_pct <= 0 or cfg.drawdown_halt_pct > 1:
        raise ConfigError("drawdown_halt_pct must be in (0, 1]")
    if cfg.drawdown_hard_floor_usd <= 0:
        raise ConfigError("drawdown_hard_floor_usd must be > 0")
    _enforce_session(cfg)


def load_config(path: str | Path | None = None) -> PaperConfig:
    load_dotenv(override=False)
    config_path = Path(path or os.environ.get("POLY_CONFIG") or "config/paper.yaml")
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    _require_mode(raw)

    ledger = raw.get("ledger") or {}
    endpoints = raw.get("endpoints") or {}
    scan = raw.get("scan") or {}
    edge = raw.get("edge") or {}
    risk = raw.get("risk") or {}
    fees = raw.get("fees") or {}
    session = raw.get("session") or {}

    ledger_path = Path(os.environ.get("POLY_LEDGER_PATH") or ledger.get("path") or "data/paper_ledger.jsonl")
    clob_host = os.environ.get("POLY_CLOB_HOST") or endpoints.get("clob_host") or "https://clob.polymarket.com"
    gamma_host = os.environ.get("POLY_GAMMA_HOST") or endpoints.get("gamma_host") or "https://gamma-api.polymarket.com"
    chain_id = int(os.environ.get("POLY_CHAIN_ID") or endpoints.get("chain_id") or 137)

    cfg = PaperConfig(
        mode=PAPER_MODE,
        starting_balance=_d(ledger.get("starting_balance_usd", STARTING_BALANCE_USD)),
        target_balance=_d(ledger.get("target_balance_usd", TARGET_BALANCE_USD)),
        ledger_path=ledger_path,
        clob_host=str(clob_host).rstrip("/"),
        gamma_host=str(gamma_host).rstrip("/"),
        chain_id=chain_id,
        max_markets=int(scan.get("max_markets", 36)),
        poll_interval_seconds=float(scan.get("poll_interval_seconds", 20)),
        condition_ids=tuple(str(x) for x in (scan.get("condition_ids") or []) if x),
        taker_edge_floor=_d(edge.get("taker_floor", TAKER_EDGE_FLOOR)),
        maker_edge_floor=_d(edge.get("maker_floor", MAKER_EDGE_FLOOR)),
        max_trade_notional_pct=_d(risk.get("max_trade_notional_pct", MAX_TRADE_NOTIONAL_PCT)),
        max_same_event_exposure_pct=_d(
            risk.get("max_same_event_exposure_pct", MAX_SAME_EVENT_EXPOSURE_PCT)
        ),
        max_concurrent_open=int(risk.get("max_concurrent_open", MAX_CONCURRENT_OPEN)),
        max_unhedged_inventory=_d(risk.get("max_unhedged_inventory_usd", 0)),
        assume_taker_only_if_fd_missing=bool(fees.get("assume_taker_only_if_fd_missing", True)),
        min_fill_size=_d(raw.get("min_fill_size", 1)),
        clob_pages=max(1, int(scan.get("clob_pages", 3))),
        include_gamma=bool(scan.get("include_gamma", True)),
        max_complete_set_events=max(0, int(scan.get("max_complete_set_events", 10))),
        max_complete_set_outcomes=max(3, int(scan.get("max_complete_set_outcomes", 12))),
        size_probe_steps=max(3, int(scan.get("size_probe_steps", 8))),
        summary_every_cycles=max(1, int(scan.get("summary_every_cycles", 1))),
        skip_walk_if_raw_below_floor=bool(scan.get("skip_walk_if_raw_below_floor", True)),
        session_enabled=bool(session.get("enabled", True)),
        session_timezone=str(session.get("timezone") or "America/New_York"),
        session_start=str(session.get("start") or "09:00"),
        session_end=str(session.get("end") or "22:00"),
        idle_zero_fill_sessions=max(1, int(session.get("idle_zero_fill_sessions", 2))),
        drawdown_halt_pct=_d(session.get("drawdown_halt_pct", "0.25")),
        drawdown_hard_floor_usd=_d(session.get("drawdown_hard_floor_usd", "180")),
    )
    _enforce_floors(cfg)
    if cfg.poll_interval_seconds < 5:
        raise ConfigError("poll_interval_seconds must be >= 5 for sane CLOB polling")
    return cfg
