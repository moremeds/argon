// Capture what the real Flash component displays, not a transcript or email teaser.
// Usage: node scripts/capture-flash.mjs <url> <steps.json> <new-output-dir>
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { viewDigest } from '../lib/flash/view-digest.ts';

const [url, source, output] = process.argv.slice(2);
const repo = fileURLToPath(new URL('../../', import.meta.url));
if (!url || !source || !output) throw new Error('expected <url> <steps.json> <new-output-dir>');
const bytes = readFileSync(source);
const evidence = JSON.parse(bytes);
if (!evidence.run?.runId || !evidence.view) throw new Error('source must contain final run/view');
mkdirSync(output, { recursive: false });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const response = await page.goto(url, { waitUntil: 'networkidle' });
  if (!response?.ok()) throw new Error(`page HTTP ${response?.status()}`);
  const report = page.getByTestId('flash-report');
  await report.waitFor({ state: 'visible' });
  if (await report.getAttribute('data-run-id') !== evidence.run.runId) throw new Error('page run does not match source');
  if (await report.getAttribute('data-view-sha256') !== viewDigest(evidence.view)) throw new Error('page view does not match source');
  const text = await report.innerText();
  if (!text.trim() || (evidence.view.headline && !text.includes(evidence.view.headline))) throw new Error('missing source headline');
  writeFileSync(join(output, 'page.md'), text + '\n');
  writeFileSync(join(output, 'page.html'), await page.content());
  // Expand only app scroll containers while photographing the complete article.
  const style = ':has([data-testid="flash-report"]) { height: auto !important; max-height: none !important; overflow: visible !important; }';
  await page.screenshot({ path: join(output, 'desktop.png'), fullPage: true, style });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: join(output, 'mobile.png'), fullPage: true, style });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 0) throw new Error(`mobile horizontal overflow: ${overflow}`);
  const hash = (value) => createHash('sha256').update(value).digest('hex');
  writeFileSync(join(output, 'capture.json'), JSON.stringify({
    url, runId: evidence.run.runId, capturedAt: new Date().toISOString(),
    argonSha: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
    argonDirty: !!execFileSync('git', ['status', '--porcelain'], { cwd: repo, encoding: 'utf8' }).trim(),
    sourceSha256: hash(bytes), viewSha256: viewDigest(evidence.view),
    pageSha256: hash(text + '\n'), mobileOverflow: overflow,
  }, null, 2) + '\n');
} finally { await browser.close(); }
