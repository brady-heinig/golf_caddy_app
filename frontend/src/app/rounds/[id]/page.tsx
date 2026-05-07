"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { HoleMap, type HoleData } from "@/components/HoleMap";

type Round = {
  id: number;
  course_id: string;
  status: string;
  current_hole: number;
  started_at: string;
  updated_at: string;
  notes?: string | null;
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

  async function load() {
    setError(null);
    try {
      const r = (await apiFetch(`/api/rounds/${id}`)) as Round;
      setRound(r);
      setHole(r.current_hole);
      setNotes(r.notes || "");
      await loadChat(r.current_hole);
      await loadHole(r.course_id, r.current_hole);
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

  if (!round) {
    return (
      <main style={{ padding: 20 }}>
        <p>{error ? <span style={{ color: "crimson" }}>{error}</span> : "Loading…"}</p>
        <p>
          <Link href="/rounds">Back</Link>
        </p>
      </main>
    );
  }

  return (
    <main style={{ padding: 20, maxWidth: 860, margin: "0 auto" }}>
      <h1 style={{ marginTop: 0 }}>
        Round #{round.id} — {round.course_id}
      </h1>
      <p style={{ opacity: 0.8 }}>
        Status: <b>{round.status}</b> · Updated: {round.updated_at}
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

