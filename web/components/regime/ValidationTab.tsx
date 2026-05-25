"use client";

import { useEffect, useRef, useState } from "react";

import type { components } from "@/lib/types";
import { regimeApi } from "@/lib/regime/api";

import CriValidationPanel from "./CriValidationPanel";
import VcgValidationPanel from "./VcgValidationPanel";

type CriResp = components["schemas"]["ValidationResponse"];
type VcgResp = components["schemas"]["VcgValidationResponse"];
type SubTab = "cri" | "vcg";

export default function ValidationTab() {
  const [sub, setSub] = useState<SubTab>("cri");
  const [cri, setCri] = useState<CriResp | null>(null);
  const [vcg, setVcg] = useState<VcgResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Request-token defends against rapid CRI->VCG->CRI clicks landing responses
  // out of order. The `cancelled` flag handles unmount; the token handles
  // re-entry while mounted.
  const reqToken = useRef(0);

  const selectSub = (next: SubTab) => {
    setErr(null);
    setSub(next);
  };

  useEffect(() => {
    let cancelled = false;
    const token = ++reqToken.current;
    const url =
      sub === "cri" ? regimeApi.validation() : regimeApi.vcgValidation();
    fetch(url)
      .then(async (r) => {
        if (r.ok) return r.json();
        // Surface the API detail string when available — better UX than
        // "HTTP 503". The detail message points operators at the right
        // script (e.g. "run scripts/backtest_vcg.py ...").
        const body = await r.json().catch(() => null);
        const detail =
          body && typeof body.detail === "string"
            ? body.detail
            : `HTTP ${r.status}`;
        throw new Error(detail);
      })
      .then((d) => {
        if (cancelled || token !== reqToken.current) return;
        if (sub === "cri") setCri(d);
        else setVcg(d);
      })
      .catch((e: unknown) => {
        if (cancelled || token !== reqToken.current) return;
        setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [sub]);

  const loading = (sub === "cri" && !cri) || (sub === "vcg" && !vcg);

  return (
    <div className="regime-panel" data-testid="validation-tab">
      <div
        className="ticker-tabs"
        style={{ marginBottom: 16 }}
        data-testid="validation-sub-tabs"
      >
        <button
          className={`ticker-tab ${sub === "cri" ? "active" : ""}`}
          onClick={() => selectSub("cri")}
          data-testid="validation-sub-cri"
        >
          CRI
        </button>
        <button
          className={`ticker-tab ${sub === "vcg" ? "active" : ""}`}
          onClick={() => selectSub("vcg")}
          data-testid="validation-sub-vcg"
        >
          VCG
        </button>
      </div>
      {err && (
        <div data-testid="validation-error">
          Validation data unavailable: {err}
        </div>
      )}
      {!err && loading && <div>Loading…</div>}
      {!err && !loading && sub === "cri" && cri && (
        <CriValidationPanel data={cri} />
      )}
      {!err && !loading && sub === "vcg" && vcg && (
        <VcgValidationPanel data={vcg} />
      )}
    </div>
  );
}
