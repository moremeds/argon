import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

type Provenance = components["schemas"]["GoldInputProvenance"];

type Props = {
  obsDate: string;
  computedAt: string;
  inputsUsed: Record<string, Provenance>;
};

/**
 * Display threshold for the staleness table, in days.
 *
 * A DISPLAY choice, not a measured limit, and it is named here rather than inlined so it
 * cannot be mistaken for one. Nothing in the engine treats 30 days as a boundary; the
 * table exists to surface the inputs whose age a reader should carry while reading the
 * lenses, and every input's own age is printed beside it either way. Two of the desk's
 * inputs are quarterly by nature, so a threshold low enough to catch a broken daily feed
 * will always also catch them — which is why the row says the cadence, not just the age.
 */
const STALE_AFTER_DAYS = 30;

function ageInDays(obs: string, against: string): number | null {
  const a = Date.parse(obs);
  const b = Date.parse(against);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

const mono: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  color: "var(--text-secondary, #9aa3b2)",
};

/**
 * Board t5 — "Input manifest · what the lenses actually read" (Q7).
 *
 * ### Why a declared-but-unread input is shown, and shown apart
 *
 * This was a footer listing the inputs that WERE read. A manifest naming only what
 * succeeded reads as a complete audit trail, and the output then looks whole while three
 * of sixteen declared inputs never reached a lens. So the panel leads with coverage —
 * read over declared — and names the rest with the reason each was skipped.
 *
 * ### Why `required` is the split, and not the omission itself
 *
 * The three omissions are not the same kind of thing. Two are recorded DECISIONS: no FX
 * leg is ingested for the gold complex, and no SPX series feeds the valuation overlay, so
 * those lenses run on what remains and say so. One is a real GAP: `exchange_inventory_daily`
 * is marked `required` and has never received a COMEX row, and it is why lens 1 degrades
 * rather than substituting a neighbouring venue's inventory. Presenting all three as
 * "missing" would flatten a deliberate scope boundary into a pipeline failure, and hide
 * the single row that actually wants fixing.
 *
 * Every count and every age is derived from the response at render time. The board's own
 * figures — 13 of 16, 81%, ~86d, ~100d — were true at its capture instant and are not
 * carried.
 */
export function InputManifestPanel({ obsDate, computedAt, inputsUsed }: Props) {
  const entries = Object.entries(inputsUsed);
  const read = entries.filter(([, p]) => p.obs_date);
  const omitted = entries.filter(([, p]) => !p.obs_date);
  const gaps = omitted.filter(([, p]) => p.required);
  const decisions = omitted.filter(([, p]) => !p.required);
  const coverage =
    entries.length > 0
      ? Math.round((100 * read.length) / entries.length)
      : null;

  const stale = read
    .map(([sid, p]) => ({
      sid,
      prov: p,
      age: p.obs_date ? ageInDays(p.obs_date, obsDate) : null,
    }))
    .filter((r) => r.age !== null && r.age >= STALE_AFTER_DAYS)
    .sort((a, b) => (b.age as number) - (a.age as number));

  return (
    <BoardPanel
      id="input-manifest"
      title="Input manifest · what the lenses actually read"
      questions={["Q7"]}
      basis="REAL"
      source={
        <>
          /api/gold/state inputs_used · observation {obsDate}, computed{" "}
          {computedAt} · declared inputs and their per-series provenance, read
          and unread alike
        </>
      }
    >
      <div className="big num" data-testid="gold-manifest-coverage">
        {read.length} read of {entries.length} declared
        {coverage !== null && <small> = {coverage}% coverage</small>}
      </div>

      <p className="read">
        Every gold reading on this tab is produced from {read.length} inputs.
        {omitted.length > 0 && (
          <>
            {" "}
            {omitted.length} more {omitted.length === 1 ? "was" : "were"}{" "}
            declared and not read, named below with the reason rather than
            letting the output look complete.
            {gaps.length === 0 ? (
              <> None of them is a pipeline gap.</>
            ) : (
              <>
                {" "}
                <b>
                  {gaps.length} of the {omitted.length}{" "}
                  {gaps.length === 1 ? "is" : "are"} a gap
                </b>
                ; the rest are recorded scope decisions.
              </>
            )}
          </>
        )}
      </p>

      {stale.length > 0 && (
        <div className="tbl-wrap">
          <table data-testid="gold-manifest-stale">
            <caption style={{ textAlign: "left" }}>
              <span className="cap">
                Read, and older than {STALE_AFTER_DAYS}d at this observation
              </span>
            </caption>
            <thead>
              <tr>
                <th>Input</th>
                <th>Obs</th>
                <th className="num">Age</th>
              </tr>
            </thead>
            <tbody>
              {stale.map(({ sid, prov, age }) => (
                <tr key={sid}>
                  <td>
                    {sid}
                    {prov.lens && prov.lens.length > 0 && (
                      <> [{prov.lens.join("/")}]</>
                    )}
                  </td>
                  <td>{prov.obs_date}</td>
                  <td className="num">~{age}d</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* The two omission lists are kept APART and styled apart, because they are
          different facts: a required input that was not read is a pipeline gap, and an
          optional one is a scope decision somebody made on purpose. One merged list would
          let the first hide inside the second. */}
      {gaps.length > 0 && (
        <ul className="tight" data-testid="gold-manifest-gaps">
          {gaps.map(([sid, prov]) => (
            <li key={sid}>
              <b style={{ color: "var(--negative)" }}>{sid} · required</b>
              {prov.omission_reason && <> — {prov.omission_reason}</>}
            </li>
          ))}
        </ul>
      )}

      {decisions.length > 0 && (
        <ul
          className="tight"
          data-testid="gold-manifest-decisions"
          style={{ color: "var(--text-muted)" }}
        >
          {decisions.map(([sid, prov]) => (
            <li key={sid}>
              {sid}
              {prov.lens && prov.lens.length > 0 && (
                <> [{prov.lens.join("/")}]</>
              )}{" "}
              · not read
              {prov.omission_reason && <> — {prov.omission_reason}</>}
            </li>
          ))}
        </ul>
      )}

      <p className="cap">
        Lens heuristics · v1 · obs {obsDate} · computed {computedAt}
      </p>
    </BoardPanel>
  );
}
