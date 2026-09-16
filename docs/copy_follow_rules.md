# Copy-follow rules v1 (freeze candidate 2026-09-16)

Allowed strategy type added by poly金融. Lock arb (YES+NO / complete-set) and maker rules unchanged.

## Watchlist (priority)
1. `x-MoneyForWhiskas` (BTC 5m) — primary
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

## Position / risk (additive)
- Per trade notional ≤ 25% cash
- Same-event exposure ≤ 40% cash
- Concurrent open opportunities ≤ 3
- **Copy sleeve** total exposure ≤ 30% equity
- Paper only; no live orders; no hand-edited ledger

## Stop-follow & rescan
Stop mirroring a leader immediately if any:
- peak drawdown ≥ 5%
- path drawdown ≥ 5%
- month-to-date PnL ≤ 0

Then trigger rescan for replacements: still trading, peak & path DD < 5%, and MTD profitable. poly 负责人 owns rescan cadence; engineering owns hooks.

## Trading window
Default gate: `America/New_York 08:00–23:00` (DST). Not 24h.
TODO / ops placeholder: may later narrow `[start, end)` from leader activity
histograms for `x-MoneyForWhiskas`, `0xcd30457c79`, and `goldfisherrr`.

## Forbidden
- Blind follow / addresses not on watchlist
- Pure discretionary directional bets outside mirror path
- Ignoring delay, depth, or fees
- Live money / ledger mutation
