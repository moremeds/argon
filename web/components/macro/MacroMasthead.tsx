import { MacroReplayMenu } from "./MacroReplayMenu";

type Props = {
  snapshotStatus: string;
  snapshotAsOf: string | null;
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

export function MacroMasthead({ snapshotStatus, snapshotAsOf, today }: Props) {
  const available = snapshotStatus !== "unavailable";
  const statusLabel = snapshotStatus.replaceAll("_", " ");
  return (
    <header className="appbar">
      <div className="wrap">
        <div className="appbar-inner">
          <div className="macro-title">
            <h1>Macro</h1>
            <p>Inflation → Policy → Dollar → Gold</p>
          </div>
          <div className="mast-meta">
            <span className={`chip${available ? " ok" : ""}`}>
              <span className="dot" />
              live chain {statusLabel}
            </span>
            <MacroReplayMenu
              liveAsOfLabel={formatAsOf(snapshotAsOf)}
              today={today}
            />
          </div>
        </div>
      </div>
    </header>
  );
}
