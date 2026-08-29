export function MacroFooter({ snapshotAsOf }: { snapshotAsOf: string | null }) {
  return (
    <footer>
      <div className="wrap">
        <div>
          Data snapshot {snapshotAsOf ?? "unavailable"} · all REAL values are
          read verbatim from the currently configured Argon database through
          the current API: <code>/api/macro/&#123;inflation,rates,usd,gold,snapshot&#125;</code>
          {" · "}<code>/api/rates/snapshot</code> · <code>/api/gold/state</code>
          {" · "}source identities and series identifiers are preserved in the
          response payloads and panel provenance rails. COMPUTED values show
          their formula in place; PLANNED panels contain no fabricated data.
        </div>
        <div style={{ marginTop: 6 }}>
          Invariants: no composite (test-enforced) · four paths never averaged
          · UNKNOWN ≠ NEUTRAL · three-state empty slots · valuation never a
          sizing input · equity consumes macro factors, the reverse is
          forbidden.
        </div>
      </div>
    </footer>
  );
}
