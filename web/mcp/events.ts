import type { EventStreamHook } from "./types";

// Owner: C (argon-69). LISTEN mcp_event → send() each new row for this token.
export const subscribeEvents: EventStreamHook = async () => () => {};
