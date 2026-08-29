import type { ReactElement } from "react";

import type { MacroReplayClock, MacroReplayRequest } from "./replay";

export type MacroTabEntry = {
  slug: string;
  ordinal: string;
  label: string;
  /** The question `as_of` asks on this tab: desk instant, market date, or none. */
  replayClock: MacroReplayClock;
};

/** The artifact's complete tab registry, already in its visual order. */
export const VALID_TABS = [
  {
    slug: "overview",
    ordinal: "00",
    label: "Overview · Daily Loop",
    replayClock: "instant",
  },
  { slug: "fed", ordinal: "01", label: "Fed · Policy", replayClock: "instant" },
  {
    slug: "rates",
    ordinal: "02",
    label: "Rates · Curve",
    replayClock: "instant",
  },
  {
    slug: "inflation",
    ordinal: "03",
    label: "Inflation",
    replayClock: "instant",
  },
  { slug: "usd", ordinal: "04", label: "US Dollar", replayClock: "instant" },
  { slug: "gold", ordinal: "05", label: "Gold", replayClock: "obs_date" },
  {
    slug: "energy",
    ordinal: "06",
    label: "Energy · Proposal",
    replayClock: "none",
  },
  {
    slug: "factors",
    ordinal: "07",
    label: "Factor Export",
    replayClock: "instant",
  },
  {
    slug: "notes",
    ordinal: "08",
    label: "Design Notes",
    replayClock: "none",
  },
] as const satisfies readonly MacroTabEntry[];

export type MacroTabSlug = (typeof VALID_TABS)[number]["slug"];
export type MacroTabProps = { replay: MacroReplayRequest };
export type MacroTabContent = (
  props: MacroTabProps,
) => ReactElement | Promise<ReactElement>;

export function macroTabHref(slug: string): string {
  return `/macro/${slug}`;
}

export function macroTabsInBoardOrder(): readonly MacroTabEntry[] {
  return VALID_TABS;
}

export function macroTabsForBar(): readonly MacroTabEntry[] {
  return VALID_TABS;
}
