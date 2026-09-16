from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx
from py_clob_client_v2 import ClobClient

from polybot.config import PaperConfig
from polybot.market.discover import (
    binary_targets,
    complete_set_targets_from_gamma_events,
    gamma_binary_ids,
    paginate_clob,
)
from polybot.types import BookLevel, FeeSchedule, MarketSnapshot, OutcomeBook, ScanTarget

logger = logging.getLogger(__name__)

LIVE_ORDER_METHODS = frozenset(
    {
        "create_order",
        "create_and_post_order",
        "create_and_post_market_order",
        "create_market_order",
        "post_order",
        "post_orders",
        "cancel_order",
        "cancel_orders",
        "cancel_all",
        "cancel_market_orders",
    }
)


class LiveOrderForbidden(RuntimeError):
    """Raised when paper mode is asked to touch a real-money order path."""


def _dec(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def _as_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "__dict__"):
        data = {k: v for k, v in vars(payload).items() if not k.startswith("_")}
        if data:
            return data
    return {}


def _levels(raw: Any) -> tuple[BookLevel, ...]:
    levels: list[BookLevel] = []
    if not raw:
        return tuple()
    for item in raw:
        if isinstance(item, dict):
            price = item.get("price")
            size = item.get("size")
        else:
            price = getattr(item, "price", None)
            size = getattr(item, "size", None)
        if price is None or size is None:
            continue
        levels.append(BookLevel(price=_dec(price), size=_dec(size)))
    return tuple(levels)


def _pick_token(tokens: list[Any], want: str | None) -> dict[str, Any] | None:
    parsed = [_as_dict(token) for token in tokens if token]
    if want:
        for token in parsed:
            label = str(token.get("o") or token.get("outcome") or "").strip().lower()
            if label == want:
                return token
    return parsed[0] if parsed else None


class PaperMarketClient:
    """Read-only CLOB/Gamma wrapper. Live order methods are hard-disabled."""

    def __init__(self, config: PaperConfig, clob: ClobClient | None = None) -> None:
        self.config = config
        self._clob = clob or ClobClient(host=config.clob_host, chain_id=config.chain_id)
        if getattr(self._clob, "signer", None) is not None or getattr(self._clob, "creds", None) is not None:
            raise LiveOrderForbidden("paper mode must use an L0 read-only ClobClient (no key/creds)")

    def __getattr__(self, name: str) -> Any:
        if name in LIVE_ORDER_METHODS:
            raise LiveOrderForbidden(f"paper mode forbids {name}")
        raise AttributeError(name)

    def get_clob_market_info(self, condition_id: str) -> dict[str, Any]:
        return _as_dict(self._clob.get_clob_market_info(condition_id))

    def get_order_book(self, token_id: str) -> dict[str, Any]:
        return _as_dict(self._clob.get_order_book(token_id))

    def list_condition_ids(self) -> list[str]:
        return [target.event_id for target in self.list_scan_targets() if target.kind == "binary"][
            : self.config.max_markets
        ]

    def list_scan_targets(self) -> list[ScanTarget]:
        if self.config.condition_ids:
            return binary_targets(self.config.condition_ids)[: self.config.max_markets]

        condition_ids: list[str] = []
        condition_ids.extend(self._from_clob("get_sampling_markets"))
        condition_ids.extend(self._from_clob("get_markets"))
        if self.config.include_gamma:
            condition_ids.extend(self._gamma_binary_ids())

        binaries = binary_targets(condition_ids)[: self.config.max_markets]
        groups: list[ScanTarget] = []
        if self.config.include_gamma and self.config.max_complete_set_events:
            groups = complete_set_targets_from_gamma_events(
                self._gamma_events(),
                self.config.max_complete_set_events,
                max_outcomes=self.config.max_complete_set_outcomes,
            )
        logger.info(
            "discover binaries=%s complete_set_events=%s (cap %s/%s)",
            len(binaries),
            len(groups),
            self.config.max_markets,
            self.config.max_complete_set_events,
        )
        return binaries + groups

    def _from_clob(self, method_name: str) -> list[str]:
        method = getattr(self._clob, method_name, None)
        if method is None:
            return []

        def fetch(cursor: str):
            return method(next_cursor=cursor)

        return paginate_clob(fetch, self.config.clob_pages)

    def _gamma_get(self, path: str, params: dict[str, str]) -> Any:
        url = f"{self.config.gamma_host}{path}"
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gamma %s failed: %s", path, exc)
            return None

    def _gamma_binary_ids(self) -> list[str]:
        rows = self._gamma_get(
            "/markets",
            {
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
                "limit": str(min(100, max(self.config.max_markets, 20))),
            },
        )
        return gamma_binary_ids(rows)

    def _gamma_events(self) -> list[Any]:
        rows = self._gamma_get(
            "/events",
            {
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
                "limit": str(min(50, max(self.config.max_complete_set_events * 2, 10))),
            },
        )
        if isinstance(rows, list):
            return rows
        if isinstance(rows, dict):
            data = rows.get("data") or rows.get("events") or []
            return data if isinstance(data, list) else []
        return []

    def snapshot_target(self, target: ScanTarget) -> MarketSnapshot | None:
        if target.kind == "complete_set":
            return self._snapshot_complete_set(target)
        if not target.condition_ids:
            return None
        snap = self.snapshot(target.condition_ids[0])
        if snap is None:
            return None
        return MarketSnapshot(
            condition_id=target.event_id,
            question=target.question if target.question != target.event_id else snap.question,
            fee=snap.fee,
            outcomes=snap.outcomes,
            min_order_size=snap.min_order_size,
            kind="binary",
        )

    def snapshot(self, condition_id: str) -> MarketSnapshot | None:
        try:
            info = self.get_clob_market_info(condition_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_clob_market_info(%s) failed: %s", condition_id, exc)
            return None
        tokens = info.get("t") or []
        if len(tokens) < 2:
            return None
        fee = self._fee_from_info(info)
        min_order = _dec(info.get("mos"), "1")
        tick = _dec(info.get("mts"), "0.01")
        question = str(info.get("q") or info.get("question") or condition_id)
        outcomes = self._books_for_tokens(tokens, fee, min_order, tick, condition_id)
        if len(outcomes) < 2:
            return None
        return MarketSnapshot(
            condition_id=condition_id,
            question=question,
            fee=fee,
            outcomes=tuple(outcomes),
            min_order_size=min_order,
            kind="binary",
        )

    def _snapshot_complete_set(self, target: ScanTarget) -> MarketSnapshot | None:
        outcomes: list[OutcomeBook] = []
        fees: list[FeeSchedule] = []
        min_order = Decimal("1")
        for condition_id in target.condition_ids:
            try:
                info = self.get_clob_market_info(condition_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_clob_market_info(%s) failed: %s", condition_id, exc)
                return None
            tokens = info.get("t") or []
            yes = _pick_token(tokens, "yes")
            if not yes:
                return None
            fee = self._fee_from_info(info)
            fees.append(fee)
            min_order = max(min_order, _dec(info.get("mos"), "1"))
            tick = _dec(info.get("mts"), "0.01")
            label = str(yes.get("o") or "Yes")
            # Prefer the market question so legs stay distinguishable.
            question = str(info.get("q") or info.get("question") or condition_id)
            books = self._books_for_tokens([yes], fee, min_order, tick, condition_id)
            if not books:
                return None
            outcome = books[0]
            outcomes.append(
                OutcomeBook(
                    token_id=outcome.token_id,
                    outcome=f"{label}:{question[:60]}",
                    bids=outcome.bids,
                    asks=outcome.asks,
                    tick_size=outcome.tick_size,
                    min_order_size=outcome.min_order_size,
                    fee=fee,
                    condition_id=condition_id,
                )
            )
        if len(outcomes) < 3:
            return None
        # Conservative shared schedule: highest taker rate among legs.
        shared = max(fees, key=lambda item: item.rate)
        return MarketSnapshot(
            condition_id=target.event_id,
            question=target.question,
            fee=shared,
            outcomes=tuple(outcomes),
            min_order_size=min_order,
            kind="complete_set",
        )

    def _fee_from_info(self, info: dict[str, Any]) -> FeeSchedule:
        fd = info.get("fd") or {}
        taker_only = fd.get("to")
        if taker_only is None:
            taker_only = self.config.assume_taker_only_if_fd_missing
        return FeeSchedule(
            rate=_dec(fd.get("r"), "0"),
            exponent=_dec(fd.get("e"), "0"),
            taker_only=bool(taker_only),
        )

    def _books_for_tokens(
        self,
        tokens: list[Any],
        fee: FeeSchedule,
        min_order: Decimal,
        tick: Decimal,
        condition_id: str,
    ) -> list[OutcomeBook]:
        outcomes: list[OutcomeBook] = []
        for token in tokens:
            item = token if isinstance(token, dict) else _as_dict(token)
            token_id = str(item.get("t") or item.get("token_id") or "")
            label = str(item.get("o") or item.get("outcome") or token_id)
            if not token_id:
                continue
            try:
                raw_book = self.get_order_book(token_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_order_book(%s) failed: %s", token_id, exc)
                return []
            outcomes.append(
                OutcomeBook(
                    token_id=token_id,
                    outcome=label,
                    bids=_levels(raw_book.get("bids")),
                    asks=_levels(raw_book.get("asks")),
                    tick_size=_dec(raw_book.get("tick_size"), str(tick)),
                    min_order_size=_dec(raw_book.get("min_order_size"), str(min_order)),
                    fee=fee,
                    condition_id=condition_id,
                )
            )
        return outcomes
