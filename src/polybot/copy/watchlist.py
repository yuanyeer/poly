from __future__ import annotations

from dataclasses import dataclass, field

from polybot.config import CopyConfig, CopyLeaderConfig


@dataclass
class WatchedLeader:
    """Mutable watchlist row. `id` is the display-name key (wallet mapping TODO)."""

    id: str
    label: str
    strategy_tag: str
    priority: int
    primary: bool = False
    wallet: str | None = None
    active: bool = True

    @classmethod
    def from_config(cls, row: CopyLeaderConfig) -> WatchedLeader:
        return cls(
            id=row.id,
            label=row.label,
            strategy_tag=row.strategy_tag,
            priority=row.priority,
            primary=row.primary,
            wallet=row.wallet,
            active=True,
        )


@dataclass
class Watchlist:
    leaders: list[WatchedLeader] = field(default_factory=list)

    def by_id(self, leader_id: str) -> WatchedLeader | None:
        for leader in self.leaders:
            if leader.id == leader_id:
                return leader
        return None

    def active_leaders(self) -> list[WatchedLeader]:
        return [leader for leader in self.leaders if leader.active]

    def primary(self) -> WatchedLeader | None:
        for leader in self.leaders:
            if leader.primary:
                return leader
        return self.leaders[0] if self.leaders else None

    def mark_inactive(self, leader_id: str) -> WatchedLeader | None:
        leader = self.by_id(leader_id)
        if leader is None:
            return None
        leader.active = False
        return leader


def load_watchlist(copy: CopyConfig) -> Watchlist:
    leaders = [WatchedLeader.from_config(row) for row in copy.leaders]
    leaders.sort(key=lambda item: item.priority)
    return Watchlist(leaders=leaders)
