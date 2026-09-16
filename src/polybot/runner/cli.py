from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from polybot.config import load_config
from polybot.ledger.store import PaperLedger
from polybot.market.client import LiveOrderForbidden
from polybot.runner.paper import PaperRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poly-paper",
        description="Polymarket paper-trading loop (read-only CLOB data, local ledger only).",
    )
    parser.add_argument("--config", default=None, help="Path to paper YAML (default: config/paper.yaml)")
    parser.add_argument("--once", action="store_true", help="Scan once and exit (default; dry-run safe)")
    parser.add_argument("--loop", action="store_true", help="Poll forever (still paper-only, no live orders)")
    parser.add_argument("--max-loops", type=int, default=None, help="Stop after N cycles")
    parser.add_argument("--ledger", default=None, help="Override ledger JSONL path")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.live:
        print("ERROR: live/real-money mode is not implemented and is forbidden.", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        for noisy in ("httpx", "httpcore", "hpack"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        config = load_config(args.config)
        if args.ledger:
            config = replace(config, ledger_path=Path(args.ledger))
        ledger = PaperLedger(config.ledger_path, config.starting_balance)
        runner = PaperRunner(config, ledger=ledger)
        once = not args.loop and args.max_loops is None
        if args.once:
            once = True
        if args.loop and not args.once:
            print(
                f"paper loop on {config.clob_host} every {config.poll_interval_seconds:.0f}s "
                f"(Ctrl+C to stop). No live orders.",
                flush=True,
            )
        report = runner.run_forever(max_loops=args.max_loops, once=once)
    except LiveOrderForbidden as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("--- paper cycle ---")
    for line in report.messages:
        print(line)
    print(
        f"scanned={report.scanned} candidates={report.candidates} "
        f"booked={report.booked} skipped={report.skipped} "
        f"rejected_edge={report.rejected_edges} rejected_risk={report.rejected_risk}"
    )
    if report.summary:
        print(report.summary)
    if report.daily_summary:
        print(report.daily_summary)
    print(
        "No real CLOB orders were sent. Target 1000 USD is a report-only milestone; "
        "fills are written only when live depth + fees clear the edge floors."
    )
    return 0
