# Poly paper trading — edge & position rules (v1 freeze 2026-09-16)

Aligned with poly金融 allow/deny list. 加密算法师: hang these as validators on paper ledger fills.

This file is the frozen source of truth for paper-mode edge, fee, depth-walk, and position gates. Thresholds and formulas below must not be loosened.

> **Allow list (finance freeze FINAL 2026-09-16):** lock arb (YES+NO /
> complete-set) + maker spread + **`whiskas_inventory`** (paper). Copy-follow
> is **ENTIRELY DISABLED** (watchlist, copy ledgers, mirror, stop-follow /
> rescan). Race is **`whiskas-inv`**: start **2300**, per-round cap **1200**,
> REVIEW **10% / <2070**, HARD **25% / <1725**. **`arb-main` booking paused**
> (read-only scan OK). Lock-arb floors below are unchanged. Inventory rules:
> [`whiskas_inventory_rules.md`](whiskas_inventory_rules.md).

## Constants

- `START_BALANCE = 200` USD (paper only)
- `TARGET_BALANCE = 1000` (milestone)
- `MAX_NOTIONAL_FRAC = 0.25`  # per trade vs current cash
- `MAX_EVENT_EXPOSURE_FRAC = 0.40`  # sum notional same event vs cash
- `MAX_OPEN_OPPS = 3`
- `MIN_EDGE_TAKER = 0.005`  # 0.5¢ — lock arb (YES+NO / complete-set) only
- `MIN_EDGE_MAKER = 0.002`  # 0.2¢
- ~~`COPY_MAX_CHASE = 0.01`~~  # **DISABLED** — historical 1¢ copy-follow chase only; not on the allow list (see `docs/copy_follow_rules.md`)

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

**Live allow list:** A + B + C + E. Section D is **DISABLED** (struck below).
`arb-main` booking is **paused** (A–C scan-only). Live race booking is **E**.

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

### D) ~~Copy-follow (newly allowed; paper-only hooks)~~ — **DISABLED / removed from allow list**

> **Not allowed.** Watchlist, copy ledgers, mirror, and stop-follow / rescan
> are **paused** until poly金融 re-opens the type. Historical text is kept
> below so git history and this freeze file stay readable. Source (disabled):
> [`docs/copy_follow_rules.md`](copy_follow_rules.md). Observation hooks
> (disabled): `docs/copy_trading.md`.

~~Copy legs have no YES+NO lock edge. The chase gate **replaces `MIN_EDGE_TAKER` for copy legs only**:~~

```
# HISTORICAL / DISABLED — do not treat as an allow-list exception
# abs(fill_px - leader_px) + fee/size > COPY_MAX_CHASE
# COPY_MAX_CHASE = 0.01 (1¢) per share
```

Do **not** apply `COPY_MAX_CHASE` to lock-arb or maker legs. Do **not** open
copy legs. Lock-arb still uses `MIN_EDGE_TAKER` (0.5¢); maker still uses
`MIN_EDGE_MAKER` (0.2¢).

- ~~No global copy-sleeve 30%. Each leader has one independent paper ledger @ **1000 USD**.~~ Copy ledgers are **paused**. Race is **`whiskas-inv`** @ **2300 USD** (per-round cap **1200**). **`arb-main` booking paused.** See [`docs/multi_ledger_race.md`](multi_ledger_race.md).
- 25% / 40% / ≤3 concurrent still apply to lock-arb / maker **if** `arb-main` booking is later re-opened (own cash)
- Race REVIEW / HARD: on **`whiskas-inv`**, dd ≥ 10% OR equity < **2070** → escalate, keep scanning; dd ≥ 25% OR equity < **1725** → SKIP `whiskas-inv`
- ~~Stop-follow: leader peak_dd ≥ 5% OR path_dd ≥ 5% OR month_pnl ≤ 0 — stops that copy ledger only + rescan~~ — **DISABLED**
- ~~Chase: abandon if `|fill_px − leader_px| + fee/share` > 0.01 (1¢)~~ — **DISABLED**
- ~~Rescan replacements must have peak and path dd < 5% and still be profitable~~ — **DISABLED**
- ~~Copy ledgers may scan continuously (24h) to mirror full-day leaders; primary is `x-MoneyForWhiskas`~~ — **DISABLED**

### E) Whiskas inventory (paper; `whiskas-inv`) — **FROZEN / allowed**

Allow-list name `whiskas_inventory`. **Not** copy-follow. Source:
[`docs/whiskas_inventory_rules.md`](whiskas_inventory_rules.md).

BTC 5m Up+Down both sides; clip **50 shares**; start **+6s**; stop when
**≤100s** remain; buy **≤89¢**; combo ask sum **≤105¢**; no mid-round sells;
cheap leg may continue, rich leg stops at 89¢; paper walk asks + fee.
Capital **$2300**, per-round cap **$1200**. Main race ledger **`whiskas-inv`**.
`arb-main` booking paused (read-only scan OK).

REVIEW: dd ≥ **10%** OR equity < **2070**. HARD: dd ≥ **25%** OR equity < **1725**.

Forbidden here: 80¢ lead-only; mid sells; copy mirror; live chain.

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
- Copy-follow / watchlist / mirror / copy-ledger activity while that type is **DISABLED**
- 80¢ lead-only / mid-round sells on `whiskas_inventory`
- Live chain orders

## Ledger

Implemented lock-arb paper ledger remains a single local JSONL; every fill: cash/position/PnL update from walked price + fee + modeled slippage only.

**Race (single live book):** **`whiskas-inv`** starts at **2300 USD**; per-round cap **1200 USD**. **`arb-main` booking paused** (read-only scan OK). ~~`copy-<leader>` ledgers per watchlist leader~~ are **DISABLED / paused**. No cross-ledger cash, positions, exposure, or PnL. Source: [`docs/multi_ledger_race.md`](multi_ledger_race.md). Lock-arb numeric floors above are unchanged.

## 旁注 / ops note (clocks & kill triggers)

Paper-only operational stop/review notes. They do **not** change edge floors, fee formulas, or position gates above.

1. **Trading window (ops frozen)** — **24h paper session.** No America/New_York 08:00–23:00 (or 09:00–22:00) gate. Default is continuous **24h** / **00:00–24:00 ET**. The prior ET window is **superseded**. China-local wall clock is **not** authoritative. ~~Copy ledgers may scan continuously to mirror 24h leaders (priority: `x-MoneyForWhiskas` full-day activity).~~ Copy ledgers and watchlist are **paused**.

2. **连续 24h booked=0 (escalate)** — Escalate / strategy-review when `booked=0` accumulates to **calendar continuous 24h**. Off-hours are no longer excluded, because there are **no off-hours**. This is wall-clock / calendar time, not two clipped NY sessions.

3. **Drawdown — two tiers (do not collapse), `whiskas-inv` race** — Live, real time: compare **`whiskas-inv`** equity vs its own peak. Copy ledgers are **not** in the race. **`arb-main` booking is paused.**

   - **Escalate / REVIEW** (ask **poly金融**): peak drawdown **≥ 10%** **OR** equity **< 2070**. **Continue scanning `whiskas-inv`; do NOT hard-stop.** This is the review gate only. 2070 must never hard-stop alone.
   - **Hard halt / SKIP**: peak drawdown **≥ 25%** **OR** equity **< 1725**. **SKIP `whiskas-inv`.** **1725 is intentionally below 2070** so the review floor and the halt floor do not collide. The 25% / 1725 halt does **not** replace the 10% / 2070 REVIEW line.

## Trading session (ops frozen; implemented)

**24h trading is frozen.** There is **no ET session gate**. Equivalent: **24h / 00:00–24:00 ET**. `config/paper.yaml` sets `session.enabled: false` and does **not** encode 08:00–23:00.

- `poly-paper --loop` keeps scanning around the clock (no `SKIP session_closed` for night / weekend ET hours).
- `booked=0` **escalate** is **calendar continuous 24h**. Overnight and former “off-window” idle **do** count. After ~24h of continuous `booked=0`, log `TRIGGER idle_zero_fill`.
- ~~Copy ledgers may scan continuously so they can mirror 24h leaders. Primary: `x-MoneyForWhiskas` (full-day activity).~~ Copy ledgers, watchlist, mirror, and stop-follow / rescan are **DISABLED**.
- Drawdown watches **`whiskas-inv` equity vs its own peak** on every cycle (`(peak − equity) / peak`). Two tiers — do not collapse:
  - **Escalate / REVIEW** (ask **poly金融**): peak drawdown ≥ **10%** OR equity < **2070**. **Continue scanning `whiskas-inv`; do NOT hard-stop.**
  - **Hard halt / SKIP**: peak drawdown ≥ **25%** (`drawdown_halt_pct`) OR equity < **1725**. `SKIP drawdown_halt` on **`whiskas-inv`**. **1725 is intentionally below 2070** so the floors do not collide.

## Daily scan quality

`SUMMARY` / `DAILY` must **split by `ledger_id`**. Every line includes:

- `cash`, `equity`, `PnL`
- race rank on **`whiskas-inv`** (start **2300**; `distance_to_2000` is the old `main_arb` field, not this race target)
- `screened_n`: SCREEN universe size this UTC day (binaries + complete-sets). Must stay visible when booking skip leaves `scanned=0`.
- `below_floor_n`: count of screened markets whose diagnostic net edge is below the applicable floor (still counted). Universe count, including skip-walk prints.
- `median_net_edge`: median of the diagnostic sample, **including** below-floor / negative prints.
- `median_net_edge_kind=raw|walked`: `walked` when every below-floor book was cheap enough to depth-walk for diagnostics only; otherwise `raw` (batch best-ask `1−Σask`, no fee). Booking never uses raw to lower floors or book below-floor.
- `best_binary` / `best_set`: best SCREEN raw edges seen this UTC day (`n/a` if none).
- review / halt flags for that ledger

Booking path is unchanged: `skip_walk_if_raw_below_floor` still omits below-floor books from the walk/book list. Diagnostic walks never book.

UTC day window for fills; edge tape resets on UTC date rollover.
