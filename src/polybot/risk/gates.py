from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from polybot.config import PaperConfig
from polybot.types import LedgerState, Opportunity, RiskDecision

ZERO = Decimal("0")


class RiskError(ValueError):
    """A hard risk-rule violation."""


class RiskEngine:
    def __init__(self, config: PaperConfig) -> None:
        self.config = config

    def evaluate(self, opportunity: Opportunity, state: LedgerState) -> RiskDecision:
        if opportunity.strategy == "whiskas_inventory":
            return self.evaluate_whiskas(opportunity, state)
        reasons = list(self._hard_rejects(opportunity, state))
        if reasons:
            return RiskDecision(allowed=False, reason="; ".join(reasons))
        return RiskDecision(allowed=True, reason="ok", capped_size=opportunity.size)

    def evaluate_whiskas(self, opportunity: Opportunity, state: LedgerState) -> RiskDecision:
        whiskas = self.config.whiskas
        reasons: list[str] = []
        if whiskas is None or not whiskas.enabled:
            return RiskDecision(allowed=False, reason="whiskas inventory disabled")
        if any(leg.side == "SELL" for leg in opportunity.legs):
            reasons.append("forbidden: mid-round sell")
        if not opportunity.legs:
            reasons.append("no legs")
        if opportunity.notional > state.cash:
            reasons.append("notional exceeds cash")
        spent = state.event_exposure.get(opportunity.event_id, ZERO)
        if spent + opportunity.notional > whiskas.per_round_notional_cap:
            reasons.append(
                f"per-round notional {spent + opportunity.notional} > cap {whiskas.per_round_notional_cap}"
            )
        prices: list[Decimal] = []
        for leg in opportunity.legs:
            if leg.levels_used < 1:
                reasons.append("forbidden: fill ignored book depth")
            if leg.price > whiskas.max_buy_price:
                reasons.append(f"buy price {leg.price} > max {whiskas.max_buy_price}")
            if leg.side == "BUY":
                prices.append(leg.price)
        if len(prices) >= 2 and sum(prices) > whiskas.combo_sum_cap:
            reasons.append(f"combo {sum(prices)} > cap {whiskas.combo_sum_cap}")
        if reasons:
            return RiskDecision(allowed=False, reason="; ".join(reasons))
        return RiskDecision(allowed=True, reason="ok", capped_size=opportunity.size)

    def notional_cap_reasons(self, notional: Decimal, event_id: str, state: LedgerState) -> list[str]:
        """Shared 25% / 40% / ≤3 concurrent gates (also used by copy sleeve stub)."""
        reasons: list[str] = []
        if state.open_count >= self.config.max_concurrent_open:
            reasons.append(f"concurrent open {state.open_count} >= {self.config.max_concurrent_open}")
        if notional > state.cash:
            reasons.append("notional exceeds cash")
        max_trade = state.cash * self.config.max_trade_notional_pct
        if notional > max_trade:
            reasons.append(
                f"single-trade notional {notional} > {self.config.max_trade_notional_pct:.0%} of cash"
            )
        current_event = state.event_exposure.get(event_id, ZERO)
        max_event = state.cash * self.config.max_same_event_exposure_pct
        if current_event + notional > max_event:
            reasons.append(
                f"same-event exposure would exceed {self.config.max_same_event_exposure_pct:.0%} of cash"
            )
        return reasons

    def _hard_rejects(self, opportunity: Opportunity, state: LedgerState) -> list[str]:
        reasons: list[str] = []
        reasons.extend(self.notional_cap_reasons(opportunity.notional, opportunity.event_id, state))
        if not opportunity.legs:
            reasons.append("no legs")
            return reasons
        if self._is_directional(opportunity):
            reasons.append("forbidden: directional single-sided bet")
        if not opportunity.event_id:
            reasons.append("forbidden: unhedged cross-event narrative")
        if any(leg.levels_used < 1 for leg in opportunity.legs):
            reasons.append("forbidden: fill ignored book depth")
        floor = (
            self.config.maker_edge_floor
            if opportunity.strategy == "maker_spread"
            else self.config.taker_edge_floor
        )
        if opportunity.edge < floor:
            reasons.append(f"edge {opportunity.edge} below floor {floor}")
        residual = self._unhedged_notional(opportunity)
        if residual > self.config.max_unhedged_inventory:
            reasons.append(f"unhedged inventory {residual} exceeds bound")
        return reasons

    def cap_size(self, opportunity: Opportunity, state: LedgerState) -> Decimal:
        """Open size <= min(balance×0.25, remaining same-event room, depth-available size)."""
        if opportunity.size <= ZERO or opportunity.notional <= ZERO:
            return ZERO
        cost_per_share = opportunity.notional / opportunity.size
        if cost_per_share <= ZERO:
            return ZERO
        trade_room = (state.cash * self.config.max_trade_notional_pct) / cost_per_share
        event_used = state.event_exposure.get(opportunity.event_id, ZERO)
        event_room_usd = max(ZERO, state.cash * self.config.max_same_event_exposure_pct - event_used)
        event_room = event_room_usd / cost_per_share
        cash_room = state.cash / cost_per_share
        capped = min(opportunity.size, trade_room, event_room, cash_room)
        return max(ZERO, capped.quantize(Decimal("0.0001"), rounding=ROUND_DOWN))

    @staticmethod
    def _is_directional(opportunity: Opportunity) -> bool:
        buys = [leg for leg in opportunity.legs if leg.side == "BUY"]
        if len(buys) < 2:
            return True
        sizes = {leg.size for leg in buys}
        return len(sizes) != 1

    @staticmethod
    def _unhedged_notional(opportunity: Opportunity) -> Decimal:
        buys = [leg for leg in opportunity.legs if leg.side == "BUY"]
        if len(buys) < 2:
            return opportunity.notional
        return ZERO
