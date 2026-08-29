import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

/** Radar now lives under the fundamentals desk as its triage tab. The route
 *  stays so old links keep resolving; the page itself moved to
 *  `app/fundamentals/radar/page.tsx` unchanged. */
export default async function RadarPage(): Promise<never> {
  redirect("/fundamentals/radar");
}
