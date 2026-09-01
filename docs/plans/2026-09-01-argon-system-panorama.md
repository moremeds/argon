# Argon System Panorama Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a validated, explorable HTML panorama of Argon's repository-proven architecture and data flows.

**Architecture:** Author one Archify `architecture` specification with no more than 12 primary nodes. Preserve a left-to-right market-data-to-operator path, attach operational and AI branches to their closest component, and encode lower-level detail in node descriptions and semantic relationship labels.

**Tech Stack:** Archify 2.16, typed JSON, inline-SVG standalone HTML, Node.js visual-check runtime.

---

### Task 1: Complete the evidence inventory

**Files:**
- Read: `docker-compose.yml`
- Read: `scripts/dev.sh`
- Read: `src/uw_scan/api/server.py`
- Read: `src/uw_scan/worker/scheduler.py`
- Read: `src/uw_scan/storage/repository.py`
- Read: `src/uw_scan/sources/CLAUDE.md`
- Read: `web/app/CLAUDE.md`

**Step 1:** Extract the authoritative service list, worker roles, API router families, source priorities, persistence boundaries, and page families.

**Step 2:** Cross-check named flows against implementation imports or service commands; label optional/configured paths as optional rather than live.

### Task 2: Author the Archify candidate

**Files:**
- Create: `output/archify/argon-system-panorama.json`

**Step 1:** Read Archify's architecture schema, common schema, architecture example, and repository-evidence authoring contract.

**Step 2:** Write a fresh Chinese-language showcase candidate with one clear main path, no more than 12 primary nodes, automatic routes, and semantic labels.

**Step 3:** Run the packaged update checker once after the first candidate exists.

### Task 3: Validate and repair the composition

**Files:**
- Modify only when diagnosed: `output/archify/argon-system-panorama.json`

**Step 1:** Run:

```bash
node bin/archify.mjs validate architecture \
  /Users/chenxi/projects/argon/output/archify/argon-system-panorama.json \
  --quality showcase --json
```

Expected: nine artifact checks, zero composition errors, zero warnings.

**Step 2:** If validation fails, change only the diagnosed subject using a supported fix, then rerun validation. Stop after two non-improving repair rounds.

### Task 4: Deliver the trusted HTML

**Files:**
- Create: `output/archify/argon-system-panorama.html`
- Create: Archify delivery sidecars beside the HTML

**Step 1:** Run Archify `deliver` with `--quality showcase --json`.

Expected: exit 0 with specification and artifact SHA-256 receipts and byte counts.

### Task 5: Collect browser and perceptual evidence

**Files:**
- Create: Archify visual-check evidence and screenshots beside the delivered HTML

**Step 1:** Run Archify `visual-check` on the exact delivered HTML.

Expected: desktop coverage at 1440x900, 1600x1000, 1920x1080, and 2048x1320; document scroll width and height stay within each viewport.

**Step 2:** Inspect the largest and representative smaller screenshots with an image-capable viewer.

**Step 3:** Report deterministic delivery, browser behavior, and perceptual review as separate claims.

No commit step is included because the repository explicitly requires separate user authorization before committing.

