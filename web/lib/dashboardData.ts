import { api, type WatchlistChainInfo, type WatchlistResponse } from "./api";

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
  hot_count: 0,
  hot_max: 0,
  tickers: [],
};

export async function loadDashboardData(qs: URLSearchParams): Promise<{
  data: WatchlistResponse;
  chains: WatchlistChainInfo[];
  apiUnavailable: boolean;
}> {
  // The rail is chrome; the grid is the page. A failing /watchlist/chains must
  // degrade to an unfiltered grid, never blank the dashboard — so its failure
  // is swallowed independently rather than sharing the outer try.
  const chainsPromise = (async () => {
    try {
      return (await api.watchlistChains())?.chains ?? [];
    } catch {
      return [];
    }
  })();

  try {
    // Both in one pass: fetching the rail client-side would flash an empty
    // filter bar on every navigation.
    const [data, chains] = await Promise.all([
      api.watchlist(qs),
      chainsPromise,
    ]);
    return { data, chains, apiUnavailable: false };
  } catch {
    return {
      data: emptyWatchlist,
      chains: await chainsPromise,
      apiUnavailable: true,
    };
  }
}
