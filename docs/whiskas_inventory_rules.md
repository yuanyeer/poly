# Whiskas inventory strategy (distilled 2026-09-16) — paper only

> **DRAFT — not on the allow list.** Waiting on **poly金融** freeze / allow-list
> name `whiskas_inventory`. Do **not** enable runtime, paper booking, or live
> chain orders from this file.
>
> This is a **new inventory / pairing** strategy, **not** copy-follow. It is
> **not** a re-open of the disabled `x-MoneyForWhiskas` watchlist, copy ledger,
> or mirror path. Copy-trading remains **DISABLED** (see
> [`copy_follow_rules.md`](copy_follow_rules.md) and
> [`copy_trading.md`](copy_trading.md)).

Source: public trade tape reverse-engineer of x-MoneyForWhiskas on Polymarket BTC 5m Up/Down. Not his public config. Not copy-splitting into two directional legs.

## Intent
Inventory / pairing: buy BOTH Up and Down each round. Pairing (~80–90% of shares) cushions; profit mainly from residual (~9–17%). NOT the "80¢ one-shot lead-side" play.

## Timing
- Start: ~6s after round open
- Stop: when ~100s remain (last ~30s almost idle)
- No mid-round sells; exit only via post-settlement redemption of winner

## Order / size
- Clip size: **50 shares** (median on tape), not fixed USD
- Max buy price: **89¢**
- Cheap leg: may keep buying if it collapses
- Expensive leg: stop at 89¢
- Combo guard: reject if Up+Down ask sum > **105¢** (extreme book only; 96.5¢ is full-round VWAP, not simultaneous limit)

## Paper capital
- Wallet: **$2300** (2 overlapping rounds × P90 ~$1095 × 1.05 buffer)
- Per-round notional cap: **$1200**
- Fill model: walk asks (eat offer) + fee curve; tape cannot recover maker/taker or resting queue

## Risk / accounting
- Separate paper ledger from lock-arb main if both run
- PnL: paired shares redeem ~$1 per pair; unpaired residual to settlement
- Forbidden: convert into lead-only directional 4:1 bets; live chain orders until finance opens

## Status
DRAFT — waiting poly金融 freeze / allow-list name `whiskas_inventory`.
