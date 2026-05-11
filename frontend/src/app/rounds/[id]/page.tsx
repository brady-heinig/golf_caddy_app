"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { HoleMap, type HoleData } from "@/components/HoleMap";
import { parseScorecardPlayers, primaryVsPar, type ScorecardPlayerRow } from "@/lib/scorecardRound";

type Round = {
  id: number;
  course_id: string;
  status: string;
  current_hole: number;
  started_at: string;
  updated_at: string;
  notes?: string | null;
  scorecard_json?: string | null;
  round_mode?: "live" | "sim" | null;
};

type ShotRow = {
  id: number;
  hole: number;
  club: string;
  logged_at: string;
  result: string | null;
  distance_achieved: number | null;
};

export default function RoundDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  const [round, setRound] = useState<Round | null>(null);
  const [distanceYd, setDistanceYd] = useState<number>(150);
  const [elevAdjYd, setElevAdjYd] = useState<number>(0);
  const [lie, setLie] = useState<string>("fairway");
  const [shape, setShape] = useState<string>("straight");
  const [chatInput, setChatInput] = useState<string>("");
  const [chat, setChat] = useState<{ role: string; content: string; created_at?: string }[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [holeData, setHoleData] = useState<HoleData | null>(null);
  const [player, setPlayer] = useState<{ lat: number; lon: number } | null>(null);
  const [hole, setHole] = useState<number>(1);
  const [notes, setNotes] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [coursePars, setCoursePars] = useState<number[]>([]);
  const [roundShots, setRoundShots] = useState<ShotRow[]>([]);

  async function load() {
    setError(null);
    try {
      const r = (await apiFetch(`/api/rounds/${id}`)) as Round;
      setRound(r);
      setHole(r.current_hole);
      setNotes(r.notes || "");
      await loadChat(r.current_hole);
      await loadHole(r.course_id, r.current_hole);
      try {
        const crs = (await apiFetch(`/api/course/${r.course_id}`)) as { holes?: { par?: number }[] };
        const pars = (crs.holes ?? []).map((h) => {
          const p = Number(h.par);
          return Number.isFinite(p) && p > 0 ? p : 4;
        });
        setCoursePars(pars);
      } catch {
        setCoursePars([]);
      }
      try {
        const shots = (await apiFetch(`/api/me/shots?round_id=${id}&limit=200`)) as ShotRow[];
        setRoundShots(Array.isArray(shots) ? shots : []);
      } catch {
        setRoundShots([]);
      }
      tryGpsOnce();
    } catch (e: any) {
      setError(e?.message || "Failed to load round");
    }
  }

  async function loadHole(courseId: string, holeNum: number) {
    try {
      const resp = (await apiFetch(`/api/course/${courseId}/hole/${holeNum}`)) as any;
      setHoleData(resp.hole as HoleData);
    } catch {
      setHoleData(null);
    }
  }

  function tryGpsOnce() {
    if (typeof navigator === "undefined" || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setPlayer({ lat: pos.coords.latitude, lon: pos.coords.longitude });
      },
      () => {},
      { enableHighAccuracy: true, timeout: 6000, maximumAge: 60000 }
    );
  }

  async function loadChat(h: number) {
    try {
      const resp = (await apiFetch(`/api/rounds/${id}/chat?hole=${h}`)) as any;
      setChat(resp.messages || []);
    } catch {
      setChat([]);
    }
  }

  useEffect(() => {
    if (Number.isFinite(id)) load();
  }, [id]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const r = (await apiFetch(`/api/rounds/${id}`, {
        method: "PUT",
        body: JSON.stringify({ current_hole: hole, notes })
      })) as Round;
      setRound(r);
      await loadChat(hole);
      await loadHole(r.course_id, hole);
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function sendChat() {
    if (!chatInput.trim()) return;
    setChatBusy(true);
    setError(null);
    try {
      const body = {
        hole,
        distance_to_pin_yd: distanceYd,
        elevation_adjust_yd: elevAdjYd,
        lie,
        shot_shape: shape,
        message: chatInput
      };
      setChatInput("");
      const r = (await apiFetch(`/api/rounds/${id}/chat`, {
        method: "POST",
        body: JSON.stringify(body)
      })) as any;
      await loadChat(hole);
      if (typeof r?.assistant === "string") {
        // no-op; server already persisted, this is just for clarity
      }
    } catch (e: any) {
      setError(e?.message || "Chat failed");
    } finally {
      setChatBusy(false);
    }
  }

  async function finish() {
    setError(null);
    try {
      const r = (await apiFetch(`/api/rounds/${id}/finish`, { method: "POST" })) as Round;
      setRound(r);
    } catch (e: any) {
      setError(e?.message || "Finish failed");
    }
  }

  const scorePlayers: ScorecardPlayerRow[] | null = round ? parseScorecardPlayers(round.scorecard_json ?? null) : null;
  const vsPar =
    scorePlayers && coursePars.length ? primaryVsPar(scorePlayers, coursePars) : null;

  if (!round) {
    return (
      <main style={{ margin: 0 }}>
        <p>{error ? <span style={{ color: "crimson" }}>{error}</span> : "Loading…"}</p>
        <p>
          <Link href="/rounds">Back</Link>
        </p>
      </main>
    );
  }

  return (
    <main style={{ margin: 0 }}>
      <h1 style={{ marginTop: 0 }}>
        Round #{round.id} — {round.course_id}
      </h1>
      <p style={{ opacity: 0.8 }}>
        Status: <b>{round.status}</b> · Updated: {round.updated_at}
        {vsPar != null ? (
          <>
            {" "}
            · Score (vs par, holes scored): <b>{vsPar}</b>
          </>
        ) : null}
      </p>
      <p style={{ opacity: 0.85, marginTop: 4 }}>
        <Link
          href={`/caddie?round=${round.id}&hole=${round.current_hole}${
            round.round_mode === "live" || round.round_mode === "sim" ? `&mode=${round.round_mode}` : ""
          }`}
        >
          Open map / caddie
        </Link>
        {" · "}
        <Link href={`/rounds/shot-history?round=${round.id}`}>Shot history for this round</Link>
      </p>

      <section style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <label>
          Current hole{" "}
          <input
            type="number"
            min={1}
            max={18}
            value={hole}
            onChange={(e) => setHole(Number(e.target.value))}
            style={{ padding: 10, width: 90 }}
            disabled={round.status !== "active"}
          />
        </label>
        <button onClick={save} disabled={saving || round.status !== "active"} style={{ padding: 12 }}>
          {saving ? "Saving…" : "Save progress"}
        </button>
        <button onClick={finish} disabled={round.status !== "active"} style={{ padding: 12 }}>
          Finish round
        </button>
        <Link href="/rounds">Back to rounds</Link>
      </section>

      <section style={{ marginTop: 16 }}>
        <label style={{ display: "block" }}>
          Notes
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            style={{ width: "100%", minHeight: 90, marginTop: 8, padding: 10 }}
            disabled={round.status !== "active"}
          />
        </label>
      </section>

      {error ? <p style={{ color: "crimson" }}>{error}</p> : null}

      <hr style={{ margin: "18px 0" }} />
      <h2>Scorecard</h2>
      {scorePlayers && scorePlayers.length > 0 ? (
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          {scorePlayers.map((pl) => (
            <div key={pl.id} style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>{pl.name}</div>
              <div style={{ display: "flex", gap: 4, fontSize: 12, flexWrap: "wrap" }}>
                {pl.scores.map((sc, i) => (
                  <div
                    key={i}
                    style={{
                      width: 36,
                      textAlign: "center",
                      padding: "4px 2px",
                      border: "1px solid rgba(11,18,32,0.12)",
                      borderRadius: 4,
                    }}
                  >
                    <div style={{ opacity: 0.6, fontSize: 10 }}>{i + 1}</div>
                    <div>{typeof sc === "number" ? sc : "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p style={{ opacity: 0.8 }}>No scorecard saved for this round yet. Enter scores in the caddie app while this round is active.</p>
      )}

      <hr style={{ margin: "18px 0" }} />
      <h2>Shots (this round)</h2>
      {roundShots.length === 0 ? (
        <p style={{ opacity: 0.8 }}>No shots logged for this round.</p>
      ) : (
        <ul style={{ paddingLeft: 18, marginTop: 8 }}>
          {roundShots.map((s) => (
            <li key={s.id} style={{ marginBottom: 6 }}>
              Hole {s.hole} · {s.club}
              {s.distance_achieved != null ? ` · ~${s.distance_achieved} yd` : ""}
              {s.result ? ` · ${s.result}` : ""}
              <span style={{ opacity: 0.65, fontSize: 12, marginLeft: 8 }}>{s.logged_at?.slice(0, 16)}</span>
            </li>
          ))}
        </ul>
      )}

      <hr style={{ margin: "18px 0" }} />
      <h2>Hole map</h2>
      {holeData ? (
        <HoleMap hole={holeData} player={player} />
      ) : (
        <p style={{ opacity: 0.8 }}>Hole geometry unavailable for this course/hole.</p>
      )}

      <hr style={{ margin: "18px 0" }} />
      <h2>Talk with caddie</h2>
      <section style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <label>
            Distance (yd)
            <input
              type="number"
              min={1}
              max={500}
              value={distanceYd}
              onChange={(e) => setDistanceYd(Number(e.target.value))}
              style={{ padding: 10, width: 110, marginLeft: 8 }}
              disabled={round.status !== "active"}
            />
          </label>
          <label>
            Elev adj (yd)
            <input
              type="number"
              step={0.5}
              min={-80}
              max={80}
              value={elevAdjYd}
              onChange={(e) => setElevAdjYd(Number(e.target.value))}
              style={{ padding: 10, width: 110, marginLeft: 8 }}
              disabled={round.status !== "active"}
            />
          </label>
          <label>
            Lie
            <select
              value={lie}
              onChange={(e) => setLie(e.target.value)}
              style={{ padding: 10, marginLeft: 8 }}
              disabled={round.status !== "active"}
            >
              <option value="tee">Tee</option>
              <option value="fairway">Fairway</option>
              <option value="light_rough">Light rough</option>
              <option value="deep_rough">Deep rough</option>
              <option value="bunker">Bunker</option>
              <option value="fringe">Fringe</option>
            </select>
          </label>
          <label>
            Shape
            <select
              value={shape}
              onChange={(e) => setShape(e.target.value)}
              style={{ padding: 10, marginLeft: 8 }}
              disabled={round.status !== "active"}
            >
              <option value="straight">Straight</option>
              <option value="draw">Draw</option>
              <option value="fade">Fade</option>
            </select>
          </label>
        </div>

        <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12, minHeight: 140 }}>
          {chat.length === 0 ? (
            <p style={{ opacity: 0.8, margin: 0 }}>
              No chat yet. Ask for a club suggestion to start.
            </p>
          ) : (
            chat.map((m, i) => (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 12, opacity: 0.7 }}>{m.role}</div>
                <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
              </div>
            ))
          )}
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <input
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder="Ask the caddie…"
            style={{ flex: 1, padding: 12 }}
            disabled={chatBusy || round.status !== "active"}
            onKeyDown={(e) => {
              if (e.key === "Enter") sendChat();
            }}
          />
          <button onClick={sendChat} disabled={chatBusy || round.status !== "active"} style={{ padding: 12 }}>
            {chatBusy ? "Thinking…" : "Send"}
          </button>
        </div>
      </section>
    </main>
  );
}

