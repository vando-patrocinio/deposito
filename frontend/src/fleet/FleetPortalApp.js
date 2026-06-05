/*
 * FleetPortalApp.js — Portal white-label premium do cliente final.
 *
 * Inspirado em Samsara, Wialon, Verizon Connect, Geotab.
 *
 * Características:
 *  • Dark mode por padrão (operacional, mapa-heavy)
 *  • Map-first: tela inicial é mapa em tela cheia
 *  • KPI strip clicável (Total / Movimento / Parado / Offline / Alertas)
 *  • Asset list lateral compacta com busca, filtro de status
 *  • Drill-down: clica veículo → drawer com detalhes, histórico, alertas
 *  • Bottom alert feed persistente (notificações em tempo real)
 *  • Responsivo: desktop 3 colunas, tablet drawer, mobile fullscreen + bottom-sheet
 *  • Branding por tenant (nome) + tema escolhível (dark/light)
 */
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { MapContainer, TileLayer, Marker, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "@/fleet/fleet-portal.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/fleet-portal`;
const LS_KEY = "fleet_portal_token";
const LS_THEME = "fleet_portal_theme";

// ─── Helpers ────────────────────────────────────────────
const status = (v) => {
  if (!v.online) return "offline";
  if ((v.speed_kmh || 0) > 3) return "moving";
  return "idle";
};
const STATUS = {
  moving: { color: "#10b981", label: "Em movimento", icon: "▲" },
  idle: { color: "#f59e0b", label: "Parado", icon: "●" },
  offline: { color: "#64748b", label: "Offline", icon: "○" },
};
const fmtMin = (ts) => {
  if (!ts) return "—";
  try {
    const min = Math.round((Date.now() - new Date(ts).getTime()) / 60000);
    if (min < 1) return "agora";
    if (min < 60) return `${min} min`;
    if (min < 1440) return `${Math.floor(min / 60)}h`;
    return `${Math.floor(min / 1440)}d`;
  } catch { return "—"; }
};

const makeIcon = (color, heading = 0, label = "", theme = "dark") => {
  const bg = theme === "dark" ? "#0f172a" : "#f1f5f9";
  const text = theme === "dark" ? "#f1f5f9" : "#0f172a";
  const html = `
    <div class="fp-marker" style="background:${color}">
      <div class="fp-marker-arrow" style="transform:rotate(${heading}deg)">▲</div>
    </div>
    ${label ? `<div class="fp-marker-label" style="background:${bg};color:${text}">${label}</div>` : ""}`;
  return L.divIcon({
    className: "fp-marker-wrap",
    html,
    iconSize: [40, 50],
    iconAnchor: [20, 20],
  });
};

function FitOnce({ vehicles }) {
  const map = useMap();
  useEffect(() => {
    const valid = vehicles.filter((v) => v.lat && v.lng);
    if (!valid.length) return;
    const bounds = L.latLngBounds(valid.map((v) => [v.lat, v.lng]));
    map.fitBounds(bounds.pad(0.25));
  }, [vehicles, map]);
  return null;
}

function FlyTo({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.flyTo(position, Math.max(map.getZoom(), 15),
                              { duration: 0.7 });
  }, [position, map]);
  return null;
}

// ─── ROOT ────────────────────────────────────────────────
export default function FleetPortalApp() {
  const [token, setToken] = useState(() => localStorage.getItem(LS_KEY) || "");
  const [meta, setMeta] = useState(null);
  const [theme, setTheme] = useState(
    () => localStorage.getItem(LS_THEME) || "dark");

  useEffect(() => {
    document.documentElement.setAttribute("data-fp-theme", theme);
    localStorage.setItem(LS_THEME, theme);
  }, [theme]);

  useEffect(() => {
    if (!token) { setMeta(null); return; }
    axios.get(`${API}/me`,
                { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setMeta(r.data))
      .catch(() => { localStorage.removeItem(LS_KEY); setToken(""); });
  }, [token]);

  if (!token || !meta) {
    return <Login theme={theme} onLogged={(tk, info) => {
      localStorage.setItem(LS_KEY, tk);
      setToken(tk); setMeta(info);
    }} />;
  }
  return <Dashboard token={token} meta={meta} theme={theme}
                       setTheme={setTheme}
                       onLogout={() => {
                         localStorage.removeItem(LS_KEY);
                         setToken(""); setMeta(null);
                       }} />;
}

// ─── LOGIN ───────────────────────────────────────────────
function Login({ onLogged, theme }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showPwd, setShowPwd] = useState(false);

  const submit = async (e) => {
    e?.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await axios.post(`${API}/auth/login`, { email, password });
      onLogged(r.data.access_token,
                { user: r.data.user, tenant: r.data.tenant });
    } catch (er) {
      setErr(er?.response?.data?.detail || er.message);
    }
    setBusy(false);
  };

  return (
    <div className={`fp-login fp-theme-${theme}`} data-testid="fleet-portal-login">
      {/* Lado esquerdo: hero / branding */}
      <div className="fp-login-hero">
        <img src="/portal-hero.png" alt="" className="fp-login-hero-image" />
        <div className="fp-login-hero-bg" />
        <div className="fp-login-hero-grid" />
        <div className="fp-login-hero-content">
          <div className="fp-login-logo-row">
            <div className="fp-logo-circle">
              <svg viewBox="0 0 24 24" width="28" height="28" fill="none"
                    stroke="white" strokeWidth="2" strokeLinecap="round"
                    strokeLinejoin="round">
                <circle cx="12" cy="12" r="2" />
                <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
                <path d="M19.07 4.93l-2.83 2.83M7.76 16.24l-2.83 2.83M19.07 19.07l-2.83-2.83M7.76 7.76L4.93 4.93" />
              </svg>
            </div>
            <h1 className="fp-login-brand">
              Track<span>Pro</span>
            </h1>
          </div>
          <h2 className="fp-login-tag">
            Rastreamento veicular<br />
            <span>em tempo real.</span>
          </h2>
          <p className="fp-login-sub">
            Acompanhe sua frota — carros, caminhões e motos — 24h por dia,
            com mapa ao vivo, histórico de rotas, alertas de velocidade,
            cercas virtuais e bloqueio remoto em caso de sinistro.
          </p>
          <div className="fp-login-features">
            <div className="fp-feat">
              <div className="fp-feat-ic">⚡</div>
              <div>
                <b>Tempo real</b>
                <span>Atualização a cada 5 segundos</span>
              </div>
            </div>
            <div className="fp-feat">
              <div className="fp-feat-ic">🛡️</div>
              <div>
                <b>Bloqueio remoto</b>
                <span>Em caso de roubo ou sinistro</span>
              </div>
            </div>
            <div className="fp-feat">
              <div className="fp-feat-ic">📊</div>
              <div>
                <b>Relatórios</b>
                <span>KM, paradas, excessos, geofences</span>
              </div>
            </div>
          </div>
          <div className="fp-login-trust">
            <div className="fp-trust-dots">
              <span /><span /><span />
            </div>
            <span>Disponível para carros · caminhões · motos</span>
          </div>
        </div>
      </div>

      {/* Lado direito: form de login */}
      <div className="fp-login-side">
        <form onSubmit={submit} className="fp-login-card">
          <div className="fp-login-mobile-brand">
            <div className="fp-logo-circle">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
                    stroke="white" strokeWidth="2" strokeLinecap="round"
                    strokeLinejoin="round">
                <circle cx="12" cy="12" r="2" />
                <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
              </svg>
            </div>
            <h1>Track<span>Pro</span></h1>
          </div>
          <h3 className="fp-login-h">Bem-vindo de volta</h3>
          <p className="fp-login-h-sub">
            Acesse sua conta para acompanhar sua frota
          </p>

          <label className="fp-field">
            <span>E-mail</span>
            <input type="email" value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="seu@email.com"
                    required autoFocus
                    data-testid="fleet-portal-email" />
          </label>

          <label className="fp-field">
            <span>Senha</span>
            <div className="fp-pwd-wrap">
              <input type={showPwd ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                      data-testid="fleet-portal-password" />
              <button type="button" className="fp-pwd-toggle"
                       onClick={() => setShowPwd((p) => !p)}
                       tabIndex={-1}>
                {showPwd ? "🙈" : "👁"}
              </button>
            </div>
          </label>

          {err && <div className="fp-err">⚠ {err}</div>}

          <button type="submit" disabled={busy}
                   className="fp-btn fp-btn-primary fp-btn-block"
                   data-testid="fleet-portal-login-btn">
            {busy ? "Entrando…" : "Entrar →"}
          </button>

          <div className="fp-login-divider"><span>ou</span></div>

          <div className="fp-login-help">
            <div className="fp-help-row">
              <span>🔒</span> Conexão criptografada (TLS 1.3)
            </div>
            <div className="fp-help-row">
              <span>📞</span> Esqueceu o acesso? Fale com seu provedor.
            </div>
          </div>

          <div className="fp-login-foot">
            © 2026 TrackPro · Powered by SmartProv
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── DASHBOARD ───────────────────────────────────────────
function Dashboard({ token, meta, theme, setTheme, onLogout }) {
  const [view, setView] = useState("map");   // map | history | alerts
  const [vehicles, setVehicles] = useState([]);
  const [events, setEvents] = useState([]);
  const [selectedVid, setSelectedVid] = useState(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(true);
  const [mapTile, setMapTile] = useState("dark");
  const [cmdBusy, setCmdBusy] = useState(false);
  const [cmdSent, setCmdSent] = useState(null);  // {kind, ts}
  const headers = { Authorization: `Bearer ${token}` };

  const refresh = async () => {
    try {
      const [v, e] = await Promise.all([
        axios.get(`${API}/positions/live`, { headers }),
        axios.get(`${API}/events`, { headers }).catch(() => ({ data: [] })),
      ]);
      setVehicles(v.data);
      setEvents(e.data);
    } catch { /* */ }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const kpis = useMemo(() => {
    const out = { total: vehicles.length, moving: 0, idle: 0, offline: 0,
                    alerts: events.filter((x) => !x.acked).length };
    vehicles.forEach((v) => { out[status(v)] += 1; });
    return out;
  }, [vehicles, events]);

  const filtered = useMemo(() => {
    let arr = vehicles;
    if (statusFilter) arr = arr.filter((v) => status(v) === statusFilter);
    if (search) {
      const q = search.toLowerCase();
      arr = arr.filter((v) => (v.placa || "").toLowerCase().includes(q)
        || (v.modelo || "").toLowerCase().includes(q));
    }
    return arr;
  }, [vehicles, statusFilter, search]);

  const selected = vehicles.find((v) => v.id === selectedVid);

  const center = useMemo(() => {
    const valid = vehicles.filter((v) => v.lat && v.lng);
    if (selected?.lat) return [selected.lat, selected.lng];
    if (valid.length) return [valid[0].lat, valid[0].lng];
    return [-15.78, -47.93];
  }, [vehicles, selected]);

  const tileUrl = mapTile === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
    : mapTile === "satellite"
      ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
      : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png";

  return (
    <div className={`fp-app fp-theme-${theme}`}
          data-testid="fleet-portal-dashboard">
      {/* ════ TOP BAR ════ */}
      <header className="fp-topbar">
        <div className="fp-topbar-left">
          <button className="fp-mob-menu"
                   onClick={() => setDrawerOpen(true)}>☰</button>
          <div className="fp-brand">
            <span className="fp-brand-icon">📡</span>
            <div>
              <div className="fp-brand-name">
                {meta.tenant?.name || "TrackPro"}
              </div>
              <div className="fp-brand-tagline">Rastreamento ao vivo</div>
            </div>
          </div>
        </div>
        <div className="fp-topbar-right">
          <button className="fp-icon-btn"
                   title={theme === "dark" ? "Tema claro" : "Tema escuro"}
                   onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                   data-testid="fleet-portal-theme">
            {theme === "dark" ? "🌞" : "🌙"}
          </button>
          <div className="fp-user-chip">
            <div className="fp-user-avatar">
              {(meta.user?.name || meta.user?.email || "?")[0].toUpperCase()}
            </div>
            <div className="fp-user-info">
              <div className="fp-user-name">
                {meta.user?.name || meta.user?.email}
              </div>
              <div className="fp-user-role">Cliente</div>
            </div>
          </div>
          <button className="fp-icon-btn" onClick={onLogout}
                   title="Sair"
                   data-testid="fleet-portal-logout">⎋</button>
        </div>
      </header>

      {/* ════ KPI STRIP ════ */}
      <div className="fp-kpi-strip" data-testid="fleet-portal-kpis">
        <KpiCard label="Frota" value={kpis.total} icon="🚗"
                  color="var(--fp-text)"
                  active={statusFilter === null}
                  onClick={() => setStatusFilter(null)} />
        <KpiCard label="Em movimento" value={kpis.moving} icon="▲"
                  color={STATUS.moving.color}
                  active={statusFilter === "moving"}
                  onClick={() => setStatusFilter(
                    statusFilter === "moving" ? null : "moving")} />
        <KpiCard label="Parados" value={kpis.idle} icon="●"
                  color={STATUS.idle.color}
                  active={statusFilter === "idle"}
                  onClick={() => setStatusFilter(
                    statusFilter === "idle" ? null : "idle")} />
        <KpiCard label="Offline" value={kpis.offline} icon="○"
                  color={STATUS.offline.color}
                  active={statusFilter === "offline"}
                  onClick={() => setStatusFilter(
                    statusFilter === "offline" ? null : "offline")} />
        <KpiCard label="Alertas" value={kpis.alerts} icon="🔔"
                  color="#ef4444"
                  active={view === "alerts"}
                  onClick={() => setView(view === "alerts" ? "map" : "alerts")} />
      </div>

      {/* ════ NAVBAR DE VISÕES ════ */}
      <nav className="fp-viewbar">
        {[
          ["map", "🗺️", "Mapa ao vivo"],
          ["history", "⏱️", "Histórico"],
          ["alerts", "🔔", "Alertas"],
        ].map(([id, ic, lb]) => (
          <button key={id}
                   onClick={() => setView(id)}
                   data-testid={`fleet-portal-tab-${id}`}
                   className={`fp-viewbtn ${view === id ? "active" : ""}`}>
            <span>{ic}</span> {lb}
          </button>
        ))}
      </nav>

      {/* ════ CONTENT ════ */}
      {view === "map" && (
        <div className="fp-main-grid">
          {/* ASSET LIST */}
          <aside className={`fp-aside ${drawerOpen ? "open" : ""}`}>
            <div className="fp-aside-head">
              <span>Veículos ({filtered.length})</span>
              <button className="fp-mob-close"
                       onClick={() => setDrawerOpen(false)}>✕</button>
            </div>
            <div className="fp-search">
              <input value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="🔍 Buscar placa, modelo…"
                      data-testid="fleet-portal-search" />
            </div>
            <div className="fp-list">
              {!filtered.length && (
                <div className="fp-empty">Nenhum veículo.</div>
              )}
              {filtered.map((v) => {
                const st = status(v);
                const sel = v.id === selectedVid;
                return (
                  <div key={v.id}
                        className={`fp-veh ${sel ? "sel" : ""}`}
                        onClick={() => {
                          setSelectedVid(v.id);
                          setDrawerOpen(false);
                          setDetailOpen(true);
                        }}>
                    <div className="fp-veh-bar"
                          style={{ background: STATUS[st].color }} />
                    <div className="fp-veh-info">
                      <div className="fp-veh-placa">{v.placa}</div>
                      <div className="fp-veh-meta">
                        {v.modelo || "—"} ·{" "}
                        <span style={{ color: STATUS[st].color,
                                         fontWeight: 700 }}>
                          {STATUS[st].label}
                        </span>
                      </div>
                    </div>
                    <div className="fp-veh-side">
                      <div className="fp-veh-spd">
                        {(v.speed_kmh || 0).toFixed(0)}
                        <span>km/h</span>
                      </div>
                      <div className="fp-veh-ago">{fmtMin(v.ts)}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </aside>

          {/* MAP */}
          <main className="fp-map" data-testid="fleet-portal-map">
            <MapContainer center={center} zoom={13}
                            zoomControl={false}
                            style={{ height: "100%", width: "100%" }}>
              <TileLayer url={tileUrl}
                           attribution='&copy; OpenStreetMap, CartoDB' />
              <FitOnce vehicles={vehicles} />
              {selected?.lat && (
                <FlyTo position={[selected.lat, selected.lng]} />
              )}
              {filtered.filter((v) => v.lat && v.lng).map((v) => (
                <Marker key={v.id} position={[v.lat, v.lng]}
                          icon={makeIcon(STATUS[status(v)].color,
                                          v.heading || 0, v.placa, theme)}
                          eventHandlers={{
                            click: () => { setSelectedVid(v.id);
                              setDetailOpen(true); },
                          }} />
              ))}
            </MapContainer>

            <div className="fp-map-tools">
              {["dark", "light", "satellite"].map((s) => (
                <button key={s}
                         className={`fp-map-tool ${mapTile === s ? "active" : ""}`}
                         onClick={() => setMapTile(s)}
                         title={s}
                         data-testid={`fleet-portal-tile-${s}`}>
                  {s === "dark" ? "🌙" : s === "light" ? "🌞" : "🛰️"}
                </button>
              ))}
            </div>

            <button className="fp-mob-list-btn"
                     onClick={() => setDrawerOpen(true)}>
              ☰ {filtered.length} veículos
            </button>
          </main>

          {/* DETAIL DRAWER */}
          {selected && detailOpen && (
            <aside className="fp-detail"
                    data-testid="fleet-portal-detail">
              <div className="fp-detail-head">
                <div>
                  <div className="fp-detail-placa">{selected.placa}</div>
                  <div className="fp-detail-sub">
                    {selected.modelo || "—"}
                    {selected.cor && ` · ${selected.cor}`}
                  </div>
                </div>
                <button className="fp-icon-btn"
                         onClick={() => setDetailOpen(false)}>✕</button>
              </div>
              <div className="fp-detail-status"
                    style={{ background: STATUS[status(selected)].color + "22",
                              color: STATUS[status(selected)].color,
                              borderLeft: `4px solid ${STATUS[status(selected)].color}` }}>
                {STATUS[status(selected)].icon} {STATUS[status(selected)].label}
              </div>
              <div className="fp-detail-stats">
                <Stat label="Velocidade"
                       value={`${(selected.speed_kmh || 0).toFixed(0)} km/h`} />
                <Stat label="Direção"
                       value={`${Math.round(selected.heading || 0)}°`} />
                <Stat label="Ignição"
                       value={selected.ignition === true ? "🔑 Ligada"
                         : selected.ignition === false ? "🔌 Desligada"
                           : "—"} />
                <Stat label="Última posição"
                       value={fmtMin(selected.ts)} />
              </div>
              {selected.lat && (
                <div className="fp-detail-loc">
                  <div className="fp-detail-loc-coords">
                    📍 {selected.lat.toFixed(5)}, {selected.lng.toFixed(5)}
                  </div>
                  <a target="_blank" rel="noreferrer"
                      href={`https://www.google.com/maps?q=${selected.lat},${selected.lng}`}
                      className="fp-btn fp-btn-ghost">
                    Abrir no Google Maps ↗
                  </a>
                </div>
              )}
              <button className="fp-btn fp-btn-primary"
                       onClick={() => setView("history")}>
                ⏱️ Ver histórico de rotas
              </button>

              {/* iter212h — Botões de comando direto */}
              <div className="fp-detail-cmds">
                <div className="fp-detail-cmds-title">Controle do veículo</div>
                {cmdSent && (
                  <div className="fp-cmd-sent" data-testid="fleet-portal-cmd-sent">
                    ✅ Comando <b>{cmdSent.kind === "block" ? "BLOQUEAR"
                      : cmdSent.kind === "unblock" ? "LIBERAR" : "LOCALIZAR"}
                    </b> enfileirado · {new Date(cmdSent.ts).toLocaleTimeString("pt-BR")}
                    <br />
                    <small>Será executado quando o rastreador conectar.</small>
                  </div>
                )}
                <div className="fp-detail-cmd-grid">
                  <button
                    onClick={async () => {
                      if (cmdBusy) return;
                      setCmdBusy(true);
                      try {
                        const r = await axios.post(
                          `${API}/vehicles/${selected.id}/command`,
                          { kind: "block" }, { headers });
                        setCmdSent({ kind: "block", ts: Date.now(),
                                       id: r.data.id });
                      } catch (e) {
                        alert(e?.response?.data?.detail || e.message);
                      }
                      setCmdBusy(false);
                    }}
                    disabled={cmdBusy}
                    className="fp-btn fp-btn-danger"
                    data-testid="fleet-portal-block">
                    🔒 Bloquear
                  </button>
                  <button
                    onClick={async () => {
                      if (cmdBusy) return;
                      setCmdBusy(true);
                      try {
                        const r = await axios.post(
                          `${API}/vehicles/${selected.id}/command`,
                          { kind: "unblock" }, { headers });
                        setCmdSent({ kind: "unblock", ts: Date.now(),
                                       id: r.data.id });
                      } catch (e) {
                        alert(e?.response?.data?.detail || e.message);
                      }
                      setCmdBusy(false);
                    }}
                    disabled={cmdBusy}
                    className="fp-btn fp-btn-success"
                    data-testid="fleet-portal-unblock">
                    🔓 Liberar
                  </button>
                </div>
                <div className="fp-detail-cmd-hint">
                  ⚠️ O bloqueio corta a partida do motor.
                  Use apenas em caso de roubo/sinistro.
                </div>
              </div>
            </aside>
          )}
        </div>
      )}

      {view === "history" && (
        <History token={token} vehicles={vehicles}
                  selectedVid={selectedVid}
                  setSelectedVid={setSelectedVid}
                  theme={theme} />
      )}
      {view === "alerts" && (
        <Alerts events={events} vehicles={vehicles}
                 onSelectVehicle={(vid) => {
                   setSelectedVid(vid); setView("map");
                 }} />
      )}
    </div>
  );
}

// ─── Components ──────────────────────────────────────────
function KpiCard({ label, value, icon, color, active, onClick }) {
  return (
    <button onClick={onClick}
             className={`fp-kpi ${active ? "active" : ""}`}
             style={{ borderColor: active ? color : "transparent" }}
             data-testid={`fleet-portal-kpi-${label.toLowerCase().replace(" ", "-")}`}>
      <span className="fp-kpi-icon" style={{ color }}>{icon}</span>
      <span className="fp-kpi-num">{value}</span>
      <span className="fp-kpi-lbl">{label}</span>
    </button>
  );
}

function Stat({ label, value }) {
  return (
    <div className="fp-stat">
      <div className="fp-stat-lbl">{label}</div>
      <div className="fp-stat-val">{value}</div>
    </div>
  );
}

// ─── History view ──────────────────────────────────────
function History({ token, vehicles, selectedVid, setSelectedVid, theme }) {
  const today = new Date().toISOString().slice(0, 10);
  const [vid, setVid] = useState(selectedVid || vehicles[0]?.id || "");
  const [date, setDate] = useState(today);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    if (!vid) return;
    setLoading(true);
    axios.get(`${API}/positions/${vid}/history`,
                { headers,
                   params: { from: `${date}T00:00:00`,
                             to: `${date}T23:59:59` } })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
    setSelectedVid?.(vid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vid, date, token]);

  const points = data?.points || [];
  const path = points.map((p) => [p.lat, p.lng]);
  const stats = useMemo(() => {
    if (points.length < 2) return null;
    let km = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i];
      const R = 6371;
      const dLat = (b.lat - a.lat) * Math.PI / 180;
      const dLng = (b.lng - a.lng) * Math.PI / 180;
      const c = Math.sin(dLat / 2) ** 2
        + Math.cos(a.lat * Math.PI / 180) * Math.cos(b.lat * Math.PI / 180)
        * Math.sin(dLng / 2) ** 2;
      km += R * 2 * Math.asin(Math.sqrt(c));
    }
    const speeds = points.map((p) => p.speed_kmh || 0).filter((s) => s > 0);
    const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
    return { km, maxSpeed, points: points.length };
  }, [points]);

  const tile = theme === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
    : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png";

  return (
    <div className="fp-history" data-testid="fleet-portal-history">
      <div className="fp-history-bar">
        <select value={vid} onChange={(e) => setVid(e.target.value)}
                 className="fp-sel">
          <option value="">— escolha um veículo —</option>
          {vehicles.map((v) => (
            <option key={v.id} value={v.id}>{v.placa}</option>
          ))}
        </select>
        <input type="date" value={date}
                onChange={(e) => setDate(e.target.value)}
                className="fp-sel" />
        {stats && (
          <div className="fp-history-stats">
            <div><span>📏</span> <b>{stats.km.toFixed(1)}</b> km</div>
            <div><span>⚡</span> <b>{stats.maxSpeed.toFixed(0)}</b> km/h máx</div>
            <div><span>📍</span> <b>{stats.points}</b> pontos</div>
          </div>
        )}
      </div>
      <div className="fp-history-map">
        {loading ? (
          <div className="fp-empty">Carregando rota…</div>
        ) : !path.length ? (
          <div className="fp-empty">Sem deslocamento neste dia.</div>
        ) : (
          <MapContainer bounds={L.latLngBounds(path)}
                          zoomControl={false}
                          style={{ height: "100%", width: "100%" }}>
            <TileLayer url={tile}
                         attribution='&copy; OpenStreetMap, CartoDB' />
            <Polyline positions={path}
                       pathOptions={{ color: "#3b82f6", weight: 5,
                                       opacity: 0.85 }} />
            <Marker position={path[0]}
                      icon={L.divIcon({
                        className: "fp-pt",
                        html: `<div class="fp-pt-start">▶</div>`,
                        iconSize: [28, 28], iconAnchor: [14, 14],
                      })} />
            <Marker position={path[path.length - 1]}
                      icon={L.divIcon({
                        className: "fp-pt",
                        html: `<div class="fp-pt-end">■</div>`,
                        iconSize: [28, 28], iconAnchor: [14, 14],
                      })} />
          </MapContainer>
        )}
      </div>
    </div>
  );
}

// ─── Alerts view ───────────────────────────────────────
function Alerts({ events, vehicles, onSelectVehicle }) {
  const vmap = Object.fromEntries(vehicles.map((v) => [v.id, v]));
  const ICON = {
    geofence_entry: "📍", geofence_exit: "🚪", speed: "⚡",
    panic: "🆘", sos: "🚨", low_battery: "🪫",
  };
  const LABEL = {
    geofence_entry: "Entrou em cerca", geofence_exit: "Saiu de cerca",
    speed: "Excesso de velocidade", panic: "Pânico", sos: "SOS",
    low_battery: "Bateria fraca",
  };
  return (
    <div className="fp-alerts" data-testid="fleet-portal-alerts">
      {!events.length && (
        <div className="fp-empty fp-empty-big">
          <span style={{ fontSize: 48 }}>🎉</span>
          <h3>Nenhum alerta!</h3>
          <p>Sua frota está operando dentro do esperado.</p>
        </div>
      )}
      {events.map((e) => {
        const v = vmap[e.vehicle_id];
        return (
          <div key={e.id} className="fp-alert"
                onClick={() => v && onSelectVehicle?.(v.id)}>
            <div className="fp-alert-icon">{ICON[e.kind] || "⚠"}</div>
            <div className="fp-alert-body">
              <div className="fp-alert-title">
                {LABEL[e.kind] || e.kind}
                {v && (
                  <span className="fp-alert-veh">
                    {v.placa}
                  </span>
                )}
              </div>
              <div className="fp-alert-meta">
                {e.kind === "speed"
                  && `${e.payload?.speed_kmh} km/h · limite ${e.payload?.limit_kmh} km/h`}
                {e.kind?.includes("geofence") && e.payload?.geofence_name}
                <span style={{ marginLeft: "auto" }}>
                  {new Date(e.ts).toLocaleString("pt-BR")}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
