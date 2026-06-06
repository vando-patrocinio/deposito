/*
 * FleetTrackingPage.js — Dashboard moderno de rastreamento, inspirado em
 * Wialon / Samsara / Geotab.
 *
 * Estrutura (desktop):
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ Header: título · KPI strip · botões (Emergência, +Veículo)   │
 *   ├──────────────────────────────────────────────────────────────┤
 *   │ Tabs (Tempo real · Histórico · Cercas · Alertas · …)         │
 *   ├──────────┬─────────────────────────────────────┬─────────────┤
 *   │ Asset    │                                       │ Inspector  │
 *   │ list     │           Live Map (Leaflet)          │ (selected) │
 *   │ search+  │                                       │            │
 *   │ filtros  │                                       │            │
 *   └──────────┴─────────────────────────────────────┴─────────────┘
 *
 * Mobile (< 768px):
 *   - KPI strip vira scroll horizontal
 *   - Asset list e Inspector viram drawers (bottom sheet)
 *   - Map full width
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, Circle, Polygon,
         useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/api";
import FleetVehicleForm from "@/fleet/FleetVehicleForm";
import FleetGpsWizard from "@/fleet/FleetGpsWizard";
import FleetGeofencesTab from "@/fleet/FleetGeofencesTab";
import FleetEventsTab from "@/fleet/FleetEventsTab";
import FleetReportsTab from "@/fleet/FleetReportsTab";
import FleetTenantsTab from "@/fleet/FleetTenantsTab";
import FleetHistoryTab from "@/fleet/FleetHistoryTab";
import FleetEmergencyBlockModal from "@/fleet/FleetEmergencyBlockModal";
import "@/fleet/fleet-tracking.css";

// ───────────────────────────── helpers ─────────────────────────────
const makeIcon = (color, heading = 0, label = "") => {
  const html = `
    <div class="ft-marker" style="background:${color}">
      <div class="ft-marker-arrow" style="transform:rotate(${heading}deg)">▲</div>
      ${label ? `<div class="ft-marker-label">${label}</div>` : ""}
    </div>`;
  return L.divIcon({
    className: "ft-marker-wrap",
    html,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });
};

function FitToMarkers({ vehicles }) {
  const map = useMap();
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current) return;
    const valid = vehicles.filter((v) => v.lat && v.lng);
    if (!valid.length) return;
    const bounds = L.latLngBounds(valid.map((v) => [v.lat, v.lng]));
    map.fitBounds(bounds.pad(0.2));
    fitted.current = true;
  }, [vehicles, map]);
  return null;
}

function FlyTo({ position }) {
  const map = useMap();
  useEffect(() => {
    if (!position) return;
    map.flyTo(position, Math.max(map.getZoom(), 15), { duration: 0.7 });
  }, [position, map]);
  return null;
}

// Estado semântico: moving / idle / offline / overspeed
function vehicleStatus(v) {
  if (!v.online) return "offline";
  if ((v.speed_kmh || 0) > (v.speed_limit_kmh || 80)) return "overspeed";
  if ((v.speed_kmh || 0) > 3) return "moving";
  return "idle";
}

const STATUS_COLOR = {
  moving: "#10b981",      // emerald-500
  idle: "#f59e0b",        // amber-500
  offline: "#64748b",     // slate-500
  overspeed: "#ef4444",   // red-500
};

const STATUS_LABEL = {
  moving: "Em movimento",
  idle: "Parado (ignição)",
  offline: "Offline",
  overspeed: "Excesso vel.",
};

const fmtMin = (ts) => {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    const min = Math.round((Date.now() - d.getTime()) / 60000);
    if (min < 1) return "agora";
    if (min < 60) return `${min} min`;
    if (min < 1440) return `${Math.floor(min / 60)}h ${min % 60}m`;
    return `${Math.floor(min / 1440)}d`;
  } catch { return "—"; }
};

// ───────────────────────────── component ─────────────────────────────
export default function FleetTrackingPage() {
  const [tab, setTab] = useState("live");
  const [vehicles, setVehicles] = useState([]);
  const [selectedVid, setSelectedVid] = useState(null);
  const [err, setErr] = useState("");
  const [showForm, setShowForm] = useState(null);
  const [showEmergency, setShowEmergency] = useState(false);
  const [geofences, setGeofences] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(null);  // null|moving|idle|offline|overspeed
  const [mapStyle, setMapStyle] = useState("light");       // light|dark|satellite
  const [drawerOpen, setDrawerOpen] = useState(false);     // mobile asset drawer
  const [inspectorOpen, setInspectorOpen] = useState(true);

  const refresh = async () => {
    try {
      const r = await api._client.get("/fleet-tracking/positions/live")
        .then((x) => x.data);
      setVehicles(r);
      setErr("");
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };
  const refreshGeofences = async () => {
    try {
      const r = await api._client.get("/fleet-tracking/geofences")
        .then((x) => x.data);
      setGeofences(r);
    } catch { /* */ }
  };

  useEffect(() => {
    refresh(); refreshGeofences();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  // KPIs agregados
  const kpis = useMemo(() => {
    const out = { total: vehicles.length, moving: 0, idle: 0,
                    offline: 0, overspeed: 0 };
    vehicles.forEach((v) => { out[vehicleStatus(v)] += 1; });
    return out;
  }, [vehicles]);

  const filtered = useMemo(() => {
    let arr = vehicles;
    if (statusFilter) arr = arr.filter((v) => vehicleStatus(v) === statusFilter);
    if (search) {
      const q = search.toLowerCase();
      arr = arr.filter((v) => (v.placa || "").toLowerCase().includes(q)
        || (v.modelo || "").toLowerCase().includes(q));
    }
    return arr;
  }, [vehicles, statusFilter, search]);

  const selected = useMemo(
    () => vehicles.find((v) => v.id === selectedVid),
    [vehicles, selectedVid],
  );

  const center = useMemo(() => {
    const valid = vehicles.filter((v) => v.lat && v.lng);
    if (selected?.lat) return [selected.lat, selected.lng];
    if (valid.length) return [valid[0].lat, valid[0].lng];
    return [-15.78, -47.93];
  }, [vehicles, selected]);

  const tileUrl = mapStyle === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
    : mapStyle === "satellite"
      ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
      : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png";

  // ────────────────── render ──────────────────
  return (
    <div className={`ft-page ft-theme-${mapStyle === "dark" ? "dark" : "light"}`}
          data-testid="fleet-tracking-page">
      {/* HEADER + KPI STRIP */}
      <header className="ft-header">
        <div className="ft-header-row">
          <div>
            <h1 className="ft-title">
              <span className="ft-title-icon"></span>
              Rastreamento de Frota
            </h1>
            <p className="ft-subtitle">
              Posição em tempo real · atualiza a cada 5s
            </p>
          </div>
          <div className="ft-header-actions">
            <button onClick={() => setShowEmergency(true)}
                     className="ft-btn ft-btn-emergency"
                     data-testid="fleet-tracking-emergency-btn"
                     title="Bloquear veículo em sinistro/roubo">
              <span className="ft-pulse-dot" />
              <span className="ft-btn-label">Emergência</span>
            </button>
            <button onClick={() => setShowForm({ edit: null })}
                     className="ft-btn ft-btn-primary"
                     data-testid="fleet-tracking-add-vehicle">
              + <span className="ft-btn-label">Cadastrar veículo</span>
            </button>
          </div>
        </div>

        {/* KPI STRIP */}
        <div className="ft-kpi-strip" data-testid="fleet-kpi-strip">
          <KPICard label="Total" value={kpis.total} icon=""
                    color="#0f172a"
                    active={statusFilter === null}
                    onClick={() => setStatusFilter(null)} />
          <KPICard label="Movimento" value={kpis.moving} icon="▲"
                    color={STATUS_COLOR.moving}
                    active={statusFilter === "moving"}
                    onClick={() => setStatusFilter(
                      statusFilter === "moving" ? null : "moving")} />
          <KPICard label="Parados" value={kpis.idle} icon="●"
                    color={STATUS_COLOR.idle}
                    active={statusFilter === "idle"}
                    onClick={() => setStatusFilter(
                      statusFilter === "idle" ? null : "idle")} />
          <KPICard label="Offline" value={kpis.offline} icon="○"
                    color={STATUS_COLOR.offline}
                    active={statusFilter === "offline"}
                    onClick={() => setStatusFilter(
                      statusFilter === "offline" ? null : "offline")} />
          <KPICard label="Excesso" value={kpis.overspeed} icon=""
                    color={STATUS_COLOR.overspeed}
                    active={statusFilter === "overspeed"}
                    onClick={() => setStatusFilter(
                      statusFilter === "overspeed" ? null : "overspeed")} />
        </div>
      </header>

      {/* TABS */}
      <nav className="ft-tabs">
        {[
          ["live", "️", "Tempo Real"],
          ["history", "⏱️", "Histórico"],
          ["geofences", "", "Cercas"],
          ["events", "", "Alertas"],
          ["reports", "", "Relatórios"],
          ["tenants", "", "Clientes"],
        ].map(([id, icon, label]) => (
          <button key={id}
                   data-testid={`fleet-tab-${id}`}
                   onClick={() => setTab(id)}
                   className={`ft-tab ${tab === id ? "ft-tab-active" : ""}`}>
            <span className="ft-tab-icon">{icon}</span>
            <span className="ft-tab-label">{label}</span>
          </button>
        ))}
      </nav>

      {err && <div className="ft-error">{err}</div>}

      {/* CONTENT */}
      {tab === "live" && (
        <div className="ft-live-grid">
          {/* ASSET LIST */}
          <aside className={`ft-aside ${drawerOpen ? "ft-aside-open" : ""}`}
                   data-testid="fleet-vehicle-list">
            <div className="ft-aside-header">
              <div className="ft-aside-title">
                Veículos <span className="ft-count">({filtered.length})</span>
              </div>
              <button className="ft-aside-close"
                       onClick={() => setDrawerOpen(false)}>✕</button>
            </div>
            <div className="ft-search-wrap">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar placa, modelo…"
                className="ft-search"
                data-testid="fleet-search-input"
              />
            </div>
            <div className="ft-vehicle-list">
              {!filtered.length && (
                <div className="ft-empty">
                  {vehicles.length === 0
                    ? "Cadastre seu primeiro veículo →"
                    : "Nenhum veículo com este filtro."}
                </div>
              )}
              {filtered.map((v) => {
                const st = vehicleStatus(v);
                const isSel = v.id === selectedVid;
                return (
                  <div key={v.id}
                        className={`ft-veh-card ${isSel ? "ft-veh-sel" : ""}`}
                        onClick={() => {
                          setSelectedVid(v.id);
                          setDrawerOpen(false);
                          setInspectorOpen(true);
                        }}
                        data-testid={`fleet-vlist-${v.id}`}>
                    <div className="ft-veh-status"
                          style={{ background: STATUS_COLOR[st] }} />
                    <div className="ft-veh-info">
                      <div className="ft-veh-placa">{v.placa}</div>
                      <div className="ft-veh-meta">
                        {v.modelo || "—"} · {(v.speed_kmh || 0).toFixed(0)}km/h
                      </div>
                    </div>
                    <div className="ft-veh-time">
                      {fmtMin(v.ts)}
                    </div>
                  </div>
                );
              })}
            </div>
          </aside>

          {/* MAP */}
          <main className="ft-map-wrap" data-testid="fleet-map">
            <button className="ft-aside-toggle"
                     onClick={() => setDrawerOpen((p) => !p)}>
              Veículos ({filtered.length})
            </button>
            <MapContainer center={center} zoom={13}
                            style={{ height: "100%", width: "100%" }}
                            zoomControl={false}>
              <TileLayer attribution='Mapa &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contribuidores &copy; <a href="https://carto.com/attributions">CARTO</a>'
                           url={tileUrl} />
              <FitToMarkers vehicles={vehicles} />
              {selected?.lat && (
                <FlyTo position={[selected.lat, selected.lng]} />
              )}
              {filtered.filter((v) => v.lat && v.lng).map((v) => {
                const st = vehicleStatus(v);
                return (
                  <Marker key={v.id} position={[v.lat, v.lng]}
                            icon={makeIcon(STATUS_COLOR[st],
                                            v.heading || 0, v.placa)}
                            eventHandlers={{
                              click: () => setSelectedVid(v.id),
                            }}>
                    <Popup>
                      <div style={{ fontFamily: "sans-serif", minWidth: 180 }}>
                        <b style={{ fontSize: 14 }}>{v.placa}</b>{" "}
                        {v.modelo && `· ${v.modelo}`}<br />
                        <span style={{
                          background: STATUS_COLOR[st], color: "white",
                          padding: "2px 6px", borderRadius: 4,
                          fontSize: 11, fontWeight: 700,
                        }}>{STATUS_LABEL[st]}</span><br />
                        {(v.speed_kmh || 0).toFixed(1)} km/h<br />
                        {v.ts && `Atualizado ${fmtMin(v.ts)} atrás`}
                      </div>
                    </Popup>
                  </Marker>
                );
              })}
              {geofences.filter((g) => g.active).map((g) =>
                g.kind === "circle"
                  ? <Circle key={g.id}
                              center={[g.center_lat, g.center_lng]}
                              radius={g.radius_m}
                              pathOptions={{ color: "#a855f7", weight: 2,
                                              fillOpacity: 0.1 }} />
                  : <Polygon key={g.id}
                                positions={(g.polygon || []).map((p) => [p[0], p[1]])}
                                pathOptions={{ color: "#a855f7", weight: 2,
                                                fillOpacity: 0.1 }} />)}
            </MapContainer>

            {/* MAP STYLE SWITCHER */}
            <div className="ft-map-style">
              {["light", "dark", "satellite"].map((s) => (
                <button key={s}
                         className={`ft-map-style-btn ${mapStyle === s ? "active" : ""}`}
                         onClick={() => setMapStyle(s)}
                         data-testid={`fleet-mapstyle-${s}`}>
                  {s === "light" ? "" : s === "dark" ? "" : "️"}
                </button>
              ))}
            </div>
          </main>

          {/* INSPECTOR (selected vehicle) */}
          {selected && inspectorOpen && (
            <aside className="ft-inspector"
                    data-testid="fleet-inspector">
              <div className="ft-inspector-header">
                <div>
                  <div className="ft-inspector-placa">{selected.placa}</div>
                  <div className="ft-inspector-modelo">
                    {selected.modelo || "—"} · {selected.cor || ""}
                  </div>
                </div>
                <button className="ft-inspector-close"
                         onClick={() => setInspectorOpen(false)}>✕</button>
              </div>
              {(() => {
                const st = vehicleStatus(selected);
                return (
                  <div className="ft-inspector-status"
                        style={{ background: STATUS_COLOR[st] + "20",
                                   color: STATUS_COLOR[st],
                                   borderLeft: `4px solid ${STATUS_COLOR[st]}` }}>
                    {STATUS_LABEL[st]}
                  </div>
                );
              })()}
              <div className="ft-inspector-grid">
                <Stat label="Velocidade"
                       value={`${(selected.speed_kmh || 0).toFixed(0)} km/h`} />
                <Stat label="Ignição"
                       value={selected.ignition === true ? "Ligada"
                         : selected.ignition === false ? "Desligada" : "—"} />
                <Stat label="Última atualização"
                       value={fmtMin(selected.ts)} />
                <Stat label="Limite"
                       value={`${selected.speed_limit_kmh || 80} km/h`} />
              </div>
              {selected.lat && (
                <div className="ft-inspector-loc">
                  {selected.lat.toFixed(5)}, {selected.lng.toFixed(5)}
                  <a target="_blank" rel="noreferrer"
                      href={`https://www.google.com/maps?q=${selected.lat},${selected.lng}`}>
                    Google Maps ↗
                  </a>
                </div>
              )}
              <div className="ft-inspector-actions">
                <button className="ft-btn ft-btn-primary"
                         onClick={() => { setTab("history"); }}
                         data-testid="fleet-inspector-history">
                  ⏱️ Ver histórico
                </button>
                <button className="ft-btn ft-btn-danger-soft"
                         onClick={() => setShowEmergency(true)}
                         data-testid="fleet-inspector-block">
                  Bloquear/Liberar
                </button>
                <button className="ft-btn ft-btn-secondary"
                         onClick={() => setShowForm({ edit: selected })}
                         data-testid="fleet-inspector-edit">
                  ✏️ Editar
                </button>
              </div>
            </aside>
          )}
        </div>
      )}

      {tab === "history" && <FleetHistoryTab vehicles={vehicles} />}
      {tab === "geofences" && (
        <FleetGeofencesTab geofences={geofences}
                            onReload={refreshGeofences}
                            vehicles={vehicles} />
      )}
      {tab === "events" && <FleetEventsTab vehicles={vehicles} />}
      {tab === "reports" && <FleetReportsTab />}
      {tab === "tenants" && <FleetTenantsTab />}

      {showForm && (
        showForm.edit
          ? <FleetVehicleForm initial={showForm.edit}
                                onClose={() => setShowForm(null)}
                                onSaved={() => { setShowForm(null); refresh(); }} />
          // iter233 — Cadastros novos usam o Wizard plug-and-play
          : <FleetGpsWizard onClose={() => setShowForm(null)}
                              onSaved={() => { setShowForm(null); refresh(); }} />
      )}

      {showEmergency && (
        <FleetEmergencyBlockModal
          vehicles={vehicles}
          onClose={() => setShowEmergency(false)}
          onActionDone={() => refresh()} />
      )}
    </div>
  );
}

function KPICard({ label, value, icon, color, active, onClick }) {
  return (
    <button onClick={onClick}
             className={`ft-kpi ${active ? "ft-kpi-active" : ""}`}
             style={{ borderColor: active ? color : "transparent" }}
             data-testid={`fleet-kpi-${label.toLowerCase()}`}>
      <span className="ft-kpi-icon" style={{ color }}>{icon}</span>
      <span className="ft-kpi-info">
        <span className="ft-kpi-value">{value}</span>
        <span className="ft-kpi-label">{label}</span>
      </span>
    </button>
  );
}

function Stat({ label, value }) {
  return (
    <div className="ft-stat">
      <div className="ft-stat-label">{label}</div>
      <div className="ft-stat-value">{value}</div>
    </div>
  );
}
