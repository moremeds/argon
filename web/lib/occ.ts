export type OccSymbol = {
  root: string;
  expiry: string; // YYYY-MM-DD
  type: "C" | "P";
  strike: number; // dollars
};

const OCC_RE = /^([A-Z.]{1,6})\s*(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/;

export function parseOccSymbol(symbol: string): OccSymbol | null {
  const m = OCC_RE.exec(symbol);
  if (!m) return null;
  const [, root, yy, mm, dd, type, strikeStr] = m;
  const year = Number(yy) < 80 ? 2000 + Number(yy) : 1900 + Number(yy);
  const month = Number(mm);
  const day = Number(dd);
  // Strict round-trip check rejects impossible dates like Feb 30 (which
  // JavaScript Date silently normalizes to early March).
  const d = new Date(Date.UTC(year, month - 1, day));
  if (
    d.getUTCFullYear() !== year ||
    d.getUTCMonth() !== month - 1 ||
    d.getUTCDate() !== day
  ) {
    return null;
  }
  return {
    root,
    expiry: `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
    type: type as "C" | "P",
    strike: Number(strikeStr) / 1000,
  };
}
