// Tool registry. Owners: A = list_endpoints, read; B = technicals_scan, ticker_snapshot,
// regime_state, market_overview; C = get_events (+ mcp/events.ts SSE hook).
import type { McpTool } from "../types";
import { tool as listEndpoints } from "./list_endpoints";
import { tool as read } from "./read";
import { tool as technicalsScan } from "./technicals_scan";
import { tool as tickerSnapshot } from "./ticker_snapshot";
import { tool as regimeState } from "./regime_state";
import { tool as marketOverview } from "./market_overview";
import { tool as getEvents } from "./get_events";

export const TOOLS: McpTool[] = [
  listEndpoints,
  read,
  technicalsScan,
  tickerSnapshot,
  regimeState,
  marketOverview,
  getEvents,
];
