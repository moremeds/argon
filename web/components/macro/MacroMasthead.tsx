import { BoardLegend } from "./BoardLegend";
import { MacroReplayMenu } from "./MacroReplayMenu";

type Props = {
  snapshotStatus: string;
  snapshotAsOf: string | null;
  sourceLabel: string;
  today: string;
};

function formatAsOf(value: string | null): string {
  if (!value) return "unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unavailable";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")} UTC+8`;
}

export function MacroMasthead({
  snapshotStatus,
  snapshotAsOf,
  sourceLabel,
  today,
}: Props) {
  const available = snapshotStatus !== "unavailable";
  return (
    <>
      <header className="appbar">
        <div className="wrap">
          <div className="appbar-inner">
            <span className="brand">
              <span>ARGON</span> <em>—</em> MACRO
            </span>
            <div className="mast-meta">
              <span className={`chip${available ? " ok" : ""}`}>
                <span className="dot" />chain snapshot: {snapshotStatus}
              </span>
              <MacroReplayMenu
                liveAsOfLabel={formatAsOf(snapshotAsOf)}
                today={today}
              />
              <span className="chip gold">{sourceLabel}</span>
            </div>
          </div>
        </div>
      </header>
      <div className="intro">
        <div className="wrap">
          <div className="kicker">
            Macro Phase 2 Integration Proposal · Review Draft
          </div>
          <h1>
            Macro Desk{" "}
            <span className="thin">/ Fed → Inflation → USD → Gold</span>
          </h1>
          <BoardLegend />
        </div>
      </div>
    </>
  );
}
