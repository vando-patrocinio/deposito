/* FleetHistoryTab.js — Replay de rota de um veículo. */
import React, { useEffect, useState } from "react";
import { MapContainer, TileLayer, Polyline, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { api } from "@/api";

const startIcon = L.divIcon({
  className: "fleet-start",
  html: `<div style="width:24px;height:24px;background:#16a34a;border:2px solid #fff;border-radius:50%;color:white;text-align:center;font-weight:700;line-height:22px;font-size:11px;box-shadow:0 2px 4px rgba(0,0,0,.4)">▶</div>`,
  iconSize: [24, 24], iconAnchor: [12, 12],
});
const endIcon = L.divIcon({
  className: "fleet-end",
  html: `<div style="width:24px;height:24px;background:#dc2626;border:2px solid #fff;border-radius:50%;color:white;text-align:center;font-weight:700;line-height:22px;font-size:11px;box-shadow:0 2px 4px rgba(0,0,0,.4)">■</div>`,
  iconSize: [24, 24], iconAnchor: [12, 12],
});

const todayISO = () => new Date().toISOString().slice(0, 10);
const isoStart = (d) => `${d}T00:00:00`;
const isoEnd = (d) => `${d}T23:59:59`;

export default function FleetHistoryTab({ vehicles }) {
  const [vid, setVid] = useState(vehicles[0]?.id || "");
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!vid) return;
    setLoading(true); setErr("");
    api._client.get(
      `/fleet-tracking/positions/${vid}/history?from=${isoStart(date)}&to=${isoEnd(date)}`,
    ).then((r) => setData(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, [vid, date]);

  const path = (data?.points || []).map((p) => [p.lat, p.lng]);
  const start = path[0];
  const end = path[path.length - 1];

  return (
    <div data-testid="fleet-history-tab" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                     alignItems: "center" }}>
        <label style={{ fontSize: 12 }}>
          Veículo:
          <select value={vid} onChange={(e) => setVid(e.target.value)}
                   style={inp} data-testid="fleet-history-vid">
            <option value="">— escolha —</option>
            {vehicles.map((v) => (
              <option key={v.id} value={v.id}>
                {v.placa} {v.modelo ? `· ${v.modelo}` : ""}
              </option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 12 }}>
          Data:
          <input type="date" value={date}
                  onChange={(e) => setDate(e.target.value)}
                  style={inp} data-testid="fleet-history-date" />
        </label>
        {data?.stats && (
          <div style={{ display: "flex", gap: 16, marginLeft: 16,
                          fontSize: 13 }}>
            <span>📏 <b>{data.stats.total_km}</b> km</span>
            <span>⏱️ <b>{data.stats.moving_minutes}</b> min em movimento</span>
            <span>🛑 <b>{data.stats.stops}</b> paradas</span>
            <span>📍 <b>{data.stats.total_points}</b> pontos</span>
          </div>
        )}
      </div>
      {err && <div style={errBox}>{err}</div>}
      <div style={{ background: "white", border: "1px solid #e2e8f0",
                     borderRadius: 12, overflow: "hidden",
                     minHeight: 500 }}>
        {!vid ? (
          <div style={empty}>Escolha um veículo.</div>
        ) : loading ? (
          <div style={empty}>Carregando rota…</div>
        ) : !path.length ? (
          <div style={empty}>Nenhuma posição neste dia.</div>
        ) : (
          <MapContainer center={start || [-15.78, -47.93]} zoom={14}
                          style={{ height: 500 }}
                          bounds={path.length ? L.latLngBounds(path) : undefined}>
            <TileLayer attribution='&copy; OpenStreetMap'
                         url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <Polyline positions={path}
                       pathOptions={{ color: "#2563eb", weight: 4 }} />
            {start && <Marker position={start} icon={startIcon}>
              <Popup>Início</Popup>
            </Marker>}
            {end && <Marker position={end} icon={endIcon}>
              <Popup>Fim</Popup>
            </Marker>}
          </MapContainer>
        )}
      </div>
    </div>
  );
}

const inp = { padding: "6px 10px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13, marginLeft: 6 };
const empty = { padding: 32, textAlign: "center", color: "#94a3b8",
                 fontSize: 13 };
const errBox = { padding: 10, background: "#fee2e2", color: "#991b1b",
                  borderRadius: 6, fontSize: 12 };
