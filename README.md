# poly

Polymarket CLOB **paper-trading** 套利骨架：用实时盘口深度、手续费和滑点决定是否成交，并把成交记入本地账本。**OWNER HALT：** `whiskas.enabled=false` 且 `accounts.whiskas-inv.paused=true` — **`whiskas-inv` 不入账，loop 不得交易**。规则仍是 inventory pairing，不要发明新策略。**`arb-main` booking paused**（只读扫描仍可）。Copy 账本 / 观察名单 **DISABLED**。

本仓库**不会**在 paper 模式向 CLOB 发送真实订单。

## 模拟了什么 / 没模拟什么

| 会做 | 不会做 |
| --- | --- |
| 只读拉取 CLOB `get_clob_market_info` + order book | 下真实单（`create_and_post_order` / `post_order` 等） |
| 按盘口逐档 walk 计算可成交均价与滑点 | 把最优一档数量当成全部可成交量 |
| 使用 `fd.r` / `fd.to` 计算 taker 费（maker 在 `fd.to=true` 时为 0） | 手改账本余额 |
| 本地 JSONL 追加成交，余额由成交回放得出 | 单边方向性下注、跨事件无对冲叙事单 |
| 风控：单笔 ≤ 该账本资金 25%、同事件 ≤ 40%、同时未平仓机会 ≤ 3 | 为了冲赛跑目标而虚增成交 |

## 策略（结构已实现，含真实 edge 公式）

1. **YES+NO lock**：对同一市场买入全部互斥结果，`edge_taker = 1 − Σ walk_ask(size_i) − Σ fee/share`，门槛 ≥ **0.5¢ (0.005)**。
2. **Multi-outcome complete-set**：三个及以上结果同样锁完全集，公式相同。
3. **Maker spread**：只在挂买价 + 对侧可成交路径的净 edge ≥ **0.2¢ (0.002)**，且库存风险被完全对冲时才记账。
4. ~~**Copy-follow**（新增允许类型）~~ — **DISABLED / removed from allow list.** 跟单、观察名单、copy 账本、mirror、停跟 / 重扫全部暂停，直到 **poly金融** 重新开放该类型。历史规则见 [`docs/copy_follow_rules.md`](docs/copy_follow_rules.md)。纸面钩子见 [`docs/copy_trading.md`](docs/copy_trading.md)。**不要删文件 / 不要抹 git 历史。**
5. **Whiskas inventory** — **FROZEN** (allow-list `whiskas_inventory`, ledger **`whiskas-inv`**, **main race**). Paper-only BTC 5m Up+Down both sides; **50 shares**; start **+6s**; stop when **≤100s** left; buy **≤89¢**; combo **≤105¢**; cheap leg may continue, rich stops at 89¢; walk asks + fee. Capital **$2300**, per-round **$1200**. REVIEW **10% / <2070**, HARD **25% / <1725**. **`arb-main` booking paused** (read-only scan OK). **Not** copy-follow. Forbidden: 80¢ lead-only, mid sells, copy mirror, live chain. Rules: [`docs/whiskas_inventory_rules.md`](docs/whiskas_inventory_rules.md).

### Copy-trading 观察（纸面）— **DISABLED**

> **Finance freeze FINAL：** copy-trading **entirely DISABLED**（watchlist、copy ledgers、mirror、stop-follow / rescan）。当前允许名单 = **lock arb + maker + `whiskas_inventory`（paper）**。赛跑只跑 **`whiskas-inv`**：起始 **2300**，单轮 **1200**，24h paper，REVIEW **10% / <2070**，HARD **25% / <1725**。**`arb-main` booking paused**（只读扫描 OK）。Lock-arb 门槛不变。

~~poly金融新增允许策略：跟单观察 → 小仓纸面。~~ **已移出允许名单。** YES+NO / complete-set / maker 套利照旧。`whiskas_inventory` 是**独立**的 paper-only inventory 类型，**不是** copy-follow。

- 观察名单（**PAUSED**）：~~`x-MoneyForWhiskas`（BTC 5m，主领，全日 / 24h）~~、~~`0xcd30457c79`（BTC 5m）~~、~~`goldfisherrr`（BTC 15m）~~。在金融重新开放前不要跟、不要重扫。
- ~~停跟 / 重扫 / Mirror chase~~ — **DISABLED**。
- ~~每个领单独立 paper 账本~~ — copy 账本 **paused**。赛跑见 [`docs/multi_ledger_race.md`](docs/multi_ledger_race.md)：**仅 `whiskas-inv`**，起始 **2300 USD**，单轮 **1200 USD**。**`arb-main` booking paused**。
- 回撤（`whiskas-inv`）：10% 或权益低于 **2070** 打 `REVIEW`（继续扫）；25% 或权益低于 **1725** 才 `SKIP`。
- 原有 25% / 40% / 同时 ≤3 仅在 **`arb-main` 重新开放 booking** 时按该账本现金生效。~~Copy 账本可连续扫描~~ — **DISABLED**。
- `MirrorExecutor` stub 仍在树里（测试用）；**不是** ops 路径，**不写账本、不下单**。
- 另档蒸馏（**FROZEN**，与跟单无关）：[`docs/whiskas_inventory_rules.md`](docs/whiskas_inventory_rules.md) 是公开成交带还原的 **inventory / pairing** 规则（allow-list `whiskas_inventory`，ledger `whiskas-inv`）。**不是** copy-follow，**不要**因此打开观察名单或 mirror。

运行时闸门与 #12 一致：`config/paper.yaml` → `copy.enabled: false`（`config/copy.yaml` 同样为 false）。`config/copy.yaml` 仅作历史 / loader 测试引用。赛跑规则见 `docs/multi_ledger_race.md`。

手续费：

```
fee(p) = size × r × p × (1 − p)   # taker
maker  = 0                         # 当 fd.to 为 true（以 getClobMarketInfo 的 fd 为准）
```

开仓数量：

```
min(balance × 0.25 / 成本, 同事件剩余额度, 盘口可成交数量)
同时未平仓机会 ≤ 3
```

## 安装

需要 Python 3.10+。官方 CLOB V2 客户端是 [`py-clob-client-v2`](https://pypi.org/project/py-clob-client-v2/)（不要用已停用的 `py-clob-client`）。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # 可选；不要填私钥
```

Paper 模式是 L0 只读客户端：`ClobClient(host=..., chain_id=137)`，不需要 API key / 私钥。`.env.example` 里故意不放密钥字段。

## 跑 paper 模式

默认扫描一轮后退出（dry-run 安全）：

```bash
poly-paper --once
# 或
python -m polybot --once --config config/paper.yaml --ledger data/paper_ledger.jsonl
```

持续轮询（仍然只写本地账本，不会下真单）。默认每 20 秒一轮，日志会打出 SCAN / REJECT / BOOK，每轮还有 `SUMMARY`（会话）和 `DAILY YYYY-MM-DD`（UTC 当日：按 `ledger_id` 拆分 fills、cash、equity、pnl、`distance_to_2000`、win_rate、open exposure、`screened_n`、`below_floor_n`、`median_net_edge`、`median_net_edge_kind=raw|walked`、`best_binary` / `best_set`、review/halt）。SCREEN 扫到的市场即使因 raw-below-floor 跳过 walk / 不成交，也会进入诊断计数，避免 `scanned=0` 看起来像“什么都没扫”。

**24h paper 已冻结（ops）。** 不再要求 America/New_York 08:00–23:00 时段门；默认连续 **24h** / **00:00–24:00 ET**。`config/paper.yaml` 为 `session.enabled: false`，**没有** 08:00–23:00。`booked=0` escalate 按**日历连续 24h** 计（已无 off-hours）。~~Copy 账本可连续扫描以镜像全日领单（优先 `x-MoneyForWhiskas`）。~~ Copy 账本与观察名单 **paused**。赛跑只跑 **`whiskas-inv`**：10% 或权益低于 **2070** 打 `REVIEW`（上报 finance，**不停扫**）；25% 或权益低于 **1725** 才 `SKIP drawdown_halt`。2070 不是硬停地板。**`arb-main` booking paused**（只读扫描 OK）。

```bash
poly-paper --loop
```

确定性纸面验收（录好的 BTC 5m fixture，不碰真盘、不下真单）。会在时间窗内 walk 双边 50 股并写 `whiskas-inv` 成交 + stub 结算兑付；`arb-main` 仍暂停记账：

```bash
poly-paper --fixture fixtures/whiskas_btc_5m_round.json \
  --whiskas-ledger fixtures/whiskas-inv.paper-fills.jsonl \
  --ledger fixtures/arb-main.paper-fills.jsonl
```

发现面会同时拉 CLOB `sampling-markets` + `markets`（可翻页）和 Gamma 活跃市场 / 多结果事件。YES+NO 与 complete-set 会在多个数量上 walk 盘口（不只看最深一档），门槛与风控不变。

配置在 `config/paper.yaml`：起始余额、edge 门槛、仓位上限、CLOB/Gamma 公共端点。加载器会拒绝放宽这些硬约束。硬公式见 `docs/edge_position_rules.md`。跟单类型（**DISABLED**）见 `docs/copy_follow_rules.md`。Whiskas inventory（**FROZEN**，allow-list `whiskas_inventory`，ledger `whiskas-inv`，paper only，**不是** copy-follow）见 [`docs/whiskas_inventory_rules.md`](docs/whiskas_inventory_rules.md)。赛跑（**仅 `whiskas-inv`，起始 2300，单轮 1200**；`arb-main` booking paused）见 [`docs/multi_ledger_race.md`](docs/multi_ledger_race.md)。

赛跑账本是 **`whiskas-inv`**（起始 **2300 USD**）。`data/paper_ledger.jsonl`（**`arb-main`**）**booking paused**，只读扫描仍可。同目录历史 `copy-<leader>.jsonl` **paused**，不入赛。只追加、带哈希链。没有 `set_balance`。`whiskas-inv` 余额 = 2300 − Σ cash_debit + Σ cash_credit；权益 = 现金 + 未结算库存 / 兑付。

## 测试

```bash
pip install -e ".[dev]"
pytest
```

覆盖账本记账 / 哈希链、风控门槛、手续费与盘口 walk、lock-arb / maker 的 edge 判定、历史 copy 观察名单 / 停跟 stub（**DISABLED，不是允许类型**），以及 paper 模式禁止真实下单路径。

## 目录

```
config/paper.yaml            # 硬约束 + 公共端点
config/copy.yaml             # 历史 copy 观察名单 / 停跟（DISABLED；loader 测试引用）
docs/multi_ledger_race.md    # 赛跑 freeze：whiskas-inv @ 2300；arb-main booking paused
docs/copy_follow_rules.md    # 跟单规则 v1 — DISABLED / 移出允许名单
docs/edge_position_rules.md  # 冻结的 edge / 手续费 / 仓位规则 (v1)；允许名单含 whiskas_inventory
docs/copy_trading.md         # copy 观察、停跟、重扫、mirror stub — DISABLED
docs/whiskas_inventory_rules.md  # FROZEN inventory pairing (paper); ledger whiskas-inv; not copy-follow
fixtures/whiskas_btc_5m_round.json   # recorded paper book for acceptance dry-run
fixtures/whiskas-inv.paper-fills.jsonl  # sample whiskas-inv fills + stub redeem
src/polybot/
  copy/                    # 历史 stub（watchlist / monitor / mirror）；非 ops 路径
  ledger/                  # 追加式 paper 账本
  market/                  # CLOB 只读客户端、盘口 walk、fd 费率
  strategy/                # yes_no_lock / complete_set / maker_spread / whiskas_inventory
  risk/                    # 仓位与禁止项
  runner/                  # poly-paper CLI
tests/
```

## 风险提示

预测市场价格、深度和费率会变。Paper 成交不是真实盈亏。本项目不构成投资建议。
