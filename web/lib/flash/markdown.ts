/**
 * The markdown-ish shapes helium actually writes, and nothing more.
 *
 * A run's body is prose the tenant composed: mostly paragraphs, sometimes a
 * pipe table (the coverage layer/source/as-of grid), occasionally a dash list.
 * This parser recognises exactly those three and falls back to a paragraph for
 * everything else — a body it cannot read is still printed in full, never
 * dropped and never reshaped into a tidier claim than the run made.
 */
export type Block =
  | { type: "p"; text: string }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "ul"; items: string[] };

/** A `|---|:--:|` rule row: structure, not data. */
function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((c) => /^:?-{1,}:?$/.test(c));
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((c) => c.trim());
}

export function parseBlocks(text: string): Block[] {
  if (!text) return [];
  const chunks = text.replace(/\r\n/g, "\n").split(/\n[ \t]*\n+/);
  const blocks: Block[] = [];

  for (const chunk of chunks) {
    const lines = chunk
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0) continue;

    if (lines.every((l) => l.startsWith("|"))) {
      const rows = lines
        .map(splitRow)
        .filter((cells) => !isSeparatorRow(cells));
      if (rows.length > 0) {
        const [header, ...body] = rows;
        blocks.push({ type: "table", header, rows: body });
        continue;
      }
    }

    if (lines.every((l) => l.startsWith("- "))) {
      blocks.push({ type: "ul", items: lines.map((l) => l.slice(2).trim()) });
      continue;
    }

    blocks.push({ type: "p", text: lines.join(" ") });
  }

  return blocks;
}
