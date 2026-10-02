// Tiny concurrency pool: `const limit = makePool(8); await limit(() => work())`
// runs at most `limit` of the wrapped fns at once, FIFO for the waiters. Used
// to cap the internal-API fan-out — ~170 tickers × 2-3 GETs would otherwise
// hit the FastAPI process all at once.
export function makePool(limit: number) {
  if (!(limit >= 1))
    throw new RangeError(`makePool limit must be >= 1, got ${limit}`);
  let active = 0;
  const waiters: (() => void)[] = [];
  const acquire = (): Promise<void> => {
    if (active < limit) {
      active++;
      return Promise.resolve();
    }
    return new Promise<void>((res) => waiters.push(res));
  };
  const release = () => {
    const next = waiters.shift();
    // A queued waiter inherits the slot — active stays put; otherwise free it.
    if (next) next();
    else active--;
  };
  return <T>(fn: () => Promise<T>): Promise<T> =>
    acquire().then(() => fn().finally(release));
}
