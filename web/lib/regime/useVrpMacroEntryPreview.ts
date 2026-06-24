"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VrpMacroEntryPreview =
  components["schemas"]["VrpMacroEntryPreview"];
export type VrpMacroEntryLeg = components["schemas"]["VrpMacroEntryLeg"];

export function useVrpMacroEntryPreview(): UseSyncReturn<VrpMacroEntryPreview> {
  // GET-only: the preview reads today's already-persisted cohort snapshot (or
  // BS-indicative pre-birth) — ZERO IB, ZERO new UW, ZERO writes. The 8x/day
  // worker owns the durable record. Weekly signal -> 30s poll (mirrors useVrpMacroLive).
  return useSyncHook<VrpMacroEntryPreview>(
    {
      endpoint: regimeApi.vrp_macro_entry_preview(),
      interval: 30_000,
      hasPost: false,
    },
    true,
  );
}
