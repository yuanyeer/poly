# Whiskas inventory strategy (distilled 2026-09-16) — paper only

> **Paper-enabled** under allow-list name `whiskas_inventory`. Runtime books
> only on the isolated **`whiskas-inv`** ledger. **No live / on-chain orders.**
>
> This is a **new inventory / pairing** strategy, **not** copy-follow. It is
> **not** a re-open of the disabled `x-MoneyForWhiskas` watchlist, copy ledger,
> or mirror path. Copy-trading remains **DISABLED** (see
> [`copy_follow_rules.md`](copy_follow_rules.md) and
> [`copy_trading.md`](copy_trading.md)). `copy.enabled` stays **false**.

Source: public trade tape reverse-engineer of x-MoneyForWhiskas on Polymarket BTC 5m Up/Down. Not his public config. Not copy-splitting into two directional legs. Knobs live in `config/paper.yaml` → `whiskas`.

## Intent
Inventory / pairing: buy BOTH Up and Down each round. Pairing (~80–90% of shares) cushions; profit mainly from residual (~9–17%). NOT the "80¢ one-shot lead-side" play.

## Timing
- Start: **6s** after round open (`enter_after_open_seconds`)
- Stop: when **100s** remain (`stop_remaining_seconds`; last ~30s almost idle)
- No mid-round sells; exit only via post-settlement redemption of winner

## Order / size
- Clip size: **50 shares** (median on tape), not fixed USD
- Max buy price: **89¢** (`max_buy_price: 0.89`)
- Cheap leg: may keep buying if it collapses
- Expensive leg: stop at 89¢
- Combo guard: reject if Up+Down ask sum > **105¢** (extreme book only; 96.5¢ is full-round VWAP, not simultaneous limit)

## Paper capital / race
- Account **`whiskas-inv`**: start **$2300** (2 overlapping rounds × P90 ~$1095 × 1.05 buffer)
- Per-round notional cap: **$1200**
- Fill model: walk asks (eat offer) + fee curve; tape cannot recover maker/taker or resting queue
- Finance race is **`whiskas-inv`**. No invented target is configured — report **pnl / equity / caps** and keep distance-to-target style (`distance_to_start` until finance sets a target)
- **`arb-main` booking is paused** (read-only SCREEN / diagnostics may continue)

## Risk / accounting
- Separate paper ledger (`data/whiskas-inv.jsonl`) from lock-arb `arb-main`
- REVIEW (per whiskas-inv): dd ≥ **10%** OR equity < **2070** — escalate, keep scanning
- HARD (per whiskas-inv): dd ≥ **25%** OR equity < **1725** — SKIP that ledger
- PnL: paired shares redeem ~$1 per pair; unpaired residual to settlement
- Forbidden: convert into lead-only directional 4:1 / 80¢ bets; mid-round sells; copy mirror; live chain orders

## Status
Paper path enabled. Copy-trading stays DISABLED. 24h / no ET session gate unchanged.
