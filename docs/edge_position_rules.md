# Poly paper trading — edge & position rules (v1 freeze 2026-09-16)

Aligned with poly金融 allow/deny list. 加密算法师: hang these as validators on paper ledger fills.

This file is the frozen source of truth for paper-mode edge, fee, depth-walk, and position gates. Thresholds and formulas below must not be loosened.

## Constants

- `START_BALANCE = 200` USD (paper only)
- `TARGET_BALANCE = 1000` (milestone)
- `MAX_NOTIONAL_FRAC = 0.25`  # per trade vs current cash
- `MAX_EVENT_EXPOSURE_FRAC = 0.40`  # sum notional same event vs cash
- `MAX_OPEN_OPPS = 3`
- `MIN_EDGE_TAKER = 0.005`  # 0.5¢
- `MIN_EDGE_MAKER = 0.002`  # 0.2¢

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

1. **连续 24h booked=0** — Meter **cumulative configured-trading-window time only**. Off-hours when the scanner is stopped do **not** count toward the 24h. In practice this is about two consecutive trading sessions of continuous `booked=0`. Calendar / wall-clock days are not the meter.

2. **Drawdown** — Still live, real time: compare current paper ledger balance vs peak, with a hard floor of **180** USD. This trigger does **not** pause outside the trading window.

3. **Trading window** — Set by ops (poly 负责人) to crypto-active hours. This doc only refers to the **configured trading window**. China-local wall clock is **not** the authority for when the scanner is on or when the 24h booked=0 meter runs.
