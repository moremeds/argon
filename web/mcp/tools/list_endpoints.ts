import { endpointsCache } from "../lib/endpoints";
import type { McpTool } from "../types";

export const tool: McpTool = {
  name: "list_endpoints",
  description:
    "List the allowlisted GET endpoints of the Argon API as " +
    "[{path, summary, params}]. Pass a listed path to the read tool; " +
    "{placeholder} segments are filled from read's params argument.",
  inputSchema: {},
  handler: async () => endpointsCache.get(),
};
