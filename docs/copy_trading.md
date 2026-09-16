# Copy-trading observation (paper-only)

poly金融 allowed a new strategy type: **copy-trading（观察 → 小仓纸面）**.
Existing YES+NO / complete-set / maker-spread arb is unchanged. Edge floors,
fee formulas, and the 25% / 40% / ≤3 concurrent gates are **not** loosened.

This repo ships **observation hooks only**. There is no wallet scraper, no
mirror fill writer, and no live order path.

## Watchlist

Configured in `config/copy.yaml` (referenced from `config/paper.yaml` → `copy.path`).
Leader **display names are config keys**. Wallet / proxy-wallet address mapping
is a **TODO** — do not invent addresses.

| Priority | Key | Tag | Role |
| --- | --- | --- | --- |
| 1 | `x-MoneyForWhiskas` | BTC 5m | primary leader; **full-day / 24h** |
| 2 | `0xcd30457c79` | BTC 5m | backup |
| 3 | `goldfisherrr` | BTC 15m | backup |

## Session

**24h (ops frozen).** No ET 08:00–23:00 gate. Copy observation / future mirror
hooks **may scan continuously** so they can follow `x-MoneyForWhiskas` full-day
activity. `booked=0` escalate is calendar continuous 24h.

## Limits

- **No global copy-sleeve 30%.** Each watchlist leader has one independent
  paper ledger starting at **1000 USD**. Risk is vs that ledger's own equity.
  Race: first ledger to **2000 USD** wins (`distance_to_2000`). See `docs/multi_ledger_race.md`.
- Existing caps still apply **per ledger**: single trade ≤ 25% of that
  ledger's cash, same event ≤ 40% of that ledger's cash, ≤ 3 concurrent opens
- REVIEW: peak dd ≥ 10% OR equity < **900** → escalate, keep scanning that ledger
- HARD: peak dd ≥ 25% OR equity < **750** → SKIP that ledger only
- Arb edge floors stay at 0.5¢ taker / 0.2¢ maker
- Mirror chase: abandon if `|fill_px − leader_px| + fee/share` **> 0.01 (1¢)**

## Stop-follow → rescan

`CopyMonitor` reads a `LeaderMetrics` snapshot (`peak_dd`, `path_dd`,
`month_pnl`, `last_seen_active`). A later scanner can feed the
`MetricsProvider` interface; paper tests use a JSON / in-memory stub.

Stop when **any** of:

- leader `peak_dd` ≥ 5%
- leader `path_dd` ≥ 5%
- leader `month_pnl` **≤ 0** (zero stops follow)

On trip: mark that leader **inactive**, emit `STOP_FOLLOW` and `RESCAN_NEEDED`,
and **stop that copy ledger only** (other ledgers keep running).
The rescan hook requests replacements with `peak_dd` **and** `path_dd` **< 5%**
that are still profitable. The default hook only logs the request — it does
**not** invent a live candidate scanner.

## Mirror executor (stub)

`MirrorExecutor` is a paper stub: it never posts CLOB orders and never
appends ledger fills. It **does** enforce the 算法 v1 chase gate and
per-ledger risk caps (own equity; no global 30% sleeve).

After delay Δt, walk our book; `fill_px = VWAP(depth)`; fee per `fd`.
**Abandon** (do not copy) if:

```
|fill_px − leader_px| + fee/share > 0.01   # 1¢
```

A real mirror (not implemented) must still:

1. apply observed **delay** vs the leader fill
2. **walk book depth** (never top-of-book only)
3. apply CLOB **fees** (`fd.r` / `fd.to`)
4. refuse if chase > 1¢ or that ledger's 25% / 40% / ≤3 gates would fail
