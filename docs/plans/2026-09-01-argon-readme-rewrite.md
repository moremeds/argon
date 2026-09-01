# Argon README Rewrite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use execute-plan to implement this plan task-by-task.

**Goal:** Replace Argon's oversized, manifesto-style README with a concise public portfolio and technical entry point that accurately positions Argon inside the five-repository quant desk.

**Architecture:** Keep one narrative path: product purpose, system panorama, research capabilities, ecosystem position, technical architecture, engineering guarantees, and a minimal developer entry point. Verify every current-state claim against repository files and sibling repositories before publishing it.

**Tech Stack:** Markdown, repository metadata, Git remotes, Archify SVG

---

### Task 1: Verify public facts

**Files:**
- Read: `pyproject.toml`
- Read: `web/package.json`
- Read: `docker-compose.yml`
- Read: `scripts/dev.sh`
- Read: `src/uw_scan/api/server.py`
- Read: `src/uw_scan/worker/scheduler.py`
- Read: `web/components/stock/panels/tradeInsightsAi/ProviderTabBar.tsx`
- Read: sibling repository README or primary project guidance for `livewire`, `signal-lab`, `apex`, and `xenon`

**Step 1:** Confirm the current Argon version from both Python and web package metadata.

**Step 2:** Confirm the current service and worker topology from `docker-compose.yml` and `scripts/dev.sh`.

**Step 3:** Confirm current provider/UI claims from the Trade Insights provider tab implementation.

**Step 4:** Confirm each ecosystem repository's public GitHub URL and current responsibility from its own repository.

**Step 5:** Record only facts needed by the new README; do not copy internal operational detail into the public document.

### Task 2: Rewrite the README

**Files:**
- Modify: `README.md`
- Preserve: `docs/screenshots/argon-system-panorama-en.svg`

**Step 1:** Replace the opening with one concrete product sentence and a short paragraph explaining the decision workflow.

**Step 2:** Place the English system panorama immediately after the opening.

**Step 3:** Add a compact `What Argon covers` section grouped by research purpose rather than route inventory.

**Step 4:** Add `Quant Desk Ecosystem` with verified links and the chain `livewire → signal-lab → apex → argon → xenon`.

**Step 5:** Add a concise `How it works` section covering sources, workers, PostgreSQL, FastAPI, Next.js, realtime failover, and human execution.

**Step 6:** Replace `Four Disciplines` with a short `Engineering guarantees` section containing only externally meaningful boundaries.

**Step 7:** Retain a minimal Quick Start and validation command set; link to detailed environment, deployment, design, plans, and changelog documentation.

**Step 8:** Remove duplicate surfaces/services descriptions, the long glossary, milestone history, private machine coordinates, stale release claims, and manifesto-style copy.

### Task 3: Validate the public README

**Files:**
- Verify: `README.md`
- Verify: `docs/screenshots/argon-system-panorama-en.svg`

**Step 1:** Run `git diff --check -- README.md docs/screenshots/argon-system-panorama-en.svg` and expect exit 0.

**Step 2:** Verify every relative Markdown link and image target exists locally.

**Step 3:** Run `xmllint --noout docs/screenshots/argon-system-panorama-en.svg` and expect exit 0.

**Step 4:** Render the SVG with `rsvg-convert` and visually inspect the result.

**Step 5:** Search the README for removed private coordinates, stale version strings, `Four Disciplines`, and unsupported current-state claims; expect no matches.

**Step 6:** Review the final diff for concise public tone, accurate ecosystem framing, and no unrelated changes.

No commit is included because repository instructions require explicit user authorization before committing.
