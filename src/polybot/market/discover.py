from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from polybot.types import ScanTarget

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


def paginate_clob(fetch, pages: int) -> list[str]:
    ids: list[str] = []
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
            cid = condition_id_from_row(row)
            if cid:
                ids.append(cid)
        if not next_cursor or next_cursor in END_CURSORS:
            break
        cursor = next_cursor
    return ids


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


def complete_set_targets_from_gamma_events(events: Any, limit: int) -> list[ScanTarget]:
    if not isinstance(events, list):
        return []
    targets: list[ScanTarget] = []
    for event in events:
        if len(targets) >= limit:
            break
        if not isinstance(event, dict):
            continue
        if event.get("closed") is True or event.get("active") is False:
            continue
        markets = event.get("markets") or []
        if not isinstance(markets, list):
            continue
        condition_ids: list[str] = []
        for market in markets:
            if not isinstance(market, dict):
                continue
            if market.get("acceptingOrders") is False or market.get("closed") is True:
                continue
            cid = condition_id_from_row(market)
            if cid:
                condition_ids.append(cid)
        # Mutually exclusive exhaustive set: 3+ live markets on one event.
        if len(condition_ids) < 3:
            continue
        event_id = str(event.get("id") or event.get("slug") or condition_ids[0])
        title = str(event.get("title") or event.get("ticker") or event_id)
        targets.append(
            ScanTarget(
                kind="complete_set",
                event_id=f"event:{event_id}",
                question=title,
                condition_ids=tuple(condition_ids),
            )
        )
    return targets


def gamma_binary_ids(rows: Any) -> list[str]:
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("markets") or []
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("acceptingOrders") is False or row.get("closed") is True:
            continue
        outcomes = _parse_maybe_json(row.get("outcomes"))
        if isinstance(outcomes, list) and len(outcomes) != 2:
            continue
        cid = condition_id_from_row(row)
        if cid:
            ids.append(cid)
    return ids
