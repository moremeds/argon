import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import { GoldPostureNotice } from "@/components/gold/GoldPostureNotice";
import type { GoldStateResponse } from "@/lib/api";
import { api } from "@/lib/api";

/** Same three-state split as `/gold`: a date the engine never reconstructed
 *  404s and settles to `value: null`; an unreachable or erroring API lands as
 *  an error string. Collapsing them would let an outage read as "this date has
 *  no posture", which is a claim about history the page cannot make. */
async function settleReplay(date: string): Promise<{
  value: GoldStateResponse | null;
  error?: string;
}> {
  try {
    return { value: await api.goldReplay(date) };
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return {
      value: null,
      error: `The gold replay request for ${date} failed: ${detail}`,
    };
  }
}

type Params = { date: string };

export default async function GoldReplayPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { date } = await params;
  const { value, error } = await settleReplay(date);

  if (error) {
    return (
      <GoldPostureNotice
        tone="failed"
        headline="Gold Compass replay · posture request failed"
        detail={error}
        body="The API could not be read, so whether this date has a posture row is unknown. This is a failure to reach the data, not a statement about it."
      />
    );
  }

  if (!value) {
    return (
      <GoldPostureNotice
        tone="pending"
        headline={`Gold Compass replay · no posture row for ${date}`}
        body="The API answered, and nothing was reconstructed for this date — no posture was ever computed for it, which is not the same as the request failing."
      />
    );
  }

  return <GoldCompassLayout state={value} replayDate={date} />;
}

export const metadata = { title: "Gold Compass · Replay" };
export const dynamic = "force-dynamic";
