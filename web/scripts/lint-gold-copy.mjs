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

async function main() {
  // The macro desk is one posture surface, not a gold one: the gold tab lands under
  // `/macro`, and the same banned vocabulary has to stay off every tab beside it.
  // Added additively here — the gold roots stay until the subtree actually moves.
  const roots = [
    path.resolve("components/gold"),
    path.resolve("app/gold"),
    path.resolve("components/macro"),
    path.resolve("app/macro"),
  ];
  let total = 0;
  for (const root of roots) {
    try {
      await fs.access(root);
    } catch {
      continue;
    }
    for await (const file of walk(root)) {
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
