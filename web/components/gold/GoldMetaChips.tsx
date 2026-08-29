import type { components } from "@/lib/types";

type State = components["schemas"]["GoldStateResponse"];

/**
 * The board's `.mast-meta` chip row for tab 05.
 *
 * ### Why this exists at all
 *
 * The board's t5 has no KPI strip — the tab opens straight onto the transmission gauge —
 * and the five-tile strip this replaces gave a spot price, a correlation number, a regime
 * badge, a lens summary and a freshness roll-up all the same weight as each other. Three
 * of those five are now stated properly elsewhere and with more context: the correlation
 * and the regime are the gauge panel's whole subject, and the lens summary is the
 * three-lens panel.
 *
 * Two were not, and dropping them to match the board's layout would have been losing
 * published data to win a layout. So the spot level and the feed health become chips —
 * the board's own idiom for a fact a tab is read AGAINST rather than a fact it is about.
 *
 * ### The freshness chip counts, it does not average
 *
 * `data_freshness` is one row per source with its own status. A single "fresh"/"stale"
 * word over the set would be a roll-up nobody published, and it would hide the case that
 * actually matters: most feeds healthy with one missing. So the chip names the count and
 * the worst status, and the manifest panel at the foot of the tab lists which.
 */
export function GoldMetaChips({ state }: { state: State }) {
  const last = Number(state.spot?.last);
  const deltaPct = Number(state.spot?.delta_pct);
  const sources = state.data_freshness ?? [];
  const notOk = sources.filter((s) => s.status !== "ok");

  return (
    <span className="mast-meta" data-testid="gold-meta-chips">
      {Number.isFinite(last) ? (
        <span className="chip gold" data-testid="gold-chip-spot">
          spot {last.toFixed(2)}
          {Number.isFinite(deltaPct) ? (
            <span
              className={
                deltaPct > 0
                  ? "delta-up"
                  : deltaPct < 0
                    ? "delta-dn"
                    : "delta-flat"
              }
            >
              {deltaPct > 0 ? "+" : deltaPct < 0 ? "−" : ""}
              {Math.abs(deltaPct * 100).toFixed(2)}%
            </span>
          ) : null}
        </span>
      ) : (
        <span className="chip" data-testid="gold-chip-spot">
          spot — not captured for this observation
        </span>
      )}

      {sources.length > 0 ? (
        <span
          className={notOk.length === 0 ? "chip ok" : "chip warn"}
          data-testid="gold-chip-freshness"
        >
          <span className="dot" />
          {sources.length - notOk.length}/{sources.length} feeds ok
          {notOk.length > 0 ? ` · ${notOk.map((s) => s.id).join(", ")}` : ""}
        </span>
      ) : null}
    </span>
  );
}
