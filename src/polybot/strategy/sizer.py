from __future__ import annotations

from decimal import Decimal

from polybot.market.book import best_bid, walk_asks
from polybot.market.fees import fee_amount
from polybot.types import Leg, MarketSnapshot, Opportunity, Role

ZERO = Decimal("0")


def resize_to_book(market: MarketSnapshot, opportunity: Opportunity, new_size: Decimal) -> Opportunity | None:
    """Re-walk live books at `new_size` so slippage/fees are recomputed (never reuse top-of-book)."""
    if new_size <= ZERO:
        return None
    by_token = {outcome.token_id: outcome for outcome in market.outcomes}
    legs: list[Leg] = []
    for old in opportunity.legs:
        book = by_token.get(old.token_id)
        if book is None:
            return None
        role: Role = old.role
        if role == "maker":
            price = old.price
            quote = best_bid(book)
            if quote is None or new_size > quote.size:
                return None
            fee = fee_amount(new_size, price, market.fee, "maker")
            legs.append(
                Leg(
                    token_id=old.token_id,
                    outcome=old.outcome,
                    side="BUY",
                    role="maker",
                    size=new_size,
                    price=price,
                    fee=fee,
                    notional=price * new_size + fee,
                    levels_used=1,
                )
            )
            continue
        fill = walk_asks(book, new_size)
        if not fill.fillable:
            return None
        fee = fee_amount(new_size, fill.vwap, market.fee, "taker")
        legs.append(
            Leg(
                token_id=old.token_id,
                outcome=old.outcome,
                side="BUY",
                role="taker",
                size=new_size,
                price=fill.vwap,
                fee=fee,
                notional=fill.cost + fee,
                levels_used=fill.levels_used,
            )
        )
    notional = sum((leg.notional for leg in legs), ZERO)
    edge = Decimal("1") - sum((leg.price + (leg.fee / new_size) for leg in legs), ZERO)
    return Opportunity(
        strategy=opportunity.strategy,
        event_id=opportunity.event_id,
        question=opportunity.question,
        edge=edge,
        size=new_size,
        notional=notional,
        expected_payout=new_size,
        legs=tuple(legs),
        notes=opportunity.notes,
    )
