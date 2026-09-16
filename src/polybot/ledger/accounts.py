from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from polybot.config import PaperConfig, copy_runtime_enabled
from polybot.ledger.store import PaperLedger
from polybot.risk.gates import RiskEngine
from polybot.types import LedgerState

ARB_MAIN_ID = "arb-main"
AccountKind = Literal["arb", "copy"]


def copy_account_id(leader_id: str) -> str:
    return f"copy-{leader_id}"


def copy_ledger_path(arb_path: Path, leader_id: str) -> Path:
    return arb_path.parent / f"{copy_account_id(leader_id)}.jsonl"


@dataclass
class PaperAccount:
    """One isolated paper ledger. Never shares cash, exposure, or sleeve."""

    account_id: str
    kind: AccountKind
    leader_id: str | None
    ledger: PaperLedger
    risk: RiskEngine
    paused: bool = False

    def state(self) -> LedgerState:
        return self.ledger.state()


@dataclass
class AccountBook:
    accounts: list[PaperAccount]

    def get(self, account_id: str) -> PaperAccount:
        for account in self.accounts:
            if account.account_id == account_id:
                return account
        raise KeyError(account_id)

    def arb(self) -> PaperAccount:
        return self.get(ARB_MAIN_ID)

    def copy_for(self, leader_id: str) -> PaperAccount | None:
        wanted = copy_account_id(leader_id)
        for account in self.accounts:
            if account.account_id == wanted:
                return account
        return None

    def copy_accounts(self) -> list[PaperAccount]:
        return [account for account in self.accounts if account.kind == "copy"]

    def ranked(self) -> list[tuple[int, PaperAccount, LedgerState]]:
        rows = [(account, account.state()) for account in self.accounts]
        rows.sort(key=lambda item: item[1].equity, reverse=True)
        return [(index, account, state) for index, (account, state) in enumerate(rows, start=1)]

    def winner(self, target) -> PaperAccount | None:
        for _rank, account, state in self.ranked():
            if state.equity >= target:
                return account
        return None


def open_account_book(
    config: PaperConfig,
    arb_ledger: PaperLedger | None = None,
) -> AccountBook:
    """Open arb-main. Copy ledgers are created only when copy.enabled is true."""
    arb_path = arb_ledger.path if arb_ledger is not None else config.ledger_path
    arb = PaperAccount(
        account_id=ARB_MAIN_ID,
        kind="arb",
        leader_id=None,
        ledger=arb_ledger or PaperLedger(arb_path, config.starting_balance),
        risk=RiskEngine(config),
    )
    accounts = [arb]
    if copy_runtime_enabled(config.copy):
        for leader in config.copy.leaders:
            path = copy_ledger_path(arb_path, leader.id)
            accounts.append(
                PaperAccount(
                    account_id=copy_account_id(leader.id),
                    kind="copy",
                    leader_id=leader.id,
                    ledger=PaperLedger(path, config.starting_balance),
                    risk=RiskEngine(config),
                )
            )
    return AccountBook(accounts=accounts)
