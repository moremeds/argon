# 期权学习笔记（中文整理）

本目录整理自 `docs/screenshots/options/` 下的 71 张截图。这些截图是同一作者（小红书 / rednote ID **580133023**）的多篇期权主题笔记与信息图（多为 iOS "备忘录" 长文 + 配图卡片）。同一篇笔记被拆成多张连续截图，文件名是随机 UUID 且导出时间相同，因此本整理是**按内容连续性重建页序后**、按主题归并成 6 个文件。

> 说明：原文是中英混排（中文叙述 + 英文期权术语），本整理**保留原文措辞**，只做拼接、去重和分主题；不做改写或加料。

## 主题文件

| # | 文件 | 主题 | 截图数（去重后/含重复） |
|---|---|---|---|
| 01 | [期权市场底层逻辑-OI-IV-Skew-DealerHedge](./01-期权市场底层逻辑-OI-IV-Skew-DealerHedge.md) | 把期权市场理解为"库存 + 非线性风险 + 被动对冲 + 反馈"的系统；OI / Volume / IV / Convexity / Skew / Term Structure / Dealer Gamma Regime 串讲 | 15 / 30 |
| 02 | [Skew 的第一性原理](./02-Skew的第一性原理.md) | skew = 风险中性分布的形状；spot-vol correlation 决定方向；杠杆效应/波动率反馈/强制流不对称；股指·单股·商品·加密谱系 | 15 / 15 |
| 03 | [Option Flow 期权流的真正价值](./03-OptionFlow期权流的真正价值.md) | 期权流为何超前；Dealer Gamma Hedging 反馈；哪些 flow 有预测力；如何用于中短线 | 8 / 8 |
| 04 | [期权波动率期限结构 Term Structure 12 讲](./04-期权波动率期限结构TermStructure-12讲.md) | Contango/Backwardation/Flat/Hump/Kink + Skew/RR/BF 期限结构，12 张图卡（·01–·12） | 12 / 12 |
| 05 | [GEX（Gamma Exposure）完全拆解](./05-GEX-GammaExposure-完全拆解.md) | GEX 定义、公式推导（S²）、正负 GEX、Gamma Flip、Vanna/Charm、用途，单页 8 板块 | 1 / 1 |
| 06 | [订单流与市场微观结构信号 30 种](./06-订单流与市场微观结构信号-30种.md) | 现货/订单流层面的 30 类信号（Footprint、DOM、Sweep、Absorption、Iceberg、Toxic Flow…） | 5 / 5 |

合计：去重后 56 张独立内容页；含重复共 **71** 张截图（主题 01 中有 15 页各被截了两遍）。

## 备注

- **重复页**集中在主题 01（OI/IV/Skew/Dealer Hedge 那篇被完整截了两套），整理时已合并为单一版本。
- 主题 04（Term Structure）与 05（GEX）、06（订单流）是**配图卡片/信息图**，本整理已把图中文字与图表要点逐条转写。
- 主题 02 自述参考来源为 `theoptionsbook.com` 附录 B「Skew 的第一性原理」。
