"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type Bag = Record<string, number>;
type Settings = { handicap_index: number | null; bag: Bag | null };

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
  "LW"
];

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [handicap, setHandicap] = useState<number>(15);
  const [bag, setBag] = useState<Bag>(() => Object.fromEntries(DEFAULT_CLUBS.map((c) => [c, 0])));

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
      } catch (e: any) {
        setError(e?.message || "Failed to load settings");
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
        body: JSON.stringify({ handicap_index: handicap, bag: cleanBag })
      });
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <main className="pageScroll" style={{ padding: 20 }}>Loading…</main>;

  return (
    <main className="pageScroll" style={{ padding: 20, maxWidth: 760, margin: "0 auto" }}>
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

      <h2 style={{ marginTop: 0 }}>My bag</h2>
      <p style={{ marginTop: 6, opacity: 0.8 }}>
        Enter typical carry yardages. These seed the first club suggestion and get refined as you log shots.
      </p>
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

