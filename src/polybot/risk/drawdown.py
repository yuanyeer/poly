from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DrawdownDecision:
    """Live ledger equity vs peak. Review and hard-halt are separate knobs."""

    drawdown: Decimal
    review: bool
    halt: bool
    below_floor: bool

    def review_line(self, *, peak: Decimal, equity: Decimal, review_pct: Decimal, floor: Decimal) -> str:
        return (
            f"REVIEW drawdown peak={peak:.4f} equity={equity:.4f} "
            f"dd={self.drawdown:.4f} review={review_pct} floor={floor} "
            f"(escalate-to-finance)"
        )

    def halt_line(self, *, peak: Decimal, equity: Decimal, halt_pct: Decimal, floor: Decimal) -> str:
        return (
            f"SKIP drawdown_halt peak={peak:.4f} equity={equity:.4f} "
            f"dd={self.drawdown:.4f} halt={halt_pct} floor={floor} "
            f"(hard stop)"
        )


def classify_drawdown(
    *,
    equity: Decimal,
    peak: Decimal,
    review_pct: Decimal,
    halt_pct: Decimal,
    hard_floor: Decimal,
) -> DrawdownDecision:
    if peak <= 0:
        drawdown = Decimal("0")
    else:
        drawdown = (peak - equity) / peak
    below_floor = equity < hard_floor
    review = drawdown >= review_pct or below_floor
    halt = drawdown >= halt_pct or below_floor
    return DrawdownDecision(drawdown=drawdown, review=review, halt=halt, below_floor=below_floor)
