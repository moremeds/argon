import { Sparkline } from "./Sparkline";
import { fmtPct } from "@/lib/formatters";

type Props = {
  closes: number[];
  ret_1d: number | null | undefined;
  ret_1w: number | null | undefined;
  ret_30d: number | null | undefined;
};

function chip(label: string, value: number | null | undefined) {
  const color =
    value == null
      ? "var(--text-muted)"
      : value >= 0
        ? "var(--positive)"
        : "var(--negative)";
  return (
    <span
      style={{
        fontSize: 10,
        fontFamily: "var(--font-mono)",
        color,
        marginRight: 8,
      }}
    >
      {label} {fmtPct(value ?? null)}
    </span>
  );
}

export function SparklineRow(p: Props) {
  return (
    <div>
      <Sparkline values={p.closes} />
      <div style={{ marginTop: 4 }}>
        {chip("1d", p.ret_1d)}
        {chip("1w", p.ret_1w)}
        {chip("30d", p.ret_30d)}
      </div>
    </div>
  );
}
