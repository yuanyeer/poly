# Multi-ledger race rules (freeze 2026-09-16) — **single `main_arb`**

> **Copy ledgers DISABLED (finance freeze 2026-09-16).**
>
> Race continues on the **`main_arb`** (`arb-main`) ledger **only**. Copy
> ledgers (`copy-<leader>` / `copy:<leader>`) and the watchlist are **paused**
> until **poly金融** re-opens the type. Runtime gate (#12): `copy.enabled: false`
> skips watchlist, copy ledgers, and `MirrorExecutor`. Do not delete historical
> ids below; they are struck, not live.

## Goal
The racing paper ledger starts at **1000 USD**. First to **2000 USD** wins.
Rank by equity / distance-to-2000.

## Ledgers
Implemented / historical ids: **arb-main** (docs freeze also called
`main_arb`) and ~~**copy-\<leader\>**~~ (docs freeze also called
~~`copy:<leader>`~~, e.g. ~~`copy-x-MoneyForWhiskas`~~).

1. **arb-main / `main_arb`** — **LIVE.** YES+NO / complete-set / maker only
2. ~~**copy-\<leader\>** — one ledger per watchlist leader~~ — **DISABLED /
   paused** until finance re-opens the type

Watchlist (paused): ~~`x-MoneyForWhiskas`~~, ~~`0xcd30457c79`~~,
~~`goldfisherrr`~~. No follow. No copy-ledger race.

No cross-ledger cash, positions, exposure, or PnL sharing.

## Per-ledger risk (own equity only)
Applies to the live **`main_arb`** ledger:

- Trade ≤ 25% of that ledger's cash
- Same-event ≤ 40% of that ledger's cash
- Concurrent opens ≤ 3 on that ledger
- ~~Copy chase ≤ 1¢ on copy ledgers (no global 30% sleeve)~~ — **DISABLED**
- REVIEW: dd ≥ 10% or equity < **900** → escalate, keep scanning `main_arb`
- HARD: dd ≥ 25% or equity < **750** → SKIP `main_arb`
- ~~Copy stop-follow: leader peak/path DD ≥ 5% or month_pnl ≤ 0 → stop that
  copy ledger + rescan~~ — **DISABLED**

## Session (ops frozen)
**24h paper.** There is **no America/New_York 08:00–23:00 (or 09:00–22:00)
session gate.** Default is a continuous session: **24h** / **00:00–24:00 ET**.
The previous ET window is superseded.

- `booked=0` escalate is **calendar continuous 24h**. Off-hours are no longer
  excluded, because there are no off-hours.
- ~~Copy ledgers may scan continuously so they can mirror 24h leaders.~~
  Copy ledgers and watchlist are **paused**.
- ~~Priority reason: primary leader `x-MoneyForWhiskas` is full-day / 24h.~~

Lock-arb edge floors (`MIN_EDGE_TAKER` 0.5¢ / `MIN_EDGE_MAKER` 0.2¢) are
unchanged.

## Reporting
`SUMMARY` / `DAILY` must split by account / ledger_id: cash, equity, PnL,
`distance_to_2000`, `below_floor_n`, `median_net_edge`, review/halt flags,
plus `RANK` / `WINNER` (report only; no fabricated fills).

While copy is DISABLED, the only racing account is **`main_arb`**. Historical
`copy-*` files may exist on disk; they are **not** in the race.
