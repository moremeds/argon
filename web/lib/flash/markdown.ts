/**
 * The markdown-ish shapes helium actually writes, and nothing more.
 *
 * A run's body is prose the tenant composed: mostly paragraphs, sometimes a
 * pipe table (the coverage layer/source/as-of grid), occasionally a dash list,
 * and sometimes a run of settlement records helium wrote as one block. This
 * parser recognises exactly those four and falls back to a paragraph for
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

/**
 * A settlement record id: `QQQ-2026-09-03-1`.
 *
 * helium writes one record per line and argon's paragraph rule joins single
 * newlines with a space, so three settlements arrive as one wall of prose in
 * which every record's ticker, verdict and price run into the next one's. The
 * id is the only reliable seam — it is the record's own key, not punctuation
 * argon guessed at.
 */
const RECORD_ID = /\b[A-Z]{1,6}-\d{4}-\d{2}-\d{2}-\d+\b/g;

/**
 * One paragraph carrying two or more record ids, cut back into its records.
 *
 * Two is the threshold because a single id is a sentence mentioning a record,
 * not a list of them. The id itself is dropped from the item — it is a key for
 * helium, and the ticker and state right after it are what a reader needs —
 * but anything BEFORE the first id survives as its own paragraph rather than
 * being swallowed by the list.
 */
function splitRecords(text: string): Block[] | null {
  const ids = [...text.matchAll(RECORD_ID)];
  if (ids.length < 2) return null;

  const items: string[] = [];
  for (let i = 0; i < ids.length; i += 1) {
    const start = (ids[i].index ?? 0) + ids[i][0].length;
    const end =
      i + 1 < ids.length ? (ids[i + 1].index ?? text.length) : text.length;
    const item = text.slice(start, end).trim();
    if (item.length > 0) items.push(item);
  }
  if (items.length === 0) return null;

  const blocks: Block[] = [];
  const preamble = text.slice(0, ids[0].index ?? 0).trim();
  if (preamble.length > 0) blocks.push({ type: "p", text: preamble });
  blocks.push({ type: "ul", items });
  return blocks;
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

    // Schema-3 bodies are block-level markdown joined by SINGLE newlines: a bare
    // heading line followed by "- " bullets, or several bare lines that are each
    // their own statement. Group consecutive lines by kind — a bullet run is one
    // list, a table run is one table, and every bare line is its own paragraph.
    // v2 bodies never soft-wrap prose (checked against the frozen v2 fixture), so
    // this only changes what used to collapse into one "wall of text".
    const kindOf = (l: string) =>
      l.startsWith("- ") ? "ul" : l.startsWith("|") ? "table" : "p";
    let i = 0;
    while (i < lines.length) {
      const kind = kindOf(lines[i]);
      let j = i;
      while (j < lines.length && kindOf(lines[j]) === kind) j++;
      const run = lines.slice(i, j);
      i = j;
      if (kind === "ul") {
        blocks.push({ type: "ul", items: run.map((l) => l.slice(2).trim()) });
      } else if (kind === "table") {
        const rows = run.map(splitRow).filter((cells) => !isSeparatorRow(cells));
        if (rows.length > 0) {
          const [header, ...body] = rows;
          blocks.push({ type: "table", header, rows: body });
        }
      } else {
        // Run-together settlement records (a real v2 shape) span lines, so the
        // record seam is looked for on the joined run first; otherwise each
        // bare line is its own statement.
        const records = splitRecords(run.join(" "));
        if (records) blocks.push(...records);
        else for (const text of run) blocks.push({ type: "p", text });
      }
    }
  }

  return blocks;
}
