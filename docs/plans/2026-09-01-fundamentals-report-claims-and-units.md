# Fundamentals 报告：传导措辞与指标口径修正计划

> **执行说明：** 本文是待用户确认的计划，不是执行授权。批准后按仓库规定使用 `execute-plan` 单线执行；先建 `.worktrees/fundamentals-report-claims-and-units/`，建议分支 `fix/fundamentals-report-claims-and-units`。本次不提交、不推送、不部署；后续 commit 仍需明确授权。

**Goal:** 让现有 AI Chain Desk 与两个案例准确表达“经营指标对照”，不再声称验证了资金传导；明确数字的单位、时间、样本与缺失含义。

**Architecture:** 仅修正现有前端的标题、解释、数字格式与失去依据的衍生展示，继续使用现有 API 和持久化数据。不改变原始指标算法、数据样本、接口、数据库或图形引擎；直接删除不再使用的前端放大比及相关叙事。

**Tech Stack:** Next.js / React / TypeScript，现有 Canvas 图形；Vitest 与现有 Playwright 用例。

**基线：** 2026-09-01，主目录 HEAD `a01a1cb8`（detached HEAD）；存在用户未提交修改。本计划文档是本轮唯一新增文件。此前已实看 Mac mini 的主页面与 cases 页面，线上显示 v0.13.2；此次以当前代码复核变更边界，不假定线上 SHA 等于本地 HEAD。

## 1. 最小范围与非目标

覆盖两个实际页面：

- `/fundamentals` 跳转后的 `/fundamentals/ai-semi`。
- `/fundamentals/ai-semi/cases`，含 optical interconnect / datacenter buildout。

本次明确不做：

- 不新增报告、研究首页、分部数据采集、客户关系数据库或传导模型。
- 不补 META、不移除 IBM、不统一两组研究样本，不重算历史 Capex；先如实标注现有边界。
- 不把 TTM 增速改为单季增速，不改毛利率或估值算法，不做历史回填。
- 不把 3D 图重做成 2D，不改旋转、半径映射或共用尺度，不新增图表库。
- 不改 API 字段、OpenAPI、数据库、worker、个股 fundamentals 页面或雷达。
- 不补新投资判断、预测、排名、自动证伪阈值；“数据限制”不再冒充经营假设的证伪。
- 不修改历史研究记录来让它符合新措辞；不全仓替换相关术语。

## 2. 已核实的事实与约束

| 事实 | 代码证据 | 对计划的约束 |
|---|---|---|
| 案例放大比只是上游营收增速中位数 / 客户营收增速中位数 | `web/lib/fundamentals/desk.ts:336-362` | 删除该比值及强弱传导叙事，不改名后继续作为主结论 |
| `rev_yoy` 来自 TTM 收入相对前一年 TTM 的增长；毛利率是单季 | `src/uw_scan/fundamentals/features.py:126-153`；`src/uw_scan/worker/jobs/fundamentals_desk_rollup.py:131-150` | 明确 TTM / latest quarter，禁止统一误标“季度同比” |
| 案例逐公司取最新记录；同一公司可出现在多个环节 | `src/uw_scan/reports/fundamentals_desk_spine.py:209-239` | 不是共同财季，也不是分部收入；重复成员必须说明 |
| 案例 API 没有逐行财期、估值方法/历史窗口、缺失原因 | `src/uw_scan/models/fundamentals_desk.py:487-505` | 不伪造日期或原因，不承诺本轮补齐这些元数据 |
| Capex 来自现金流表的供应商 `capital_expenditures` 字段，按财期结束日归入日历季度 | `src/uw_scan/reports/fundamentals_desk_spine.py:124-184`；`src/uw_scan/storage/fundamentals_desk.py:126-163` | 标明供应商字段与日历归桶，不宣称租赁已统一或全部是 AI 支出 |
| 现有测试直接要求出现 amplification、4.08 和旧标题 | `web/tests/unit/industryDesk.test.tsx:657-730`；`web/tests/e2e/fundamentals-chain-desk.spec.ts:46-64` | 必须同步改这些断言，不能为保住旧测试而保留错误叙事 |

## 3. 最小文件集

预计 11 个现有前端文件，全部属于这两个页面；没有新增业务文件：

| 用途 | 修改文件 |
|---|---|
| 主页面、案例入口、五节标题 | `web/app/fundamentals/ai-semi/page.tsx`；`web/app/fundamentals/ai-semi/cases/page.tsx`；`web/components/fundamentals/DeskMasthead.tsx` |
| Capex / 链图 / 限制说明 | `web/components/fundamentals/CapexPanel.tsx`；`web/components/fundamentals/ChainMapPanel.tsx`；`web/components/fundamentals/DeskLimits.tsx` |
| 案例卡、图、表 | `web/components/fundamentals/CaseCards.tsx`；`web/components/fundamentals/CaseFunnels.tsx`；`web/components/fundamentals/CaseStageTables.tsx` |
| 估值文字与已有格式化 helper | `web/components/fundamentals/ValuationPanel.tsx`；`web/lib/fundamentals/desk.ts` |

配套仅修改 `web/tests/unit/industryDesk.test.tsx`、`web/tests/unit/capexPanel.test.tsx`、`web/tests/e2e/fundamentals-chain-desk.spec.ts`，以及实现分支的 `CHANGELOG.md` `[Unreleased]` 条目。若实际需要更多业务文件，先说明原因，不顺手扩范围。

## 4. 执行步骤

### P1 — 撤掉未经验证的传导主张

**文件：** 上表中的两个页面、DeskMasthead、CapexPanel、ChainMapPanel、DeskLimits、CaseCards、CaseFunnels、desk.ts；相关现有测试。

1. 在隔离 worktree 核对基线、相关目录规则及用户修改；跑两份目标单测记录基线。不要切换或清理当前主目录。
2. 先调整现有 CaseCards 主路径和页面标题断言，使其要求新表达；确认旧实现因这次需求而失败。
3. 保持现有五节顺序、路由和页面语言，统一 masthead 与正文标题：

| 当前 | 新标题 |
|---|---|
| Is the money still coming? | How is sample capex changing? |
| Where does it land? | How do industry groups compare? |
| Does it transmit? | How do case groups compare? |
| What am I paying for it? | Where is valuation versus own history? |
| What would falsify this? | What are the data limits? |

4. 开篇替换为事实边界，例如：`Company-level growth, reported margins and own-history valuation across selected AI-related industry groups. This page does not trace payments or establish causal transmission.` 不再写“every revenue dollar is somebody else's capex”“唯一外生输入”“end-to-end dollar tracing”“下游无一幸免”。
5. 案例卡撤掉 4.08× / 2.25×，改为并列的 `Customer-group TTM revenue growth` 与对应另一组的 `TTM revenue growth`，各自显示原有中位数。不计算替代倍数、差分分数或排名；保持案例顺序与成员数。
6. 删除 `WhyTwo`、`FunnelFindings` / `barelyOpens` 等以该比值选择强弱案例的叙事；删除 `CaseSummary.amplification` 及其计算。`belowCustomer` 若无剩余调用方一并删除。保留仍有用途的组别排序、成员去重和 Capex 自身历史倍数，不泛化清理。
7. 图上不再写“美元向下流”“吸收/放大”“same dollar, two transmissions”。保留现有图形，改标题为 `Stage growth comparison`，用组别标签与增长值并列，移除案例标题中的数值传导箭头。说明分类排序不是采购链路；组别之间可能是并行供应关系。
8. CaseCards 或案例说明只保留一处简短限制：相同公司可跨组，使用公司整体数据，不代表这些业务分部各自增长；两案例与 Capex 面板不是同一个买方样本。
9. ChainMapPanel 中删除“组间极差之比 = 3.1 倍解释力”的推论，保留原始极差作为描述；把增长/毛利率相关系数解释限定为当前样本，不称经济规律。DeskLimits 保留现有数据限制，不编造商业证伪条件。
10. 同步修正本次触及前端文件中与新表达冲突的注释，跑目标单测。后端旧 docstring / schema 描述不属于本轮变更；本计划不能被称为“整个 API 的语义也已修复”。

**验收：** 两页及 hover/Canvas 标注不再作资金传导或放大主张；原有公司值、组别中位数、覆盖计数及图形行为保留。旧倍数代码及其专用叙事测试不留死路径。

### P2 — 单位、时间口径、样本和缺失含义一致

**文件：** CapexPanel、ChainMapPanel、CaseCards、CaseFunnels、CaseStageTables、ValuationPanel、DeskLimits、desk.ts；相关现有测试。

1. 在现有用例上补充下面的展示断言后再实现。默认不新建测试文件；确需新增时，总计最多 1 个主路径、1 个关键失败路径。
2. 表格、图例、hover 和解释使用同一组标签，不只在页尾解释：

| 数据 | 展示规则 |
|---|---|
| `rev_yoy` | `Revenue growth (TTM YoY, %)`；四个季度收入和 / 上年前四季度收入和 − 1 |
| `gross_margin` | `Reported gross margin (latest quarter, %)`；单季毛利 / 单季收入；不把所有公司一律标成 GAAP |
| 组别 median | 明确是有效公司指标的等权中位数，不是收入加权，也不是该环节市场总体增长 |
| Capex 金额 | 保留现有数值，图表明确 `USD bn`，解释 1 bn = 10 亿美元；正数表示支出规模 |
| Capex / revenue | `Sample capex / sample revenue (%)`，分母不是 AI 收入，也不是现金流 |
| `spot_percentile` | `P20 · rich` / `P80 · cheap` 等；标题和可见说明限定“相对自身历史”；高收益率分位表示历史相对便宜，不是折价 80% |
| 百分点变化 | 使用 `pp (percentage points)`，不与 `%` 增长率混用 |

3. `desk.ts` 内加一个极小的估值展示函数供 CaseStageTables、CaseFunnels、ValuationPanel 共用（已有三个真实调用方）。使用现有 0.3/0.7 rich/cheap 界线，不改阈值、排序或估值方法。格式如 `P${Number((p * 100).toFixed(1))} · rich/cheap/mid-range`；null 用中性缺失文本。坐标轴也显示 P0–P100，不混用 0–1 裸数字。
4. Capex 可见说明固定以下边界，成员名单仍动态取 API：样本由当前 taxonomy 决定，并非完整 AI 买家集合，不应假设与案例客户组相同；取供应商现金流表字段，未统一融资租赁等调整；不等于纯 AI 支出。本次核对时不含 META 是现状证据，不写成永久硬编码说明，也不把 META 当作币种排除项。不得将其改写成已经核对所有公司的统一“现金 Capex”。
5. 财期说明明确：Capex 是按各公司财期结束日归入日历季度；案例/链图取各公司最新可用记录，期间可能不同，不代表同步的同一季度，也不是历史时点回放。不给 API 没有的逐行日期补默认值，不把日历面板 `as_of` 冒充全页数据日期。
6. `rev_yoy=null` 改为 `TTM growth unavailable`；`reporting/total` 改为 `growth available n/N`；不能再由此推出“没有财报”。继续保留公司、空心标记及缺失排除规则，不改成零。估值无 band 只称不可用，不统一归因为历史不足。
7. Capex 空序列只表达“本样本没有可用季度数据”，不由空序列推断“所有公司都不是 USD”；保留 API 请求失败与空数据的区别。先复用已有测试形状，若缺口确实存在，仅新增上述 1 个关键失败路径。
8. 图形半径仍是现有截断映射，不声称面积/体积代表金额；说明 0–80% 的显示区间，负增长、缺失和超范围值应看表格。不要在本轮修改坐标映射或对原值截断。
9. 删除相关单测里只服务于已移除 amplification / 强弱叙事的断言，更新现有缺失与覆盖测试。混有单季 fixture 的旧测试不改造成数据回填工程；只在本轮所用展示用例中清楚区分测试值与口径验证。

**验收：** 同一数字在卡片、表格、hover 和图例中含义一致；TTM 与单季可直接区分；P 分位方向明确；缺失不变零、不编造原因；计算及 API 保持不变。

### P3 — 验证与交付

**文件：** 三份现有测试、`CHANGELOG.md`；不新增验证基础设施。

以下命令均在实施 worktree 的 `web/` 目录执行，本计划编写时未运行这些测试：

```bash
npm run test -- tests/unit/industryDesk.test.tsx tests/unit/capexPanel.test.tsx
npm run typecheck
npx eslint app/fundamentals/ai-semi components/fundamentals lib/fundamentals/desk.ts tests/unit/industryDesk.test.tsx tests/unit/capexPanel.test.tsx tests/e2e/fundamentals-chain-desk.spec.ts
```

在现有本地开发数据库和已验证端口可用后，复用原浏览器测试；不得误连生产数据库、重用运行旧代码的页面，或为了过测试新增基础设施：

```bash
npm run build
PLAYWRIGHT_WEB_PORT=3011 npm run test:e2e -- tests/e2e/fundamentals-chain-desk.spec.ts
```

3011 须先确认空闲；配置仍使用 API 8400，该服务须确认连接开发库。若当前配置/数据不能支持该测试，如实记录环境阻塞，使用当前 worktree 的实际页面人工核对，不把未执行说成通过。

人工验收两页，截图放 `output/playwright/`：

- 新五节标题、案例入口和实际页面一致；无传导/放大主张或 4.08× headline。
- 案例原始增长值、毛利率、成员、等权中位数不变；重复公司仍可见。
- 表头、hover、Canvas 标签注明 TTM / latest quarter / USD bn / P 分位；长标签不遮挡图表或表格。
- 缺失仍为空值，公司不消失；Capex 完整/部分季度与错误提示未退化。
- 现有两个图能绘制、同步拖动、主题切换，无新增控制台错误；不新增估值排序。
- 仓库根运行 `git diff --check`，检查 diff 不包含 API/schema/worker/数据/依赖或无关文件变化。
- 在 `[Unreleased]` 记录展示语义修正，明确没有重算数据。报告确切命令与结果，不用“单测全绿”代替浏览器验收。

发布不是这份计划的默认授权：得到 commit/PR/merge/release 授权后再按仓库工作流执行，禁止直推 main。线上未部署前，只能称“本地修正已验证”；发布后另核对 Mac mini 实际镜像/版本与两页显示。无数据库变更，回退只需走正常 PR/发布回退流程。

## 5. 计划校验摘要（plan-validator）

### 1) Context Snapshot

仅校验当前两个页面的展示纠偏；已读对应实现、API 形状与现有测试。数据源正确性、历史研究有效性、生产部署状态不在本次验证范围。

### 2) Executive Verdict

**ready，待用户批准执行。** 所有改动可在现有前端完成；无新增依赖、接口、数据迁移或外部服务。没有必须由用户补充的技术选择。

### 3) Plan Coverage Matrix

| Item | Status / Risk | Files / Evidence | Tests / Gap / Fix |
|---|---|---|---|
| P1 撤掉传导结论 | valid / medium | `desk.ts:336`、`CaseCards.tsx:64`、`CaseFunnels.tsx:454` | 改 industryDesk / 现有 e2e 旧标题断言；同时删除专用计算与叙事，避免只改 headline |
| P2 指标语义 | valid / medium | `features.py:126`、`CaseStageTables.tsx:148`、`ValuationPanel.tsx:183`、`CapexPanel.tsx:362` | 扩现有单位/缺失断言；最多两条新测试，逐行日期与缺失原因不在当前 API 中，不能伪造 |
| P3 验证交付 | valid / low | `web/playwright.config.ts:3-36`、`web/package.json:7-19` | 两份 Vitest、一份既有 e2e、定向 lint/typecheck、实际页面；部署授权单独处理 |

### 4) Findings By Severity

- **F-1 / medium：** 仅替换“amplification”单词无法修正比值驱动的强弱叙事。P1 已改为删除该展示和专用分支。
- **F-2 / medium：** `CaseStageMember` 缺少逐行时间和缺失状态，强行补全会扩大 API 范围。P2 已改为真实口径说明和中性不可用标签。
- **F-3 / low：** 单测 stub 了部分 Canvas，单测通过不能证明标签可读。P3 保留既有真实浏览器检查。

### 5) Improvement Points

| Priority | Improvement | Benefit | Effort |
|---|---|---|---|
| P0 | 删除比值而非重命名 | 不留下未经验证的主结论 | S |
| P0 | 保留现有数据、明确口径 | 避免修文案时隐性改指标 | S |
| P1 | 更新既有测试并做视觉验收 | 验证真实显示，不补测试体系 | S |

### 6) Suggested Revised Plan

按 P1 → P2 → P3 单线执行；P1/P2 各自更新相关现有断言，P3 做最终联验。不建立平行实现或多 Agent 工作流。

### 7) Test And Validation Plan

见 P3 的确切命令与人工检查清单。现有用例优先；新增最多 1 主路径 + 1 关键失败路径，不增加测试文件/框架。

### 8) Open Questions

无阻塞技术问题；仅等待用户确认计划。commit、推送和发布未获授权。

### 9) Confidence And Assumptions

代码范围与可行性信心高；假设执行时沿用本次核实的指标算法。实施前重新核对基线，若字段实际语义已变先更新计划。逐行财期、统一租赁口径、业务分部和因果传导仍未验证，不能在验收时声称解决。
