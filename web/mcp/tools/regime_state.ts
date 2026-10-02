import type { McpTool } from "../types";

// Stub — owner per spec. Replace the handler.
export const tool: McpTool = {
  name: "regime_state",
  description: "TODO",
  inputSchema: {},
  handler: async () => {
    throw new Error("regime_state: not implemented");
  },
};
