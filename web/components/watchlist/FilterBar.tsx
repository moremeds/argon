"use client";
import { useState, type CSSProperties } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { groupForChain, type SectorGroup } from "./sectorGroups";

const SETUPS = ["All", "C-bull", "C-bear", "F-MULTI", "NEUTRAL"];

const monoLabelStyle: CSSProperties = {
  fontSize: 10,
  fontFamily: "var(--font-mono)",
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase",
  whiteSpace: "nowrap",
};

function SetupFormulaPopover() {
  const [open, setOpen] = useState(false);

  return (
    <span
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      style={{ position: "relative", display: "inline-flex" }}
    >
      <button
        type="button"
        aria-label="Setup formula explanation"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        style={{
          cursor: "help",
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
          border: "1px solid var(--border-dim)",
          borderRadius: "50%",
          width: 14,
          height: 14,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          background: "transparent",
          padding: 0,
        }}
      >
        i
      </button>
      {open && (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            top: 20,
            right: 0,
            zIndex: 20,
            width: 520,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            padding: 10,
            fontSize: 11,
            lineHeight: 1.45,
            color: "var(--text-primary)",
            boxShadow: "0 12px 30px rgba(0, 0, 0, 0.35)",
          }}
        >
          <p style={{ margin: 0 }}>
            Flow direction = sign(net call premium - net put premium).
          </p>
          <p style={{ margin: "6px 0 0 0" }}>
            net premium = net call premium - net put premium.
          </p>
          <p style={{ margin: "6px 0 0 0" }}>
            Type C requires abs(net premium) &gt;= $5M and flow imbalance &gt;=
            20%, where flow imbalance = abs(net premium) / (call premium + put
            premium).
          </p>
          <p style={{ margin: "6px 0 0 0" }}>
            F-MULTI = Type C base plus at least 2 of: GEX/OI shift, VRP anomaly,
            relative volume &gt; 1.5, or flow polarization &gt; $50M.
          </p>
          <p style={{ margin: "6px 0 0 0", color: "var(--text-secondary)" }}>
            IV rank is context for structure, not a directional veto.
          </p>
        </div>
      )}
    </span>
  );
}

export function FilterBar({
  current,
  groups,
  counts,
}: {
  current: Record<string, string | undefined>;
  // Built server-side from /api/watchlist/chains — the rail is data, not a
  // hardcoded list, so it cannot drift from uw_scan.watchlist_taxonomy.
  groups: SectorGroup[];
  counts?: Record<string, number>;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const chain = current.chain;
  const filteredGroup = groupForChain(groups, chain);
  // `null` means "follow the URL". A rail click pins the row open so you can
  // browse a layer's chains without filtering to one of them first.
  const [pinnedKey, setPinnedKey] = useState<string | null>(null);
  const openGroup =
    groups.find((g) => g.key === pinnedKey) ?? filteredGroup ?? groups[0];

  const setParam = (key: string, value: string | null) => {
    const q = new URLSearchParams(params.toString());
    if (value === null || value === "All") q.delete(key);
    else q.set(key, value);
    router.push(`${pathname}?${q.toString()}`);
  };

  const chip = (
    label: string,
    active: boolean,
    onClick: () => void,
    key?: string,
  ) => (
    <button
      key={key ?? label}
      className="wl-chip"
      data-active={active}
      onClick={onClick}
      style={{
        padding: "4px 10px",
        fontSize: 11,
        fontFamily: "var(--font-mono)",
        background: active ? "var(--accent-bg)" : "transparent",
        color: active ? "var(--accent-text)" : "var(--text-secondary)",
        border: `1px solid ${active ? "var(--accent-bg)" : "var(--border-dim)"}`,
        borderRadius: 3,
        cursor: "pointer",
        // Chain names plus a count are long enough to wrap inside the chip,
        // which doubles the chip height and defeats the fixed-height row.
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {label}
    </button>
  );

  const railButton = (
    key: string,
    label: string,
    title: string,
    holdsFilter: boolean,
    isOpen: boolean,
    onClick: () => void,
  ) => (
    <button
      key={key}
      className="wl-rail-btn"
      title={title}
      aria-pressed={holdsFilter}
      onClick={onClick}
      style={{
        padding: "6px 11px",
        fontSize: 11,
        fontFamily: "var(--font-mono)",
        letterSpacing: 1,
        textTransform: "uppercase",
        // Two independent states, two independent channels: colour says
        // "the active filter lives in here", the underline says "this is the
        // chain row you're looking at". They coincide often but not always.
        color: holdsFilter ? "var(--accent-bg)" : "var(--text-muted)",
        fontWeight: holdsFilter ? 600 : 400,
        background: "transparent",
        border: 0,
        borderBottom: `2px solid ${isOpen ? "var(--accent-bg)" : "transparent"}`,
        cursor: "pointer",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </button>
  );

  const onRailClick = (g: SectorGroup) => {
    if (g.leaf) {
      setPinnedKey(g.key);
      setParam("chain", chain === g.items[0] ? null : g.items[0]);
      return;
    }
    setPinnedKey(g.key);
  };

  if (!openGroup) return null;

  return (
    <div
      style={{
        marginBottom: 16,
        borderBottom: "1px solid var(--border-dim)",
      }}
    >
      {/* Row 1 — group rail. Fixed height regardless of how many chains exist. */}
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap" }}>
        {railButton("all", "All", "No chain filter", !chain, false, () =>
          setParam("chain", null),
        )}
        {groups.map((g, i) => {
          const prev = groups[i - 1];
          const newCluster = i === 0 || prev.cluster !== g.cluster;
          return [
            newCluster ? (
              <span
                key={`div-${g.key}`}
                aria-hidden
                style={{
                  width: 1,
                  alignSelf: "stretch",
                  margin: "6px 8px",
                  background: "var(--border-dim)",
                }}
              />
            ) : null,
            railButton(
              g.key,
              g.label,
              g.full,
              filteredGroup?.key === g.key,
              openGroup.key === g.key,
              () => onRailClick(g),
            ),
          ];
        })}
      </div>

      {/* Row 2 — chains of the open group (left) + setup (right). Setup lives
          here so the row is never empty and the bar never changes height. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          // nowrap, not wrap: chain names are long (Foundation-Model-Proxy,
          // IT-Services/Integration) and wrapping pushed Setup onto a third
          // row, which is exactly the fixed-height property this layout exists
          // to guarantee. The chain strip scrolls instead.
          flexWrap: "nowrap",
          padding: "8px 0 10px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "nowrap",
            overflowX: "auto",
            // Without minWidth:0 a flex item refuses to shrink below its
            // content width, so overflowX never engages.
            minWidth: 0,
            scrollbarWidth: "thin",
          }}
        >
          <span style={monoLabelStyle}>{openGroup.full}</span>
          {openGroup.items.map((s) =>
            chip(
              counts?.[s] ? `${s} ${counts[s]}` : s,
              chain === s,
              () => setParam("chain", chain === s ? null : s),
              s,
            ),
          )}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            // Setup never shrinks or scrolls away — the chain strip absorbs the
            // overflow instead, so this stays reachable at any width.
            flexShrink: 0,
          }}
        >
          <span
            style={{
              ...monoLabelStyle,
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            <span>Setup</span>
            <SetupFormulaPopover />
          </span>
          {SETUPS.map((s) =>
            chip(s, (current.setup ?? "All") === s, () =>
              setParam("setup", s === "All" ? null : s),
            ),
          )}
        </div>
      </div>
    </div>
  );
}
