from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from polybot.config import CopyConfig, PaperConfig
from polybot.risk.gates import RiskEngine
from polybot.types import LedgerState, RiskDecision

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


@dataclass(frozen=True)
class MirrorIntent:
    """Proposed copy of a leader fill. Not an order and not a ledger fill.

    A future implementation MUST:
    - apply observed delay vs the leader fill (`delay_seconds`)
    - walk book depth (never top-of-book); set `depth_walked=True` only after walk
    - apply CLOB fees (`fd.r` / `fd.to`); set `fees_applied=True` only after fees
    """

    leader_id: str
    event_id: str
    notional: Decimal
    size: Decimal
    delay_seconds: Decimal | None
    depth_walked: bool
    fees_applied: bool
    notes: str = ""


@dataclass(frozen=True)
class MirrorDecision:
    allowed: bool
    reason: str

    @property
    def rejected(self) -> bool:
        return not self.allowed


class MirrorExecutor:
    """Paper-only stub. Evaluates sleeve + risk; never posts orders or writes fills.

    Rejects if the intent would violate:
    - delay / depth-walk / fee requirements (documented, not simulated)
    - copy sleeve ≤ 30% of equity
    - existing 25% trade / 40% same-event / ≤3 concurrent caps
    """

    def __init__(
        self,
        config: PaperConfig,
        copy: CopyConfig | None = None,
        risk: RiskEngine | None = None,
    ) -> None:
        self.config = config
        self.copy = copy if copy is not None else config.copy
        self.risk = risk or RiskEngine(config)

    def evaluate(
        self,
        intent: MirrorIntent,
        state: LedgerState,
        sleeve_used: Decimal = ZERO,
    ) -> MirrorDecision:
        if self.copy is None or not self.copy.enabled:
            return MirrorDecision(False, "copy-trading observation is disabled")
        if intent.delay_seconds is None:
            return MirrorDecision(False, "mirror requires observed delay vs leader fill")
        if intent.delay_seconds < ZERO:
            return MirrorDecision(False, "mirror delay cannot be negative")
        if not intent.depth_walked:
            return MirrorDecision(False, "mirror requires depth walk (never top-of-book only)")
        if not intent.fees_applied:
            return MirrorDecision(False, "mirror requires fees applied (fd.r / fd.to)")
        if intent.notional <= ZERO or intent.size <= ZERO:
            return MirrorDecision(False, "mirror notional/size must be positive")
        if not intent.event_id:
            return MirrorDecision(False, "mirror event_id required")

        equity = state.equity
        sleeve_cap = equity * self.copy.max_sleeve_pct
        projected = sleeve_used + intent.notional
        if projected > sleeve_cap:
            return MirrorDecision(
                False,
                (
                    f"copy sleeve {projected} would exceed "
                    f"{self.copy.max_sleeve_pct:.0%} of equity ({sleeve_cap})"
                ),
            )

        cap_reasons = self.risk.notional_cap_reasons(intent.notional, intent.event_id, state)
        if cap_reasons:
            return MirrorDecision(False, "; ".join(cap_reasons))
        return MirrorDecision(True, "ok (paper stub; no order, no fill)")

    def execute(
        self,
        intent: MirrorIntent,
        state: LedgerState,
        sleeve_used: Decimal = ZERO,
    ) -> MirrorDecision:
        """Reject-or-ack only. Does not append ledger fills or post CLOB orders."""
        decision = self.evaluate(intent, state, sleeve_used)
        if decision.allowed:
            logger.info(
                "MIRROR stub ack leader=%s event=%s notional=%s (no fill written)",
                intent.leader_id,
                intent.event_id,
                intent.notional,
            )
        else:
            logger.info("MIRROR reject leader=%s: %s", intent.leader_id, decision.reason)
        return decision

    def risk_preview(
        self,
        intent: MirrorIntent,
        state: LedgerState,
        sleeve_used: Decimal = ZERO,
    ) -> RiskDecision:
        """Same gates as `evaluate`, shaped as a RiskDecision for callers."""
        decision = self.evaluate(intent, state, sleeve_used)
        return RiskDecision(allowed=decision.allowed, reason=decision.reason)
