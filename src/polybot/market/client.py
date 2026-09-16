from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Iterable

import httpx
from py_clob_client_v2 import ClobClient

from polybot.config import PaperConfig
from polybot.types import BookLevel, FeeSchedule, MarketSnapshot, OutcomeBook

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


def _parse_maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


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
        if self.config.condition_ids:
            return list(self.config.condition_ids)[: self.config.max_markets]
        found = self._from_clob_markets()
        if not found:
            found = self._from_gamma()
        return found[: self.config.max_markets]

    def _from_clob_markets(self) -> list[str]:
        ids: list[str] = []
        try:
            payload = self._clob.get_sampling_markets()
        except Exception as exc:  # noqa: BLE001 — public API shape can vary
            logger.warning("CLOB sampling markets unavailable: %s", exc)
            return ids
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, Iterable):
            return ids
        for row in rows:
            item = _as_dict(row)
            cid = item.get("condition_id") or item.get("conditionId") or item.get("id")
            if cid:
                ids.append(str(cid))
        return ids

    def _from_gamma(self) -> list[str]:
        url = f"{self.config.gamma_host}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
            "limit": str(self.config.max_markets),
        }
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                rows = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gamma market discovery failed: %s", exc)
            return []
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("markets") or []
        ids: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("acceptingOrders") is False:
                continue
            cid = row.get("conditionId") or row.get("condition_id")
            if cid:
                ids.append(str(cid))
        return ids

    def snapshot(self, condition_id: str) -> MarketSnapshot | None:
        try:
            info = self.get_clob_market_info(condition_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_clob_market_info(%s) failed: %s", condition_id, exc)
            return None
        tokens = info.get("t") or []
        if len(tokens) < 2:
            return None
        fd = info.get("fd") or {}
        taker_only = fd.get("to")
        if taker_only is None:
            taker_only = self.config.assume_taker_only_if_fd_missing
        fee = FeeSchedule(
            rate=_dec(fd.get("r"), "0"),
            exponent=_dec(fd.get("e"), "0"),
            taker_only=bool(taker_only),
        )
        min_order = _dec(info.get("mos"), "1")
        tick = _dec(info.get("mts"), "0.01")
        question = str(info.get("q") or info.get("question") or condition_id)
        outcomes: list[OutcomeBook] = []
        for token in tokens:
            token_id = str(token.get("t") or token.get("token_id") or "")
            label = str(token.get("o") or token.get("outcome") or token_id)
            if not token_id:
                continue
            try:
                raw_book = self.get_order_book(token_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_order_book(%s) failed: %s", token_id, exc)
                return None
            outcomes.append(
                OutcomeBook(
                    token_id=token_id,
                    outcome=label,
                    bids=_levels(raw_book.get("bids")),
                    asks=_levels(raw_book.get("asks")),
                    tick_size=_dec(raw_book.get("tick_size"), str(tick)),
                    min_order_size=_dec(raw_book.get("min_order_size"), str(min_order)),
                )
            )
        if len(outcomes) < 2:
            return None
        return MarketSnapshot(
            condition_id=condition_id,
            question=question,
            fee=fee,
            outcomes=tuple(outcomes),
            min_order_size=min_order,
        )
