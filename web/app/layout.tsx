import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/700.css";
import "./globals.css";
import { AppShell } from "@/components/shared/AppShell";

export const metadata = {
  title: "Argon",
  description: "Per-ticker options analytics, watchlist-driven",
  icons: { icon: "/rates-icon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-theme="dark">
      <body
        style={{
          fontFamily: "var(--font-sans)",
          margin: 0,
          overflow: "hidden",
        }}
      >
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
