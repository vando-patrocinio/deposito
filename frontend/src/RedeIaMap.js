/* =============================================================
   RedeIaMap — Mapa interativo FTTH (Leaflet)
   Substitui o fluxograma React Flow.

   Elementos:
   - CTOs: marker circular colorido pela saúde (verde/amarelo/vermelho)
   - CE: marker diamante azul, com label
   - Cabos: polylines coloridas por capacidade (6/12/24FO)
   - Drops: linhas finas cinzas
   - Bolha de média da VLAN sobre cada CTO

   Interatividade:
   - Drag → reposicionar manualmente (salva no backend)
   - Click → popup com detalhes + ações
   - Modo edição: criar CE, ligar cabos
============================================================= */
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  MapContainer, TileLayer, Marker, Popup, Polyline,
  useMap, CircleMarker, Tooltip,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/api";
import { Card } from "@/ui";

// Fix dos ícones default do Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

// Paleta CTO por saúde
const CTO_COLORS = {
  ok: { fill: "#16a34a", border: "#14532d" },
  warning: { fill: "#ca8a04", border: "#713f12" },
  critical: { fill: "#dc2626", border: "#7f1d1d" },
  no_data: { fill: "#94a3b8", border: "#475569" },
  unknown: { fill: "#94a3b8", border: "#475569" },
};
const CABLE_COLORS = {
  drop: "#94a3b8",
  "6fo": "#facc15",   // amarelo
  "12fo": "#fb923c",  // laranja
  "24fo": "#ef4444",  // vermelho
  "48fo": "#8b5cf6",  // roxo
  "96fo": "#0f172a",  // preto
};
const CABLE_WIDTHS = {
  drop: 1.5, "6fo": 2.5, "12fo": 3.5, "24fo": 4.5, "48fo": 5.5, "96fo": 6.5,
};

const STATUS_LABEL = {
  ok: "Saudável", warning: "Atenção", critical: "Crítico",
  no_data: "Sem dados", unknown: "Desconhecido",
};

// Ícone customizado CTO usando DivIcon (HTML)
function makeCtoIcon(health, used, total) {
  const c = CTO_COLORS[health.status] || CTO_COLORS.no_data;
  const pct = total ? Math.round((used / total) * 100) : 0;
  return L.divIcon({
    className: "cto-marker",
    html: `<div style="
      position:relative;width:38px;height:38px;border-radius:9px;
      background:${c.fill};border:2.5px solid ${c.border};
      box-shadow:0 2px 6px rgba(0,0,0,0.35);
      display:grid;place-items:center;color:#fff;font-weight:800;
      font-size:11px;font-family:system-ui;">
      ▦
      <span style="position:absolute;bottom:-5px;right:-6px;
        background:#fff;color:${c.border};font-size:9px;font-weight:800;
        border:1.5px solid ${c.border};border-radius:99px;
        padding:1px 4px;line-height:1;">${pct}%</span>
    </div>`,
    iconSize: [38, 38],
    iconAnchor: [19, 19],
  });
}

function makeCeIcon(ce) {
  return L.divIcon({
    className: "ce-marker",
    html: `<div style="
      width:30px;height:30px;
      transform:rotate(45deg);background:#2563eb;
      border:2px solid #1e40af;
      box-shadow:0 2px 5px rgba(0,0,0,0.3);
      display:grid;place-items:center;">
      <span style="transform:rotate(-45deg);color:#fff;font-weight:800;font-size:11px;">CE</span>
    </div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

// Helper: centraliza no mapa ao carregar
function FitBounds({ ctos }) {
  const map = useMap();
  useEffect(() => {
    if (ctos.length === 0) return;
    const bounds = L.latLngBounds(ctos.map((c) => [c.lat, c.lng]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 18 });
  }, [ctos, map]);
  return null;
}

export default function RedeIaMap() {
  const [data, setData] = useState({ ctos: [], ces: [], cables: [], vlans: [],
                                          center: { lat: -22.9068, lng: -43.1729 } });
  const [loading, setLoading] = useState(false);
  const [vlanFilter, setVlanFilter] = useState("");
  const [healthFilter, setHealthFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("view"); // view | drag | add-ce | add-cable
  const [cableDraft, setCableDraft] = useState({ from: null, to: null });
  const [legendOpen, setLegendOpen] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.redeIaMapData();
      setData(r);
    } catch (e) {
      console.error(e);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const filteredCtos = useMemo(() => {
    return data.ctos.filter((c) => {
      if (vlanFilter && String(c.vlan) !== String(vlanFilter)) return false;
      if (healthFilter && c.health.status !== healthFilter) return false;
      return true;
    });
  }, [data.ctos, vlanFilter, healthFilter]);

  const ctosById = useMemo(() => {
    const m = new Map();
    data.ctos.forEach((c) => m.set(c.id, c));
    return m;
  }, [data.ctos]);
  const cesById = useMemo(() => {
    const m = new Map();
    data.ces.forEach((c) => m.set(c.id, c));
    return m;
  }, [data.ces]);

  const handleDragEnd = useCallback(async (entity_type, entity_id, latlng) => {
    try {
      await api.redeIaPositionSave({
        entity_id, entity_type,
        lat: latlng.lat, lng: latlng.lng,
      });
      // atualiza local sem refetch
      setData((d) => {
        const upd = { ...d };
        if (entity_type === "cto") {
          upd.ctos = d.ctos.map((c) => c.id === entity_id
            ? { ...c, lat: latlng.lat, lng: latlng.lng, moved_manually: true } : c);
        } else if (entity_type === "ce") {
          upd.ces = d.ces.map((c) => c.id === entity_id
            ? { ...c, lat: latlng.lat, lng: latlng.lng, moved_manually: true } : c);
        }
        return upd;
      });
    } catch (e) {
      alert("Falha ao salvar posição: " + (e?.response?.data?.detail || e.message));
    }
  }, []);

  const autoGenerate = async () => {
    if (!window.confirm("rede_IA vai agrupar CTOs próximas em CEs e criar cabos 24FO automaticamente. Continuar?")) return;
    setBusy(true);
    try {
      const r = await api.redeIaAutoGenerateCes(200);
      await load();
      alert(`✓ ${r.ces_created} CEs criadas · ${r.cables_created} cabos · ${r.ctos_clustered} CTOs agrupadas`);
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const removeCable = async (id) => {
    if (!window.confirm("Excluir este cabo?")) return;
    try {
      await api.redeIaCableDelete(id);
      load();
    } catch (e) { alert(e?.response?.data?.detail || "Erro"); }
  };
  const removeCe = async (id) => {
    if (!window.confirm("Excluir esta CE? Os cabos ligados também serão removidos.")) return;
    try {
      await api.redeIaCeDelete(id);
      load();
    } catch (e) { alert(e?.response?.data?.detail || "Erro"); }
  };

  // Cabos: monta segments (usa override se segments vazio)
  const buildCablePath = useCallback((cable) => {
    if (cable.segments && cable.segments.length >= 2) {
      return cable.segments.map((s) => [s.lat, s.lng]);
    }
    // fallback: ponto-a-ponto
    const from = cable.from_type === "ce" ? cesById.get(cable.from_id)
                  : ctosById.get(cable.from_id);
    const to = cable.to_type === "ce" ? cesById.get(cable.to_id)
                : ctosById.get(cable.to_id);
    if (!from || !to) return null;
    return [[from.lat, from.lng], [to.lat, to.lng]];
  }, [ctosById, cesById]);

  const totalCtos = data.ctos.length;
  const criticalCount = data.ctos.filter((c) => c.health.status === "critical").length;
  const warningCount = data.ctos.filter((c) => c.health.status === "warning").length;
  const portsUsed = data.ctos.reduce((s, c) => s + c.used_ports, 0);
  const portsTotal = data.ctos.reduce((s, c) => s + (c.capacity || 0), 0);

  return (
    <Card style={{ padding: 0, overflow: "hidden",
                    display: "flex", flexDirection: "column" }}>
      {/* Toolbar */}
      <div style={{
        display: "flex", gap: 8, padding: 12, alignItems: "center",
        background: "var(--bg-surface-2)",
        borderBottom: "1px solid var(--border-default)",
        flexWrap: "wrap",
      }}>
        <select data-testid="map-filter-vlan" value={vlanFilter}
          onChange={(e) => setVlanFilter(e.target.value)}
          style={selectStyle}>
          <option value="">Todas as VLANs</option>
          {data.vlans.map((v) => (
            <option key={v.vlan} value={v.vlan}>
              VLAN {v.vlan} ({v.sigla}) · saúde {v.avg_score}%
            </option>
          ))}
        </select>
        <select data-testid="map-filter-health" value={healthFilter}
          onChange={(e) => setHealthFilter(e.target.value)}
          style={selectStyle}>
          <option value="">Todas as saúdes</option>
          <option value="critical">🔴 Crítico</option>
          <option value="warning">🟡 Atenção</option>
          <option value="ok">🟢 Saudável</option>
          <option value="no_data">⚫ Sem dados</option>
        </select>
        <button data-testid="map-refresh" onClick={load}
                style={tbBtn("#0f172a")}>
          {loading ? "Carregando..." : "Atualizar mapa"}
        </button>
        <button data-testid="map-auto-ces" onClick={autoGenerate} disabled={busy}
                style={{ ...tbBtn("#7c3aed"), opacity: busy ? 0.5 : 1 }}
                title="rede_IA agrupa CTOs próximas e cria CEs + cabos automaticamente">
          {busy ? "Processando..." : "🤖 rede_IA gerar CEs"}
        </button>
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-muted)" }}>
          {filteredCtos.length}/{totalCtos} CTOs ·
          {" "}{data.ces.length} CEs · {data.cables.length} cabos
          {criticalCount > 0 && (
            <span style={{ color: "#dc2626", marginLeft: 8, fontWeight: 700 }}>
              🔴 {criticalCount} críticos
            </span>
          )}
        </span>
      </div>

      {/* VLAN strip */}
      {data.vlans.length > 0 && (
        <div style={{
          display: "flex", gap: 6, padding: "8px 12px", overflowX: "auto",
          background: "#f8fafc",
          borderBottom: "1px solid var(--border-default)",
        }}>
          {data.vlans.map((v) => {
            const status = v.avg_score < 50 ? "critical"
                            : v.avg_score < 75 ? "warning" : "ok";
            const c = CTO_COLORS[status];
            return (
              <button key={v.vlan} data-testid={`vlan-strip-${v.vlan}`}
                onClick={() => setVlanFilter(vlanFilter === String(v.vlan) ? "" : String(v.vlan))}
                style={{
                  padding: "6px 12px", borderRadius: 8,
                  background: vlanFilter === String(v.vlan) ? c.fill : "#fff",
                  border: `1.5px solid ${c.border}`,
                  color: vlanFilter === String(v.vlan) ? "#fff" : c.border,
                  fontSize: 12, fontWeight: 700, cursor: "pointer",
                  whiteSpace: "nowrap",
                }}>
                <span>VLAN {v.vlan} ({v.sigla})</span>
                <span style={{ marginLeft: 6, opacity: 0.7, fontSize: 11 }}>
                  {v.avg_score}% · {v.cto_count} CTOs
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Map */}
      <div style={{ position: "relative", height: 620 }}>
        <MapContainer center={[data.center.lat, data.center.lng]}
                       zoom={14} style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; <a href="https://osm.org">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={19}
          />
          <FitBounds ctos={filteredCtos} />

          {/* Cabos */}
          {data.cables.map((cab) => {
            const path = buildCablePath(cab);
            if (!path) return null;
            return (
              <Polyline key={cab.id} positions={path}
                pathOptions={{
                  color: CABLE_COLORS[cab.type] || "#64748b",
                  weight: CABLE_WIDTHS[cab.type] || 3,
                  opacity: 0.85,
                  dashArray: cab.type === "drop" ? "6 6" : null,
                }}>
                <Popup>
                  <div style={{ minWidth: 200 }}>
                    <div style={{ fontWeight: 800, marginBottom: 4 }}>
                      Cabo {cab.type.toUpperCase()}
                    </div>
                    <div style={{ fontSize: 12, color: "#64748b" }}>
                      {cab.fo_count} fibras · {cab.length_m
                        ? `${Math.round(cab.length_m)}m` : "comprimento ?"}
                    </div>
                    {cab.notes && (
                      <div style={{ fontSize: 11, marginTop: 6, color: "#475569" }}>
                        {cab.notes}
                      </div>
                    )}
                    <button onClick={() => removeCable(cab.id)}
                      style={{ marginTop: 8, padding: "4px 10px", border: 0,
                                background: "#dc2626", color: "#fff",
                                borderRadius: 6, fontSize: 11, cursor: "pointer",
                                fontWeight: 700 }}>
                      Excluir cabo
                    </button>
                  </div>
                </Popup>
              </Polyline>
            );
          })}

          {/* CEs */}
          {data.ces.map((ce) => (
            <Marker key={ce.id} position={[ce.lat, ce.lng]}
              icon={makeCeIcon(ce)}
              draggable={mode === "drag"}
              eventHandlers={{
                dragend: (e) => handleDragEnd("ce", ce.id, e.target.getLatLng()),
              }}>
              <Tooltip direction="top" offset={[0, -15]}>
                <strong>{ce.name}</strong>
              </Tooltip>
              <Popup>
                <div style={{ minWidth: 220 }}>
                  <div style={{ fontWeight: 800, fontSize: 14, color: "#1e40af" }}>
                    {ce.name}
                  </div>
                  <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                    {ce.type} · {ce.capacity_fo} FO
                  </div>
                  {ce.address && (
                    <div style={{ fontSize: 11, marginTop: 6 }}>📍 {ce.address}</div>
                  )}
                  {ce.notes && (
                    <div style={{ fontSize: 11, marginTop: 6, fontStyle: "italic",
                                     color: "#475569" }}>{ce.notes}</div>
                  )}
                  {ce.moved_manually && (
                    <div style={{ fontSize: 10, color: "#7c3aed", marginTop: 4 }}>
                      ✋ Posição ajustada manualmente
                    </div>
                  )}
                  <button onClick={() => removeCe(ce.id)}
                    style={{ marginTop: 8, padding: "4px 10px", border: 0,
                              background: "#dc2626", color: "#fff",
                              borderRadius: 6, fontSize: 11, cursor: "pointer",
                              fontWeight: 700 }}>
                    Excluir CE
                  </button>
                </div>
              </Popup>
            </Marker>
          ))}

          {/* CTOs */}
          {filteredCtos.map((c) => {
            const c2 = CTO_COLORS[c.health.status] || CTO_COLORS.no_data;
            return (
              <React.Fragment key={c.id}>
                {/* halo da saúde quando crítico/warning */}
                {(c.health.status === "critical" || c.health.status === "warning") && (
                  <CircleMarker center={[c.lat, c.lng]}
                    radius={c.health.status === "critical" ? 26 : 20}
                    pathOptions={{
                      color: c2.fill, fillColor: c2.fill,
                      fillOpacity: 0.18, weight: 1,
                    }} />
                )}
                <Marker position={[c.lat, c.lng]}
                  icon={makeCtoIcon(c.health, c.used_ports, c.capacity)}
                  draggable={mode === "drag"}
                  eventHandlers={{
                    dragend: (e) => handleDragEnd("cto", c.id, e.target.getLatLng()),
                  }}>
                  <Tooltip direction="top" offset={[0, -15]}>
                    <strong>{c.name}</strong>
                    <br />
                    <small>Saúde: {STATUS_LABEL[c.health.status]}</small>
                  </Tooltip>
                  <Popup maxWidth={280}>
                    <div style={{ minWidth: 220 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8,
                                       marginBottom: 8 }}>
                        <div style={{
                          width: 24, height: 24, borderRadius: 5,
                          background: c2.fill,
                          display: "grid", placeItems: "center",
                          color: "#fff", fontSize: 12, fontWeight: 800,
                        }}>▦</div>
                        <div>
                          <div style={{ fontWeight: 800, fontSize: 14 }}>{c.name}</div>
                          <div style={{ fontSize: 11, color: "#64748b" }}>
                            VLAN {c.vlan} · {c.sigla}
                          </div>
                        </div>
                      </div>

                      <div style={{
                        padding: 8, borderRadius: 8,
                        background: c2.fill, color: "#fff",
                        fontSize: 12, fontWeight: 700, marginBottom: 8,
                      }}>
                        {c.health.status === "no_data"
                          ? "⚫ Sem dados de sinal"
                          : `${{ok:"🟢",warning:"🟡",critical:"🔴"}[c.health.status]} ${STATUS_LABEL[c.health.status]} · score ${c.health.score}%`}
                        {c.health.total > 0 && (
                          <div style={{ marginTop: 4, fontSize: 11, fontWeight: 500,
                                          opacity: 0.95 }}>
                            {c.health.total} ONUs · {c.health.warning} aviso ·
                            {" "}{c.health.critical} crítico
                            {c.health.avg_rx_dbm != null && (
                              <span> · {c.health.avg_rx_dbm.toFixed(1)} dBm</span>
                            )}
                          </div>
                        )}
                      </div>

                      <div style={{ fontSize: 12, marginBottom: 4 }}>
                        <strong>Portas:</strong> {c.used_ports}/{c.capacity}
                      </div>
                      <div style={{ fontSize: 12, marginBottom: 4 }}>
                        <strong>Tipo:</strong> {c.network_type}
                        {c.splitter ? ` · ${c.splitter}` : ""}
                      </div>
                      {c.address && (
                        <div style={{ fontSize: 11, color: "#475569" }}>
                          📍 {c.address.rua}, {c.address.numero}
                        </div>
                      )}
                      {c.moved_manually && (
                        <div style={{ fontSize: 10, color: "#7c3aed", marginTop: 4 }}>
                          ✋ Posição ajustada manualmente
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
                        <a href={`${process.env.REACT_APP_BACKEND_URL}/api/rede-ia/ctos/${c.id}/qrcode.png`}
                           target="_blank" rel="noreferrer"
                           style={popBtn("#7c3aed")}>QR</a>
                        <a href={`${process.env.REACT_APP_BACKEND_URL}/api/rede-ia/ctos/${c.id}/pdf.pdf`}
                           target="_blank" rel="noreferrer"
                           style={popBtn("#dc2626")}>PDF</a>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              </React.Fragment>
            );
          })}
        </MapContainer>

        {/* Legenda flutuante */}
        {legendOpen && (
          <div style={{
            position: "absolute", bottom: 12, left: 12,
            background: "rgba(255,255,255,0.96)",
            borderRadius: 10, padding: 12, zIndex: 1000,
            border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
            fontSize: 11, minWidth: 200, maxWidth: 240,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "center", marginBottom: 8 }}>
              <strong style={{ fontSize: 12, color: "#0f172a" }}>Legenda</strong>
              <button onClick={() => setLegendOpen(false)}
                style={{ border: 0, background: "transparent", cursor: "pointer",
                          fontSize: 14, color: "#64748b" }}>×</button>
            </div>
            <div style={{ display: "grid", gap: 4 }}>
              <LegendItem color="#16a34a" label="CTO saudável" sq />
              <LegendItem color="#ca8a04" label="CTO atenção" sq />
              <LegendItem color="#dc2626" label="CTO crítica" sq />
              <LegendItem color="#2563eb" label="CE (Caixa Emenda)" diamond />
            </div>
            <div style={{ borderTop: "1px solid #e2e8f0", marginTop: 8,
                            paddingTop: 8 }}>
              <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                              textTransform: "uppercase", marginBottom: 4 }}>
                Cabos
              </div>
              <LegendItem color="#facc15" label="6 FO" line />
              <LegendItem color="#fb923c" label="12 FO" line />
              <LegendItem color="#ef4444" label="24 FO" line />
              <LegendItem color="#94a3b8" label="Drop (1FO)" line dashed />
            </div>
          </div>
        )}
        {!legendOpen && (
          <button onClick={() => setLegendOpen(true)} style={{
            position: "absolute", bottom: 12, left: 12,
            padding: "6px 12px", borderRadius: 8, border: 0,
            background: "rgba(255,255,255,0.96)", color: "#0f172a",
            fontSize: 12, cursor: "pointer", zIndex: 1000,
            boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
          }}>📑 Legenda</button>
        )}

        {/* Modo edição */}
        <div style={{
          position: "absolute", top: 12, right: 12,
          background: "rgba(255,255,255,0.96)",
          borderRadius: 10, padding: 8, zIndex: 1000,
          border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
          display: "flex", flexDirection: "column", gap: 6,
        }}>
          <button data-testid="map-mode-view"
            onClick={() => setMode("view")}
            style={modeBtn(mode === "view")}>👁 Ver</button>
          <button data-testid="map-mode-drag"
            onClick={() => setMode("drag")}
            style={modeBtn(mode === "drag")}>✋ Mover</button>
        </div>
      </div>
    </Card>
  );
}

const selectStyle = {
  padding: "6px 10px", borderRadius: 6,
  border: "1px solid var(--border-default)", fontSize: 12,
  minWidth: 160,
};
const tbBtn = (color) => ({
  padding: "6px 12px", borderRadius: 6, background: color,
  color: "#fff", border: 0, fontSize: 12, cursor: "pointer", fontWeight: 600,
});
const popBtn = (color) => ({
  flex: 1, padding: "5px 10px", borderRadius: 6, background: color,
  color: "#fff", border: 0, fontSize: 11, cursor: "pointer", fontWeight: 700,
  textDecoration: "none", textAlign: "center",
});
const modeBtn = (active) => ({
  padding: "6px 10px", borderRadius: 6, border: "0",
  background: active ? "#0f172a" : "#fff",
  color: active ? "#fff" : "#0f172a",
  fontSize: 11, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap",
});

function LegendItem({ color, label, sq, diamond, line, dashed }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
      <span style={{
        width: 18, height: 14,
        background: line ? "transparent" : color,
        border: line ? "none" : `1.5px solid rgba(0,0,0,0.2)`,
        borderRadius: sq ? 3 : (diamond ? 0 : 99),
        transform: diamond ? "rotate(45deg)" : "none",
        display: line ? "block" : "block",
        backgroundImage: line && dashed
          ? `linear-gradient(to right, ${color} 50%, transparent 50%)`
          : "none",
        backgroundSize: line && dashed ? "8px 100%" : "auto",
        borderTop: line ? `${dashed ? 0 : 3}px solid ${color}` : undefined,
        borderBottom: line && dashed ? `3px dashed ${color}` : undefined,
        height: line ? 3 : 14,
      }} />
      <span>{label}</span>
    </div>
  );
}
