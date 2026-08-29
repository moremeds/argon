import { DESIGN_NOTES_REFERENCE_HTML } from "./designNotesReference";

/**
 * Static operator record from the SHA-pinned Claude artifact.
 *
 * This tab has no live bindings or interactions. Rendering its reviewed DOM verbatim
 * keeps all eleven panels, tables, tags, and decision notes aligned with the visual
 * authority without maintaining a second hand-transcribed component tree.
 */
export function DesignNotes() {
  return (
    <div
      className="board"
      data-testid="macro-design-notes"
      dangerouslySetInnerHTML={{ __html: DESIGN_NOTES_REFERENCE_HTML }}
    />
  );
}
