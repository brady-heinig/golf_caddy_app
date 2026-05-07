"use client";

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function fmtNum(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return "—";
}

function fmtBool(v: unknown): string {
  return v === true ? "Yes" : v === false ? "No" : "—";
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="caddieStructuredIntelRow">
      <span className="caddieStructuredIntelRowLabel">{label}</span>
      <span className="caddieStructuredIntelRowValue">{value}</span>
    </div>
  );
}

function formatHazardLine(h: Record<string, unknown>): string {
  const gt = typeof h.golf_type === "string" ? h.golf_type.replace(/_/g, " ") : "hazard";
  const side = typeof h.side === "string" ? h.side : "";
  const line =
    typeof h.distance_to_shot_line_yds === "number"
      ? `about ${Math.round(h.distance_to_shot_line_yds)} yards off line`
      : "";
  const along =
    typeof h.approx_along_carry_from_ball_yds === "number"
      ? `about ${Math.round(h.approx_along_carry_from_ball_yds)} yards along track`
      : "";
  const bits = [side ? `${side} ${gt}` : gt, line, along].filter(Boolean);
  return bits.join(" · ");
}

function formatClubPick(pick: unknown): string {
  if (!isRecord(pick)) return "—";
  const club = pick.club;
  const listed = pick.listed_carry_yds;
  const target = pick.adjusted_plays_like_yds;
  const fb = pick.fallback;
  let s =
    typeof club === "string" ? `${club}` : "Unknown club";
  if (typeof listed === "number") {
    s += ` (${listed} yard listed carry)`;
  }
  if (typeof target === "number") {
    s += ` vs ${target} yards adjusted`;
  }
  if (typeof fb === "string") {
    s += ` [${fb}]`;
  }
  return s;
}

function summarizeLieDetect(ld: unknown): string | null {
  if (!isRecord(ld) || Object.keys(ld).length === 0) return null;
  const detail = ld.detail;
  const src = ld.source;
  const bits: string[] = [];
  if (typeof src === "string") bits.push(src.replace(/_/g, " "));
  if (typeof detail === "string") bits.push(detail.replace(/_/g, " "));
  return bits.length ? bits.join(" · ") : null;
}

function HazardBlock({
  title,
  items,
  emptyHint,
}: {
  title: string;
  items: unknown[];
  emptyHint: string;
}) {
  if (!items.length) {
    return (
      <section className="caddieStructuredIntelSection">
        <h4 className="caddieStructuredIntelH">{title}</h4>
        <p className="caddieStructuredIntelMuted">{emptyHint}</p>
      </section>
    );
  }
  const max = 6;
  const shown = items.slice(0, max);
  const rest = items.length - shown.length;
  return (
    <section className="caddieStructuredIntelSection">
      <h4 className="caddieStructuredIntelH">{title}</h4>
      <ul className="caddieStructuredIntelList">
        {shown.map((item, i) => (
          <li key={i}>{isRecord(item) ? formatHazardLine(item) : String(item)}</li>
        ))}
      </ul>
      {rest > 0 ? (
        <p className="caddieStructuredIntelMuted">{`${rest} more not listed.`}</p>
      ) : null}
    </section>
  );
}

export function CaddieStructuredIntelSummary({ intel }: { intel: unknown }) {
  if (!isRecord(intel)) return null;

  const pp = intel.player_position;
  const lieSit = intel.lie_and_situation;
  const landing = intel.intended_landing_target;
  const bunkers = Array.isArray(intel.bunkers_near_tee_shot_corridor)
    ? (intel.bunkers_near_tee_shot_corridor as unknown[])
    : [];
  const trouble = Array.isArray(intel.major_trouble_near_corridor)
    ? (intel.major_trouble_near_corridor as unknown[])
    : [];
  const fw = intel.fairway_at_landing;
  const shapeSet = intel.shot_shape_from_settings;
  const clubSug = intel.club_suggestion;
  const next = intel.next_shot_if_plan_works;

  const lieMeta = isRecord(lieSit) ? lieSit.lie_detection : undefined;
  const lieDetectLine = summarizeLieDetect(lieMeta);

  const fwInside =
    fw != null && isRecord(fw) && typeof fw.landing_inside_fairway_polygon === "boolean"
      ? fw.landing_inside_fairway_polygon
      : null;
  const fwWidth =
    fw != null && isRecord(fw) && typeof fw.width_yds === "number" ? fw.width_yds : null;
  const fwNote = fw != null && isRecord(fw) && typeof fw.note === "string" ? fw.note : null;

  const landingHow =
    landing != null && isRecord(landing) && typeof landing.how === "string" ? landing.how : null;

  const shapesNorm =
    shapeSet != null && isRecord(shapeSet) ? shapeSet.driver_woods_irons_settings : undefined;
  let shapesLine = "";
  if (isRecord(shapesNorm)) {
    const d = shapesNorm.driver;
    const w = shapesNorm.woods;
    const ir = shapesNorm.irons;
    const bits = [];
    if (typeof d === "string") bits.push(`driver ${d}`);
    if (typeof w === "string") bits.push(`woods/hybrid ${w}`);
    if (typeof ir === "string") bits.push(`irons/wedges ${ir}`);
    shapesLine = bits.join(" · ");
  }

  const hazardousGreen =
    clubSug != null &&
    isRecord(clubSug) &&
    isRecord(clubSug.hazard_check_full_line_to_green)
      ? clubSug.hazard_check_full_line_to_green
      : null;

  return (
    <div className="caddieStructuredIntelBody">
      {pp != null && isRecord(pp) ? (
        <section className="caddieStructuredIntelSection">
          <h4 className="caddieStructuredIntelH">Player position</h4>
          <Row label="Distance to pin" value={`about ${fmtNum(pp.distance_to_pin_yds)} yards`} />
          <Row label="From tee marker" value={`about ${fmtNum(pp.distance_from_tee_marker_yds)} yards`} />
          <Row label="Near tee box" value={fmtBool(pp.near_tee_box)} />
          <Row label="Bearing to pin" value={`${fmtNum(pp.bearing_to_pin_deg)}°`} />
        </section>
      ) : null}

      {lieSit != null && isRecord(lieSit) ? (
        <section className="caddieStructuredIntelSection">
          <h4 className="caddieStructuredIntelH">Lie &amp; situation</h4>
          <Row label="Lie (map)" value={typeof lieSit.lie === "string" ? lieSit.lie : "—"} />
          <Row label="Par" value={fmtNum(lieSit.par)} />
          <Row label="Shot type" value={typeof lieSit.shot_type === "string" ? lieSit.shot_type : "—"} />
          {typeof lieSit.note === "string" && lieSit.note.trim() ? (
            <p className="caddieStructuredIntelNote">{lieSit.note}</p>
          ) : null}
          {lieDetectLine ? <Row label="Lie detection" value={lieDetectLine} /> : null}
        </section>
      ) : null}

      {landing != null && isRecord(landing) ? (
        <section className="caddieStructuredIntelSection">
          <h4 className="caddieStructuredIntelH">Intended landing</h4>
          <Row label="Modeled carry" value={`about ${fmtNum(landing.modeled_carry_distance_yds)} yards`} />
          {landingHow ? <Row label="How set" value={landingHow.replace(/_/g, " ")} /> : null}
          {typeof landing.fraction_along_pin_vector === "number" ? (
            <Row label="Along pin vector (fraction)" value={String(landing.fraction_along_pin_vector)} />
          ) : null}
          {typeof landing.fraction === "number" ? (
            <Row label="Along pin (fraction)" value={String(landing.fraction)} />
          ) : null}
          {typeof landing.assumed_carry_club_yd === "number" ? (
            <Row label="Assumed carry (model)" value={`about ${Math.round(landing.assumed_carry_club_yd)} yards`} />
          ) : null}
        </section>
      ) : null}

      <section className="caddieStructuredIntelSection">
        <h4 className="caddieStructuredIntelH">Fairway at landing</h4>
        {fwWidth != null ? <Row label="Approx. width" value={`about ${Math.round(fwWidth)} yards`} /> : null}
        {fwInside != null ? <Row label="Landing inside fairway polygon" value={fwInside ? "Yes" : "No"} /> : null}
        {fwNote ? <p className="caddieStructuredIntelMuted">{fwNote}</p> : null}
        {fwWidth == null && fwInside == null && !fwNote ? (
          <p className="caddieStructuredIntelMuted">No fairway width from OSM at this landing.</p>
        ) : null}
      </section>

      <HazardBlock
        title="Bunkers near corridor"
        items={bunkers}
        emptyHint="None modeled near this corridor."
      />
      <HazardBlock
        title="Water / OB near corridor"
        items={trouble}
        emptyHint="None modeled near this corridor."
      />

      {shapeSet != null && isRecord(shapeSet) ? (
        <section className="caddieStructuredIntelSection">
          <h4 className="caddieStructuredIntelH">Shot shape (Settings)</h4>
          <Row
            label="Bucket for this club"
            value={typeof shapeSet.club_category === "string" ? shapeSet.club_category : "—"}
          />
          <Row label="Shape used" value={typeof shapeSet.shape === "string" ? shapeSet.shape : "—"} />
          {shapesLine ? <Row label="Your preferences" value={shapesLine} /> : null}
        </section>
      ) : null}

      {clubSug != null && isRecord(clubSug) ? (
        <section className="caddieStructuredIntelSection">
          <h4 className="caddieStructuredIntelH">Club suggestion (computed)</h4>
          <Row label="Bag match for plays-like" value={formatClubPick(clubSug.bag_match_for_adjusted_plays_like)} />
          <Row
            label="Longest driver / wood carry"
            value={
              typeof clubSug.longest_driver_or_wood_carry_yds === "number"
                ? `about ${clubSug.longest_driver_or_wood_carry_yds} yards`
                : "—"
            }
          />
          <Row label="Go for green (driver/wood)" value={fmtBool(clubSug.go_for_it)} />
          {typeof clubSug.go_for_it_rationale === "string" ? (
            <p className="caddieStructuredIntelNote">{clubSug.go_for_it_rationale}</p>
          ) : null}
          {hazardousGreen != null ? (
            <>
              <Row
                label="Severe hazard on line to green"
                value={fmtBool(hazardousGreen.severe_hazard_tight_to_direct_line)}
              />
              {typeof hazardousGreen.detail === "string" && hazardousGreen.detail ? (
                <p className="caddieStructuredIntelMuted">{hazardousGreen.detail}</p>
              ) : null}
            </>
          ) : null}
          <Row
            label="Ideal yards left (next shot)"
            value={
              typeof clubSug.ideal_remaining_yds_next_shot === "number"
                ? `about ${clubSug.ideal_remaining_yds_next_shot} yards`
                : "—"
            }
          />
          {typeof clubSug.ideal_remaining_note === "string" ? (
            <p className="caddieStructuredIntelNote">{clubSug.ideal_remaining_note}</p>
          ) : null}
        </section>
      ) : null}

      {next != null && isRecord(next) ? (
        <section className="caddieStructuredIntelSection">
          <h4 className="caddieStructuredIntelH">Next shot (if plan works)</h4>
          <Row
            label="Yards remaining to pin"
            value={`about ${fmtNum(next.remaining_distance_to_pin_yds)} yards`}
          />
          <Row label="Bag pick for that distance" value={formatClubPick(next.club_pick_same_rule)} />
          {typeof next.summary === "string" ? <p className="caddieStructuredIntelNote">{next.summary}</p> : null}
        </section>
      ) : null}
    </div>
  );
}
