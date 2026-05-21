"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/shared/Sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const standalone = pathname === "/rates" || pathname.startsWith("/rates/");

  if (standalone) {
    return (
      <main
        style={{
          minHeight: "100vh",
          height: "100vh",
          overflowY: "auto",
          background: "#f4f3fd",
        }}
      >
        {children}
      </main>
    );
  }

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <Sidebar />
      <main
        style={{
          flex: 1,
          minWidth: 0,
          height: "100vh",
          overflowY: "auto",
        }}
      >
        {children}
      </main>
    </div>
  );
}
