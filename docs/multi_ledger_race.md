# Paper race rules (freeze 2026-09-16; copy DISABLED)

## Goal
The **single** lock-arb paper ledger `arb-main` starts at **1000 USD**. Target **2000 USD** (report only; no fabricated fills). Field: `distance_to_2000`.

## Ledgers
1. **arb-main** — YES+NO / complete-set / maker strategies only. **This is the only active account.**

**Copy-trading is DISABLED.** Per-leader `copy-<leader>` ledgers, the watchlist, and `MirrorExecutor` are skipped when `copy.enabled: false`. Do not compete copy accounts.

## Risk (arb-main equity only)
- Trade ≤ 25% of cash
- Same-event ≤ 40% of cash
- Concurrent opens ≤ 3
- REVIEW: dd ≥ 10% or equity < 900 → escalate, keep scanning
- HARD: dd ≥ 25% or equity < 750 → SKIP

## Session (ops frozen)
**24h trading.** No America/New_York 08:00–23:00 (or 09:00–22:00) session gate. Default is continuous **24h** / **00:00–24:00 ET**.

- `booked=0` escalate is **calendar / wall-clock continuous 24h**.
- `config/paper.yaml` sets `session.enabled: false`.

Lock-arb edge floors (`MIN_EDGE_TAKER` 0.5¢ / `MIN_EDGE_MAKER` 0.2¢) are unchanged.

## Reporting
`SUMMARY` / `DAILY` for `arb-main`: cash, equity, PnL, `distance_to_2000`, `below_floor_n`, `median_net_edge`, review/halt flags. `RANK` / `WINNER` remain report-only.
