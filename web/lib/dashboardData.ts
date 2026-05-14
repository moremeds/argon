import { api, type WatchlistResponse } from "./api";

type SparklineMap = Record<string, number[]>;

const emptyWatchlist: WatchlistResponse = {
  scanned_at_min: null,
  scanned_at_max: null,
  scheduler_lag_seconds: null,
  tickers: [],
};

export async function loadDashboardData(
  qs: URLSearchParams,
): Promise<{
  data: WatchlistResponse;
  sparklines: SparklineMap;
  apiUnavailable: boolean;
}> {
  let data: WatchlistResponse;
  try {
    data = await api.watchlist(qs);
  } catch {
    return { data: emptyWatchlist, sparklines: {}, apiUnavailable: true };
  }

  const sparklineEntries = await Promise.all(
    data.tickers.map(async (t) => {
      try {
        const bars = await api.ohlc(t.ticker, 30);
        const closes = bars.map((b) => Number(b.close)).reverse();
        return [t.ticker, closes] as const;
      } catch {
        return [t.ticker, [] as number[]] as const;
      }
    }),
  );

  return {
    data,
    sparklines: Object.fromEntries(sparklineEntries),
    apiUnavailable: false,
  };
}
