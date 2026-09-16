from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from polybot.config import PaperConfig, WhiskasConfig, whiskas_runtime_enabled
from polybot.market.whiskas import classify_outcome, split_up_down
from polybot.strategy.base import Strategy, walk_taker
from polybot.types import Leg, MarketSnapshot, Opportunity, WalkFill

ZERO = Decimal("0")


def _aware(now: datetime) -> datetime:
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def whiskas_window(
    market: MarketSnapshot,
    now: datetime,
    config: WhiskasConfig,
) -> tuple[bool, str]:
    if market.round_open is None or market.round_end is None:
        return False, "missing_round_clock"
    current = _aware(now)
    opened = _aware(market.round_open)
    ends = _aware(market.round_end)
    elapsed = (current - opened).total_seconds()
    remaining = (ends - current).total_seconds()
    if elapsed < config.enter_after_open_seconds:
        return False, "too_early"
    if remaining <= config.stop_remaining_seconds:
        return False, "too_late"
    return True, "ok"


def _leg(outcome, walk: WalkFill, fee: Decimal, label: str) -> Leg:
    return Leg(
        token_id=outcome.token_id,
        outcome=label,
        side="BUY",
        role="taker",
        size=walk.size,
        price=walk.vwap,
        fee=fee,
        notional=walk.cost + fee,
        levels_used=walk.levels_used,
    )


class WhiskasInventoryStrategy(Strategy):
    """Buy both BTC 5m Up and Down clips. Paper taker walk only. No sells."""

    name = "whiskas_inventory"

    def scan(
        self,
        market: MarketSnapshot,
        config: PaperConfig,
        *,
        now: datetime | None = None,
        round_notional: Decimal | None = None,
    ) -> list[Opportunity]:
        whiskas = config.whiskas
        if not whiskas_runtime_enabled(whiskas) or whiskas is None:
            return []
        if market.resolved:
            return []
        clock = now or datetime.now(timezone.utc)
        open_ok, reason = whiskas_window(market, clock, whiskas)
        if not open_ok:
            return []
        pair = split_up_down(market, whiskas)
        if pair is None:
            return []
        up_book, down_book = pair
        clip = whiskas.clip_size
        if clip < max(config.min_fill_size, market.min_order_size):
            return []
        spent = round_notional or ZERO
        remaining_cap = whiskas.per_round_notional_cap - spent
        if remaining_cap <= ZERO:
            return []

        walked: dict[str, tuple[object, WalkFill, Decimal]] = {}
        for label, book in (("Up", up_book), ("Down", down_book)):
            fill, fee = walk_taker(book, clip, market)
            if fill.fillable and fill.size == clip:
                walked[label] = (book, fill, fee)

        up_ok = "Up" in walked and walked["Up"][1].vwap <= whiskas.max_buy_price
        down_ok = "Down" in walked and walked["Down"][1].vwap <= whiskas.max_buy_price
        legs: list[Leg] = []
        notes = f"window={reason}"
        if up_ok and down_ok:
            combo = walked["Up"][1].vwap + walked["Down"][1].vwap
            if combo > whiskas.combo_sum_cap:
                return []
            legs.append(_leg(walked["Up"][0], walked["Up"][1], walked["Up"][2], "Up"))
            legs.append(_leg(walked["Down"][0], walked["Down"][1], walked["Down"][2], "Down"))
            notes += ";pair"
        elif up_ok:
            legs.append(_leg(walked["Up"][0], walked["Up"][1], walked["Up"][2], "Up"))
            notes += ";cheap=Up"
        elif down_ok:
            legs.append(_leg(walked["Down"][0], walked["Down"][1], walked["Down"][2], "Down"))
            notes += ";cheap=Down"
        else:
            return []
        if any(leg.side != "BUY" for leg in legs):
            return []
        notional = sum((leg.notional for leg in legs), ZERO)
        if notional <= ZERO or notional > remaining_cap:
            return []
        paired = min((leg.size for leg in legs), default=ZERO) if len(legs) == 2 else ZERO
        return [
            Opportunity(
                strategy="whiskas_inventory",
                event_id=market.condition_id,
                question=market.question,
                edge=ZERO if len(legs) == 1 else (paired - notional),
                size=clip,
                notional=notional,
                expected_payout=paired,
                legs=tuple(legs),
                notes=notes,
                clip_id=uuid4().hex,
            )
        ]

    def preview_edge(self, market: MarketSnapshot, config: PaperConfig):
        return None


def inventory_from_fills(fills, config: WhiskasConfig) -> dict[str, dict[str, Decimal]]:
    """event_id -> {Up, Down, debit} for unsettled whiskas buys."""
    redeemed: set[str] = set()
    for fill in fills:
        if getattr(fill, "strategy", "") == "whiskas_inventory" and "redeem" in str(getattr(fill, "notes", "")):
            redeemed.add(fill.event_id)
    out: dict[str, dict[str, Decimal]] = {}
    for fill in fills:
        if getattr(fill, "strategy", "") != "whiskas_inventory":
            continue
        if fill.event_id in redeemed:
            continue
        if "redeem" in str(getattr(fill, "notes", "")):
            continue
        bucket = out.setdefault(fill.event_id, {"Up": ZERO, "Down": ZERO, "debit": ZERO})
        bucket["debit"] += fill.cash_debit
        for leg in fill.legs:
            if leg.side != "BUY":
                continue
            side = classify_outcome(leg.outcome, config) or leg.outcome
            if side in {"Up", "Down"}:
                bucket[side] += leg.size
    return out
