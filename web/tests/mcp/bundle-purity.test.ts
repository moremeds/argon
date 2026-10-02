// Bundle purity: every MCP tool B owns must bundle for platform=node without
// pulling browser modules. Asserted on esbuild's metafile inputs (the files
// actually bundled), not on a string grep of the output.
// @vitest-environment node — esbuild needs real-node globals (its jsdom
// TextEncoder realm fails esbuild's startup invariant check).
import { describe, expect, it } from "vitest";
import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const B_TOOLS = [
  "technicals_scan",
  "ticker_snapshot",
  "regime_state",
  "market_overview",
];
const BANNED = /(^|\/)node_modules\/(react|react-dom|lightweight-charts|fancy-canvas)(\/|$)/;

describe("mcp bundle purity", () => {
  it("B's tools bundle for Node with no react/lwc modules", async () => {
    const res = await build({
      entryPoints: B_TOOLS.map((t) =>
        path.join(WEB, "mcp", "tools", `${t}.ts`),
      ),
      bundle: true,
      write: false,
      // outdir is required to name multiple entry outputs; nothing is written.
      outdir: "bundle-purity-out",
      platform: "node",
      format: "cjs",
      alias: { "@": WEB },
      external: ["pg", "@modelcontextprotocol/sdk"],
      metafile: true,
      logLevel: "silent",
    });
    const inputs = Object.keys(res.metafile?.inputs ?? {});
    // Sanity: the entry points really did bundle (guard against a vacuous pass).
    expect(inputs.some((p) => p.endsWith("technicals_scan.ts"))).toBe(true);
    expect(inputs.some((p) => p.includes("lib/technicals/overlays"))).toBe(
      true,
    );
    const bad = inputs.filter((p) => BANNED.test(p));
    expect(bad).toEqual([]);
    // No banned specifier left external either (e.g. a bare "react" import).
    for (const out of Object.values(res.metafile?.outputs ?? {})) {
      const badExt = (out.imports ?? [])
        .filter((i) => i.external)
        .filter((i) => BANNED.test(`x/node_modules/${i.path}`));
      expect(badExt).toEqual([]);
    }
  });
});
