/** Vocabulary shared by every surface on the Fundamentals tab.
 *
 * Extracted when `FundamentalsTab.tsx` crossed the 500-line budget: the tile,
 * the eighth card and the tab itself all need the same panel chrome and the
 * same feature names, and a second copy of `LABELS` would let the coverage
 * list disagree with the tile it describes.
 */

export const LABELS: Record<string, string> = {
  rev_growth: "Revenue growth",
  gross_margin: "Gross margin",
  op_margin: "Operating margin",
  fcf_margin: "FCF margin",
  roe: "Return on equity",
  neg_net_debt_ebitda: "Net cash / EBITDA",
  asset_turnover: "Asset turnover",
};

export const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  minWidth: 0,
};

export const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

/** The style a tile uses to look like a panel while being a real `<button>`.
 *
 * `font`/`color`/`textAlign` undo the UA button defaults. A native button is
 * what delivers Enter, Space, focus order and the right role — reimplementing
 * those on a div is how they get missed. */
export const tileButtonStyle: React.CSSProperties = {
  ...panelStyle,
  padding: 12,
  textAlign: "left",
  cursor: "pointer",
  font: "inherit",
  color: "inherit",
  width: "100%",
};

/** The wrapper an opened back renders into: full grid row, so 20 quarterly
 *  bars get a readable width instead of a 260px column.
 *
 *  Built on `tileButtonStyle`, not `panelStyle`, because the back is itself a
 *  `<button>` — clicking the card flips it back. That is also why the back
 *  carries no `close` control: HTML forbids a button inside a button, and a
 *  div-with-onClick standing in for one would drop Enter, Space and focus. */
export const backPanelStyle: React.CSSProperties = {
  ...tileButtonStyle,
  gridColumn: "1 / -1",
};
