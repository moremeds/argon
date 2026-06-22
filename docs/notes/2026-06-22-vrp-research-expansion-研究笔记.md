# VRP 研究扩展笔记（把"卖贵波动率"的研究做深：测量层 + 三个轴）

> 日期：2026-06-22 ｜ 计划：`docs/superpowers/plans/2026-06-22-vrp-research-expansion.md`
> 代码：`reports/{vrp_markout_core,vrp_rv_validation,vrp_harvest_axes,vrp_directional}.py`
> 表：migration 080 的 6 张表 ｜ 作业：`worker/jobs/{corporate_actions_jobs,vrp_research_jobs}.py`
> 本笔记的实测数字来自 **2026-06-22 对本地 `option_wizard_local`（114 标的 × 28,544 行 vrp_daily）的预跑**，
> 已 ingest 真实 corporate-actions（96 splits / 1,562 dividends，52 个标的有拆股）。

---

## 1. 这次扩展在解决什么 —— "内在联系"

PR #147（VRP harvest markout）只回答了一个 cube 里的**一格**：`(asset_class × deviation_class)`、
单一 T+20、单一目标（harvest），而且前瞻 RV 用的是个**近似**。这次扩展把它做成一个
**统一的、测量被校正过的研究引擎**，五个清单项不是五条独立支线，而是同一个 markout 的两层：

```
              测量层（所有轴共用的地基）
   item 1 ─▶  用 corporate-action 调整后的价格，算精确的 [t,t+h] 前瞻 RV
   item 3 ─▶  历史财报日历（massive filing_date ∪ flow_events）+ filing 滞后缓冲
                                  ▲
            三个轴都坐在这个校正过的地基上：
   AXIS A (item 2) 条件粒度    AXIS B (item 4) 持仓期   AXIS C (item 5) 目标定义
   asset_class → ×sector       h ∈ {5,20,60}            harvest → 方向性 → ΔVRP 回归
```

**关键点**：如果 RV(t+h) 被污染（拆股看起来像 −90% 暴跌）或财报漏进 (t,t+h] 窗口，**每一个轴都会
报出有偏的数字**。所以即便五项"并行"开发，它们都消费**同一个校正过的核心**（`vrp_markout_core`）。

---

## 2. 方法论（含联网核验的引用）

- **精确前瞻 RV**：`sqrt(252) × 日 log 收益的样本标准差`，与现有 `volatility_series._fill_rv_from_price`
  的口径一致（pandas `.std()` 即 ddof=1）。窗口用 `horizon` 个收益（持仓期本身），这正是与"trailing-21d
  近似"的差别 —— item 1 量化的就是这个差。约定核验：Wikipedia *Volatility (finance)* / AnalystPrep FRM。
- **拆股/分红回填**：拆股必调（大跳空会毁掉 RV）；分红默认**关**（季度除息只有 ~0.5% 跳空，对 RV 二阶，
  且打开会把方向性研究悄悄变成 total-return 研究）。一个"未调整拆股"防线：单日 |log 收益| > 0.5 直接丢弃该窗口。
- **历史财报日历（item 3）**：`massive_fundamentals.filing_date` ∪ `flow_events.next_earnings_date`。
  联网核验：8-K 财报新闻稿（真正的跳空日）领先 10-Q **0–14 天**（KnownTrends / Calcbench），所以
  filing 来源的日期带 **15 个自然日的向后缓冲**，flow 来源（即公告日）缓冲 0。
- **OOS 纪律**：沿用 skew/VRP 的 walk-forward 留出（后 40%）+ **逐季度灾难闸**。置信度最高 "med"。
- **方向性（item 5a）联网核验**：Bollerslev–Tauchen–Zhou —— 高 VRP（**水平/时序**）预测**高**未来收益。
  横截面去均值会把这个效应抹掉，所以方向性测试**不去均值**，改测 **RICH−CHEAP 的多空差值序列**，
  且 OOS 直接跑在这个差值序列上。

---

## 3. 实测结果（2026-06-22 本地预跑，已做 corp-action 调整）

覆盖：114 个 vrp_daily 标的 ｜ 89 个有 ≥1 corporate action ｜ 99 个有 ≥1 财报日。

### 3.1 item 1 —— 近似到底有多松？（vrp_rv_validation 摘要）

| horizon | 标的数 | 平均 \|偏差\|（vol pts） | 平均 corr(近似, 精确) |
|---|---|---|---|
| 5 | 114 | **0.1845** | 0.176 |
| 20 | 114 | 0.1353 | 0.137 |
| 60 | 114 | 0.1176 | 0.073 |

**结论**：trailing-21d 近似在**短持仓期最松**（h=5 平均差 ~18 个 vol 点，相关性仅 0.18），波动率高的
小盘（如 AAOI h=5 |偏差| 0.45）尤甚 —— 短窗精确 RV 只有 5 个收益、本身很吵。这证明 item 1 的前提成立：
harvest 应当用**精确 RV**（现在 `run_vrp_markout` 已切换）。

### 3.2 item 4 —— 收成随持仓期的衰减曲线（RICH 桶 mean_realized_vrp）

| asset_class | T+5 | T+20 | T+60 |
|---|---|---|---|
| index_macro | +0.028 ✅ | **+0.055 ✅** | +0.035 ✅ |
| credit | +0.043 ✅ | +0.044 ✅ | +0.045 ✅ |
| sector_etf | +0.066 ✅ | **+0.073 ✅** | +0.041 ✅ |
| single_name | +0.078 ✅ | **+0.081 ✅** | +0.013 ❌NONE |

（✅ = HARVEST_SELLABLE）。**收成在 ~T+20 见顶**；单票到 T+60 衰减到不可卖（与"方差风险溢价集中在短端"的
期限结构文献一致，NY Fed SR 736）。指数/信用/行业 ETF 在各持仓期都稳，单票则有明确的"时间窗"。

### 3.3 item 2 —— 单票的"WHERE"问题（按 sector 下钻，T+20，RICH 桶）

| sector | 裁决 | mean | n | | sector | 裁决 | mean | n |
|---|---|---|---|---|---|---|---|---|
| Power | ✅ | +0.187 | 45 | | M7 | ✅ | +0.082 | 248 |
| Space | ✅ | +0.164 | 167 | | SaaS | ✅ | +0.080 | 233 |
| Fintech | ✅ | +0.140 | 79 | | Healthcare | ✅ | +0.077 | 241 |
| Crypto | ✅ | +0.097 | 192 | | Semi-Cap | ✅ | +0.074 | 390 |
| Foundry | ✅ | +0.094 | 134 | | Semi-Logic | ❌NONE | +0.067 | 204 |
| NeoCloud | ✅ | +0.091 | 159 | | Banks | ✅ | +0.064 | 227 |

**这是对原结论的实质性细化**：原笔记说"单票整桶被季度闸否（NONE）"，但**按 sector 条件化后，绝大多数
板块的 RICH 桶是可卖的**（只有 Semi-Logic 被季度闸否）。即——单票短波动率**并非整体不可卖，而是聚合掩盖了
板块结构**。
> **诚实的保留**：per-sector 样本更小、覆盖的季度更少，季度灾难闸天然更"容易过"。这个结果指出了"哪里值得卖"，
> 但单票仍应**限仓、限板块**，不能当成无差别系统化卖。

### 3.4 item 5a —— 方向性（RICH−CHEAP 多空差值，不去均值）

| asset_class | T+5 | T+20 | T+60 |
|---|---|---|---|
| single_name | NEUTRAL (+0.002, n=220) | **BEARISH_TILT (−0.036, n=214)** | **BEARISH_TILT (−0.073, n=174)** |
| index_macro / sector_etf | NEUTRAL（n=3~5，名字太少，诚实地不下结论） | … | … |

**单票里，高 VRP（贵波动率）的名字在 20–60 天后系统性地跑输低 VRP 的名字**（多空差值为负）。这与
Bollerslev 的**指数层面**"高 VRP→高收益"方向相反 —— 在单票**横截面**上，贵波动率往往是被爆炒/拥挤的名字，
随后跑输。指数/行业因名字太少（n≤5）不下结论。

### 3.5 item 5b —— ΔVRP 回归（RICH 桶 forward ΔVRP）

| asset_class | T+5 | T+20 | T+60 |
|---|---|---|---|
| single_name | NEUTRAL (−0.016) | **REVERTS (−0.087)** | **REVERTS (−0.105)** |
| sector_etf | NEUTRAL (−0.018) | REVERTS (−0.053) | REVERTS (−0.063) |
| index_macro | NEUTRAL (−0.013) | REVERTS (−0.040) | NEUTRAL (−0.060) |
| credit | NEUTRAL (−0.020) | REVERTS (−0.023) | REVERTS (−0.039) |

**贵 VRP 会均值回归向下**，T+20 起在所有资产类里都成立、单票最强（−0.087 / −0.105）。CHEAP 桶则
对称地向上回归（见全表）。这把"什么时候卖最有把握"又加了一层证据：**贵且会回落**。

---

## 4. 三轴拼出的统一图景（内在联系的回报）

- **测量层**修正后，收成数字普遍更可信（拆股不再污染 RV，财报不再漏进窗口）。
- **持仓期轴**：溢价在 ~T+20 见顶，单票 T+60 衰减到不可卖。
- **条件轴**：单票可卖与否是**板块问题**，不是整体问题。
- **目标轴**：贵波动率不仅"收成正"，还**自身向下回归**、且对应的**单票还会跑输** —— 三个独立目标
  指向同一笔交易（在 RICH 时卖指数/信用/行业 ETF 以及精选板块单票的波动率，~一个月持仓）。

---

## 5. 工程决策

1. **测量层是共享核心**：`vrp_markout_core`（调整价 + 精确 RV + 通用 walk-forward/季度闸）被 harvest 与
   三个轴共同消费 —— 这是"内在联系"的代码化；不是五段拷贝的 markout。
2. **校正只作用于"目标"，不重算"信号"**：精确 RV 修正的是 harvest/方向性的**前瞻目标**；`vrp_z` 信号与
   ΔVRP 目标仍用 UW 口径的 `vrp_daily`（UW 独立计算，重算会偏离全站展示的 VRP）。item 1 的 validation
   量化了 UW-RV 近似与精确的差，也就间接框定了信号可能的偏差。
3. **无价格覆盖时回退**：`run_vrp_markout` 在标的无价格序列时回退到 UW `vrp_daily.rv`（降级、等价 v1）。
   生产里每个 vrp_daily 标的都源自 realized_volatility_history，所以跑的是精确路径。
4. **作业顺序**：corp-actions 17:35（OHLC 后）→ fundamentals 19:00（filing 财报腿）→ vrp_research 19:10
   （在 filing 之后，日历最新）。所有结果表**整表重写**，掉出的桶不会留下陈旧行。

---

## 6. 如何上线（合并 ≠ 立刻运行）

1. 合并到 main → cut release → mini deploy-poller 部署。部署会应用 migration 080 + 重启 worker。
2. corp-actions（17:35）与 vrp_research（19:10）是 **massive-0** 上的夜间作业；下一个工作日窗口才算出第一批。
3. 想立刻看：在你拥有的库上跑 `scripts/research/vrp_expansion_prerun.py`（会先 ingest，再算，再打印每张表）。
4. **消费方仍待接**：六张表已落库，option-wizard / Trade Insights 还没读取它们（与 UI 卡片一样，留作后续）。

---

## 7. 一句话结论

**把测量层校正（精确 corp-action 调整 RV + 真实财报日历）之后，"卖贵波动率"的图景清晰了：收成在 ~T+20 见顶；
单票并非整体不可卖、而是有明确的可卖板块（Power/Space/Fintech/Crypto…）；贵 VRP 既会向下均值回归、对应的
单票还会跑输。** 这套统一引擎把一个 cube 的一格，扩成了带 OOS 纪律的三轴全景。
