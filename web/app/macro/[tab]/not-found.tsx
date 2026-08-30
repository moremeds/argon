/**
 * What `notFound()` in `[tab]/page.tsx` renders when a slug is not in `VALID_TABS`.
 *
 * Without this file the throw has no boundary to land on inside the desk, and the route
 * answered 200 with the loading fallback frozen on screen — a page that looks hung rather
 * than one that says the tab does not exist. That is the inverse of the failure the
 * registry was built to prevent: not a link to a route that 404s, but a route that should
 * 404 and does not.
 *
 * Deliberately distinct from `[tab]/error.tsx` and from a tab's own empty state. This desk
 * keeps three kinds of nothing apart — answered, request failed, never computed — and an
 * unregistered slug is a fourth: the tab does not exist at all. Saying "no data" here
 * would claim something about a subject the desk does not have.
 */
export default function MacroTabNotFound() {
  return (
    <main style={{ padding: "48px 32px", maxWidth: 640 }}>
      <p
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 12,
        }}
      >
        Unknown tab
      </p>
      <h1
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: "var(--text-primary)",
          marginBottom: 12,
        }}
      >
        No such macro tab.
      </h1>
      <p style={{ color: "var(--text-secondary)", lineHeight: 1.6 }}>
        This address does not name a tab on the macro desk. The tabs that exist
        are the ones in the bar above — that bar is generated from the same
        registry this page checked, so nothing it links to can be missing, and
        nothing missing can be linked.
      </p>
    </main>
  );
}
