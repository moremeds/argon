import type { McpTool } from "../types";

// Stub — owner per spec. Replace the handler.
export const tool: McpTool = {
  name: "get_events",
  description: "TODO",
  inputSchema: {},
  handler: async () => {
    throw new Error("get_events: not implemented");
  },
};
