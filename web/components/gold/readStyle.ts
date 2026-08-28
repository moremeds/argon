import type { CSSProperties } from "react";

/**
 * The board's `.read` — an interpretive paragraph on its 2px accent rail.
 *
 * Written as an inline style object rather than by using the `read` class from
 * `app/macro/board.css`, because these paragraphs render on two routes and only one of
 * them loads that stylesheet: the macro desk imports `board.css` in its layout, while
 * `/gold/replay/<date>` is outside `app/macro` entirely. A class would style the desk and
 * silently do nothing on the replay route, which is the worse of the two failures — the
 * rail is what separates "here is a number" from "here is what it means", and a page that
 * drops it is making a claim without marking it as one.
 *
 * The colour is the board's `--accent-deep`, matching the note in `board.css`: it is the
 * light theme's `--positive`, so the one literal reads correctly on either ground.
 */
export const goldReadStyle: CSSProperties = {
  margin: 0,
  fontSize: 12.5,
  lineHeight: 1.5,
  color: "var(--text-secondary, #9aa3b2)",
  borderLeft: "2px solid #048a7a",
  paddingLeft: 9,
  maxWidth: "72ch",
};
