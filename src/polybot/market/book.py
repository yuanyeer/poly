from __future__ import annotations

from decimal import Decimal

from polybot.types import BookLevel, OutcomeBook, WalkFill

ZERO = Decimal("0")


def _sort_asks(levels: tuple[BookLevel, ...] | list[BookLevel]) -> list[BookLevel]:
    return sorted((lvl for lvl in levels if lvl.size > 0 and lvl.price > 0), key=lambda x: x.price)


def _sort_bids(levels: tuple[BookLevel, ...] | list[BookLevel]) -> list[BookLevel]:
    return sorted(
        (lvl for lvl in levels if lvl.size > 0 and lvl.price > 0),
        key=lambda x: x.price,
        reverse=True,
    )


def available_ask_size(book: OutcomeBook) -> Decimal:
    return sum((lvl.size for lvl in book.asks), ZERO)


def available_bid_size(book: OutcomeBook) -> Decimal:
    return sum((lvl.size for lvl in book.bids), ZERO)


def walk_asks(book: OutcomeBook, size: Decimal) -> WalkFill:
    """Walk ask depth for `size`. Never books top-of-book size blindly."""
    return _walk(_sort_asks(book.asks), size)


def walk_bids(book: OutcomeBook, size: Decimal) -> WalkFill:
    """Walk bid depth for `size` (selling into bids)."""
    return _walk(_sort_bids(book.bids), size)


def _walk(levels: list[BookLevel], size: Decimal) -> WalkFill:
    size = Decimal(size)
    if size <= 0:
        return WalkFill(
            size=ZERO,
            cost=ZERO,
            vwap=ZERO,
            fee=ZERO,
            levels_used=0,
            exhausted=True,
            residual_size=ZERO,
        )
    remaining = size
    cost = ZERO
    used = 0
    for level in levels:
        if remaining <= 0:
            break
        take = min(remaining, level.size)
        if take <= 0:
            continue
        cost += take * level.price
        remaining -= take
        used += 1
    filled = size - remaining
    exhausted = remaining > 0
    vwap = (cost / filled) if filled > 0 else ZERO
    return WalkFill(
        size=filled if exhausted else size,
        cost=cost,
        vwap=vwap,
        fee=ZERO,
        levels_used=used,
        exhausted=exhausted,
        residual_size=remaining,
    )


def best_bid(book: OutcomeBook) -> BookLevel | None:
    bids = _sort_bids(book.bids)
    return bids[0] if bids else None


def best_ask(book: OutcomeBook) -> BookLevel | None:
    asks = _sort_asks(book.asks)
    return asks[0] if asks else None
