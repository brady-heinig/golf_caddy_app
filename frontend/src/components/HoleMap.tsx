"use client";

import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { useMemo } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer } from "react-leaflet";

type LL = { lat: number; lon: number };

type Hazard = { type?: string; lat: number; lon: number; note?: string };

export type HoleData = {
  number: number;
  tee: LL;
  green_center: LL;
  green_front: LL;
  green_back: LL;
  hazards?: Hazard[];
};

const icon = (color: string) =>
  new L.DivIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 6px rgba(0,0,0,.35)"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7]
  });

export function HoleMap({
  hole,
  player
}: {
  hole: HoleData;
  player?: { lat: number; lon: number } | null;
}) {
  const center = useMemo(() => [hole.green_center.lat, hole.green_center.lon] as [number, number], [hole]);
  const tee = [hole.tee.lat, hole.tee.lon] as [number, number];
  const green = [hole.green_center.lat, hole.green_center.lon] as [number, number];
  const front = [hole.green_front.lat, hole.green_front.lon] as [number, number];
  const back = [hole.green_back.lat, hole.green_back.lon] as [number, number];
  const playerPt = player ? ([player.lat, player.lon] as [number, number]) : null;

  return (
    <div style={{ height: 420, width: "100%", borderRadius: 10, overflow: "hidden", border: "1px solid #ddd" }}>
      <MapContainer center={center} zoom={16} style={{ height: "100%", width: "100%" }}>
        <TileLayer attribution='&copy; OpenStreetMap' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />

        <Marker position={tee} icon={icon("#007AFF")}>
          <Popup>Tee</Popup>
        </Marker>
        <Marker position={green} icon={icon("#34C759")}>
          <Popup>Green center</Popup>
        </Marker>
        <Marker position={front} icon={icon("#8E8E93")}>
          <Popup>Green front</Popup>
        </Marker>
        <Marker position={back} icon={icon("#8E8E93")}>
          <Popup>Green back</Popup>
        </Marker>

        <Polyline positions={[tee, green]} pathOptions={{ color: "white", weight: 4, opacity: 0.9 }} />

        {(hole.hazards || []).slice(0, 25).map((h, idx) => (
          <Marker key={idx} position={[h.lat, h.lon]} icon={icon("#FFCC00")}>
            <Popup>
              <b>{h.type || "hazard"}</b>
              <div>{h.note || ""}</div>
            </Popup>
          </Marker>
        ))}

        {playerPt ? (
          <Marker position={playerPt} icon={icon("#0A84FF")}>
            <Popup>Your location (GPS)</Popup>
          </Marker>
        ) : null}
      </MapContainer>
    </div>
  );
}

