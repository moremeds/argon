"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ReportBlock, ReportDeltaModel, ReportResponse } from "@/lib/api";

/**
 * One versioned report.
 *
 * The delta sits ABOVE the content on purpose. A reader who opens version 4
 * without first seeing what moved since version 3 is reading the same document
 * this milestone exists to replace — one that looks identical every time and
 * quietly means something different.
 */

function Manifest({ manifest }: { manifest: Record<string, unknown> }) {
  const scope = manifest.scope as Record<string, unknown> | undefined;
  return (
    <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
      {(
        [
          ["Engine", manifest.engine_version],
          ["Taxonomy", manifest.taxonomy_version],
          ["Evidence policy", manifest.evidence_policy],
          ["As of", manifest.as_of],
          ["Assembler", manifest.assembler_version],
          ["Scope", scope ? Object.values(scope).join(", ") : null],
        ] as [string, unknown][]
      ).map(([label, value]) => (
        <div key={label}>
          <dt className="text-zinc-600">{label}</dt>
          <dd className="text-zinc-300">
            {value == null ? (
              <span className="text-zinc-600">none</span>
            ) : (
              <code className="text-[11px]">{String(value)}</code>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Counts must not render as 19.0000. A fixed precision on every number makes a
 *  member count look like a measurement. */
function num(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(4);
}

function Delta({ delta }: { delta: ReportDeltaModel }) {
  if (delta.is_first_version) {
    return (
      <p className="mt-4 rounded border border-zinc-800 bg-zinc-900/40 p-3 text-xs text-zinc-500">
        First version — nothing to compare against yet.
      </p>
    );
  }
  return (
    <section className="mt-4 rounded border border-zinc-800 bg-zinc-900/40 p-3">
      <h2 className="text-xs uppercase tracking-wide text-zinc-500">
        Since the previous version
      </h2>
      <p className="mt-1 text-sm text-zinc-300">{delta.summary}</p>
      {/* Method changes are listed FIRST and apart. A composite that fell
          because the engine changed is not news about a company. */}
      {delta.manifest.length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs text-amber-300/90">
          {delta.manifest.map((m) => (
            <li key={m.field}>
              <span className="text-zinc-500">method · </span>
              {m.field}: <code>{m.before ?? "none"}</code> →{" "}
              <code>{m.after ?? "none"}</code>
            </li>
          ))}
        </ul>
      ) : null}
      {delta.moved.map((block) => (
        <div key={`${block.block_kind}-${block.title}`} className="mt-2">
          <p className="text-xs text-zinc-500">{block.title}</p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {block.changes.map((c) => (
              <li key={c.path} className="tabular-nums text-zinc-300">
                {c.path}: {num(c.before)} → {num(c.after)}
                {c.change == null ? null : (
                  <span
                    className={
                      c.change >= 0 ? "ml-2 text-emerald-400" : "ml-2 text-red-400"
                    }
                  >
                    {c.change >= 0 ? "+" : ""}
                    {num(c.change)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {delta.added.length + delta.removed.length > 0 ? (
        <p className="mt-2 text-xs text-zinc-500">
          {delta.added.map((b) => `+${b.title}`).join(", ")}
          {delta.added.length && delta.removed.length ? " · " : ""}
          {delta.removed.map((b) => `−${b.title}`).join(", ")}
        </p>
      ) : null}
    </section>
  );
}

function Payload({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <p className="text-xs text-zinc-600">none</p>;
    }
    return (
      <ul className="space-y-1">
        {value.map((row, i) => (
          <li key={i} className="text-xs text-zinc-300">
            {typeof row === "object" && row !== null
              ? Object.entries(row as Record<string, unknown>)
                  .map(([k, v]) => `${k}=${v == null ? "na" : String(v)}`)
                  .join("  ")
              : String(row)}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object" && value !== null) {
    return (
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs text-zinc-600">{k}</dt>
            <dd className="text-xs text-zinc-300">
              {v == null ? (
                // `na`, never a blank: a blank reads as zero.
                <span className="text-zinc-600">na</span>
              ) : typeof v === "object" ? (
                <Payload value={v} />
              ) : (
                String(v)
              )}
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <p className="text-xs text-zinc-300">{String(value)}</p>;
}

function Block({ block }: { block: ReportBlock }) {
  const evidence = block.evidence as Record<string, unknown>;
  const hasEvidence = Object.keys(evidence ?? {}).length > 0;
  return (
    <section className="mt-4 border-t border-zinc-900 pt-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-200">{block.title}</h2>
        {block.authority ? (
          <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
            {block.authority.replace("_", " ")}
          </span>
        ) : null}
      </div>
      <div className="mt-2">
        <Payload value={block.payload} />
      </div>
      {/* Provenance is rendered, not stored-and-hidden: a number a reader
          cannot trace is the state this program exists to leave. */}
      <p className="mt-2 text-[11px] text-zinc-600">
        {hasEvidence
          ? Object.entries(evidence)
              .map(([k, v]) => `${k}=${String(v)}`)
              .join(" · ")
          : block.derivation}
      </p>
    </section>
  );
}

export function ReportView({
  data,
  reportType,
  reportKey,
}: {
  data: ReportResponse;
  reportType: "company" | "chain";
  reportKey: string;
}) {
  const [busy, setBusy] = useState(false);

  async function assemble() {
    setBusy(true);
    try {
      await api.assembleResearchReport(reportType, reportKey);
      window.location.reload();
    } finally {
      setBusy(false);
    }
  }

  if (data.state !== "ok" || !data.report) {
    return (
      <div className="p-6 text-zinc-200">
        <h1 className="text-xl font-semibold">
          {reportType} · {reportKey}
        </h1>
        <p className="mt-2 text-sm text-zinc-500">
          {data.reason ?? `No report available (${data.state}).`}
        </p>
        <button
          type="button"
          onClick={assemble}
          disabled={busy}
          className="mt-4 rounded border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
        >
          {busy ? "Assembling…" : "Assemble report"}
        </button>
      </div>
    );
  }

  const report = data.report;
  return (
    <div className="p-6 text-zinc-200">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">{report.title}</h1>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500">
            v{report.version_no} · {report.status}
          </span>
          <button
            type="button"
            onClick={assemble}
            disabled={busy}
            className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
          >
            {busy ? "Assembling…" : "Re-assemble"}
          </button>
        </div>
      </div>
      <p className="mt-1 text-[11px] text-zinc-600">
        content hash <code>{report.content_hash.slice(0, 16)}</code>{" "}
        — an old version replays from its stored blocks, never from
        today&apos;s data.
      </p>

      <Manifest manifest={report.manifest as unknown as Record<string, unknown>} />
      {data.delta ? <Delta delta={data.delta} /> : null}

      {data.versions.length > 1 ? (
        <nav className="mt-4 flex flex-wrap gap-2 text-xs">
          {data.versions.map((v) => (
            <a
              key={v.version_no}
              href={`/reports/${reportType}/${reportKey}?version=${v.version_no}`}
              className={
                v.version_no === report.version_no
                  ? "rounded bg-zinc-800 px-2 py-1 text-zinc-200"
                  : "rounded px-2 py-1 text-zinc-500 hover:bg-zinc-900"
              }
            >
              v{v.version_no}
            </a>
          ))}
        </nav>
      ) : null}

      {report.blocks.map((b) => (
        <Block key={b.ordinal} block={b} />
      ))}
    </div>
  );
}
