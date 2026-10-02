import type { McpTool } from "../types";

// Stub — owner per spec. Replace the handler.
export const tool: McpTool = {
  name: "technicals_scan",
  description: "TODO",
  inputSchema: {},
  handler: async () => {
    throw new Error("technicals_scan: not implemented");
  },
};
