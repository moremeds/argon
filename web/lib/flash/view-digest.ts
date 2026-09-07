import { createHash } from "node:crypto";

// Server-side provenance: JSONB may reorder object keys, but never array rows.
function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (value !== null && typeof value === "object")
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => [key, ordered(entry)]));
  return value;
}

export function viewDigest(view: unknown): string {
  return createHash("sha256").update(JSON.stringify(ordered(view))).digest("hex");
}
