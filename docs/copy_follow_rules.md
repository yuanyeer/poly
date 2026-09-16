# Copy-follow rules v1 — **DISABLED**

> **DISABLED / ENTIRELY REMOVED FROM ALLOW LIST (finance freeze 2026-09-16).**
>
> Copy-trading is **entirely off**: watchlist, copy ledgers (`copy-<leader>` /
> `copy:<leader>`), mirror fills, and stop-follow / rescan are **paused**.
> Distilled inventory rules live in
> [`whiskas_inventory_rules.md`](whiskas_inventory_rules.md) — that is
> **not** a copy-follow re-open. Do **not** treat this file as an allowed
> strategy type.
>
> **Current allow list:** lock arb (YES+NO / complete-set) + maker spread +
> **`whiskas_inventory`** (paper, ledger **`whiskas-inv`**). This file is
> **not** that type.
> **Race:** **`whiskas-inv`**, start **2300**, per-round cap **1200**.
> REVIEW **10% / equity < 2070**. HARD **25% / equity < 1725**.
> **`arb-main` booking paused** (read-only scan OK). Lock-arb floors unchanged
> (`MIN_EDGE_TAKER` 0.5¢ / `MIN_EDGE_MAKER` 0.2¢).
>
> This file is kept for history. Do not delete it. Struck entries below are
> **not** live.

Allowed strategy type ~~added~~ **removed** by poly金融. Lock arb (YES+NO /
complete-set) and maker rules unchanged. **`whiskas_inventory`** is a
separate frozen paper type — not a copy-follow re-open.

## Watchlist (priority) — **PAUSED / DISABLED**

~~1. `x-MoneyForWhiskas` (BTC 5m) — primary; **full-day / 24h activity**~~
~~2. `0xcd30457c79` (BTC 5m)~~
~~3. `goldfisherrr` (BTC 15m)~~

Watchlist is **paused until finance re-opens the type**. No follow. No
successors. No rescan.

## Mirror fill — **DISABLED**

Historical paper rule (do not execute):

On each leader fill (token_id, side, size_hint, leader_px, ts):
1. Wait delay `Δt` (config; default 1–3s paper) to model latency.
2. Walk our book for the same side/outcome with depth walk (not top-of-book).
3. `fill_px = VWAP`; `fee = size * r * p * (1-p)` if taker (`fd.to`).
4. **Chase gate (copy quality):** reject fill if
   `abs(fill_px - leader_px) + fee/size > COPY_MAX_CHASE`
   where `COPY_MAX_CHASE = 0.01` (1¢) per share.
5. Size = min(leader remaining mirror size, risk caps, available depth).

There is no YES+NO lock edge here; the chase gate replaced `MIN_EDGE_TAKER`
for copy legs **when the type was allowed**. It is **not** an allow-list
exception now.

## Position / risk (archived copy ledgers)

Each watchlist leader **had** one independent paper ledger starting at
**1000 USD**. Those copy ledgers are **paused**. There is **no** live copy
sleeve. No cross-ledger cash, positions, exposure, or PnL sharing.

Race **now:** **`whiskas-inv`** (allow-list `whiskas_inventory`), start
**2300**, per-round cap **1200**. **`arb-main` booking paused** (read-only
scan OK). See [`docs/multi_ledger_race.md`](multi_ledger_race.md).

Historical per-copy-ledger risk (paused; not live):
- Per trade notional ≤ 25% of that ledger's cash
- Same-event exposure ≤ 40% of that ledger's cash
- Concurrent open opportunities ≤ 3 on that ledger
- Copy chase ≤ 1¢ on that copy ledger
- REVIEW: peak dd ≥ 10% OR equity < **900** → escalate, keep scanning that ledger
- HARD: peak dd ≥ 25% OR equity < **750** → SKIP that ledger only
- Paper only; no live orders; no hand-edited ledger

`whiskas-inv` uses REVIEW **10% / <2070** and HARD **25% / <1725**.
`arb-main` booking is paused.

## Stop-follow & rescan — **DISABLED**

~~Stop mirroring a leader immediately if any: peak drawdown ≥ 5% / path
drawdown ≥ 5% / month-to-date PnL ≤ 0.~~

Stop-follow and rescan hooks are **paused**. No replacement candidates. No
`STOP_FOLLOW` / `RESCAN_NEEDED` as a live ops path until finance re-opens
the type.

## Trading window

**24h paper (ops frozen).** No America/New_York 08:00–23:00 session gate.
Default is continuous **24h** / **00:00–24:00 ET**. `booked=0` escalate is
calendar continuous 24h.

~~Copy ledgers may scan continuously to mirror 24h leaders.~~ Copy ledgers
and watchlist are **paused**. `whiskas-inv` is the only racing ledger.

## Forbidden

- Blind follow / addresses not on watchlist
- Pure discretionary directional bets outside mirror path
- Ignoring delay, depth, or fees
- Live money / ledger mutation
- **Any copy-follow / watchlist / mirror / copy-ledger activity while this
  type is DISABLED**
