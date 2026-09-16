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
    DRAWDOWN_HALT_FLOOR_USD,
    DRAWDOWN_REVIEW_FLOOR_USD,
    MAKER_EDGE_FLOOR,
    MAX_CONCURRENT_OPEN,
    MAX_SAME_EVENT_EXPOSURE_PCT,
    MAX_TRADE_NOTIONAL_PCT,
    PAPER_MODE,
    STARTING_BALANCE_USD,
    TAKER_EDGE_FLOOR,
    TARGET_BALANCE_USD,
    WHISKAS_ACCOUNT_ID,
    WHISKAS_CLIP_SIZE,
    WHISKAS_COMBO_SUM_CAP,
    WHISKAS_DRAWDOWN_HALT_FLOOR_USD,
    WHISKAS_DRAWDOWN_REVIEW_FLOOR_USD,
    WHISKAS_ENTER_AFTER_OPEN_SECONDS,
    WHISKAS_MAX_BUY_PRICE,
    WHISKAS_PER_ROUND_NOTIONAL_CAP_USD,
    WHISKAS_ROUND_SECONDS,
    WHISKAS_STARTING_BALANCE_USD,
    WHISKAS_STOP_REMAINING_SECONDS,
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

    enabled: bool = False  # owner: DISABLED while distilling lock-arb; runtime must skip copy modules
    max_sleeve_pct: Decimal = Decimal(COPY_MAX_SLEEVE_PCT)
    stop_peak_dd: Decimal = Decimal(COPY_STOP_PEAK_DD)
    stop_path_dd: Decimal = Decimal(COPY_STOP_PATH_DD)
    month_pnl_below: Decimal = Decimal("0")
    max_chase_slippage: Decimal = Decimal(COPY_MAX_CHASE_SLIPPAGE)
    leaders: tuple[CopyLeaderConfig, ...] = ()
    metrics_stub: Path | None = None
    source_path: Path | None = None


@dataclass(frozen=True)
class WhiskasConfig:
    """Paper-only BTC 5m Up/Down inventory. Not copy-follow. No live orders."""

    enabled: bool = False
    account_id: str = WHISKAS_ACCOUNT_ID
    starting_balance: Decimal = Decimal(WHISKAS_STARTING_BALANCE_USD)
    # None = do not invent a race target; report pnl / equity / caps.
    target_balance: Decimal | None = None
    ledger_path: Path | None = None
    clip_size: Decimal = Decimal(WHISKAS_CLIP_SIZE)
    enter_after_open_seconds: float = float(WHISKAS_ENTER_AFTER_OPEN_SECONDS)
    stop_remaining_seconds: float = float(WHISKAS_STOP_REMAINING_SECONDS)
    max_buy_price: Decimal = Decimal(WHISKAS_MAX_BUY_PRICE)
    combo_sum_cap: Decimal = Decimal(WHISKAS_COMBO_SUM_CAP)
    per_round_notional_cap: Decimal = Decimal(WHISKAS_PER_ROUND_NOTIONAL_CAP_USD)
    round_seconds: float = float(WHISKAS_ROUND_SECONDS)
    pause_arb_main_booking: bool = True
    drawdown_review_pct: Decimal = Decimal("0.10")
    drawdown_review_floor_usd: Decimal = Decimal(WHISKAS_DRAWDOWN_REVIEW_FLOOR_USD)
    drawdown_halt_pct: Decimal = Decimal("0.25")
    drawdown_halt_floor_usd: Decimal = Decimal(WHISKAS_DRAWDOWN_HALT_FLOOR_USD)
    question_needles: tuple[str, ...] = ("bitcoin", "btc")
    updown_needles: tuple[str, ...] = ("up or down", "up/down", "updown")
    interval_needles: tuple[str, ...] = ("5m", "5-min", "5 min", "5-minute", "5 minute")
    outcome_up: tuple[str, ...] = ("up", "yes")
    outcome_down: tuple[str, ...] = ("down", "no")


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
    # Diagnostics-only: walk all below-floor books when N <= this; else use raw SCREEN edges.
    # Never books below-floor. Does not change skip_walk_if_raw_below_floor or edge floors.
    diag_walk_limit: int = 12
    # 24h / 00:00–24:00 ET. Gate off; unused start/end are not an 08:00–23:00 window.
    session_enabled: bool = False
    session_timezone: str = "America/New_York"
    session_start: str = "00:00"
    session_end: str = "00:00"
    # booked=0 escalate is wall-clock continuous hours (default 24), not session-window accrual.
    idle_zero_fill_hours: float = 24.0
    # Two-tier ops (ask poly金融). Pct lines stay 10% / 25% unless told otherwise.
    # Absolute floors YAML-editable; finance freeze defaults 900 / 750.
    # REVIEW = peak DD ≥ review_pct OR equity < review_floor — keep scanning.
    # SKIP   = peak DD ≥ halt_pct OR equity < halt_floor. Halt floor must be below review.
    drawdown_review_pct: Decimal = Decimal("0.10")
    drawdown_review_floor_usd: Decimal = Decimal(DRAWDOWN_REVIEW_FLOOR_USD)
    drawdown_halt_pct: Decimal = Decimal("0.25")
    drawdown_halt_floor_usd: Decimal = Decimal(DRAWDOWN_HALT_FLOOR_USD)
    copy: CopyConfig | None = None
    whiskas: WhiskasConfig | None = None
    race_primary_account: str = "arb-main"


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
        raise ConfigError("session window must be a same-day interval (start < end) when the optional gate is enabled")


def _require_mode(raw: dict[str, Any]) -> None:
    mode = str(raw.get("mode", "")).strip().lower()
    if mode != PAPER_MODE:
        raise ConfigError(
            f"only mode={PAPER_MODE!r} is supported; live/real-money paths are not implemented"
        )


def _enforce_floors(cfg: PaperConfig) -> None:
    if cfg.starting_balance <= 0:
        raise ConfigError("starting_balance must be > 0")
    if cfg.target_balance <= cfg.starting_balance:
        raise ConfigError("target_balance must exceed starting_balance")
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
    if cfg.idle_zero_fill_hours <= 0:
        raise ConfigError("idle_zero_fill_hours must be > 0")
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
        raise ConfigError("drawdown_halt_floor_usd must be below drawdown_review_floor_usd (review floor is review-only)")
    _enforce_session(cfg)
    if cfg.copy is not None:
        _enforce_copy(cfg.copy)
    if cfg.whiskas is not None:
        _enforce_whiskas(cfg.whiskas)


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
        enabled=bool(raw.get("enabled", False)),
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


def _as_str_tuple(raw: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not raw:
        return default
    if not isinstance(raw, list):
        raise ConfigError("whiskas needle lists must be YAML lists")
    values = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    return values or default


def parse_whiskas_config(raw: dict[str, Any], *, paper_path: Path) -> WhiskasConfig:
    market = raw.get("market") or {}
    if market and not isinstance(market, dict):
        raise ConfigError("whiskas market must be a mapping")
    target_raw = raw.get("target_balance_usd")
    ledger_raw = raw.get("ledger_path")
    if ledger_raw:
        candidate = Path(str(ledger_raw))
        ledger_path = candidate if candidate.is_absolute() else Path.cwd() / candidate
    else:
        ledger_path = Path("data/whiskas-inv.jsonl")
    return WhiskasConfig(
        enabled=bool(raw.get("enabled", False)),
        account_id=str(raw.get("account_id") or WHISKAS_ACCOUNT_ID).strip(),
        starting_balance=_d(raw.get("starting_balance_usd", WHISKAS_STARTING_BALANCE_USD)),
        target_balance=_d(target_raw) if target_raw not in (None, "") else None,
        ledger_path=ledger_path,
        clip_size=_d(raw.get("clip_size", WHISKAS_CLIP_SIZE)),
        enter_after_open_seconds=float(raw.get("enter_after_open_seconds", WHISKAS_ENTER_AFTER_OPEN_SECONDS)),
        stop_remaining_seconds=float(raw.get("stop_remaining_seconds", WHISKAS_STOP_REMAINING_SECONDS)),
        max_buy_price=_d(raw.get("max_buy_price", WHISKAS_MAX_BUY_PRICE)),
        combo_sum_cap=_d(raw.get("combo_sum_cap", WHISKAS_COMBO_SUM_CAP)),
        per_round_notional_cap=_d(raw.get("per_round_notional_cap_usd", WHISKAS_PER_ROUND_NOTIONAL_CAP_USD)),
        round_seconds=float(raw.get("round_seconds", WHISKAS_ROUND_SECONDS)),
        pause_arb_main_booking=bool(raw.get("pause_arb_main_booking", True)),
        drawdown_review_pct=_d(raw.get("drawdown_review_pct", "0.10")),
        drawdown_review_floor_usd=_d(raw.get("drawdown_review_floor_usd", WHISKAS_DRAWDOWN_REVIEW_FLOOR_USD)),
        drawdown_halt_pct=_d(raw.get("drawdown_halt_pct", "0.25")),
        drawdown_halt_floor_usd=_d(raw.get("drawdown_halt_floor_usd", WHISKAS_DRAWDOWN_HALT_FLOOR_USD)),
        question_needles=_as_str_tuple(market.get("question_needles"), ("bitcoin", "btc")),
        updown_needles=_as_str_tuple(market.get("updown_needles"), ("up or down", "up/down", "updown")),
        interval_needles=_as_str_tuple(
            market.get("interval_needles"), ("5m", "5-min", "5 min", "5-minute", "5 minute")
        ),
        outcome_up=_as_str_tuple(market.get("outcome_up"), ("up", "yes")),
        outcome_down=_as_str_tuple(market.get("outcome_down"), ("down", "no")),
    )


def _load_whiskas(raw: dict[str, Any], paper_path: Path) -> WhiskasConfig | None:
    section = raw.get("whiskas")
    if not section:
        return None
    if not isinstance(section, dict):
        raise ConfigError("whiskas must be a mapping")
    return parse_whiskas_config(section, paper_path=paper_path)


def _enforce_whiskas(whiskas: WhiskasConfig) -> None:
    if not whiskas.account_id.strip():
        raise ConfigError("whiskas account_id is required")
    if whiskas.starting_balance <= 0:
        raise ConfigError("whiskas starting_balance must be > 0")
    if whiskas.target_balance is not None and whiskas.target_balance <= whiskas.starting_balance:
        raise ConfigError("whiskas target_balance must exceed starting_balance when set")
    if whiskas.clip_size <= 0:
        raise ConfigError("whiskas clip_size must be > 0")
    if whiskas.enter_after_open_seconds < 0:
        raise ConfigError("whiskas enter_after_open_seconds cannot be negative")
    if whiskas.stop_remaining_seconds < 0:
        raise ConfigError("whiskas stop_remaining_seconds cannot be negative")
    if whiskas.max_buy_price <= 0 or whiskas.max_buy_price > 1:
        raise ConfigError("whiskas max_buy_price must be in (0, 1]")
    if whiskas.combo_sum_cap <= 0:
        raise ConfigError("whiskas combo_sum_cap must be > 0")
    if whiskas.per_round_notional_cap <= 0:
        raise ConfigError("whiskas per_round_notional_cap must be > 0")
    if whiskas.round_seconds <= 0:
        raise ConfigError("whiskas round_seconds must be > 0")
    if whiskas.drawdown_review_pct <= 0 or whiskas.drawdown_review_pct > 1:
        raise ConfigError("whiskas drawdown_review_pct must be in (0, 1]")
    if whiskas.drawdown_halt_pct <= 0 or whiskas.drawdown_halt_pct > 1:
        raise ConfigError("whiskas drawdown_halt_pct must be in (0, 1]")
    if whiskas.drawdown_review_pct > whiskas.drawdown_halt_pct:
        raise ConfigError("whiskas drawdown_review_pct cannot exceed drawdown_halt_pct")
    if whiskas.drawdown_review_floor_usd <= 0:
        raise ConfigError("whiskas drawdown_review_floor_usd must be > 0")
    if whiskas.drawdown_halt_floor_usd <= 0:
        raise ConfigError("whiskas drawdown_halt_floor_usd must be > 0")
    if whiskas.drawdown_halt_floor_usd >= whiskas.drawdown_review_floor_usd:
        raise ConfigError("whiskas halt floor must be below review floor")


def copy_runtime_enabled(copy: CopyConfig | None) -> bool:
    """True only when copy modules may run. False skips watchlist, copy ledgers, and MirrorExecutor."""
    return copy is not None and copy.enabled


def whiskas_runtime_enabled(whiskas: WhiskasConfig | None) -> bool:
    """True when the paper inventory path may book on whiskas-inv."""
    return whiskas is not None and whiskas.enabled


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
    race = raw.get("race") or {}
    whiskas = _load_whiskas(raw, config_path)
    race_primary = str(race.get("primary_account") or "").strip()
    if not race_primary:
        race_primary = whiskas.account_id if whiskas_runtime_enabled(whiskas) else "arb-main"

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
        diag_walk_limit=max(0, int(scan.get("diag_walk_limit", 12))),
        session_enabled=bool(session.get("enabled", False)),
        session_timezone=str(session.get("timezone") or "America/New_York"),
        session_start=str(session.get("start") or "00:00"),
        session_end=str(session.get("end") or "00:00"),
        idle_zero_fill_hours=float(session.get("idle_zero_fill_hours", 24)),
        drawdown_review_pct=_d(session.get("drawdown_review_pct", "0.10")),
        drawdown_review_floor_usd=_d(session.get("drawdown_review_floor_usd", DRAWDOWN_REVIEW_FLOOR_USD)),
        drawdown_halt_pct=_d(session.get("drawdown_halt_pct", "0.25")),
        drawdown_halt_floor_usd=_d(session.get("drawdown_halt_floor_usd", DRAWDOWN_HALT_FLOOR_USD)),
        copy=_load_copy(raw, config_path),
        whiskas=whiskas,
        race_primary_account=race_primary,
    )
    _enforce_floors(cfg)
    if cfg.poll_interval_seconds < 5:
        raise ConfigError("poll_interval_seconds must be >= 5 for sane CLOB polling")
    return cfg
