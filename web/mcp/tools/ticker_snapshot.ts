import type { McpTool } from "../types";

// Stub — owner per spec. Replace the handler.
export const tool: McpTool = {
  name: "ticker_snapshot",
  description: "TODO",
  inputSchema: {},
  handler: async () => {
    throw new Error("ticker_snapshot: not implemented");
  },
};
