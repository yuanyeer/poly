# Copy-follow rules v1 (freeze candidate 2026-09-16)

Allowed strategy type added by poly金融. Lock arb (YES+NO / complete-set) and maker rules unchanged.

## Watchlist (priority)
1. `x-MoneyForWhiskas` (BTC 5m) — primary; **full-day / 24h activity** (reason the project session is 24h)
2. `0xcd30457c79` (BTC 5m)
3. `goldfisherrr` (BTC 15m)

Only these addresses (or successors after rescan). No blind follow.

## Mirror fill
On each leader fill (token_id, side, size_hint, leader_px, ts):
1. Wait delay `Δt` (config; default 1–3s paper) to model latency.
2. Walk our book for the same side/outcome with depth walk (not top-of-book).
3. `fill_px = VWAP`; `fee = size * r * p * (1-p)` if taker (`fd.to`).
4. **Chase gate (copy quality):** reject fill if
   `abs(fill_px - leader_px) + fee/size > COPY_MAX_CHASE`  
   where `COPY_MAX_CHASE = 0.01` (1¢) per share.
5. Size = min(leader remaining mirror size, risk caps, available depth).

There is no YES+NO lock edge here; the chase gate replaces MIN_EDGE_TAKER for copy legs.

## Position / risk (per independent ledger; own equity only)
Each watchlist leader has **one independent paper ledger** starting at **1000 USD**. There is **no global copy-sleeve 30%** across ledgers. No cross-ledger cash, positions, exposure, or PnL sharing.

Risk is vs that ledger's own cash/equity:
- Per trade notional ≤ 25% of that ledger's cash
- Same-event exposure ≤ 40% of that ledger's cash
- Concurrent open opportunities ≤ 3 on that ledger
- Copy chase ≤ 1¢ on that copy ledger
- REVIEW: peak dd ≥ 10% OR equity < **900** → escalate, keep scanning that ledger
- HARD: peak dd ≥ 25% OR equity < **750** → SKIP that ledger only
- Paper only; no live orders; no hand-edited ledger

Race: first ledger to **2000 USD** wins. Rank by equity / `distance_to_2000`. See [`docs/multi_ledger_race.md`](multi_ledger_race.md).

## Stop-follow & rescan
Stop mirroring a leader immediately if any:
- peak drawdown ≥ 5%
- path drawdown ≥ 5%
- month-to-date PnL ≤ 0

A breach **stops only that copy ledger** (other ledgers keep running) and triggers rescan for replacements: still trading, peak & path DD < 5%, and MTD profitable. poly 负责人 owns rescan cadence; engineering owns hooks.

## Trading window
**24h (ops frozen).** No America/New_York 08:00–23:00 session gate. Default is continuous **24h** / **00:00–24:00 ET**. Copy ledgers **may scan continuously** to mirror 24h leaders. Priority: `x-MoneyForWhiskas` full-day activity. `booked=0` escalate is calendar continuous 24h.

## Forbidden
- Blind follow / addresses not on watchlist
- Pure discretionary directional bets outside mirror path
- Ignoring delay, depth, or fees
- Live money / ledger mutation
