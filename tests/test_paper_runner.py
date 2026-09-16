from __future__ import annotations

from polybot.ledger.store import PaperLedger
from polybot.runner.paper import PaperRunner
from tests.conftest import binary_market, level, paper_config


class _StubMarket:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot

    def list_condition_ids(self):
        return [self._snapshot.condition_id]

    def snapshot(self, condition_id: str):
        return self._snapshot if condition_id == self._snapshot.condition_id else None


def test_runner_books_paper_fill_from_walked_book(tmp_path):
    cfg = paper_config(tmp_path)
    market = binary_market(
        yes_asks=[level("0.30", "20"), level("0.32", "20")],
        no_asks=[level("0.30", "20"), level("0.33", "20")],
    )
    ledger = PaperLedger(cfg.ledger_path, cfg.starting_balance)
    runner = PaperRunner(cfg, ledger=ledger, market=_StubMarket(market))  # type: ignore[arg-type]
    report = runner.run_cycle()
    assert report.booked == 1
    state = ledger.state()
    assert state.open_count == 1
    assert state.cash < cfg.starting_balance
    assert state.equity > state.cash
    fill = state.fills[0]
    assert fill.cash_debit == fill.legs[0].notional + fill.legs[1].notional
    assert all(leg.levels_used >= 1 for leg in fill.legs)


def test_runner_does_not_fake_fill_without_edge(tmp_path):
    cfg = paper_config(tmp_path)
    market = binary_market(
        yes_asks=[level("0.52", "20")],
        no_asks=[level("0.52", "20")],
    )
    ledger = PaperLedger(cfg.ledger_path, cfg.starting_balance)
    runner = PaperRunner(cfg, ledger=ledger, market=_StubMarket(market))  # type: ignore[arg-type]
    report = runner.run_cycle()
    assert report.booked == 0
    assert ledger.state().cash == cfg.starting_balance
