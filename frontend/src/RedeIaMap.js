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
  useMap, CircleMarker, Tooltip, useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.heat";
import { api } from "@/api";
import { Card } from "@/ui";
import CTOInteractionModal from "@/CTOInteractionModal";

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

// Camada que captura clique no mapa (modos add-ce / draw-cable)
function MapClickHandler({ enabled, onClick }) {
  // Refs garantem que o handler do useMapEvents sempre veja valor atual,
  // sem precisar re-bindar listeners.
  const enabledRef = useRef(enabled);
  const onClickRef = useRef(onClick);
  useEffect(() => { enabledRef.current = enabled; }, [enabled]);
  useEffect(() => { onClickRef.current = onClick; }, [onClick]);
  useMapEvents({
    click: (e) => {
      if (enabledRef.current && onClickRef.current) {
        onClickRef.current(e.latlng);
      }
    },
  });
  return null;
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

// Camada Heatmap: pesos baseados em score de saúde (quanto pior, mais quente)
function HeatLayer({ ctos, enabled }) {
  const map = useMap();
  const layerRef = useRef(null);
  useEffect(() => {
    if (layerRef.current) {
      map.removeLayer(layerRef.current);
      layerRef.current = null;
    }
    if (!enabled || ctos.length === 0) return;
    const points = ctos
      .filter((c) => c.health.status !== "no_data")
      .map((c) => {
        // weight: 1.0 quando crítico (score 0), 0.0 quando saudável (score 100)
        const score = c.health.score ?? 100;
        const weight = Math.max(0, Math.min(1, (100 - score) / 100));
        return [c.lat, c.lng, weight];
      });
    if (points.length === 0) return;
    layerRef.current = L.heatLayer(points, {
      radius: 35, blur: 25, maxZoom: 17,
      max: 1.0,
      gradient: {
        0.0: "#22c55e",
        0.3: "#facc15",
        0.6: "#f97316",
        1.0: "#dc2626",
      },
    }).addTo(map);
    return () => {
      if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    };
  }, [map, ctos, enabled]);
  return null;
}

export default function RedeIaMap() {
  const [data, setData] = useState({ ctos: [], ces: [], cables: [], vlans: [],
                                          center: { lat: -22.9068, lng: -43.1729 } });
  const [loading, setLoading] = useState(false);
  const [vlanFilter, setVlanFilter] = useState("");
  const [healthFilter, setHealthFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("view"); // view | drag | add-cable | add-ce | draw-cable
  const [photoLightbox, setPhotoLightbox] = useState(null); // {url, ctoName, uploadedByName}
  const [cableDraft, setCableDraft] = useState({
    from: null,           // { id, type, lat, lng, name }
    waypoints: [],        // [{lat,lng}] intermediários do draw-cable
    cableType: "12fo",
  });
  const [newCe, setNewCe] = useState(null); // { lat, lng } pendente nome
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [legendOpen, setLegendOpen] = useState(true);
  // CTO ativa no modal de interação (clientes + cadastro)
  const [activeCto, setActiveCto] = useState(null);

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
      await window.alert("Falha ao salvar posição: " + (e?.response?.data?.detail || e.message));
    }
  }, []);

  // Mantém referência sempre atualizada do cableDraft para os handlers
  // capturados nos eventHandlers do Leaflet (evita closure stale).
  const cableDraftRef = useRef(cableDraft);
  const modeRef = useRef(mode);
  useEffect(() => { cableDraftRef.current = cableDraft; }, [cableDraft]);
  useEffect(() => { modeRef.current = mode; }, [mode]);

  // Handler: clique no mapa (modos add-ce / draw-cable waypoint)
  const handleMapClick = useCallback((latlng) => {
    const m = modeRef.current;
    const draft = cableDraftRef.current;
    if (m === "add-ce") {
      setNewCe({ lat: latlng.lat, lng: latlng.lng });
    } else if (m === "draw-cable" && draft.from) {
      setCableDraft((d) => ({
        ...d,
        waypoints: [...d.waypoints, { lat: latlng.lat, lng: latlng.lng }],
      }));
    }
  }, []);

  // Confirma criação da CE (modal/prompt)
  const confirmCreateCe = useCallback(async (name, type, capacity) => {
    if (!newCe || !name) return;
    try {
      await api.redeIaCeCreate({
        name, type: type || "secundaria",
        capacity_fo: capacity || 24,
        lat: newCe.lat, lng: newCe.lng,
        address: "", notes: "Criada manualmente via mapa interativo",
      });
      setNewCe(null);
      load();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }, [newCe, load]);

  // Handler: clique em CTO/CE durante modo add-cable OU draw-cable
  const handleEntityClick = useCallback(async (entity) => {
    const m = modeRef.current;
    const draft = cableDraftRef.current;
    if (m === "add-cable") {
      if (!draft.from) {
        setCableDraft((d) => ({ ...d, from: entity }));
        return true;
      }
      if (draft.from.id === entity.id) {
        setCableDraft((d) => ({ ...d, from: null }));
        return true;
      }
      try {
        await api.redeIaCableCreate({
          type: draft.cableType,
          from_id: draft.from.id, from_type: draft.from.type,
          to_id: entity.id, to_type: entity.type,
          segments: [
            { lat: draft.from.lat, lng: draft.from.lng },
            { lat: entity.lat, lng: entity.lng },
          ],
          length_m: null,
          notes: "Criado manualmente via mapa interativo",
        });
        setCableDraft((d) => ({ ...d, from: null }));
        load();
      } catch (e) {
        await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
      }
      return true;
    }
    if (m === "draw-cable") {
      if (!draft.from) {
        setCableDraft((d) => ({ ...d, from: entity, waypoints: [] }));
        return true;
      }
      if (draft.from.id === entity.id) return true;
      try {
        const segs = [
          { lat: draft.from.lat, lng: draft.from.lng },
          ...draft.waypoints,
          { lat: entity.lat, lng: entity.lng },
        ];
        await api.redeIaCableCreate({
          type: draft.cableType,
          from_id: draft.from.id, from_type: draft.from.type,
          to_id: entity.id, to_type: entity.type,
          segments: segs,
          length_m: null,
          notes: `Desenhado com ${draft.waypoints.length} pontos intermediários`,
        });
        setCableDraft((d) => ({ ...d, from: null, waypoints: [] }));
        load();
      } catch (e) {
        await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
      }
      return true;
    }
    return false;
  }, [load]);

  const autoGenerate = async () => {
    if (!await window.confirm("rede_IA vai agrupar CTOs próximas em CEs e criar cabos 24FO automaticamente. Continuar?")) return;
    setBusy(true);
    try {
      const r = await api.redeIaAutoGenerateCes(200);
      await load();
      await window.alert(`✓ ${r.ces_created} CEs criadas · ${r.cables_created} cabos · ${r.ctos_clustered} CTOs agrupadas`);
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  // Atualiza waypoints de um cabo existente após drag (modo drag)
  const updateCableWaypoint = useCallback(async (cableId, idx, latlng) => {
    const cable = data.cables.find((c) => c.id === cableId);
    if (!cable) return;
    const newSegs = [...(cable.segments || [])];
    newSegs[idx] = { lat: latlng.lat, lng: latlng.lng };
    try {
      await api.redeIaCableUpdate(cableId, {
        type: cable.type,
        from_id: cable.from_id, from_type: cable.from_type,
        to_id: cable.to_id, to_type: cable.to_type,
        segments: newSegs,
        length_m: cable.length_m,
        notes: cable.notes || "",
      });
      // atualiza local
      setData((d) => ({
        ...d,
        cables: d.cables.map((c) =>
          c.id === cableId ? { ...c, segments: newSegs } : c),
      }));
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }, [data.cables]);

  // Insere waypoint no meio do cabo (clique em segmento)
  const insertCableWaypoint = useCallback(async (cableId, latlng, afterIdx) => {
    const cable = data.cables.find((c) => c.id === cableId);
    if (!cable) return;
    const segs = [...(cable.segments || [])];
    segs.splice(afterIdx + 1, 0, { lat: latlng.lat, lng: latlng.lng });
    try {
      await api.redeIaCableUpdate(cableId, {
        type: cable.type,
        from_id: cable.from_id, from_type: cable.from_type,
        to_id: cable.to_id, to_type: cable.to_type,
        segments: segs,
        length_m: cable.length_m,
        notes: cable.notes || "",
      });
      setData((d) => ({
        ...d,
        cables: d.cables.map((c) =>
          c.id === cableId ? { ...c, segments: segs } : c),
      }));
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }, [data.cables]);

  const removeCable = async (id) => {
    if (!await window.confirm("Excluir este cabo?")) return;
    try {
      await api.redeIaCableDelete(id);
      load();
    } catch (e) { await window.alert(e?.response?.data?.detail || "Erro"); }
  };
  const removeCe = async (id) => {
    if (!await window.confirm("Excluir esta CE? Os cabos ligados também serão removidos.")) return;
    try {
      await api.redeIaCeDelete(id);
      load();
    } catch (e) { await window.alert(e?.response?.data?.detail || "Erro"); }
  };
  const removeCto = async (cto) => {
    if (!await window.confirm(
      `Apagar a CTO "${cto.name}"?\n\n` +
      "Vai remover a CTO + todos os cabos ligados a ela. " +
      "ONUs e clientes vinculados NÃO serão afetados (continuam no SmartOLT). " +
      "Esta ação não pode ser desfeita."
    )) return;
    try {
      await api._client.delete(`/rede-ia/ctos/${cto.id}`);
      load();
    } catch (e) {
      await window.alert(e?.response?.data?.detail || "Erro ao apagar CTO");
    }
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
        <button data-testid="map-share-btn" onClick={async () => {
          const ttlInput = await window.prompt("Validade do link (dias, 1-365):", "30");
          const ttl = parseInt(ttlInput, 10);
          if (!ttl || ttl < 1 || ttl > 365) return;
          try {
            const r = await api.redeIaPublicTokenCreate(vlanFilter || null, ttl);
            const url = `${window.location.origin}${r.share_url}`;
            try { await navigator.clipboard.writeText(url); } catch (_) {}
            const exp = new Date(r.expires_at).toLocaleString("pt-BR");
            await window.prompt(
              `Link público (read-only) — copiado!\nExpira em ${exp} (${ttl} dias):`,
              url,
            );
          } catch (e) {
            await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
          }
        }} style={tbBtn("#16a34a")}
            title="Gera link público read-only com TTL configurável">
          🔗 Compartilhar
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
          <HeatLayer ctos={filteredCtos} enabled={showHeatmap} />
          <MapClickHandler
            enabled={mode === "add-ce" || mode === "draw-cable"}
            onClick={handleMapClick}
          />

          {/* Prévia do cabo em desenho (modo draw-cable) */}
          {mode === "draw-cable" && cableDraft.from && (
            <Polyline
              positions={[
                [cableDraft.from.lat, cableDraft.from.lng],
                ...cableDraft.waypoints.map((w) => [w.lat, w.lng]),
              ]}
              pathOptions={{
                color: CABLE_COLORS[cableDraft.cableType] || "#7c3aed",
                weight: 4, opacity: 0.6, dashArray: "8 8",
              }}
            />
          )}
          {/* Waypoints da prévia */}
          {mode === "draw-cable" && cableDraft.waypoints.map((w, i) => (
            <CircleMarker key={`wp-${i}`} center={[w.lat, w.lng]}
              radius={6}
              pathOptions={{
                color: "#7c3aed", fillColor: "#fff",
                fillOpacity: 1, weight: 3,
              }}
              eventHandlers={{
                click: () => {
                  // remove waypoint clicado
                  setCableDraft((d) => ({
                    ...d,
                    waypoints: d.waypoints.filter((_, idx) => idx !== i),
                  }));
                },
              }}>
              <Tooltip>{`Ponto ${i + 1} · clique para remover`}</Tooltip>
            </CircleMarker>
          ))}

          {/* CE preview (modo add-ce) */}
          {newCe && (
            <Marker position={[newCe.lat, newCe.lng]} icon={makeCeIcon({})}>
              <Popup autoOpen>
                <CeCreationForm
                  onCancel={() => setNewCe(null)}
                  onConfirm={confirmCreateCe}
                />
              </Popup>
            </Marker>
          )}

          {/* Cabos */}
          {data.cables.map((cab) => {
            const path = buildCablePath(cab);
            if (!path) return null;
            return (
              <React.Fragment key={cab.id}>
                <Polyline positions={path}
                  pathOptions={{
                    color: CABLE_COLORS[cab.type] || "#64748b",
                    weight: CABLE_WIDTHS[cab.type] || 3,
                    opacity: 0.85,
                    dashArray: cab.type === "drop" ? "6 6" : null,
                  }}>
                  <Popup>
                    <div style={{ minWidth: 220 }}>
                      <div style={{ fontWeight: 800, marginBottom: 4 }}>
                        Cabo {cab.type.toUpperCase()}
                      </div>
                      <div style={{ fontSize: 12, color: "#64748b" }}>
                        {cab.fo_count} fibras · {cab.length_m
                          ? `${Math.round(cab.length_m)}m` : "comprimento ?"}
                      </div>
                      {cab.created_by && (
                        <div style={{ fontSize: 11, marginTop: 4,
                                        color: "#475569" }}>
                          Lançado por <strong>{cab.created_by}</strong>
                          {cab.created_at && ` · ${new Date(cab.created_at).toLocaleString("pt-BR", {day:"2-digit",month:"2-digit",year:"2-digit",hour:"2-digit",minute:"2-digit"})}`}
                        </div>
                      )}
                      {cab.stok_debit && (
                        <div style={{ marginTop: 6, padding: "5px 8px",
                                        background: "#f0fdf4",
                                        border: "1px solid #bbf7d0",
                                        borderRadius: 6, fontSize: 11,
                                        color: "#065f46" }}>
                          📦 Estoque: <strong>{Math.abs(cab.stok_debit.meters_signed)}m</strong>
                          {" "}de <strong>{cab.stok_debit.consumable_id.replace("fibra_","").toUpperCase()}</strong>
                          {" "}debitados de <strong>{cab.stok_debit.location === "empresa" ? "Empresa" : "Técnico"}</strong>
                        </div>
                      )}
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
                {/* Waypoints intermediários (índices 1..n-2 — exclui pontas) */}
                {mode === "drag" && (cab.segments || []).map((seg, idx) => {
                  if (idx === 0 || idx === (cab.segments.length - 1)) return null;
                  return (
                    <Marker key={`${cab.id}-wp-${idx}`}
                      position={[seg.lat, seg.lng]}
                      draggable={true}
                      icon={L.divIcon({
                        className: "waypoint",
                        html: `<div style="width:14px;height:14px;border-radius:50%;
                          background:#fff;border:3px solid ${CABLE_COLORS[cab.type] || "#64748b"};
                          box-shadow:0 1px 3px rgba(0,0,0,0.3);"></div>`,
                        iconSize: [14, 14], iconAnchor: [7, 7],
                      })}
                      eventHandlers={{
                        dragend: (e) => updateCableWaypoint(cab.id, idx,
                                                              e.target.getLatLng()),
                      }}>
                      <Tooltip>Arraste para curvar o cabo</Tooltip>
                    </Marker>
                  );
                })}
              </React.Fragment>
            );
          })}

          {/* CEs */}
          {data.ces.map((ce) => (
            <Marker key={ce.id} position={[ce.lat, ce.lng]}
              icon={makeCeIcon(ce)}
              draggable={mode === "drag"}
              eventHandlers={{
                dragend: (e) => handleDragEnd("ce", ce.id, e.target.getLatLng()),
                click: (e) => {
                  if (mode === "add-cable" || mode === "draw-cable") {
                    e.originalEvent?.stopPropagation();
                    handleEntityClick({ id: ce.id, type: "ce",
                                         lat: ce.lat, lng: ce.lng, name: ce.name });
                    e.target.closePopup();
                  }
                },
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
            // Saúde física da IA (Gemini Vision)
            const photoSev = Number(c.photo_severity || 0);
            const photoColor = photoSev >= 70 ? "#dc2626"
                                : photoSev >= 40 ? "#ea580c"
                                : photoSev >= 15 ? "#ca8a04" : null;
            return (
              <React.Fragment key={c.id}>
                {/* halo saúde física via IA (anel externo) */}
                {photoColor && (
                  <CircleMarker center={[c.lat, c.lng]}
                    radius={28}
                    pathOptions={{
                      color: photoColor, fillColor: photoColor,
                      fillOpacity: 0.10, weight: 2,
                      dashArray: "3 4",
                    }} />
                )}
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
                    dblclick: (e) => {
                      // Pedido do usuário: clicar 2× na CTO abre o card
                      // com as informações + fotos cadastradas.
                      e.originalEvent?.stopPropagation();
                      e.target.openPopup();
                    },
                    click: (e) => {
                      if (mode === "add-cable" || mode === "draw-cable") {
                        e.originalEvent?.stopPropagation();
                        handleEntityClick({ id: c.id, type: "cto",
                                             lat: c.lat, lng: c.lng, name: c.name });
                        e.target.closePopup();
                      }
                    },
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
                      {photoColor && (
                        <div data-testid={`cto-photo-health-${c.id}`}
                              style={{
                                marginTop: 6, padding: 6, borderRadius: 6,
                                background: photoColor + "15",
                                border: `1px solid ${photoColor}`,
                                fontSize: 11, color: "#0f172a", lineHeight: 1.35,
                              }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{ color: photoColor, fontWeight: 800 }}>
                              🤖 Saúde física {photoSev}/100
                            </span>
                          </div>
                          {c.photo_summary && (
                            <div style={{ marginTop: 3, color: "#475569" }}>
                              {c.photo_summary}
                            </div>
                          )}
                          {(c.photo_tags || []).length > 0 && (
                            <div style={{ marginTop: 4, display: "flex",
                                            flexWrap: "wrap", gap: 3 }}>
                              {(c.photo_tags || []).slice(0, 4).map((tg) => (
                                <span key={tg}
                                      style={{ fontSize: 9, padding: "1px 6px",
                                                borderRadius: 999,
                                                background: "#fff",
                                                color: photoColor,
                                                border: `1px solid ${photoColor}`,
                                                fontWeight: 700 }}>
                                  {tg.replace(/_/g, " ")}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                      {c.moved_manually && (
                        <div style={{ fontSize: 10, color: "#7c3aed", marginTop: 4 }}>
                          ✋ Posição ajustada manualmente
                        </div>
                      )}

                      {Array.isArray(c.photos) && c.photos.length > 0 && (
                        <div data-testid={`cto-photos-${c.id}`}
                              style={{
                                marginTop: 8, paddingTop: 8,
                                borderTop: "1px dashed #cbd5e1",
                              }}>
                          <div style={{ fontSize: 10, fontWeight: 800,
                                          color: "#7c3aed",
                                          textTransform: "uppercase",
                                          letterSpacing: 0.4,
                                          marginBottom: 5 }}>
                            📸 Fotos cadastradas ({c.photos.length})
                          </div>
                          <div style={{ display: "grid",
                                          gridTemplateColumns: "repeat(3, 1fr)",
                                          gap: 4 }}>
                            {c.photos.slice(0, 6).map((ph) => (
                              <ThumbWithDblClick key={ph.id}
                                    src={ph.url}
                                    testid={`cto-photo-thumb-${ph.id}`}
                                    onOpen={() => setPhotoLightbox({
                                      url: ph.url,
                                      ctoName: c.name,
                                      uploadedByName: ph.uploaded_by_name,
                                    })} />
                            ))}
                          </div>
                        </div>
                      )}

                      <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
                        {(() => {
                          const tok = window.localStorage.getItem("ponto_token") || "";
                          const apiBase = process.env.REACT_APP_BACKEND_URL;
                          return (
                            <>
                              <button
                                onClick={(e) => {
                                  e.preventDefault();
                                  setActiveCto({ id: c.id, name: c.name,
                                                   capacity: c.capacity });
                                }}
                                data-testid={`map-cto-clients-${c.id}`}
                                style={{
                                  ...popBtn("#10b981"),
                                  background: "linear-gradient(135deg,#10b981,#059669)",
                                  cursor: "pointer",
                                  border: 0, color: "#fff",
                                }}>
                                👥 Clientes / Cadastrar
                              </button>
                              <a href={`${apiBase}/api/rede-ia/ctos/${c.id}/qrcode.png?t=${encodeURIComponent(tok)}`}
                                  target="_blank" rel="noreferrer"
                                  data-testid={`map-cto-qr-${c.id}`}
                                  style={popBtn("#7c3aed")}>QR</a>
                              <a href={`${apiBase}/api/rede-ia/ctos/${c.id}/pdf.pdf?t=${encodeURIComponent(tok)}`}
                                  target="_blank" rel="noreferrer"
                                  data-testid={`map-cto-pdf-${c.id}`}
                                  style={popBtn("#dc2626")}>PDF</a>
                              <button
                                onClick={(e) => {
                                  e.preventDefault();
                                  removeCto(c);
                                }}
                                data-testid={`map-cto-delete-${c.id}`}
                                style={{
                                  ...popBtn("#475569"),
                                  background: "#fff",
                                  color: "#dc2626",
                                  border: "1px solid #fecaca",
                                  cursor: "pointer",
                                }}>
                                🗑 Apagar
                              </button>
                            </>
                          );
                        })()}
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
          display: "flex", flexDirection: "column", gap: 6, minWidth: 160,
        }}>
          <button data-testid="map-mode-view"
            onClick={() => { setMode("view");
                              setCableDraft({ ...cableDraft, from: null, waypoints: [] });
                              setNewCe(null); }}
            style={modeBtn(mode === "view")}>👁 Ver</button>
          <button data-testid="map-mode-drag"
            onClick={() => { setMode("drag");
                              setCableDraft({ ...cableDraft, from: null, waypoints: [] });
                              setNewCe(null); }}
            style={modeBtn(mode === "drag")}>✋ Mover/Curvar</button>
          <button data-testid="map-mode-add-ce"
            onClick={() => { setMode("add-ce");
                              setCableDraft({ ...cableDraft, from: null, waypoints: [] }); }}
            style={modeBtn(mode === "add-ce")}>📍 Criar CE</button>
          <button data-testid="map-mode-cable"
            onClick={() => { setMode("add-cable");
                              setCableDraft({ ...cableDraft, from: null, waypoints: [] });
                              setNewCe(null); }}
            style={modeBtn(mode === "add-cable")}>➕ Cabo reto</button>
          <button data-testid="map-mode-draw-cable"
            onClick={() => { setMode("draw-cable");
                              setCableDraft({ ...cableDraft, from: null, waypoints: [] });
                              setNewCe(null); }}
            style={modeBtn(mode === "draw-cable")}>✏️ Desenhar cabo</button>
          {(mode === "add-cable" || mode === "draw-cable") && (
            <select data-testid="map-cable-type"
              value={cableDraft.cableType}
              onChange={(e) => setCableDraft({ ...cableDraft, cableType: e.target.value })}
              style={{
                padding: "4px 6px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 11, fontWeight: 600,
              }}>
              <option value="drop">Drop (1FO)</option>
              <option value="6fo">6 FO</option>
              <option value="12fo">12 FO</option>
              <option value="24fo">24 FO</option>
              <option value="48fo">48 FO</option>
              <option value="96fo">96 FO</option>
            </select>
          )}
          <button data-testid="map-mode-heatmap"
            onClick={() => setShowHeatmap(!showHeatmap)}
            style={modeBtn(showHeatmap)}>🔥 Heatmap</button>
        </div>

        {/* Banner instruções por modo */}
        {mode === "add-cable" && (
          <div data-testid="cable-instructions" style={instructionsBanner("#7c3aed")}>
            {cableDraft.from
              ? `✅ Origem: ${cableDraft.from.name} → Clique no destino (CTO ou CE)`
              : "➕ Modo cabo reto · Clique na CTO/CE de origem"}
          </div>
        )}
        {mode === "draw-cable" && (
          <div data-testid="draw-cable-instructions" style={instructionsBanner("#0ea5e9")}>
            {!cableDraft.from
              ? "✏️ Modo desenhar · Clique na CTO/CE de ORIGEM"
              : cableDraft.waypoints.length === 0
                ? `✅ ${cableDraft.from.name} · Agora clique no mapa para criar pontos (curvas) · depois clique na CTO/CE de destino`
                : `${cableDraft.waypoints.length} ponto${cableDraft.waypoints.length>1?"s":""} adicionados · Clique no mapa para mais OU na CTO/CE de destino para finalizar`}
          </div>
        )}
        {mode === "add-ce" && (
          <div data-testid="add-ce-instructions" style={instructionsBanner("#16a34a")}>
            📍 Clique no mapa onde a CE será instalada
          </div>
        )}
      </div>
      {activeCto && (
        <CTOInteractionModal
          ctoId={activeCto.id}
          ctoMeta={activeCto}
          onClose={() => setActiveCto(null)}
        />
      )}
      {photoLightbox && (
        <PhotoLightbox {...photoLightbox}
                        onClose={() => setPhotoLightbox(null)} />
      )}
    </Card>
  );
}

/* PhotoLightbox compartilhado — modal full-screen pra ampliar foto da CTO. */
function ThumbWithDblClick({ src, testid, onOpen }) {
  // Leaflet bloqueia dblclick nativo dentro do Popup (DomEvent.
  // disableClickPropagation engole o 2º click). Workaround: detecta
  // 2 cliques manualmente com timer de 350ms.
  const clickRef = useRef({ count: 0, timer: null });
  const handle = (e) => {
    e.stopPropagation();
    const c = clickRef.current;
    c.count += 1;
    if (c.timer) { clearTimeout(c.timer); c.timer = null; }
    if (c.count >= 2) {
      c.count = 0;
      onOpen();
      return;
    }
    c.timer = setTimeout(() => { c.count = 0; }, 350);
  };
  return (
    <img src={src} alt="Foto CTO"
          title="2× para ampliar"
          onClick={handle}
          onDoubleClick={(e) => { e.stopPropagation(); onOpen(); }}
          data-testid={testid}
          style={{
            width: "100%", aspectRatio: "1/1",
            objectFit: "cover", borderRadius: 4,
            cursor: "zoom-in",
            border: "1px solid #e2e8f0",
          }} />
  );
}

function PhotoLightbox({ url, ctoName, uploadedByName, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div data-testid="map-photo-lightbox"
          onClick={onClose}
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(0,0,0,.92)",
            display: "grid", placeItems: "center", padding: 20,
            cursor: "zoom-out",
          }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ display: "flex", flexDirection: "column", gap: 12,
                      alignItems: "center" }}>
        <div style={{
          padding: "6px 14px", borderRadius: 999,
          background: "rgba(255,255,255,.1)", color: "white",
          fontSize: 12, fontWeight: 700, display: "flex", gap: 10,
        }}>
          📸 {ctoName || "CTO"}
          {uploadedByName && (
            <span style={{ opacity: 0.7, fontWeight: 500 }}>
              · {uploadedByName}
            </span>
          )}
        </div>
        <img src={url} alt="Foto CTO ampliada"
              data-testid="map-lightbox-img"
              style={{
                maxWidth: "92vw", maxHeight: "82vh", borderRadius: 8,
                boxShadow: "0 12px 40px rgba(0,0,0,.6)",
              }} />
        <button data-testid="map-lightbox-close"
                onClick={onClose}
                style={{
                  padding: "8px 18px", borderRadius: 8,
                  border: "1px solid rgba(255,255,255,.3)",
                  background: "rgba(255,255,255,.1)", color: "white",
                  fontSize: 12, fontWeight: 700, cursor: "pointer",
                }}>
          Fechar (Esc)
        </button>
      </div>
    </div>
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

const instructionsBanner = (color) => ({
  position: "absolute", top: 12, left: "50%",
  transform: "translateX(-50%)", zIndex: 1000,
  background: color, color: "#fff",
  padding: "8px 16px", borderRadius: 8,
  fontSize: 12, fontWeight: 600, maxWidth: 540, textAlign: "center",
  boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
});

function CeCreationForm({ onCancel, onConfirm }) {
  const [name, setName] = useState("CE-NOVA-001");
  const [type, setType] = useState("secundaria");
  const [cap, setCap] = useState(24);
  return (
    <div style={{ minWidth: 220 }}>
      <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 8 }}>
        Nova Caixa de Emenda
      </div>
      <label style={{ fontSize: 11, color: "#64748b", display: "block", marginBottom: 2 }}>
        Nome
      </label>
      <input value={name} onChange={(e) => setName(e.target.value)}
        data-testid="ce-name-input"
        style={{ width: "100%", padding: "6px 8px", borderRadius: 6,
                  border: "1px solid #cbd5e1", fontSize: 12, marginBottom: 6 }} />
      <label style={{ fontSize: 11, color: "#64748b", display: "block", marginBottom: 2 }}>
        Tipo
      </label>
      <select value={type} onChange={(e) => setType(e.target.value)}
        data-testid="ce-type-input"
        style={{ width: "100%", padding: "6px 8px", borderRadius: 6,
                  border: "1px solid #cbd5e1", fontSize: 12, marginBottom: 6 }}>
        <option value="primaria">Primária</option>
        <option value="secundaria">Secundária</option>
        <option value="terciaria">Terciária</option>
        <option value="emenda_aerea">Emenda aérea</option>
        <option value="emenda_subterranea">Emenda subterrânea</option>
      </select>
      <label style={{ fontSize: 11, color: "#64748b", display: "block", marginBottom: 2 }}>
        Capacidade (FO)
      </label>
      <input type="number" value={cap}
        onChange={(e) => setCap(parseInt(e.target.value, 10) || 24)}
        data-testid="ce-cap-input"
        style={{ width: "100%", padding: "6px 8px", borderRadius: 6,
                  border: "1px solid #cbd5e1", fontSize: 12, marginBottom: 10 }} />
      <div style={{ display: "flex", gap: 6 }}>
        <button onClick={onCancel}
          style={{ flex: 1, padding: "6px", border: "1px solid #cbd5e1",
                    background: "#fff", borderRadius: 6, fontSize: 11,
                    cursor: "pointer", fontWeight: 600 }}>
          Cancelar
        </button>
        <button data-testid="ce-confirm-btn"
          onClick={() => onConfirm(name, type, cap)}
          style={{ flex: 1, padding: "6px", border: 0,
                    background: "#2563eb", color: "#fff",
                    borderRadius: 6, fontSize: 11,
                    cursor: "pointer", fontWeight: 700 }}>
          Criar CE
        </button>
      </div>
    </div>
  );
}

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
