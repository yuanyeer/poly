from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DrawdownDecision:
    """Live ledger equity vs peak. Review and hard-halt use separate floors."""

    drawdown: Decimal
    review: bool
    halt: bool
    below_review_floor: bool
    below_halt_floor: bool

    def review_line(
        self,
        *,
        peak: Decimal,
        equity: Decimal,
        review_pct: Decimal,
        review_floor: Decimal,
    ) -> str:
        return (
            f"REVIEW drawdown peak={peak:.4f} equity={equity:.4f} "
            f"dd={self.drawdown:.4f} review={review_pct} floor={review_floor} "
            f"(escalate-to-finance; keep scanning)"
        )

    def halt_line(
        self,
        *,
        peak: Decimal,
        equity: Decimal,
        halt_pct: Decimal,
        halt_floor: Decimal,
    ) -> str:
        return (
            f"SKIP drawdown_halt peak={peak:.4f} equity={equity:.4f} "
            f"dd={self.drawdown:.4f} halt={halt_pct} floor={halt_floor} "
            f"(hard stop)"
        )


def classify_drawdown(
    *,
    equity: Decimal,
    peak: Decimal,
    review_pct: Decimal,
    halt_pct: Decimal,
    review_floor: Decimal,
    halt_floor: Decimal,
) -> DrawdownDecision:
    """REVIEW: dd >= review_pct OR equity < review_floor (finance: 10% / 900).

    HALT: dd >= halt_pct OR equity < halt_floor (finance: 25% / 750).
    Equity below the review floor must not by itself hard-stop.
    """
    if peak <= 0:
        drawdown = Decimal("0")
    else:
        drawdown = (peak - equity) / peak
    below_review_floor = equity < review_floor
    below_halt_floor = equity < halt_floor
    review = drawdown >= review_pct or below_review_floor
    halt = drawdown >= halt_pct or below_halt_floor
    return DrawdownDecision(
        drawdown=drawdown,
        review=review,
        halt=halt,
        below_review_floor=below_review_floor,
        below_halt_floor=below_halt_floor,
    )
