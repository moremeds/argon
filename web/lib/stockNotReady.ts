export function isStockReportNotReadyError(error: unknown, ticker: string) {
  if (!(error instanceof Error)) return false;

  const escapedTicker = ticker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(
    `API 404 for /api/stock/${escapedTicker}: .*"detail"\\s*:\\s*"no runs for ${escapedTicker}"`,
    "i",
  ).test(error.message);
}
