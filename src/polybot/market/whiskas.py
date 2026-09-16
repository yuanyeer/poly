from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from polybot.config import WhiskasConfig
from polybot.types import MarketSnapshot, OutcomeBook, ScanTarget

_TIME_RANGE = re.compile(
    r"(?P<a>\d{1,2}:\d{2})\s*(?P<ap>AM|PM)?\s*[-–]\s*(?P<b>\d{1,2}:\d{2})\s*(?P<bp>AM|PM)?",
    re.IGNORECASE,
)


def _blob(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _has_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle and needle.lower() in text for needle in needles)


def parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_dt(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _minutes_from_clock(match: re.Match[str]) -> int | None:
    def minutes(clock: str, meridiem: str | None) -> int | None:
        hour_s, minute_s = clock.split(":")
        hour = int(hour_s)
        minute = int(minute_s)
        mer = (meridiem or "").lower()
        if mer == "pm" and hour != 12:
            hour += 12
        if mer == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        return hour * 60 + minute

    start = minutes(match.group("a"), match.group("ap") or match.group("bp"))
    end = minutes(match.group("b"), match.group("bp") or match.group("ap"))
    if start is None or end is None:
        return None
    delta = end - start
    if delta <= 0:
        delta += 24 * 60
    return delta


def _title_looks_five_minutes(text: str) -> bool:
    match = _TIME_RANGE.search(text)
    if match is None:
        return False
    minutes = _minutes_from_clock(match)
    return minutes is not None and 4 <= minutes <= 6


def is_btc_5m_updown(text: str, config: WhiskasConfig, *, duration_seconds: float | None = None) -> bool:
    blob = text.lower()
    if not _has_any(blob, config.question_needles):
        return False
    if not _has_any(blob, config.updown_needles):
        return False
    if duration_seconds is not None and 240 <= duration_seconds <= 360:
        return True
    if _has_any(blob, config.interval_needles):
        return True
    return _title_looks_five_minutes(blob)


def parse_round_clock(
    row: dict[str, Any],
    *,
    round_seconds: float,
) -> tuple[datetime | None, datetime | None]:
    end = parse_dt(
        row.get("endDate")
        or row.get("end_date_iso")
        or row.get("endDateIso")
        or row.get("end_date")
        or row.get("closedTime")
    )
    start = parse_dt(
        row.get("eventStartTime")
        or row.get("gameStartTime")
        or row.get("startDate")
        or row.get("start_date_iso")
        or row.get("startDateIso")
    )
    if end and start is None:
        start = end - timedelta(seconds=round_seconds)
    if start and end is None:
        end = start + timedelta(seconds=round_seconds)
    return start, end


def duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def _token_winner(tokens: Any) -> str | None:
    if not isinstance(tokens, list):
        return None
    for token in tokens:
        if not isinstance(token, dict):
            continue
        winner = token.get("winner")
        if winner is True:
            label = token.get("o") or token.get("outcome")
            if label:
                return str(label)
    return None


def row_resolution(row: dict[str, Any]) -> tuple[bool, str | None]:
    closed = row.get("closed") is True or row.get("active") is False
    winner = row.get("winner") or row.get("umaResolutionStatus")
    if isinstance(winner, str) and winner.strip() and winner.strip().lower() not in {"resolved", "yes"}:
        return True, winner.strip()
    token_winner = _token_winner(row.get("tokens") or row.get("t"))
    if token_winner:
        return True, token_winner
    return bool(closed), None


def whiskas_target_from_row(row: dict[str, Any], config: WhiskasConfig) -> ScanTarget | None:
    cid = str(row.get("condition_id") or row.get("conditionId") or row.get("id") or "").strip()
    if not cid:
        return None
    question = str(row.get("question") or row.get("q") or row.get("title") or cid)
    slug = str(row.get("slug") or row.get("market_slug") or "")
    start, end = parse_round_clock(row, round_seconds=config.round_seconds)
    blob = _blob(question, slug, row.get("description"))
    if not is_btc_5m_updown(blob, config, duration_seconds=duration_seconds(start, end)):
        return None
    tokens = row.get("tokens") or row.get("t") or row.get("clobTokenIds") or []
    token_ids: list[str] = []
    if isinstance(tokens, list):
        for token in tokens:
            if isinstance(token, dict):
                tid = token.get("token_id") or token.get("t")
                if tid:
                    token_ids.append(str(tid))
            elif token:
                token_ids.append(str(token))
    resolved, winner = row_resolution(row)
    return ScanTarget(
        kind="binary",
        event_id=cid,
        question=question,
        condition_ids=(cid,),
        token_ids=tuple(token_ids[:2]),
        slug=slug,
        round_open=start,
        round_end=end,
        resolved=resolved,
        winner=winner,
    )


def collect_whiskas_targets(rows: Iterable[Any], config: WhiskasConfig) -> list[ScanTarget]:
    found: dict[str, ScanTarget] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        target = whiskas_target_from_row(row, config)
        if target:
            found[target.event_id] = target
    return list(found.values())


def classify_outcome(label: str, config: WhiskasConfig) -> str | None:
    name = label.strip().lower()
    if name in config.outcome_up or name.endswith(":up"):
        return "Up"
    if name in config.outcome_down or name.endswith(":down"):
        return "Down"
    if "up" == name or name.startswith("up"):
        return "Up"
    if "down" == name or name.startswith("down"):
        return "Down"
    return None


def split_up_down(market: MarketSnapshot, config: WhiskasConfig) -> tuple[OutcomeBook, OutcomeBook] | None:
    if len(market.outcomes) != 2:
        return None
    mapped: dict[str, OutcomeBook] = {}
    for outcome in market.outcomes:
        side = classify_outcome(outcome.outcome, config)
        if side:
            mapped[side] = outcome
    if "Up" in mapped and "Down" in mapped:
        return mapped["Up"], mapped["Down"]
    # Binary Yes/No fallback: first=Up, second=Down only when labels already classified.
    return None


def normalize_winner(label: str | None, config: WhiskasConfig) -> str | None:
    if not label:
        return None
    return classify_outcome(label, config)
