"use client";

import { Sidebar } from "@/components/shared/Sidebar";
import { usePathname } from "next/navigation";
import styles from "./AppShell.module.css";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isMacroDesk = pathname === "/macro" || pathname.startsWith("/macro/");

  if (isMacroDesk) {
    return (
      <div className={styles.macroShell}>
        <Sidebar />
        <main className={styles.macroMain}>{children}</main>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>{children}</main>
    </div>
  );
}
