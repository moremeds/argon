"use client";

import { usePathname, useSearchParams } from "next/navigation";

import { ReplayControl } from "./ReplayControl";
import { parseReplayRequest } from "./replay";
import { VALID_TABS, macroTabHref } from "./tabs";

export function MacroReplayMenu({
  liveAsOfLabel,
  today,
}: {
  liveAsOfLabel: string;
  today: string;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const values = params.getAll("as_of");
  const request = parseReplayRequest(
    values.length === 0 ? undefined : values.length === 1 ? values[0] : values,
  );
  const slug = pathname.split("/")[2] ?? "overview";
  const entry = VALID_TABS.find((candidate) => candidate.slug === slug);
  const display = request.kind === "replay" ? request.asOf : liveAsOfLabel;

  if (!entry || entry.replayClock === "none") {
    return (
      <span className="chip">
        as_of <span className="num">{display}</span>
      </span>
    );
  }

  return (
    <details
      className="macro-replay-menu"
      data-testid="macro-replay-menu"
      open={request.kind === "rejected"}
    >
      <summary className="chip">
        as_of <span className="num">{display}</span>
      </summary>
      <div className="macro-replay-popover">
        <ReplayControl
          request={request}
          clock={entry.replayClock}
          tabHref={macroTabHref(entry.slug)}
          today={today}
        />
      </div>
    </details>
  );
}
