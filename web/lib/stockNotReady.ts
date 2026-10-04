import { ApiError } from "./apiClient";

/** True when `/api/stock/{ticker}` answered 404 "no runs for {ticker}" (the
 *  ticker is on the watchlist but has never been scanned). Matches on the typed
 *  status/path/detail, not the error text (I-102). Case-insensitive, as the old
 *  text match was. */
export function isStockReportNotReadyError(error: unknown, ticker: string) {
  if (!(error instanceof ApiError) || error.status !== 404) return false;
  const lower = ticker.toLowerCase();
  return (
    error.path.toLowerCase() === `/api/stock/${lower}` &&
    typeof error.detail === "string" &&
    error.detail.toLowerCase() === `no runs for ${lower}`
  );
}
