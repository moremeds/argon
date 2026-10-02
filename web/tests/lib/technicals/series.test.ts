import { describe, expect, it } from "vitest";
import type {
  TechnicalsLiveResponse,
  TechnicalsResponse,
} from "@/lib/api";
import {
  etSessionDate,
  isFresh,
  mergeLiveHead,
  sliceSeriesByTimeframe,
} from "@/lib/technicals/series";
import aaplTechnicals from "@/tests/fixtures/mcp/aapl_technicals.json";
import aaplLiveFixture from "@/tests/fixtures/mcp/aapl_technicals_live.json";

const data = aaplTechnicals as unknown as TechnicalsResponse;
const fixtureLive = aaplLiveFixture as unknown as TechnicalsLiveResponse;

// An arbitrary pinned instant inside US RTH: Fri 2026-10-02 11:00 ET (EDT).
const NOW = Date.parse("2026-10-02T15:00:00Z");

describe("isFresh", () => {
  it("accepts a capture inside the 900s window and rejects stale/future/absent", () => {
    const at = (iso: string) =>
      ({ ...fixtureLive, captured_at: iso }) as TechnicalsLiveResponse;
    expect(isFresh(at(new Date(NOW - 60_000).toISOString()), NOW)).toBe(true);
    expect(isFresh(at(new Date(NOW - 901_000).toISOString()), NOW)).toBe(false);
    expect(isFresh(at(new Date(NOW + 60_000).toISOString()), NOW)).toBe(false);
    expect(isFresh(null, NOW)).toBe(false);
  });
});

describe("etSessionDate", () => {
  it("dates the fixture capture to its ET session, not its UTC date", () => {
    // captured_at is 2026-07-11T11:49:08+08:00 — Sat Jul 11 in UTC/+08 but
    // Fri Jul 10 23:49 in New York, so the session date is 2026-07-10.
    expect(etSessionDate(fixtureLive.captured_at!)).toBe("2026-07-10");
  });
});

describe("sliceSeriesByTimeframe on the frozen series", () => {
  it("windows the 500-row payload to 1y around the last bar (2026-09-18)", () => {
    const rows = sliceSeriesByTimeframe(data.series, "1y");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(data.series.length);
    expect(rows[0].as_of >= "2025-09-18").toBe(true);
    expect(rows.at(-1)!.as_of).toBe("2026-09-18");
  });
});

describe("mergeLiveHead with injected now", () => {
  it("leaves data unchanged when the live capture is stale", () => {
    // Fixture captured_at (2026-07-11) is ~12 weeks before NOW — far outside
    // the 900s gate, so mergeLiveHead returns the input untouched.
    expect(mergeLiveHead(data, fixtureLive, NOW)).toBe(data);
  });

  it("appends a provisional live row when the capture's ET session is newer than the EOD head", () => {
    // Changed vs the fixture payload: only `captured_at` (was
    // 2026-07-11T11:49:08+08:00, stale vs the 2026-09-18 EOD head) is set to
    // 30s before NOW. The fixture's forming_ohlc.session_date (2026-07-11) no
    // longer matches the new ET session, so the appended row is the close-only
    // spot head, not a forming candle.
    const live = {
      ...fixtureLive,
      captured_at: new Date(NOW - 30_000).toISOString(),
    };
    const merged = mergeLiveHead(data, live, NOW);
    expect(merged.series).toHaveLength(data.series.length + 1);
    const head = merged.series.at(-1)!;
    expect(head.as_of).toBe("2026-10-02"); // ET session of NOW
    expect(head.as_of > data.series.at(-1)!.as_of).toBe(true);
    expect(head.close).toBe(fixtureLive.spot);
    expect(head.open == null).toBe(true);
    // The settled EOD row itself is untouched.
    expect(merged.series.at(-2)!.as_of).toBe(data.series.at(-1)!.as_of);
    expect(merged.series.at(-2)!.close).toBe(data.series.at(-1)!.close);
  });
});
