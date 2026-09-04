import type { BriefView, CandidateView } from "@/components/flash/view";

/**
 * The recorded option-wizard premarket run of 2026-09-03, as the Flash view
 * model sees it. Every number here comes from that run — the candidate's own
 * spot (717.29) is the one the candidate object carried, and it deliberately
 * differs from the tape's 717.47: they were read at different moments and
 * reconciling them here would be argon inventing a price.
 */
export const QQQ_SPREAD: CandidateView = {
  id: "QQQ-2026-09-03-1",
  ticker: "QQQ",
  strategy: "put_debit_spread",
  expiry: "2026-10-02",
  dte: 29,
  spot: 717.29,
  width: 45.0,
  legs: [
    {
      action: "buy",
      right: "put",
      strike: 710.0,
      expiry: "2026-10-02",
      mid: 10.45,
    },
    {
      action: "sell",
      right: "put",
      strike: 665.0,
      expiry: "2026-10-02",
      mid: 2.71,
    },
  ],
  pricing: {
    kind: "priced",
    net: 7.74,
    maxGain: 3726.0,
    maxLoss: 774.0,
    breakevens: [702.26],
    pnlAt: [],
  },
  entry: { level: 710, side: "below" },
  invalidation: [{ level: 720, side: "above" }],
  rationale:
    "Highest-duration index and the cleanest expression of the real-yield thesis (DFII10 +12bp to 2.44%), with VIX bid into tomorrow's payroll.",
};

export const PREMARKET_VIEW: BriefView = {
  schemaVersion: 1,
  date: "2026-09-03",
  tenant: "option-wizard",
  asOf: "2026-09-03T17:01:15.101Z",
  headline:
    "Real yields did the work — DFII10 ran +12bp to 2.44% while VIX broke its August 14-handle pin to 16.34 into tomorrow's payroll.",
  lead: "Real yields did the work — DFII10 ran +12bp to 2.44% while VIX broke its August 14-handle pin to 16.34 into tomorrow's payroll.",
  tape: [
    {
      label: "SPY",
      value: "772.80",
      source: "ow_spot, last price only — no daily change recorded",
    },
    {
      label: "QQQ",
      value: "717.47",
      source: "ow_spot, last price only — no daily change recorded",
    },
    {
      label: "DFII10",
      value: "2.44%",
      change: "+12bp",
      source: "DFII10 10y real yield, 2026-09-01, ~2d behind",
    },
  ],
  decision: [
    {
      label: "Call",
      value:
        "Bearish tilt across index duration into payroll; keep three defined-risk put-debit spreads and drop the redundant single name.",
    },
    {
      label: "Action",
      value:
        "Enter QQQ 710/665, SPY 765/745 and IWM 294/280 put-debit spreads on a break below each short-side entry level.",
    },
    {
      label: "Confidence",
      value:
        "Moderate — no ow_ib_positions call, so existing book exposure and buying-power fit are unverified.",
    },
  ],
  overnight: [
    "AVGO: Broadcom guided 4Q revenue to ~$34.8B vs. $35.05B estimate and fell ~6.8% after hours.",
  ],
  schedule: [
    {
      group: "Tomorrow",
      time: "08:30 ET",
      event: "Employment Report (NFP)",
      consensus: "+50k / −23k",
    },
    { time: "08:30 ET", event: "Unemployment Rate", consensus: "4.1% / 4.1%" },
  ],
  policy: {
    steps: [
      {
        date: "9/16",
        implied: "3.78",
        band: "3.75-4.00%",
        call: "HIKE",
        probability: "60%",
      },
    ],
    source:
      "Fed-funds futures via argon, snapshot 2026-09-02; not CME FedWatch.",
  },
  sections: [
    {
      title: "Rates are the first cause, and this time the levels line up",
      body: "Yesterday stood down: both bearish spreads carried 'above' invalidations spot had already touched.",
    },
  ],
  candidates: [QQQ_SPREAD],
  gamma: [
    {
      ticker: "QQQ",
      spot: "717.43",
      levels: [
        { strike: 710.0, label: "Call Wall", role: "resistance", value: 13785 },
        { strike: 710.0, label: "Put Wall", role: "support", value: 13785 },
        { strike: 665.0, label: "Gamma Flip", role: "flip", value: 0 },
      ],
    },
  ],
  riskList: [
    {
      title: "NVDA",
      body: "Dropped as a redundant, correlated expression of the same rising-real-yields megacap-duration thesis already carried by QQQ and SPY.",
    },
  ],
  coverage: {
    title: "Data coverage",
    body: "Rates       ok    partial, 10Y trend only (DGS10 4.79, 2026-09-01, ~2d behind)\nCredit HY OAS ok  2.65% via series fallback, fredDirect unavailable\nCommodities skip  skipped, no numeric close (TradingView app down)",
  },
};
