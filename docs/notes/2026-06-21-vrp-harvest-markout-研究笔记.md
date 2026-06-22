# VRP Harvest Markout 研究笔记（卖出"贵"波动率到底有没有稳定的钱可赚？）

> 日期：2026-06-21 ｜ 对应 Spec B：`docs/superpowers/specs/2026-06-19-vrp-harvest-markout-design.md`
> 代码：`reports/vrp_markout.py` ｜ 表：`vrp_harvest_verdicts`（migration 079）｜ API：`GET /api/regime/vrp-harvest`
> 本笔记里的实测数字来自 **2026-06-21 对生产 mini（option_wizard）的只读预跑**。

---

## 1. 研究背景与问题

### 1.1 我们已经在做什么

我们对波动率微笑的**斜率（slope）**挖得很深：skew 引擎（`reports/skew_markout.py`）把
25Δ risk-reversal 对未来收益做 markout，带完整的样本外（OOS）纪律。

但我们**从来没测过"水平（level）"层面的错价**，也就是方差风险溢价：

```
VRP = IV − RV   （隐含波动率 − 已实现波动率）
```

我们一直在算它、也持久化了它（`vrp_daily` 表里有 `vrp_z_20`），但**从没回答过唯一真正能拿来交易的问题**。

### 1.2 唯一要回答的问题

> **当 VRP 处于"贵"的状态时，卖出波动率到底能不能稳定地、正向地赚到这笔溢价 —— 在样本外、且排除掉财报陷阱之后？**

这是一个近在眼前、完全可检验的 alpha 问题。`vrp_daily` 已经有
**118 个标的 × ~313 个交易日（2025-05-13 → 2026-06-17），约 2.54 万个非空 `vrp_z_20` 观测**，
足够做 T+20 markout + 横截面分桶 + 分季度稳定性检验。

---

## 2. 方法论（拆开讲清楚）

### 2.1 信号（Signal）

用 `vrp_daily.vrp_z_20`——VRP 的 **20 日滚动 z-score**，把每个观测分成 `deviation_class`：

| deviation_class | 条件 | 含义 |
|---|---|---|
| **RICH** | `vrp_z ≥ +1.0` | 波动率相对自身近期基线**偏贵** |
| **CHEAP** | `vrp_z ≤ −1.0` | 偏便宜 |
| **NORMAL** | 其余 | 正常 |

> 用 z-score 而不是 VRP 绝对值，是为了让每个标的跟**自己**的历史比——
> NVDA 的 VRP 和 KO 的 VRP 绝对水平天差地别，但 z-score 让它们可比。

### 2.2 前瞻目标 —— "实现的 VRP 收成"（realized VRP harvest）

```
realized_VRP(t) = IV(t) − RV(t+20)
```

- `IV(t)`：信号日当天的隐含波动率。
- `RV(t+20)`：**向前数 20 个交易日**那一天读到的 trailing-21d 已实现波动率
  —— 约等于持仓窗口 `[t, t+20]` 内**真正走出来**的波动率。

直觉：这就是一个在 `t` 开仓、持有约一个月的**空波动率头寸实际赚到的溢价**。
当"卖出的 IV"比"后来真正实现的 RV"贵时，它就是正的。

> **单位提示**：iv/rv 都是十进制波动率（0.20 = 20%）。所以下文 `+0.0472` 读作
> **+4.72 个波动率点（vol points）**。

> **一个被记录在案的近似**：现有 RV 序列是 trailing-21d 的，在 `t+20` 读它来近似
> `[t, t+20]` 区间实现波动率（21d 窗 ≈ 20d 持仓）。若日后验证发现这个近似太松，
> 备选方案是直接从价格序列算 `[t, t+20]` 的前瞻实现波动率（spec 已写明）。

### 2.3 财报排除（Earnings exclusion）—— 关键

只要某个观测的前瞻窗口 `(t, t+20]` 里**含有一个财报日**，就把这条观测**丢掉**。

原因：那个窗口恰好就是"持仓穿越财报的空波动率交易"，正是我们 **"绝不持仓穿越财报"**
的铁律所禁止的。如果留着，IV 会朝着已知事件爬升、RV 在公布日跳空，会**严重污染**
RICH 单票桶，制造出假的"可卖"信号。

> 工程实现上：本仓库没有历史财报表，所以**从 `flow_events.next_earnings_date`
> 的 DISTINCT 集合重建**每个标的的财报日历（设计决策 1）。

### 2.4 分桶（Bucketing）

按 `(asset_class, deviation_class)` 二维分桶。`asset_class` 复用 skew 的分类器：

- `index_macro`（指数/宏观 ETF：SPX、SPY、QQQ、IWM、TLT、GLD…）
- `credit`（信用：HYG、JNK…）
- `sector_etf`（行业 ETF：XLF、XLE、SMH…）
- `single_name`（个股）

### 2.5 打分（Scoring）

- **主指标：RICH 桶的"绝对"平均 `realized_VRP`**（注意：**不做**横截面去均值——
  与 skew 的方向性测试不同，收成的命题是"溢价在水平上为正"，而非"相对全市场为正"）。
  RICH 桶里一个**正的、稳定的**均值，就是可卖的 edge。
- **条件证据：RICH − CHEAP 价差**。看"按 `vrp_z` 分条件"到底有没有真把收成区分开来，
  还是说不管贵不贵收成都差不多（那就说明信号没用）。

### 2.6 样本外纪律（OOS hygiene）—— 两道闸

1. **Walk-forward holdout（前瞻留出）**：按 `market_date` 时间排序，取**最后 40%**
   作为留出集（绝不泄漏未来）。要求全样本与留出集**符号一致**且都过幅度地板：
   - 全样本均值 ≥ `0.02`（2 个波动率点）
   - 留出均值 ≥ `0.01`（约一半，仿照 skew 的 0.003/0.005 比例）
2. **分季度灾难性退化闸（per-quarter catastrophic gate）**：如果**任何一个日历季度**
   的均值**反转了总体符号、且幅度更大**，这个桶就**判负**。
   —— 这是我们的 spec 永远要求的承重保护：**总体均值会掩盖某个 regime 里的崩盘**。

### 2.7 裁决（Verdict）

`HARVEST_SELLABLE` 需要**同时**满足：`n ≥ 20`、均值 > `0.02`、过 walk-forward、过分季度闸。
否则 `NONE`。置信度**最高只给 "med"**（仿照 skew——单一回测框架绝不喊 "high"）。

> **Kill criteria（什么情况说明"没有 edge"）**：若 RICH 桶均值不稳定为正、或
> RICH−CHEAP 价差≈0、或没有任何桶能过季度闸——诚实结论就是**没有可交易的 VRP 条件化
> edge**，记下 `NONE` 然后收手，**绝不松阈值去硬凑信号**。

---

## 3. 实测结果（2026-06-21，生产 mini 只读预跑）

```
DB host=100.66.147.98 name=option_wizard schema=uw_scan
vrp_daily 标的数：118
参与打分标的：115  ｜  跳过的 single_name（无财报覆盖）：3

asset_class   dev       n   n_hold     mean     hold  wf gate   spread  verdict
-------------------------------------------------------------------------------
index_macro   RICH    360    144  +0.0472  +0.0806   Y    Y  +0.0959  HARVEST_SELLABLE
index_macro   NORMAL  843    337  +0.0056  +0.0396   n    n  +0.0959  NONE
index_macro   CHEAP   411    164  -0.0488  -0.0107   n    Y  +0.0959  NONE
credit        RICH     68     27  +0.0471  +0.0354   Y    Y  +0.0466  HARVEST_SELLABLE
credit        NORMAL  231     92  +0.0186  +0.0046   n    Y  +0.0466  NONE
credit        CHEAP    85     34  +0.0006  -0.0200   n    n  +0.0466  NONE
sector_etf    RICH    208     83  +0.0340  +0.0242   Y    Y  +0.0649  HARVEST_SELLABLE
sector_etf    NORMAL  535    214  +0.0065  +0.0047   n    n  +0.0649  NONE
sector_etf    CHEAP   271    108  -0.0308  -0.0489   n    Y  +0.0649  NONE
single_name   RICH   4873   1949  +0.0238  +0.0187   Y    n  +0.0909  NONE
single_name   NORMAL 9424   3770  -0.0164  -0.0263   n    Y  +0.0909  NONE
single_name   CHEAP  5139   2056  -0.0671  -0.0888   n    Y  +0.0909  NONE
```

### 3.1 逐行读懂这张表

**`index_macro` / RICH —— 可卖（最强）**
- n=360，均值 **+4.72 vol pts**，留出 **+8.06**（留出比全样本还高！），两闸全过。
- 留出集更强意味着这个 edge **不是早期样本的残留**，而是越往近端越稳。指数级波动率
  在偏贵时卖出，约一个月平均能收到 ~5 个波动率点的溢价。

**`credit` / RICH —— 可卖**
- n=68（样本最少但过 n≥20），均值 **+4.71**，留出 **+3.54**，两闸全过。
- 信用 ETF（HYG/JNK）偏贵时同样有稳定收成。

**`sector_etf` / RICH —— 可卖**
- n=208，均值 **+3.40**，留出 **+2.42**，两闸全过。行业 ETF 偏贵时也能稳定收。

**`single_name` / RICH —— 判负（这是全表最有价值的一行）**
- n=4873，均值 **+2.38**（已经 > 0.02 阈值！），留出 **+1.87**，walk-forward **过了（Y）**，
  **但分季度闸没过（gate=n）→ NONE**。
- 翻译：个股波动率在偏贵时，**聚合**看起来也是正收成、甚至连前瞻留出都过了——
  **但至少有一个季度收成反转且幅度更大**（典型是某个财报/特异性事件密集的季度把空波动率打爆）。
- **承重闸正是为抓这种情况而设**：个股短波动率收成**不是一个可系统化、稳定的 edge**，
  哪怕平均数看着诱人。这正是 spec 的 kill criteria 在起作用——我们**没有**为了凑出一个
  漂亮结论而放过它。

### 3.2 横向看：信号确实有效

每个资产类里都呈现干净的 **RICH > NORMAL > CHEAP** 单调结构，且 RICH−CHEAP 价差全为正：

| asset_class | RICH−CHEAP 价差 | 解读 |
|---|---|---|
| index_macro | **+9.59 vol pts** | 按 vrp_z 分条件极其有效 |
| single_name | **+9.09** | 信号本身有区分力（但个股的尾部风险让它不可系统卖） |
| sector_etf | **+6.49** | 有效 |
| credit | **+4.66** | 有效 |

更要命的是 **CHEAP 桶大多为负**：
- index_macro CHEAP **−4.88**、sector_etf CHEAP **−3.08**、single_name CHEAP **−6.71**。
- 即：**在波动率便宜时卖出，平均是亏钱的**（卖了 4.9~6.7 个波动率点的"反向溢价"）。

这条不对称非常关键——它把"什么时候**别**卖"也量化了出来，而不只是"什么时候能卖"。

---

## 4. 具体可卖标的（RICH 桶里按平均收成排序）

> 这些是各资产类 RICH 桶内、按单标的平均 `realized_VRP` 排序的头部名字（仅 RICH 状态样本）。

- **index_macro**：`SLV(+0.068)` `SPY(+0.053)` `IWM(+0.051)` `SPX(+0.048)`
  `QQQ(+0.047)` `TLT(+0.040)` `DIA(+0.038)` `GLD(+0.036)`
- **credit**：`JNK(+0.088)` `HYG(+0.025)`
- **sector_etf**：`XLF(+0.053)` `IGV(+0.045)` `SMH(+0.038)` `XLE(+0.036)` `SOXX(-0.006)`
- **single_name**（**整桶判负**，列出仅供观察 / 不可系统卖）：
  `MARA(+0.218)` `CRDO(+0.204)` `TGT(+0.200)` `IREN(+0.195)` `HIMS(+0.171)` `APP(+0.161)` `NVDA(+0.153)` `CRS(+0.139)`

> 注意单票的平均收成数字（+0.15~+0.22）远高于指数（~+0.05）——这正是"诱饵"：
> 个股的高 VRP 是对**事件/跳空尾部风险**的补偿，季度闸把这种"高均值但会崩"的桶拦了下来。

---

## 5. 三个关键工程决策（为什么能跑在现有数据上）

1. **财报日历重建**：无历史财报表 → 从 `flow_events.next_earnings_date` 的 DISTINCT 集合重建。
   对于**完全没有财报覆盖的 single_name（本次 3 个）直接跳过**——因为无法兑现 `(t, t+20]`
   排除，留着会制造假 SELLABLE。index/credit/sector ETF 本就无财报，正常参与。
2. **单一数据源收成**：完全跑在 `vrp_daily`（iv/rv 单位一致）+ 价格/财报上，**不依赖**
   逐 strike 期权面（Spec A）。所以它**今天就能在现有数据上跑**。
3. **无需 backfill**（与 skew 引擎不同）：skew 的 cron 只"打分"已有快照，所以要一次性
   `skew_analytics_backfill`；而 VRP 直接读 `vrp_daily` 这张已经有 ~13 个月面板的表，
   **首次定时跑就会写出 verdict**，不需要单独 seeding。

---

## 6. 如何上线（合并 ≠ 立刻运行）

PR #147 当前 CI 全绿、mergeable。但**合并到 main 并不会让它跑起来**，链路是：

1. **合并到 main ≠ 部署**：mini 跑的是已发布 Release，不是 main HEAD。需要 cut 一个 release
   （`cut.sh prepare` → 合并 release PR → `cut.sh tag` → `release.yml` 发布 → mini 的
   deploy-poller ~120s 内拉取并跑 `macmini-prod.sh`）。
2. **部署会应用 migration 079 并重启 worker**：建表 `vrp_harvest_verdicts` + 重启 launchd
   worker（APScheduler 在 fork 时冻结代码/env，必须重启才注册新 job）。
3. **即便如此也不会立刻跑**：cron 是 `50 18 * * 0-4` = **ET 周一~周五 18:50**，无开机即跑。
   等下一个 18:50 ET 工作日窗口才会算出第一批 verdict（紧跟 18:45 的 skew markout）。
4. 想在 18:50 之前出结果：没有 API 触发口（`/jobs` 表只管 rescan），只能在 mini 上手动
   调 `vrp_markout_refresh(repo=...)`，或等当晚 cron。

---

## 7. 下一步建议（What's next）

**立即可做**
1. **Ship**：cut release，让 verdict 每晚自动落库——这是把研究变成"持续可消费决策"的最小一步。
2. **接入决策面**：把 RICH 桶的 `HARVEST_SELLABLE` 作为 option-wizard / Trade Insights
   "波动率是否贵到可卖"的硬门控——目前 verdict 只持久化、还没有消费方。

**近期增强**
3. **近似校验 job**：spec 写明 trailing-21d 在 t+20 读是个近似。加一个夜间校验，用
   价格序列直接算 `[t, t+20]` 前瞻 RV 对比，若偏差大就切到精确 fallback。
4. **UI 卡片**（spec 里的 deferred follow-up）：在 vol tab 上做一张"各资产类 RICH/CHEAP
   收成 + 可卖裁决"的卡，把 RICH−CHEAP 价差画出来，让"无 edge"也一眼可见。

**研究方向**
5. **单票的 WHERE 问题**：single_name 整桶被季度闸否，但说明"哪里"不稳——可以下钻到
   **按 sector 细分**或**更严的财报排除**，看个股里是否存在某个稳定子集；或者直接接受结论：
   **系统化地卖指数/信用/行业 ETF 波动率，而不要系统化卖个股波动率**。
6. **多 horizon 扫描**（T+5 / T+60，v1 之外）：看收成随持仓期的衰减曲线。
7. **其他目标变体**（spec 明确暂未选）：方向性 VRP 测试、ΔVRP 回归测试。

---

## 8. 一句话结论

**在波动率偏贵（vrp_z ≥ +1）时卖出指数、信用、行业 ETF 的波动率，过去 ~13 个月里
在样本外稳定赚到约 3~5 个波动率点的溢价；而个股即便平均数更诱人，也会被分季度灾难闸否决——
不可系统化卖。在波动率便宜时卖出则普遍亏钱。** 这正是这套 markout 想给出的、带 OOS 纪律的答案。
