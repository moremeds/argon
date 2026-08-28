import { ConfidenceArithmetic } from "./ConfidenceArithmetic";
import { confidencePct } from "./format";
import type { MacroDomainKey, MacroDomainSlot } from "./types";
import { DOMAIN_LABEL, DOMAIN_LEDE } from "./types";

const LABEL: React.CSSProperties = {
  fontFamily: "var(--font-mono), monospace",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const FRESHNESS_COLOR: Record<string, string> = {
  fresh: "var(--positive)",
  aging: "var(--warning)",
  stale: "var(--negative)",
};

/**
 * One domain, with what it stood on.
 *
 * Deliberately shows the confidence TERMS rather than only the number.  A bare 0.40 reads
 * as an opinion held weakly; "2/5 load-bearing inputs present" says which input to go fix.
 */
export function DomainStateCard({
  domain,
  slot,
}: {
  domain: MacroDomainKey;
  slot: MacroDomainSlot;
}) {
  const raw = slot.value;
  // Pydantic defaults these to empty lists, so OpenAPI marks them optional and the
  // generated type is `T[] | undefined`. Normalise once here rather than guarding at
  // every use site -- an absent list and an empty one mean the same thing to the reader.
  const s = raw
    ? {
        ...raw,
        velocity: raw.velocity ?? [],
        confidence_reasons: raw.confidence_reasons ?? [],
        contradictions: raw.contradictions ?? [],
        factors: raw.factors ?? [],
        evidence: raw.evidence ?? [],
        notes: raw.notes ?? [],
        upstream: raw.upstream ?? [],
      }
    : null;
  return (
    <section
      data-testid={`macro-domain-${domain}`}
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
        padding: "16px 18px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={LABEL}>{DOMAIN_LABEL[domain]}</div>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
            {DOMAIN_LEDE[domain]}
          </p>
        </div>
        {s ? (
          <div style={{ ...LABEL, textAlign: "right", whiteSpace: "nowrap" }}>
            {s.engine_version}
          </div>
        ) : null}
      </div>

      {!s ? (
        <p
          style={{
            margin: "14px 0 0",
            fontSize: 13,
            color: slot.error ? "var(--negative)" : "var(--text-muted)",
          }}
        >
          {slot.error
            ? slot.error
            : "No state has been computed for this domain yet — the engine has not run, which is not the same as the request failing."}
        </p>
      ) : (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 14,
              margin: "14px 0 0",
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono), monospace",
                fontSize: 22,
                fontWeight: 700,
                color: "var(--text-primary)",
              }}
            >
              {s.state}
            </span>
            <span style={{ ...LABEL, fontSize: 11 }}>{s.direction}</span>
            <span
              style={{
                ...LABEL,
                fontSize: 11,
                color: FRESHNESS_COLOR[s.freshness] ?? "var(--text-muted)",
              }}
            >
              {s.freshness} · {Math.round(s.age_hours)}h
            </span>
            <span style={{ ...LABEL, fontSize: 11 }}>
              confidence {confidencePct(s.confidence)}
            </span>
          </div>

          {/* The confidence ARITHMETIC, under the number it explains rather than folded
              into the disclosure below. This card used to list every term raw inside
              "what this stood on" -- `term value — detail`, with no way to tell whether a
              value dragged: 1.00 is neutral for a multiplicand and total for a penalty,
              and an informational term is not in the product at all. That is the reading
              §4.1 of the port plan records the rates page getting wrong on screen. The
              strip sorts by `kind` and is shared by all four domains (P5's lift). */}
          <div style={{ marginTop: 10 }}>
            <ConfidenceArithmetic
              reasons={s.confidence_reasons}
              testId={`macro-confidence-${domain}`}
            />
          </div>

          {s.velocity.length > 0 ? (
            <div style={{ marginTop: 10, display: "grid", gap: 3 }}>
              {s.velocity.map((v) => (
                <div key={v.metric} style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  <span style={LABEL}>{v.metric.replace(/_/g, " ")}</span>{" "}
                  {v.value === null || v.value === undefined ? (
                    <span style={{ color: "var(--text-muted)" }}>
                      {v.unavailable_reason ?? "unavailable"}
                    </span>
                  ) : (
                    <span style={{ fontFamily: "var(--font-mono), monospace" }}>
                      {Number(v.value).toFixed(2)} {v.unit} / {v.window_months}mo
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : null}

          {s.contradictions.length > 0 ? (
            <ul
              data-testid="macro-contradictions"
              style={{
                margin: "12px 0 0",
                padding: "8px 10px 8px 26px",
                background: "var(--bg-panel-raised)",
                borderLeft: "2px solid var(--warning)",
                borderRadius: 3,
                display: "grid",
                gap: 4,
              }}
            >
              {s.contradictions.map((c) => (
                <li key={c.rule} style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  {c.detail}
                </li>
              ))}
            </ul>
          ) : null}

          {s.upstream.length > 0 ? (
            <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-secondary)" }}>
              <span style={LABEL}>consumes</span>{" "}
              {s.upstream
                .map((u) => `${u.domain} = ${u.state} (${u.direction})`)
                .join(" · ")}
            </div>
          ) : null}

          <div style={{ marginTop: 12, display: "flex", gap: 16, flexWrap: "wrap" }}>
            <span data-testid="macro-evidence-count" style={LABEL}>
              {s.evidence.length} evidence rows cited
            </span>
            <span style={LABEL}>as of {s.as_of.slice(0, 10)}</span>
          </div>

          <details style={{ marginTop: 10 }}>
            <summary style={{ ...LABEL, cursor: "pointer" }}>
              what this stood on
            </summary>
            <div style={{ marginTop: 8, display: "grid", gap: 10 }}>
              {s.factors.length > 0 ? (
                <div style={{ display: "grid", gap: 3 }}>
                  {s.factors.map((f) => (
                    <div
                      key={`${f.name}-${f.series_id}`}
                      style={{ fontSize: 12, color: "var(--text-secondary)" }}
                    >
                      <span style={{ fontFamily: "var(--font-mono), monospace" }}>
                        {f.series_id}
                      </span>{" "}
                      {f.value} {f.unit} · {f.period_end} · {f.age_days}d ·{" "}
                      {f.source} ({f.quality_status})
                    </div>
                  ))}
                </div>
              ) : null}
              {/* The confidence terms are NOT repeated here. They moved up beside the
                  confidence number, where `ConfidenceArithmetic` renders them by `kind`;
                  printing the same terms twice, once sorted and once raw, would put the
                  misreading this card is fixing back on the same page. */}
              {s.notes.length > 0 ? (
                <div style={{ display: "grid", gap: 3 }}>
                  {s.notes.map((n) => (
                    <div key={n} style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      {n}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </details>
        </>
      )}
    </section>
  );
}
