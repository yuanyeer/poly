from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


@dataclass(frozen=True)
class LeaderMetrics:
    """Point-in-time leader snapshot. Fed by a scanner later; stubbed for paper."""

    leader_id: str
    peak_dd: Decimal
    path_dd: Decimal
    month_pnl: Decimal
    last_seen_active: datetime | None = None
    as_of: datetime | None = None

    @classmethod
    def from_mapping(cls, leader_id: str, raw: Mapping[str, Any]) -> LeaderMetrics:
        return cls(
            leader_id=leader_id,
            peak_dd=_d(raw.get("peak_dd", "0")),
            path_dd=_d(raw.get("path_dd", "0")),
            month_pnl=_d(raw.get("month_pnl", "0")),
            last_seen_active=_parse_ts(raw.get("last_seen_active")),
            as_of=_parse_ts(raw.get("as_of")),
        )


class MetricsProvider(ABC):
    """Interface a later leader scanner can implement. Not a live scraper."""

    @abstractmethod
    def snapshot(self, leader_id: str) -> LeaderMetrics | None:
        """Return the latest metrics for `leader_id`, or None if unseen."""


class InMemoryMetricsProvider(MetricsProvider):
    """Test / paper stub. Push snapshots in; no network."""

    def __init__(self, rows: Mapping[str, LeaderMetrics] | None = None) -> None:
        self._rows: dict[str, LeaderMetrics] = dict(rows or {})

    def snapshot(self, leader_id: str) -> LeaderMetrics | None:
        return self._rows.get(leader_id)

    def put(self, metrics: LeaderMetrics) -> None:
        self._rows[metrics.leader_id] = metrics


class JsonFileMetricsProvider(MetricsProvider):
    """Paper-test stub: load `{leader_id: {peak_dd, path_dd, month_pnl, ...}}` JSON."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._rows = self._load()

    def _load(self) -> dict[str, LeaderMetrics]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("copy metrics stub must be a JSON object keyed by leader id")
        rows: dict[str, LeaderMetrics] = {}
        for leader_id, body in raw.items():
            if not isinstance(body, dict):
                raise ValueError(f"metrics for {leader_id!r} must be an object")
            rows[str(leader_id)] = LeaderMetrics.from_mapping(str(leader_id), body)
        return rows

    def reload(self) -> None:
        self._rows = self._load()

    def snapshot(self, leader_id: str) -> LeaderMetrics | None:
        return self._rows.get(leader_id)
