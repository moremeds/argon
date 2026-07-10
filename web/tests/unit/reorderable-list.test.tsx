/* @vitest-environment jsdom */
import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ReorderableList,
  reconcileOrder,
} from "@/components/stock/panels/ReorderableList";

function installLocalStorage() {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  });
}

describe("reconcileOrder", () => {
  it("keeps the stored order when the id set is unchanged", () => {
    expect(reconcileOrder(["c", "a", "b"], ["a", "b", "c"])).toEqual([
      "c",
      "a",
      "b",
    ]);
  });

  it("drops ids that no longer exist and appends new ones in default order", () => {
    // 'x' was removed (e.g. Trend Reliability panel); 'c' is new.
    expect(reconcileOrder(["b", "x", "a"], ["a", "b", "c"])).toEqual([
      "b",
      "a",
      "c",
    ]);
  });

  it("falls back to the default order when nothing is stored", () => {
    expect(reconcileOrder([], ["a", "b"])).toEqual(["a", "b"]);
  });
});

const KEY = "test:order";
const items = [
  { id: "a", node: <div>ALPHA</div> },
  { id: "b", node: <div>BETA</div> },
  { id: "c", node: <div>GAMMA</div> },
];

describe("ReorderableList — drag and drop", () => {
  beforeEach(() => installLocalStorage());

  it("renders items in default order initially", () => {
    const { getAllByText } = render(
      <ReorderableList items={items} storageKey={KEY} />,
    );
    const texts = getAllByText(/ALPHA|BETA|GAMMA/).map((n) => n.textContent);
    expect(texts).toEqual(["ALPHA", "BETA", "GAMMA"]);
  });

  it("reorders on drop and persists to localStorage", () => {
    const { getAllByText, getAllByTitle } = render(
      <ReorderableList items={items} storageKey={KEY} />,
    );
    const handles = getAllByTitle(/drag to reorder/i);
    const rows = getAllByText(/ALPHA|BETA|GAMMA/).map(
      (n) => n.closest("[data-reorder-id]") as HTMLElement,
    );
    // drag 'a' (handle 0) onto 'c' (row 2)
    fireEvent.dragStart(handles[0]);
    fireEvent.dragOver(rows[2]);
    fireEvent.drop(rows[2]);

    const after = getAllByText(/ALPHA|BETA|GAMMA/).map((n) => n.textContent);
    expect(after).toEqual(["BETA", "GAMMA", "ALPHA"]);
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual(["b", "c", "a"]);
  });
});
