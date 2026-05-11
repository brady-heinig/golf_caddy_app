"use client";

// Port of `caddie/frontend/src/App.tsx` so we can host the same experience
// inside the Vercel-ready Next.js app.

import { listenOnce } from "@/lib/speechListen";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type Map, Marker } from "maplibre-gl";
import * as turf from "@turf/turf";

import "maplibre-gl/dist/maplibre-gl.css";

type Course = { id: string; name: string };
type HoleResp = any;
type CourseDetail = {
  id: string;
  name: string;
  par: number;
  holes: { number: number; par: number; handicap?: number }[];
};

const ESRI_IMAGERY =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const SATELLITE_MAX_ZOOM = 18;
const MAP_FOLLOW_DURATION_MS = 480;

type LL = { lat: number; lon: number };
type RoundMode = "live" | "sim";

const SCORE_STRIP_MIN = 1;
const SCORE_STRIP_MAX = 15;

type ScorecardPlayerRow = { id: string; name: string; scores: (number | null)[] };

function genPlayerId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `p-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function voiceLineId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `v-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

type VoiceThreadLine = { id: string; role: "user" | "assistant"; content: string };

function emptyScores18(): (number | null)[] {
  return Array.from({ length: 18 }, () => null);
}

function bearingDegrees(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const dlam = ((lon2 - lon1) * Math.PI) / 180;
  const x = Math.sin(dlam) * Math.cos(phi2);
  const y = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dlam);
  const brg = (Math.atan2(x, y) * 180) / Math.PI;
  return ((brg % 360) + 360) % 360;
}

function windShotAlongCross(windMph: number, windFromDeg: number, bearingShotDeg: number): { along: number; cross: number } {
  const windTo = (Number(windFromDeg) + 180) % 360;
  const rad = ((windTo - Number(bearingShotDeg)) * Math.PI) / 180;
  const w = Number(windMph);
  return { along: w * Math.cos(rad), cross: w * Math.sin(rad) };
}

function windYardHeadTailYds(alongMph: number, baselineYds: number): { add: number; sub: number } {
  const b = Number(baselineYds);
  if (!(b > 0)) return { add: 0, sub: 0 };
  const headMph = Math.max(0, -Number(alongMph));
  const tailMph = Math.max(0, Number(alongMph));
  return { add: b * 0.01 * headMph, sub: b * 0.005 * tailMph };
}

function haversineYards(a: LL, b: LL): number {
  const R = 6371008.8; // meters
  const toRad = (d: number) => (d * Math.PI) / 180;
  const p1 = toRad(a.lat);
  const p2 = toRad(b.lat);
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const x =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(p1) * Math.cos(p2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
  return R * c * 1.0936133;
}

const WIND_ADJ_YD_EPS = 0.35;
function formatWindAdjustmentYds(windAdjYd: number): string {
  const r = Math.round(windAdjYd);
  if (r === 0) return "0 yd";
  return r > 0 ? `+${r} yd` : `${r} yd`;
}

function distWindAdjClass(windAdjYd: number): string {
  if (!Number.isFinite(windAdjYd) || Math.abs(windAdjYd) < WIND_ADJ_YD_EPS) return "distInfoWindNeutral";
  // Sign convention matches inverted wind_adjust_yd (+ = tailwind term dominant in net).
  return windAdjYd > 0 ? "distInfoWindHelps" : "distInfoWindAdds";
}

function yardChipWindAdjClass(windAdjYd: number): string {
  if (!Number.isFinite(windAdjYd) || Math.abs(windAdjYd) < WIND_ADJ_YD_EPS) return "yardChipWindNeutral";
  return windAdjYd > 0 ? "yardChipWindHelps" : "yardChipWindAdds";
}

function formatSignedElevYd(v: number): string {
  const r = Math.round(v * 10) / 10;
  const body = Number.isInteger(r) ? `${Math.abs(r)}` : Math.abs(r).toFixed(1);
  if (r === 0) return "0 yd";
  return `${r > 0 ? "+" : "-"}${body} yd`;
}

/** Prefer the SUMMARY paragraph for voice when the caddie follows the prompt format (handles **SUMMARY:** etc.). */
function speechTextFromCaddieReply(full: string): string {
  const trimmed = full.trim();
  const re = /(?:^|[\r\n])\s*(?:#{1,6}\s+)?\*{0,2}\s*SUMMARY\s*:\s*\*{0,2}\s*/i;
  const found = re.exec(trimmed);
  if (!found) return trimmed;
  const after = trimmed.slice(found.index + found[0].length).trim();
  return after || trimmed;
}

/** Uses structured briefing + summary when present; falls back to legacy `assistant` string. */
function parseCaddieAdvicePayload(data: Record<string, unknown>): {
  briefing: string | null;
  summary: string | null;
  meta: { recommendedClub: string; playsLikeContextYd: number };
} {
  let briefing = typeof data.briefing === "string" ? data.briefing.trim() : "";
  let summary = typeof data.summary === "string" ? data.summary.trim() : "";
  const assistant = typeof data.assistant === "string" ? data.assistant.trim() : "";

  const rcRaw = typeof data.recommended_club === "string" ? data.recommended_club.trim() : "Unknown";
  const plyRaw =
    typeof data.plays_like_context_yd === "number"
      ? data.plays_like_context_yd
      : Number(data.plays_like_context_yd);
  const playsLikeContextYd = Number.isFinite(plyRaw) ? plyRaw : 0;

  if ((!briefing || !summary) && assistant) {
    const parts = assistant.split(/\n---\n/);
    if (parts.length >= 2) {
      if (!briefing) briefing = parts[0].trim();
      const tail = parts.slice(1).join("\n---\n").trim();
      if (!summary)
        summary =
          speechTextFromCaddieReply(tail) ||
          tail.replace(/^\*{0,2}\s*SUMMARY\s*:\s*\*{0,2}\s*/i, "").trim();
    } else if (!summary) {
      summary = speechTextFromCaddieReply(assistant) || assistant;
    }
  }

  return {
    briefing: briefing || null,
    summary: summary || null,
    meta: {
      recommendedClub: rcRaw || "Unknown",
      playsLikeContextYd,
    },
  };
}

type MapYardChipDetail = {
  playsYd: number;
  straightYd: number;
  elevChangeYd: number | null;
  windAdjustYd: number | null;
  weatherOk: boolean;
  pending?: boolean;
};

function fillMapYardChip(host: HTMLDivElement, d: MapYardChipDetail, popOpen: { current: HTMLDivElement | null }) {
  host.replaceChildren();
  host.className = "yardChipHost";
  host.onmousedown = (e) => e.stopPropagation();

  const row = document.createElement("div");
  row.className = "yardChipRow";
  const val = document.createElement("span");
  val.textContent = `${Math.round(d.playsYd)} yd`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "yardChipInfoBtn";
  btn.setAttribute("aria-label", "Distance breakdown");
  btn.appendChild(document.createTextNode("i"));

  const pop = document.createElement("div");
  pop.className = "yardChipPopover";

  const mkYcRow = (label: string, valueEl: HTMLElement) => {
    const r = document.createElement("div");
    r.className = "ycLine ycBreakRow";
    const lbl = document.createElement("span");
    lbl.className = "ycMuted";
    lbl.textContent = label;
    r.append(lbl, valueEl);
    return r;
  };

  const l1Val = document.createElement("span");
  l1Val.className = "ycDiagVal";
  l1Val.textContent = `${Math.round(d.straightYd)} yd`;
  const l1 = mkYcRow("True distance", l1Val);

  const l2 = document.createElement("div");
  l2.className = "ycLine ycBreakRow";
  const l2Lbl = document.createElement("span");
  l2Lbl.className = "ycMuted";
  l2Lbl.textContent = "Elevation adjustment";
  const l2Val = document.createElement("span");
  l2.append(l2Lbl, l2Val);
  if (d.pending || d.elevChangeYd == null) {
    l2Val.textContent = "…";
    l2Val.className = "ycDiagVal";
  } else {
    const e = d.elevChangeYd;
    l2Val.className = e >= 0 ? "yardChipElevPos" : "yardChipElevNeg";
    l2Val.textContent = formatSignedElevYd(e);
  }

  const l3Lbl = document.createElement("span");
  l3Lbl.className = "ycMuted";
  l3Lbl.textContent = "Wind adjustment";
  const l3Val = document.createElement("span");
  const l3 = document.createElement("div");
  l3.className = "ycLine ycBreakRow";
  l3.append(l3Lbl, l3Val);
  if (d.pending) {
    l3Val.className = "ycDiagVal";
    l3Val.textContent = "…";
  } else if (!d.weatherOk) {
    l3Val.className = "ycDiagVal";
    l3Val.textContent = "—";
  } else {
    const wa = Number(d.windAdjustYd ?? 0);
    l3Val.className = yardChipWindAdjClass(wa);
    l3Val.textContent = formatWindAdjustmentYds(wa);
  }

  pop.append(l1, l2, l3);

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    const isOpen = pop.style.display === "block";
    if (popOpen.current && popOpen.current !== pop) popOpen.current.style.display = "none";
    if (isOpen) {
      pop.style.display = "none";
      popOpen.current = null;
    } else {
      pop.style.display = "block";
      popOpen.current = pop;
    }
  });

  row.append(val, btn);
  host.append(row, pop);
}

function DistanceHeaderTip({
  straightYd,
  elevYd,
  windAdjYd,
  weatherOk,
}: {
  straightYd: number | string;
  elevYd: number | null;
  windAdjYd: number | null;
  weatherOk: boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: globalThis.MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [open]);

  const e = elevYd != null && Number.isFinite(Number(elevYd)) ? Math.round(Number(elevYd) * 10) / 10 : null;
  const elevCls = e != null && e >= 0 ? "distInfoElevPos" : "distInfoElevNeg";
  const wa = typeof windAdjYd === "number" && Number.isFinite(windAdjYd) ? windAdjYd : 0;

  return (
    <div className="metricHeadWrap" ref={wrapRef}>
      <button
        type="button"
        className="distInfoBtn"
        aria-label="Straight, elevation, and wind breakdown"
        onClick={(ev) => {
          ev.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        i
      </button>
      <div className={`distInfoPopover ${open ? "open" : ""}`} role="tooltip">
        <div className="diLine diBreakRow">
          <span className="diMuted">True distance</span>
          <span className="diValStrong">{straightYd} yd</span>
        </div>
        <div className="diLine diBreakRow">
          <span className="diMuted">Elevation adjustment</span>
          <span className={e != null ? elevCls : "diValStrong"}>{e != null ? formatSignedElevYd(e) : "—"}</span>
        </div>
        <div className="diLine diBreakRow">
          <span className="diMuted">Wind adjustment</span>
          {!weatherOk ? (
            <span className="diValStrong">—</span>
          ) : (
            <span className={distWindAdjClass(wa)}>{formatWindAdjustmentYds(wa)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

export function CaddieApp() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState<string>("stevens_golf_course");
  const [holeNum, setHoleNum] = useState<number>(1);
  const [hole, setHole] = useState<HoleResp | null>(null);
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [roundMode, setRoundMode] = useState<RoundMode | null>(null);
  const [liveGps, setLiveGps] = useState<LL | null>(null);
  const [simPos, setSimPos] = useState<LL | null>(null);
  const simHoleInitialized = useRef<number | null>(null);
  const simPosLatestRef = useRef<LL | null>(null);
  if (simPos) simPosLatestRef.current = simPos;
  const [mapBearing, setMapBearing] = useState<number>(0);
  const [showScore, setShowScore] = useState<boolean>(false);
  const [scorecardPlayers, setScorecardPlayers] = useState<ScorecardPlayerRow[]>(() => {
    const id = genPlayerId();
    return [{ id, name: "You", scores: emptyScores18() }];
  });
  const [showHolePicker, setShowHolePicker] = useState<boolean>(false);
  const [showCaddieAdvice, setShowCaddieAdvice] = useState(false);
  const [caddieLoading, setCaddieLoading] = useState(false);
  const [caddieErr, setCaddieErr] = useState<string | null>(null);
  const [caddieBriefing, setCaddieBriefing] = useState<string | null>(null);
  const [caddieSummary, setCaddieSummary] = useState<string | null>(null);
  const [caddieFlowKey, setCaddieFlowKey] = useState(0);
  const priorAdviceSnapRef = useRef<{
    courseId: string;
    holeNum: number;
    playsLikeYd: number;
    recommendedClub: string;
  } | null>(null);
  /** Lets “Try again” after a failed advice call skip the last-shot gate for that open only. */
  const skipFeedbackGateOnceRef = useRef(false);
  const [lastShotFeedbackPrompt, setLastShotFeedbackPrompt] = useState<string | null>(null);
  const [lastShotAwaitingSpeakOrMic, setLastShotAwaitingSpeakOrMic] = useState(false);
  const [listeningLastShot, setListeningLastShot] = useState(false);
  const [showVoiceAsk, setShowVoiceAsk] = useState(false);
  const [voiceThread, setVoiceThread] = useState<VoiceThreadLine[]>([]);
  const voiceThreadRef = useRef<VoiceThreadLine[]>([]);
  voiceThreadRef.current = voiceThread;
  const [voiceAskBusy, setVoiceAskBusy] = useState(false);
  const [voiceAskErr, setVoiceAskErr] = useState<string | null>(null);
  const voiceScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [ttsLoading, setTtsLoading] = useState(false);
  const [ttsErr, setTtsErr] = useState<string | null>(null);
  /** Mobile Safari/Chrome block audio unless play/speech runs from a fresh tap (autoplay after await fails). */
  const [ttsNeedsUserTap, setTtsNeedsUserTap] = useState(false);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsObjectUrlRef = useRef<string | null>(null);
  const ttsTapTextRef = useRef<string>("");
  const [scoreEditCell, setScoreEditCell] = useState<{ playerId: string; hole: number } | null>(null);
  const [activeCardPlayerId, setActiveCardPlayerId] = useState<string | null>(null);
  const [wxOverride, setWxOverride] = useState<any | null>(null);
  const [metricsOverride, setMetricsOverride] = useState<any | null>(null);

  const mapRef = useRef<Map | null>(null);
  const mapEl = useRef<HTMLDivElement | null>(null);
  const approachBendUserDraggedRef = useRef(false);
  const playerMapPosRef = useRef<LL | null>(null);
  const bendMapRef = useRef<LL | null>(null);
  const mapInteractionRef = useRef<{
    updateDyn: (b: LL) => void;
    applyFrame: (opts?: { animate?: boolean }) => void;
    playerMarker: Marker | null;
  } | null>(null);
  const pathLegsDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pathLegsRequestIdRef = useRef(0);

  useEffect(() => {
    approachBendUserDraggedRef.current = false;
  }, [holeNum, courseId]);

  useEffect(() => {
    if (roundMode !== "live" || liveGps == null) return;
    const mi = mapInteractionRef.current;
    if (!mi?.playerMarker) return;
    playerMapPosRef.current = liveGps;
    mi.playerMarker.setLngLat([liveGps.lon, liveGps.lat]);
    const b = bendMapRef.current;
    if (b) mi.updateDyn(b);
    mi.applyFrame({ animate: true });
  }, [roundMode, liveGps?.lat, liveGps?.lon]);

  const effectivePos: LL | null = useMemo(() => {
    if (roundMode === "live") return liveGps;
    if (roundMode === "sim") return simPos;
    return null;
  }, [roundMode, liveGps, simPos]);

  useEffect(() => {
    if (roundMode !== "live") {
      setLiveGps(null);
      return;
    }
    if (!navigator.geolocation) return;
    let lastEmit = 0;
    const THROTTLE_MS = 3000;
    const emit = (lat: number, lon: number) => {
      const t = Date.now();
      if (t - lastEmit < THROTTLE_MS) return;
      lastEmit = t;
      setLiveGps({ lat, lon });
    };
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLiveGps({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        lastEmit = Date.now();
      },
      () => {},
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20_000 },
    );
    const wid = navigator.geolocation.watchPosition(
      (pos) => emit(pos.coords.latitude, pos.coords.longitude),
      () => {},
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 30_000 },
    );
    return () => navigator.geolocation.clearWatch(wid);
  }, [roundMode]);

  useLayoutEffect(() => {
    if (roundMode !== "sim") {
      simHoleInitialized.current = null;
      return;
    }
    const t = hole?.hole?.tee;
    const hn = hole?.hole?.number;
    if (!t || hn !== holeNum) return;
    if (simHoleInitialized.current === holeNum) return;
    simHoleInitialized.current = holeNum;
    const next = { lat: t.lat, lon: t.lon };
    simPosLatestRef.current = next;
    setSimPos(next);
  }, [roundMode, holeNum, hole?.hole?.number, hole?.hole?.tee?.lat, hole?.hole?.tee?.lon]);

  useEffect(() => {
    fetch("/api/caddie/courses")
      .then((r) => r.json())
      .then(setCourses)
      .catch(() => setCourses([]));
  }, []);

  useEffect(() => {
    fetch(`/api/caddie/course/${encodeURIComponent(courseId)}`)
      .then((r) => {
        if (!r.ok) throw new Error("course fetch failed");
        return r.json();
      })
      .then((c) => setCourse(c))
      .catch(() => setCourse(null));
  }, [courseId]);

  useEffect(() => {
    if (roundMode == null) return;
    const ac = new AbortController();
    setErr(null);
    const qp =
      effectivePos != null
        ? `?player_lat=${encodeURIComponent(effectivePos.lat)}&player_lon=${encodeURIComponent(effectivePos.lon)}`
        : "";
    const n = holeNum;
    fetch(`/api/caddie/course/${encodeURIComponent(courseId)}/hole/${n}${qp}`, { signal: ac.signal, cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("hole fetch failed");
        return r.json();
      })
      .then((data) => {
        if (data?.hole?.number !== n) return;
        setHole(data);
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        setErr(String(e));
      });
    return () => ac.abort();
  }, [roundMode, courseId, holeNum, effectivePos?.lat, effectivePos?.lon]);

  const metrics = hole?.metrics;
  const effectiveMetrics = metricsOverride ?? metrics ?? null;
  const dist = effectiveMetrics?.distance_yd ?? "—";
  const plays = effectiveMetrics?.plays_like_yd ?? "—";
  const elevToPinYd = effectiveMetrics?.elev_change_yd;
  const windAdjMetric = effectiveMetrics?.wind_adjust_yd;
  const greenHitPct = effectiveMetrics?.green_hit_pct;
  const w = wxOverride ?? hole?.weather ?? null;
  const windMph = w?.wind_mph ?? null;
  const windFromDeg = w?.wind_dir_deg ?? null;
  const windCard = w?.wind_dir_card ?? "";
  const weatherOk = Boolean(w && !w.error && windMph != null && windFromDeg != null);

  // Client-side fallback: if backend can't reach Open‑Meteo, compute weather + plays-like adjustments here.
  useEffect(() => {
    if (!hole?.hole) return;
    const tee = hole.hole.tee as LL;
    const gc = hole.hole.green_center as LL;
    const player = effectivePos ?? tee;

    const backendWx = hole?.weather;
    const backendOk = Boolean(backendWx && !backendWx.error && backendWx.wind_mph != null && backendWx.wind_dir_deg != null);
    const backendHasMetrics = Boolean(hole?.metrics && hole.metrics.distance_yd != null && hole.metrics.elev_change_yd != null);

    let cancelled = false;
    const ac = new AbortController();

    async function fetchWxAndMaybeMetrics() {
      try {
        // Weather fallback (Open‑Meteo forecast current)
        if (!backendOk) {
          const q = new URLSearchParams({
            latitude: String(player.lat),
            longitude: String(player.lon),
            current: "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation,weather_code",
            wind_speed_unit: "mph",
            temperature_unit: "fahrenheit",
            forecast_days: "1",
          });
          const r = await fetch(`https://api.open-meteo.com/v1/forecast?${q.toString()}`, {
            signal: ac.signal,
            cache: "no-store",
          });
          if (!r.ok) throw new Error(`wx ${r.status}`);
          const j = await r.json();
          const cur = j?.current ?? {};
          const wd = cur?.wind_direction_10m;
          const ws = cur?.wind_speed_10m;
          const wx = {
            temp_f: cur?.temperature_2m ?? null,
            humidity_pct: cur?.relative_humidity_2m ?? null,
            wind_mph: typeof ws === "number" ? ws : ws != null ? Number(ws) : null,
            wind_dir_deg: typeof wd === "number" ? wd : wd != null ? Number(wd) : null,
            wind_dir_card: "",
          };
          if (!cancelled) setWxOverride(wx);
        } else {
          if (!cancelled) setWxOverride(null);
        }

        // Metrics fallback (elevation + wind adjustment) if backend metrics missing.
        if (!backendHasMetrics) {
          const q2 = new URLSearchParams({
            latitude: `${player.lat},${gc.lat}`,
            longitude: `${player.lon},${gc.lon}`,
          });
          const r2 = await fetch(`https://api.open-meteo.com/v1/elevation?${q2.toString()}`, {
            signal: ac.signal,
            cache: "no-store",
          });
          if (!r2.ok) throw new Error(`elev ${r2.status}`);
          const j2 = await r2.json();
          const arr = Array.isArray(j2?.elevation) ? j2.elevation : [];
          const elevPlayerM = Number(arr?.[0] ?? 0);
          const elevGreenM = Number(arr?.[1] ?? 0);
          const elevChangeYd = ((elevGreenM - elevPlayerM) * 3.28084) / 3.0;
          const distYd = haversineYards(player, gc);
          const baseline = distYd + elevChangeYd;

          const wx = (wxOverride ?? backendWx) as any;
          let windAdj = 0;
          if (wx && !wx.error && wx.wind_mph != null && wx.wind_dir_deg != null) {
            const brg = bearingDegrees(player.lat, player.lon, gc.lat, gc.lon);
            const { along } = windShotAlongCross(Number(wx.wind_mph), Number(wx.wind_dir_deg), brg);
            const { add, sub } = windYardHeadTailYds(along, baseline);
            windAdj = sub - add;
          }
          const playsLike = baseline + windAdj;
          const out = {
            distance_yd: Math.round(distYd),
            elev_change_yd: Math.round(elevChangeYd * 10) / 10,
            wind_adjust_yd: Math.round(windAdj * 10) / 10,
            plays_like_yd: Math.round(playsLike),
          };
          if (!cancelled) setMetricsOverride(out);
        } else {
          if (!cancelled) setMetricsOverride(null);
        }
      } catch {
        // If the browser can't fetch either, keep backend values (or lack thereof).
      }
    }

    fetchWxAndMaybeMetrics();
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [hole?.hole?.number, hole?.weather?.fetched_at, effectivePos?.lat, effectivePos?.lon, wxOverride]);

  const primaryScores = scorecardPlayers[0]?.scores ?? [];
  const scoreStr = useMemo(() => {
    const pars = (course?.holes ?? []).map((h) => Number(h.par) || 0);
    let parPlayed = 0;
    let strokesPlayed = 0;
    let anyPlayed = false;
    for (let i = 0; i < 18; i++) {
      const p = pars[i] ?? 0;
      const s = primaryScores[i];
      if (typeof s === "number") {
        anyPlayed = true;
        strokesPlayed += s;
        if (p > 0) parPlayed += p;
      }
    }
    if (!anyPlayed) return "E";
    if (parPlayed <= 0) return "E";
    const diff = strokesPlayed - parPlayed;
    if (diff === 0) return "E";
    return diff > 0 ? `+${diff}` : `${diff}`;
  }, [course?.holes, primaryScores]);

  const parForHole = (hn: number) => {
    const p = (course?.holes ?? [])[hn - 1]?.par;
    const n = Number(p);
    return Number.isFinite(n) && n > 0 ? n : 4;
  };

  const clampScore = (n: number) => Math.min(SCORE_STRIP_MAX, Math.max(SCORE_STRIP_MIN, Math.round(n)));

  const setHoleScore = (playerId: string, hn: number, score: number) => {
    setScorecardPlayers((prev) =>
      prev.map((pl) => {
        if (pl.id !== playerId) return pl;
        const scores = pl.scores.slice();
        scores[hn - 1] = clampScore(score);
        return { ...pl, scores };
      }),
    );
  };

  const adjustHoleScore = (playerId: string, hn: number, delta: number) => {
    setScorecardPlayers((prev) =>
      prev.map((pl) => {
        if (pl.id !== playerId) return pl;
        const cur = pl.scores[hn - 1];
        const base = typeof cur === "number" ? cur : parForHole(hn);
        const scores = pl.scores.slice();
        scores[hn - 1] = clampScore(base + delta);
        return { ...pl, scores };
      }),
    );
  };

  const resolvedActivePlayerId = activeCardPlayerId ?? scorecardPlayers[0]?.id ?? "";

  const activateHoleCell = (playerId: string, hn: number) => {
    setActiveCardPlayerId(playerId);
    setScoreEditCell({ playerId, hole: hn });
    setScorecardPlayers((prev) =>
      prev.map((pl) => {
        if (pl.id !== playerId) return pl;
        if (pl.scores[hn - 1] != null) return pl;
        const p = parForHole(hn);
        const scores = pl.scores.slice();
        scores[hn - 1] = p;
        return { ...pl, scores };
      }),
    );
  };

  const addScorecardPlayer = () => {
    const id = genPlayerId();
    setScorecardPlayers((prev) => [...prev, { id, name: `Player ${prev.length + 1}`, scores: emptyScores18() }]);
  };

  useEffect(() => {
    if (!showScore) setScoreEditCell(null);
  }, [showScore]);

  useEffect(() => {
    if (showCaddieAdvice || showVoiceAsk) return;
    if (ttsAudioRef.current) {
      ttsAudioRef.current.pause();
      ttsAudioRef.current = null;
    }
    if (ttsObjectUrlRef.current) {
      URL.revokeObjectURL(ttsObjectUrlRef.current);
      ttsObjectUrlRef.current = null;
    }
    setTtsErr(null);
    setTtsNeedsUserTap(false);
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  }, [showCaddieAdvice, showVoiceAsk]);

  useLayoutEffect(() => {
    if (!showVoiceAsk) return;
    voiceScrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [showVoiceAsk, voiceThread]);

  function deviceSpeakAdvice(raw: string) {
    if (!raw.trim() || typeof window === "undefined" || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const text = raw
      .replace(/\r/g, "")
      .replace(/\n-{3,}\n/g, ". ")
      .replace(/\n+/g, ". ")
      .replace(/\s+/g, " ")
      .trim();
    if (!text) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-US";
    u.rate = 1;
    window.speechSynthesis.speak(u);
  }

  const playTtsFromUserGesture = useCallback(() => {
    const text = ttsTapTextRef.current.trim();
    const audio = ttsAudioRef.current;
    if (audio?.src) {
      void audio
        .play()
        .then(() => {
          setTtsNeedsUserTap(false);
          setTtsErr(null);
        })
        .catch(() => {
          if (text) deviceSpeakAdvice(text);
          setTtsNeedsUserTap(false);
        });
      return;
    }
    if (text) {
      deviceSpeakAdvice(text);
      setTtsNeedsUserTap(false);
      setTtsErr(null);
      return;
    }
    setTtsErr("Nothing to play.");
    setTtsNeedsUserTap(false);
  }, []);

  /** After advice returns: ElevenLabs when configured; on phones, play() must often run from a tap (see ttsNeedsUserTap). */
  const speakAdviceAutomatically = useCallback(async (spokenFromApi: string) => {
    let text = (spokenFromApi ?? "").trim();
    if (/^(?:\*{0,2}\s*)?SUMMARY\s*:\s*\*{0,2}\s*/i.test(text)) {
      text = text.replace(/^(?:\*{0,2}\s*)?SUMMARY\s*:\s*\*{0,2}\s*/i, "").trim();
    }
    if (!text) return;

    setTtsErr(null);
    setTtsNeedsUserTap(false);
    ttsTapTextRef.current = text;
    if (ttsAudioRef.current) {
      ttsAudioRef.current.pause();
      ttsAudioRef.current = null;
    }
    if (ttsObjectUrlRef.current) {
      URL.revokeObjectURL(ttsObjectUrlRef.current);
      ttsObjectUrlRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    setTtsLoading(true);
    try {
      const res = await fetch("/api/caddie/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const data: unknown = await res.json().catch(() => ({}));
        const detail = (data as { detail?: unknown }).detail;
        const msg =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? (detail as { msg?: string }[]).map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
              : res.statusText;
        throw new Error(msg || "Voice request failed");
      }
      const blob = await res.blob();
      if (!blob.size) throw new Error("Empty audio response");
      const url = URL.createObjectURL(blob);
      ttsObjectUrlRef.current = url;
      const audio = new Audio(url);
      audio.playsInline = true;
      audio.setAttribute("playsinline", "true");
      audio.preload = "auto";
      ttsAudioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (ttsObjectUrlRef.current === url) ttsObjectUrlRef.current = null;
        if (ttsAudioRef.current === audio) ttsAudioRef.current = null;
      };
      try {
        await audio.play();
      } catch {
        // Common on iOS/Android: play() rejected after async TTS fetch (no user-gesture chain).
        setTtsNeedsUserTap(true);
      }
    } catch {
      ttsAudioRef.current = null;
      if (ttsObjectUrlRef.current) {
        URL.revokeObjectURL(ttsObjectUrlRef.current);
        ttsObjectUrlRef.current = null;
      }
      setTtsNeedsUserTap(true);
    } finally {
      setTtsLoading(false);
    }
  }, []);

  /** Core advice POST (spoken summary). Saves prior-advice snapshot for the next modal open’s feedback gate. */
  const fetchCaddieAdviceInternal = useCallback(
    async (signal?: AbortSignal) => {
      const pos = effectivePos;
      if (!pos) {
        setCaddieErr(
          roundMode === "live" && liveGps == null
            ? "Still acquiring GPS. Wait a few seconds or check location permissions."
            : roundMode === "sim"
              ? "Sim position not ready. Try again after the map loads."
              : "Position unavailable.",
        );
        return;
      }
      setCaddieLoading(true);
      setCaddieErr(null);
      try {
        const bend = bendMapRef.current;
        const body: Record<string, unknown> = {
          course_id: courseId,
          hole_number: holeNum,
          player_lat: pos.lat,
          player_lon: pos.lon,
        };
        if (bend != null && Number.isFinite(bend.lat) && Number.isFinite(bend.lon)) {
          body.bend_lat = bend.lat;
          body.bend_lon = bend.lon;
        }
        const res = await fetch("/api/caddie/advice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal,
        });
        const data: unknown = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = (data as { detail?: unknown }).detail;
          const msg =
            typeof detail === "string"
              ? detail
              : Array.isArray(detail)
                ? (detail as { msg?: string }[]).map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
                : res.statusText;
          throw new Error(msg || "Request failed");
        }
        const parsed = parseCaddieAdvicePayload(data as Record<string, unknown>);
        setCaddieBriefing(parsed.briefing);
        setCaddieSummary(parsed.summary);
        priorAdviceSnapRef.current = {
          courseId,
          holeNum,
          playsLikeYd: parsed.meta.playsLikeContextYd,
          recommendedClub: parsed.meta.recommendedClub,
        };
        const summarySpeak = typeof parsed.summary === "string" ? parsed.summary.trim() : "";
        if (summarySpeak) await speakAdviceAutomatically(summarySpeak);
      } catch (e) {
        if ((e instanceof DOMException || e instanceof Error) && e.name === "AbortError") return;
        setCaddieErr(e instanceof Error ? e.message : String(e));
        setCaddieBriefing(null);
        setCaddieSummary(null);
      } finally {
        setCaddieLoading(false);
      }
    },
    [courseId, holeNum, effectivePos, roundMode, liveGps, speakAdviceAutomatically],
  );

  /** Retry advice only while the modal stays open after the feedback gate cleared. */
  const fetchCaddieAdvice = useCallback(async () => {
    skipFeedbackGateOnceRef.current = true;
    await fetchCaddieAdviceInternal(undefined);
  }, [fetchCaddieAdviceInternal]);

  const skipLastShotFeedback = useCallback(async () => {
    priorAdviceSnapRef.current = null;
    setLastShotFeedbackPrompt(null);
    setLastShotAwaitingSpeakOrMic(false);
    setListeningLastShot(false);
    setCaddieErr(null);
    await fetchCaddieAdviceInternal(undefined);
  }, [fetchCaddieAdviceInternal]);

  const retryLastShotListen = useCallback(async () => {
    if (!lastShotFeedbackPrompt?.trim()) return;
    const ctrlListen = new AbortController();
    setCaddieErr(null);
    try {
      setListeningLastShot(true);
      const transcript = await listenOnce({ signal: ctrlListen.signal });
      const snap = priorAdviceSnapRef.current;
      if (!snap?.courseId || snap.courseId !== courseId) {
        await fetchCaddieAdviceInternal(undefined);
        setLastShotAwaitingSpeakOrMic(false);
        setLastShotFeedbackPrompt(null);
        setListeningLastShot(false);
        return;
      }
      setCaddieLoading(true);
      setLastShotAwaitingSpeakOrMic(false);
      setLastShotFeedbackPrompt(null);
      setListeningLastShot(false);
      const logRes = await fetch("/api/caddie/log-last-shot-feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: snap.courseId,
          hole_number: snap.holeNum,
          transcript,
          prior_recommended_club: snap.recommendedClub,
          prior_plays_like_yd: snap.playsLikeYd,
        }),
      });
      if (!logRes.ok) {
        const data: unknown = await logRes.json().catch(() => ({}));
        const detail = (data as { detail?: unknown }).detail;
        const msg =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? (detail as { msg?: string }[]).map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
              : logRes.statusText;
        throw new Error(msg || "Save failed");
      }
      priorAdviceSnapRef.current = null;
      await fetchCaddieAdviceInternal(undefined);
    } catch (e) {
      setCaddieErr(e instanceof Error ? e.message : String(e));
    } finally {
      setListeningLastShot(false);
      setCaddieLoading(false);
    }
  }, [courseId, fetchCaddieAdviceInternal, lastShotFeedbackPrompt]);

  const openVoiceAskModal = useCallback(() => {
    setVoiceAskErr(null);
    setVoiceThread([]);
    setShowVoiceAsk(true);
  }, []);

  const runVoiceConversationTurn = useCallback(async () => {
    const pos = effectivePos;
    if (!pos) {
      setVoiceAskErr(
        roundMode === "live" && liveGps == null
          ? "Still acquiring GPS."
          : roundMode === "sim"
            ? "Sim position not ready."
            : "Position unavailable.",
      );
      return;
    }
    setVoiceAskBusy(true);
    setVoiceAskErr(null);
    try {
      const transcript = await listenOnce({});
      const t = transcript.trim();
      if (!t) throw new Error("No speech detected.");
      const userLine: VoiceThreadLine = { id: voiceLineId(), role: "user", content: t };
      const withUser = [...voiceThreadRef.current, userLine];
      setVoiceThread(withUser);

      const bend = bendMapRef.current;
      const body: Record<string, unknown> = {
        course_id: courseId,
        hole_number: holeNum,
        player_lat: pos.lat,
        player_lon: pos.lon,
        messages: withUser.map(({ role, content }) => ({ role, content })),
      };
      if (bend != null && Number.isFinite(bend.lat) && Number.isFinite(bend.lon)) {
        body.bend_lat = bend.lat;
        body.bend_lon = bend.lon;
      }
      const res = await fetch("/api/caddie/voice-conversation-turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data: unknown = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (data as { detail?: unknown }).detail;
        const msg =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? (detail as { msg?: string }[]).map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
              : res.statusText;
        throw new Error(msg || "Request failed");
      }
      const ans =
        typeof (data as { answer_summary?: unknown }).answer_summary === "string"
          ? (data as { answer_summary: string }).answer_summary.trim()
          : "";
      if (!ans) throw new Error("Empty reply.");
      const botLine: VoiceThreadLine = { id: voiceLineId(), role: "assistant", content: ans };
      const full = [...withUser, botLine];
      setVoiceThread(full);
      await speakAdviceAutomatically(ans);
    } catch (e) {
      setVoiceAskErr(e instanceof Error ? e.message : String(e));
    } finally {
      setVoiceAskBusy(false);
    }
  }, [courseId, effectivePos, holeNum, liveGps, roundMode, speakAdviceAutomatically]);

  useEffect(() => {
    if (!showCaddieAdvice) return;
    const ctrl = new AbortController();
    let aborted = false;

    (async () => {
      const pos = effectivePos;
      if (!pos) {
        setCaddieErr(
          roundMode === "live" && liveGps == null
            ? "Still acquiring GPS. Wait a few seconds or check location permissions."
            : roundMode === "sim"
              ? "Sim position not ready. Try again after the map loads."
              : "Position unavailable.",
        );
        return;
      }

      const skipGateOnce = skipFeedbackGateOnceRef.current;
      skipFeedbackGateOnceRef.current = false;
      const snap = priorAdviceSnapRef.current;
      const gate = !!(snap && snap.courseId === courseId && !skipGateOnce);

      if (gate && snap) {
        let promptReady = false;
        setCaddieErr(null);
        setLastShotAwaitingSpeakOrMic(true);
        setLastShotFeedbackPrompt(null);
        setListeningLastShot(false);
        try {
          const prepRes = await fetch("/api/caddie/prep-last-shot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              course_id: snap.courseId,
              hole_number: snap.holeNum,
              recommended_club: snap.recommendedClub,
              plays_like_context_yd: snap.playsLikeYd,
            }),
            signal: ctrl.signal,
          });
          const prepJson = (await prepRes.json().catch(() => ({}))) as { question?: string };
          if (!prepRes.ok) throw new Error("Could not start follow-up.");
          const qRaw = typeof prepJson.question === "string" ? prepJson.question.trim() : "";
          if (aborted) return;
          const qShow =
            qRaw ||
            `Quick check on hole ${snap.holeNum} — what club did you hit last shot, and how did it turn out?`;
          setLastShotFeedbackPrompt(qShow);
          promptReady = true;
          await speakAdviceAutomatically(qShow);
          if (aborted) return;
          let transcript = "";
          try {
            setListeningLastShot(true);
            transcript = await listenOnce({ signal: ctrl.signal });
          } finally {
            setListeningLastShot(false);
          }
          if (aborted) return;
          const t = transcript.trim();
          if (!t) throw new Error("I didn’t catch that — retry the mic or skip.");
          const logRes = await fetch("/api/caddie/log-last-shot-feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              course_id: snap.courseId,
              hole_number: snap.holeNum,
              transcript: t,
              prior_recommended_club: snap.recommendedClub,
              prior_plays_like_yd: snap.playsLikeYd,
            }),
          });
          if (!logRes.ok) {
            const data: unknown = await logRes.json().catch(() => ({}));
            const detail = (data as { detail?: unknown }).detail;
            const msg =
              typeof detail === "string"
                ? detail
                : Array.isArray(detail)
                  ? (detail as { msg?: string }[]).map((d) => d?.msg ?? JSON.stringify(d)).join("; ")
                  : logRes.statusText;
            throw new Error(msg || "Save failed");
          }
          priorAdviceSnapRef.current = null;
          setLastShotFeedbackPrompt(null);
          setLastShotAwaitingSpeakOrMic(false);
          await fetchCaddieAdviceInternal(ctrl.signal);
        } catch (e) {
          if (!aborted && !((e instanceof DOMException || e instanceof Error) && e.name === "AbortError"))
            setCaddieErr(e instanceof Error ? e.message : String(e));
          if (!promptReady) {
            setLastShotAwaitingSpeakOrMic(false);
            setLastShotFeedbackPrompt(null);
          }
        } finally {
          setListeningLastShot(false);
        }
      } else if (!gate) {
        await fetchCaddieAdviceInternal(ctrl.signal);
      }
    })();

    return () => {
      aborted = true;
      ctrl.abort();
    };
  }, [
    showCaddieAdvice,
    caddieFlowKey,
    courseId,
    holeNum,
    effectivePos,
    fetchCaddieAdviceInternal,
    liveGps,
    roundMode,
    speakAdviceAutomatically,
  ]);

  const talkWithCaddie = () => {
    setCaddieFlowKey((k) => k + 1);
    setCaddieErr(null);
    setCaddieBriefing(null);
    setCaddieSummary(null);
    setLastShotFeedbackPrompt(null);
    setLastShotAwaitingSpeakOrMic(false);
    setListeningLastShot(false);
    setTtsErr(null);
    setTtsNeedsUserTap(false);
    skipFeedbackGateOnceRef.current = false;
    setShowCaddieAdvice(true);
  };

  // Create map after mode chosen.
  useEffect(() => {
    if (roundMode == null) {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      return;
    }

    const el = mapEl.current;
    if (!el || mapRef.current) return;

    const m = new maplibregl.Map({
      container: el,
      style: {
        version: 8,
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
        sources: {
          esri: {
            type: "raster",
            tiles: [ESRI_IMAGERY],
            tileSize: 256,
            maxzoom: SATELLITE_MAX_ZOOM,
            attribution: "Imagery © Esri",
          },
        },
        layers: [{ id: "esri", type: "raster", source: "esri" }],
      } as any,
      center: [-96.850431, 32.758606],
      zoom: 16,
      maxZoom: SATELLITE_MAX_ZOOM,
      dragRotate: false,
      touchPitch: false,
      pitchWithRotate: false,
      attributionControl: false,
    });

    mapRef.current = m;

    const syncBearing = () => setMapBearing(((m.getBearing() % 360) + 360) % 360);
    m.on("rotate", syncBearing);
    m.on("load", syncBearing);
    syncBearing();

    return () => {
      m.off("rotate", syncBearing);
      m.off("load", syncBearing);
      m.remove();
      mapRef.current = null;
    };
  }, [roundMode]);

  // Apply hole data to map.
  useEffect(() => {
    const m = mapRef.current;
    if (!m || !hole || roundMode == null) return;

    let cancelled = false;

    const applyHoleToMap = () => {
      const cid = courseId;
      const hn = holeNum;
      const tee = hole.hole.tee;
      const green = hole.hole.green_center;
      const playerLL: LL =
        roundMode === "live" && liveGps
          ? liveGps
          : roundMode === "sim" && simPosLatestRef.current
            ? simPosLatestRef.current
            : { lat: tee.lat, lon: tee.lon };

      const fc = hole.features ?? { type: "FeatureCollection", features: [] };
      const fcUse =
        fc.features?.length > 0
          ? fc
          : turf.featureCollection([
              turf.lineString(
                [
                  [tee.lon, tee.lat],
                  [green.lon, green.lat],
                ],
                { golf: "hole" },
              ),
            ]);

      const holeFeat = (fcUse.features || []).find((f: any) => f?.properties?.golf === "hole" && f?.geometry);
      const coords: [number, number][] =
        holeFeat?.geometry?.type === "LineString"
          ? holeFeat.geometry.coordinates
          : holeFeat?.geometry?.type === "MultiLineString"
            ? (holeFeat.geometry.coordinates?.[0] ?? [])
            : [];
      const midIdx = coords.length >= 2 ? Math.floor(coords.length / 2) : 0;
      const bendInitDefault: LL =
        coords.length >= 2 ? { lon: coords[midIdx][0], lat: coords[midIdx][1] } : { lon: tee.lon, lat: tee.lat };
      // Preserve the agent/user-selected white target across hole-data refreshes.
      const bendInit: LL =
        approachBendUserDraggedRef.current && bendMapRef.current
          ? bendMapRef.current
          : bendInitDefault;

      const start: LL = playerLL;
      const end: LL = { lat: green.lat, lon: green.lon };
      const hw = hole?.weather;
      const wxOkChip = Boolean(hw && !hw.error && hw.wind_mph != null && hw.wind_dir_deg != null);
      playerMapPosRef.current = playerLL;
      bendMapRef.current = bendInit;

      const srcId = "holeFeatures";
      if (!m.getSource(srcId)) {
        m.addSource(srcId, { type: "geojson", data: fcUse } as any);
        m.addLayer({
          id: "golf-outline",
          type: "line",
          source: srcId,
          paint: {
            "line-color": [
              "match",
              ["get", "golf"],
              "green",
              "#2ee6a8",
              "fairway",
              "#0b6b2a",
              "bunker",
              "#cbc103",
              "tee",
              "#777777",
              "water_hazard",
              "#2096f3",
              "lateral_water_hazard",
              "#ff5252",
              "out_of_bounds",
              "#fafafa",
              "#00000000",
            ],
            "line-width": [
              "match",
              ["get", "golf"],
              "green",
              2.25,
              "fairway",
              2.25,
              "water_hazard",
              2.1,
              "lateral_water_hazard",
              2.1,
              "out_of_bounds",
              2.1,
              1.75,
            ],
            "line-opacity": ["match", ["get", "golf"], "out_of_bounds", 0.88, 0.92],
          },
        } as any);
      } else {
        (m.getSource(srcId) as any).setData(fcUse);
      }

      const dynLineId = "dynLine";
      const bendId = "bendPoint";
      const markersId = "holeMarkers";

      const lineFC: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {},
            geometry: {
              type: "LineString",
              coordinates: [
                [start.lon, start.lat],
                [bendInit.lon, bendInit.lat],
                [end.lon, end.lat],
              ],
            },
          } as any,
        ],
      };
      const bendFC: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [bendInit.lon, bendInit.lat] } } as any,
        ],
      };
      const markersFC: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: { kind: "tee" }, geometry: { type: "Point", coordinates: [tee.lon, tee.lat] } } as any,
          { type: "Feature", properties: { kind: "green" }, geometry: { type: "Point", coordinates: [green.lon, green.lat] } } as any,
        ],
      };

      const ensureSource = (id: string, data: any) => {
        if (!m.getSource(id)) m.addSource(id, { type: "geojson", data } as any);
        else (m.getSource(id) as any).setData(data);
      };
      ensureSource(dynLineId, lineFC);
      ensureSource(bendId, bendFC);
      ensureSource(markersId, markersFC);

      const yardPopOpen: { current: HTMLDivElement | null } = { current: null };
      const closeYardPopoverDoc = () => {
        if (yardPopOpen.current) {
          yardPopOpen.current.style.display = "none";
          yardPopOpen.current = null;
        }
      };
      document.addEventListener("click", closeYardPopoverDoc);

      const makeYardageEl = () => document.createElement("div");
      const yardEl1 = makeYardageEl();
      const yardEl2 = makeYardageEl();
      const yardMarker1 = new maplibregl.Marker({ element: yardEl1, anchor: "center" })
        .setLngLat([bendInit.lon, bendInit.lat])
        .addTo(m);
      const yardMarker2 = new maplibregl.Marker({ element: yardEl2, anchor: "center" })
        .setLngLat([bendInit.lon, bendInit.lat])
        .addTo(m);

      const schedulePathLegs = () => {
        if (pathLegsDebounceRef.current != null) clearTimeout(pathLegsDebounceRef.current);
        pathLegsDebounceRef.current = setTimeout(() => {
          pathLegsDebounceRef.current = null;
          const a = playerMapPosRef.current;
          const b = bendMapRef.current;
          if (!a || !b) return;
          const rid = ++pathLegsRequestIdRef.current;
          const url =
            `/api/caddie/course/${encodeURIComponent(cid)}/hole/${hn}/plays-like-path?` +
            `player_lat=${encodeURIComponent(a.lat)}&player_lon=${encodeURIComponent(a.lon)}` +
            `&bend_lat=${encodeURIComponent(b.lat)}&bend_lon=${encodeURIComponent(b.lon)}`;
          fetch(url, { cache: "no-store" })
            .then((r) => {
              if (!r.ok) throw new Error("path");
              return r.json();
            })
            .then((d: any) => {
              if (rid !== pathLegsRequestIdRef.current) return;
              if (d.leg1_horiz_yd != null && d.leg1_elev_change_yd != null && d.leg1_plays_like_yd != null) {
                fillMapYardChip(
                  yardEl1,
                  {
                    playsYd: Number(d.leg1_plays_like_yd),
                    straightYd: Number(d.leg1_horiz_yd),
                    elevChangeYd: Number(d.leg1_elev_change_yd),
                    windAdjustYd: d.leg1_wind_adjust_yd != null ? Number(d.leg1_wind_adjust_yd) : null,
                    weatherOk: wxOkChip,
                    pending: false,
                  },
                  yardPopOpen,
                );
              }
              if (d.leg2_horiz_yd != null && d.leg2_horiz_yd > 0.5 && d.leg2_elev_change_yd != null && d.leg2_plays_like_yd != null) {
                fillMapYardChip(
                  yardEl2,
                  {
                    playsYd: Number(d.leg2_plays_like_yd),
                    straightYd: Number(d.leg2_horiz_yd),
                    elevChangeYd: Number(d.leg2_elev_change_yd),
                    windAdjustYd: d.leg2_wind_adjust_yd != null ? Number(d.leg2_wind_adjust_yd) : null,
                    weatherOk: wxOkChip,
                    pending: false,
                  },
                  yardPopOpen,
                );
              }
            })
            .catch(() => {});
        }, 200);
      };

      const playerDot = document.createElement("div");
      playerDot.style.width = "18px";
      playerDot.style.height = "18px";
      playerDot.style.borderRadius = "50%";
      playerDot.style.background = "#58a6ff";
      playerDot.style.border = "2px solid #0b1220";
      playerDot.style.boxShadow = "0 2px 8px rgba(0,0,0,0.35)";
      playerDot.style.cursor = roundMode === "sim" ? "grab" : "default";

      const playerMarker = new maplibregl.Marker({ element: playerDot, draggable: roundMode === "sim" })
        .setLngLat([playerLL.lon, playerLL.lat])
        .addTo(m);

      if (!m.getLayer("dynLineLayer")) {
        m.addLayer({
          id: "dynLineLayer",
          type: "line",
          source: dynLineId,
          paint: { "line-color": "#f0f6fc", "line-width": 2, "line-opacity": 0.9 } as any,
          layout: { "line-join": "round", "line-cap": "round" } as any,
        } as any);
        (m as any).setPaintProperty("dynLineLayer", "line-dasharray", [1.2, 1.2]);
      }

      if (!m.getLayer("bendHitLayer")) {
        m.addLayer({
          id: "bendHitLayer",
          type: "circle",
          source: bendId,
          paint: {
            "circle-radius": 28,
            "circle-color": "#000000",
            "circle-opacity": 0,
          } as any,
        } as any);
      }
      if (!m.getLayer("bendLayer")) {
        m.addLayer({
          id: "bendLayer",
          type: "circle",
          source: bendId,
          paint: {
            "circle-radius": 7,
            "circle-color": "#ffffff",
            "circle-stroke-color": "#111827",
            "circle-stroke-width": 2,
          } as any,
        } as any);
      }

      if (!m.getLayer("markerLayer")) {
        m.addLayer({
          id: "markerLayer",
          type: "circle",
          source: markersId,
          paint: {
            "circle-radius": ["match", ["get", "kind"], "tee", 6, "green", 6, 6],
            "circle-color": ["match", ["get", "kind"], "tee", "#ffffff", "green", "#2ee6a8", "#ffffff"],
            "circle-stroke-color": "#0b1220",
            "circle-stroke-width": 2,
          } as any,
        } as any);
      }

      const updateDyn = (bend: LL) => {
        const pm = playerMapPosRef.current;
        if (!pm) return;
        const startNow: LL = pm;

        // Never auto-move the white target or shot line—advice uses wherever the player aimed (drag or initial hole target).
        const bendForLine: LL = bend;
        bendMapRef.current = bendForLine;

        function nudgeOffLine(p1: LL, p2: LL, mid: LL): LL {
          try {
            const br = turf.bearing(turf.point([p1.lon, p1.lat]), turf.point([p2.lon, p2.lat]));
            const perp = br + 90;
            const nudged = turf.destination(turf.point([mid.lon, mid.lat]), 7.3, perp, { units: "meters" } as any);
            const c = nudged.geometry.coordinates as [number, number];
            return { lon: c[0], lat: c[1] };
          } catch {
            return mid;
          }
        }

        const d1 = haversineYards(startNow, bendForLine);
        const d2 = haversineYards(bendForLine, end);
        const mid1N = nudgeOffLine(startNow, bendForLine, { lat: (startNow.lat + bendForLine.lat) / 2, lon: (startNow.lon + bendForLine.lon) / 2 });
        const mid2N = nudgeOffLine(bendForLine, end, { lat: (bendForLine.lat + end.lat) / 2, lon: (bendForLine.lon + end.lon) / 2 });

        const line = {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              properties: {},
              geometry: {
                type: "LineString",
                coordinates: [
                  [startNow.lon, startNow.lat],
                  [bendForLine.lon, bendForLine.lat],
                  [end.lon, end.lat],
                ],
              },
            },
          ],
        };
        const bendG = {
          type: "FeatureCollection",
          features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [bendForLine.lon, bendForLine.lat] } }],
        };
        (m.getSource(dynLineId) as any).setData(line);
        (m.getSource(bendId) as any).setData(bendG);

        yardMarker1.setLngLat([mid1N.lon, mid1N.lat]);
        yardEl1.style.display = "";
        fillMapYardChip(
          yardEl1,
          { playsYd: d1, straightYd: d1, elevChangeYd: null, windAdjustYd: null, weatherOk: wxOkChip, pending: true },
          yardPopOpen,
        );

        yardEl2.style.display = "";
        yardMarker2.setLngLat([mid2N.lon, mid2N.lat]);
        fillMapYardChip(
          yardEl2,
          { playsYd: d2, straightYd: d2, elevChangeYd: null, windAdjustYd: null, weatherOk: wxOkChip, pending: true },
          yardPopOpen,
        );

        schedulePathLegs();
      };

      updateDyn(bendInit);

      const padFrac = 0.1;
      const padMinPx = 10;
      let applyFrameRaf = 0;
      const applyFrame = (opts?: { animate?: boolean }) => {
        const animate = opts?.animate !== false;
        const run = () => {
          applyFrameRaf = 0;
          const a = playerMapPosRef.current;
          if (!a) return;
          const sz = m.getCanvas().getBoundingClientRect();
          if (sz.width < 1 || sz.height < 1) return;
          const pad = Math.max(padMinPx, sz.height * padFrac);
          const bearing = turf.bearing(turf.point([a.lon, a.lat]), turf.point([end.lon, end.lat]));
          const bendPt = bendMapRef.current;
          const lngs = [a.lon, end.lon];
          const lats = [a.lat, end.lat];
          if (bendPt && Number.isFinite(bendPt.lat) && Number.isFinite(bendPt.lon)) {
            lngs.push(bendPt.lon);
            lats.push(bendPt.lat);
          }
          const sw: [number, number] = [Math.min(...lngs), Math.min(...lats)];
          const ne: [number, number] = [Math.max(...lngs), Math.max(...lats)];
          m.fitBounds([sw, ne], {
            padding: { top: pad, bottom: pad, left: pad, right: pad },
            bearing,
            duration: animate ? MAP_FOLLOW_DURATION_MS : 0,
            maxZoom: SATELLITE_MAX_ZOOM,
            essential: true,
          });
        };
        if (!animate) {
          if (applyFrameRaf) cancelAnimationFrame(applyFrameRaf);
          run();
          return;
        }
        if (applyFrameRaf) cancelAnimationFrame(applyFrameRaf);
        applyFrameRaf = requestAnimationFrame(run);
      };

      const onPlayerDrag = () => {
        if (roundMode !== "sim") return;
        const ll = playerMarker.getLngLat();
        playerMapPosRef.current = { lat: ll.lat, lon: ll.lng };
        updateDyn(bendMapRef.current ?? end);
        applyFrame({ animate: true });
      };
      const onPlayerDragEnd = () => {
        if (roundMode !== "sim") return;
        const ll = playerMarker.getLngLat();
        const p = { lat: ll.lat, lon: ll.lng };
        simPosLatestRef.current = p;
        playerMapPosRef.current = p;
        setSimPos(p);
        updateDyn(bendMapRef.current ?? end);
        applyFrame({ animate: true });
      };
      playerMarker.on("drag", onPlayerDrag);
      playerMarker.on("dragend", onPlayerDragEnd);

      let dragging = false;
      let bendDragFrameRaf = 0;
      const bendTouchMoveOpts: AddEventListenerOptions = { passive: false };

      const stepBendDrag = (lat: number, lon: number) => {
        updateDyn({ lat, lon });
        if (bendDragFrameRaf) return;
        bendDragFrameRaf = requestAnimationFrame(() => {
          bendDragFrameRaf = 0;
          applyFrame({ animate: false });
        });
      };

      const bendDocMove = (ev: MouseEvent | TouchEvent) => {
        if (!dragging) return;
        ev.preventDefault();
        let cx: number | undefined;
        let cy: number | undefined;
        if ("touches" in ev && ev.touches.length > 0) {
          cx = ev.touches[0].clientX;
          cy = ev.touches[0].clientY;
        } else if ("clientX" in ev) {
          cx = (ev as MouseEvent).clientX;
          cy = (ev as MouseEvent).clientY;
        }
        if (cx == null || cy == null) return;
        const r = m.getCanvas().getBoundingClientRect();
        const ll = m.unproject([cx - r.left, cy - r.top]);
        stepBendDrag(ll.lat, ll.lng);
      };

      const detachBendDocDrag = () => {
        document.removeEventListener("mousemove", bendDocMove);
        document.removeEventListener("touchmove", bendDocMove, bendTouchMoveOpts);
        document.removeEventListener("mouseup", bendDocEnd);
        document.removeEventListener("touchend", bendDocEnd);
      };

      const bendDocEnd = () => {
        detachBendDocDrag();
        if (!dragging) return;
        dragging = false;
        m.dragPan.enable();
        if (bendDragFrameRaf) {
          cancelAnimationFrame(bendDragFrameRaf);
          bendDragFrameRaf = 0;
        }
        m.getCanvas().style.cursor = "";
        applyFrame({ animate: true });
      };

      const onDown = (e: any) => {
        const feats = m.queryRenderedFeatures(e.point, { layers: ["bendHitLayer", "bendLayer"] });
        if (!feats.length) return;
        dragging = true;
        approachBendUserDraggedRef.current = true;
        m.getCanvas().style.cursor = "grabbing";
        m.dragPan.disable();
        e.preventDefault();
        document.addEventListener("mousemove", bendDocMove);
        document.addEventListener("touchmove", bendDocMove, bendTouchMoveOpts);
        document.addEventListener("mouseup", bendDocEnd);
        document.addEventListener("touchend", bendDocEnd);
      };
      m.on("mousedown", onDown);
      m.on("touchstart", onDown);

      mapInteractionRef.current = { updateDyn, applyFrame, playerMarker };

      applyFrame({ animate: false });
      requestAnimationFrame(() => {
        applyFrame({ animate: false });
        requestAnimationFrame(() => applyFrame({ animate: false }));
      });

      return () => {
        document.removeEventListener("click", closeYardPopoverDoc);
        if (applyFrameRaf) cancelAnimationFrame(applyFrameRaf);
        if (bendDragFrameRaf) cancelAnimationFrame(bendDragFrameRaf);
        detachBendDocDrag();
        m.dragPan.enable();
        if (pathLegsDebounceRef.current != null) {
          clearTimeout(pathLegsDebounceRef.current);
          pathLegsDebounceRef.current = null;
        }
        pathLegsRequestIdRef.current += 1;
        mapInteractionRef.current = null;
        m.off("mousedown", onDown);
        m.off("touchstart", onDown);
        yardMarker1.remove();
        yardMarker2.remove();
        playerMarker.off("drag", onPlayerDrag);
        playerMarker.off("dragend", onPlayerDragEnd);
        playerMarker.remove();
      };
    };

    let teardown: (() => void) | undefined;
    const runHoleSetup = () => {
      if (cancelled) return;
      teardown?.();
      teardown = applyHoleToMap();
    };

    if (!m.isStyleLoaded()) m.once("load", runHoleSetup);
    else runHoleSetup();

    // liveGps intentionally omitted from deps below: GPS updates use a separate effect so the white target is not rebuilt every tick.

    return () => {
      cancelled = true;
      m.off("load", runHoleSetup);
      teardown?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- liveGps omitted; see comment before return
  }, [hole, holeNum, roundMode, courseId]);

  if (roundMode == null) {
    return (
      <div className="phoneShell modePickerShell">
        <div className="modePickerCard">
          <h1 className="modePickerTitle">Play a round</h1>
          <p className="modePickerSub">Choose a mode to start.</p>
          <div className="modePickerBtns">
            <button type="button" className="modePickerBtn modePickerBtnPrimary" onClick={() => setRoundMode("live")}>
              Live round
            </button>
            <button type="button" className="modePickerBtn" onClick={() => setRoundMode("sim")}>
              Simulated round
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="phoneShell">
      <div className="bar header">
        <div>
          <div className="metricLabel">Distance (Adjusted)</div>
          <div className="metricValueRow">
            <div className="metricValue">{plays !== "—" ? plays : dist} yd</div>
            {plays !== "—" || dist !== "—" ? (
              <DistanceHeaderTip
                straightYd={dist}
                elevYd={elevToPinYd != null && Number.isFinite(Number(elevToPinYd)) ? Number(elevToPinYd) : null}
                windAdjYd={typeof windAdjMetric === "number" && Number.isFinite(windAdjMetric) ? windAdjMetric : null}
                weatherOk={weatherOk}
              />
            ) : null}
          </div>
          {roundMode === "live" && !liveGps ? <div className="metricSub">Acquiring GPS…</div> : null}
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="metricLabel">Hit green %</div>
          <div className="metricValue" key={holeNum}>
            {typeof greenHitPct === "number" ? `${greenHitPct}%` : "—"}
          </div>
        </div>
      </div>

      <div className="mapCard">
        <div ref={mapEl} style={{ position: "absolute", inset: 0 }} />
        {err ? <div className="mapHud">API error</div> : null}
        {windMph != null && windFromDeg != null ? (
          <div
            className="windHud"
            style={
              {
                "--wind-rot": `${(((Number(windFromDeg) - mapBearing) % 360) + 360) % 360}deg`,
              } as any
            }
          >
            <div className="windArrow" aria-hidden="true">
              <div className="windArrowStem" />
              <div className="windArrowHead" />
            </div>
            <div className="windText">
              <div className="windLine1">{Math.round(Number(windMph))} mph</div>
              <div className="windLine2">{windCard || "wind"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="bar footer">
        <button
          className="btn"
          onClick={() => setShowScore(true)}
          aria-label="Open scorecard"
          title="Scorecard"
        >
          {scoreStr}
        </button>
        <button className="btn" onClick={() => setHoleNum((h) => Math.max(1, h - 1))} aria-label="Previous hole">
          ◀
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => setShowHolePicker(true)}
          aria-label="Select hole"
          title="Hole"
        >
          Hole {holeNum}
        </button>
        <button className="btn" onClick={() => setHoleNum((h) => Math.min(18, h + 1))} aria-label="Next hole">
          ▶
        </button>
        <div style={{ display: "flex", gap: 8, alignItems: "stretch", minWidth: 0 }}>
          <button
            type="button"
            className="btn btnPrimary btnFooterShrink"
            onClick={talkWithCaddie}
            aria-label="Talk with caddie"
          >
            Talk with caddie
          </button>
          <button
            type="button"
            className="btn btnBrown btnFooterShrink"
            onClick={openVoiceAskModal}
            aria-label="Ask question with voice"
          >
            Ask question
          </button>
        </div>
      </div>

      {showHolePicker ? (
        <div
          className="modalOverlay"
          role="dialog"
          aria-modal="true"
          aria-label="Select hole"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowHolePicker(false);
          }}
        >
          <div className="modalCard" style={{ maxHeight: "70dvh" }}>
            <div className="modalHeader">
              <div>
                <div className="modalTitle">Select hole</div>
                <div className="modalSub">{course?.name ?? courseId}</div>
              </div>
              <button type="button" className="btn modalClose" onClick={() => setShowHolePicker(false)}>
                Done
              </button>
            </div>
            <div style={{ padding: 12, overflow: "auto" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 8 }}>
                {Array.from({ length: 18 }, (_, i) => {
                  const hn = i + 1;
                  const active = hn === holeNum;
                  return (
                    <button
                      key={hn}
                      type="button"
                      className="btn"
                      style={{
                        height: 44,
                        borderColor: active ? "rgba(22,163,74,0.65)" : undefined,
                        background: active ? "rgba(22,163,74,0.10)" : undefined,
                      }}
                      onClick={() => {
                        setHoleNum(hn);
                        setShowHolePicker(false);
                      }}
                    >
                      {hn}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {showCaddieAdvice ? (
        <div
          className="modalOverlay"
          role="dialog"
          aria-modal="true"
          aria-label="Talk with caddie"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowCaddieAdvice(false);
          }}
        >
          <div
            className="modalCard"
            style={{
              maxHeight: "78dvh",
              width: "min(100%, 400px)",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            <div className="modalHeader">
              <div>
                <div className="modalTitle">Talk with caddie</div>
                <div className="modalSub">
                  Hole {holeNum} · {course?.name ?? courseId}
                </div>
              </div>
              <button type="button" className="btn modalClose" onClick={() => setShowCaddieAdvice(false)}>
                Close
              </button>
            </div>
            <div
              style={{
                flex: 1,
                minHeight: 0,
                padding: 12,
                display: "flex",
                flexDirection: "column",
                gap: 10,
                overflow: "auto",
              }}
            >
              {lastShotAwaitingSpeakOrMic && !lastShotFeedbackPrompt && !listeningLastShot ? (
                <div style={{ fontSize: 14, opacity: 0.75 }} aria-live="polite">
                  Preparing a quick check-in on your last shot…
                </div>
              ) : null}
              {lastShotFeedbackPrompt ? (
                <section
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    background: "rgba(22, 163, 74, 0.08)",
                    border: "1px solid rgba(22,163,74,0.22)",
                    fontSize: 14,
                    lineHeight: 1.45,
                  }}
                  aria-label="Last shot check-in"
                >
                  <div style={{ fontWeight: 800, fontSize: 12, letterSpacing: "0.06em", marginBottom: 6 }}>
                    LAST SHOT
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{lastShotFeedbackPrompt}</div>
                  {listeningLastShot ? (
                    <div className="metricSub" style={{ marginTop: 8 }} aria-live="polite">
                      Listening — speak now…
                    </div>
                  ) : null}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
                    <button
                      type="button"
                      className="btn"
                      disabled={listeningLastShot || caddieLoading}
                      onClick={() => void retryLastShotListen()}
                    >
                      Retry mic
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={listeningLastShot || caddieLoading}
                      onClick={() => void skipLastShotFeedback()}
                    >
                      Skip logging
                    </button>
                  </div>
                </section>
              ) : null}
              {caddieLoading && !(lastShotAwaitingSpeakOrMic && lastShotFeedbackPrompt) ? (
                <div style={{ fontSize: 14, padding: "8px 0" }} aria-live="polite">
                  Getting advice…
                </div>
              ) : null}
              {caddieErr ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div style={{ fontSize: 13, color: "#b91c1c", whiteSpace: "pre-wrap" }}>{caddieErr}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {lastShotFeedbackPrompt ? (
                      <>
                        <button type="button" className="btn" onClick={() => void retryLastShotListen()}>
                          Retry mic
                        </button>
                        <button type="button" className="btn" onClick={() => void skipLastShotFeedback()}>
                          Skip to advice
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn"
                        onClick={() => {
                          if (lastShotAwaitingSpeakOrMic) setCaddieFlowKey((k) => k + 1);
                          else void fetchCaddieAdvice();
                        }}
                      >
                        Try again
                      </button>
                    )}
                  </div>
                </div>
              ) : null}
              {caddieSummary || caddieBriefing ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {caddieSummary ? (
                    <div style={{ fontSize: 15, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{caddieSummary}</div>
                  ) : (
                    <div style={{ fontSize: 13, color: "rgba(11,18,32,0.65)" }}>
                      No summary returned — open briefing details below for the labeled lines.
                    </div>
                  )}
                  {caddieBriefing ? (
                    <details style={{ fontSize: 13 }}>
                      <summary style={{ cursor: "pointer", color: "rgba(11,18,32,0.75)", userSelect: "none" }}>
                        Briefing details (8 lines)
                      </summary>
                      <div
                        style={{
                          marginTop: 8,
                          padding: "10px 12px",
                          borderRadius: 8,
                          background: "rgba(11,18,32,0.04)",
                          fontSize: 13,
                          lineHeight: 1.45,
                          whiteSpace: "pre-wrap",
                          color: "rgba(11,18,32,0.88)",
                        }}
                      >
                        {caddieBriefing}
                      </div>
                    </details>
                  ) : null}
                  {ttsLoading && (caddieSummary ?? "").trim() ? (
                    <div className="metricSub" style={{ paddingTop: 2 }} aria-live="polite">
                      Playing caddie voice…
                    </div>
                  ) : null}
                  {ttsNeedsUserTap && (caddieSummary ?? "").trim() ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 4 }}>
                      <div className="metricSub" style={{ fontSize: 12, lineHeight: 1.35 }}>
                        Sound on phones is blocked until you tap once (browser autoplay rule).
                      </div>
                      <button type="button" className="btn btnPrimary" onClick={playTtsFromUserGesture}>
                        Tap to play caddie audio
                      </button>
                    </div>
                  ) : null}
                  {ttsErr ? <div style={{ fontSize: 13, color: "#b91c1c" }}>{ttsErr}</div> : null}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {showVoiceAsk ? (
        <div
          className="modalOverlay"
          role="dialog"
          aria-modal="true"
          aria-label="Ask the caddie"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowVoiceAsk(false);
          }}
        >
          <div
            className="modalCard"
            style={{
              maxHeight: "82dvh",
              width: "min(100%, 420px)",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            <div className="modalHeader">
              <div>
                <div className="modalTitle">Ask the caddie</div>
                <div className="modalSub">
                  Hole {holeNum} · {course?.name ?? courseId}
                </div>
              </div>
              <button type="button" className="btn modalClose" onClick={() => setShowVoiceAsk(false)}>
                Close
              </button>
            </div>
            <div style={{ flex: 1, minHeight: 160, overflow: "auto", padding: "0 12px 8px" }}>
              {voiceThread.length === 0 && !voiceAskBusy ? (
                <p style={{ margin: "12px 0", fontSize: 14, opacity: 0.75, lineHeight: 1.45 }}>
                  Tap “Speak turn” below. Each exchange is shown here; the caddie remembers earlier lines when you speak
                  again.
                </p>
              ) : null}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {voiceThread.map((m) => (
                  <div
                    key={m.id}
                    style={{
                      alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                      maxWidth: "92%",
                      padding: "10px 12px",
                      borderRadius: 12,
                      background:
                        m.role === "user" ? "rgba(22, 163, 74, 0.12)" : "rgba(11,18,32,0.06)",
                      border:
                        m.role === "user" ? "1px solid rgba(22,163,74,0.28)" : "1px solid rgba(11,18,32,0.1)",
                      fontSize: 14,
                      lineHeight: 1.45,
                      whiteSpace: "pre-wrap",
                      color: "rgba(11,18,32,0.92)",
                    }}
                  >
                    <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.08em", opacity: 0.55 }}>
                      {m.role === "user" ? "YOU" : "CADDIE"}
                    </div>
                    {m.content}
                  </div>
                ))}
                <div ref={voiceScrollAnchorRef} aria-hidden />
              </div>
            </div>
            {voiceAskErr ? (
              <div style={{ padding: "0 12px", fontSize: 13, color: "#b91c1c" }}>{voiceAskErr}</div>
            ) : null}
            <div style={{ flexShrink: 0, borderTop: "1px solid rgba(11,18,32,0.1)", padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
              {!effectivePos ? (
                <div className="metricSub" style={{ fontSize: 12 }}>
                  Turn on location (live) or finish map load (sim) to use voice.
                </div>
              ) : null}
              <button
                type="button"
                className="btn btnPrimary"
                disabled={voiceAskBusy || !effectivePos}
                onClick={() => void runVoiceConversationTurn()}
              >
                {voiceAskBusy ? "Listening…" : "Speak turn"}
              </button>
              {ttsLoading ? (
                <div className="metricSub" style={{ fontSize: 12 }} aria-live="polite">
                  Playing caddie voice…
                </div>
              ) : null}
              {ttsNeedsUserTap ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div className="metricSub" style={{ fontSize: 11, lineHeight: 1.35 }}>
                    Tap once to play — mobile browsers require a gesture for sound after loading.
                  </div>
                  <button type="button" className="btn btnPrimary" onClick={playTtsFromUserGesture}>
                    Tap to play caddie audio
                  </button>
                </div>
              ) : null}
              {ttsErr ? <div style={{ fontSize: 12, color: "#b91c1c" }}>{ttsErr}</div> : null}
            </div>
          </div>
        </div>
      ) : null}

      {showScore ? (
        <div
          className="modalOverlay"
          role="dialog"
          aria-modal="true"
          aria-label="Scorecard"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowScore(false);
          }}
        >
          <div className="modalCard">
            <div className="modalHeader">
              <div>
                <div className="modalTitle">Scorecard</div>
                <div className="modalSub">{course?.name ?? "Course"}</div>
              </div>
              <button className="btn modalClose" onClick={() => setShowScore(false)}>
                Done
              </button>
            </div>

            <div className="scorecardBody">
              <div className="scorecardSplit">
                <div className="scorecardPinnedCol">
                  <div className="scorecardPinnedMeta">
                    <div className="scorecardMetaLabel">Hole</div>
                    <div className="scorecardMetaLabel">Handicap</div>
                    <div className="scorecardMetaLabel">Par</div>
                  </div>
                  {scorecardPlayers.map((pl) => {
                    const rowActive = pl.id === resolvedActivePlayerId;
                    return (
                      <div
                        key={`pin-${pl.id}`}
                        className={`scorecardPinnedName scorecardNameCell ${rowActive ? "scorecardPinnedNameActive" : ""}`}
                      >
                        <input
                          className="scorecardNameInput"
                          value={pl.name}
                          onChange={(e) => {
                            const v = e.target.value;
                            setScorecardPlayers((prev) => prev.map((x) => (x.id === pl.id ? { ...x, name: v } : x)));
                          }}
                          placeholder="Name"
                          aria-label="Player name"
                        />
                      </div>
                    );
                  })}
                </div>

                <div className="scorecardHScroll">
                  <div className="scorecardScrollWide">
                    <div className="scorecardScrollHeader">
                      {Array.from({ length: 18 }, (_, i) => (
                        <div key={`hdr-hole-${i + 1}`} className="scorecardHdrData scorecardHdrRowHole">
                          {i + 1}
                        </div>
                      ))}
                      {Array.from({ length: 18 }, (_, i) => {
                        const hn = i + 1;
                        const h = (course?.holes ?? [])[hn - 1]?.handicap ?? "";
                        return (
                          <div key={`hdr-hcp-${hn}`} className="scorecardHdrData scorecardHdrRowHcp">
                            {h}
                          </div>
                        );
                      })}
                      {Array.from({ length: 18 }, (_, i) => {
                        const hn = i + 1;
                        const p = (course?.holes ?? [])[hn - 1]?.par ?? "";
                        return (
                          <div key={`hdr-par-${hn}`} className="scorecardHdrData scorecardHdrRowPar">
                            {p}
                          </div>
                        );
                      })}
                    </div>

                    {scorecardPlayers.map((pl) => (
                      <div key={pl.id} className="scorecardGridRow scorecardPlayerRow">
                        {Array.from({ length: 18 }, (_, i) => {
                          const hn = i + 1;
                          const s = pl.scores[hn - 1];
                          const isEditing =
                            scoreEditCell != null && scoreEditCell.playerId === pl.id && scoreEditCell.hole === hn;
                          const showAdjuster = isEditing && typeof s === "number";
                          return (
                            <div
                              key={hn}
                              data-score-cell
                              tabIndex={0}
                              className={`scoreCell scoreCellInGrid ${isEditing ? "active" : ""}`}
                              onClick={() => activateHoleCell(pl.id, hn)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  activateHoleCell(pl.id, hn);
                                }
                              }}
                              aria-label={
                                typeof s === "number"
                                  ? `Hole ${hn}, score ${s}. Press Enter to edit.`
                                  : `Hole ${hn}, no score. Press Enter to add.`
                              }
                            >
                              {!showAdjuster ? (
                                <div className="scoreVal scoreValSolo">{typeof s === "number" ? s : ""}</div>
                              ) : (
                                <div
                                  className="scoreAdjuster"
                                  onClick={(e) => e.stopPropagation()}
                                  onPointerDown={(e) => e.stopPropagation()}
                                >
                                  <button
                                    type="button"
                                    className="scoreAdjBtn"
                                    aria-label="Subtract one stroke"
                                    disabled={typeof s === "number" && s <= SCORE_STRIP_MIN}
                                    onClick={() => adjustHoleScore(pl.id, hn, -1)}
                                  >
                                    −
                                  </button>
                                  <div className="scoreAdjVal" aria-live="polite">
                                    {s}
                                  </div>
                                  <button
                                    type="button"
                                    className="scoreAdjBtn"
                                    aria-label="Add one stroke"
                                    disabled={typeof s === "number" && s >= SCORE_STRIP_MAX}
                                    onClick={() => adjustHoleScore(pl.id, hn, 1)}
                                  >
                                    +
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <button type="button" className="btn scorecardAddPl" onClick={addScorecardPlayer}>
                + Add player
              </button>
              <div className="muted" style={{ fontSize: 12 }}>
                Score is stored locally in your browser for this prototype screen.
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

