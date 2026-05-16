import type { components } from "@/lib/types";

export type GexData = components["schemas"]["GexResponse"];
export type GexLevel =
  | components["schemas"]["uw_scan__api__schemas__GexLevel"]
  | null;
export type GexLevels = components["schemas"]["GexLevels"];
export type GexBucket = components["schemas"]["GexBucket"];
export type GexBias = components["schemas"]["GexBias"];
export type GexHistoryEntry = components["schemas"]["GexHistoryEntry"];
export type GexExpectedRange = components["schemas"]["GexExpectedRange"];
export type MqLevels = components["schemas"]["GexMqLevels"];
export type SourceDelta = components["schemas"]["GexSourceDelta"];
export type SourceDeltaEntry = components["schemas"]["GexSourceDeltaEntry"];
export type IvData = components["schemas"]["GexIvData"];

export type RegimePendingResponse =
  components["schemas"]["RegimePendingResponse"];
