# Multi-ledger race rules (freeze 2026-09-16) — **`whiskas-inv` race**

> **Copy ledgers DISABLED (finance freeze 2026-09-16).**
>
> Race is the **`whiskas-inv`** inventory ledger (start **2300 USD**).
> **`arb-main` booking is paused** (read-only SCREEN may continue). Copy
> ledgers (`copy-<leader>` / `copy:<leader>`) and the watchlist are **paused**
> until **poly金融** re-opens the type. Runtime gate: `copy.enabled: false`
> skips watchlist, copy ledgers, and `MirrorExecutor`. Do not delete historical
> ids below; they are struck, not live.
>
> This is **not** copy-follow. See [`whiskas_inventory_rules.md`](whiskas_inventory_rules.md).

## Goal
The racing paper ledger is **`whiskas-inv`**, start **2300 USD**. Finance did
not set a new numeric target — do **not** invent one. Rank / SUMMARY keep
distance-to-target style (`distance_to_start` / pnl / equity / per-round cap
**1200**). Historical `arb-main` still reports `distance_to_2000` (1000 → 2000)
as a paused reference line.

## Ledgers
Implemented / historical ids: **whiskas-inv**, **arb-main** (docs freeze also
called `main_arb`) and ~~**copy-\<leader\>**~~ (docs freeze also called
~~`copy:<leader>`~~, e.g. ~~`copy-x-MoneyForWhiskas`~~).

1. **whiskas-inv** — **LIVE race.** BTC 5m Up/Down inventory / pairing
2. **arb-main / `main_arb`** — **BOOKING PAUSED.** YES+NO / complete-set / maker
   scan may stay read-only
3. ~~**copy-\<leader\>** — one ledger per watchlist leader~~ — **DISABLED /
   paused** until finance re-opens the type

Watchlist (paused): ~~`x-MoneyForWhiskas`~~, ~~`0xcd30457c79`~~,
~~`goldfisherrr`~~. No follow. No copy-ledger race.

No cross-ledger cash, positions, exposure, or PnL sharing.

## Per-ledger risk (own equity only)
Applies to the live **`whiskas-inv`** ledger (inventory knobs, not lock-arb 25/40/3):

- Clip **50** shares; max buy **0.89**; combo Up+Down ≤ **1.05**
- Per-round notional cap **1200 USD**
- REVIEW: dd ≥ 10% or equity < **2070** → escalate, keep scanning `whiskas-inv`
- HARD: dd ≥ 25% or equity < **1725** → SKIP `whiskas-inv`
- Paused **`arb-main`** keeps its historical lock-arb lines (25% / 40% / ≤3,
  REVIEW **10% / 900**, HARD **25% / 750**) if booking is ever re-opened
- ~~Copy chase ≤ 1¢ on copy ledgers (no global 30% sleeve)~~ — **DISABLED**
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
distance-to-target style (`distance_to_start` on `whiskas-inv` until a target
is configured; `distance_to_2000` on paused `arb-main`), per-round cap,
`screened_n`, `below_floor_n`, `median_net_edge`,
`median_net_edge_kind=raw|walked`, `best_binary` / `best_set`, review/halt
flags, plus `RANK` / `WINNER` (report only; no fabricated fills; no WINNER
without a configured target).

While copy is DISABLED, the racing account is **`whiskas-inv`**. `arb-main`
booking is paused. Historical `copy-*` files may exist on disk; they are
**not** in the race.
