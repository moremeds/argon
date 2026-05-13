import { redirect } from "next/navigation";

// Watchlist content moved to / (root). Keep /watchlist as a permanent
// redirect so existing bookmarks still land on the dashboard.
export default function WatchlistRedirect() {
  redirect("/");
}
