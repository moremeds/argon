export type OverlayMode = "sma" | "ema";
export const OVERLAY_MODE_KEY = "technicals:priceOverlayMode";
export const CHANLUN_KEY = "technicals:chanlun";
export const VOLUME_PROFILE_KEY = "technicals:volumeProfile";
export const FVG_KEY = "technicals:fvg";

// ReorderableList.tsx pattern: lazy init + try/catch; client-only component
// so no hydration mismatch.
export function loadOverlayMode(): OverlayMode {
  try {
    return localStorage.getItem(OVERLAY_MODE_KEY) === "ema" ? "ema" : "sma";
  } catch {
    return "sma";
  }
}

export function loadChanlun(): boolean {
  try {
    return localStorage.getItem(CHANLUN_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadVolumeProfile(): boolean {
  try {
    return localStorage.getItem(VOLUME_PROFILE_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadFvg(): boolean {
  try {
    return localStorage.getItem(FVG_KEY) === "1";
  } catch {
    return false;
  }
}
