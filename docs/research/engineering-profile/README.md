# ARGON 验证与 profiling 汇总 — 2026-09-27

本轮完成：将静态审查中的重点疑点变成可重复的诊断与测量。没有修改业务代码、迁移、生产数据，没有提交、发布或部署。候选优化只存在于诊断脚本中。

- 分支：`chore/profile-review`；统一 worktree：`.worktrees/profile-review`。
- 基线：`9f094d0cb5b8d20f6103bae1bab2cea25c69c358`。
- 新文件仅在 `scripts/profile_review/` 与本文档目录；采样、逐次计时、查询计划、cProfile 和浏览器证据保留于忽略的 `output/profile-review/`。
- 三个 native worker 分别负责 DB/API、任务与研究计算、前端；主代理核验关键结论并独立重跑检查。此次 worker 继承 Astra，未降级；后续机械执行应使用 Sol，简单提取使用 Luna，主代理保留审查与验收。

## 已验证结果及建议顺序

| 顺序 | 实际代码 | 结果 | 证据边界与下一步 |
|---|---|---|---|
| 1 | `storage/technicals_repository.py::fetch_latest_macd_all` | 现有查询处理 267,923 条历史记录，返回 170 个 ticker。五组交替暖缓存 EXPLAIN：中位数 **88.994 → 19.596 ms**；同一快照下 170 行完全一致 | 真实生产数据库只读查询；候选使用 ticker 枚举 + LATERAL latest lookup，沿用现有索引。枚举仍读取历史索引条目。优先做窄 SQL 修改和结果等价检查；不是 HTTP 提速比例 |
| 2 | `reports/vrp_macro_drawdown.py::_build_loaded` | 5,212 条完整历史与最后 272 条比较：**492.075 → 6.253 ms**；最终行及末尾 252 个 RV/VRP 值一致。主代理独立重跑 **507.226 → 6.535 ms** | 真实捕获数据、离线计算、各七次；只覆盖此数据样本。实施前补缺失日期、as-of、修订与窗口边界；完整回测仍保留完整历史 |
| 3 | `worker/jobs/technical_daily_refresh.py::technical_daily_refresh` | 两个 ticker 实际调用四次 series builder。复用候选 **58.073 → 37.158 ms**，七组交替测量，DataFrame 与 snapshot 一致 | NVDA/SPY 各 1,300 条真实持久化 OHLCV；源与写入边界 mock，近期 OHLC overlay 缺省。纯计算减少约 36%，不是整项任务缩短 36% |
| 4 | `reports/single_stock.py::assemble_single_stock_report` 与 dealer inputs | 报告组装实测 32 次 SELECT；加初始 latest-run 查询为 33 次。四个分析查询在同次组装重复 | 真实只读执行；另有初始/内部 latest-run 重复。先复用已读 primitives，保留显式 run 与 latest overlay 各自语义；不以单次采样推算 p95 |
| 5 | `reports/volatility_series.py::assemble_volatility_series` | 一次组装产生 **250 + 344 = 594 行 upsert 意图**及一次 commit；全部拦截。离线组装中位数 69.912 ms，主代理重跑 64.653 ms | 已证实读取路径伴随持久化意图；没有执行 DML，没有测量写入、WAL 或锁成本。将它列为架构问题，不能据此断言是当前最大生产瓶颈 |
| 6 | Stock `TabBar.tsx` | 真实 production Next build + Chromium，未点击时 **7 个未访问 tab 预取**；mock 后端一次访问收到 16 个请求，其中 5 个完整 stock report 请求 | 两次 fixture 访问计数一致；不是生产用户流量或延迟。优先评估取消全量 tab 预取，不增加新缓存框架 |
| 7 | `ScanAllButton.tsx` / `LiveSpotsProvider.tsx` | 三项确定性复现：模拟 602 秒仍轮询；状态 GET 失败显示成功；模拟 5 秒出现 3 个未完成 spot 请求 | 组件与 fake timer/mock transport；先修 deadline 生命周期、失败状态和 in-flight guard。测试通过代表缺陷被复现，不代表已经修复 |
| 8 | `worker/jobs/option_surface_capture.py::option_surface_backfill` | 已有与目标集合数量相等但成员不同，函数跳过缺失成员 | 实际函数、mock 成员边界；应比较成员差集。证明逻辑缺陷，不证明生产已经漏采 |

路径以 `src/uw_scan/` 为 Python 根。前端精确路径及重现命令见分项报告。

## 测量方法与限制

数据库采样采用 PostgreSQL 强制只读 session/transaction 与 8 秒 statement timeout；没有调用可能写入的 HTTP GET、任务或外部行情供应商。原始数据来源、时间、代码路径与哈希保存在捕获文件。生产数据库 EXPLAIN 是实际服务器执行时间；Python profiling 在本机对捕获数据重放，二者不可混为端到端延迟。

latest-MACD 第一次观测为 3,388.134 ms，并发生物理读；未清理数据库缓存，不能称为严格冷缓存基准。正式比较采用五组交替暖缓存查询，完整保留每次结果。该查询无需先增加索引，已有主键可支持候选方案。

`pg_stat_statements` 重置时间为 2026-08-25，属于跨版本累计证据。历史 health COUNT 与写入量不能归因于当前 HTTP 实现；已有 health snapshot 优化不能被历史统计否定。最终优先级依据此次可重复查询与计算测量，而非累计耗时简单排序。

尚未测量：真实 HTTP p50/p95、并发连接池等待、实际 upsert/WAL/锁开销、完整 scheduled-job 时长、供应商调用费用、真实用户的预取流量，以及改动后的生产效果。没有给这些指标编造改善比例。

## 已完成的验收

- DB worker 捕获与重放通过；主代理独立 offline replay 通过 response/write-intent 与 bounded-window 等价断言。
- 主代理重跑任务诊断：两个 ticker 成功、四次 builder 调用、成员缺陷复现成功。
- 主代理重跑前端 Vitest：3/3 诊断通过；真实 production webpack build 和浏览器证据另存。Turbopack 曾因外部 node_modules 符号链接失败，改用已支持的 webpack 构建成功。
- `ruff check scripts/profile_review/` 通过。
- 浏览器 fixture 所有自建服务器已停止；未重启既有应用栈。
- 工作树只新增诊断脚本与报告；主 checkout 原有 `.serena/project.yml` 及 sector-RS 草稿保持原状。

## 报告与证据入口

- [DB/API：捕获、查询次数、离线重放命令](db-api.md)
- [任务与研究：计算复用、输入哈希、成员缺陷](jobs-research.md)
- [前端：production 浏览器与组件重现命令](frontend.md)
- SQL：`scripts/profile_review/technical_queries.py`；正式原始结果 `output/profile-review/technical-query-paired.json`。
- DB 正式结果：`output/profile-review/db-api/final-pinned/`；独立复核 `db-api/lead-replay/`。
- 任务正式结果：`output/profile-review/jobs-research/{validation.json,timing.json}`；独立复核 `jobs-research/lead-validation/`。
- 前端：`output/profile-review/frontend/`；截图 `output/playwright/profile-review/mock-stock-prefetch.png`。

原始捕获含真实内部数据与运行环境信息，保留于忽略目录，不纳入公共提交。当前工作是诊断完成，不是修复完成。下一步最小实施批次应为上述窄 SQL 优化与确定性逻辑修复，然后计算复用，最后才调整请求时持久化边界；不需要新增服务、数据库或框架。
