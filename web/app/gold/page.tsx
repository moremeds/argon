import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import { GoldPostureNotice } from "@/components/gold/GoldPostureNotice";
import type { GoldStateResponse } from "@/lib/api";
import { api } from "@/lib/api";

/** Settled, not swallowed. The raw fetch this replaces returned `null` for a
 *  non-2xx AND for a thrown error, so the page showed the never-computed
 *  placeholder while the API was down. `api.goldState()` keeps the two apart:
 *  the router's 404 ("no gold posture computed yet") is the only outcome that
 *  reaches `value: null`; anything else lands here as an error string. */
async function settleState(): Promise<{
  value: GoldStateResponse | null;
  error?: string;
}> {
  try {
    return { value: await api.goldState() };
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return { value: null, error: `The gold posture request failed: ${detail}` };
  }
}

export default async function GoldPage() {
  const { value, error } = await settleState();

  if (error) {
    return (
      <GoldPostureNotice
        tone="failed"
        headline="Gold Compass · posture request failed"
        detail={error}
        body="The API could not be read, so whether a posture has been computed is unknown. This is a failure to reach the data, not a statement about it."
      />
    );
  }

  if (!value) {
    return (
      <GoldPostureNotice
        tone="pending"
        headline="Gold Compass · posture not yet computed"
        body="The API answered, and there is no posture row yet — the engine has not run, which is not the same as the request failing. The first scheduled run lands at the next worker tick."
      />
    );
  }

  return <GoldCompassLayout state={value} />;
}

export const metadata = { title: "Gold Compass" };
export const dynamic = "force-dynamic";
