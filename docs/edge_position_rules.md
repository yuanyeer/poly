# Poly paper trading — edge & position rules (v1 freeze 2026-09-16)

Aligned with poly金融 allow/deny list. 加密算法师: hang these as validators on paper ledger fills.

This file is the frozen source of truth for paper-mode edge, fee, depth-walk, and position gates. Thresholds and formulas below must not be loosened.

## Constants

- `START_BALANCE = 200` USD (paper only)
- `TARGET_BALANCE = 1000` (milestone)
- `MAX_NOTIONAL_FRAC = 0.25`  # per trade vs current cash
- `MAX_EVENT_EXPOSURE_FRAC = 0.40`  # sum notional same event vs cash
- `MAX_OPEN_OPPS = 3`
- `MIN_EDGE_TAKER = 0.005`  # 0.5¢ — lock arb (YES+NO / complete-set) only
- `MIN_EDGE_MAKER = 0.002`  # 0.2¢
- `COPY_MAX_CHASE = 0.01`  # 1¢ per share; copy-follow legs only (see `docs/copy_follow_rules.md`)

## Fee (CLOB V2 style)

From `getClobMarketInfo(condition_id).fd`:

- `fee_rate = fd.r`, `fee_exp = fd.e` (default treat as quadratic curve if e≈2)
- if `fd.to` (taker-only): makers pay 0
- per fill leg: `fee = size * fee_rate * p * (1 - p)`  # p = fill price in [0,1]

Do not use book best alone; walk depth.

## Depth walk

```
def walk_asks(book, size):
    cost, filled = 0, 0
    for level in book.asks:  # ascending price
        take = min(level.size, size - filled)
        cost += take * level.price
        filled += take
        if filled >= size: break
    if filled < size: return None  # insufficient depth
    return cost  # total USDC to buy `size` shares
```

Same for bids when selling.

## Allowed strategies

### A) YES+NO lock (binary)

Buy YES size S and NO size S (same condition), both as taker walking asks:

```
cost = walk_asks(yes_book, S) + walk_asks(no_book, S)
fee  = fee(yes_fills) + fee(no_fills)
edge = S - cost - fee   # redeem pays S when complementary
# open iff edge/S >= MIN_EDGE_TAKER and size gates pass
```

### B) Multi-outcome complete set

For mutually exclusive exhaustive outcomes o1..ok of one event:

```
cost = sum(walk_asks(book_i, S) for i)
fee  = sum(fees)
edge = S - cost - fee
# open iff edge/S >= MIN_EDGE_TAKER
```

### C) Maker spread / rebate

Post-only quotes only when:

- expected net edge after adverse selection / inventory skew >= MIN_EDGE_MAKER
- inventory risk within event exposure cap
- never cross the spread (post-only)

Paper fill: match only when live book trades through our price (or sim fill model agreed with eng).

### D) Copy-follow (newly allowed; paper-only hooks)

Source of truth: [`docs/copy_follow_rules.md`](copy_follow_rules.md). Lock arb (YES+NO / complete-set) and maker floors above are unchanged. Observation hooks: `docs/copy_trading.md`.

Copy legs have no YES+NO lock edge. The chase gate **replaces `MIN_EDGE_TAKER` for copy legs only**:

```
# reject fill if
abs(fill_px - leader_px) + fee/size > COPY_MAX_CHASE
# COPY_MAX_CHASE = 0.01 (1¢) per share
```

Do not apply `MIN_EDGE_TAKER` (0.5¢) to copy legs. Do not apply `COPY_MAX_CHASE` to lock-arb or maker legs.

- Sleeve ≤ 30% of equity; 25% / 40% / ≤3 concurrent still apply
- Stop-follow: leader peak_dd ≥ 5% OR path_dd ≥ 5% OR month_pnl < 0
- Rescan replacements must have peak **and** path dd < 5% and still be profitable

## Position gates (all must pass)

```
def can_open(balance, event_exposure, open_opps, notional, event_id):
    if open_opps >= MAX_OPEN_OPPS: return False
    if notional > balance * MAX_NOTIONAL_FRAC: return False
    if event_exposure[event_id] + notional > balance * MAX_EVENT_EXPOSURE_FRAC: return False
    return True
```

## Forbidden

- Directional unhedged bets
- Cross-event unhedged narrative books
- Edge computed on top-of-book without depth walk
- Sweeping illiquid / near-resolution books
- Mutating ledger balance by hand / fake fills
- Any live/real-money order in this phase

## Ledger

Single local paper ledger; every fill: cash/position/PnL update from walked price + fee + modeled slippage only.

## 旁注 / ops note (clocks & kill triggers)

Paper-only operational stop/review notes. They do **not** change edge floors, fee formulas, or position gates above.

1. **Trading window (ops finalized)** — Default window is **America/New_York 08:00–23:00** (follows DST; roughly **UTC 12:00–03:00** EDT / **13:00–04:00** EST). **Not 24h.** China-local wall clock is **not** authoritative.

2. **连续 24h booked=0 (escalate)** — Escalate / strategy-review when `booked=0` accumulates to ~24h. The meter is still **cumulative time inside this trading window only** (**America/New_York 08:00–23:00**). Off-hours (scanner stopped / outside NY 08:00–23:00) do **not** count toward the 24h. In practice this is about two consecutive NY sessions of continuous `booked=0`. Calendar / China-local wall-clock days are not the meter.

3. **Drawdown — two tiers (do not collapse)** — Live, real time: compare current paper ledger equity vs peak. This watch does **not** pause outside the trading window.

   - **Escalate / REVIEW** (ask **poly金融**): peak drawdown **≥ 10%** **OR** equity **< 180**. **Continue scanning; do NOT hard-stop.** This is the review gate only. 180 must never hard-stop alone.
   - **Hard halt / SKIP**: peak drawdown **≥ 25%** **OR** equity **< 150**. Stops trading. **150 is intentionally below 180** so the review floor and the halt floor do not collide. The 25% / 150 halt does **not** replace the 10% / 180 REVIEW line.

## Trading session (implemented)

Default window is **America/New_York 08:00–23:00 local**. `zoneinfo` honors DST (EST/EDT). The interval is `[start, end)` on the local clock. Weekends use the same hours.

- Encoded in `config/paper.yaml` → `session` so hours can be edited without code changes.
- **Not 24h trading.** Outside the window `poly-paper --loop` must stop scanning (idle / sleep; log `SKIP session_closed`).
- Continuous `booked=0` **escalate** still uses **cumulative trading-window time** only (**America/New_York 08:00–23:00**), **not** wall-clock 24h. Overnight idle from `end`→next `start` (NY 23:00–08:00) does **not** increment the streak. After `idle_zero_fill_sessions` (default 2) in-window sessions with zero books, log `TRIGGER idle_zero_fill`.
- Drawdown watches **live ledger equity vs peak** on every cycle, including off-hours (`(peak − equity) / peak`). Two tiers — do not collapse:
  - **Escalate / REVIEW** (ask **poly金融**): peak drawdown ≥ **10%** OR equity < **180**. **Continue scanning; do NOT hard-stop.**
  - **Hard halt / SKIP**: peak drawdown ≥ **25%** (`drawdown_halt_pct`) OR equity < **150**. Stops scanning (`SKIP drawdown_halt`) even while the session is open. **150 is intentionally below 180** so the floors do not collide.

## Daily scan quality

Every `DAILY` line includes:

- `below_floor_n`: count of scanned markets whose best post-fee + depth-walk per-share net edge is below the applicable floor (still counted).
- `median_net_edge`: median of those same per-share net edges, **including** below-floor prints.

UTC day window for fills; edge tape resets on UTC date rollover.
