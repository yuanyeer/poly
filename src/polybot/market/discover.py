from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Iterable

from polybot.types import ScanTarget, ScreenTape

logger = logging.getLogger(__name__)

END_CURSORS = frozenset({"", "LTE=", None})


def _as_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return {}


def _parse_maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def condition_id_from_row(row: Any) -> str | None:
    item = _as_dict(row)
    cid = item.get("condition_id") or item.get("conditionId") or item.get("id")
    if cid is None:
        return None
    text = str(cid).strip()
    return text or None


def rows_from_clob_payload(payload: Any) -> tuple[list[Any], str | None]:
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("markets") or []
        cursor = payload.get("next_cursor") or payload.get("nextCursor")
        return list(rows) if isinstance(rows, Iterable) else [], str(cursor) if cursor else None
    if isinstance(payload, list):
        return payload, None
    return [], None


def paginate_clob_rows(fetch, pages: int) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    cursor = "MA=="
    for _ in range(max(1, pages)):
        try:
            payload = fetch(cursor)
        except TypeError:
            try:
                payload = fetch()
            except Exception as exc:  # noqa: BLE001
                logger.warning("CLOB market page failed: %s", exc)
                break
        except Exception as exc:  # noqa: BLE001
            logger.warning("CLOB market page failed: %s", exc)
            break
        rows, next_cursor = rows_from_clob_payload(payload)
        for row in rows:
            if isinstance(row, dict):
                rows_out.append(row)
        if not next_cursor or next_cursor in END_CURSORS:
            break
        cursor = next_cursor
    return rows_out


def paginate_clob(fetch, pages: int) -> list[str]:
    ids: list[str] = []
    for row in paginate_clob_rows(fetch, pages):
        cid = condition_id_from_row(row)
        if cid:
            ids.append(cid)
    return ids


def token_ids_from_clob_row(row: dict[str, Any]) -> tuple[str, ...]:
    tokens = row.get("tokens") or row.get("t") or []
    ids: list[str] = []
    for token in tokens:
        item = token if isinstance(token, dict) else {}
        tid = item.get("token_id") or item.get("t")
        if tid:
            ids.append(str(tid))
    return tuple(ids)


def live_binary_target(row: dict[str, Any]) -> ScanTarget | None:
    if row.get("closed") is True or row.get("active") is False:
        return None
    if row.get("accepting_orders") is False or row.get("acceptingOrders") is False:
        return None
    cid = condition_id_from_row(row)
    token_ids = token_ids_from_clob_row(row)
    if not cid or len(token_ids) != 2:
        return None
    question = str(row.get("question") or cid)
    return ScanTarget(
        kind="binary",
        event_id=cid,
        question=question,
        condition_ids=(cid,),
        token_ids=token_ids,
    )


def parse_ask_map(payload: Any) -> dict[str, Decimal]:
    """Normalize get_prices() payload to token_id -> best ask."""
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Decimal] = {}
    for token_id, node in payload.items():
        raw = None
        if isinstance(node, dict):
            raw = node.get("SELL") or node.get("sell") or node.get("ASK") or node.get("ask")
        else:
            raw = node
        price = _dec(raw)
        if price is not None:
            out[str(token_id)] = price
    return out


def raw_taker_edge(token_ids: Iterable[str], asks: dict[str, Decimal]) -> Decimal | None:
    prices: list[Decimal] = []
    for token_id in token_ids:
        price = asks.get(token_id)
        if price is None:
            return None
        prices.append(price)
    if not prices:
        return None
    return Decimal("1") - sum(prices, Decimal("0"))


def rank_targets_by_raw_edge(
    targets: Iterable[ScanTarget],
    asks: dict[str, Decimal],
) -> list[ScanTarget]:
    scored: list[ScanTarget] = []
    for target in targets:
        if not target.token_ids:
            scored.append(target)
            continue
        raw = raw_taker_edge(target.token_ids, asks)
        scored.append(
            ScanTarget(
                kind=target.kind,
                event_id=target.event_id,
                question=target.question,
                condition_ids=target.condition_ids,
                token_ids=target.token_ids,
                raw_edge=raw,
            )
        )
    scored.sort(key=lambda item: item.raw_edge if item.raw_edge is not None else Decimal("-99"), reverse=True)
    return scored


def select_walkable(
    targets: list[ScanTarget],
    floor: Decimal,
    *,
    limit: int,
    skip_below_floor: bool,
) -> list[ScanTarget]:
    if not skip_below_floor:
        return targets[:limit]
    hits = [
        target
        for target in targets
        if target.raw_edge is not None and target.raw_edge >= floor
    ]
    return hits[:limit]


def build_screen_tape(
    binaries: list[ScanTarget],
    groups: list[ScanTarget],
    *,
    floor: Decimal,
    walk_binary_limit: int,
    walk_group_limit: int,
    skip_below_floor: bool,
) -> ScreenTape:
    """Ranked SCREEN universe plus booking-only walk list.

    Booking skip is unchanged: `walk_targets` still omit raw-below-floor
    when `skip_below_floor` is set. Diagnostics use `raw_edges` /
    `below_floor_targets` separately.
    """
    walk_binaries = select_walkable(
        binaries,
        floor,
        limit=walk_binary_limit,
        skip_below_floor=skip_below_floor,
    )
    walk_groups = select_walkable(
        groups,
        floor,
        limit=walk_group_limit,
        skip_below_floor=skip_below_floor,
    )
    scored = [item for item in binaries + groups if item.raw_edge is not None]
    below = [item for item in scored if item.raw_edge is not None and item.raw_edge < floor]
    return ScreenTape(
        screened_n=len(binaries) + len(groups),
        below_floor_n=len(below),
        best_binary=binaries[0].raw_edge if binaries else None,
        best_set=groups[0].raw_edge if groups else None,
        raw_edges=tuple(item.raw_edge for item in scored if item.raw_edge is not None),
        walk_targets=tuple(walk_binaries + walk_groups),
        below_floor_targets=tuple(below),
    )


def binary_targets(condition_ids: Iterable[str], questions: dict[str, str] | None = None) -> list[ScanTarget]:
    named = questions or {}
    targets: list[ScanTarget] = []
    seen: set[str] = set()
    for cid in condition_ids:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        targets.append(
            ScanTarget(
                kind="binary",
                event_id=cid,
                question=named.get(cid, cid),
                condition_ids=(cid,),
            )
        )
    return targets


def yes_token_id(market: dict[str, Any]) -> str | None:
    tokens = _parse_maybe_json(market.get("clobTokenIds") or market.get("tokens"))
    outcomes = _parse_maybe_json(market.get("outcomes"))
    if not isinstance(tokens, list) or not tokens:
        return None
    idx = 0
    if isinstance(outcomes, list):
        for i, label in enumerate(outcomes):
            if str(label).strip().lower() == "yes":
                idx = i
                break
    if idx >= len(tokens):
        return None
    token = tokens[idx]
    if isinstance(token, dict):
        tid = token.get("token_id") or token.get("t")
        return str(tid) if tid else None
    return str(token)


def complete_set_targets_from_gamma_events(
    events: Any,
    limit: int,
    max_outcomes: int = 12,
) -> list[ScanTarget]:
    if not isinstance(events, list) or limit <= 0:
        return []
    targets: list[ScanTarget] = []
    collect_cap = max(limit * 8, limit)
    for event in events:
        if len(targets) >= collect_cap:
            break
        if not isinstance(event, dict):
            continue
        if event.get("closed") is True or event.get("active") is False:
            continue
        if event.get("enableNegRisk") is not True:
            continue
        markets = event.get("markets") or []
        if not isinstance(markets, list):
            continue
        condition_ids: list[str] = []
        yes_tokens: list[str] = []
        for market in markets:
            if not isinstance(market, dict):
                continue
            if market.get("acceptingOrders") is False or market.get("closed") is True:
                continue
            cid = condition_id_from_row(market)
            token = yes_token_id(market)
            if cid:
                condition_ids.append(cid)
            if token:
                yes_tokens.append(token)
        if len(condition_ids) < 3 or len(condition_ids) > max_outcomes:
            continue
        event_id = str(event.get("id") or event.get("slug") or condition_ids[0])
        title = str(event.get("title") or event.get("ticker") or event_id)
        targets.append(
            ScanTarget(
                kind="complete_set",
                event_id=f"event:{event_id}",
                question=title,
                condition_ids=tuple(condition_ids),
                token_ids=tuple(yes_tokens) if len(yes_tokens) == len(condition_ids) else (),
            )
        )
    return targets


def gamma_binary_targets(rows: Any) -> list[ScanTarget]:
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("markets") or []
    if not isinstance(rows, list):
        return []
    targets: list[ScanTarget] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("acceptingOrders") is False or row.get("closed") is True:
            continue
        outcomes = _parse_maybe_json(row.get("outcomes"))
        if isinstance(outcomes, list) and len(outcomes) != 2:
            continue
        cid = condition_id_from_row(row)
        tokens = _parse_maybe_json(row.get("clobTokenIds"))
        token_ids: tuple[str, ...] = ()
        if isinstance(tokens, list) and len(tokens) == 2:
            token_ids = tuple(str(t) for t in tokens)
        if cid:
            targets.append(
                ScanTarget(
                    kind="binary",
                    event_id=cid,
                    question=str(row.get("question") or cid),
                    condition_ids=(cid,),
                    token_ids=token_ids,
                )
            )
    return targets


def gamma_binary_ids(rows: Any) -> list[str]:
    return [target.event_id for target in gamma_binary_targets(rows)]
