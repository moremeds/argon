import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DesignNotes } from "@/components/macro/DesignNotes";
import { DESIGN_NOTES_REFERENCE_HTML } from "@/components/macro/designNotesReference";

describe("DesignNotes", () => {
  it("renders the artifact's eleven-panel inventory in order", () => {
    const { container } = render(<DesignNotes />);
    expect(
      [...container.querySelectorAll(".panel > .panel-h h3")].map((node) =>
        node.textContent?.replace(/\s+/g, " ").trim(),
      ),
    ).toEqual([
      "① First principles · why the board is shaped like this",
      "② Deep-review verdict · before → after",
      "③ Reference benchmark · four Vercel monitors",
      "④ Data-quality findings · from this build",
      "⑤ Extraction inventory · every panel on the three source pages",
      "⑥ Four dead elements on the live pages — and two misleading ones",
      "⑦ Two freshness-reporting holes · observed, not diagnosed",
      "⑧ Palette decision record",
      "⑨ Endpoint reality check · every panel on this desk",
      "⑩ Routing & implementation split",
      "Open questions · for the operator",
    ]);
  });

  it("keeps the rendered reference byte-identical to the pinned artifact section", () => {
    const artifact = readFileSync(
      resolve(
        process.cwd(),
        "../docs/superpowers/specs/2026-08-27-macro-desk-board.html",
      ),
      "utf8",
    );
    const marker = '<section id="t8" role="tabpanel">';
    const start = artifact.indexOf(marker);
    const end = artifact.indexOf("</section>", start);

    expect(start).toBeGreaterThanOrEqual(0);
    expect(end).toBeGreaterThan(start);
    expect(DESIGN_NOTES_REFERENCE_HTML).toBe(
      artifact.slice(start + marker.length, end),
    );
  });
});
