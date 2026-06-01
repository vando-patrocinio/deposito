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
import { fmtAddress } from "@/utils/format";
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

// iter180 — Helper: voa até o elemento destacado pela busca
function FlyToHighlight({ highlight }) {
  const map = useMap();
  useEffect(() => {
    if (!highlight || !highlight.lat || !highlight.lng) return;
    map.flyTo([highlight.lat, highlight.lng], Math.max(map.getZoom(), 19),
              { duration: 0.7 });
  }, [highlight, map]);
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
  // iter149 — filtro de cabos por tipo lógico (drop/distribuicao/backbone)
  // ou capacidade legada (6/12/24/48/96fo). "all" mostra todos.
  const [cableFilter, setCableFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("view"); // view | drag | add-cable | add-ce | draw-cable
  // iter183 — modal lateral de detalhes do cabo (double-click na polyline)
  const [activeCableDetail, setActiveCableDetail] = useState(null);
  const [vlanStats, setVlanStats] = useState(null);
  const [photoLightbox, setPhotoLightbox] = useState(null); // {url, ctoName, uploadedByName}
  const [cableDraft, setCableDraft] = useState({
    from: null,           // { id, type, lat, lng, name }
    waypoints: [],        // [{lat,lng}] intermediários do draw-cable
    cableType: "12fo",
  });
  const [newCe, setNewCe] = useState(null); // { lat, lng } pendente nome
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [legendOpen, setLegendOpen] = useState(true);
  // Mancha de sinal ruim/crítico
  const [showSignalLayer, setShowSignalLayer] = useState(false);
  const [signalPoints, setSignalPoints] = useState([]);
  const [signalStats, setSignalStats] = useState(null);
  const [signalLoading, setSignalLoading] = useState(false);
  // CTO ativa no modal de interação (clientes + cadastro)
  const [activeCto, setActiveCto] = useState(null);
  // iter180 — busca rápida por nome (CTO_301_004, CE_00001, CABO_301_002…)
  const [searchQuery, setSearchQuery] = useState("");
  const [searchHighlight, setSearchHighlight] = useState(null);
  // searchHighlight = { id, kind: "cto"|"ce"|"cable", lat, lng, name }

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

  // Carrega/recarrega pontos de sinal quando o toggle for ativado
  useEffect(() => {
    if (!showSignalLayer) return;
    let cancelled = false;
    (async () => {
      setSignalLoading(true);
      try {
        // geocode_max=0 → só usa cache (rápido). User pode disparar batch manual.
        const r = await api.redeIaSignalPoints("all", 0);
        if (cancelled) return;
        setSignalPoints(r.points || []);
        setSignalStats(r.stats || null);
      } catch (e) {
        console.warn("[signal-layer] err:", e);
      } finally {
        if (!cancelled) setSignalLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [showSignalLayer]);

  // Batch geocode manual (botão "Geocodificar mais")
  async function geocodeSignalBatch() {
    if (signalLoading) return;
    setSignalLoading(true);
    try {
      const r = await api.redeIaSignalGeocodeBatch(40);
      // Recarrega após batch
      const sp = await api.redeIaSignalPoints("all", 0);
      setSignalPoints(sp.points || []);
      setSignalStats(sp.stats || null);
      window.alert(
        `Geocodificou ${r.geocoded} de ${r.processed} ONUs. `
        + `${r.remaining_estimate} ainda sem coords — clique de novo pra processar mais.`
      );
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setSignalLoading(false);
    }
  }

  // iter180 — Busca por nome (CTO_301_004, CE_00001, CABO_301_002 ou trecho)
  const searchMatches = useMemo(() => {
    const q = (searchQuery || "").trim().toUpperCase();
    if (q.length < 2) return [];
    const out = [];
    (data.ctos || []).forEach((c) => {
      const name = (c.name || "").toUpperCase();
      const legacy = (c.name_legacy || "").toUpperCase();
      if (name.includes(q) || legacy.includes(q)) {
        out.push({ id: c.id, name: c.name, kind: "cto",
                     lat: c.lat, lng: c.lng });
      }
    });
    (data.ces || []).forEach((ce) => {
      const name = (ce.name || "").toUpperCase();
      const legacy = (ce.name_legacy || "").toUpperCase();
      if (name.includes(q) || legacy.includes(q)) {
        out.push({ id: ce.id, name: ce.name, kind: "ce",
                     lat: ce.lat, lng: ce.lng });
      }
    });
    (data.cables || []).forEach((cab) => {
      const name = (cab.name || "").toUpperCase();
      const legacy = (cab.name_legacy || "").toUpperCase();
      if (name.includes(q) || legacy.includes(q)) {
        // cabo: usa ponto médio dos waypoints (ou origem)
        const wps = cab.waypoints || [];
        const mid = wps[Math.floor(wps.length / 2)] || wps[0];
        if (mid) out.push({ id: cab.id, name: cab.name, kind: "cable",
                              lat: mid.lat, lng: mid.lng });
      }
    });
    return out.slice(0, 12);
  }, [searchQuery, data.ctos, data.ces, data.cables]);

  const filteredCtos = useMemo(() => {
    return data.ctos.filter((c) => {
      if (vlanFilter && String(c.vlan) !== String(vlanFilter)) return false;
      if (healthFilter && c.health.status !== healthFilter) return false;
      return true;
    });
  }, [data.ctos, vlanFilter, healthFilter]);

  // iter149 — filtragem de cabos por tipo + VLAN (via endpoint from)
  const filteredCables = useMemo(() => {
    const ctosByIdLocal = new Map();
    (data.ctos || []).forEach((c) => ctosByIdLocal.set(c.id, c));
    return (data.cables || []).filter((cab) => {
      // Filtro por tipo
      if (cableFilter !== "all") {
        const logical = (cab.cable_type_logical || "").toLowerCase();
        const t = (cab.type || "").toLowerCase();
        const isLogical = ["drop", "distribuicao", "backbone"].includes(cableFilter);
        if (isLogical) {
          if (logical !== cableFilter && t !== cableFilter) return false;
        } else {
          // Capacidade legada (6fo/12fo/24fo/48fo/96fo)
          if (t !== cableFilter) return false;
        }
      }
      // Filtro por VLAN — usa endpoint origem para deduzir
      if (vlanFilter) {
        const from = ctosByIdLocal.get(cab.from_id);
        if (!from || String(from.vlan) !== String(vlanFilter)) return false;
      }
      return true;
    });
  }, [data.cables, data.ctos, cableFilter, vlanFilter]);

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

  // iter183 — carrega stats da VLAN ao abrir o modal de cabo
  useEffect(() => {
    if (!activeCableDetail) { setVlanStats(null); return; }
    const v = activeCableDetail.vlan;
    if (!v) { setVlanStats(null); return; }
    api.redeIaVlanStats(v)
      .then((r) => setVlanStats(r))
      .catch(() => setVlanStats(null));
  }, [activeCableDetail]);
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
        {/* iter180 — busca rápida por nome */}
        <div style={{ position: "relative" }}>
          <input data-testid="map-search-input"
            type="search" value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setSearchQuery(""); setSearchHighlight(null);
              } else if (e.key === "Enter" && searchMatches.length > 0) {
                const m = searchMatches[0];
                setSearchHighlight(m); setSearchQuery(m.name);
              }
            }}
            placeholder="🔎 CTO_301_004, CE_00001…"
            style={{
              ...selectStyle, width: 220, paddingLeft: 12,
              fontFamily: "monospace",
              borderColor: searchHighlight ? "#06b6d4" : undefined,
            }} />
          {searchQuery && (
            <button data-testid="map-search-clear"
                    onClick={() => { setSearchQuery(""); setSearchHighlight(null); }}
                    style={{
                      position: "absolute", right: 6, top: "50%",
                      transform: "translateY(-50%)",
                      background: "transparent", border: 0,
                      fontSize: 14, cursor: "pointer", color: "#94a3b8",
                      padding: "2px 6px",
                    }}>✕</button>
          )}
          {searchMatches.length > 0
            && !(searchHighlight && searchQuery === searchHighlight.name) && (
            <div data-testid="map-search-results" style={{
              position: "absolute", top: "100%", left: 0,
              marginTop: 4, background: "#fff",
              border: "1px solid var(--border-default)",
              borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
              zIndex: 1000, minWidth: 260, maxHeight: 320,
              overflowY: "auto",
            }}>
              {searchMatches.map((m) => (
                <button key={`${m.kind}-${m.id}`}
                        data-testid={`map-search-hit-${m.id}`}
                        onClick={() => {
                          setSearchHighlight(m);
                          setSearchQuery(m.name);
                        }}
                        style={{
                          display: "block", width: "100%",
                          padding: "8px 12px", textAlign: "left",
                          background: "transparent", border: 0,
                          cursor: "pointer", fontSize: 12.5,
                          borderBottom: "1px solid #f1f5f9",
                          fontFamily: "monospace",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#f1f5f9")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                  <span style={{
                    display: "inline-block", padding: "1px 6px", borderRadius: 4,
                    marginRight: 8, fontSize: 9, fontWeight: 800,
                    background: m.kind === "cto" ? "#dbeafe"
                                : m.kind === "ce" ? "#fef3c7" : "#fed7aa",
                    color: m.kind === "cto" ? "#1e40af"
                            : m.kind === "ce" ? "#92400e" : "#9a3412",
                  }}>{m.kind.toUpperCase()}</span>
                  {m.name}
                </button>
              ))}
            </div>
          )}
        </div>

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
        <select data-testid="map-filter-cable" value={cableFilter}
          onChange={(e) => setCableFilter(e.target.value)}
          style={selectStyle}
          title="Filtra os cabos exibidos no mapa">
          <option value="all">Todos os cabos</option>
          <option value="drop">🔵 Drop (cliente)</option>
          <option value="distribuicao">🟧 Distribuição</option>
          <option value="backbone">🔴 Backbone</option>
          <option value="6fo">6FO</option>
          <option value="12fo">12FO</option>
          <option value="24fo">24FO</option>
          <option value="48fo">48FO</option>
          <option value="96fo">96FO</option>
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
        <KmzControls vlanFilter={vlanFilter} onImported={load} />
        <button data-testid="map-toggle-signal-layer"
                onClick={() => setShowSignalLayer((v) => !v)}
                title="Mostra mancha de clientes com sinal ruim/crítico no mapa"
                style={{
                  padding: "6px 12px", borderRadius: 7, fontSize: 12,
                  fontWeight: 700, cursor: "pointer",
                  background: showSignalLayer ? "#dc2626" : "#fff",
                  color: showSignalLayer ? "#fff" : "#dc2626",
                  border: `1.5px solid #dc2626`,
                }}>
          {signalLoading ? "⏳ Carregando…"
            : (showSignalLayer
                ? `⚠️ Sinal ruim${signalStats
                    ? ` (${signalStats.with_coords}/${signalStats.total_with_issue})`
                    : ""}`
                : "⚠️ Mostrar sinal ruim")}
        </button>
        {showSignalLayer && signalStats?.without_coords > 0 && (
          <button data-testid="map-signal-geocode-more"
                  onClick={geocodeSignalBatch}
                  disabled={signalLoading}
                  title="Geocodifica mais 40 clientes (~40 segundos)"
                  style={{
                    padding: "6px 10px", borderRadius: 7, fontSize: 11,
                    fontWeight: 700, cursor: signalLoading ? "wait" : "pointer",
                    background: "#0ea5e9", color: "#fff", border: 0,
                    opacity: signalLoading ? 0.5 : 1,
                  }}>
            ⚡ +40 ({signalStats.without_coords} restantes)
          </button>
        )}
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
          <FlyToHighlight highlight={searchHighlight} />
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
          {filteredCables.map((cab) => {
            const path = buildCablePath(cab);
            if (!path) return null;
            // iter149 — label flutuante no ponto médio do cabo
            const mid = path[Math.floor(path.length / 2)];
            const occPct = (cab.fo_count && cab.fibras_ocupadas != null)
              ? Math.round((cab.fibras_ocupadas / cab.fo_count) * 100) : null;
            const occColor = occPct == null ? "#64748b"
              : occPct >= 80 ? "#dc2626"
              : occPct >= 50 ? "#ea580c" : "#16a34a";
            return (
              <React.Fragment key={cab.id}>
                <Polyline positions={path}
                  eventHandlers={{
                    dblclick: () => setActiveCableDetail?.(cab),
                  }}
                  pathOptions={{
                    // iter186 — cabo solto (sem from/to vinculado) é laranja
                    color: cab.status === "cabo_solto"
                      ? "#ea580c"
                      : (CABLE_COLORS[cab.type] || "#64748b"),
                    // iter183 — espessura proporcional ao FO
                    weight: cab.fo_count
                      ? Math.max(3, Math.min(10, Math.log2(cab.fo_count) + 1))
                      : (CABLE_WIDTHS[cab.type] || 3),
                    opacity: cab.status === "cabo_solto" ? 0.95 : 0.85,
                    dashArray: cab.status === "cabo_solto"
                      ? "8 6"
                      : (cab.type === "drop" ? "6 6" : null),
                  }}>
                  <Tooltip permanent direction="center"
                             offset={[0, -8]} className="cable-label-tooltip">
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      padding: "2px 7px",
                      background: "rgba(255,255,255,0.96)",
                      border: `1px solid ${CABLE_COLORS[cab.type] || "#64748b"}`,
                      borderRadius: 999,
                      fontSize: 10, fontWeight: 700, color: "#0f172a",
                      whiteSpace: "nowrap",
                      boxShadow: "0 1px 4px rgba(15,23,42,0.18)",
                    }}>
                      {cab.name || (cab.type || "").toUpperCase()}
                      <span style={{
                        color: CABLE_COLORS[cab.type] || "#64748b",
                        fontWeight: 800,
                      }}>· {cab.fo_count || cab.type?.replace("fo", "")}FO</span>
                      {occPct != null && (
                        <span style={{
                          color: occColor, fontWeight: 800,
                        }}>· {occPct}%</span>
                      )}
                    </span>
                  </Tooltip>
                  <Popup>
                    <div style={{ minWidth: 240 }}>
                      <div style={{ fontWeight: 800, marginBottom: 4 }}>
                        {cab.name || `Cabo ${cab.type.toUpperCase()}`}
                      </div>
                      <div style={{ fontSize: 12, color: "#64748b" }}>
                        <strong>{cab.fo_count || 0} FO</strong>
                        {cab.total_length_m
                          ? <> · <strong>{Math.round(cab.total_length_m)}m</strong> total</>
                          : cab.length_m
                          ? <> · {Math.round(cab.length_m)}m</>
                          : null}
                        {cab.route_distance_m && (
                          <span> ({Math.round(cab.route_distance_m)}m trajeto + {cab.extra_margin_m || 20}m sobra)</span>
                        )}
                        {occPct != null && (
                          <span> · <strong style={{ color: occColor }}>
                            {cab.fibras_ocupadas}/{cab.fo_count} ocupadas ({occPct}%)
                          </strong></span>
                        )}
                      </div>
                      {cab.cable_brand && (
                        <div style={{ fontSize: 11, marginTop: 3, color: "#475569" }}>
                          Marca: <strong>{cab.cable_brand}</strong>
                          {cab.cable_serial && <> · NS: <code>{cab.cable_serial}</code></>}
                        </div>
                      )}
                      {(cab.cable_type_logical || cab.cable_type) && (
                        <div style={{ fontSize: 11, marginTop: 3,
                                        color: "#475569",
                                        textTransform: "capitalize" }}>
                          Tipo: <strong>{cab.cable_type_logical || cab.cable_type}</strong>
                        </div>
                      )}
                      {cab.created_by && (
                        <div style={{ fontSize: 11, marginTop: 4,
                                        color: "#475569" }}>
                          Lançado por <strong>{cab.created_by}</strong>
                          {cab.created_at && ` · ${new Date(cab.created_at).toLocaleString("pt-BR", {day:"2-digit",month:"2-digit",year:"2-digit",hour:"2-digit",minute:"2-digit"})}`}
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                        <button onClick={() => setActiveCableDetail?.(cab)}
                          style={{ padding: "4px 10px", border: 0,
                                    background: "#0d9488", color: "#fff",
                                    borderRadius: 6, fontSize: 11, cursor: "pointer",
                                    fontWeight: 700, flex: 1 }}>
                          Ver detalhes completos
                        </button>
                        <button onClick={() => removeCable(cab.id)}
                          style={{ padding: "4px 10px", border: 0,
                                    background: "#dc2626", color: "#fff",
                                    borderRadius: 6, fontSize: 11, cursor: "pointer",
                                    fontWeight: 700 }}>
                          Excluir
                        </button>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
                {/* iter186 — Pinos laranja pulsantes nas pontas SOLTAS */}
                {cab.is_loose && (cab.segments || []).length >= 2 && (
                  <>
                    {!cab.from_id && (
                      <Marker
                        position={[cab.segments[0].lat, cab.segments[0].lng]}
                        icon={L.divIcon({
                          className: "loose-end-pin",
                          html: `
                            <div style="position:relative;width:28px;height:28px;">
                              <div style="position:absolute;inset:0;border-radius:50%;
                                background:#ea580c;opacity:0.4;
                                animation:looseEndPulse 1.5s ease-out infinite;"></div>
                              <div style="position:absolute;top:6px;left:6px;
                                width:16px;height:16px;border-radius:50%;
                                background:#ea580c;border:3px solid #fff;
                                box-shadow:0 1px 4px rgba(0,0,0,0.4);"></div>
                            </div>`,
                          iconSize: [28, 28],
                          iconAnchor: [14, 14],
                        })}
                        eventHandlers={{
                          click: () => setActiveCableDetail?.({
                            ...cab, _loose_end: "from",
                            _loose_lat: cab.segments[0].lat,
                            _loose_lng: cab.segments[0].lng,
                          }),
                        }}>
                        <Tooltip direction="top" offset={[0, -12]}>
                          🧵 <strong>{cab.name}</strong>
                          <br />Ponta solta (Origem) — clique para vincular
                        </Tooltip>
                      </Marker>
                    )}
                    {!cab.to_id && (
                      <Marker
                        position={[
                          cab.segments[cab.segments.length - 1].lat,
                          cab.segments[cab.segments.length - 1].lng,
                        ]}
                        icon={L.divIcon({
                          className: "loose-end-pin",
                          html: `
                            <div style="position:relative;width:28px;height:28px;">
                              <div style="position:absolute;inset:0;border-radius:50%;
                                background:#ea580c;opacity:0.4;
                                animation:looseEndPulse 1.5s ease-out infinite;"></div>
                              <div style="position:absolute;top:6px;left:6px;
                                width:16px;height:16px;border-radius:50%;
                                background:#ea580c;border:3px solid #fff;
                                box-shadow:0 1px 4px rgba(0,0,0,0.4);"></div>
                            </div>`,
                          iconSize: [28, 28],
                          iconAnchor: [14, 14],
                        })}
                        eventHandlers={{
                          click: () => setActiveCableDetail?.({
                            ...cab, _loose_end: "to",
                            _loose_lat: cab.segments[cab.segments.length - 1].lat,
                            _loose_lng: cab.segments[cab.segments.length - 1].lng,
                          }),
                        }}>
                        <Tooltip direction="top" offset={[0, -12]}>
                          🧵 <strong>{cab.name}</strong>
                          <br />Ponta solta (Destino) — clique para vincular
                        </Tooltip>
                      </Marker>
                    )}
                  </>
                )}
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
            <React.Fragment key={ce.id}>
              {/* iter180 — anel de busca */}
              {searchHighlight?.id === ce.id && (
                <CircleMarker center={[ce.lat, ce.lng]}
                  radius={36}
                  pathOptions={{
                    color: "#06b6d4", fillColor: "#06b6d4",
                    fillOpacity: 0.18, weight: 3,
                  }} />
              )}
              <Marker position={[ce.lat, ce.lng]}
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
                    <div style={{ fontSize: 11, marginTop: 6 }}>📍 {fmtAddress(ce.address)}</div>
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
            </React.Fragment>
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
                {/* iter180 — anel de busca destacando o elemento encontrado */}
                {searchHighlight?.id === c.id && (
                  <CircleMarker center={[c.lat, c.lng]}
                    radius={36}
                    pathOptions={{
                      color: "#06b6d4", fillColor: "#06b6d4",
                      fillOpacity: 0.18, weight: 3,
                    }} />
                )}
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
                            {c.photos.slice(0, 6).map((ph, phIdx) => (
                              <ThumbWithDblClick key={ph.id}
                                    src={ph.url}
                                    testid={`cto-photo-thumb-${ph.id}`}
                                    onOpen={() => setPhotoLightbox({
                                      photos: c.photos.slice(0, 6),
                                      index: phIdx,
                                      ctoName: c.name,
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
          {/* Mancha de sinal ruim/crítico — bolinhas pequenas */}
          {showSignalLayer && signalPoints.map((p) => {
            const isCritical = p.status === "critical";
            const color = isCritical ? "#dc2626" : "#f59e0b";
            return (
              <CircleMarker key={`sig-${p.id}`}
                center={[p.lat, p.lng]}
                radius={isCritical ? 4.5 : 3.5}
                pathOptions={{
                  color: color,
                  fillColor: color,
                  fillOpacity: 0.75,
                  weight: 1,
                  opacity: 0.95,
                }}>
                <Tooltip>
                  <div style={{ fontSize: 11, lineHeight: 1.35 }}>
                    <b style={{
                      color: color, textTransform: "uppercase",
                      letterSpacing: 0.5,
                    }}>
                      {isCritical ? "🔴 CRITICAL" : "🟠 WARNING"}
                    </b>
                    <br/>
                    <span style={{ fontWeight: 700 }}>{p.name}</span>
                    {p.signal_1490 != null && (
                      <>
                        <br/>
                        <span style={{ color: "#475569" }}>
                          Rx 1490nm: <b>{p.signal_1490} dBm</b>
                        </span>
                      </>
                    )}
                    {p.olt && (
                      <>
                        <br/>
                        <span style={{ color: "#94a3b8" }}>
                          OLT: {p.olt}{p.zone ? ` · ${p.zone}` : ""}
                        </span>
                      </>
                    )}
                    {!p.online && (
                      <>
                        <br/>
                        <span style={{ color: "#dc2626", fontWeight: 700 }}>
                          ⚡ OFFLINE
                        </span>
                      </>
                    )}
                  </div>
                </Tooltip>
              </CircleMarker>
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
      {/* iter183 — Modal lateral de detalhes do cabo */}
      {activeCableDetail && (
        <CableDetailDrawer
          cable={activeCableDetail}
          vlanStats={vlanStats}
          onClose={() => setActiveCableDetail(null)}
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

function PhotoLightbox({ photos, index, ctoName, onClose,
                              // Back-compat: callers antigos podem passar
                              // {url, uploadedByName} no lugar de {photos, index}.
                              url, uploadedByName }) {
  const list = Array.isArray(photos) && photos.length > 0
    ? photos
    : (url ? [{ url, uploaded_by_name: uploadedByName }] : []);
  const [idx, setIdx] = useState(typeof index === "number" ? index : 0);
  const safeIdx = Math.min(Math.max(idx, 0), Math.max(list.length - 1, 0));
  const current = list[safeIdx] || {};
  const total = list.length;
  const hasMany = total > 1;

  // Zoom-pan state (resetado a cada troca de foto)
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef({ active: false, sx: 0, sy: 0, ox: 0, oy: 0 });
  const touchRef = useRef({ pinchDist: 0, baseZoom: 1, swipeStartX: null });

  const reset = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);
  useEffect(() => { reset(); }, [safeIdx, reset]);

  const next = useCallback(() => {
    if (hasMany) setIdx((i) => (i + 1) % total);
  }, [hasMany, total]);
  const prev = useCallback(() => {
    if (hasMany) setIdx((i) => (i - 1 + total) % total);
  }, [hasMany, total]);

  // Keyboard: Esc fecha, ← → navegam, +/- zoom, 0 reset
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowRight") { next(); return; }
      if (e.key === "ArrowLeft") { prev(); return; }
      if (e.key === "+" || e.key === "=") {
        setZoom((z) => Math.min(z + 0.25, 5));
      }
      if (e.key === "-" || e.key === "_") {
        setZoom((z) => Math.max(z - 0.25, 1));
      }
      if (e.key === "0") { reset(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, next, prev, reset]);

  // Wheel zoom — apenas sobre a imagem
  const onWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.15 : -0.15;
    setZoom((z) => {
      const nz = Math.min(Math.max(z + delta, 1), 5);
      if (nz === 1) setPan({ x: 0, y: 0 });
      return nz;
    });
  };

  // Drag pan (mouse) — só ativa quando zoom > 1
  const onMouseDown = (e) => {
    if (zoom <= 1) return;
    e.preventDefault();
    dragRef.current = {
      active: true, sx: e.clientX, sy: e.clientY,
      ox: pan.x, oy: pan.y,
    };
  };
  const onMouseMove = (e) => {
    const d = dragRef.current;
    if (!d.active) return;
    setPan({ x: d.ox + (e.clientX - d.sx), y: d.oy + (e.clientY - d.sy) });
  };
  const stopDrag = () => { dragRef.current.active = false; };

  // Touch: 1 dedo = swipe horizontal (mudar foto), 2 dedos = pinch-zoom
  const dist2 = (a, b) => {
    const dx = a.clientX - b.clientX, dy = a.clientY - b.clientY;
    return Math.sqrt(dx * dx + dy * dy);
  };
  const onTouchStart = (e) => {
    if (e.touches.length === 2) {
      touchRef.current.pinchDist = dist2(e.touches[0], e.touches[1]);
      touchRef.current.baseZoom = zoom;
      touchRef.current.swipeStartX = null;
    } else if (e.touches.length === 1 && zoom === 1) {
      touchRef.current.swipeStartX = e.touches[0].clientX;
    } else if (e.touches.length === 1 && zoom > 1) {
      // Pan single-finger no zoom in
      dragRef.current = {
        active: true,
        sx: e.touches[0].clientX, sy: e.touches[0].clientY,
        ox: pan.x, oy: pan.y,
      };
      touchRef.current.swipeStartX = null;
    }
  };
  const onTouchMove = (e) => {
    if (e.touches.length === 2 && touchRef.current.pinchDist) {
      const d = dist2(e.touches[0], e.touches[1]);
      const ratio = d / touchRef.current.pinchDist;
      const nz = Math.min(Math.max(touchRef.current.baseZoom * ratio, 1), 5);
      setZoom(nz);
      if (nz === 1) setPan({ x: 0, y: 0 });
    } else if (e.touches.length === 1 && dragRef.current.active) {
      const d = dragRef.current;
      setPan({
        x: d.ox + (e.touches[0].clientX - d.sx),
        y: d.oy + (e.touches[0].clientY - d.sy),
      });
    }
  };
  const onTouchEnd = (e) => {
    // Swipe horizontal: dispara só se foi gesto rápido E zoom=1
    if (touchRef.current.swipeStartX !== null && zoom === 1
        && e.changedTouches.length === 1) {
      const dx = e.changedTouches[0].clientX - touchRef.current.swipeStartX;
      if (Math.abs(dx) > 60) {
        if (dx < 0) next();
        else prev();
      }
    }
    dragRef.current.active = false;
    touchRef.current.pinchDist = 0;
    touchRef.current.swipeStartX = null;
  };

  if (list.length === 0) return null;

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
                      alignItems: "center", maxWidth: "100%" }}>
        {/* Header: CTO + uploader + contador */}
        <div style={{
          padding: "6px 14px", borderRadius: 999,
          background: "rgba(255,255,255,.1)", color: "white",
          fontSize: 12, fontWeight: 700,
          display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
          justifyContent: "center",
        }}>
          📸 {ctoName || "CTO"}
          {current.uploaded_by_name && (
            <span style={{ opacity: 0.7, fontWeight: 500 }}>
              · {current.uploaded_by_name}
            </span>
          )}
          {hasMany && (
            <span data-testid="lightbox-counter"
                    style={{
                      padding: "1px 8px", borderRadius: 999,
                      background: "rgba(255,255,255,.18)", fontSize: 11,
                    }}>
              {safeIdx + 1} / {total}
            </span>
          )}
          {zoom > 1 && (
            <span style={{
              padding: "1px 8px", borderRadius: 999,
              background: "rgba(16,185,129,.25)", fontSize: 11,
              color: "#a7f3d0",
            }}>
              {zoom.toFixed(1)}×
            </span>
          )}
        </div>

        {/* Imagem + setas */}
        <div style={{ position: "relative", display: "flex",
                        alignItems: "center", justifyContent: "center" }}>
          {hasMany && (
            <button data-testid="lightbox-prev"
                      aria-label="Anterior"
                      onClick={prev}
                      style={navBtn("left")}>‹</button>
          )}
          <div onWheel={onWheel}
                onMouseDown={onMouseDown}
                onMouseMove={onMouseMove}
                onMouseUp={stopDrag}
                onMouseLeave={stopDrag}
                onTouchStart={onTouchStart}
                onTouchMove={onTouchMove}
                onTouchEnd={onTouchEnd}
                style={{
                  overflow: "hidden",
                  maxWidth: "92vw", maxHeight: "78vh",
                  cursor: zoom > 1
                    ? (dragRef.current.active ? "grabbing" : "grab")
                    : "zoom-in",
                  borderRadius: 8,
                  boxShadow: "0 12px 40px rgba(0,0,0,.6)",
                  touchAction: "none",
                }}>
            <img src={current.url} alt="Foto CTO ampliada"
                  data-testid="map-lightbox-img"
                  draggable={false}
                  onDoubleClick={() => {
                    // Toggle entre 1× e 2× num clique duplo
                    setZoom((z) => (z === 1 ? 2 : 1));
                    if (zoom !== 1) setPan({ x: 0, y: 0 });
                  }}
                  style={{
                    display: "block",
                    maxWidth: "92vw", maxHeight: "78vh",
                    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                    transformOrigin: "center",
                    transition: dragRef.current.active
                      ? "none" : "transform 0.18s ease-out",
                    userSelect: "none",
                  }} />
          </div>
          {hasMany && (
            <button data-testid="lightbox-next"
                      aria-label="Próxima"
                      onClick={next}
                      style={navBtn("right")}>›</button>
          )}
        </div>

        {/* Toolbar: zoom controls + close */}
        <div style={{ display: "flex", gap: 8, alignItems: "center",
                        flexWrap: "wrap", justifyContent: "center" }}>
          <button data-testid="lightbox-zoom-out"
                    aria-label="Diminuir zoom"
                    onClick={() => setZoom((z) =>
                      Math.max(z - 0.5, 1))}
                    style={tbZoomBtn}>−</button>
          <button data-testid="lightbox-zoom-reset"
                    aria-label="Resetar zoom"
                    onClick={reset} style={tbZoomBtn}>
            {zoom > 1 ? "Reset" : "1×"}
          </button>
          <button data-testid="lightbox-zoom-in"
                    aria-label="Aumentar zoom"
                    onClick={() => setZoom((z) =>
                      Math.min(z + 0.5, 5))}
                    style={tbZoomBtn}>+</button>
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
        <div style={{ color: "rgba(255,255,255,.45)", fontSize: 10,
                        textAlign: "center", marginTop: -4 }}>
          {hasMany && "← → muda foto · "}
          scroll/+/− zoom · 0 reset · arrastar para mover
        </div>
      </div>
    </div>
  );
}

const navBtn = (side) => ({
  position: "absolute",
  [side]: -54,
  top: "50%", transform: "translateY(-50%)",
  width: 44, height: 44, borderRadius: "50%",
  border: "1px solid rgba(255,255,255,.25)",
  background: "rgba(255,255,255,.12)", color: "white",
  fontSize: 28, lineHeight: 1, cursor: "pointer", fontWeight: 700,
  display: "flex", alignItems: "center", justifyContent: "center",
});

const tbZoomBtn = {
  width: 36, height: 36, borderRadius: 8,
  border: "1px solid rgba(255,255,255,.3)",
  background: "rgba(255,255,255,.1)", color: "white",
  fontSize: 16, fontWeight: 700, cursor: "pointer",
};

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
        width: 18,
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

// ---------------------------------------------------------------------------
// KmzControls — botões Exportar e Importar KMZ
// ---------------------------------------------------------------------------
function KmzControls({ vlanFilter, onImported }) {
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef(null);

  async function handleExport() {
    if (busy) return;
    setBusy(true);
    try {
      // Em iframe do Emergent, link direto via window.open com ?t=token
      const inIframe = window.self !== window.top;
      if (inIframe) {
        const url = api.redeIaExportKmzUrl(vlanFilter || null);
        window.open(url, "_blank", "noopener,noreferrer");
        return;
      }
      // Fora de iframe: usa File System Access API se disponível
      const r = await api.redeIaExportKmz(vlanFilter || null);
      if (typeof window.showSaveFilePicker === "function") {
        try {
          const handle = await window.showSaveFilePicker({
            suggestedName: r.filename,
            types: [{ description: "Google Earth (.kmz)",
                       accept: { "application/vnd.google-earth.kmz": [".kmz"] } }],
          });
          const writable = await handle.createWritable();
          await writable.write(r.blob);
          await writable.close();
          return;
        } catch (e) {
          if (e.name === "AbortError") return;
          // Cai pro download via blob abaixo
        }
      }
      const url = window.URL.createObjectURL(r.blob);
      const a = document.createElement("a");
      a.href = url; a.download = r.filename;
      document.body.appendChild(a); a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      }, 1500);
    } catch (e) {
      window.alert("Erro ao exportar KMZ: "
        + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  }

  async function handleImport(file) {
    if (!file || busy) return;
    setBusy(true);
    try {
      // 1) Dry-run pra mostrar prévia
      const preview = await api.redeIaImportKmz(file, true);
      const total = preview.ctos_created + preview.ctos_updated
                    + preview.ces_created + preview.ces_updated
                    + preview.cables_created + preview.cables_updated;
      if (total === 0) {
        window.alert(
          `Nada importável no arquivo "${file.name}". `
          + `(ignorados: ${preview.ignored})`,
        );
        return;
      }
      const ok = window.confirm(
        `Importar de "${file.name}"?\n\n`
        + `📍 CTOs: ${preview.ctos_created} novas, ${preview.ctos_updated} atualizadas\n`
        + `◆ CEs:  ${preview.ces_created} novos, ${preview.ces_updated} atualizados\n`
        + `━ Cabos: ${preview.cables_created} novos, ${preview.cables_updated} atualizados\n`
        + (preview.ignored ? `\n⚠️ ${preview.ignored} Placemarks ignorados (sem coordenadas válidas)` : "")
        + `\n\nConfirma?`
      );
      if (!ok) return;
      // 2) Import real
      const result = await api.redeIaImportKmz(file, false);
      window.alert(
        `✅ Importação concluída!\n\n`
        + `CTOs: +${result.ctos_created}, ~${result.ctos_updated}\n`
        + `CEs:  +${result.ces_created}, ~${result.ces_updated}\n`
        + `Cabos: +${result.cables_created}, ~${result.cables_updated}`
      );
      onImported && onImported();
    } catch (e) {
      window.alert("Erro ao importar KMZ: "
        + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <>
      <button data-testid="map-export-kmz" onClick={handleExport}
              disabled={busy}
              title={vlanFilter
                ? `Exporta CTOs/CEs/Cabos da VLAN ${vlanFilter} como KMZ (Google Earth)`
                : "Exporta TODA a topologia como KMZ (Google Earth/QGIS)"}
              style={{
                padding: "6px 12px", borderRadius: 7, fontSize: 12,
                fontWeight: 700, cursor: busy ? "wait" : "pointer",
                background: "#0ea5e9", color: "#fff", border: 0,
                opacity: busy ? 0.5 : 1,
              }}>
        📥 Exportar KMZ
      </button>
      <button data-testid="map-import-kmz"
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
              title="Importa CTOs/CEs/Cabos de arquivo KMZ ou KML"
              style={{
                padding: "6px 12px", borderRadius: 7, fontSize: 12,
                fontWeight: 700, cursor: busy ? "wait" : "pointer",
                background: "#f59e0b", color: "#fff", border: 0,
                opacity: busy ? 0.5 : 1,
              }}>
        📤 Importar KMZ
      </button>
      <input
        ref={fileInputRef}
        data-testid="map-import-kmz-input"
        type="file"
        accept=".kmz,.kml,application/vnd.google-earth.kmz,application/vnd.google-earth.kml+xml"
        onChange={(e) => handleImport(e.target.files?.[0])}
        style={{ display: "none" }}
      />
    </>
  );
}


// ============================================================================
// iter183 — Drawer lateral com detalhes do cabo
// ============================================================================
function CableDetailDrawer({ cable, vlanStats, onClose }) {
  const c = cable || {};
  const occPct = c.fo_count && c.fibras_ocupadas != null
    ? Math.round((c.fibras_ocupadas / c.fo_count) * 100) : null;
  return (
    <div data-testid="cable-detail-drawer"
         style={{ position: "fixed", inset: 0, zIndex: 1000,
                    background: "rgba(15,23,42,0.4)",
                    display: "flex", justifyContent: "flex-end" }}
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: "white", width: "100%", maxWidth: 420,
                      height: "100%", padding: 20, overflowY: "auto",
                      boxShadow: "-10px 0 30px rgba(0,0,0,0.2)" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
              Detalhes do cabo
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a",
                            marginTop: 2 }}>
              {c.name || "Cabo s/ nome"}
            </div>
          </div>
          <button onClick={onClose} data-testid="cable-detail-close"
                  style={{ background: "#f1f5f9", border: 0, padding: 10,
                             borderRadius: 8, cursor: "pointer",
                             fontSize: 16, fontWeight: 800 }}>
            ✕
          </button>
        </div>

        {/* iter186 — Vincular ponta solta */}
        {c._loose_end && (
          <div style={{ padding: 14, background: "#fff7ed",
                            border: "1px solid #fed7aa",
                            borderRadius: 12, marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: "#9a3412",
                              marginBottom: 6, textTransform: "uppercase",
                              letterSpacing: 0.5 }}>
              🧵 Ponta solta — {c._loose_end === "from" ? "Origem" : "Destino"}
            </div>
            <div style={{ fontSize: 12, color: "#7c2d12", marginBottom: 10,
                              lineHeight: 1.45 }}>
              GPS: {c._loose_lat?.toFixed(5)}, {c._loose_lng?.toFixed(5)}
              <br />Clique numa ação:
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button data-testid="loose-link-existing"
                          onClick={() => {
                            onClose();
                            window.dispatchEvent(new CustomEvent(
                              "rede-ia-navigate",
                              { detail: { tab: "orphan_cables" } },
                            ));
                          }}
                          style={{ flex: 1, padding: "10px 12px",
                                       borderRadius: 8, border: "1px solid #ea580c",
                                       background: "#fff", color: "#9a3412",
                                       fontWeight: 700, fontSize: 12,
                                       cursor: "pointer" }}>
                🔗 Ir para Cabos Órfãos
              </button>
              <button data-testid="loose-cadastrar-aqui"
                          onClick={() => {
                            const u = new URL(window.location.href);
                            u.searchParams.set("cadastrar_aqui",
                              `${c._loose_lat},${c._loose_lng}`);
                            window.location.href = u.toString();
                          }}
                          style={{ flex: 1, padding: "10px 12px",
                                       borderRadius: 8, border: "1px solid #ea580c",
                                       background: "#ea580c", color: "#fff",
                                       fontWeight: 700, fontSize: 12,
                                       cursor: "pointer" }}>
                + Cadastrar CTO aqui
              </button>
            </div>
          </div>
        )}

        {/* Card principal */}
        <div style={{ padding: 14, background: "#f8fafc",
                        borderRadius: 12, marginBottom: 14 }}>
          <Row label="FO (fibras)"   value={c.fo_count ? `${c.fo_count} FO` : "—"} />
          <Row label="Marca"          value={c.cable_brand || "—"} />
          <Row label="Nº de série"   value={c.cable_serial || "—"} mono />
          <Row label="Tipo"            value={(c.cable_type_logical || c.cable_type || "—").toString().toUpperCase()} />
          <Row label="VLAN"            value={c.vlan ? `VLAN ${c.vlan}` : "—"} />
        </div>

        {/* Métricas de comprimento */}
        <div style={{ padding: 14, background: "linear-gradient(135deg,#0d9488,#06b6d4)",
                        color: "#fff", borderRadius: 12, marginBottom: 14 }}>
          <div style={{ fontSize: 10, opacity: 0.85, textTransform: "uppercase",
                          letterSpacing: 0.5, fontWeight: 700, marginBottom: 6 }}>
            📏 Comprimento deste cabo
          </div>
          <div style={{ fontSize: 28, fontWeight: 900 }}>
            {c.total_length_m
              ? `${Math.round(c.total_length_m)} m`
              : c.length_m ? `${Math.round(c.length_m)} m` : "—"}
          </div>
          {c.route_distance_m && (
            <div style={{ fontSize: 11, marginTop: 4, opacity: 0.9 }}>
              {Math.round(c.route_distance_m)}m trajeto + {c.extra_margin_m || 20}m sobra
            </div>
          )}
        </div>

        {/* Ocupação */}
        {occPct != null && (
          <div style={{ padding: 14, background: "#fef3c7",
                          borderRadius: 12, marginBottom: 14,
                          border: "1px solid #fde68a" }}>
            <div style={{ fontSize: 10, color: "#92400e", fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 4 }}>
              Ocupação de fibras
            </div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#78350f" }}>
              {c.fibras_ocupadas} / {c.fo_count} ({occPct}%)
            </div>
            <div style={{ height: 6, background: "#fef9c3", borderRadius: 3,
                            marginTop: 8, overflow: "hidden" }}>
              <div style={{ width: `${occPct}%`, height: "100%",
                              background: occPct > 80 ? "#dc2626"
                                : occPct > 60 ? "#f59e0b" : "#16a34a" }} />
            </div>
          </div>
        )}

        {/* Stats da VLAN */}
        {vlanStats && (
          <div style={{ padding: 14, background: "#f0f9ff",
                          borderRadius: 12, marginBottom: 14,
                          border: "1px solid #bae6fd" }}>
            <div style={{ fontSize: 10, color: "#0369a1", fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 6 }}>
              📡 VLAN {vlanStats.vlan} — totais
            </div>
            <Row label="Total de cabo"
                 value={`${Math.round(vlanStats.total_cable_m || 0).toLocaleString("pt-BR")} m`} />
            <Row label="Cabos"      value={vlanStats.cables_count} />
            <Row label="CTOs"       value={vlanStats.ctos_count} />
            <Row label="CEs"        value={vlanStats.ces_count} />
            <Row label="Portas"
                 value={`${vlanStats.ports_used}/${vlanStats.ports_total} (${vlanStats.occupancy_pct}%)`} />
          </div>
        )}

        {/* Origem / Destino */}
        <div style={{ padding: 14, background: "#fafafa",
                        border: "1px dashed #e2e8f0",
                        borderRadius: 12, marginBottom: 14 }}>
          <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                          textTransform: "uppercase", letterSpacing: 0.5,
                          marginBottom: 6 }}>
            Origem → Destino
          </div>
          <div style={{ fontSize: 13, color: "#0f172a", lineHeight: 1.6 }}>
            <strong>{c.from_element_name || c.from_element_id || "Ponto livre"}</strong>
            <br />↓<br />
            <strong>{c.to_element_name || c.to_element_id || "Ponto livre"}</strong>
          </div>
        </div>

        {c.created_by && (
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 16,
                          paddingTop: 12, borderTop: "1px solid #e2e8f0" }}>
            Lançado por <strong>{c.created_by}</strong>
            {c.created_at && (
              <> em {new Date(c.created_at).toLocaleString("pt-BR")}</>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, mono = false }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                    padding: "5px 0", fontSize: 13,
                    borderBottom: "1px solid rgba(0,0,0,0.04)" }}>
      <span style={{ color: "#64748b" }}>{label}</span>
      <span style={{ color: "#0f172a", fontWeight: 700,
                       fontFamily: mono ? "monospace" : "inherit" }}>
        {value}
      </span>
    </div>
  );
}
