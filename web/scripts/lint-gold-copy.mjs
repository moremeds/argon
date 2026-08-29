#!/usr/bin/env node
// Posture-language CI lint for the GOLD COMPASS UI and the macro desk. Per spec §8.4,
// build fails if any file under web/components/{gold,macro}/** or
// web/app/{gold,macro}/** contains a banned posture-language substring outside an
// opt-out comment.

import { promises as fs } from "node:fs";
import path from "node:path";

export const BANNED = [
  // sizing imperatives
  "buy",
  "sell",
  "long",
  "short",
  // sizing nouns
  "position size",
  "recommended size",
  "allocate %",
  "position heat",
  // execution verbs
  "trade",
  "execute",
  "enter",
  "exit",
  "take profit",
  "stop loss",
  // model claims
  "predicted return",
  "today's signal",
  "signal: long",
  "signal: short",
  "SHAP",
  "XGBoost",
  "8因子",
  // backtest claims
  "equity curve",
  "Sharpe",
  "Calmar",
  "win rate",
  "max drawdown",
  "current drawdown",
  // bilingual sizing
  "做多",
  "做空",
  "仓位",
  "今日信号",
  "预测收益",
  "净值曲线",
  "回测账户",
];

// Compound phrases where banned words are legitimate.
const ALLOWED_COMPOUNDS = [
  "long-horizon",
  "short-term",
  "long-term",
  "long-form",
  "tail-risk",
  "execute query",
  "execute the migration",
];

// Match the disable directive in either a // line comment or a {/* JSX */} comment.
const DISABLE_RE = /posture-lint-disable-next-line/i;

function isAllowedHit(line, idx, word) {
  for (const compound of ALLOWED_COMPOUNDS) {
    if (compound.toLowerCase().includes(word.toLowerCase())) {
      const window = line
        .slice(Math.max(0, idx - 20), idx + word.length + 20)
        .toLowerCase();
      if (window.includes(compound)) return true;
    }
  }
  return false;
}

export function lintFileContents(filename, source) {
  const lines = source.split("\n");
  const violations = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (i > 0 && DISABLE_RE.test(lines[i - 1])) continue;
    // Skip the disable directive line itself.
    if (DISABLE_RE.test(lines[i])) continue;
    const line = lines[i];
    for (const word of BANNED) {
      const isAscii = /^[\x00-\x7F]+$/.test(word);
      const re = isAscii
        ? new RegExp(
            `\\b${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`,
            "i",
          )
        : new RegExp(word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      const m = line.match(re);
      if (m && typeof m.index === "number") {
        if (isAllowedHit(line, m.index, word)) continue;
        violations.push({
          file: filename,
          line: i + 1,
          word,
          text: line.trim(),
        });
      }
    }
  }
  return violations;
}

async function* walk(dir) {
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (full.endsWith(".tsx") || full.endsWith(".ts")) yield full;
  }
}

/**
 * The directories this lint speaks for, relative to `web/`.
 *
 * The macro desk is one posture surface, not a gold one: the gold tab lands under
 * `/macro`, and the same banned vocabulary has to stay off every tab beside it. P2 added
 * the two macro roots additively; P6 keeps all four, because §10-B of the port plan
 * settled that the subtrees do NOT move — only the page shells do, and `app/gold` still
 * holds `loading.tsx` and `replay/[date]/` after `app/gold/page.tsx` is retired into
 * `/macro/gold`.
 *
 * Deliberately NOT here: `components/rates`. `RatesScorecard` prints `BUY` / `SELL`
 * verbatim from `RatesDurationStance` (`models/rates.py:18`), and the operator settled
 * on 2026-08-28 (plan §10-I) that it may — it is the legacy rule score, quarantined
 * inside tab 02's "what this tab refuses" panel, reporting its own output. Adding
 * `components/rates` here would fail the build over a rendering that is explicitly
 * authorised. The linter and that ruling are complementary: this enforces the condition
 * the ruling attached — the word never appears where the model did not produce it —
 * everywhere OUTSIDE the one quarantine, and `macro-rates-state.spec.ts` enforces the
 * quarantine's own boundary at runtime.
 */
export const ROOTS = [
  "components/gold",
  "app/gold",
  "components/macro",
  "app/macro",
];

// Exact, operator-only copy extracted from the SHA-pinned design artifact. It is rendered
// only on Design Notes and is byte-tested against that artifact; treating review prose
// such as "raw material of trades" as live posture copy would require corrupting the
// reference. Keep this exemption file-specific so no runtime component inherits it.
export const EXCLUDED_FILES = new Set([
  "components/macro/designNotesReference.ts",
]);

/**
 * Which of `roots` do not exist on disk, resolved against the current directory.
 *
 * Separated out and exported so the *scope* of this lint is itself testable. Before P6
 * `main()` caught a missing root and `continue`d, so the script exited **0 with no
 * output** over a scope that had evaporated — and the port plan (§7) names exactly when
 * that would have happened: re-homing `app/gold/page.tsx` under `/macro` is the move that
 * removes a root, and it lands in this very PR. A lint whose scope can disappear without
 * a message is not a lint; it is a green check mark over nothing.
 */
export async function findMissingRoots(roots = ROOTS) {
  const missing = [];
  for (const root of roots) {
    try {
      await fs.access(path.resolve(root));
    } catch {
      missing.push(root);
    }
  }
  return missing;
}

async function main() {
  const missing = await findMissingRoots();
  if (missing.length > 0) {
    for (const root of missing) {
      console.error(
        `lint-gold-copy: scope root '${root}' does not exist (resolved to ${path.resolve(root)}).`,
      );
    }
    console.error(
      "\nRefusing to report a clean posture surface over a directory that is not there. " +
        "If a root moved, update ROOTS in web/scripts/lint-gold-copy.mjs in the same commit that moved it.",
    );
    process.exit(1);
  }

  let total = 0;
  for (const root of ROOTS.map((root) => path.resolve(root))) {
    for await (const file of walk(root)) {
      const relativeFile = path.relative(process.cwd(), file).split(path.sep).join("/");
      if (EXCLUDED_FILES.has(relativeFile)) continue;
      if (
        file.endsWith("lint-gold-copy.mjs") ||
        file.endsWith("lint-gold-copy.test.mjs")
      )
        continue;
      if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
      const src = await fs.readFile(file, "utf-8");
      const violations = lintFileContents(file, src);
      for (const v of violations) {
        console.error(
          `${v.file}:${v.line}: banned posture-language '${v.word}': ${v.text}`,
        );
        total += 1;
      }
    }
  }
  if (total > 0) {
    console.error(`\n${total} posture-language violations.`);
    process.exit(1);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();
