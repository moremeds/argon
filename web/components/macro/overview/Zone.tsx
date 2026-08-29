/**
 * The board's `.zone` banner — tab 00's spine.
 *
 * The board divides the daily loop into four labelled zones (WHAT CHANGED / WHAT DISAGREES
 * / WHAT'S NEXT / the chain) and the banner is what makes them read as an ordered walk
 * rather than eleven panels in a pile. Without it the tab is a wall of cards and the
 * operator has to infer the reading order from the content, which is exactly the failure
 * the board's own zone kickers exist to prevent.
 *
 * `scope` is the board's SECOND kicker, on the right of the rule. It is not decoration:
 * it says what the zone is bounded by — a date range for zone 1, a caveat for zone 2 —
 * and every zone on the board carries one.
 */
export function Zone({
  kicker,
  label,
  scope,
  first = false,
}: {
  /** Left kicker. The board writes `ZONE 1` … `ZONE 3`, then `ANCHOR` for the chain. */
  kicker: string;
  /** The zone's name, in the board's 14px bold sans. */
  label: string;
  /** Right kicker — the zone's bound. Derived by the caller, never a frozen string:
   *  zone 1's is a real date range and must move with the data. */
  scope: string;
  /** The first zone sits closer to the standfirst above it (board `.zone.z1`). */
  first?: boolean;
}) {
  return (
    <div
      className={first ? "zone z1" : "zone"}
      data-testid={`macro-zone-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}
    >
      <span className="zk">{kicker}</span>
      <span className="zl">{label}</span>
      <span className="rule" />
      <span className="zk">{scope}</span>
    </div>
  );
}
