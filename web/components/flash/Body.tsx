import { parseBlocks } from "@/lib/flash/markdown";

import styles from "./flash.module.css";

/**
 * A run's prose, in the shapes the run wrote it.
 *
 * The parser only recognises what helium actually emits; anything it does not
 * recognise is printed as a paragraph, so an unfamiliar body degrades to plain
 * text rather than disappearing. Tables scroll inside their own box: a wide
 * coverage grid must never widen the page around it.
 */
export function Body({ text }: { text: string }) {
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
                        <td key={c} data-label={block.header[c] ?? ""}>
                          {cell}
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
                <li key={n}>{item}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className={styles.bodyText}>
            {block.text}
          </p>
        );
      })}
    </div>
  );
}
