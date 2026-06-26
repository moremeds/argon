# GEX（Gamma Exposure）完全拆解

> 来源：小红书 GEX 一图流信息图（rednote ID 580133023，单页 8 板块），整理自 `docs/screenshots/options/` 截图。
> 主题：GEX 衡量"当现货变动 1% 时，Dealer 为对冲所需买/卖的美元金额（notional）"，以及它如何影响市场的微观行为。

---

## 1. 什么是 GEX（Gamma Exposure）

GEX 衡量的是：当前的持仓变动 1% 时，Dealer 为对冲所需买/卖的金额（美元 notional）。

机制：价格变动 → 期权 Delta 变化 → Dealer 被动追买/卖出现货来维持对冲。

- 客户（买期权） vs Dealer（卖期权），双方通过**动态对冲（Delta Hedge）**维持中性。

## 2. Gamma 直觉理解

**Short Gamma（Dealer 短 Gamma）= 追涨杀跌**

- 股价上涨 → Delta 变大 → 需要买更多股票（追涨，被动买入）
- 股价下跌 → Delta 变小 → 需要卖股票（被动卖出）

**Long Gamma（Dealer 长 Gamma）= 逢高卖逢低买**

- 股价上涨 → Delta 变大 → 可以卖出股票（主动卖）
- 股价下跌 → Delta 变小 → 可以买入股票（主动买）

## 3. GEX 公式推导

- Γ（Gamma）= ∂Δ/∂S（股价每变动 $1，Delta 的变化量）
- 需调整的股票数 = Γ × OI × ContractSize × ΔS
- 当 1% 的价格变动，即 ΔS = 0.01 × S 时：

```
GEX（美元）= Γ × OI × ContractSize × 0.01 × S × S
           = Γ × OI × ContractSize × S² × 0.01
```

其中：

- **Γ（Gamma）**：股价每变动 1 美元，Delta 的变化量
- **OI（Open Interest）**：未平仓的合约数
- **ContractSize**：每张合约对应的股票数量（美股通常为 100）
- **S²**：见下一节解释

## 4. 为什么是 S²？

| 步骤 | 计算 | 结果单位 |
|---|---|---|
| ① | Γ × OI × ContractSize | 每股每变动 $1 需重新对冲的股数（shares） |
| ② | ΔS = 0.01 × S | 每变动 1% 的美元 |
| ③ | 把股数 × 美元波动 | 美元（USD） |
| 合计 | Γ × OI × ContractSize × S² × 0.01 | |

（直观：一项是"每 $1 变动要对冲多少股"，另一项是"1% 等于多少美元"，两者相乘出现一个 S，再叠加把股数换成美元金额的 S，于是得到 S²。）

## 5. 正 GEX 与负 GEX

**正 GEX（Dealer 长 Gamma）**

- Dealer 在上涨时卖出，在下跌时买入
- → 压制波动 / 稳定 / 逢高卖逢低买
- dip 被买，rally 被卖 → 稳定区间，mean reversion

**负 GEX（Dealer 短 Gamma）**

- Dealer 在上涨时买入，在下跌时卖出
- → 放大波动 → squeeze / 瀑布下跌
- → momentum，long vol → 过渡区域 / 不稳定 / 放大波动

## 6. 如何知道 Dealer 是买还是卖？（本质上是猜测）

**市场惯例假设**：客户主动买期权，Dealer 被动卖出：

- Call OI = Dealer Short Call
- Put OI = Dealer Short Put

但这不是 100% 正确。（若客户 sell call / covered call / short put，则 Dealer 持仓相反。）

**更专业的判断方法：**

- **成交方向（Trade Direction）**：看 bid/ask、aggressor side、sweep、block。
- **IV / Skew / Flow 综合分析**：IV 下降的 Put 可能是客户卖 Put。
- **Dealer Inventory Models**：大型机构内部跟踪自己的资产 + 持仓变化。
- **Intraday Flow**：看占比变化（盘中实时新仓位方向）。

## 7. 从哪些维度看 GEX？每种维度代表什么含义？

- **① Total Net GEX（全市场净 GEX）**：市场整体是长 Gamma 还是短 Gamma → 市场整体 Regime。
- **② GEX by Strike（按 Strike 分布）**：看每个 Strike 的 GEX 大小 → 找出 Gamma Wall / 支撑阻力 / 磁吸效应。
- **③ GEX by Expiration（按到期日）**：0DTE / 周度 / 月度 / LEAPS，看不同到期日的 GEX 大小 → 近月影响最大。
- **④ Gamma Flip Level（翻转点）**：市场从正 GEX 切换到负 GEX 的价格位置；上方稳定 / 压制波动，下方趋势化 / 放大波动。
- **⑤ Vanna / Charm Exposure**：Vanna = IV 变化对 Delta 的影响；Charm = 时间对 Delta 的变化 → 影响开盘、事件、月底、临期、收盘。
- **⑥ Volume GEX vs OI GEX**：OI GEX = 历史累积仓位，更稳定；Volume GEX = 当天新增仓位，变化快，尤其 0DTE 影响大。

## 8. 总结：GEX 的核心用途

```
判断关键价格区（Gamma Wall / Flip）
   → 判断市场状态（稳定 or 趋势）
   → 把握波动节奏（近月 / 0DTE 影响）
   → 结合其他因子（IV / Flow / Greeks）
   → 制定交易策略（Mean Reversion / Momentum）
```

**重要提醒：**

- GEX 只是估算，不是 Dealer 持仓的真实数据；
- 市场结构在变，OTC 权重越来越增加；
- 需要结合流动性、趋势、宏观、情绪综合应用。
