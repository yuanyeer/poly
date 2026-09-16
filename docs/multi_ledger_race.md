# Multi-ledger race rules (freeze 2026-09-16) — **`whiskas-inv`**

> **Finance freeze FINAL (2026-09-16).**
>
> Race is the **`whiskas-inv`** ledger (**allow-list `whiskas_inventory`**).
> Start **2300 USD**. Per-round cap **1200 USD**. Paper only.
>
> **`arb-main` / `main_arb`:** booking **paused** (read-only scan OK).
> Copy ledgers (`copy-<leader>` / `copy:<leader>`) and the watchlist remain
> **DISABLED**. Runtime gate (#12): `copy.enabled: false` skips watchlist,
> copy ledgers, and `MirrorExecutor`. Do not delete historical ids below;
> they are struck, not live.
>
> Inventory rules: [`whiskas_inventory_rules.md`](whiskas_inventory_rules.md).

## Goal
The racing paper ledger is **`whiskas-inv`**, start **2300 USD**.
Rank by that ledger's equity / PnL. Do **not** fabricate fills.

`distance_to_2000` was the old **`main_arb`** 1000 → 2000 report field.
It is **not** the `whiskas-inv` race target.

## Ledgers

1. **`whiskas-inv`** — **LIVE / main race.** `whiskas_inventory` paper pairing
2. **arb-main / `main_arb`** — **booking paused** (read-only scan OK). Lock-arb
   / maker floors unchanged but do **not** book
3. ~~**copy-\<leader\>** — one ledger per watchlist leader~~ — **DISABLED /
   paused**

Watchlist (paused): ~~`x-MoneyForWhiskas`~~, ~~`0xcd30457c79`~~,
~~`goldfisherrr`~~. No follow. No copy-ledger race. No copy mirror.

No cross-ledger cash, positions, exposure, or PnL sharing.

## Per-ledger risk (own equity only)

Applies to the live **`whiskas-inv`** race ledger:

- Per-round notional cap **$1200**
- Clip **50 shares**; buy **≤89¢**; combo Up+Down ask sum **≤105¢**
- REVIEW: dd ≥ **10%** OR equity < **2070** → escalate, keep scanning `whiskas-inv`
- HARD: dd ≥ **25%** OR equity < **1725** → SKIP `whiskas-inv`
- ~~Copy chase ≤ 1¢ on copy ledgers~~ — **DISABLED**
- ~~Copy stop-follow + rescan~~ — **DISABLED**

`arb-main` has no live booking; its historical 25% / 40% / ≤3 and
REVIEW **10% / <900** / HARD **25% / <750** gates are **not** the race
gates while booking is paused.

## Session (ops frozen)
**24h paper.** There is **no America/New_York 08:00–23:00 (or 09:00–22:00)
session gate.** Default is a continuous session: **24h** / **00:00–24:00 ET**.
The previous ET window is superseded.

- `booked=0` escalate is **calendar continuous 24h**. Off-hours are no longer
  excluded, because there are no off-hours.
- ~~Copy ledgers may scan continuously so they can mirror 24h leaders.~~
  Copy ledgers and watchlist are **paused**.
- `arb-main` may keep a read-only scan; it must **not** book.

Lock-arb edge floors (`MIN_EDGE_TAKER` 0.5¢ / `MIN_EDGE_MAKER` 0.2¢) are
unchanged and unused for booking while `arb-main` is paused.

## Reporting
`SUMMARY` / `DAILY` must split by account / ledger_id: cash, equity, PnL,
review/halt flags, plus `RANK` / `WINNER` (report only; no fabricated fills).
Race rank is **`whiskas-inv`**. Historical `copy-*` files and `arb-main`
fills may exist on disk; they are **not** the live race book.
