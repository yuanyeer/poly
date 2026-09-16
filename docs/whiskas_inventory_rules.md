# Whiskas inventory strategy (frozen 2026-09-16) — paper only

> **FROZEN** by poly金融 (FINAL). Allow-list name: `whiskas_inventory`.
> Ledger: **`whiskas-inv`** — **main race ledger**.
> Paper only. Do **not** send live chain orders.
>
> This is an **inventory / pairing** strategy, **not** copy-follow. It is
> **not** a re-open of the disabled `x-MoneyForWhiskas` watchlist, copy ledger,
> or mirror path. Copy-trading remains **DISABLED** (see
> [`copy_follow_rules.md`](copy_follow_rules.md) and
> [`copy_trading.md`](copy_trading.md)).

Source: public trade tape reverse-engineer of x-MoneyForWhiskas on Polymarket BTC 5m Up/Down. Not his public config. Not copy-splitting into two directional legs. Runtime knobs: `config/paper.yaml` → `whiskas`.

## Intent
Inventory / pairing: buy BOTH Up and Down each BTC 5m round. Pairing (~80–90% of shares) cushions; profit mainly from residual (~9–17%). NOT the "80¢ one-shot lead-side" play.

## Timing
- Start: **+6s** after round open
- Stop: when **≤100s** remain (last ~30s almost idle)
- No mid-round sells; exit only via post-settlement redemption of winner

## Order / size
- Market: BTC 5m **Up + Down both sides**
- Clip size: **50 shares** (median on tape), not fixed USD
- Buy price: **≤89¢**
- Cheap leg: may keep buying if it collapses
- Rich / expensive leg: stop at **89¢**
- Combo guard: reject if Up+Down ask sum **> 105¢** (extreme book only; 96.5¢ is full-round VWAP, not simultaneous limit)
- Fill model: paper **walk asks** (eat offer) + fee curve; tape cannot recover maker/taker or resting queue

## Paper capital / race
- Wallet / start: **$2300** (2 overlapping rounds × P90 ~$1095 × 1.05 buffer)
- Per-round notional cap: **$1200**
- **Main race ledger:** `whiskas-inv`
- **`arb-main`:** pause booking (read-only scan OK)
- No cross-ledger cash, positions, exposure, or PnL with `arb-main` or paused copy ledgers

## Risk / accounting
- PnL: paired shares redeem ~$1 per pair; unpaired residual to settlement
- REVIEW: peak drawdown **≥ 10%** OR equity **< 2070** → escalate; keep scanning `whiskas-inv`
- HARD: peak drawdown **≥ 25%** OR equity **< 1725** → SKIP `whiskas-inv`
- 2070 / 1725 are **$2300 × (1 − 10%)** / **$2300 × (1 − 25%)**; do not collapse the two floors

## Forbidden
- 80¢ lead-only / lead-only directional 4:1 bets
- Mid-round sells
- Copy mirror / watchlist follow / copy ledgers
- Live chain orders

## Status
FROZEN — allow-list `whiskas_inventory`, ledger `whiskas-inv` (main race). Paper only. Not copy-follow.
Paper runtime is implemented (`config/paper.yaml` → `whiskas`; `copy.enabled` stays false). Knobs match this freeze.
Acceptance dry-run (recorded book, not live CLOB): `poly-paper --fixture fixtures/whiskas_btc_5m_round.json`. Sample paper fills: `fixtures/whiskas-inv.paper-fills.jsonl`.
