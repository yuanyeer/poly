from __future__ import annotations

from decimal import Decimal

from polybot.config import PaperConfig
from polybot.market.book import best_bid, walk_asks
from polybot.market.fees import fee_amount
from polybot.strategy.base import Strategy, depth_cap
from polybot.types import Leg, MarketSnapshot, Opportunity


class MakerSpreadStrategy(Strategy):
    """Post a maker bid only when the opposite path is executable and inventory is hedged."""

    name = "maker_spread"

    def scan(self, market: MarketSnapshot, config: PaperConfig) -> list[Opportunity]:
        if len(market.outcomes) < 2:
            return []
        min_size = max(config.min_fill_size, market.min_order_size)
        best: Opportunity | None = None
        for idx, posted in enumerate(market.outcomes):
            quote = best_bid(posted)
            if quote is None:
                continue
            # Join the bid; do not cross the spread.
            posted_price = quote.price
            others = [outcome for j, outcome in enumerate(market.outcomes) if j != idx]
            size = min(quote.size, depth_cap(MarketSnapshot(
                condition_id=market.condition_id,
                question=market.question,
                fee=market.fee,
                outcomes=tuple(others),
                min_order_size=market.min_order_size,
            )))
            if size < min_size:
                continue
            hedge_walks = [walk_asks(other, size) for other in others]
            if any(not walk.fillable for walk in hedge_walks):
                continue
            maker_fee = fee_amount(size, posted_price, market.fee, "maker")
            hedge_fees = [
                fee_amount(size, walk.vwap, market.fee, "taker") for walk in hedge_walks
            ]
            hedge_vwap = sum((walk.vwap for walk in hedge_walks), Decimal("0"))
            edge = (
                Decimal("1")
                - posted_price
                - hedge_vwap
                - (maker_fee / size)
                - sum((fee / size for fee in hedge_fees), Decimal("0"))
            )
            if edge < config.maker_edge_floor:
                continue
            legs = [
                Leg(
                    token_id=posted.token_id,
                    outcome=posted.outcome,
                    side="BUY",
                    role="maker",
                    size=size,
                    price=posted_price,
                    fee=maker_fee,
                    notional=posted_price * size + maker_fee,
                    levels_used=1,
                )
            ]
            for other, walk, fee in zip(others, hedge_walks, hedge_fees, strict=True):
                legs.append(
                    Leg(
                        token_id=other.token_id,
                        outcome=other.outcome,
                        side="BUY",
                        role="taker",
                        size=size,
                        price=walk.vwap,
                        fee=fee,
                        notional=walk.cost + fee,
                        levels_used=walk.levels_used,
                    )
                )
            notional = sum((leg.notional for leg in legs), Decimal("0"))
            candidate = Opportunity(
                strategy="maker_spread",
                event_id=market.condition_id,
                question=market.question,
                edge=edge,
                size=size,
                notional=notional,
                expected_payout=size,
                legs=tuple(legs),
                notes="maker bid + immediate opposite taker hedge; fd.to controls maker fee",
            )
            if best is None or candidate.edge > best.edge:
                best = candidate
        return [best] if best is not None else []
