from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from polybot import (
    COPY_MAX_CHASE_SLIPPAGE,
    COPY_MAX_SLEEVE_PCT,
    COPY_STOP_PATH_DD,
    COPY_STOP_PEAK_DD,
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
class CopyLeaderConfig:
    """Watchlist row. `id` is the display-name key until wallet mapping exists."""

    id: str
    label: str
    strategy_tag: str
    priority: int = 100
    primary: bool = False
    wallet: str | None = None


@dataclass(frozen=True)
class CopyConfig:
    """Paper-only copy-trading observation. No live orders."""

    enabled: bool = False
    max_sleeve_pct: Decimal = Decimal(COPY_MAX_SLEEVE_PCT)
    stop_peak_dd: Decimal = Decimal(COPY_STOP_PEAK_DD)
    stop_path_dd: Decimal = Decimal(COPY_STOP_PATH_DD)
    month_pnl_below: Decimal = Decimal("0")
    max_chase_slippage: Decimal = Decimal(COPY_MAX_CHASE_SLIPPAGE)
    leaders: tuple[CopyLeaderConfig, ...] = ()
    metrics_stub: Path | None = None
    source_path: Path | None = None


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
    # FINAL default from poly 负责人: America/New_York 08:00–23:00 local (DST).
    # Not 24h. Outside the window the loop must not scan.
    session_enabled: bool = True
    session_timezone: str = "America/New_York"
    session_start: str = "08:00"
    session_end: str = "23:00"
    # booked=0 streak counts only in-window cycles (not wall-clock 24h).
    # Overnight idle between end and next start does not increment it.
    # ~two in-window sessions of booked=0 trips TRIGGER idle_zero_fill.
    idle_zero_fill_sessions: int = 2
    # Two-tier ops (ask poly金融):
    # REVIEW = peak DD ≥ 10% OR equity < 180 (keep scanning; 180 never SKIPs alone).
    # SKIP   = peak DD ≥ 25% OR equity < 150. 150 is below 180 so floors do not collide.
    drawdown_review_pct: Decimal = Decimal("0.10")
    drawdown_review_floor_usd: Decimal = Decimal("180")
    drawdown_halt_pct: Decimal = Decimal("0.25")
    drawdown_halt_floor_usd: Decimal = Decimal("150")
    copy: CopyConfig | None = None


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
    if cfg.drawdown_review_pct <= 0 or cfg.drawdown_review_pct > 1:
        raise ConfigError("drawdown_review_pct must be in (0, 1]")
    if cfg.drawdown_halt_pct <= 0 or cfg.drawdown_halt_pct > 1:
        raise ConfigError("drawdown_halt_pct must be in (0, 1]")
    if cfg.drawdown_review_pct > cfg.drawdown_halt_pct:
        raise ConfigError("drawdown_review_pct cannot exceed drawdown_halt_pct")
    if cfg.drawdown_review_floor_usd <= 0:
        raise ConfigError("drawdown_review_floor_usd must be > 0")
    if cfg.drawdown_halt_floor_usd <= 0:
        raise ConfigError("drawdown_halt_floor_usd must be > 0")
    if cfg.drawdown_halt_floor_usd >= cfg.drawdown_review_floor_usd:
        raise ConfigError("drawdown_halt_floor_usd must be below drawdown_review_floor_usd (180 is review-only)")
    _enforce_session(cfg)
    if cfg.copy is not None:
        _enforce_copy(cfg.copy)


def _enforce_copy(copy: CopyConfig) -> None:
    if copy.max_sleeve_pct <= 0 or copy.max_sleeve_pct > _d(COPY_MAX_SLEEVE_PCT):
        raise ConfigError(f"copy max_sleeve_pct cannot exceed {COPY_MAX_SLEEVE_PCT}")
    if copy.stop_peak_dd <= 0 or copy.stop_peak_dd > _d(COPY_STOP_PEAK_DD):
        raise ConfigError(f"copy stop peak_dd cannot exceed {COPY_STOP_PEAK_DD} (loosening forbidden)")
    if copy.stop_path_dd <= 0 or copy.stop_path_dd > _d(COPY_STOP_PATH_DD):
        raise ConfigError(f"copy stop path_dd cannot exceed {COPY_STOP_PATH_DD} (loosening forbidden)")
    if copy.month_pnl_below < 0:
        raise ConfigError("copy month_pnl_below cannot be negative (would loosen stop-follow)")
    if copy.max_chase_slippage <= 0 or copy.max_chase_slippage > _d(COPY_MAX_CHASE_SLIPPAGE):
        raise ConfigError(
            f"copy max_chase_slippage cannot exceed {COPY_MAX_CHASE_SLIPPAGE} (1¢; loosening forbidden)"
        )
    ids = [leader.id for leader in copy.leaders]
    if any(not leader_id.strip() for leader_id in ids):
        raise ConfigError("copy leader id is required")
    if len(ids) != len(set(ids)):
        raise ConfigError("copy leader ids must be unique")
    for leader in copy.leaders:
        if not leader.label.strip():
            raise ConfigError(f"copy leader {leader.id!r} needs a label")
        if not leader.strategy_tag.strip():
            raise ConfigError(f"copy leader {leader.id!r} needs a strategy_tag")
        if leader.priority < 1:
            raise ConfigError(f"copy leader {leader.id!r} priority must be >= 1")


def _resolve_copy_path(raw_path: str, paper_path: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_file():
        return candidate
    search = [
        Path.cwd() / candidate,
        paper_path.parent / candidate,
        paper_path.parent / candidate.name,
    ]
    for path in search:
        if path.is_file():
            return path
    raise ConfigError(f"copy config not found: {raw_path}")


def _parse_leaders(raw: Any) -> tuple[CopyLeaderConfig, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("copy leaders must be a list")
    leaders: list[CopyLeaderConfig] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ConfigError(f"copy leader #{index} must be a mapping")
        raw_id = row.get("id") if row.get("id") not in (None, "") else row.get("name")
        if isinstance(raw_id, (int, float)):
            raise ConfigError(
                "copy leader id was parsed as a number; quote 0x… / numeric keys in YAML"
            )
        leader_id = str(raw_id or "").strip()
        label = str(row.get("label") or leader_id).strip()
        tag = str(row.get("strategy_tag") or row.get("tag") or "").strip()
        wallet_raw = row.get("wallet")
        wallet = str(wallet_raw).strip() if wallet_raw else None
        leaders.append(
            CopyLeaderConfig(
                id=leader_id,
                label=label,
                strategy_tag=tag,
                priority=int(row.get("priority") or index + 1),
                primary=bool(row.get("primary", False)),
                wallet=wallet or None,
            )
        )
    return tuple(sorted(leaders, key=lambda item: item.priority))


def parse_copy_config(raw: dict[str, Any], *, source_path: Path | None = None) -> CopyConfig:
    stop = raw.get("stop_follow") or {}
    if not isinstance(stop, dict):
        raise ConfigError("copy stop_follow must be a mapping")
    stub_raw = raw.get("metrics_stub")
    stub = Path(str(stub_raw)) if stub_raw else None
    return CopyConfig(
        enabled=bool(raw.get("enabled", True)),
        max_sleeve_pct=_d(raw.get("max_sleeve_pct", COPY_MAX_SLEEVE_PCT)),
        stop_peak_dd=_d(stop.get("peak_dd", COPY_STOP_PEAK_DD)),
        stop_path_dd=_d(stop.get("path_dd", COPY_STOP_PATH_DD)),
        month_pnl_below=_d(stop.get("month_pnl_below", "0")),
        max_chase_slippage=_d(raw.get("max_chase_slippage", COPY_MAX_CHASE_SLIPPAGE)),
        leaders=_parse_leaders(raw.get("leaders")),
        metrics_stub=stub,
        source_path=source_path,
    )


def _load_copy(raw: dict[str, Any], paper_path: Path) -> CopyConfig | None:
    section = raw.get("copy")
    if not section:
        return None
    if not isinstance(section, dict):
        raise ConfigError("copy must be a mapping")
    nested = dict(section)
    source = paper_path
    if nested.get("path"):
        source = _resolve_copy_path(str(nested["path"]), paper_path)
        loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError("copy config root must be a mapping")
        enabled_override = nested["enabled"] if "enabled" in nested else None
        nested = loaded
        if enabled_override is not None:
            nested["enabled"] = enabled_override
    return parse_copy_config(nested, source_path=source)


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
        session_start=str(session.get("start") or "08:00"),
        session_end=str(session.get("end") or "23:00"),
        idle_zero_fill_sessions=max(1, int(session.get("idle_zero_fill_sessions", 2))),
        drawdown_review_pct=_d(session.get("drawdown_review_pct", "0.10")),
        drawdown_review_floor_usd=_d(session.get("drawdown_review_floor_usd", "180")),
        drawdown_halt_pct=_d(session.get("drawdown_halt_pct", "0.25")),
        drawdown_halt_floor_usd=_d(session.get("drawdown_halt_floor_usd", "150")),
        copy=_load_copy(raw, config_path),
    )
    _enforce_floors(cfg)
    if cfg.poll_interval_seconds < 5:
        raise ConfigError("poll_interval_seconds must be >= 5 for sane CLOB polling")
    return cfg
