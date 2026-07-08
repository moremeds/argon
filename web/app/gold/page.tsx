import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import type { components } from "@/lib/types";

type State = components["schemas"]["GoldStateResponse"];

async function fetchGoldState(): Promise<State | null> {
  // Runtime NEXT_INTERNAL_API_BASE (not build-inlined): `http://api:8400` in
  // Docker, unset → localhost under launchd. See docker spec code change #7.
  const base = process.env.NEXT_INTERNAL_API_BASE ?? "http://127.0.0.1:8400";
  try {
    const res = await fetch(`${base}/api/gold/state`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as State;
  } catch {
    return null;
  }
}

export default async function GoldPage() {
  const state = await fetchGoldState();
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
        GOLD COMPASS · Posture not yet computed. First scheduled run lands at
        the next worker tick.
      </main>
    );
  }
  return <GoldCompassLayout state={state} />;
}

export const metadata = { title: "Gold Compass" };
export const dynamic = "force-dynamic";
