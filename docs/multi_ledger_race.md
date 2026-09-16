# Multi-ledger race rules (freeze 2026-09-16)

## Goal
Independent paper ledgers start at **1000 USD**. First ledger to **2000 USD** wins. Rank by equity / distance-to-2000.

## Ledgers
Implemented ids: **arb-main** (docs freeze also called `main_arb`) and **copy-\<leader\>** (docs freeze also called `copy:<leader>`), e.g. `copy-x-MoneyForWhiskas`.
1. **arb-main** — YES+NO / complete-set / maker strategies only
2. **copy-\<leader\>** — one ledger per watchlist leader

Watchlist priority: `x-MoneyForWhiskas` first (full-day / 24h), then `0xcd30457c79`, then `goldfisherrr`.

No cross-ledger cash, positions, exposure, or PnL sharing.

## Per-ledger risk (own equity only)
- Trade ≤ 25% of that ledger's cash
- Same-event ≤ 40% of that ledger's cash
- Concurrent opens ≤ 3 on that ledger
- Copy chase ≤ 1¢ on copy ledgers (no global 30% sleeve across ledgers)
- REVIEW: dd ≥ 10% or equity < 900 → escalate, keep scanning that ledger
- HARD: dd ≥ 25% or equity < 750 → SKIP that ledger only
- Copy stop-follow: leader peak/path DD ≥ 5% or month_pnl ≤ 0 → stop that copy ledger + rescan

## Session (ops frozen)
**24h trading.** There is **no America/New_York 08:00–23:00 (or 09:00–22:00) session gate.** Default is a continuous session: **24h** / **00:00–24:00 ET**. The previous ET window is superseded.

- `booked=0` escalate is **calendar continuous 24h**. Off-hours are no longer excluded, because there are no off-hours.
- Copy ledgers **may scan continuously** so they can mirror 24h leaders.
- Priority reason: primary leader `x-MoneyForWhiskas` is **full-day / 24h** activity.

Lock-arb edge floors (`MIN_EDGE_TAKER` 0.5¢ / `MIN_EDGE_MAKER` 0.2¢) are unchanged.

## Reporting
`SUMMARY` / `DAILY` must split by account / ledger_id: cash, equity, PnL, `distance_to_2000`, `below_floor_n`, `median_net_edge`, review/halt flags, plus `RANK` / `WINNER` (report only; no fabricated fills).
