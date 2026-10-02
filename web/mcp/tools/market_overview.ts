import type { McpTool } from "../types";

// Stub — owner per spec. Replace the handler.
export const tool: McpTool = {
  name: "market_overview",
  description: "TODO",
  inputSchema: {},
  handler: async () => {
    throw new Error("market_overview: not implemented");
  },
};
