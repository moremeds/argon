export function DataTable<T extends Record<string, unknown>>({
  rows,
  columns,
}: {
  rows: T[];
  columns: {
    key: keyof T;
    label: string;
    render?: (v: T[keyof T], row: T) => React.ReactNode;
  }[];
}) {
  if (rows.length === 0)
    return (
      <div style={{ color: "var(--text-muted)", fontSize: 12 }}>No rows.</div>
    );
  return (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
      }}
    >
      <thead>
        <tr>
          {columns.map((c) => (
            <th
              key={String(c.key)}
              style={{
                textAlign: "left",
                padding: "4px 8px",
                color: "var(--text-muted)",
                borderBottom: "1px solid var(--border-dim)",
              }}
            >
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} style={{ borderBottom: "1px solid var(--border-dim)" }}>
            {columns.map((c) => (
              <td key={String(c.key)} style={{ padding: "4px 8px" }}>
                {c.render ? c.render(r[c.key], r) : String(r[c.key] ?? "—")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
