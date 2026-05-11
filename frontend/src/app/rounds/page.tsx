"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { parseScorecardPlayers, primaryStrokeTotals } from "@/lib/scorecardRound";

type Round = {
  id: number;
  course_id: string;
  status: string;
  current_hole: number;
  started_at: string;
  updated_at: string;
  scorecard_json?: string | null;
};

export default function RoundsPage() {
  const [courseId, setCourseId] = useState("stevens_golf_course");
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<Round[]>([]);
  const [finished, setFinished] = useState<Round[]>([]);
  const [loading, setLoading] = useState(true);

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

  async function startRound() {
    setError(null);
    try {
      const r = (await apiFetch("/api/rounds", {
        method: "POST",
        body: JSON.stringify({ course_id: courseId })
      })) as Round;
      window.location.href = `/rounds/${r.id}`;
    } catch (e: any) {
      setError(e?.message || "Failed to start round");
    }
  }

  async function finishRound(id: number) {
    setError(null);
    try {
      await apiFetch(`/api/rounds/${id}/finish`, { method: "POST" });
      await refresh();
    } catch (e: any) {
      setError(e?.message || "Failed to finish round");
    }
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

  return (
    <main style={{ margin: 0 }}>
      <h1 style={{ marginTop: 0 }}>Rounds</h1>
      <p style={{ opacity: 0.8 }}>
        Start a round, exit anytime, and resume later. Current hole, scorecard, and mapped shot history are stored per round.
      </p>

      <section style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <label>
          Course ID{" "}
          <input
            value={courseId}
            onChange={(e) => setCourseId(e.target.value)}
            style={{ padding: 10, width: 220 }}
          />
        </label>
        <button onClick={startRound} style={{ padding: 12 }}>
          Start new round
        </button>
        <Link href="/settings">Settings</Link>
        <Link href="/caddie">Map / caddie</Link>
      </section>

      {error ? <p style={{ color: "crimson" }}>{error}</p> : null}
      {loading ? <p>Loading…</p> : null}

      <h2>Active</h2>
      {active.length === 0 ? <p style={{ opacity: 0.8 }}>No active rounds.</p> : null}
      <ul style={{ paddingLeft: 18 }}>
        {active.map((r) => (
          <li key={r.id} style={{ marginBottom: 8 }}>
            <Link href={`/caddie?round=${r.id}`} style={{ fontWeight: 800 }}>
              Continue round #{r.id}
            </Link>
            <span style={{ opacity: 0.85 }}>
              {" "}
              — {r.course_id} — hole {r.current_hole}
              {(() => {
                const t = primaryStrokeTotals(parseScorecardPlayers(r.scorecard_json ?? null));
                return t ? ` — ${t.strokes} st / ${t.holesPlayed} holes` : "";
              })()}
            </span>
            {" · "}
            <Link href={`/rounds/${r.id}`} style={{ fontSize: 14 }}>
              Chat & details
            </Link>
            {" · "}
            <Link href={`/rounds/shot-history?round=${r.id}`} style={{ fontSize: 14 }}>
              Shots
            </Link>
            <button onClick={() => finishRound(r.id)} style={{ marginLeft: 10 }}>
              Finish
            </button>
            <button onClick={() => deleteRound(r.id)} style={{ marginLeft: 8 }}>
              Delete
            </button>
          </li>
        ))}
      </ul>

      <h2>Finished</h2>
      {finished.length === 0 ? <p style={{ opacity: 0.8 }}>No finished rounds.</p> : null}
      <ul style={{ paddingLeft: 18 }}>
        {finished.map((r) => (
          <li key={r.id} style={{ marginBottom: 8 }}>
            <Link href={`/rounds/${r.id}`}>Round #{r.id}</Link> — {r.course_id}
            {(() => {
              const t = primaryStrokeTotals(parseScorecardPlayers(r.scorecard_json ?? null));
              return t ? (
                <span style={{ opacity: 0.85 }}>
                  {" "}
                  — {t.strokes} st / {t.holesPlayed} holes
                </span>
              ) : null;
            })()}
            {" · "}
            <Link href={`/rounds/shot-history?round=${r.id}`} style={{ fontSize: 14 }}>
              Shots
            </Link>
            <button onClick={() => deleteRound(r.id)} style={{ marginLeft: 8 }}>
              Delete
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}

