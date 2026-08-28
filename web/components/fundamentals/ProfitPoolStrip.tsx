import type { ProfitPoolLayer } from "@/lib/api";

/**
 * Where gross profit sits, layer by layer.
 *
 * DESCRIPTIVE ONLY, AND THE ABSENCE IS THE POINT. There are no arrows between
 * these columns, no "reads through to", no propagation and no lead/lag copy —
 * not because the layout was easier that way, but because the desk has not
 * measured that a margin at one layer says anything about the next, and the
 * model carries no field that would let it. An arrow is a causal claim drawn
 * in CSS; the reader supplies the argument, the desk supplies the levels.
 *
 * A null median is an abstention and renders as one. Printing 0% for "no
 * member carries this metric" would put a whole layer at the bottom of a
 * comparison it never entered.
 */

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function Figure({
  value,
  label,
  testid,
}: {
  value: number | null;
  label: string;
  // Each figure carries its OWN id. A shared one makes `getByTestId`
  // ambiguous the moment a layer renders two of them, and the ambiguity hides
  // WHICH figure abstained — which is the only thing the abstention says.
  testid: string;
}) {
  if (value === null) {
    return (
      <div>
        <span className="text-[10px] uppercase tracking-wide text-zinc-600">
          {label}
        </span>
        <p
          data-testid={`${testid}-absent`}
          className="text-[11px] text-zinc-500"
        >
          no member carries this figure
        </p>
      </div>
    );
  }
  return (
    <div>
      <span className="text-[10px] uppercase tracking-wide text-zinc-600">
        {label}
      </span>
      <p data-testid={testid} className="tabular-nums text-sm text-zinc-100">
        {pct(value)}
      </p>
    </div>
  );
}

export function ProfitPoolStrip({
  layers,
  error,
}: {
  layers: ProfitPoolLayer[] | null;
  error?: string;
}) {
  if (error != null) {
    return (
      <section data-testid="profit-pool" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">Profit pool</h2>
        <p className="mt-2 text-xs text-red-300" role="alert">
          The profit-pool request failed: {error}
        </p>
      </section>
    );
  }
  const ordered = [...(layers ?? [])].sort(
    (a, b) => a.layer_rank - b.layer_rank,
  );
  return (
    <section data-testid="profit-pool" className="mt-6">
      <h2 className="text-sm font-semibold text-zinc-200">Profit pool</h2>
      <p className="mt-1 text-[11px] text-zinc-600">
        Layers side by side. The desk draws no connection between them: it has
        not measured one.
      </p>
      {ordered.length === 0 ? (
        <p
          data-testid="profit-pool-empty"
          className="mt-2 text-xs text-zinc-500"
        >
          No layer holds a member with a figure.
        </p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-3">
          {ordered.map((l) => (
            <div
              key={`${l.chain}-${l.layer_rank}`}
              data-testid={`profit-pool-layer-${l.layer_rank}`}
              className="min-w-40 flex-1 rounded border border-zinc-800 p-2"
            >
              <p className="font-mono text-[11px] text-zinc-300">{l.chain}</p>
              <p className="text-[10px] uppercase tracking-wide text-zinc-600">
                position {l.layer_rank}
              </p>
              <div className="mt-2 space-y-2">
                <Figure
                  value={l.median_gross_margin}
                  label="median gross margin"
                  testid="layer-margin"
                />
                <Figure
                  value={l.median_rev_yoy}
                  label="median revenue YoY"
                  testid="layer-rev-yoy"
                />
              </div>
              <p className="mt-2 font-mono text-[10px] text-zinc-600">
                {l.dots.map((d) => d.ticker).join(" ")}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
