"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type Bag = Record<string, number>;
type ShotShapes = { driver: string; woods: string; irons: string };
type Settings = {
  handicap_index: number | null;
  bag: Bag | null;
  shot_shapes: ShotShapes | null;
};

const DEFAULT_CLUBS = [
  "Driver",
  "3W",
  "5W",
  "3i",
  "4i",
  "5i",
  "6i",
  "7i",
  "8i",
  "9i",
  "PW",
  "GW",
  "SW",
  "LW",
];

const DEFAULT_SHAPES: ShotShapes = { driver: "straight", woods: "straight", irons: "straight" };

const SHAPE_OPTIONS = [
  { value: "straight", label: "Straight" },
  { value: "draw", label: "Draw" },
  { value: "fade", label: "Fade" },
];

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [handicap, setHandicap] = useState<number>(15);
  const [bag, setBag] = useState<Bag>(() => Object.fromEntries(DEFAULT_CLUBS.map((c) => [c, 0])));
  const [shotShapes, setShotShapes] = useState<ShotShapes>({ ...DEFAULT_SHAPES });

  useEffect(() => {
    (async () => {
      setError(null);
      try {
        const s = (await apiFetch("/api/me/settings")) as Settings;
        if (typeof s.handicap_index === "number") setHandicap(s.handicap_index);
        if (s.bag && typeof s.bag === "object") {
          const merged: Bag = { ...Object.fromEntries(DEFAULT_CLUBS.map((c) => [c, 0])), ...s.bag };
          setBag(merged);
        }
        if (s.shot_shapes && typeof s.shot_shapes === "object") {
          setShotShapes({ ...DEFAULT_SHAPES, ...s.shot_shapes });
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load settings");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const cleanBag: Bag = {};
      for (const [k, v] of Object.entries(bag)) {
        const n = Number(v);
        if (Number.isFinite(n) && n > 0) cleanBag[k] = Math.round(n);
      }
      await apiFetch("/api/me/settings", {
        method: "PUT",
        body: JSON.stringify({
          handicap_index: handicap,
          bag: cleanBag,
          shot_shapes: shotShapes,
        }),
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <main className="pageScrollLight">Loading…</main>;

  return (
    <main className="pageScrollLight" style={{ maxWidth: 760, margin: "0 auto" }}>
      <h1 style={{ marginTop: 0 }}>Settings</h1>
      <section style={{ display: "grid", gap: 10, marginBottom: 18 }}>
        <label>
          Handicap index
          <input
            type="number"
            step={0.5}
            min={0}
            max={54}
            value={handicap}
            onChange={(e) => setHandicap(Number(e.target.value))}
            style={{ width: 140, padding: 10, marginLeft: 10 }}
          />
        </label>
      </section>

      <h2 style={{ marginTop: 24 }}>Typical Shot Shape</h2>
      <div style={{ display: "grid", gap: 12, maxWidth: 520 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, whiteSpace: "nowrap" }}>Driver</span>
          <select
            value={shotShapes.driver}
            onChange={(e) => setShotShapes((s) => ({ ...s, driver: e.target.value }))}
            aria-label="Typical shot shape with driver"
            style={{ padding: "8px 10px", minWidth: 140 }}
          >
            {SHAPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, whiteSpace: "nowrap" }}>Fairway Woods &amp; Hybrids</span>
          <select
            value={shotShapes.woods}
            onChange={(e) => setShotShapes((s) => ({ ...s, woods: e.target.value }))}
            aria-label="Typical shot shape with fairway woods and hybrids"
            style={{ padding: "8px 10px", minWidth: 140 }}
          >
            {SHAPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, whiteSpace: "nowrap" }}>Irons &amp; Wedges</span>
          <select
            value={shotShapes.irons}
            onChange={(e) => setShotShapes((s) => ({ ...s, irons: e.target.value }))}
            aria-label="Typical shot shape with irons and wedges"
            style={{ padding: "8px 10px", minWidth: 140 }}
          >
            {SHAPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <h2 style={{ marginTop: 28 }}>My Bag</h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 140px", gap: 10 }}>
        {DEFAULT_CLUBS.map((club) => (
          <div key={club} style={{ display: "contents" }}>
            <label style={{ alignSelf: "center" }}>{club}</label>
            <input
              type="number"
              min={0}
              max={400}
              value={bag[club] ?? 0}
              onChange={(e) => setBag((b) => ({ ...b, [club]: Number(e.target.value) }))}
              style={{ padding: 10 }}
            />
          </div>
        ))}
      </div>

      <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center" }}>
        <button onClick={save} disabled={saving} style={{ padding: 12 }}>
          {saving ? "Saving…" : "Save settings"}
        </button>
        {error ? <span style={{ color: "crimson" }}>{error}</span> : null}
      </div>
    </main>
  );
}
