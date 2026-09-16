from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from polybot.config import PaperConfig, copy_runtime_enabled, whiskas_runtime_enabled
from polybot.ledger.store import PaperLedger
from polybot.risk.gates import RiskEngine
from polybot.types import LedgerState

ARB_MAIN_ID = "arb-main"
WHISKAS_INV_ID = "whiskas-inv"
AccountKind = Literal["arb", "copy", "inventory"]


def copy_account_id(leader_id: str) -> str:
    return f"copy-{leader_id}"


def copy_ledger_path(arb_path: Path, leader_id: str) -> Path:
    return arb_path.parent / f"{copy_account_id(leader_id)}.jsonl"


def whiskas_ledger_path(config: PaperConfig, arb_path: Path) -> Path:
    if config.whiskas is not None and config.whiskas.ledger_path is not None:
        return Path(config.whiskas.ledger_path)
    return arb_path.parent / "whiskas-inv.jsonl"


def race_primary_id(config: PaperConfig) -> str:
    if whiskas_runtime_enabled(config.whiskas) and config.whiskas is not None:
        explicit = (config.race_primary_account or "").strip()
        if explicit and explicit != ARB_MAIN_ID:
            return explicit
        if explicit == ARB_MAIN_ID and not config.whiskas.pause_arb_main_booking:
            return ARB_MAIN_ID
        return config.whiskas.account_id
    return (config.race_primary_account or "").strip() or ARB_MAIN_ID


def race_target(config: PaperConfig, account_id: str) -> Decimal | None:
    if whiskas_runtime_enabled(config.whiskas) and config.whiskas is not None:
        if account_id == config.whiskas.account_id:
            return config.whiskas.target_balance
    if account_id == ARB_MAIN_ID or account_id.startswith("copy-"):
        return config.target_balance
    return config.target_balance


def drawdown_params(config: PaperConfig, account_id: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if whiskas_runtime_enabled(config.whiskas) and config.whiskas is not None:
        if account_id == config.whiskas.account_id:
            whiskas = config.whiskas
            return (
                whiskas.drawdown_review_pct,
                whiskas.drawdown_halt_pct,
                whiskas.drawdown_review_floor_usd,
                whiskas.drawdown_halt_floor_usd,
            )
    return (
        config.drawdown_review_pct,
        config.drawdown_halt_pct,
        config.drawdown_review_floor_usd,
        config.drawdown_halt_floor_usd,
    )


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

    def whiskas(self) -> PaperAccount | None:
        for account in self.accounts:
            if account.kind == "inventory":
                return account
        return None

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

    def winner(self, target, *, targets: dict[str, Decimal | None] | None = None) -> PaperAccount | None:
        for _rank, account, state in self.ranked():
            goal = targets.get(account.account_id) if targets is not None else target
            if goal is not None and state.equity >= goal:
                return account
        return None


def open_account_book(
    config: PaperConfig,
    arb_ledger: PaperLedger | None = None,
) -> AccountBook:
    """Open arb-main. Optionally whiskas-inv. Copy ledgers only when copy.enabled."""
    arb_path = arb_ledger.path if arb_ledger is not None else config.ledger_path
    pause_arb = whiskas_runtime_enabled(config.whiskas) and bool(
        config.whiskas and config.whiskas.pause_arb_main_booking
    )
    arb = PaperAccount(
        account_id=ARB_MAIN_ID,
        kind="arb",
        leader_id=None,
        ledger=arb_ledger or PaperLedger(arb_path, config.starting_balance),
        risk=RiskEngine(config),
        paused=pause_arb,
    )
    accounts = [arb]
    if whiskas_runtime_enabled(config.whiskas) and config.whiskas is not None:
        path = whiskas_ledger_path(config, arb_path)
        accounts.append(
            PaperAccount(
                account_id=config.whiskas.account_id,
                kind="inventory",
                leader_id=None,
                ledger=PaperLedger(path, config.whiskas.starting_balance),
                risk=RiskEngine(config),
            )
        )
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
