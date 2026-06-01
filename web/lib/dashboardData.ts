import { api, type WatchlistResponse } from "./api";

const emptyWatchlist: WatchlistResponse = {
  scanned_at_min: null,
  scanned_at_max: null,
  scheduler_lag_seconds: null,
  queue: {
    total: 0,
    queued: 0,
    running: 0,
    oldest_requested_at: null,
  },
  tickers: [],
};

export async function loadDashboardData(
  qs: URLSearchParams,
): Promise<{ data: WatchlistResponse; apiUnavailable: boolean }> {
  try {
    const data = await api.watchlist(qs);
    return { data, apiUnavailable: false };
  } catch {
    return { data: emptyWatchlist, apiUnavailable: true };
  }
}
