/* =============================================================
   PublicMapPage — mapa público (read-only) acessível via /rede-publica?t=TOKEN
   Sem login. Sem dados sensíveis: só CTOs anônimas + bairro + saúde.
============================================================= */
import React, { useEffect, useState, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { API } from "@/api";

const CTO_COLORS = {
  ok: "#16a34a", warning: "#ca8a04", critical: "#dc2626",
  no_data: "#94a3b8", unknown: "#94a3b8",
};
const CABLE_COLORS = {
  drop: "#94a3b8", "6fo": "#facc15", "12fo": "#fb923c",
  "24fo": "#ef4444", "48fo": "#8b5cf6", "96fo": "#0f172a",
};

function ctoIcon(status) {
  const color = CTO_COLORS[status] || CTO_COLORS.no_data;
  return L.divIcon({
    className: "cto-public",
    html: `<div style="
      width:26px;height:26px;border-radius:7px;
      background:${color};border:2px solid #000;
      box-shadow:0 2px 4px rgba(0,0,0,0.4);
      display:grid;place-items:center;color:#fff;font-weight:800;
      font-size:11px;">▦</div>`,
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}
function ceIcon() {
  return L.divIcon({
    className: "ce-public",
    html: `<div style="width:22px;height:22px;transform:rotate(45deg);
      background:#2563eb;border:2px solid #1e40af;"></div>`,
    iconSize: [22, 22], iconAnchor: [11, 11],
  });
}

function FitBounds({ ctos }) {
  const map = useMap();
  useEffect(() => {
    if (ctos.length === 0) return;
    const bounds = L.latLngBounds(ctos.map((c) => [c.lat, c.lng]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
  }, [ctos, map]);
  return null;
}

export default function PublicMapPage() {
  const token = useMemo(() => {
    const p = new URLSearchParams(window.location.search);
    return p.get("t") || "";
  }, []);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!token) { setErr("Link inválido (token ausente)."); return; }
    fetch(`${API}/rede-ia/map/public/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(setData)
      .catch((e) => setErr(e.message || "Falha ao carregar o mapa"));
  }, [token]);

  const ctosById = useMemo(() => {
    if (!data) return new Map();
    const m = new Map();
    data.ctos.forEach((c) => m.set(c.id, c));
    return m;
  }, [data]);
  const cesById = useMemo(() => {
    if (!data) return new Map();
    const m = new Map();
    data.ces.forEach((c) => m.set(c.id, c));
    return m;
  }, [data]);

  if (err) {
    return (
      <div style={errorPage}>
        <div style={{ fontSize: 56, marginBottom: 10 }}>🔒</div>
        <h1 style={{ fontSize: 22, margin: "0 0 8px", color: "#0f172a" }}>
          Acesso negado
        </h1>
        <p style={{ color: "#64748b", maxWidth: 380, textAlign: "center" }}>
          {err}
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={errorPage}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>⏳</div>
        Carregando mapa…
      </div>
    );
  }

  const criticalCount = data.ctos.filter((c) => c.health_status === "critical").length;
  const okCount = data.ctos.filter((c) => c.health_status === "ok").length;

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column",
                     fontFamily: "system-ui, sans-serif" }}>
      {/* Header */}
      <header style={{
        background: "linear-gradient(90deg,#5b21b6,#7c3aed)",
        color: "#fff", padding: "12px 20px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 8,
      }}>
        <div>
          <div style={{ fontSize: 11, opacity: 0.8, letterSpacing: 0.5,
                          textTransform: "uppercase" }}>
            SmartProv · Mapa Público
          </div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800 }}>
            Cobertura FTTH
            {data.vlan_filter && (
              <span style={{ marginLeft: 8, fontSize: 13, opacity: 0.8 }}>
                VLAN {data.vlan_filter}
              </span>
            )}
          </h1>
        </div>
        <div style={{ display: "flex", gap: 14, fontSize: 12 }}>
          <Stat label="CTOs ativas" value={data.ctos_count} />
          <Stat label="Bairros" value={data.by_bairro.length} />
          <Stat label="Críticas" value={criticalCount}
            color={criticalCount > 0 ? "#fecaca" : "#fff"} />
          <Stat label="Saudáveis" value={okCount} color="#bbf7d0" />
        </div>
      </header>

      {/* Map */}
      <div style={{ flex: 1, position: "relative" }}>
        <MapContainer center={[data.center.lat, data.center.lng]} zoom={14}
          style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; OpenStreetMap'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" maxZoom={19} />
          <FitBounds ctos={data.ctos} />

          {/* Cabos */}
          {data.cables.map((cab) => {
            let path = null;
            if (cab.segments && cab.segments.length >= 2) {
              path = cab.segments.map((s) => [s.lat, s.lng]);
            } else {
              const from = cab.from_type === "ce" ? cesById.get(cab.from_id) : ctosById.get(cab.from_id);
              const to = cab.to_type === "ce" ? cesById.get(cab.to_id) : ctosById.get(cab.to_id);
              if (from && to) path = [[from.lat, from.lng], [to.lat, to.lng]];
            }
            if (!path) return null;
            return (
              <Polyline key={cab.id} positions={path}
                pathOptions={{
                  color: CABLE_COLORS[cab.type] || "#64748b",
                  weight: cab.type === "drop" ? 1.5 : 3,
                  opacity: 0.75,
                  dashArray: cab.type === "drop" ? "6 6" : null,
                }} />
            );
          })}

          {/* CEs */}
          {data.ces.map((ce) => (
            <Marker key={ce.id} position={[ce.lat, ce.lng]} icon={ceIcon()}>
              <Tooltip direction="top" offset={[0, -12]}>
                {ce.name}
              </Tooltip>
            </Marker>
          ))}

          {/* CTOs */}
          {data.ctos.map((c) => (
            <Marker key={c.id} position={[c.lat, c.lng]} icon={ctoIcon(c.health_status)}>
              <Tooltip direction="top" offset={[0, -12]}>
                <div>
                  <strong>{c.name}</strong>
                  <br />
                  <span style={{ fontSize: 11, color: "#475569" }}>
                    {c.bairro} · {c.capacity} portas
                  </span>
                </div>
              </Tooltip>
            </Marker>
          ))}
        </MapContainer>

        {/* Legenda inferior esquerda */}
        <div style={{
          position: "absolute", bottom: 12, left: 12, zIndex: 1000,
          background: "rgba(255,255,255,0.96)", padding: 12, borderRadius: 10,
          fontSize: 12, border: "1px solid #e2e8f0",
          boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
        }}>
          <strong style={{ fontSize: 12 }}>Legenda</strong>
          <div style={{ display: "grid", gap: 4, marginTop: 6 }}>
            <Lg color="#16a34a" label="Saudável" sq />
            <Lg color="#ca8a04" label="Atenção" sq />
            <Lg color="#dc2626" label="Crítico" sq />
            <Lg color="#2563eb" label="CE" diamond />
          </div>
        </div>

        {/* Footer */}
        <div style={{
          position: "absolute", top: 12, right: 12, zIndex: 1000,
          background: "rgba(255,255,255,0.96)", padding: "8px 12px",
          borderRadius: 8, fontSize: 11, color: "#64748b",
          border: "1px solid #e2e8f0",
        }}>
          Read-only · sem dados sensíveis
        </div>
      </div>
    </div>
  );
}

const errorPage = {
  display: "grid", placeItems: "center", height: "100vh",
  flexDirection: "column", color: "#0f172a",
  fontFamily: "system-ui, sans-serif",
};
function Stat({ label, value, color }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 16, fontWeight: 800, color: color || "#fff",
                       lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 10, opacity: 0.8, textTransform: "uppercase",
                       letterSpacing: 0.3 }}>{label}</div>
    </div>
  );
}
function Lg({ color, label, sq, diamond }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{
        width: 14, height: 14, background: color, borderRadius: sq ? 3 : 0,
        transform: diamond ? "rotate(45deg)" : "none",
      }} />
      <span>{label}</span>
    </div>
  );
}
