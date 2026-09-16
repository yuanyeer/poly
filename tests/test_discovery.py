from __future__ import annotations

from decimal import Decimal

from polybot.market.discover import (
    binary_targets,
    build_screen_tape,
    complete_set_targets_from_gamma_events,
    gamma_binary_ids,
    live_binary_target,
    paginate_clob,
    parse_ask_map,
    rank_targets_by_raw_edge,
    rows_from_clob_payload,
    select_walkable,
)
from polybot.types import ScanTarget


def test_paginate_clob_merges_pages():
    pages = {
        "MA==": {"data": [{"condition_id": "0xa"}, {"condition_id": "0xb"}], "next_cursor": "p2"},
        "p2": {"data": [{"conditionId": "0xc"}], "next_cursor": "LTE="},
    }

    def fetch(cursor: str):
        return pages[cursor]

    assert paginate_clob(fetch, pages=3) == ["0xa", "0xb", "0xc"]


def test_rows_from_clob_payload_accepts_list():
    rows, cursor = rows_from_clob_payload([{"condition_id": "0x1"}])
    assert cursor is None
    assert len(rows) == 1


def test_gamma_binaries_skip_closed_and_multi():
    rows = [
        {"conditionId": "0xbin", "acceptingOrders": True, "outcomes": '["Yes","No"]'},
        {"conditionId": "0xclosed", "closed": True, "outcomes": '["Yes","No"]'},
        {"conditionId": "0xmulti", "acceptingOrders": True, "outcomes": '["A","B","C"]'},
    ]
    assert gamma_binary_ids(rows) == ["0xbin"]


def test_complete_set_from_event_with_three_markets():
    events = [
        {
            "id": "42",
            "title": "Who wins?",
            "active": True,
            "closed": False,
            "enableNegRisk": True,
            "markets": [
                {"conditionId": "0x1", "acceptingOrders": True},
                {"conditionId": "0x2", "acceptingOrders": True},
                {"conditionId": "0x3", "acceptingOrders": True},
            ],
        },
        {
            "id": "99",
            "title": "sports props",
            "enableNegRisk": False,
            "markets": [
                {"conditionId": "0xa", "acceptingOrders": True},
                {"conditionId": "0xb", "acceptingOrders": True},
                {"conditionId": "0xc", "acceptingOrders": True},
            ],
        },
        {
            "id": "1",
            "title": "binary only",
            "enableNegRisk": True,
            "markets": [
                {"conditionId": "0x9", "acceptingOrders": True},
                {"conditionId": "0x8", "acceptingOrders": True},
            ],
        },
    ]
    targets = complete_set_targets_from_gamma_events(events, limit=5)
    assert len(targets) == 1
    assert targets[0].kind == "complete_set"
    assert targets[0].event_id == "event:42"
    assert targets[0].condition_ids == ("0x1", "0x2", "0x3")


def test_complete_set_skips_oversized_neg_risk_event():
    markets = [{"conditionId": f"0x{i}", "acceptingOrders": True} for i in range(20)]
    events = [{"id": "big", "title": "huge field", "enableNegRisk": True, "markets": markets}]
    assert complete_set_targets_from_gamma_events(events, limit=5, max_outcomes=12) == []


def test_binary_targets_dedupe():
    targets = binary_targets(["0xa", "0xa", "0xb"])
    assert [t.event_id for t in targets] == ["0xa", "0xb"]


def test_live_binary_target_requires_two_tokens():
    row = {
        "condition_id": "0xbin",
        "active": True,
        "closed": False,
        "accepting_orders": True,
        "question": "q",
        "tokens": [{"token_id": "yes"}, {"token_id": "no"}],
    }
    target = live_binary_target(row)
    assert target is not None
    assert target.token_ids == ("yes", "no")
    assert live_binary_target({**row, "closed": True}) is None


def test_rank_and_select_walkable_skips_raw_below_floor():
    asks = parse_ask_map({"y1": {"SELL": "0.40"}, "n1": "0.40", "y2": {"SELL": "0.52"}, "n2": "0.52"})
    cheap = ScanTarget(
        kind="binary",
        event_id="cheap",
        question="cheap",
        condition_ids=("cheap",),
        token_ids=("y1", "n1"),
    )
    rich = ScanTarget(
        kind="binary",
        event_id="rich",
        question="rich",
        condition_ids=("rich",),
        token_ids=("y2", "n2"),
    )
    ranked = rank_targets_by_raw_edge([rich, cheap], asks)
    assert ranked[0].event_id == "cheap"
    assert ranked[0].raw_edge == Decimal("0.20")
    walk = select_walkable(ranked, Decimal("0.005"), limit=10, skip_below_floor=True)
    assert [item.event_id for item in walk] == ["cheap"]


def test_build_screen_tape_keeps_booking_skip_and_counts_below_floor():
    asks = parse_ask_map(
        {
            "y1": {"SELL": "0.40"},
            "n1": "0.40",
            "y2": {"SELL": "0.52"},
            "n2": "0.52",
            "y3": {"SELL": "0.60"},
            "n3": "0.60",
        }
    )
    cheap = ScanTarget("binary", "cheap", "cheap", ("cheap",), ("y1", "n1"))
    mid = ScanTarget("binary", "mid", "mid", ("mid",), ("y2", "n2"))
    rich = ScanTarget("binary", "rich", "rich", ("rich",), ("y3", "n3"))
    ranked = rank_targets_by_raw_edge([cheap, mid, rich], asks)
    tape = build_screen_tape(
        ranked,
        [],
        floor=Decimal("0.005"),
        walk_binary_limit=10,
        walk_group_limit=0,
        skip_below_floor=True,
    )
    assert tape.screened_n == 3
    assert tape.below_floor_n == 2
    assert [item.event_id for item in tape.walk_targets] == ["cheap"]
    assert {item.event_id for item in tape.below_floor_targets} == {"mid", "rich"}
    assert tape.best_binary == Decimal("0.20")
    assert tape.best_set is None
    assert sorted(tape.raw_edges) == [Decimal("-0.20"), Decimal("-0.04"), Decimal("0.20")]
