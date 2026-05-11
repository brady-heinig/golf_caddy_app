export type ScorecardPlayerRow = { id: string; name: string; scores: (number | null)[] };

function genPlayerId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `p-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function emptyScores18(): (number | null)[] {
  return Array.from({ length: 18 }, () => null);
}

/** Parse server-stored JSON array into player rows (18 holes each). */
export function parseScorecardPlayers(raw: string | null | undefined): ScorecardPlayerRow[] | null {
  if (raw == null || !String(raw).trim()) return null;
  try {
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr) || arr.length === 0) return null;
    const out: ScorecardPlayerRow[] = [];
    for (const row of arr) {
      if (!row || typeof row !== "object") continue;
      const o = row as Record<string, unknown>;
      const id = typeof o.id === "string" ? o.id : genPlayerId();
      const name = typeof o.name === "string" ? o.name : "Player";
      const scoresRaw = Array.isArray(o.scores) ? o.scores : [];
      const scores = emptyScores18();
      for (let i = 0; i < 18; i++) {
        const v = scoresRaw[i];
        scores[i] = typeof v === "number" && Number.isFinite(v) ? v : null;
      }
      out.push({ id, name, scores });
    }
    return out.length ? out : null;
  } catch {
    return null;
  }
}

export function primaryStrokeTotals(players: ScorecardPlayerRow[] | null): { strokes: number; holesPlayed: number } | null {
  if (!players?.length) return null;
  let strokes = 0;
  let holesPlayed = 0;
  for (const s of players[0].scores) {
    if (typeof s === "number") {
      strokes += s;
      holesPlayed += 1;
    }
  }
  return holesPlayed === 0 ? null : { strokes, holesPlayed };
}

/** Sum par for holes 1..18 where the player has a numeric score (vs par for holes played). */
export function primaryVsPar(players: ScorecardPlayerRow[] | null, holePars: number[]): string | null {
  const p0 = players?.[0];
  if (!p0 || !holePars.length) return null;
  let parSum = 0;
  let strokes = 0;
  let n = 0;
  for (let i = 0; i < 18; i++) {
    const s = p0.scores[i];
    if (typeof s !== "number") continue;
    strokes += s;
    const par = Number(holePars[i]);
    if (Number.isFinite(par) && par > 0) {
      parSum += par;
      n += 1;
    }
  }
  if (n === 0) return null;
  const diff = strokes - parSum;
  if (diff === 0) return "E";
  return diff > 0 ? `+${diff}` : `${diff}`;
}
