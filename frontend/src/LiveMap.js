import React, { useEffect, useMemo, useRef, useState } from "react";
import { Circle, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip as LTooltip, useMap, ZoomControl } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/api";
import { Button, Card, Icon } from "@/ui";
import { disablePushForGestor, enablePushForGestor, getCurrentSubscription, getPushPermission, sendTestPush } from "@/push";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

const BRAZIL_CENTER = [-14.235, -51.925];
const BRAZIL_ZOOM = 4;
const REFRESH_MS = 15000;
const DWELL_REFRESH_MS = 60000;

function colorForId(id) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360;
  return `hsl(${h}, 78%, 42%)`;
}

const RISK_COLOR = { alto: "#dc2626", medio: "#f59e0b", baixo: "#16a34a" };
const RISK_LABEL = { alto: "ALTO", medio: "MÉDIO", baixo: "BAIXO" };

function makeAvatarIcon(name, color, isStale, badge) {
  const initials = (name || "?").split(" ").filter(Boolean).slice(0, 2).map((s) => s[0]?.toUpperCase()).join("");
  const opacity = isStale ? 0.55 : 1;
  const badgeHtml = badge
    ? `<span style="position:absolute;top:-6px;right:-6px;min-width:18px;height:18px;padding:0 4px;border-radius:9px;background:${badge.color};color:white;font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;border:2px solid white;box-shadow:0 2px 4px rgba(0,0,0,.3);">${badge.text}</span>`
    : "";
  return L.divIcon({
    className: "live-avatar-icon",
    html: `
      <div style="width:38px;height:38px;border-radius:50%;background:${color};color:white;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:13px;font-family:Inter,Arial;border:3px solid white;box-shadow:0 4px 10px rgba(0,0,0,.25);opacity:${opacity};position:relative;">
        ${initials}
        <span style="position:absolute;bottom:-2px;right:-2px;width:12px;height:12px;border-radius:50%;background:${isStale ? "#94a3b8" : "#16a34a"};border:2px solid white;"></span>
        ${badgeHtml}
      </div>`,
    iconSize: [38, 38],
    iconAnchor: [19, 19],
  });
}

function FitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (!points || points.length === 0) return;
    const valid = points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    if (valid.length === 0) return;
    if (valid.length === 1) map.setView(valid[0], 16, { animate: true });
    else map.fitBounds(L.latLngBounds(valid).pad(0.2), { animate: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(points)]);
  return null;
}

function fmtElapsed(iso) {
  if (!iso) return "—";
  const diffSec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffSec < 60) return `há ${diffSec}s`;
  if (diffSec < 3600) return `há ${Math.floor(diffSec / 60)} min`;
  if (diffSec < 86400) return `há ${Math.floor(diffSec / 3600)} h`;
  return new Date(iso).toLocaleString("pt-BR");
}

function fmtDur(min) {
  if (!min) return "0 min";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const r = min % 60;
  return r ? `${h}h${String(r).padStart(2, "0")}` : `${h}h`;
}

export default function LiveMap() {
  const [collabs, setCollabs] = useState([]);
  const [live, setLive] = useState([]);
  const [tracks, setTracks] = useState({});
  const [hours, setHours] = useState(24);
  const [showTrack, setShowTrack] = useState({});
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [, setTick] = useState(0);
  const lastFetchRef = useRef(0);

  // Dwell / IA
  const [dwell, setDwell] = useState(null);
  const [dwellThreshold, setDwellThreshold] = useState(30);
  const [useAi, setUseAi] = useState(true);

  // Web Push
  const [pushState, setPushState] = useState({ supported: false, permission: "default", subscribed: false });
  const refreshPushState = async () => {
    const supported = "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
    if (!supported) { setPushState({ supported: false, permission: "unsupported", subscribed: false }); return; }
    const permission = await getPushPermission();
    const sub = await getCurrentSubscription();
    setPushState({ supported: true, permission, subscribed: !!sub });
  };
  useEffect(() => { refreshPushState(); }, []);

  async function togglePush() {
    try {
      if (pushState.subscribed) {
        await disablePushForGestor();
      } else {
        await enablePushForGestor();
      }
      await refreshPushState();
    } catch (e) {
      alert(`Falha ao ${pushState.subscribed ? "desativar" : "ativar"} notificações: ${e.message || e}`);
    }
  }
  async function testPush() {
    try {
      const r = await sendTestPush();
      alert(`Teste enviado. ${r.sent || 0} entregue(s), ${r.failed || 0} falha(s).`);
    } catch (e) { alert("Falha ao enviar teste: " + (e.message || e)); }
  }

  useEffect(() => { api.listCollaborators().then(setCollabs); }, []);

  const reload = async () => {
    try {
      const liveDocs = await api.liveLocations(360);
      setLive(liveDocs);
      const visibleIds = liveDocs.map((d) => d.collaborator_id);
      const newTracks = { ...tracks };
      await Promise.all(visibleIds.map(async (cid) => {
        if (showTrack[cid] !== false) {
          try { newTracks[cid] = await api.trackCollaborator(cid, hours); } catch {}
        }
      }));
      setTracks(newTracks);
      lastFetchRef.current = Date.now();
    } catch {}
  };

  const reloadDwell = async () => {
    try {
      const d = await api.dwellAnalysis({ hours: 8, min_dur_min: dwellThreshold, use_ai: useAi });
      setDwell(d);
    } catch {}
  };

  const [refreshing, setRefreshing] = useState(false);
  async function manualRefresh() {
    setRefreshing(true);
    await Promise.all([reload(), reloadDwell()]);
    setRefreshing(false);
  }

  useEffect(() => {
    let t1, t2, cancelled = false;
    const run = async () => { if (!cancelled) await reload(); };
    const runDwell = async () => { if (!cancelled) await reloadDwell(); };
    run(); runDwell();
    if (autoRefresh) {
      t1 = setInterval(run, REFRESH_MS);
      t2 = setInterval(runDwell, DWELL_REFRESH_MS);
    }
    return () => { cancelled = true; if (t1) clearInterval(t1); if (t2) clearInterval(t2); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, hours, dwellThreshold, useAi, JSON.stringify(showTrack)]);

  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 15000);
    return () => clearInterval(t);
  }, []);

  const collabsById = useMemo(() => {
    const m = {}; collabs.forEach((c) => (m[c.id] = c)); return m;
  }, [collabs]);
  const liveById = useMemo(() => {
    const m = {}; live.forEach((d) => (m[d.collaborator_id] = d)); return m;
  }, [live]);
  const dwellById = useMemo(() => {
    const m = {}; (dwell?.items || []).forEach((d) => (m[d.collaborator_id] = d)); return m;
  }, [dwell]);

  const points = useMemo(() => live.map((d) => [d.lat, d.lng]), [live]);

  function isStale(iso) {
    if (!iso) return true;
    return Date.now() - new Date(iso).getTime() > 5 * 60 * 1000;
  }

  function badgeFor(item) {
    if (!item) return null;
    if (item.out_of_fence) return { color: "#dc2626", text: "!" };
    if (item.current_dwell_min >= dwellThreshold) {
      const risk = item.ai_evaluation?.risk;
      const c = RISK_COLOR[risk] || "#f59e0b";
      return { color: c, text: `${item.current_dwell_min}m` };
    }
    return null;
  }

  const alerts = dwell?.alerts || [];

  return (
    <div>
      <Card title="Mapa ao vivo — colaboradores" action={
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Button onClick={manualRefresh} disabled={refreshing} variant="primary" data-testid="refresh-map-btn" title="Recarregar agora">
            <Icon name="sync" /> {refreshing ? "Atualizando..." : "Atualizar agora"}
          </Button>
          <label style={{ fontSize: 13, color: "#64748b" }}>Trajeto últimas:</label>
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))} data-testid="track-hours">
            <option value={1}>1 h</option><option value={4}>4 h</option><option value={8}>8 h</option><option value={24}>24 h (padrão)</option>
          </select>
          <label style={{ fontSize: 13, color: "#64748b" }}>Alerta parado &gt;</label>
          <select value={dwellThreshold} onChange={(e) => setDwellThreshold(Number(e.target.value))} data-testid="dwell-threshold">
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={45}>45 min</option>
            <option value={60}>1 h</option>
            <option value={120}>2 h</option>
          </select>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, color: "#475569" }}>
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} data-testid="use-ai-toggle" />
            Avaliar com IA
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, color: "#475569" }}>
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} data-testid="auto-refresh" />
            Atualização automática
          </label>
          {pushState.supported && (
            <>
              <Button
                onClick={togglePush}
                variant={pushState.subscribed ? "soft" : "secondary"}
                data-testid="toggle-push-btn"
                title={pushState.subscribed ? "Desativar notificações" : "Receber alertas mesmo com a aba fechada"}
                style={{ fontSize: 12 }}
              >
                {pushState.subscribed ? "🔔 Notificações: ON" : "🔕 Ativar notificações"}
              </Button>
              {pushState.subscribed && (
                <Button onClick={testPush} variant="secondary" data-testid="test-push-btn" style={{ fontSize: 12 }} title="Enviar push de teste">
                  Testar
                </Button>
              )}
            </>
          )}
        </div>
      }>
        {/* Banner de alertas */}
        {alerts.length > 0 && (
          <div data-testid="map-alerts-banner" style={{ marginBottom: 12, display: "flex", flexDirection: "column", gap: 6 }}>
            {alerts.slice(0, 4).map((a) => (
              <div
                key={a.id}
                data-testid={`map-alert-${a.id}`}
                style={{
                  background: a.level === "danger" ? "#fee2e2" : "#fef3c7",
                  border: `1px solid ${a.level === "danger" ? "#fecaca" : "#fde68a"}`,
                  color: a.level === "danger" ? "#991b1b" : "#92400e",
                  padding: "8px 12px",
                  borderRadius: 12,
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  fontSize: 13,
                }}
              >
                <span style={{
                  width: 22, height: 22, borderRadius: "50%",
                  background: a.level === "danger" ? "#dc2626" : "#f59e0b",
                  color: "white", display: "grid", placeItems: "center",
                  fontWeight: 900, fontSize: 13, flexShrink: 0,
                }}>!</span>
                <strong style={{ fontSize: 13 }}>{a.title}</strong>
                <span style={{ color: "inherit", opacity: 0.85 }}>· {a.message}</span>
              </div>
            ))}
            {alerts.length > 4 && (
              <div style={{ fontSize: 12, color: "#64748b" }}>+ {alerts.length - 4} alerta(s) adicional(is)</div>
            )}
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 14 }}>
          <div style={{ borderRadius: 18, overflow: "hidden", border: "1px solid #e2e8f0" }}>
            <MapContainer center={BRAZIL_CENTER} zoom={BRAZIL_ZOOM} style={{ height: 540, width: "100%" }} scrollWheelZoom zoomControl={false}>
              <ZoomControl position="topleft" zoomInTitle="Aproximar" zoomOutTitle="Afastar" />
              <TileLayer
                attribution='Mapa &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contribuidores &copy; <a href="https://carto.com/attributions">CARTO</a>'
                url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
                subdomains={["a", "b", "c", "d"]}
                maxZoom={20}
              />
              <FitBounds points={points} />

              {/* Trajetos */}
              {Object.entries(tracks).map(([cid, pts]) => {
                if (showTrack[cid] === false) return null;
                if (!pts || pts.length < 2) return null;
                const color = colorForId(cid);
                const positions = pts.map((p) => [p.lat, p.lng]);
                return <Polyline key={`tr-${cid}`} positions={positions} pathOptions={{ color, weight: 4, opacity: 0.8 }} />;
              })}

              {/* Estadias longas (dwell) - círculos com tempo */}
              {(dwell?.items || []).flatMap((it) =>
                (it.stays || []).map((s, idx) => {
                  const c = colorsForRisk(it, dwellThreshold);
                  return (
                    <Circle
                      key={`stay-${it.collaborator_id}-${idx}`}
                      center={[s.center_lat, s.center_lng]}
                      radius={Math.max(35, Math.min(80, 35 + s.duration_min * 0.5))}
                      pathOptions={{ color: c.stroke, weight: 2, fillColor: c.fill, fillOpacity: 0.35 }}
                      data-testid={`stay-circle-${it.collaborator_id}-${idx}`}
                    >
                      <LTooltip direction="top" permanent>
                        <span style={{ fontWeight: 800, fontSize: 12 }}>
                          {it.name}: parado {fmtDur(s.duration_min)}
                        </span>
                      </LTooltip>
                      <Popup>
                        <strong>{it.name}</strong><br />
                        Parado por <strong>{fmtDur(s.duration_min)}</strong><br />
                        Início: {new Date(s.start).toLocaleString("pt-BR")}<br />
                        Fim: {new Date(s.end).toLocaleString("pt-BR")}<br />
                        {it.ai_evaluation && (
                          <>
                            <br /><strong>IA:</strong> {it.ai_evaluation.summary}<br />
                            <em>Sugestão: {it.ai_evaluation.suggested_action}</em>
                          </>
                        )}
                      </Popup>
                    </Circle>
                  );
                })
              )}

              {/* Marcadores ao vivo */}
              {live.map((d) => {
                const c = collabsById[d.collaborator_id];
                const stale = isStale(d.recorded_at);
                const color = colorForId(d.collaborator_id);
                const item = dwellById[d.collaborator_id];
                const badge = badgeFor(item);
                return (
                  <React.Fragment key={d.collaborator_id}>
                    <Marker
                      position={[d.lat, d.lng]}
                      icon={makeAvatarIcon(c?.name || d.collaborator_id, color, stale, badge)}
                    >
                      <Popup>
                        <strong>{c?.name || d.collaborator_id}</strong><br />
                        {fmtElapsed(d.recorded_at)}<br />
                        Lat {d.lat.toFixed(5)}, Lng {d.lng.toFixed(5)}<br />
                        {d.accuracy && <>Precisão: {Math.round(d.accuracy)} m<br /></>}
                        Status: {stale ? "⚪ Inativo (>5 min)" : "🟢 Ativo"}<br />
                        {item && item.current_dwell_min >= dwellThreshold && (
                          <>⏱️ <strong>Parado há {fmtDur(item.current_dwell_min)}</strong><br /></>
                        )}
                        {item && item.out_of_fence && (
                          <>🚧 <strong>Fora da cerca</strong>
                            {item.nearest_fence_distance_m != null && <> ({Math.round(item.nearest_fence_distance_m)} m)</>}<br />
                          </>
                        )}
                        {item?.ai_evaluation && (
                          <>
                            <br /><strong>IA · risco {RISK_LABEL[item.ai_evaluation.risk] || "?"}:</strong> {item.ai_evaluation.summary}<br />
                            <em>Sugestão: {item.ai_evaluation.suggested_action}</em>
                          </>
                        )}
                      </Popup>
                    </Marker>
                    {d.accuracy && (
                      <Circle
                        center={[d.lat, d.lng]}
                        radius={Math.min(d.accuracy, 200)}
                        pathOptions={{ color, fillColor: color, fillOpacity: 0.08, weight: 1, dashArray: "4 6" }}
                      />
                    )}
                  </React.Fragment>
                );
              })}
            </MapContainer>
          </div>

          <div data-testid="live-collab-list" style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 540, overflowY: "auto" }}>
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 14, padding: 10, fontSize: 12, color: "#475569" }}>
              <strong>{live.length}</strong> com localização recente • <strong>{collabs.length}</strong> cadastrado(s)
              {alerts.length > 0 && (
                <span style={{ marginLeft: 6, color: "#b91c1c", fontWeight: 800 }}>· {alerts.length} alerta(s)</span>
              )}
              <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 4 }}>
                🟢 ativo (até 5 min) • ⚪ inativo (mais de 5 min)
              </div>
              {lastFetchRef.current > 0 && (
                <div style={{ color: "#94a3b8", fontSize: 11, marginTop: 2 }}>
                  Última atualização: {new Date(lastFetchRef.current).toLocaleTimeString("pt-BR")}
                  {dwell && <> · IA {dwell.use_ai ? "ON" : "OFF"}</>}
                </div>
              )}
            </div>

            {collabs.length === 0 && <div style={{ color: "#64748b" }}>Nenhum colaborador cadastrado.</div>}

            {collabs.map((c) => {
              const d = liveById[c.id];
              const color = colorForId(c.id);
              const stale = !d || isStale(d.recorded_at);
              const visible = showTrack[c.id] !== false;
              const trackPoints = (tracks[c.id] || []).length;
              const item = dwellById[c.id];
              const flagged = item && (item.current_dwell_min >= dwellThreshold || item.out_of_fence);
              const risk = item?.ai_evaluation?.risk;
              return (
                <div
                  key={c.id}
                  data-testid={`live-card-${c.id}`}
                  style={{
                    background: "white",
                    border: `1px solid ${flagged ? (risk === "alto" ? "#fecaca" : "#fde68a") : "#e2e8f0"}`,
                    borderLeft: `5px solid ${flagged ? (RISK_COLOR[risk] || "#f59e0b") : color}`,
                    borderRadius: 14,
                    padding: 10,
                    display: "flex",
                    gap: 10,
                    alignItems: "center",
                    opacity: d ? 1 : 0.6,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <strong style={{ fontSize: 14 }}>{c.name}</strong>
                      <span style={{ fontSize: 11, color: stale ? "#94a3b8" : "#16a34a", fontWeight: 700 }}>
                        {d ? (stale ? "⚪ inativo" : "🟢 ativo") : "○ sem dados"}
                      </span>
                      {item?.out_of_fence && (
                        <span data-testid={`badge-fence-${c.id}`} style={{ fontSize: 10, fontWeight: 900, background: "#fee2e2", color: "#991b1b", padding: "2px 6px", borderRadius: 8 }}>
                          FORA DA CERCA
                        </span>
                      )}
                      {item && item.current_dwell_min >= dwellThreshold && (
                        <span data-testid={`badge-dwell-${c.id}`} style={{ fontSize: 10, fontWeight: 900, background: "#fef3c7", color: "#92400e", padding: "2px 6px", borderRadius: 8 }}>
                          PARADO {fmtDur(item.current_dwell_min)}
                        </span>
                      )}
                      {risk && (
                        <span style={{ fontSize: 10, fontWeight: 900, background: RISK_COLOR[risk], color: "white", padding: "2px 6px", borderRadius: 8 }}>
                          IA: {RISK_LABEL[risk]}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: "#64748b" }}>
                      {d ? fmtElapsed(d.recorded_at) : "Nenhum ping recebido"}
                      {d?.accuracy && ` • ±${Math.round(d.accuracy)}m`}
                    </div>
                    {item?.ai_evaluation?.summary && (
                      <div style={{ fontSize: 11, color: "#475569", marginTop: 3, fontStyle: "italic" }}>
                        💡 {item.ai_evaluation.summary}
                      </div>
                    )}
                    <div style={{ fontSize: 11, color: "#94a3b8" }}>{trackPoints} ponto(s) no trajeto</div>
                  </div>
                  {d && (
                    <Button
                      variant={visible ? "soft" : "secondary"}
                      onClick={() => setShowTrack({ ...showTrack, [c.id]: !visible })}
                      data-testid={`toggle-track-${c.id}`}
                      title={visible ? "Ocultar trajeto" : "Mostrar trajeto"}
                      style={{ fontSize: 11, padding: "6px 10px" }}
                    >
                      {visible ? "Ocultar" : "Mostrar"}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </Card>
    </div>
  );
}

function colorsForRisk(it, thr) {
  if (it.out_of_fence) return { stroke: "#dc2626", fill: "#fecaca" };
  if (it.current_dwell_min >= thr * 2) return { stroke: "#dc2626", fill: "#fecaca" };
  if (it.current_dwell_min >= thr) return { stroke: "#f59e0b", fill: "#fde68a" };
  const risk = it.ai_evaluation?.risk;
  if (risk === "alto") return { stroke: "#dc2626", fill: "#fecaca" };
  if (risk === "medio") return { stroke: "#f59e0b", fill: "#fde68a" };
  return { stroke: "#0ea5e9", fill: "#bae6fd" };
}
