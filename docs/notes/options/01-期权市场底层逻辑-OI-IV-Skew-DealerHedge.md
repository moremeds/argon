# 期权市场底层逻辑全梳理：OI、IV、Skew 与 Dealer Hedge

> 来源：小红书笔记（rednote ID 580133023），由 `docs/screenshots/options/` 截图整理。
> 主题：把期权市场理解为一个关于"库存、非线性风险、被动对冲和反馈机制"的系统，而不只是"看涨还是看跌"。

---

## 封面：核心框架一图流

**OPTIONS MARKET — OI、IV、SKEW 与 DEALER HEDGE**

四个关键词：

- **风险库存（Risk Inventory）**
- **波动定价（Vol Pricing）**
- **尾部风险（Tail Risk）**
- **对冲驱动（Hedge Flow）**

几张核心图：

- **OI 分布与 Gamma 暴露**：OI 集中在哪里，Gamma 风险就集中在哪里（图中 Gamma 集中在 ~450 strike，标注 High Gamma Concentration）。
- **SKEW：尾部风险的供需定价**：看哪一侧的 Convexity 更稀缺（Put IV / ATM IV / Call IV 三条曲线随 Moneyness 变化）。
- **TERM STRUCTURE：波动率期限结构**：不同期限的不确定性定价（Today vs Yesterday，1W→1Y）。
- **IV Surface 3D**：Moneyness × Expiry 的隐含波动率曲面。

**DEALER GAMMA REGIME：决定市场微观行为**

- **LONG GAMMA**：Sell High / Buy Low → Mean Reversion（波动抑制，均值回归）
- **SHORT GAMMA**：Buy High / Sell Low → Acceleration（波动放大，趋势延伸）

**HEDGE FLOW FEEDBACK LOOP：反身性循环**

```
Options Positioning (Inventory)
        → Dealer Hedge Flow
        → Underlying Price Move
        → Greeks Change / Hedge Requirement Changes
        → （回到 Options Positioning）
```

**核心分析框架 FRAMEWORK**

```
库存结构 (OI) → Greeks 暴露 (Gamma 等) → 波动定价 (IV / Skew) → 对冲行为 (Hedge Flow) → 价格行为 (Underlying)
```

一句话脚注：

- OI = 风险库存
- IV = Convexity 价格
- Skew = Tail Risk 供需
- Hedge = 价格驱动因子

---

## 一、指标不要孤立看：它们是风险结构的不同切面

期权市场里，很多指标如果单独看，容易被误读。OI、Volume、IV、Skew、Put/Call Ratio 这些数据本身并不直接等于方向信号，它们更像是市场风险结构的不同切面。真正需要关注的，不是某一个指标孤立地变大或变小，而是这些指标放在一起之后，能否说明市场里的风险库存、convexity demand，以及后续可能产生的 dealer hedge pressure。

## 二、OI：未平仓风险库存，不是方向

OI，也就是 Open Interest，本质上不是方向指标，而是未平仓风险库存。每一张期权合约背后，都同时存在一个 long 和一个 short。因此，Call OI 增加并不天然代表市场看涨，Put OI 增加也不天然代表市场看跌。Call OI 的增加，可能来自买方主动买 call，也可能来自卖方主动卖 call；Put OI 的增加，可能来自 downside protection demand，也可能来自 short put / vol selling。

所以，OI 更准确的理解方式是：市场里仍然有多少期权合约没有被关闭，这些合约对应着多少仍然存在的风险暴露。它反映的是 inventory，而不是 view。

从这个角度看，total OI 的意义有限。更重要的是 **OI 分布在哪里**。也就是说，真正需要关注的不是"市场总共有多少 OI"，而是这些 OI 集中在哪些 strike，集中在哪些 expiry，集中在哪些 delta 区域，以及它们对应的 gamma exposure 有多大。

这也是为什么 strike concentration 和 expiry concentration 很重要。某些 strike 附近如果堆积了大量短期期权 OI，那么当 underlying price 接近这些位置时，dealer 的 hedge requirement 可能会快速变化。此时，价格运动就不只是普通买卖盘的结果，也可能受到 options positioning 的反向影响。

这个机制可以抽象成：

```
positioning → hedge flow → underlying move → positioning reinforcement
```

也就是：期权仓位结构影响 dealer hedge flow，dealer hedge flow 影响现货价格，现货价格变化又进一步改变 option Greeks 和 hedge requirement，从而形成一种 reflexive feedback loop。

## 三、Dealer Gamma Regime：同样的上涨，结果可能完全不同

在 short-dated options 比例较高的市场里，这种机制会更加明显。尤其是 0DTE、weekly options，以及 SPX、QQQ、NVDA、TSLA 这类期权活跃度很高的标的，underlying 的短期价格行为有时并不能只从基本面或普通资金流角度解释，而需要结合 options inventory structure 和 dealer gamma regime 来理解。

这里的关键不是判断"市场看涨还是看跌"，而是判断市场当前处在什么样的 dealer gamma environment 中。

- 如果 dealer 整体处于 **long gamma** 状态，hedge flow 往往会产生一定的 mean-reverting effect。价格上涨时，dealer 可能需要卖出 underlying hedge；价格下跌时，dealer 可能需要买入 underlying hedge。这种机制容易压制 realized volatility，使市场表现出更强的区间震荡特征。
- 如果 dealer 整体处于 **short gamma** 状态，hedge flow 则可能放大价格运动。价格上涨时，dealer 可能需要买入 underlying hedge；价格下跌时，dealer 可能需要卖出 underlying hedge。这种机制容易形成 acceleration、squeeze 或者 panic selling。

也就是说，同样是价格上涨，在不同 gamma regime 下，后续的市场行为可能完全不同。

因此，OI 的真正价值不在于直接判断方向，而在于推断潜在 hedge pressure。市场上大量未平仓合约本身并不等于 bullish 或 bearish，但如果这些合约集中在某些关键位置，并且对应较高 gamma exposure，那么它们就可能成为后续价格行为的重要约束或放大器。

## 四、Volume 与 OI change：要区分活跃度和库存变化

Volume 和 OI 之间也需要区分。Volume 代表交易活跃度，OI change 代表未平仓仓位结构的变化。高 volume 不一定意味着新风险建立，也可能只是仓位换手。只有当 volume 与 OI change 结合起来看时，才更有解释力。

例如：

- 高 volume 之后 OI 明显增加，通常说明新的风险库存被建立；
- 高 volume 但 OI 变化不大，可能说明大量换手，opening 和 closing 互相抵消；
- 高 volume 之后 OI 明显下降，则可能说明原有风险库存正在被关闭。

也就是说，OI change 是理解 volume 性质的重要补充。

## 五、IV：交易的是 option premium，不是波动率本身

接下来是 IV。

IV，也就是 Implied Volatility，经常被简单理解成"市场对未来波动率的预测"。这个说法并不完全错，但容易让人忽略一个更重要的事实：**市场真正交易的是 option premium，而不是 IV 本身。IV 是从期权市场价格中反推出来的参数。**

也就是说，IV 并不是一个独立地先变化、再决定期权价格的东西。现实中发生的是：市场参与者交易期权，期权 premium 被重新定价，然后模型再根据这个价格反推出对应的 implied volatility。

所以，IV expansion 的本质并不是"波动率自动升高"，而是 option premium 被市场买贵了。更具体地说，如果一张 option 被持续 aggressively bid up，比如买盘不断 hit ask，offer 被持续 lift，dealer 不断提高报价，而 option price 的上涨超过了 underlying move 通过 delta/gamma 所能解释的范围，那么模型最终只能通过提高 IV 来解释这个价格。

这也是为什么单纯看到期权价格上涨，并不能马上说 IV 上升。期权价格本身会受到 underlying move 的影响。比如 call 在股票上涨时价格自然会上升，这是 delta 和 gamma 能解释的一部分。只有当 call price 的上涨超过了 underlying price move 所能解释的部分，才意味着 vol expansion 或额外的 option demand。

换句话说，需要区分两件事：

1. option price 因为 underlying move 而上涨。
2. option price 因为自身供需变化而被重新定价。

前者更多是 delta/gamma effect，后者才更接近 IV expansion。

这一点在分析 call IV 和 put IV 时尤其重要。Call IV 上升，并不必然意味着市场看涨；Put IV 上升，也不必然意味着市场看跌。更准确地说，某一侧 IV 上升，代表这一侧的 option premium 正在被重新定价，背后可能是对应方向的 convexity demand，也可能是事件风险、库存压力、hedging demand 或者 market maker risk limit 的变化。

## 六、Convexity：IV 是凸性的价格

这里需要引入一个核心概念：**convexity**。

期权市场真正交易的，不只是 direction，而是 convexity。股票更接近线性资产，价格上涨多少，持仓收益大致按比例变化。期权则不同，尤其是 long option，它的收益结构是非线性的。期权买方支付 premium，换取的是未来发生大幅运动时的非线性收益暴露。

因此，**买 call 不只是表达"看涨"，而是购买 upside convexity；买 put 也不只是表达"看跌"，而是购买 downside convexity。市场在期权上支付的 premium，本质上是在给某种大幅运动的可能性定价。**

从这个角度看，IV 可以理解为 convexity 的价格。当市场愿意为未来大幅波动支付更高 premium 时，IV 就会上升。这个大幅波动可以是向上，也可以是向下，也可以是事件驱动下的双向不确定性。

例如，财报前 IV 上升，通常并不代表市场单纯看涨或看跌，而是市场在重新定价 event uncertainty。财报本身可能带来明显 gap move，因此 call 和 put 的 premium 都可能上升。此时 IV expansion 更多体现的是 movement pricing，而不是 direction pricing。

但在 panic 或 crash environment 中，put IV 往往会上升得更快。这是因为 downside protection demand 急剧增加，市场在抢 downside convexity。特别是在 equity market 中，市场下跌通常伴随着 realized volatility 上升和 hedging demand 上升，因此 put wing 会明显变贵。

相反，在 squeeze 或 momentum environment 中，call IV 可能会相对增强。比如某些高动量股票、meme stock 或者 short squeeze 场景中，市场会大量抢 OTM calls，导致 upside convexity 被重新定价。此时 call wing 可能变得异常昂贵，甚至出现 call skew 明显增强。

## 七、Skew：不同方向 tail risk 的供需结构

这就引出了 skew 的重要性。单独看 absolute IV 往往不够。真正有信息量的是不同 strike、不同 expiry、不同 moneyness 上的 IV 如何相对变化。Skew 本质上反映的是不同方向 tail risk 的供需结构。

在 equity market 中，常见结构是 **downside skew**，也就是 OTM put IV 高于 OTM call IV。这并不表示市场长期看跌，而是因为机构投资者长期持有 equity exposure，需要持续购买 downside protection，所以 downside convexity 存在结构性需求。长期 protection demand 使得 put wing 更贵，这是 equity vol surface 的一个常见特征。

因此，Put IV 高于 Call IV 本身并不是新信息。**真正值得关注的是这个差值是否发生异常变化。** 例如，put skew 突然 steepen，可能意味着 downside hedge demand 快速增加；call IV relative strengthening，可能意味着 upside chase、short squeeze risk 或者 dealer upside inventory pressure 正在增强。

所以，更重要的问题不是"IV 高不高"，而是：**哪一段 vol surface 在变贵？**

## 八、Term Structure 与 vol surface 的拆解维度

具体地问：

- 哪一个 expiry 的 vol 在变贵？
- 是 ATM vol 上升，还是 wing vol 上升？
- 是 put wing 被重新定价，还是 call wing 被重新定价？
- 是整个 term structure 上移，还是 front expiry 被单独 bid up？

这些问题比单独看某一张期权的 IV 更重要。

Term structure 也同样重要。不同 expiry 的 IV 反映的是不同时间维度上的不确定性定价。财报、CPI、FOMC 这类事件通常会集中影响 front expiry 或覆盖事件日期的 expiry。如果只是某个短端 expiry IV 明显上升，而远端 IV 没有同步变化，这更像 event vol repricing；如果整个 term structure 同时上移，则可能代表更广泛的 volatility regime shift。

因此，vol surface 的变化可以拆成几个维度：

1. **level shift**：即整体 IV 是否上移。
2. **skew shift**：即 call wing 和 put wing 的相对变化。
3. **term structure shift**：即短端和长端 vol 的变化是否一致。
4. **wing repricing**：即 tail convexity 是否被重新定价。
5. **event concentration**：即某个 expiry 是否因为事件被单独 bid up。

这些维度组合起来，才构成对市场风险结构的完整观察。

## 九、为什么单笔 flow 很 noisy

在没有逐笔成交方向数据的情况下，这种框架尤其重要。很多数据源只能提供 minute snapshot、Greeks、OI、Volume、IV，而没有明确的 aggressor side。即使有逐笔成交，也很难完全准确判断成交方向，因为期权市场存在多交易所、NBBO、midpoint execution、spread legs、rolls、hedges、complex orders 等问题。

因此，单笔 flow 本身非常 noisy。所谓"大单买 call"或者"大单买 put"，如果没有上下文，很可能被误读。它可能是方向性交易，也可能是 spread 的一条腿，也可能是 delta hedge，也可能是 roll，也可能是 vol arb，也可能是 portfolio hedge。

相比之下，inventory structure 和 vol surface deformation 更稳定。因为它们不是单笔交易的噪声，而是市场整体风险库存和定价结构的结果。

## 十、完整的观察框架

因此，比较完整的观察框架应该是：

1. 先看 **OI 分布**，判断风险库存集中在哪里。
2. 再看 **gamma exposure**，判断这些库存对 dealer hedge 的敏感度。
3. 再看 **volume 与 OI change**，判断风险库存是在新增、换手还是消退。
4. 再看 **IV change**，判断 option premium 是否被重新定价。
5. 再看 **skew**，判断哪一侧 convexity 更稀缺。
6. 再看 **term structure**，判断这是短期事件定价，还是更广泛的 vol regime shift。
7. 最后结合 **underlying price behavior**，判断价格运动是否正在触发新的 hedge flow。

## 结语：期权市场是一个反馈系统

在这个框架下，期权市场不再只是"看涨还是看跌"的问题，而是一个关于库存、非线性风险、被动对冲和反馈机制的系统。

很多短期市场行为，尤其是在高期权活跃度标的中，并不能只用基本面变化解释。Underlying price 有时会被 options market 反向驱动。大量 OI、短期限、高 gamma、集中 strike、dealer short gamma、call wing repricing 或 put skew steepening，这些因素叠加在一起，就可能改变价格运动的路径和速度。

因此，Options Market 的核心不是单独判断某个指标的方向含义，而是理解几个结构之间的联动：

- **OI** 描述风险库存。
- **Gamma** 描述库存对价格变化的敏感度。
- **IV** 描述 convexity 的价格。
- **Skew** 描述不同方向 tail risk 的相对供需。
- **Term structure** 描述不同时间维度上的不确定性定价。
- **Dealer hedge** 描述这些结构如何反作用于 underlying。

这些变量组合在一起，才构成现代期权市场真正重要的分析框架。
