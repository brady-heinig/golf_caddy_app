"use client";

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type Round = {
  id: number;
  course_id: string;
  status: string;
  current_hole: number;
  started_at: string;
  updated_at: string;
  scorecard_json?: string | null;
  round_mode?: "live" | "sim" | null;
};

function caddieContinueHref(r: Round): string {
  const hole = Math.min(18, Math.max(1, Math.round(Number(r.current_hole)) || 1));
  const base = `/caddie?round=${r.id}&hole=${hole}`;
  if (r.round_mode === "live" || r.round_mode === "sim") return `${base}&mode=${r.round_mode}`;
  return base;
}

export default function RoundsPage() {
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<Round[]>([]);
  const [finished, setFinished] = useState<Round[]>([]);
  const [loading, setLoading] = useState(true);
  const [courseNames, setCourseNames] = useState<Record<string, string>>({});

  async function refresh() {
    setError(null);
    setLoading(true);
    try {
      const a = (await apiFetch("/api/rounds?status_filter=active")) as Round[];
      const f = (await apiFetch("/api/rounds?status_filter=finished")) as Round[];
      setActive(a);
      setFinished(f);
    } catch (e: any) {
      setError(e?.message || "Failed to load rounds");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = (await apiFetch("/api/caddie/courses")) as { id: string; name: string }[];
        if (cancelled || !Array.isArray(list)) return;
        const m: Record<string, string> = {};
        for (const c of list) {
          if (c?.id && typeof c.name === "string") m[c.id] = c.name;
        }
        setCourseNames(m);
      } catch {
        /* keep course_id fallback */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function courseLabel(courseId: string): string {
    return courseNames[courseId] ?? courseId.replace(/_/g, " ");
  }

  async function deleteRound(id: number) {
    setError(null);
    try {
      await apiFetch(`/api/rounds/${id}`, { method: "DELETE" });
      await refresh();
    } catch (e: any) {
      setError(e?.message || "Failed to delete round");
    }
  }

  const rowStyle: CSSProperties = {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 10,
    marginBottom: 14,
    paddingBottom: 12,
    borderBottom: "1px solid rgba(11,18,32,0.1)",
  };

  const btnStyle: CSSProperties = {
    padding: "10px 16px",
    borderRadius: 10,
    border: "1px solid rgba(11,18,32,0.2)",
    background: "#f4f6f8",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 14,
    textDecoration: "none",
    color: "#0b1220",
    display: "inline-block",
  };

  const primaryBtn: CSSProperties = {
    ...btnStyle,
    background: "#16a34a",
    borderColor: "#15803d",
    color: "#fff",
  };

  const delBtn: CSSProperties = {
    ...btnStyle,
    background: "#fff",
    borderColor: "rgba(185,28,28,0.45)",
    color: "#b91c1c",
  };

  return (
    <main style={{ margin: 0 }}>
      <h1 style={{ marginTop: 0 }}>Rounds</h1>

      {error ? <p style={{ color: "crimson" }}>{error}</p> : null}
      {loading ? <p>Loading…</p> : null}

      <h2>Active</h2>
      {active.length === 0 ? <p style={{ opacity: 0.8 }}>No active rounds.</p> : null}
      <div>
        {active.map((r) => (
          <div key={r.id} style={rowStyle}>
            <div style={{ flex: "1 1 220px", minWidth: 0, fontWeight: 600 }}>
              Round #{r.id}: {courseLabel(r.course_id)} - Hole {r.current_hole}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <a href={caddieContinueHref(r)} style={primaryBtn}>
                Continue
              </a>
              <button type="button" style={delBtn} onClick={() => void deleteRound(r.id)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      <h2 style={{ marginTop: 28 }}>Finished</h2>
      {finished.length === 0 ? <p style={{ opacity: 0.8 }}>No finished rounds.</p> : null}
      <div>
        {finished.map((r) => (
          <div key={r.id} style={rowStyle}>
            <div style={{ flex: "1 1 220px", minWidth: 0, fontWeight: 600 }}>
              Round #{r.id}: {courseLabel(r.course_id)} - Hole {r.current_hole}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" style={delBtn} onClick={() => void deleteRound(r.id)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
