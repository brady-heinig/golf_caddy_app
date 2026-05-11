"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { apiFetch } from "@/lib/api";

export type ShotHistoryRow = {
  id: number;
  round_id: number | null;
  course_id: string;
  hole: number;
  shot_number: number;
  club: string;
  distance_to_pin_before: number | null;
  distance_achieved: number | null;
  lie: string | null;
  shot_shape: string | null;
  result: string | null;
  notes: string | null;
  proximity_ft: number | null;
  logged_at: string;
  recommended_club: string | null;
  advised_plays_like_yd: number | null;
  feedback_transcript: string | null;
};

function clip(s: string | null | undefined, n: number): string {
  if (s == null || !String(s).trim()) return "—";
  const t = String(s).trim();
  return t.length <= n ? t : `${t.slice(0, n - 1)}…`;
}

function formatWhen(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (!Number.isFinite(d.getTime())) return iso.slice(0, 16);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function roundIdFromSearchParams(sp: URLSearchParams): number | null {
  const raw = sp.get("round");
  const n = raw != null ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n > 0 ? n : null;
}

function ShotHistoryInner() {
  const searchParams = useSearchParams();
  const filterRoundId = useMemo(() => roundIdFromSearchParams(searchParams), [searchParams]);

  const [rows, setRows] = useState<ShotHistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setError(null);
      setLoading(true);
      try {
        const q =
          filterRoundId != null
            ? `/api/me/shots?limit=300&round_id=${filterRoundId}`
            : "/api/me/shots?limit=300";
        const data = (await apiFetch(q)) as ShotHistoryRow[];
        if (!cancelled) setRows(Array.isArray(data) ? data : []);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load shots");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filterRoundId]);

  return (
    <main style={{ margin: 0, background: "#ffffff", color: "#0b1220" }}>
      <h1 style={{ marginTop: 0 }}>Shot history</h1>
      {filterRoundId != null ? (
        <p style={{ marginTop: 8 }}>
          Showing shots for{" "}
          <Link href={`/rounds/${filterRoundId}`} style={{ fontWeight: 700 }}>
            round #{filterRoundId}
          </Link>
          {" · "}
          <Link href="/rounds/shot-history">Clear filter</Link>
        </p>
      ) : null}

      {error ? (
        <p style={{ color: "crimson" }}>{error}</p>
      ) : null}
      {loading ? (
        <p style={{ opacity: 0.8 }}>Loading…</p>
      ) : rows.length === 0 ? (
        <p style={{ opacity: 0.8 }}>No shots logged yet.</p>
      ) : (
        <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch", marginTop: 12 }}>
          <table
            style={{
              borderCollapse: "collapse",
              width: "100%",
              fontSize: 13,
              minWidth: 800,
              background: "#fff",
              color: "#0b1220",
            }}
          >
            <thead>
              <tr style={{ borderBottom: "2px solid rgba(11,18,32,0.15)", textAlign: "left" }}>
                <th style={{ padding: "10px 8px", whiteSpace: "nowrap" }}>When</th>
                <th style={{ padding: "10px 8px" }}>Round</th>
                <th style={{ padding: "10px 8px" }}>Course</th>
                <th style={{ padding: "10px 8px" }}>Hole</th>
                <th style={{ padding: "10px 8px" }}>Club</th>
                <th style={{ padding: "10px 8px" }} title="Suggested club from prior caddie context">Prior pick</th>
                <th style={{ padding: "10px 8px" }}>Plays-like (yd)</th>
                <th style={{ padding: "10px 8px" }}>Carry / result</th>
                <th style={{ padding: "10px 8px", minWidth: 160 }}>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const detail =
                  clip(r.feedback_transcript ?? r.result ?? r.notes, 120);
                const carryAch =
                  r.distance_achieved != null ? `${r.distance_achieved}` : "—";
                const outcome = clip(r.result, 40);
                return (
                  <tr key={r.id} style={{ borderBottom: "1px solid rgba(11,18,32,0.08)", verticalAlign: "top" }}>
                    <td style={{ padding: "10px 8px", whiteSpace: "nowrap" }}>{formatWhen(r.logged_at)}</td>
                    <td style={{ padding: "10px 8px", whiteSpace: "nowrap" }}>
                      {r.round_id != null ? (
                        <Link href={`/rounds/${r.round_id}`}>#{r.round_id}</Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={{ padding: "10px 8px", wordBreak: "break-word" }}>{r.course_id}</td>
                    <td style={{ padding: "10px 8px" }}>{r.hole}</td>
                    <td style={{ padding: "10px 8px" }}>{r.club}</td>
                    <td style={{ padding: "10px 8px" }}>{clip(r.recommended_club ?? "—", 16)}</td>
                    <td style={{ padding: "10px 8px", whiteSpace: "nowrap" }}>
                      {r.advised_plays_like_yd != null
                        ? Math.round(Number(r.advised_plays_like_yd))
                        : r.distance_to_pin_before != null
                          ? Math.round(Number(r.distance_to_pin_before))
                          : "—"}
                    </td>
                    <td
                      style={{ padding: "10px 8px" }}
                      title={carryAch !== "—" || outcome !== "—" ? `${carryAch} · ${outcome}` : undefined}
                    >
                      {carryAch !== "—" ? `${carryAch} yd` : "—"}
                      {outcome !== "—" ? ` · ${outcome}` : ""}
                    </td>
                    <td style={{ padding: "10px 8px", opacity: 0.88 }} title={r.feedback_transcript ?? r.notes ?? undefined}>
                      {detail}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

export default function ShotHistoryPage() {
  return (
    <Suspense
      fallback={
        <main style={{ margin: 0, background: "#ffffff", color: "#0b1220" }}>
          <h1 style={{ marginTop: 0 }}>Shot history</h1>
          <p style={{ opacity: 0.8 }}>Loading…</p>
        </main>
      }
    >
      <ShotHistoryInner />
    </Suspense>
  );
}
