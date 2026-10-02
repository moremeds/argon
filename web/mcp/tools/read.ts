import type { McpTool } from "../types";

// Stub — owner per spec. Replace the handler.
export const tool: McpTool = {
  name: "read",
  description: "TODO",
  inputSchema: {},
  handler: async () => {
    throw new Error("read: not implemented");
  },
};
