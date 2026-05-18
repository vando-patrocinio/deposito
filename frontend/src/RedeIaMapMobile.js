/*
RedeIaMapMobile.js — Mapa da Rede IA otimizado pra mobile (Lousa Mobile).

Mostra tudo que está cadastrado na Rede IA:
  • CTOs (marker roxo) — toque abre CTOInteractionModal
  • CEs / Cabos / Bairros (quando presentes em /rede-ia/map/data)
  • Posição do técnico em tempo real (azul pulsante)
  • Botão GPS pra centralizar na própria posição (estilo Salva-Locais/Uber)
  • Filtro rápido por bairro (chips no topo)
  • Cards de stats (CTOs total, ocupadas, livres)

Layout fullscreen sem cabeçalho — usado dentro da página /rede-mobile do
app do técnico.
*/
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer, TileLayer, useMap, CircleMarker, Marker,
  Polyline, Popup, Tooltip,
} from "react-leaflet";
import L from "leaflet";
import { api } from "@/api";
import { Crosshair, Layers, Search, X, RefreshCw, MapPin } from "lucide-react";
import CTOInteractionModal from "@/CTOInteractionModal";

const DEFAULT_CENTER = [-22.9068, -43.1729];

/* Ícone customizado pra CTO — círculo roxo numerado */
function ctoIcon(label, status) {
  const color = status === "Cadastrada"
    ? "#10b981"
    : status === "validation_pending"
      ? "#f59e0b"
      : "#8b5cf6";
  return L.divIcon({
    html: `<div style="
      background:${color};color:#fff;font-weight:800;
      width:34px;height:34px;border-radius:50%;
      display:flex;align-items:center;justify-content:center;
      border:3px solid #fff;
      box-shadow:0 3px 8px rgba(0,0,0,0.35);
      font-size:11px;font-family:system-ui;letter-spacing:-0.3px;
    ">${label || "?"}</div>`,
    className: "",
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function ceIcon() {
  return L.divIcon({
    html: `<div style="
      background:#0ea5e9;color:#fff;
      width:18px;height:18px;border-radius:4px;
      border:2px solid #fff;box-shadow:0 2px 5px rgba(0,0,0,0.3);
    "></div>`,
    className: "", iconSize: [18, 18], iconAnchor: [9, 9],
  });
}

/* Componente pra recentrar mapa quando recebe nova posição */
function Recenter({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.flyTo(position, Math.max(map.getZoom(), 16), { duration: 0.8 });
  }, [position, map]);
  return null;
}

export default function RedeIaMapMobile({ onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [activeCto, setActiveCto] = useState(null);
  const [myPos, setMyPos] = useState(null);
  const [forceCenter, setForceCenter] = useState(null);
  const [layerCe, setLayerCe] = useState(true);
  const [layerCabos, setLayerCabos] = useState(true);
  const [bairroFilter, setBairroFilter] = useState(null);
  const [search, setSearch] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const watchRef = useRef(null);

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.redeIaMapData();
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  // Watch GPS continuamente quando o componente está ativo
  useEffect(() => {
    if (!navigator.geolocation) return;
    watchRef.current = navigator.geolocation.watchPosition(
      (pos) => setMyPos([pos.coords.latitude, pos.coords.longitude]),
      () => {},
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 },
    );
    return () => {
      if (watchRef.current != null) {
        try { navigator.geolocation.clearWatch(watchRef.current); } catch { /* */ }
      }
    };
  }, []);

  const bairros = useMemo(() => {
    const set = new Set();
    (data?.ctos || []).forEach((c) => {
      const b = c.address?.bairro || c.bairro || c.sigla_bairro || c.sigla;
      if (b) set.add(b);
    });
    return Array.from(set).sort();
  }, [data]);

  const ctosFiltered = useMemo(() => {
    let list = data?.ctos || [];
    if (bairroFilter) {
      list = list.filter((c) =>
        (c.address?.bairro || c.bairro || c.sigla_bairro || c.sigla) === bairroFilter,
      );
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((c) => (c.name || "").toLowerCase().includes(q));
    }
    // Endpoint /map/data já achata lat/lng no nível raiz e exclui sem GPS,
    // mas filtramos defensivo (cobre formato {gps:{lat,lng}} se vier de cache).
    return list.filter((c) => (c.lat != null && c.lng != null)
                                || (c.gps?.lat && c.gps?.lng));
  }, [data, bairroFilter, search]);

  const stats = useMemo(() => {
    const ctos = data?.ctos || [];
    const hasGps = (c) => (c.lat != null && c.lng != null) || c.gps?.lat;
    return {
      total: ctos.length,
      ativas: ctos.filter((c) => c.status === "approved" || c.status === "Cadastrada").length,
      pendentes: ctos.filter((c) => c.status === "pending_validation"
                                || c.status === "validation_pending").length,
      sem_gps: ctos.filter((c) => !hasGps(c)).length,
    };
  }, [data]);

  const goToMyLocation = () => {
    if (!navigator.geolocation) {
      alert("Geolocalização não suportada.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const p = [pos.coords.latitude, pos.coords.longitude];
        setMyPos(p);
        setForceCenter(p);
        setTimeout(() => setForceCenter(null), 1000);
      },
      (e) => alert("Não foi possível obter GPS: " + e.message),
      { enableHighAccuracy: true, timeout: 15000 },
    );
  };

  const center = forceCenter || myPos
    || (data?.center && [data.center.lat, data.center.lng])
    || (ctosFiltered[0]
        ? [ctosFiltered[0].lat ?? ctosFiltered[0].gps.lat,
            ctosFiltered[0].lng ?? ctosFiltered[0].gps.lng]
        : null)
    || DEFAULT_CENTER;

  return (
    <div data-testid="rede-mobile-map"
          style={{
            position: "fixed", inset: 0, zIndex: 30,
            background: "#0f172a",
            display: "flex", flexDirection: "column",
          }}>
      {/* Header */}
      <div style={{
        padding: "10px 12px", background: "#0f172a", color: "#fff",
        display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid #1e293b",
      }}>
        {onBack && (
          <button onClick={onBack}
                    data-testid="rede-mobile-back"
                    style={{
                      padding: 6, border: 0, background: "transparent",
                      color: "#cbd5e1", cursor: "pointer",
                    }}>
            <X size={18} />
          </button>
        )}
        <MapPin size={16} color="#a78bfa" />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, fontSize: 13 }}>Mapa da Rede</div>
          <div style={{ fontSize: 10.5, color: "#94a3b8" }}>
            {stats.total} CTOs · {stats.ativas} ativas
            {stats.pendentes ? ` · ${stats.pendentes} pendente(s)` : ""}
          </div>
        </div>
        <button onClick={() => setShowSearch((v) => !v)}
                  data-testid="rede-mobile-search-toggle"
                  style={{
                    padding: 6, border: 0,
                    background: showSearch ? "#7c3aed" : "transparent",
                    color: "#cbd5e1", borderRadius: 6, cursor: "pointer",
                  }}><Search size={16} /></button>
        <button onClick={load}
                  data-testid="rede-mobile-reload"
                  style={{
                    padding: 6, border: 0, background: "transparent",
                    color: "#cbd5e1", cursor: "pointer",
                  }}>
          {loading ? <RefreshCw size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      </div>

      {/* Busca expansível */}
      {showSearch && (
        <div style={{ padding: 8, background: "#1e293b" }}>
          <input
            data-testid="rede-mobile-search-input"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar CTO (nome, sigla)…"
            autoFocus
            style={{
              width: "100%", padding: "8px 12px",
              border: 0, borderRadius: 8, fontSize: 13,
              background: "#0f172a", color: "#e2e8f0",
              boxSizing: "border-box",
            }}
          />
        </div>
      )}

      {/* Chips de bairros */}
      {bairros.length > 0 && (
        <div style={{
          padding: "8px 10px", background: "#0f172a",
          display: "flex", gap: 6, overflowX: "auto",
          borderBottom: "1px solid #1e293b",
        }} data-testid="rede-mobile-bairros">
          <button onClick={() => setBairroFilter(null)}
                    style={chip(bairroFilter === null)}>
            Todos
          </button>
          {bairros.map((b) => (
            <button key={b}
                      onClick={() => setBairroFilter(b === bairroFilter ? null : b)}
                      data-testid={`rede-mobile-bairro-${b}`}
                      style={chip(bairroFilter === b)}>
              {b}
            </button>
          ))}
        </div>
      )}

      {err && (
        <div style={{ padding: 10, background: "#fee2e2", color: "#991b1b",
                        fontSize: 12 }}>{err}</div>
      )}

      {/* Mapa */}
      <div style={{ flex: 1, position: "relative" }}>
        <MapContainer
          center={center}
          zoom={15}
          minZoom={4}
          maxZoom={20}
          style={{ height: "100%", width: "100%" }}
          zoomControl={true}
          attributionControl={false}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <Recenter position={forceCenter} />

          {/* Cabos (linhas) */}
          {layerCabos && (data?.cables || data?.cabos || []).map((cabo) => {
            const pts = (cabo.path || cabo.points || [])
              .filter((p) => p && p.lat && p.lng)
              .map((p) => [p.lat, p.lng]);
            if (pts.length < 2) return null;
            return (
              <Polyline key={cabo.id} positions={pts}
                          pathOptions={{
                            color: cabo.color || "#fbbf24",
                            weight: 3, opacity: 0.85,
                          }}>
                <Tooltip>{cabo.name || "Cabo"} · {cabo.fibras || ""}</Tooltip>
              </Polyline>
            );
          })}

          {/* CEs (caixas emendas) */}
          {layerCe && (data?.ces || []).map((e) => {
            const lat = e.lat ?? e.gps?.lat;
            const lng = e.lng ?? e.gps?.lng;
            if (lat == null || lng == null) return null;
            return (
              <Marker key={e.id}
                         position={[lat, lng]}
                         icon={ceIcon()}>
                <Popup>
                  <div style={{ fontSize: 12 }}>
                    <strong>{e.name || "CE"}</strong>
                    {e.address?.bairro && <div>{e.address.bairro}</div>}
                  </div>
                </Popup>
              </Marker>
            );
          })}

          {/* CTOs (markers principais) */}
          {ctosFiltered.map((c) => {
            const lat = c.lat ?? c.gps?.lat;
            const lng = c.lng ?? c.gps?.lng;
            if (lat == null || lng == null) return null;
            const lbl = c.number != null ? String(c.number)
              : (c.name || "?").replace(/[^\d]+/g, "").slice(-3) || "?";
            return (
              <Marker key={c.id}
                         position={[lat, lng]}
                         icon={ctoIcon(lbl, c.status)}
                         eventHandlers={{
                           click: () => setActiveCto({
                             id: c.id, name: c.name, capacity: c.capacity,
                           }),
                         }}>
                <Tooltip>{c.name}</Tooltip>
              </Marker>
            );
          })}

          {/* Posição do técnico (azul pulsante) */}
          {myPos && (
            <>
              <CircleMarker center={myPos} radius={14}
                               pathOptions={{
                                 color: "#3b82f6",
                                 fillColor: "#3b82f6",
                                 fillOpacity: 0.15, weight: 2,
                               }} />
              <CircleMarker center={myPos} radius={6}
                               pathOptions={{
                                 color: "#fff",
                                 fillColor: "#3b82f6",
                                 fillOpacity: 1, weight: 2,
                               }} />
            </>
          )}
        </MapContainer>

        {/* FAB GPS (canto inferior direito) */}
        <button onClick={goToMyLocation}
                  data-testid="rede-mobile-locate-btn"
                  style={{
                    position: "absolute", bottom: 90, right: 14, zIndex: 600,
                    padding: 14, border: 0, borderRadius: 999,
                    background: "#fff", color: "#0f172a",
                    boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
                    cursor: "pointer",
                  }}>
          <Crosshair size={20} />
        </button>

        {/* Toggle camadas (canto inferior esquerdo) */}
        <button onClick={() => {
                    if (layerCe && layerCabos) { setLayerCe(false); setLayerCabos(true); }
                    else if (!layerCe && layerCabos) { setLayerCabos(false); }
                    else { setLayerCe(true); setLayerCabos(true); }
                  }}
                  data-testid="rede-mobile-layers-toggle"
                  title="Alternar camadas"
                  style={{
                    position: "absolute", bottom: 90, left: 14, zIndex: 600,
                    padding: 10, border: 0, borderRadius: 999,
                    background: "#fff",
                    color: layerCabos ? "#8b5cf6" : "#94a3b8",
                    boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
                    cursor: "pointer",
                  }}>
          <Layers size={18} />
        </button>
      </div>

      {/* Rodapé de stats */}
      <div style={{
        padding: "8px 12px", background: "#0f172a",
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
        gap: 6, color: "#fff", borderTop: "1px solid #1e293b",
      }}>
        <StatPill label="Total" value={stats.total} color="#a78bfa" />
        <StatPill label="OK" value={stats.ativas} color="#10b981" />
        <StatPill label="Pend." value={stats.pendentes} color="#f59e0b" />
        <StatPill label="Sem GPS" value={stats.sem_gps} color="#64748b" />
      </div>

      {/* Modal interação CTO (clientes + cadastrar) */}
      {activeCto && (
        <CTOInteractionModal ctoId={activeCto.id} ctoMeta={activeCto}
                                onClose={() => setActiveCto(null)} />
      )}
    </div>
  );
}

function StatPill({ label, value, color }) {
  return (
    <div style={{
      padding: "4px 6px", background: "#1e293b", borderRadius: 6,
      textAlign: "center",
    }}>
      <div style={{ fontSize: 9, color: "#94a3b8",
                      textTransform: "uppercase", letterSpacing: 0.3 }}>
        {label}
      </div>
      <div style={{ fontSize: 14, fontWeight: 800, color }}>
        {value}
      </div>
    </div>
  );
}

function chip(active) {
  return {
    flex: "0 0 auto", padding: "5px 11px", border: 0, borderRadius: 14,
    background: active ? "#7c3aed" : "#1e293b",
    color: active ? "#fff" : "#cbd5e1",
    fontSize: 11, fontWeight: 600, cursor: "pointer",
    whiteSpace: "nowrap",
  };
}
