import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

/**
 * The chain index folds into the desk (spec §2: the `/chains` pages are raw
 * material for it, not a parallel surface).
 *
 * WHAT THIS COSTS, stated rather than buried: the page that used to live here
 * rendered a chain × LAYER matrix across every domain — 39 chains — whereas
 * the desk's matrix is chain × METRIC for one section. That whole-taxonomy
 * overview is gone with this redirect, and `ChainMatrix.tsx` is deleted in the
 * same commit rather than left unreachable. It is recoverable from git if the
 * all-domain view is wanted back as its own thing.
 *
 * The per-chain DETAIL pages are untouched: `/chains/[chain]` still resolves,
 * and it is what the desk's matrix cells link to.
 */
export default async function ChainsPage(): Promise<never> {
  redirect("/fundamentals/ai-semi");
}
