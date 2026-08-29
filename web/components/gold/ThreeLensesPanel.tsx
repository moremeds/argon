import { BoardPanel, BoardRead } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

type State = components["schemas"]["GoldStateResponse"];

/**
 * The board's second t5 panel: the three lenses side by side, and the refusal in its title.
 *
 * ### "each publishes, none composites" is the panel's whole argument
 *
 * Three lenses on one surface is the shape most likely to be read as three inputs to a
 * score, and the board's own heading pre-empts that. Each lens publishes its own label on
 * its own basis — L1 counts metal, L2 reads a macro relationship, L3 compares gold against
 * its own history — and there is no arithmetic that combines them, because there is no
 * common unit to combine them IN. A row that averaged the three chips would be inventing
 * one.
 *
 * ### Why the meters are valuation's and not one per lens
 *
 * A meter is a position on a shared 0..1 track, so it can only be drawn for readings that
 * are already percentiles. L3 publishes three of them (real price, gold÷M2, gold÷oil) and
 * the other two lenses publish labels and tonnages, which have no track to sit on. Drawing
 * a meter for a label would be assigning it a number nobody computed — so the meters are
 * L3's, marked as such, and the other two lenses stay words.
 *
 * The null anchor renders as a track with no pin and `n/a`, never as a pin at zero: a
 * percentile that was not computed is not a percentile of nothing.
 */
const ANCHORS = [
  { key: "real_price_percentile", label: "real gold own-history" },
  { key: "gold_m2_ratio_percentile", label: "gold ÷ M2" },
  { key: "gold_oil_ratio_percentile", label: "gold ÷ oil" },
  { key: "gold_spx_ratio_percentile", label: "gold ÷ SPX" },
] as const;

function pct(raw: string | number | null | undefined): number | null {
  const n = typeof raw === "string" ? Number(raw) : raw;
  return n === null || n === undefined || !Number.isFinite(n) ? null : n;
}

export function ThreeLensesPanel({ state }: { state: State }) {
  const lenses = [
    {
      id: "l1",
      name: "L1 · Structural",
      publishes: "metal that moved — official sector, ETFs, exchange stock",
      chip: state.structural.posture_chip,
      label: state.structural.state_label,
    },
    {
      id: "l2",
      name: "L2 · Cyclical",
      publishes:
        "the macro relationship — real rates, inflation compensation, the dollar",
      chip: state.cyclical.posture_chip,
      label: state.cyclical.zone_label,
    },
    {
      id: "l3",
      name: "L3 · Valuation",
      publishes: "gold against its own history — never a price target",
      chip: state.valuation.posture_chip,
      label: state.valuation.flag,
    },
  ];

  const anchors = ANCHORS.map((a) => ({
    ...a,
    value: pct(state.valuation[a.key]),
  }));
  const served = anchors.filter((a) => a.value !== null);

  return (
    <BoardPanel
      id="three-lenses"
      title="Three lenses · each publishes, none composites"
      questions={["Q1", "Q5"]}
      basis="REAL"
      source={
        <>
          /api/gold/state · structural, cyclical and valuation each as its own
          engine published it · {served.length} of {anchors.length} valuation
          anchors computed
        </>
      }
    >
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Lens</th>
              <th>What it publishes</th>
              <th>Reading</th>
            </tr>
          </thead>
          <tbody>
            {lenses.map((lens) => (
              <tr key={lens.id} data-testid={`gold-lens-${lens.id}`}>
                <td>{lens.name}</td>
                <td>{lens.publishes}</td>
                <td className="num">
                  {lens.label}
                  {lens.chip ? (
                    <span className="dir"> · {lens.chip}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="cap">L3 valuation anchors · own-history percentile</p>
      {anchors.map((a) => (
        <div className="meter" key={a.key} data-testid={`gold-anchor-${a.key}`}>
          <span className="lbl">{a.label}</span>
          <div className="track">
            <span className="mid" />
            {a.value !== null ? (
              <span
                className={a.value >= 0.8 ? "pin crit" : "pin"}
                style={{
                  left: `${Math.max(0, Math.min(100, a.value * 100))}%`,
                }}
              />
            ) : null}
          </div>
          <span
            className="val"
            style={
              a.value === null ? { color: "var(--text-muted)" } : undefined
            }
          >
            {a.value === null ? "n/a" : `p${Math.round(a.value * 100)}`}
          </span>
        </div>
      ))}

      {/* L3's own published sentence. Carried here rather than dropped with the separate
          valuation panel the board does not have: the flag in the table above is a label,
          and this is the engine's own words about what the label rests on. */}
      {state.valuation.narrative_text ? (
        <p className="cap" data-testid="gold-valuation-narrative">
          {state.valuation.narrative_text}
        </p>
      ) : null}

      <BoardRead testId="gold-lenses-read">
        {served.length === 0 ? (
          <>
            No valuation anchor has been computed, so the meters are empty. The
            two lenses above still published — an absent percentile is not an
            absent lens.
          </>
        ) : (
          <>
            {served.length === anchors.length ? (
              <>All {anchors.length} anchors are computed.</>
            ) : (
              <>
                <b>
                  {anchors.length - served.length} of {anchors.length} anchors
                  are null
                </b>{" "}
                (
                {anchors
                  .filter((a) => a.value === null)
                  .map((a) => a.label)
                  .join(", ")}
                ) — each lights up on its own once the series behind it lands,
                and until then the track is drawn empty rather than pinned at
                zero.
              </>
            )}{" "}
            The three readings above are <b>not combined</b>: they are measured
            in different units against different histories, and a single gold
            verdict averaging them would be a number no engine on this desk
            produced.
          </>
        )}
      </BoardRead>
    </BoardPanel>
  );
}
