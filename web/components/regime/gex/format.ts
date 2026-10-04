export { fmtGexUsd as fmtGex } from "@/lib/formatters";

export function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "---";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function biasColor(direction: string): string {
  switch (direction) {
    case "BULL":
      return "var(--signal-core)";
    case "CAUTIOUS_BULL":
      return "var(--signal-core)";
    case "BEAR":
      return "var(--fault)";
    case "CAUTIOUS_BEAR":
      return "var(--fault)";
    default:
      return "var(--neutral)";
  }
}

export function biasLabel(direction: string): string {
  return direction.replace("_", " ");
}
