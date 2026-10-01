# Sector RS + breadth — post-merge runbook

`sector_rs_daily` (migration 152) ships with `UW_SCAN_SECTOR_RS_ENABLED=false`. This
runbook is what to do on the mini after the PR (spec
`docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md`, plan
`docs/superpowers/plans/2026-09-26-sector-rs-daily.md`) merges and deploys.

1. Deploy through the normal release. The `api` service self-migrates, which applies
   migration 152.
2. The next 04:40 ET `company_sector_refresh` run fills S&P 500 sectors (about 330 UW
   calls, once). Check coverage with:
   ```sql
   SELECT count(*) FILTER (WHERE c.ticker IS NOT NULL)::float / count(*)
     FROM unnest(<sp500 list>) m
     LEFT JOIN uw_scan.company_sector c ON c.ticker = m;
   ```
   The list is `src/uw_scan/sources/data/sp500_members.json`.
3. After the nightly `--full` Silver rebuild, run:

   ```bash
   uv run python scripts/backfill/sector_rs_backfill.py --start 1998-12-22 --end <last close>
   ```

   It pre-flights that Silver serves the 1999 XLK/XLY/XLB/XLU/XLE bars (livewire #157),
   and it is resumable — re-run it if interrupted.

   **Gate (the ETF leg).** `rs_12m IS NOT NULL` on at least 95% of gics rows from each
   fund's first_date + 252 sessions: about 2000-01 for the nine 1998 funds, 2016-10 for
   XLRE, and 2019-07 for XLC. Every row of this query must show `rs12_share >= 0.95`:

   ```sql
   WITH first_bar(group_key, first_date) AS (
            VALUES ('Real Estate', DATE '2015-10-08'),
                   ('Communication Services', DATE '2018-06-19')),
        g AS (
            SELECT d.group_key, d.as_of, d.rs_12m,
                   COALESCE(f.first_date, DATE '1998-12-22') AS first_date
              FROM uw_scan.sector_rs_daily d
              LEFT JOIN first_bar f USING (group_key)
             WHERE d.group_kind = 'gics'),
        k AS (
            SELECT g.*, row_number() OVER (PARTITION BY group_key ORDER BY as_of) AS nth
              FROM g
             WHERE as_of >= first_date)
   SELECT group_key, min(as_of) AS gate_from,
          round(avg((rs_12m IS NOT NULL)::int), 4) AS rs12_share, count(*) AS n
     FROM k
    WHERE nth > 252            -- from first_date + 252 sessions
    GROUP BY 1 ORDER BY 1;
   ```

   **Report (the breadth leg; not gated).** This is the `degraded` share per group per
   year. Its early years are thin by construction (current membership applied to every
   session, survivorship-biased); the §6 effective start is where breadth becomes
   usable. Paste the output into the PR or the VERDICT follow-up:

   ```sql
   SELECT group_key, extract(year FROM as_of)::int AS year,
          round(avg((NOT degraded)::int), 3) AS non_degraded_share,
          round(avg(n_priced::float / NULLIF(n_members, 0))::numeric, 3) AS mean_priced_share,
          count(*) AS n
     FROM uw_scan.sector_rs_daily
    WHERE group_kind = 'gics'
    GROUP BY 1, 2 ORDER BY 1, 2;
   ```

4. Set `UW_SCAN_SECTOR_RS_ENABLED=true` in `/opt/argon/.env` and recreate the worker
   container. Watchtower does not re-read `env_file`.
5. Run `uv run python scripts/research/sector_rs_breadth_probe.py` against the mini DB.
   Commit `docs/research/<run-date>-sector-rs-breadth/` in a follow-up PR.
