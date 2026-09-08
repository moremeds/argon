import type { ReactNode } from "react";

import { parseBlocks } from "@/lib/flash/markdown";
import { TICKER_TOKEN, tickerSet } from "@/lib/flash/tickers";

import styles from "./flash.module.css";

/**
 * A cell that is a bare value, not a sentence.
 *
 * A number, a percentage, a date, an ISO timestamp, a ✓ or an em dash is read
 * by comparing it down a column, which is what tabular monospace is for. The
 * test is the WHOLE cell: "2.66%" is a value, "HY OAS at 2.66%" is prose.
 */
const ATOMIC_CELL =
  /^(?:[+\-−±]?\d[\d,]*(?:\.\d+)?\s*%?|\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?|✓|—)$/;

/** The list used when a caller hands Body no page-specific names. */
const STATIC_ONLY = tickerSet();

/**
 * A coverage verdict, as v3's review sections write it: one bare uppercase
 * word per layer. Closed set on purpose — anything else stays plain text, so
 * a verdict helium renames prints as written instead of vanishing into a chip
 * argon guessed at.
 */
const COVERAGE_TOKENS: Record<string, "up" | "down" | "hold"> = {
  CONTINUE: "up",
  STRENGTHEN: "up",
  FADE: "down",
  REVERSE: "down",
  UNTESTED: "hold",
};

/** A ticker OR a coverage verdict. Longest alternative first, or `\b[A-Z]{1,5}\b` eats CONTI. */
const PROSE_TOKEN = new RegExp(
  `\\b(?:${Object.keys(COVERAGE_TOKENS).join("|")})\\b|${TICKER_TOKEN.source}`,
  "g",
);

/**
 * A ticker or a coverage verdict inside a sentence, set apart from it.
 *
 * The prose is the run's and is never rewritten — only wrapped. For a ticker,
 * membership in the page's ticker set decides; the token pattern alone would
 * make a symbol out of every "ET", "OAS" or "RTH" helium writes. For a
 * verdict, the closed list above decides. Nothing else in the string moves, so
 * a paragraph reads the same whether or not a token was recognised.
 */
function highlight(text: string, tickers: ReadonlySet<string>): ReactNode {
  PROSE_TOKEN.lastIndex = 0;
  const out: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = PROSE_TOKEN.exec(text)) !== null) {
    const token = match[0];
    const cov = COVERAGE_TOKENS[token];
    if (!cov && !tickers.has(token)) continue;
    if (match.index > cursor) out.push(text.slice(cursor, match.index));
    out.push(
      cov ? (
        <span
          key={`${match.index}-${token}`}
          className={styles.cov}
          data-cov={cov}
        >
          {token}
        </span>
      ) : (
        <span key={`${match.index}-${token}`} className={styles.tick}>
          {token}
        </span>
      ),
    );
    cursor = match.index + token.length;
  }
  if (out.length === 0) return text;
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

/**
 * A run's prose, in the shapes the run wrote it.
 *
 * The parser only recognises what helium actually emits; anything it does not
 * recognise is printed as a paragraph, so an unfamiliar body degrades to plain
 * text rather than disappearing. Tables scroll inside their own box: a wide
 * coverage grid must never widen the page around it.
 *
 * `tickers` is the page's own set of names (see `viewTickers`). Without one
 * the body still highlights the desk's standing universe, so a Body rendered
 * from a context that has no view is quieter, never wrong.
 */
export function Body({
  text,
  tickers = STATIC_ONLY,
}: {
  text: string;
  tickers?: ReadonlySet<string>;
}) {
  const blocks = parseBlocks(text);
  if (blocks.length === 0) return null;

  return (
    <div className={styles.body}>
      {blocks.map((block, i) => {
        if (block.type === "table") {
          return (
            <div key={i} className={`${styles.scrollx} ${styles.bodyTable}`}>
              <table>
                <thead>
                  <tr>
                    {block.header.map((cell, c) => (
                      <th key={c} className={styles.lbl}>
                        {cell}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c) => (
                        <td
                          key={c}
                          data-label={block.header[c] ?? ""}
                          className={
                            ATOMIC_CELL.test(cell.trim())
                              ? styles.num
                              : undefined
                          }
                        >
                          {highlight(cell, tickers)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === "ul") {
          return (
            <ul key={i} className={styles.bodyList}>
              {block.items.map((item, n) => (
                <li key={n}>{highlight(item, tickers)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className={styles.bodyText}>
            {highlight(block.text, tickers)}
          </p>
        );
      })}
    </div>
  );
}
