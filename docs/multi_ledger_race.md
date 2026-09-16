# Multi-ledger race rules (freeze 2026-09-16)

## Goal
Independent paper ledgers start at **1000 USD**. First ledger to **2000 USD** wins. Rank by equity / distance-to-2000.

## Ledgers
1. **main_arb** — YES+NO / complete-set / maker strategies only
2. **copy:<leader>** — one ledger per watchlist leader (e.g. `copy:x-MoneyForWhiskas`)

No cross-ledger cash, positions, exposure, or PnL sharing.

## Per-ledger risk (own equity only)
- Trade ≤ 25% of that ledger's cash
- Same-event ≤ 40% of that ledger's cash
- Concurrent opens ≤ 3 on that ledger
- Copy chase ≤ 1¢ on copy ledgers (no global 30% sleeve across ledgers)
- REVIEW: dd ≥ 10% or equity < 900 → escalate, keep scanning that ledger
- HARD: dd ≥ 25% or equity < 750 → SKIP that ledger only
- Copy stop-follow: leader peak/path DD ≥ 5% or month_pnl ≤ 0 → stop that copy ledger + rescan

## Reporting
SUMMARY/DAILY must split by ledger_id: cash, equity, PnL, distance_to_2000, below_floor_n, median_net_edge, review/halt flags.
