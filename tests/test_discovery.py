from __future__ import annotations

from polybot.market.discover import (
    binary_targets,
    complete_set_targets_from_gamma_events,
    gamma_binary_ids,
    paginate_clob,
    rows_from_clob_payload,
)


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
            "markets": [
                {"conditionId": "0x1", "acceptingOrders": True},
                {"conditionId": "0x2", "acceptingOrders": True},
                {"conditionId": "0x3", "acceptingOrders": True},
            ],
        },
        {
            "id": "1",
            "title": "binary only",
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


def test_binary_targets_dedupe():
    targets = binary_targets(["0xa", "0xa", "0xb"])
    assert [t.event_id for t in targets] == ["0xa", "0xb"]
