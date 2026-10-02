import type { McpTool } from "../types";

// Stub — owner per spec. Replace the handler.
export const tool: McpTool = {
  name: "list_endpoints",
  description: "TODO",
  inputSchema: {},
  handler: async () => {
    throw new Error("list_endpoints: not implemented");
  },
};
