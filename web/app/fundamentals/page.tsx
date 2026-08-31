import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

/**
 * The index is a redirect, not a landing page, because there is exactly one
 * section. A chooser listing a single choice is a page that exists to be
 * clicked through, and it would imply siblings that do not exist — the desk
 * would look like it covers a universe it does not.
 *
 * When a second section is registered (a `SECTIONS` row on the API side), this
 * becomes a real index and the redirect goes. Until then the honest shape of
 * "/fundamentals" is "the AI/semi desk".
 */
export default async function FundamentalsIndex(): Promise<never> {
  redirect("/fundamentals/ai-semi");
}
