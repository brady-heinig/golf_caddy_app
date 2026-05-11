"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { CaddieApp } from "@/components/CaddieApp";

function CaddieWithRoundQuery() {
  const sp = useSearchParams();
  const raw = sp.get("round");
  const n = raw != null ? Number.parseInt(raw, 10) : NaN;
  const resumeRoundId = Number.isFinite(n) && n > 0 ? n : null;
  return <CaddieApp resumeRoundId={resumeRoundId} />;
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
