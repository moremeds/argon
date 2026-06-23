"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VrpMacroLive = components["schemas"]["VrpMacroSignalLiveResponse"];

export function useVrpMacroLive(): UseSyncReturn<VrpMacroLive> {
  // GET-only (hasPost:false): every poll is a server-side live recompute; the
  // 5-min worker owns persistence (mirrors useCriLive). Weekly signal -> 30s poll.
  return useSyncHook<VrpMacroLive>(
    {
      endpoint: regimeApi.vrp_macro_signal_live(),
      interval: 30_000,
      hasPost: false,
    },
    true,
  );
}
