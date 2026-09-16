# Copy-trading observation (paper-only) — **DISABLED**

> **DISABLED / ENTIRELY REMOVED FROM ALLOW LIST (finance freeze 2026-09-16).**
>
> Copy-trading is **entirely off**: watchlist, copy ledgers, mirror executor,
> and stop-follow / rescan are **paused** until **poly金融** re-opens the type.
> Playbook is being distilled separately. Do not treat observation hooks as
> an allowed strategy.
>
> **Current allow list:** lock arb (YES+NO / complete-set) + maker spread only.
> **Race:** **`whiskas-inv`** (start **2300**, no invented target).
> **`arb-main` booking is paused.** 24h paper. Whiskas REVIEW **10% / <2070**,
> HARD **25% / <1725**. Lock-arb floors unchanged. Not a copy-follow re-open.
>
> This file is kept for history. Do not delete it. Struck entries below are
> **not** live.

~~poly金融 allowed a new strategy type: **copy-trading（观察 → 小仓纸面）**.~~
**Removed from the allow list.** Existing YES+NO / complete-set / maker-spread
arb is unchanged and is the **only** allowed set. Edge floors, fee formulas,
and the 25% / 40% / ≤3 concurrent gates are **not** loosened.

This repo still ships historical observation stubs. They are **not** an
ops path: no watchlist follow, no copy-ledger race, no mirror fill writer,
and no live order path.

## Watchlist — **PAUSED / DISABLED**

Configured in `config/copy.yaml` (referenced from `config/paper.yaml` →
`copy.path`) for historical / loader tests only. Leader display names are
config keys. Wallet / proxy-wallet address mapping remains a TODO — do not
invent addresses. **Do not follow any of these until finance re-opens the type.**

| Priority | Key | Tag | Role | Status |
| --- | --- | --- | --- | --- |
| 1 | ~~`x-MoneyForWhiskas`~~ | BTC 5m | ~~primary leader; full-day / 24h~~ | **DISABLED** |
| 2 | ~~`0xcd30457c79`~~ | BTC 5m | ~~backup~~ | **DISABLED** |
| 3 | ~~`goldfisherrr`~~ | BTC 15m | ~~backup~~ | **DISABLED** |

## Session

**24h paper (ops frozen).** No ET 08:00–23:00 gate. `booked=0` escalate is
calendar continuous 24h.

~~Copy observation / future mirror hooks may scan continuously.~~ Copy
observation, watchlist, and copy ledgers are **paused**. Race continues on
**`main_arb` only**.

## Limits

- **No live copy ledgers.** ~~Each watchlist leader has one independent
  paper ledger starting at 1000 USD.~~ Those ledgers are **paused** until
  finance re-opens the type. There is **no** global copy-sleeve 30%.
- **Race:** single **`main_arb`** ledger, start **1000**, first to **2000**
  wins (`distance_to_2000`). See `docs/multi_ledger_race.md`.
- Existing caps still apply on **`main_arb`**: single trade ≤ 25% of cash,
  same event ≤ 40% of cash, ≤ 3 concurrent opens
- REVIEW: peak dd ≥ 10% OR equity < **900** → escalate, keep scanning `main_arb`
- HARD: peak dd ≥ 25% OR equity < **750** → SKIP `main_arb`
- Arb edge floors stay at 0.5¢ taker / 0.2¢ maker
- ~~Mirror chase: abandon if `|fill_px − leader_px| + fee/share` > 0.01 (1¢)~~
  — **DISABLED**

## Stop-follow → rescan — **DISABLED**

`CopyMonitor` / `LeaderMetrics` / `MetricsProvider` stubs may remain in tree
for tests. They are **not** a live ops path.

~~Stop when any of: leader `peak_dd` ≥ 5% / `path_dd` ≥ 5% / `month_pnl` ≤ 0.~~

On a historical trip the hook marked that leader inactive and emitted
`STOP_FOLLOW` + `RESCAN_NEEDED`. **Do not** stop-follow, rescan, or open a
replacement copy ledger while this type is DISABLED.

## Mirror executor (stub) — **DISABLED**

`MirrorExecutor` is a paper stub: it never posts CLOB orders and never
appends ledger fills. While copy-trading is DISABLED, treat any mirror
attempt as **forbidden**, not as a chase-gate decision.

Historical chase gate (archived; not an allow-list exception):

```
|fill_px − leader_px| + fee/share > 0.01   # 1¢
```

A real mirror (not implemented, and **not allowed** until finance re-opens)
would still have required delay, depth walk, CLOB fees, and per-ledger
25% / 40% / ≤3 gates. That is **not** current policy.
