import { Body } from "./Body";
import { Panel } from "./Panel";
import type { Section } from "./view";

/**
 * What the run read, from where, as of when.
 *
 * The panel's own title says that; the run's title for the block rides in the
 * tail, so a tenant renaming its coverage section cannot rename argon's panel
 * out from under the reader. The body itself is printed in full — the parser
 * only recognises the pipe table helium writes and falls back to paragraphs,
 * so a changed shape degrades to plain text instead of a tidy, wrong table.
 */
export function CoveragePanel({ coverage }: { coverage: Section }) {
  return (
    <Panel title="Sources & as-of" tail={coverage.title || undefined}>
      <Body text={coverage.body} />
    </Panel>
  );
}
