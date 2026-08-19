import type { PolicyPath, PolicyPathSlot } from "./types";

/**
 * Rules shared by every surface that renders a policy path.
 *
 * They live here rather than in the component that happened to need them first
 * because they are safety rules, not formatting: a second copy is a second place
 * for a mock source to slip through as a publisher, or for a window edge to be
 * printed as a release date.
 */

//: A source kind that is not a real publisher can never be presented as one. It is
//: representable in the contract, so the rejection is enforced at every render site
//: rather than assumed away upstream.
export const NON_PRODUCTION_SOURCE_KINDS = new Set(["mock", "static", "demo"]);

export function isWithheld(path: PolicyPath): boolean {
  return NON_PRODUCTION_SOURCE_KINDS.has(path.source_kind);
}

export function releaseDate(path: PolicyPath): string {
  const stamp = path.published_at ?? path.available_at;
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return stamp;
  return date.toISOString().slice(0, 10);
}

export type PlottablePath =
  | { status: "ok"; path: PolicyPath }
  | { status: "empty"; reason: string };

/**
 * Resolve a slot to something a chart may draw, or to the sentence explaining why not.
 *
 * A chart has no way to render "this release was unreadable" -- an empty axis reads as
 * a flat path, which is a claim. So the caller gets a reason string instead of an empty
 * dataset and must print it.
 */
export function plottable(slot: PolicyPathSlot | null | undefined): PlottablePath {
  if (!slot?.path) {
    return {
      status: "empty",
      reason: slot?.missing_reason ?? "This path has not been ingested.",
    };
  }
  if (isWithheld(slot.path)) {
    return {
      status: "empty",
      reason: `Withheld: this lane is carrying ${slot.path.source_kind} evidence, which is not a publisher.`,
    };
  }
  if (!(slot.path.points ?? []).length) {
    return {
      status: "empty",
      reason: "The release carried no readable path point.",
    };
  }
  return { status: "ok", path: slot.path };
}
