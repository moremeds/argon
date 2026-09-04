/**
 * Which uppercase words in a run's prose are TICKERS.
 *
 * A page cannot tell `SPY` from `ET`, `OAS` or `RTH` by shape — they are all
 * short uppercase words — so nothing is inferred from the token. A word is a
 * ticker only if it is on a list: the names this page is already about (its
 * tape, its candidates, its gamma rows, its status blocks), plus the desk's
 * standing universe below. Anything else stays plain text.
 *
 * The consequence is deliberate: a ticker helium mentions once, in prose, and
 * nowhere in the structured view is NOT highlighted unless it is on the static
 * list. A missed highlight is a paragraph that reads normally; a wrong one
 * turns "the ET close" into a symbol the run never traded.
 */
export const STATIC_TICKERS: readonly string[] = [
  "SPY",
  "QQQ",
  "IWM",
  "DIA",
  "VIX",
  "VVIX",
  "SPX",
  "NDX",
  "RUT",
  "TLT",
  "HYG",
  "GLD",
  "SLV",
  "USO",
  "UUP",
  "SMH",
  "XLK",
  "XLF",
  "XLE",
  "XLV",
  "XLY",
  "XLP",
  "XLI",
  "XLU",
  "XLRE",
  "VNQ",
  "ARKK",
  "NVDA",
  "AAPL",
  "MSFT",
  "AMZN",
  "GOOGL",
  "META",
  "TSLA",
  "AVGO",
  "AMD",
  "MRVL",
  "ALAB",
  "MU",
  "TSM",
  "ASML",
  "LULU",
];

/** An uppercase word that COULD be a ticker. Membership decides, not shape. */
export const TICKER_TOKEN = /\b[A-Z]{1,5}\b/g;

/**
 * The static universe plus whatever names the caller found in its own view.
 *
 * `XLRE` is five characters and `GOOGL` is five, so the token pattern stops
 * there; a longer symbol simply never matches, which is a missed highlight and
 * not a wrong one.
 */
export function tickerSet(extra: Iterable<string> = []): Set<string> {
  const set = new Set<string>(STATIC_TICKERS);
  for (const raw of extra) {
    const t = String(raw ?? "")
      .trim()
      .toUpperCase();
    if (/^[A-Z]{1,5}$/.test(t)) set.add(t);
  }
  return set;
}
