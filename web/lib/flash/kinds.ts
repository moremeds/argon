/**
 * The ONLY place in argon that names option-wizard's kinds.
 *
 * Everything below layer 3 — the migration, the repository, the models, the
 * router — is a generic transport for structured helium runs and must stay
 * that way (see the plan's "Global Constraints"). `premarket` is a fact about
 * one tenant's view layer, and this file is that layer's dictionary.
 *
 * All date arithmetic here is UTC. A trading date is a label, not an instant;
 * running "2026-08-31" through a local timezone west of UTC turns a Monday
 * into the previous Sunday and silently shifts the whole week strip.
 */

import type { AgentRunIndexRow } from "@/lib/api";

export const FLASH_TENANT = "option-wizard";

/** The three phases of one trading day. `weekly` and `frank` are NOT DayKinds. */
export const DAY_KINDS = ["premarket", "intraday", "close"] as const;
export type DayKind = (typeof DAY_KINDS)[number];

/** Attached to the week, not to a day. */
export const WEEK_KINDS = ["weekly", "frank"] as const;
export type WeekKind = (typeof WEEK_KINDS)[number];

export const PIP_LABEL: Record<DayKind, "P" | "I" | "C"> = {
  premarket: "P",
  intraday: "I",
  close: "C",
};

export const KIND_LABEL: Record<string, string> = {
  premarket: "Premarket",
  intraday: "Intraday",
  close: "Close",
  weekly: "Weekly summary & outlook",
  frank: "Frank 复盘",
};

export function isDayKind(value: string): value is DayKind {
  return (DAY_KINDS as readonly string[]).includes(value);
}

const DOW = ["MON", "TUE", "WED", "THU", "FRI"] as const;

const MS_DAY = 86_400_000;

function utcDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
}

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/**
 * ISO-8601 week of a `YYYY-MM-DD` label, as `YYYY-Www`.
 *
 * The year is the ISO year, not the calendar year: the week owning
 * 2025-12-29 (a Monday) is `2026-W01` because its Thursday lands in 2026.
 */
export function isoWeekOf(date: string): string {
  const d = utcDate(date);
  // Shift to the Thursday of this week — the day that decides the ISO year.
  const dow = (d.getUTCDay() + 6) % 7; // Mon=0 … Sun=6
  const thursday = new Date(d.getTime() + (3 - dow) * MS_DAY);
  const year = thursday.getUTCFullYear();
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Dow = (jan4.getUTCDay() + 6) % 7;
  const week1Monday = new Date(jan4.getTime() - jan4Dow * MS_DAY);
  const week =
    Math.round((thursday.getTime() - week1Monday.getTime()) / MS_DAY / 7) + 1;
  return `${year}-W${String(week).padStart(2, "0")}`;
}

/** The Monday of `YYYY-Www`, as a UTC Date. */
function mondayOf(weekKey: string): Date {
  const [yearPart, weekPart] = weekKey.split("-W");
  const year = Number(yearPart);
  const week = Number(weekPart);
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Dow = (jan4.getUTCDay() + 6) % 7;
  const week1Monday = new Date(jan4.getTime() - jan4Dow * MS_DAY);
  return new Date(week1Monday.getTime() + (week - 1) * 7 * MS_DAY);
}

/** Monday..Friday of a week. Five days, always — a market week, not a calendar one. */
export function weekDays(weekKey: string): { date: string; dow: string }[] {
  const monday = mondayOf(weekKey);
  return DOW.map((dow, i) => ({
    date: isoDay(new Date(monday.getTime() + i * MS_DAY)),
    dow,
  }));
}

export function weekRange(weekKey: string): { first: string; last: string } {
  const days = weekDays(weekKey);
  return { first: days[0].date, last: days[days.length - 1].date };
}

/**
 * Today in New York — the tenant's own report timezone. Never the server's:
 * argon renders from a container whose clock is UTC, and a UTC "today" reads
 * as tomorrow for five hours of every American evening.
 */
export function todayEt(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/**
 * The newest recorded row of one kind in a week's index.
 *
 * THE WEEK'S RUNS ARE NOT FILED UNDER FRIDAY. helium sends `week_key`
 * explicitly and files each run under its own `run_day` — a Frank 复盘 for
 * W36 carries run_day 2026-09-07, the Monday AFTER the week it reviews, and
 * the weekly outlook of W36 landed on Sunday 2026-09-06. Looking for a
 * week-scoped run on the Friday finds nothing and reports "not generated yet"
 * over a run that exists. The index is the only authority on which day a
 * week-scoped run actually landed on, so the strip and the page body must both
 * read it through here — a second private copy of this rule is how the header
 * and the body came to disagree in the first place.
 */
export function newestOfKind(
  runs: AgentRunIndexRow[],
  kind: string,
): AgentRunIndexRow | undefined {
  return runs
    .filter((r) => r.kind === kind)
    .sort((a, b) =>
      String(a.run_day) === String(b.run_day)
        ? b.version_no - a.version_no
        : String(a.run_day) < String(b.run_day)
          ? 1
          : -1,
    )[0];
}
