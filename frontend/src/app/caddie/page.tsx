"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { CaddieApp } from "@/components/CaddieApp";

function CaddieWithRoundQuery() {
  const sp = useSearchParams();
  const raw = sp.get("round");
  const n = raw != null ? Number.parseInt(raw, 10) : NaN;
  const resumeRoundId = Number.isFinite(n) && n > 0 ? n : null;
  const holeRaw = sp.get("hole");
  const hn = holeRaw != null ? Number.parseInt(holeRaw, 10) : NaN;
  const resumeHoleHint =
    resumeRoundId != null && Number.isFinite(hn) && hn >= 1 && hn <= 18 ? hn : null;
  const modeRaw = (sp.get("mode") || "").toLowerCase();
  const resumeModeHint =
    resumeRoundId != null && (modeRaw === "live" || modeRaw === "sim") ? (modeRaw as "live" | "sim") : null;
  return (
    <CaddieApp resumeRoundId={resumeRoundId} resumeHoleHint={resumeHoleHint} resumeModeHint={resumeModeHint} />
  );
}

export default function CaddiePage() {
  return (
    <Suspense
      fallback={
        <div className="phoneShell modePickerShell">
          <div className="modePickerCard">
            <p className="modePickerSub">Loading…</p>
          </div>
        </div>
      }
    >
      <CaddieWithRoundQuery />
    </Suspense>
  );
}
