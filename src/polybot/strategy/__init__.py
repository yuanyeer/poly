from polybot.strategy.base import Strategy
from polybot.strategy.complete_set import CompleteSetStrategy
from polybot.strategy.maker_spread import MakerSpreadStrategy
from polybot.strategy.whiskas_inventory import WhiskasInventoryStrategy
from polybot.strategy.yes_no_lock import YesNoLockStrategy

__all__ = [
    "CompleteSetStrategy",
    "MakerSpreadStrategy",
    "Strategy",
    "WhiskasInventoryStrategy",
    "YesNoLockStrategy",
]


def default_strategies() -> tuple[Strategy, ...]:
    return (
        YesNoLockStrategy(),
        CompleteSetStrategy(),
        MakerSpreadStrategy(),
    )
