/**
 * Posture-language lint rule for the GOLD COMPASS UI.
 *
 * v1 dashboard copy must use posture / risk / scenario language, NOT
 * recommendation / position / sizing / execution language. Per
 * docs/research/gold-sdf-framework/04-three-layer-architecture.md and
 * spec §8.4 (banned-strings table), sizing-imperative copy overstates
 * confidence before backtest validation exists and is banned in any
 * /gold UI component.
 *
 * Bypass: a single line can opt out by adding the trailing comment
 *   // posture-lint-disable-next-line
 * on the line above the offending string (for academic citations,
 * banned-string assertions in tests, etc.).
 */

export const BANNED_POSTURE_LANGUAGE = [
  // sizing imperatives (English)
  "buy",
  "sell",
  "long",
  "short",
  // sizing nouns (English)
  "position size",
  "recommended size",
  "allocate %",
  // execution verbs (English)
  "trade",
  "execute",
  // model claims (English)
  "predicted return",
  "shap",
  "xgboost",
  // backtest claims (English)
  "equity curve",
  "backtest account",
  // bilingual mirrors (per spec §8.4)
  "做多",
  "做空",
  "仓位",
  "今日信号",
  "预测收益",
  "净值曲线",
  "回测账户",
] as const;

export type BannedTerm = (typeof BANNED_POSTURE_LANGUAGE)[number];

/**
 * Return the list of banned substrings present in `text`.
 *
 * - Case-insensitive for ASCII terms; CJK terms match literally.
 * - Uses word boundaries on ASCII terms so "buyback" / "longwood" don't
 *   trigger false positives. CJK doesn't have word boundaries; we accept
 *   that a banned CJK token embedded in another word is still a match.
 */
export function findBannedSubstrings(text: string): string[] {
  const lower = text.toLowerCase();
  const hits: string[] = [];
  for (const term of BANNED_POSTURE_LANGUAGE) {
    if (isAscii(term)) {
      const re = new RegExp(`\\b${escapeRegExp(term)}\\b`, "i");
      if (re.test(lower)) hits.push(term);
    } else if (text.includes(term)) {
      hits.push(term);
    }
  }
  return hits;
}

function isAscii(s: string): boolean {
  for (let i = 0; i < s.length; i += 1) {
    if (s.charCodeAt(i) > 127) return false;
  }
  return true;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
