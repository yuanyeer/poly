from __future__ import annotations

from decimal import Decimal

from polybot.risk.gates import RiskEngine
from polybot.types import LedgerState, Leg, Opportunity
from tests.conftest import paper_config


def _state(**kwargs) -> LedgerState:
    values = dict(
        starting_balance=Decimal("200"),
        cash=Decimal("200"),
        locked_payout=Decimal("0"),
        open_count=0,
        event_exposure={},
        fills=[],
    )
    values.update(kwargs)
    return LedgerState(**values)


def _opp(
    *,
    notional: str = "20",
    size: str = "40",
    edge: str = "0.02",
    legs: int = 2,
    event: str = "0xevent",
    strategy: str = "yes_no_lock",
    levels: int = 2,
) -> Opportunity:
    sz = Decimal(size)
    built = []
    for i in range(legs):
        built.append(
            Leg(
                token_id=f"t{i}",
                outcome=f"o{i}",
                side="BUY",
                role="taker",
                size=sz,
                price=Decimal("0.4"),
                fee=Decimal("0.01"),
                notional=Decimal(notional) / Decimal(legs),
                levels_used=levels,
            )
        )
    return Opportunity(
        strategy=strategy,  # type: ignore[arg-type]
        event_id=event,
        question="q",
        edge=Decimal(edge),
        size=sz,
        notional=Decimal(notional),
        expected_payout=sz,
        legs=tuple(built),
    )


def test_allows_hedged_trade_within_limits():
    engine = RiskEngine(paper_config())
    decision = engine.evaluate(_opp(notional="20"), _state())
    assert decision.allowed


def test_rejects_trade_over_25_percent():
    engine = RiskEngine(paper_config())
    decision = engine.evaluate(_opp(notional="51"), _state())
    assert not decision.allowed
    assert "25%" in decision.reason or "0.25" in decision.reason or "notional" in decision.reason


def test_rejects_same_event_over_40_percent():
    engine = RiskEngine(paper_config())
    state = _state(event_exposure={"0xevent": Decimal("70")})
    decision = engine.evaluate(_opp(notional="20"), state)
    assert not decision.allowed
    assert "same-event" in decision.reason


def test_rejects_fourth_concurrent():
    engine = RiskEngine(paper_config())
    decision = engine.evaluate(_opp(), _state(open_count=3))
    assert not decision.allowed
    assert "concurrent" in decision.reason


def test_rejects_directional_single_leg():
    engine = RiskEngine(paper_config())
    decision = engine.evaluate(_opp(legs=1), _state())
    assert not decision.allowed
    assert "directional" in decision.reason


def test_rejects_ignored_depth():
    engine = RiskEngine(paper_config())
    decision = engine.evaluate(_opp(levels=0), _state())
    assert not decision.allowed
    assert "depth" in decision.reason


def test_rejects_edge_below_taker_floor():
    engine = RiskEngine(paper_config())
    decision = engine.evaluate(_opp(edge="0.004"), _state())
    assert not decision.allowed
    assert "edge" in decision.reason


def test_size_cap_is_min_of_rooms():
    engine = RiskEngine(paper_config())
    opp = _opp(notional="40", size="80")  # 0.5 USD per share
    # 25% of 200 = 50 notional => 100 shares; event room 80; depth 80 => 80
    cap = engine.cap_size(opp, _state())
    assert cap == Decimal("80.0000")
    # existing 60 exposure: remaining event room = 80-60=20 => 40 shares
    cap2 = engine.cap_size(opp, _state(event_exposure={"0xevent": Decimal("60")}))
    assert cap2 == Decimal("40.0000")
