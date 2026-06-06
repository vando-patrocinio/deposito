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
  Polyline, Popup, Tooltip, Circle,
} from "react-leaflet";
import L from "leaflet";
import { api } from "@/api";
import { getBestPosition } from "@/utils/geo";
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

export default function RedeIaMapMobile({ onBack, technician }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [activeCto, setActiveCto] = useState(null);
  const [myPos, setMyPos] = useState(null);
  // iter157 — accuracy real do GPS + trail do dia
  const [myAccuracy, setMyAccuracy] = useState(null);
  const [trail, setTrail] = useState({ points: [], distance_m: 0,
                                              first: null, last: null });
  const [showTrail, setShowTrail] = useState(true);
  const [forceCenter, setForceCenter] = useState(null);
  const [layerCe, setLayerCe] = useState(true);
  const [layerCabos, setLayerCabos] = useState(true);
  const [bairroFilter, setBairroFilter] = useState(null);
  const [search, setSearch] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  // iter156 — raio de busca (km). 0 = sem filtro.
  const [radiusKm, setRadiusKm] = useState(5);
  const watchRef = useRef(null);

  const collabId = technician?.id || null;

  const load = async (gpsPos = null) => {
    setLoading(true); setErr("");
    try {
      let r = null;
      // 1ª tentativa: endpoint público com collab_id + raio (app do técnico)
      if (collabId) {
        try {
          const opts = {};
          if (gpsPos && radiusKm > 0) {
            opts.lat = gpsPos[0];
            opts.lng = gpsPos[1];
            opts.radius_km = radiusKm;
          }
          r = await api.redeIaMapDataPublic(collabId, opts);
        } catch (e0) {
          // fallback pros endpoints autenticados (admin testando)
          r = null;
        }
      }
      if (!r) {
        try {
          r = await api.collabRedeMapData();
        } catch (e1) {
          if (e1?.response?.status === 401 || e1?.response?.status === 404) {
            r = await api.redeIaMapData();
          } else {
            throw e1;
          }
        }
      }
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro");
    } finally { setLoading(false); }
  };

  // Carrega inicial; recarrega quando GPS chega ou raio muda
  useEffect(() => { load(myPos); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [myPos && Math.round(myPos[0] * 1000), myPos && Math.round(myPos[1] * 1000), radiusKm, collabId]);

  // Auto-centralizar no GPS+rede do dispositivo ao abrir o mapa.
  // iter183 — usa `getBestPosition` (helper híbrido): dispara GPS (alta) +
  // rede (rápido) em paralelo, resolve com o primeiro fix < 25m ou melhor
  // disponível no timeout. Garante que mesmo em prédio/sombra o mapa
  // abre na localização real do técnico em vez de cair no fallback do dataset
  // (que era o Rio de Janeiro por causa das CTOs de teste lá).
  useEffect(() => {
    let cancelled = false;
    getBestPosition({ cutoffM: 50, timeoutMs: 15000 })
      .then((fix) => {
        if (cancelled) return;
        const p = [fix.lat, fix.lng];
        setMyPos(p);
        setMyAccuracy(fix.accuracy || null);
        setForceCenter(p);
        setTimeout(() => setForceCenter(null), 1500);
      })
      .catch(() => { /* sem GPS+rede: cai pro center default do dataset */ });
    return () => { cancelled = true; };
  }, []);

  // Watch GPS contínuo + envio de pings ao backend (rastro do dia).
  // iter157 — Geolocation API com enableHighAccuracy + maximumAge=0
  // amostra direto do chip GPS; filtramos amostras com accuracy > 100m
  // (provavelmente fix por celular/wifi).
  useEffect(() => {
    if (!navigator.geolocation) return;
    let lastPingAt = 0;
    let lastPingPos = null;
    watchRef.current = navigator.geolocation.watchPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const acc = pos.coords.accuracy || null;
        setMyPos([lat, lng]);
        setMyAccuracy(acc);
        // Envia ping ao backend (bg, fire-and-forget)
        if (!collabId) return;
        if (acc && acc > 400) return; // iter226 — relaxado de 100→400m
        const now = Date.now();
        // Throttle: 1 ping por 3 segundos OU se andou > 8m
        let dist = 0;
        if (lastPingPos) {
          const R = 6371000;
          const φ1 = lastPingPos[0] * Math.PI / 180;
          const φ2 = lat * Math.PI / 180;
          const dφ = (lat - lastPingPos[0]) * Math.PI / 180;
          const dλ = (lng - lastPingPos[1]) * Math.PI / 180;
          const a = Math.sin(dφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(dλ/2)**2;
          dist = 2 * R * Math.asin(Math.sqrt(a));
        }
        const tooSoon = (now - lastPingAt) < 3000;
        const tooClose = dist < 8 && lastPingPos;
        if (tooSoon && tooClose) return;
        lastPingAt = now; lastPingPos = [lat, lng];
        try {
          await api._client.post(
            `/tech-tracking/public/ping/${collabId}`,
            { lat, lng, accuracy: acc,
              speed: pos.coords.speed, heading: pos.coords.heading });
        } catch { /* ignora — offline ou backend down */ }
      },
      () => {},
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
    );
    return () => {
      if (watchRef.current != null) {
        try { navigator.geolocation.clearWatch(watchRef.current); } catch { /* */ }
      }
    };
  }, [collabId]);

  // Carrega o trail (rastro) do dia com snap-to-road (OSRM)
  useEffect(() => {
    if (!collabId) return;
    let alive = true;
    const fetchTrail = async () => {
      try {
        // iter158 — endpoint /snap retorna trail + geometria casada nas vias
        const r = await api._client.get(
          `/tech-tracking/public/trail/${collabId}/snap`);
        if (alive) setTrail(r.data || { points: [], distance_m: 0 });
      } catch {
        // fallback: trail bruto (sem snap-to-road)
        try {
          const r = await api._client.get(
            `/tech-tracking/public/trail/${collabId}`);
          if (alive) setTrail(r.data || { points: [], distance_m: 0 });
        } catch { /* sem trail */ }
      }
    };
    fetchTrail();
    const tm = setInterval(fetchTrail, 20000);
    return () => { alive = false; clearInterval(tm); };
  }, [collabId]);

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

  const goToMyLocation = async () => {
    try {
      // iter183 — Helper híbrido (GPS+rede). Cutoff mais generoso (60m)
      // pra responder rápido mesmo em prédio/sombra.
      const fix = await getBestPosition({ cutoffM: 60, timeoutMs: 12000 });
      const p = [fix.lat, fix.lng];
      setMyPos(p);
      setForceCenter(p);
      setTimeout(() => setForceCenter(null), 1000);
    } catch (e) {
      await window.alert("Não foi possível obter GPS: " + (e.message || e));
    }
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
            {radiusKm > 0 && myPos ? ` · raio ${radiusKm}km` : ""}
            {myAccuracy ? ` · GPS ±${Math.round(myAccuracy)}m` : ""}
            {trail.distance_m > 0 ? ` · trilha ${(trail.distance_m/1000).toFixed(2)}km` : ""}
          </div>
        </div>
        <button onClick={() => load(myPos)}
                  data-testid="rede-mobile-reload"
                  style={{
                    padding: 6, border: 0, background: "transparent",
                    color: "#cbd5e1", cursor: "pointer",
                  }}>
          {loading ? <RefreshCw size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
        <button onClick={() => setShowSearch((v) => !v)}
                  data-testid="rede-mobile-search-toggle"
                  style={{
                    padding: 6, border: 0,
                    background: showSearch ? "#7c3aed" : "transparent",
                    color: "#cbd5e1", borderRadius: 6, cursor: "pointer",
                  }}><Search size={16} /></button>
      </div>

      {/* iter156 — Chips de raio (3 / 5 / 10 km / Sem limite) */}
      <div data-testid="rede-mobile-radius-chips" style={{
        padding: "6px 10px", background: "#0f172a",
        borderBottom: "1px solid #1e293b",
        display: "flex", gap: 5, overflowX: "auto", flexShrink: 0,
      }}>
        {[
          { v: 3, label: "3km" },
          { v: 5, label: "5km" },
          { v: 10, label: "10km" },
          { v: 0, label: "Tudo" },
        ].map((opt) => (
          <button key={opt.v}
                    data-testid={`rede-mobile-radius-${opt.v}`}
                    onClick={() => setRadiusKm(opt.v)}
                    style={{
                      padding: "5px 12px", borderRadius: 999, border: 0,
                      background: radiusKm === opt.v ? "#7c3aed" : "#1e293b",
                      color: radiusKm === opt.v ? "#fff" : "#cbd5e1",
                      fontSize: 11, fontWeight: 700, cursor: "pointer",
                      whiteSpace: "nowrap", flexShrink: 0,
                    }}>
            {opt.label}
          </button>
        ))}
        {/* iter157 — toggle do trail */}
        <button data-testid="rede-mobile-trail-toggle"
                   onClick={() => setShowTrail((v) => !v)}
                   style={{
                     padding: "5px 12px", borderRadius: 999, border: 0,
                     background: showTrail ? "#7c3aed" : "#1e293b",
                     color: showTrail ? "#fff" : "#cbd5e1",
                     fontSize: 11, fontWeight: 700, cursor: "pointer",
                     whiteSpace: "nowrap", flexShrink: 0,
                     marginLeft: "auto",
                   }}>
          Trilha {trail.points?.length || 0}
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
          <TileLayer url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png" />
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

          {/* iter157/158 — Trail (rastro) do dia: usa snap-to-road do OSM
              quando disponível (trail.snapped); cai pro polyline reto dos
              pings GPS quando o snap não estiver pronto. */}
          {showTrail && (trail.snapped?.length > 1
            || (trail.points && trail.points.length > 1)) && (
            <Polyline
              positions={
                trail.snapped && trail.snapped.length > 1
                  ? trail.snapped
                  : trail.points.map((p) => [p.lat, p.lng])
              }
              pathOptions={{
                color: "#7c3aed",
                weight: 5,
                opacity: 0.8,
                dashArray: trail.snapped ? null : "1 6",
                lineCap: "round",
                lineJoin: "round",
              }}
            >
              <Tooltip sticky>
                <div style={{ fontSize: 11 }}>
                  <strong>Trajeto de hoje</strong><br />
                  {trail.points.length} pontos · {(trail.distance_m / 1000).toFixed(2)} km
                  {trail.snapped ? (
                    <><br/><span style={{ color: "#7c3aed" }}>✓ Casado nas ruas (OSM)</span></>
                  ) : null}
                </div>
              </Tooltip>
            </Polyline>
          )}

          {/* Posição do técnico (azul pulsante) + círculo de accuracy */}
          {myPos && (
            <>
              {/* iter157 — círculo real de accuracy do GPS (raio em metros).
                  Mostra a precisão real do fix, em vez de raio fixo. */}
              {myAccuracy && myAccuracy < 200 && (
                <Circle center={myPos} radius={myAccuracy}
                          pathOptions={{
                            color: "#3b82f6", fillColor: "#3b82f6",
                            fillOpacity: 0.08, weight: 1, opacity: 0.4,
                          }} />
              )}
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
