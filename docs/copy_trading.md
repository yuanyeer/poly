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
| 1 | `x-MoneyForWhiskas` | BTC 5m | primary leader |
| 2 | `0xcd30457c79` | BTC 5m | backup |
| 3 | `goldfisherrr` | BTC 15m | backup |

## Limits

- Copy sleeve notional ≤ **30% of paper equity**
- Existing caps still apply to any future mirror intent: single trade ≤ 25% of
  cash, same event ≤ 40% of cash, ≤ 3 concurrent opens
- Arb edge floors stay at 0.5¢ taker / 0.2¢ maker
- Mirror chase: abandon if `|fill_px − leader_px| + fee/share` **> 0.01 (1¢)**
- Session default is America/New_York **08:00–23:00** (not 24h). TODO: may later
  narrow from activity histograms of the three watchlist leaders.

## Stop-follow → rescan

`CopyMonitor` reads a `LeaderMetrics` snapshot (`peak_dd`, `path_dd`,
`month_pnl`, `last_seen_active`). A later scanner can feed the
`MetricsProvider` interface; paper tests use a JSON / in-memory stub.

Stop when **any** of:

- leader `peak_dd` ≥ 5%
- leader `path_dd` ≥ 5%
- leader `month_pnl` **≤ 0** (zero stops follow)

On trip: mark that leader **inactive**, emit `STOP_FOLLOW` and `RESCAN_NEEDED`.
The rescan hook requests replacements with `peak_dd` **and** `path_dd` **< 5%**
that are still profitable. The default hook only logs the request — it does
**not** invent a live candidate scanner.

## Mirror executor (stub)

`MirrorExecutor` is a paper stub: it never posts CLOB orders and never
appends ledger fills. It **does** enforce the 算法 v1 chase gate and
sleeve / risk caps.

After delay Δt, walk our book; `fill_px = VWAP(depth)`; fee per `fd`.
**Abandon** (do not copy) if:

```
|fill_px − leader_px| + fee/share > 0.01   # 1¢
```

A real mirror (not implemented) must still:

1. apply observed **delay** vs the leader fill
2. **walk book depth** (never top-of-book only)
3. apply CLOB **fees** (`fd.r` / `fd.to`)
4. refuse if chase > 1¢, sleeve, or the existing 25% / 40% / ≤3 gates would fail
