# poly

Polymarket CLOB **paper-trading** 套利骨架：用实时盘口深度、手续费和滑点决定是否成交，并把成交记入本地账本。每本独立账本起始 **1000 USD**，先到 **2000 USD** 获胜（只用于报告，不会伪造成交去凑数）。

本仓库**不会**在 paper 模式向 CLOB 发送真实订单。

## 模拟了什么 / 没模拟什么

| 会做 | 不会做 |
| --- | --- |
| 只读拉取 CLOB `get_clob_market_info` + order book | 下真实单（`create_and_post_order` / `post_order` 等） |
| 按盘口逐档 walk 计算可成交均价与滑点 | 把最优一档数量当成全部可成交量 |
| 使用 `fd.r` / `fd.to` 计算 taker 费（maker 在 `fd.to=true` 时为 0） | 手改账本余额 |
| 本地 JSONL 追加成交，余额由成交回放得出 | 单边方向性下注、跨事件无对冲叙事单 |
| 风控：单笔 ≤ 该账本资金 25%、同事件 ≤ 40%、同时未平仓机会 ≤ 3 | 为了冲 2000 USD 而虚增成交 |

## 策略（结构已实现，含真实 edge 公式）

1. **YES+NO lock**：对同一市场买入全部互斥结果，`edge_taker = 1 − Σ walk_ask(size_i) − Σ fee/share`，门槛 ≥ **0.5¢ (0.005)**。
2. **Multi-outcome complete-set**：三个及以上结果同样锁完全集，公式相同。
3. **Maker spread**：只在挂买价 + 对侧可成交路径的净 edge ≥ **0.2¢ (0.002)**，且库存风险被完全对冲时才记账。
4. **Copy-follow**（新增允许类型）：跟单腿用 chase gate **1¢ (`COPY_MAX_CHASE=0.01`)** 替代 `MIN_EDGE_TAKER`（**仅 copy 腿**；YES+NO / complete-set lock-arb 门槛不变）。规则见 [`docs/copy_follow_rules.md`](docs/copy_follow_rules.md)。纸面钩子见 `docs/copy_trading.md`。

### Copy-trading 观察（纸面）

poly金融新增允许策略：**跟单观察 → 小仓纸面**。YES+NO / complete-set 套利照旧。

- 观察名单（优先级）：`x-MoneyForWhiskas`（BTC 5m，主领，**全日 / 24h**）、`0xcd30457c79`（BTC 5m）、`goldfisherrr`（BTC 15m）。配置键是展示名；钱包地址映射仍是 TODO。
- 停跟：领单 `peak_dd ≥ 5%` **或** `path_dd ≥ 5%` **或** `month_pnl ≤ 0`（含 0）→ 标记 inactive，打出 `STOP_FOLLOW` + `RESCAN_NEEDED`。
- Mirror chase：`|fill_px − leader_px| + fee/share > 0.01`（1¢）则放弃该笔，不跟。
- 重扫钩子：要求候选 `peak_dd` 与 `path_dd` 都 **< 5%** 且仍盈利。默认只记日志，没有 live 钱包扫描器。
- **无全局 30% 袖仓**。每个领单独立 paper 账本，起始 **1000 USD**；风控只相对该账本自身权益。违约只停该 copy 账本。赛跑见 [`docs/multi_ledger_race.md`](docs/multi_ledger_race.md)（先到 **2000 USD**，报告字段 `distance_to_2000`）。
- 回撤（每本账本）：10% 或权益低于 **900** 打 `REVIEW`（该账本继续扫）；25% 或权益低于 **750** 才对该账本 `SKIP`。
- 原有 25% / 40% / 同时 ≤3 仍按**该账本**现金生效。Copy 账本可 **连续扫描**，以镜像 24h 领单。
- `MirrorExecutor` 是 stub：要求 delay + 深度 walk + 手续费，违规则拒绝；**不写账本、不下单**。

配置在 `config/copy.yaml`（`config/paper.yaml` 的 `copy.path`）。加载器仍会拒绝放宽停跟阈值。多账本赛跑规则（docs freeze）见 `docs/multi_ledger_race.md`。

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

持续轮询（仍然只写本地账本，不会下真单）。默认每 20 秒一轮，日志会打出 SCAN / REJECT / BOOK，每轮还有 `SUMMARY`（会话）和 `DAILY YYYY-MM-DD`（UTC 当日：按 `ledger_id` 拆分 fills、cash、equity、pnl、`distance_to_2000`、win_rate、open exposure、`below_floor_n`、`median_net_edge`、review/halt）。

**24h 交易已冻结（ops）。** 不再要求 America/New_York 08:00–23:00 时段门；默认连续 **24h** / **00:00–24:00 ET**。`config/paper.yaml` 为 `session.enabled: false`，**没有** 08:00–23:00。`booked=0` escalate 按**日历连续 24h** 计（已无 off-hours）。Copy 账本可连续扫描以镜像全日领单（优先 `x-MoneyForWhiskas`）。多账本赛跑回撤（每本账本）：10% 或权益低于 **900** 打 `REVIEW`（上报 finance，**该账本不停扫**）；25% 或权益低于 **750** 才对该账本 `SKIP drawdown_halt`。900 不是硬停地板。

```bash
poly-paper --loop
```

发现面会同时拉 CLOB `sampling-markets` + `markets`（可翻页）和 Gamma 活跃市场 / 多结果事件。YES+NO 与 complete-set 会在多个数量上 walk 盘口（不只看最深一档），门槛与风控不变。

配置在 `config/paper.yaml`：起始余额、edge 门槛、仓位上限、CLOB/Gamma 公共端点。加载器会拒绝放宽这些硬约束。硬公式见 `docs/edge_position_rules.md`。跟单类型见 `docs/copy_follow_rules.md`。多账本赛跑（每本 **1000 → 2000**）见 [`docs/multi_ledger_race.md`](docs/multi_ledger_race.md)。

账本是 `data/paper_ledger.jsonl`（arb-main）以及同目录 `copy-<leader>.jsonl`：只追加、带哈希链。没有 `set_balance`。每本账本余额 = 1000 − Σ cash_debit + Σ cash_credit；权益 = 现金 + 已锁定完全集兑付。

## 测试

```bash
pip install -e ".[dev]"
pytest
```

覆盖账本记账 / 哈希链、风控门槛、手续费与盘口 walk、三种策略的 edge 判定、copy 观察名单 / 停跟 / 独立账本风控，以及 paper 模式禁止真实下单路径。

## 目录

```
config/paper.yaml            # 硬约束 + 公共端点
config/copy.yaml             # copy 观察名单 / 停跟（paper 引用）
docs/multi_ledger_race.md    # 多账本赛跑 freeze（1000 → 2000，24h session）
docs/copy_follow_rules.md    # 跟单规则 v1（watchlist / chase gate 1¢ / 独立账本）
docs/edge_position_rules.md  # 冻结的 edge / 手续费 / 仓位规则 (v1)
docs/copy_trading.md       # copy 观察、停跟、重扫、mirror stub
src/polybot/
  copy/                    # watchlist / metrics stub / monitor / mirror stub
  ledger/                  # 追加式 paper 账本
  market/                  # CLOB 只读客户端、盘口 walk、fd 费率
  strategy/                # yes_no_lock / complete_set / maker_spread
  risk/                    # 仓位与禁止项
  runner/                  # poly-paper CLI
tests/
```

## 风险提示

预测市场价格、深度和费率会变。Paper 成交不是真实盈亏。本项目不构成投资建议。
