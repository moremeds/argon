# Changelog

All notable changes to Argon are documented here. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/) with semver versioning.
`VERSION` is the source of truth; `pyproject.toml` and `web/package.json`
version in lockstep (enforced by `scripts/release/version_sync_check.py`).

## [Unreleased]

### Fixed

- Stock detail pages (Flow / Market Structure / GEX) no longer render empty
  during US off-hours. `Repository.latest_run_id` selected the newest scan_run
  via a hand-maintained `notes` denylist; the skew engine's `skew_swing_greeks`
  side-channel runs were not on it and — having higher run_ids and no aggregates
  — shadowed the real `full_scan`, blanking every ticker's detail page after
  ~17:30 ET each day. The selector (and the `get_scan_duration_summary` health
  metric) now key on the property the report actually needs —
  `status='ok' AND aggregates IS NOT NULL` — so no future side-channel job can
  re-break it. No data was lost; the fix is read-path only.

## [0.1.1] — 2026-06-17


### Added

- Health sidebar now shows deployed backend version in the collapsed header,
  sourced from the running process via the existing `/api/health` poll.
## [0.1.0] — 2026-06-17

### Added

- Baseline release. Per-ticker options analytics: Next.js web (`web/`, :3001),
  FastAPI read API (`src/uw_scan/api/`, :8400), and the APScheduler worker, over
  a single Postgres (`uw_scan` schema). Scanner, regime (CRI/GEX/VCG), skew,
  Gold Compass, cockpit, and Trade Insights AI (Codex/Claude/DeepSeek) ship in
  this baseline. First release cut through the tag-driven `release.yml` pipeline.
