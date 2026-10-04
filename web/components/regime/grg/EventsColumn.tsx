"use client";

import { type GrgEvent } from "@/lib/regime/useGrgLive";
import { EventRow } from "./EventRow";

export function EventsColumn({
  title,
  testid,
  events,
  emptyCopy,
}: {
  title: string;
  testid: string;
  events: GrgEvent[];
  emptyCopy: string;
}) {
  return (
    <div className="section" data-testid={testid}>
      <div className="section-header">
        <div className="section-title">{title}</div>
      </div>
      <div className="section-body" style={{ padding: 12 }}>
        {events.length === 0 ? (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-muted)",
            }}
          >
            {emptyCopy}
          </div>
        ) : (
          events.slice(0, 5).map((ev) => <EventRow key={ev.date} ev={ev} />)
        )}
      </div>
    </div>
  );
}
