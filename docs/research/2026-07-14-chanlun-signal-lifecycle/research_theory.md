# Faster Chanlun signal confirmation — pending→confirmed lifecycle research

Date: 2026-07-14
For: argon `web/lib/chanlun.ts` (branch `feat/chanlun-v2`) — the daily-bar overlay
Problem: current semantics flip `confirmed=true` only when the NEXT opposite endpoint
is appended, so 买卖点/背离 marks land ~4–8 daily bars after the bar they decorate. The
user wants (a) a pending mark at bar close (~1 bar after the extreme), (b) a
confirm/invalidate lifecycle, (c) confirmation narrowed toward ~1 bar.

Claim tags: [verified from source] = read from the cited page/source; [recall — unverified]
= from my training, not re-verified here. Confidence: HIGH/MED/LOW.

---

## 1. czsc (github.com/waditu/czsc) — how it models real-time 分型/笔 state

czsc's `CZSC` analysis object is the reference for exactly the state machine argon lacks.
It explicitly separates *finished* from *unfinished* structure rather than back-dating a
`confirmed` flag. Verbatim attribute definitions (fetched from the API docs):
[verified from source] https://czsc.readthedocs.io/en/stable/api/czsc.analyze.CZSC.html — HIGH

- `ubi` — "Unfinished Bi，未完成的笔" — the still-forming stroke off the last confirmed
  endpoint. A first-class object, not a nullable tail.
- `bars_ubi` — the raw bars belonging to the unfinished stroke (the bars accumulated since
  the last confirmed 笔 end).
- `ubi_fxs` — "bars_ubi 中的分型" — fractals detected *inside* the unfinished region (i.e.
  candidate next-endpoints that have not yet earned a stroke).
- `fx_list` — "分型列表，包括 bars_ubi 中的分型" — ALL fractals, confirmed-region + unfinished.
- `finished_bis` — "已完成的笔" — the confirmed strokes only.
- `last_bi_extend` — "判断最后一笔是否在延伸中，True 表示延伸中" — boolean, is the last stroke
  still extending its extreme.

Design implication of the shape: czsc keeps a **live `ubi` you can render every bar** and a
separate `finished_bis` list. It never needs to "wait for the opposite endpoint to set a
flag" to *show* the forming stroke — the forming stroke is always visible as `ubi`; only its
*promotion* into `finished_bis` waits.

### 1a. What promotes `ubi` → finished 笔 (`check_bi` / `check_fx`)

From the pure-Python `analyze.py` source (older 0.9.x line, before the Rust port):
[verified from source] https://czsc.readthedocs.io/en/0.9.4/_modules/czsc/analyze.html — HIGH

- `check_fx` — top fractal `Mark.G`: `k1.high < k2.high > k3.high and k1.low < k2.low > k3.low`;
  bottom `Mark.D`: mirror. So a **fractal is "complete" the instant the 3rd merged candle
  closes** — this is the ~1-bar-after-extreme trigger the user is asking for. czsc treats
  that completed fractal as a candidate, held in `ubi_fxs`, before it is a 笔 endpoint.
- `check_bi` gates the candidate 笔 on:
  1. **Minimum length:** `len(bars_a) >= min_bi_len`, where `min_bi_len = envs.get_min_bi_len()`
     (env-var configurable, not hardcoded). [recall — unverified] default is **6 bars** for
     the "new 笔" rule (argon's `MIN_VERTEX_GAP=4` merged-candles is the analogous knob). MED.
  2. **Non-containment of the two fractals:**
     `(fx_a.high > fx_b.high and fx_a.low < fx_b.low) or (fx_a.high < fx_b.high and fx_a.low > fx_b.low)`.
  3. **Power/threshold early-out (the important one for "faster"):** if a benchmark exists and
     `abs(fx_a.fx - fx_b.fx) > benchmark * envs.get_bi_change_th()`, **the stroke is confirmed
     despite being shorter than `min_bi_len`.** [verified from source, same page] — HIGH.
     `bi_change_th` numeric default: [recall — unverified] ~0.5. LOW. Mechanism is verified;
     the constant is not.

Takeaway: czsc already has a **two-speed confirmation** — normal (length + alternation) OR
fast (a large enough price swing confirms a short 笔 immediately). That is a documented,
production rule for confirming an endpoint in fewer bars with a magnitude filter guarding
against noise.

### 1b. Freshness convention

czsc's quant layer (220+ signal functions) reads state off this object every bar; the
"未完成笔" is explicitly consumable. Signals that must not repaint key off `finished_bis` /
confirmed structure; signals that want immediacy read `ubi` / `ubi_fxs` and accept that they
can change. [verified from source — the attribute split itself encodes this] — MED. The library
does not hide the forming stroke; it labels it.

---

## 2. chanlun-pro (github.com/yijixiuxin/chanlun-pro) and Pine/TV scripts

### 2a. chanlun-pro repaint model
[verified from source] repo README / cookbook docs via search of
github.com/yijixiuxin/chanlun-pro — MED (read via search summary, not full file):

- Compute is **bar-by-bar**: on each new bar it re-merges Chan K-lines, then recomputes
  分型→笔→线段→中枢→走势段→背驰→买卖点, updating as bars arrive.
- Stated stability contract: *"Once fractals, strokes, segments, pivot zones, and trend
  segments are formed and confirmed, they generally won't change unless special circumstances
  occur."* — i.e. confirmed structure is sticky; only the tail moves.
- Explicit **redraw mechanism**: *"the program can provide current divergence or buy/sell
  point information, but subsequent market movements may confirm these signals or continue,
  potentially causing the divergence or buy/sell points to disappear."* This is precisely a
  **pending→(confirm | invalidate/disappear)** lifecycle, shipped in a mature library — it
  paints the provisional signal now and lets it vanish if price invalidates it.

### 2b. 缠论++ (chanlunpp.org, @crblandet) — already in argon's own doc
[verified from source] argon `docs/research/2026-07-14-chanlun-tv-view-research.md` §2 — HIGH:
built on 笔 (not 线段) specifically to get **real-time provisional signals that erase if
invalidated, marked with a "?" suffix**; paid tier adds 背驰系数 + alerts. The author
explicitly traded textbook fidelity for real-time responsiveness. This is the single closest
precedent to what the user wants and it validates the "paint pending with ?, erase on
invalidation" pattern.

### 2c. TradingView Pine chanlun scripts
[verified from source] TradingView script search results (ChanLun Pro by AlphaViz; "Chanlun
HD Pro - Fractals, Strokes, Segments and Pivots" by TA_handbook) —
https://www.tradingview.com/script/4V66pXJ9-ChanLun-Pro/ and
https://www.tradingview.com/script/LanFVK0l/ — MED. These render fractals/strokes/pivots but
the public pages don't document their real-time signal-timing internals. AlphaViz's product
line (noted in argon's doc §2) is explicitly the *strict/laggy* camp: "signals confirm only
after the move completes." So the TV ecosystem spans both poles — strict-late (AlphaViz) and
provisional-erasing (缠论++). No production-grade TypeScript chanlun lib was found (confirms
argon's prior finding).

---

## 3. Chanlun theory/practice for FASTER endpoint confirmation on daily bars

### 3a. 分型 completion as the pending trigger + strength filters (分型强度)

The basic 分型 completes at the 3rd candle (top: middle candle has the highest high; the 3rd
candle has a lower high). That is ~1 bar after the extreme — the natural "pending" moment.
Practitioners do NOT treat all completed fractals as equal; they grade **分型强度** to filter
weak/中继 (continuation) fractals from strong/转折 (reversal) ones. Verbatim rules from the
practitioner literature:
[verified from source] Sina/新浪财经 缠论 分型 article (via search snippet)
https://cj.sina.com.cn/articles/view/6867255644/19952015c00100htgo and龙哥量化
https://www.cnblogs.com/long136/p/17991062 — MED:

- **Strong top fractal:** the 3rd candle opens in the lower-middle of the 2nd (peak) candle
  and is a medium/large **阴线 (down candle) that pierces the lower edge of the top fractal**;
  strongest form = the 3rd candle **breaks below the 1st candle's low AND closes below the
  midpoint of the 1st candle's range**. (Mirror for strong bottom fractals.)
- **Weak top fractal:** the 3rd candle's low stays **above the lower edge of the fractal** (no
  real break) → likely 中继 (continuation), not a turn.
- **收盘价 (close) role:** strength keys on *where the 3rd candle closes* relative to the 1st
  candle's body/midpoint, not just its high/low. A close that fails to reclaim the midpoint =
  strong reversal; a close back inside = weak/suspect.
- **缺口 (gap):** a gap on the confirming candle raises strength (aggressive rejection).

These are exactly the filters to layer on a "pending at fractal completion" mark so you paint
fewer, higher-quality pending signals rather than one at every raw fractal.

### 3b. 区间套 / 小级别转大级别 — confirm a daily point same-day or next-day
[verified from source] cnfol / zhihu 区间套 explainers
http://mp.cnfol.com/51950/article/1617262509-139753732.html ,
https://zhuanlan.zhihu.com/p/362786036 — MED:

- Definition: 区间套 = locate a high-level turning point by recursively finding the 背驰 point
  down through adjacent sub-levels (周线→日线→30F→5F→1F), the ranges telescoping onto the exact
  reversal bar. Self-similarity of 走势 makes the sub-level 背驰 confirm the higher-level one.
- **Concrete practitioner rule:** to precisely time a **日线 (daily)** buy/sell point, drop to
  the **30-minute (次级别)** structure and require a sub-level 1/2/3-class point there. A daily
  第一类买点 is confirmed *within the same or next session* once the 30m shows its own 背驰/
  第二类买点 — you do not wait for the daily 笔 to fully complete. Practitioner guidance:
  "只需定位日线一买、30分钟一买位置" (locate the daily-1B AND the 30m-1B), experts go to 5m.
- czsc mechanization: czsc's `bars_ubi` + multi-timeframe bar synthesis (it composes higher
  TFs from a base TF) is exactly the substrate for this — the sub-level `finished_bis` can
  confirm the higher-level `ubi` before the higher-level 笔 finishes. [recall — unverified as
  a single named czsc API] MED.

**Constraint for argon:** the overlay currently has **daily bars only** (no intraday store,
per `docs/research/...` §4 "Timeframe"). True 区间套 confirmation needs a 30m/60m feed argon
doesn't have on this page. The **weekly×daily 区间套 resonance** already shipped
(`markResonance`) is the *coarser* direction (higher-level confirms via weekly); the *finer*
sub-daily direction that would give same-day confirmation is blocked until an intraday bar
source exists. Flag this as the main feasibility gap for goal (c).

### 3c. Is there a rule that confirms a 笔 endpoint in ~1 bar with acceptable error?

- czsc's `bi_change_th` power early-out (§1a) is the closest documented "confirm faster than
  min length" rule — it confirms a short 笔 on a big enough swing. [verified from source] HIGH.
- 分型强度 (§3a) is the standard qualitative filter that lets practitioners *act* on a strong
  分型 at completion (~1 bar) rather than waiting for the full 笔. [verified from source] MED.
- There is **no free lunch**: the non-repaint literature is explicit that "methods that prevent
  repainting will also trigger signals later than repainting scripts, which is an inevitable
  compromise." [verified from source] crosstrade.io / GrandAlgo — HIGH. So ~1-bar confirmation
  is only achievable as a *pending* (repaint-allowed) mark; a truly *confirmed* mark on daily
  bars either accepts some invalidation rate or takes the extra bars. The honest design is a
  labeled two-state signal, not a magically-early "confirmed."

---

## 4. UX conventions for repainting / pending-vs-confirmed signals

[verified from source] TradingView Pine docs + chartrades barstate guide + crosstrade/PickMyTrade
https://www.tradingview.com/pine-script-docs/concepts/repainting/ ,
https://chartrades.com/guides/pine-script-barstate-confirmed-realtime/ ,
https://crosstrade.io/blog/pine-script-repainting — HIGH:

- **Bar-close semantics are the canonical dividing line.** An *unconfirmed* signal is
  intra-bar and "can appear and disappear with the current price fluctuations"; a *confirmed*
  signal "is only generated when a candle closes … cannot trigger and disappear." The whole
  ecosystem draws the line at bar close, not at some later structural event.
- `barstate.isconfirmed` + `alert.freq_once_per_bar_close` ("Once Per Bar Close") is the
  standard idiom: **compute/display live, but only fire alerts on bar close.** Directly maps
  to argon's "alert bar < trade bar; never alert off the provisional tail" invariant.
- TradingView flags repainting scripts with a **yellow "!" next to the alert dialog** — the
  platform's own convention for "this signal is provisional." A "?" suffix (缠论++'s choice)
  is the community analog on the marker itself.
- **Invalidated-signal handling:** the accepted behavior for a repainting indicator is that
  the provisional marker simply **disappears** when price invalidates it (chanlun-pro §2a:
  "买卖点… disappear"; TV replay test: "signals that appear on bar N then shift/vanish").
  There isn't a strong *standard* for a graceful fade — most just remove the mark. A fade-out
  is a reasonable UX nicety but is your invention, not a documented convention. [verified: the
  disappear behavior; the fade is not a named convention] MED.
- Visual encoding already catalogued in argon's doc: provisional = dashed line / faint border
  / "?" suffix; confirmed = solid / labeled. [verified from source] argon doc §2. HIGH.

---

## 5. Design implications for us (pending→confirmed/invalidated, ~1-bar pending latency)

Each recommendation cites the source that supports it.

1. **Adopt czsc's structural split, not a back-dated boolean.** Replace the single
   `confirmed: boolean` (which only flips when the opposite endpoint arrives) with an explicit
   **three-state lifecycle**: `pending` (fractal just completed, ~1 bar after extreme) →
   `confirmed` (earned a 笔 / opposite endpoint) → `invalidated` (superseded before earning).
   Mirror czsc's `finished_bis` vs `ubi`/`ubi_fxs` separation so the forming stroke is a
   first-class rendered object, not a "provisional tail" special case. [§1, verified] — HIGH.

2. **Paint the pending mark at 分型 completion (the 3rd merged candle's close).** That is the
   ~1-bar trigger the user wants and it is exactly czsc's `check_fx` completion point. Emit a
   pending 买卖点/背离 candidate there instead of waiting for the next opposite endpoint. [§1a,
   §3a — verified] — HIGH.

3. **Gate pending marks with a 分型强度 filter to cut false positives.** Require the confirming
   (3rd) candle to *close* beyond the middle candle's opposite extreme (e.g. top: 3rd candle
   closes below the 1st candle's midpoint / breaks its low); optionally boost on a gap. This is
   the standard practitioner method for separating 转折 (reversal) from 中继 (weak) fractals and
   directly reduces the invalidation rate of pending marks. [§3a — verified, MED] — MED.

4. **Add a magnitude early-confirm, mirroring czsc `bi_change_th`.** Promote a short 笔 to
   `confirmed` before the full `MIN_VERTEX_GAP` when the endpoint-to-endpoint price swing
   exceeds a benchmark fraction (czsc: `abs(fx_a.fx - fx_b.fx) > benchmark * bi_change_th`).
   This is the one documented rule that legitimately shortens confirmation latency with a
   noise guard. Pick the benchmark from recent ATR/中枢 height; the exact ratio is a tunable.
   [§1a — mechanism verified HIGH; constant unverified LOW] — HIGH on mechanism.

5. **Keep the alert boundary at bar close, never on the intra-bar forming tail.** Use
   `barstate.isconfirmed`-equivalent semantics: pending marks may render live and repaint, but
   the alert pipeline fires only once per closed bar and preferably only on `confirmed`
   (or `pending` that has survived one full bar). This satisfies argon's "alert bar < trade
   bar / never alert off the provisional tail" invariant. [§4 — verified] — HIGH.

6. **UX: encode the three states, and be honest that ~1-bar "confirmation" is really
   "pending."** Convention: pending = hollow/low-opacity marker with "?" suffix (缠论++ /
   TV "!" precedent); confirmed = solid, labeled 1B..3S; invalidated = remove the mark (a
   short fade-out is an acceptable but non-standard nicety — do not over-invest). Do not label
   a repaint-prone early mark as `confirmed`; the literature is explicit that earlier = repaint,
   so the honest artifact is a visibly-provisional pending state, not a faux-early confirm.
   [§2b, §4 — verified] — HIGH.

7. **(Feasibility flag, not a recommendation to build now)** True same-day 区间套 confirmation
   (30m/60m sub-level confirming the daily point) is blocked: this page has **daily bars only**
   and no intraday store. The shipped weekly×daily `markResonance` is the coarser higher-level
   direction; the finer sub-daily direction needs an intraday feed. Treat §3b as future work,
   not part of the ~1-bar pending change. [§3b + argon doc §4 — verified] — HIGH.

---

## Sources
- czsc CZSC class attributes (ubi / ubi_fxs / fx_list / finished_bis / last_bi_extend):
  https://czsc.readthedocs.io/en/stable/api/czsc.analyze.CZSC.html
- czsc analyze.py source (check_fx / check_bi / min_bi_len / bi_change_th):
  https://czsc.readthedocs.io/en/0.9.4/_modules/czsc/analyze.html
- czsc repo: https://github.com/waditu/czsc
- chanlun-pro: https://github.com/yijixiuxin/chanlun-pro (README + cookbook/docs)
- 缠论++ launch context: argon docs/research/2026-07-14-chanlun-tv-view-research.md §2
- 分型强度 (strong/weak fractals): https://cj.sina.com.cn/articles/view/6867255644/19952015c00100htgo ,
  https://www.cnblogs.com/long136/p/17991062 , https://www.crazychanlun.com/post/2/ (timed out, cited via search)
- 区间套: http://mp.cnfol.com/51950/article/1617262509-139753732.html ,
  https://zhuanlan.zhihu.com/p/362786036
- TradingView repainting / barstate.isconfirmed: https://www.tradingview.com/pine-script-docs/concepts/repainting/ ,
  https://chartrades.com/guides/pine-script-barstate-confirmed-realtime/ ,
  https://crosstrade.io/blog/pine-script-repainting , https://grandalgo.com/blog/non-repaint-tradingview-indicators
- TV chanlun scripts: https://www.tradingview.com/script/4V66pXJ9-ChanLun-Pro/ ,
  https://www.tradingview.com/script/LanFVK0l/

[RULES I BROKE]: None. Numeric defaults I could not re-verify (czsc `min_bi_len`≈6,
`bi_change_th`≈0.5) are explicitly tagged [recall — unverified]/LOW; every mechanism claim is
tagged with the source it was read from. The crazychanlun.com fetch timed out, so 分型强度 is
cited from the Sina/龙哥量化 sources whose search snippets contained the verbatim rules.
