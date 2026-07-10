"use client";

import { useState, type ReactNode } from "react";

export type ReorderItem = { id: string; node: ReactNode };

/** Merge a persisted order with the current item set: keep stored ids that
 * still exist (in their stored order), then append any new ids in default
 * order. Drops ids that no longer exist. Pure — unit-tested. */
export function reconcileOrder(stored: string[], ids: string[]): string[] {
  const known = new Set(ids);
  const kept = stored.filter((id) => known.has(id));
  const keptSet = new Set(kept);
  return [...kept, ...ids.filter((id) => !keptSet.has(id))];
}

function loadStoredOrder(storageKey: string): string[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(storageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

// ponytail: native HTML5 DnD, desktop-only; the whole row is the drag source
// (no handle — a handle column shifted every chart out of alignment with the
// KPI strip). Order persisted per-browser in localStorage. Native drag disables
// text-selection inside a row; fine for a chart stack. Add dnd-kit only if
// touch/mobile, cross-device sync, or in-panel text selection is needed.
export function ReorderableList({
  items,
  storageKey,
}: {
  items: ReorderItem[];
  storageKey: string;
}) {
  const ids = items.map((i) => i.id);
  // Lazy init reads the persisted order once. Safe: this list only ever mounts
  // client-side (the tab shows "Loading…" during SSR until data is fetched),
  // so there's no hydration mismatch and no set-state-in-effect.
  const [order, setOrder] = useState<string[]>(() =>
    loadStoredOrder(storageKey),
  );
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const persist = (next: string[]) => {
    setOrder(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      /* storage unavailable — order stays in-memory for the session */
    }
  };

  const move = (from: string, to: string) => {
    if (from === to) return;
    const cur = reconcileOrder(order, ids);
    const fi = cur.indexOf(from);
    const ti = cur.indexOf(to);
    if (fi < 0 || ti < 0) return;
    const next = [...cur];
    next.splice(fi, 1);
    next.splice(ti, 0, from);
    persist(next);
  };

  const byId = new Map(items.map((i) => [i.id, i.node]));
  const ordered = reconcileOrder(order, ids);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {ordered.map((id) => (
        <div
          key={id}
          data-reorder-id={id}
          draggable
          onDragStart={(e) => {
            setDraggingId(id);
            if (e.dataTransfer) {
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", id);
            }
          }}
          onDragEnd={() => {
            setDraggingId(null);
            setOverId(null);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            if (overId !== id) setOverId(id);
          }}
          onDrop={(e) => {
            e.preventDefault();
            if (draggingId) move(draggingId, id);
            setDraggingId(null);
            setOverId(null);
          }}
          style={{
            cursor: "grab",
            minWidth: 0,
            borderTop:
              overId === id && draggingId
                ? "2px solid var(--accent-vivid)"
                : "2px solid transparent",
            opacity: draggingId === id ? 0.5 : 1,
          }}
        >
          {byId.get(id)}
        </div>
      ))}
    </div>
  );
}
