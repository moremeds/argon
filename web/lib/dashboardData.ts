import { api, type WatchlistResponse } from "./api";

type SparklineMap = Record<string, number[]>;

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

async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const workers = Array.from(
    { length: Math.min(Math.max(limit, 1), items.length) },
    async () => {
      while (next < items.length) {
        const index = next;
        next += 1;
        results[index] = await fn(items[index]);
      }
    },
  );
  await Promise.all(workers);
  return results;
}

export async function loadDashboardData(
  qs: URLSearchParams,
  sparklineConcurrency = 6,
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

  const sparklineEntries = await mapWithConcurrency(
    data.tickers,
    sparklineConcurrency,
    async (t) => {
      try {
        const bars = await api.ohlc(t.ticker, 30);
        const closes = bars.map((b) => Number(b.close)).reverse();
        return [t.ticker, closes] as const;
      } catch {
        return [t.ticker, [] as number[]] as const;
      }
    },
  );

  return {
    data,
    sparklines: Object.fromEntries(sparklineEntries),
    apiUnavailable: false,
  };
}
