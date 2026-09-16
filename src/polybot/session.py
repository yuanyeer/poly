from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from polybot.config import ConfigError


def parse_hhmm(value: str) -> time:
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
    return time(hour, minute)


def zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"unknown session timezone: {name!r}") from exc


def as_utc(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def local_now(tz_name: str, now: datetime | None = None) -> datetime:
    return as_utc(now).astimezone(zoneinfo(tz_name))


def in_trading_window(
    tz_name: str,
    start: str,
    end: str,
    now: datetime | None = None,
    *,
    enabled: bool = True,
) -> bool:
    """True when local wall clock is in [start, end). ZoneInfo honors DST."""
    if not enabled:
        return True
    local = local_now(tz_name, now)
    start_t = parse_hhmm(start)
    end_t = parse_hhmm(end)
    return start_t <= local.time() < end_t


def session_label(tz_name: str, start: str, end: str) -> str:
    return f"{tz_name} {start}-{end}"
