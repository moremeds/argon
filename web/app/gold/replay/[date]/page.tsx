import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import type { components } from "@/lib/types";

type State = components["schemas"]["GoldStateResponse"];

async function fetchReplay(date: string): Promise<State | null> {
  const base = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8400";
  try {
    const res = await fetch(`${base}/api/gold/replay?as_of=${date}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as State;
  } catch {
    return null;
  }
}

type Params = { date: string };

export default async function GoldReplayPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { date } = await params;
  const state = await fetchReplay(date);
  if (!state) {
    return (
      <main
        style={{
          padding: 32,
          color: "var(--text-muted, #6b7280)",
          background: "var(--bg-base, #060810)",
          minHeight: "100vh",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          letterSpacing: 1.5,
          textTransform: "uppercase",
        }}
      >
        GOLD COMPASS REPLAY · no posture row for {date}
      </main>
    );
  }
  return <GoldCompassLayout state={state} replayDate={date} />;
}

export const metadata = { title: "Gold Compass · Replay" };
export const dynamic = "force-dynamic";
