# poly

Polymarket CLOB **paper-trading** 套利骨架：用实时盘口深度、手续费和滑点决定是否成交，并把成交记入本地账本。起始资金 **200 USD**，里程碑 **1000 USD**（只用于报告，不会伪造成交去凑数）。

本仓库**不会**在 paper 模式向 CLOB 发送真实订单。

## 模拟了什么 / 没模拟什么

| 会做 | 不会做 |
| --- | --- |
| 只读拉取 CLOB `get_clob_market_info` + order book | 下真实单（`create_and_post_order` / `post_order` 等） |
| 按盘口逐档 walk 计算可成交均价与滑点 | 把最优一档数量当成全部可成交量 |
| 使用 `fd.r` / `fd.to` 计算 taker 费（maker 在 `fd.to=true` 时为 0） | 手改账本余额 |
| 本地 JSONL 追加成交，余额由成交回放得出 | 单边方向性下注、跨事件无对冲叙事单 |
| 风控：单笔 ≤ 资金 25%、同事件 ≤ 40%、同时未平仓机会 ≤ 3 | 为了冲 1000 USD 而虚增成交 |

## 策略（结构已实现，含真实 edge 公式）

1. **YES+NO lock**：对同一市场买入全部互斥结果，`edge_taker = 1 − Σ walk_ask(size_i) − Σ fee/share`，门槛 ≥ **0.5¢ (0.005)**。
2. **Multi-outcome complete-set**：三个及以上结果同样锁完全集，公式相同。
3. **Maker spread**：只在挂买价 + 对侧可成交路径的净 edge ≥ **0.2¢ (0.002)**，且库存风险被完全对冲时才记账。

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

持续轮询（仍然只写本地账本，不会下真单）：

```bash
poly-paper --loop
```

配置在 `config/paper.yaml`：起始余额、edge 门槛、仓位上限、CLOB/Gamma 公共端点。加载器会拒绝放宽这些硬约束。

账本是 `data/paper_ledger.jsonl`：只追加、带哈希链。没有 `set_balance`。余额 = 200 − Σ cash_debit + Σ cash_credit；权益 = 现金 + 已锁定完全集兑付。

## 测试

```bash
pip install -e ".[dev]"
pytest
```

覆盖账本记账 / 哈希链、风控门槛、手续费与盘口 walk、三种策略的 edge 判定，以及 paper 模式禁止真实下单路径。

## 目录

```
config/paper.yaml          # 硬约束 + 公共端点
docs/edge_position_rules.md  # 冻结的 edge / 手续费 / 仓位规则 (v1)
src/polybot/
  ledger/                  # 追加式 paper 账本
  market/                  # CLOB 只读客户端、盘口 walk、fd 费率
  strategy/                # yes_no_lock / complete_set / maker_spread
  risk/                    # 仓位与禁止项
  runner/                  # poly-paper CLI
tests/
```

## 风险提示

预测市场价格、深度和费率会变。Paper 成交不是真实盈亏。本项目不构成投资建议。
