/**
 * LousaServicesMap — Modal de mapa com pinos de serviços (bolhas),
 * coloridos por técnico atribuído.
 *
 * - Filtros: período (hoje/ontem/7d/30d/custom) + status (open/closed/all)
 * - Pinos: divIcon com cor única por collaborator_id (paleta de 12)
 * - Cluster: agrupa pinos próximos (leaflet.markercluster)
 * - Legenda: lateral, clicável (toggle visibilidade do técnico)
 * - Popup: cliente, horário, tipo, status, endereço + link "Abrir bolha"
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer, TileLayer, Marker, Popup, Polyline, useMap,
  CircleMarker, Tooltip,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/api";
import { fmtAddress } from "@/utils/format";

// Fix ícone default Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

const PERIODS = [
  { id: "today", label: "Hoje" },
  { id: "yesterday", label: "Ontem" },
  { id: "7d", label: "7 dias" },
  { id: "30d", label: "30 dias" },
];

const STATUSES = [
  { id: "all", label: "Todos", color: "#475569" },
  { id: "open", label: "Em aberto", color: "#ea580c" },
  { id: "closed", label: "Finalizados", color: "#16a34a" },
];

// Converte hex (#rrggbb) → {h, s, l} (HSL)
function hexToHsl(hex) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let H = 0, S = 0; const L = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    S = L > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: H = (g - b) / d + (g < b ? 6 : 0); break;
      case g: H = (b - r) / d + 2; break;
      default: H = (r - g) / d + 4;
    }
    H *= 60;
  }
  return { h: H, s: S * 100, l: L * 100 };
}

function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3,
                                                  Math.min(9 - k(n), 1)));
  const toHex = (x) => {
    const v = Math.round(x * 255);
    return v.toString(16).padStart(2, "0");
  };
  return `#${toHex(f(0))}${toHex(f(8))}${toHex(f(4))}`;
}

// Ajusta a cor base do técnico de acordo com o status da nota:
//  - em_execucao  → cor original (saturada, vibrante)
//  - pendente/agendada → mesma cor, mais clara (lightness +18)
//  - executada/finalizada → muito clara (lightness +30, sat -30)
//  - cancelada    → cinza esmaecido
function statusTinted(baseHex, status) {
  if (status === "cancelada") return "#cbd5e1";
  const hsl = hexToHsl(baseHex);
  if (status === "em_execucao") {
    // Reforça saturação pra dar destaque
    return hslToHex(hsl.h, Math.min(100, hsl.s + 5), hsl.l);
  }
  if (status === "executada" || status === "finalizada") {
    return hslToHex(hsl.h,
                    Math.max(15, hsl.s - 25),
                    Math.min(85, hsl.l + 25));
  }
  // pendente, agendada, default → mais claro/translúcido
  return hslToHex(hsl.h,
                  Math.max(20, hsl.s - 15),
                  Math.min(80, hsl.l + 18));
}

// Tamanho do pino: em execução é maior + tem anel pulsante
function pinScale(status) {
  if (status === "em_execucao") return 1.15;
  if (status === "executada" || status === "finalizada") return 0.85;
  return 1.0;
}

// Paleta de saúde da CTO (mesmo do Mapa Interativo)
const CTO_HEALTH_COLORS = {
  ok: { fill: "#16a34a", border: "#14532d" },
  warning: { fill: "#ca8a04", border: "#713f12" },
  critical: { fill: "#dc2626", border: "#7f1d1d" },
  no_data: { fill: "#94a3b8", border: "#475569" },
  unknown: { fill: "#94a3b8", border: "#475569" },
};

function makeCtoIcon(cto) {
  const status = cto?.health?.status || "unknown";
  const c = CTO_HEALTH_COLORS[status] || CTO_HEALTH_COLORS.no_data;
  const used = cto.used_ports || 0;
  const total = cto.capacity || 0;
  const pct = total ? Math.round((used / total) * 100) : 0;
  return L.divIcon({
    className: "cto-marker-lousa",
    html: `<div style="
      position:relative;width:30px;height:30px;border-radius:7px;
      background:${c.fill};border:2px solid ${c.border};
      box-shadow:0 2px 5px rgba(0,0,0,0.35);
      display:grid;place-items:center;color:#fff;font-weight:800;
      font-size:10px;font-family:system-ui;">
      ▦
      <span style="position:absolute;bottom:-5px;right:-5px;
        background:#fff;color:${c.border};font-size:8px;font-weight:800;
        border:1.5px solid ${c.border};border-radius:99px;
        padding:0px 4px;line-height:1.2;">${pct}%</span>
    </div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    popupAnchor: [0, -16],
  });
}

// Cabos: cores e larguras por tipo (mesmo do Mapa Interativo)
const CABLE_COLORS = {
  drop: "#94a3b8",
  "6fo": "#facc15",
  "12fo": "#fb923c",
  "24fo": "#ef4444",
  "48fo": "#8b5cf6",
  "96fo": "#0f172a",
};
const CABLE_WIDTHS = {
  drop: 1.5, "6fo": 2.5, "12fo": 3.5, "24fo": 4.5, "48fo": 5.5, "96fo": 6.5,
};

function makeCeIcon() {
  return L.divIcon({
    className: "ce-marker-lousa",
    html: `<div style="
      width:24px;height:24px;
      transform:rotate(45deg);background:#2563eb;
      border:2px solid #1e40af;
      box-shadow:0 2px 5px rgba(0,0,0,0.3);
      display:grid;place-items:center;">
      <span style="transform:rotate(-45deg);color:#fff;
                    font-weight:800;font-size:10px;">CE</span>
    </div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -10],
  });
}

// Haversine: distância em km entre 2 coords
function haversineKm(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2
            + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2))
              * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// Caminho do cabo (segments OU ponto-a-ponto se vazio)
function buildCablePath(cab, ctosById, cesById) {
  if (cab.segments && cab.segments.length >= 2) {
    return cab.segments.map((s) => [s.lat, s.lng]);
  }
  const from = cab.from_type === "ce" ? cesById.get(cab.from_id)
                                       : ctosById.get(cab.from_id);
  const to = cab.to_type === "ce" ? cesById.get(cab.to_id)
                                   : ctosById.get(cab.to_id);
  if (!from || !to) return null;
  return [[from.lat, from.lng], [to.lat, to.lng]];
}

// Constrói ícone com cor + iniciais + tonalidade por status
function makePinIcon(baseColor, initials, status) {
  const fill = statusTinted(baseColor, status);
  const isRunning = status === "em_execucao";
  const isDone = status === "executada" || status === "finalizada";
  const scale = pinScale(status);
  const w = Math.round(34 * scale);
  const h = Math.round(42 * scale);
  const strokeColor = isRunning ? "#fff" : (isDone ? "#cbd5e1" : "#e2e8f0");
  const strokeWidth = isRunning ? 2.5 : 1.5;
  const pulse = isRunning
    ? `<circle cx="17" cy="17" r="15" fill="${baseColor}"
               opacity=".25">
         <animate attributeName="r" from="12" to="20" dur="1.4s"
                  repeatCount="indefinite"/>
         <animate attributeName="opacity" from=".5" to="0" dur="1.4s"
                  repeatCount="indefinite"/>
       </circle>`
    : "";
  const checkmark = isDone
    ? `<text x="17" y="22" text-anchor="middle"
             font-size="14" font-weight="900" fill="${baseColor}"
             font-family="system-ui">✓</text>`
    : `<text x="17" y="22" text-anchor="middle"
             font-size="11" font-weight="800" fill="${baseColor}"
             font-family="system-ui" letter-spacing="-.5">${initials}</text>`;
  return L.divIcon({
    className: "lousa-pin",
    html: `<div style="
      position:relative;width:${w}px;height:${h}px;
      display:grid;place-items:center;
      filter:drop-shadow(0 2px 4px rgba(0,0,0,.35));
    ">
      <svg width="${w}" height="${h}" viewBox="0 0 34 42"
           style="overflow:visible">
        ${pulse}
        <path d="M17 0 C7.6 0 0 7.6 0 17 C0 28 17 42 17 42 C17 42 34 28 34 17 C34 7.6 26.4 0 17 0 Z"
              fill="${fill}" stroke="${strokeColor}"
              stroke-width="${strokeWidth}"/>
        <circle cx="17" cy="17" r="10" fill="#fff"/>
        ${checkmark}
      </svg>
    </div>`,
    iconSize: [w, h],
    iconAnchor: [Math.round(w / 2), h],
    popupAnchor: [0, -(h - 4)],
  });
}

function initialsFrom(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Recentraliza o mapa quando os pinos mudam
function MapAutoFit({ pins }) {
  const map = useMap();
  useEffect(() => {
    if (!pins || pins.length === 0) return;
    const bounds = L.latLngBounds(pins.map((p) => [p.lat, p.lng]));
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    }
  }, [pins, map]);
  return null;
}

// Centraliza o mapa quando o usuário escolhe um resultado de busca
function MapFlyTo({ target }) {
  const map = useMap();
  useEffect(() => {
    if (target && target.lat != null && target.lng != null) {
      map.flyTo([target.lat, target.lng], 17, { duration: 1.2 });
    }
  }, [target, map]);
  return null;
}

// Marcador azul vibrante pra resultado de pesquisa (chamativo, pulsa)
function makeSearchPinIcon() {
  return L.divIcon({
    className: "search-pin",
    html: `<div style="
      position:relative;width:42px;height:52px;
      display:grid;place-items:center;
      filter:drop-shadow(0 3px 6px rgba(0,0,0,.45));
    ">
      <svg width="42" height="52" viewBox="0 0 34 42" style="overflow:visible">
        <circle cx="17" cy="17" r="16" fill="#0ea5e9" opacity=".35">
          <animate attributeName="r" from="14" to="22" dur="1.2s"
                   repeatCount="indefinite"/>
          <animate attributeName="opacity" from=".6" to="0" dur="1.2s"
                   repeatCount="indefinite"/>
        </circle>
        <path d="M17 0 C7.6 0 0 7.6 0 17 C0 28 17 42 17 42 C17 42 34 28 34 17 C34 7.6 26.4 0 17 0 Z"
              fill="#0ea5e9" stroke="#fff" stroke-width="3"/>
        <circle cx="17" cy="17" r="6" fill="#fff"/>
        <text x="17" y="21" text-anchor="middle"
              font-size="11" font-weight="900" fill="#0ea5e9"
              font-family="system-ui">🔍</text>
      </svg>
    </div>`,
    iconSize: [42, 52],
    iconAnchor: [21, 52],
    popupAnchor: [0, -48],
  });
}

export default function LousaServicesMap({ onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [period, setPeriod] = useState("today");
  const [statusFilter, setStatusFilter] = useState("all");
  const [hiddenCollabs, setHiddenCollabs] = useState(() => new Set());
  const [geocodingNow, setGeocodingNow] = useState(false);
  // Topologia do Mapa Interativo (clonada)
  const [ctos, setCtos] = useState([]);
  const [ces, setCes] = useState([]);
  const [cables, setCables] = useState([]);
  const [showCtos, setShowCtos] = useState(true);
  const [showLinkToCto, setShowLinkToCto] = useState(true);

  // Mancha de sinal ruim (warning) / crítico — toggles separados
  const [showSignalWarning, setShowSignalWarning] = useState(false);
  const [showSignalCritical, setShowSignalCritical] = useState(false);
  const [signalPoints, setSignalPoints] = useState([]);
  const [signalStats, setSignalStats] = useState(null);
  const [signalLoading, setSignalLoading] = useState(false);

  // Pesquisa de endereço
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchPin, setSearchPin] = useState(null); // { lat, lng, label }
  const searchTimerRef = useRef(null);

  async function load(p = period, s = statusFilter) {
    setLoading(true);
    setErr(null);
    try {
      const [r, mapData] = await Promise.all([
        api.lousaMapServices({ period: p, status: s, geocode_max: 30 }),
        api.redeIaMapData().catch(() => ({ ctos: [], ces: [], cables: [] })),
      ]);
      setData(r);
      setCtos((mapData?.ctos || []).filter(
        (c) => c.lat != null && c.lng != null));
      setCes((mapData?.ces || []).filter(
        (c) => c.lat != null && c.lng != null));
      setCables(mapData?.cables || []);
    } catch (e) {
      const det = e?.response?.data?.detail;
      setErr(typeof det === "string" ? det : (det?.message || e.message));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); /* eslint-disable-line */ }, []);

  // Carrega pontos de sinal ruim/crítico quando algum dos toggles for ativado
  useEffect(() => {
    if (!showSignalWarning && !showSignalCritical) return;
    if (signalPoints.length > 0) return; // já tem cache em memória
    let cancelled = false;
    (async () => {
      setSignalLoading(true);
      try {
        const r = await api.redeIaSignalPoints("all", 0);
        if (cancelled) return;
        setSignalPoints(r.points || []);
        setSignalStats(r.stats || null);
      } catch (e) {
        console.warn("[lousa-signal-layer] err:", e);
      } finally {
        if (!cancelled) setSignalLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [showSignalWarning, showSignalCritical, signalPoints.length]);

  async function geocodeSignalBatchLousa() {
    if (signalLoading) return;
    setSignalLoading(true);
    try {
      const r = await api.redeIaSignalGeocodeBatch(40);
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

  const toggleCollab = (id) => {
    setHiddenCollabs((prev) => {
      const next = new Set(prev);
      const key = id || "_unassigned";
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const allShown = hiddenCollabs.size === 0;
  const toggleAll = () => {
    if (allShown) {
      // hide all
      setHiddenCollabs(new Set(
        (data?.legend || []).map((l) => l.collaborator_id || "_unassigned")
      ));
    } else {
      setHiddenCollabs(new Set());
    }
  };

  const visiblePins = useMemo(() => {
    if (!data?.pins) return [];
    const filtered = data.pins.filter((p) => {
      const key = p.collaborator_id || "_unassigned";
      return !hiddenCollabs.has(key);
    });
    // Jitter: separa visualmente pinos exatamente no mesmo endereço (lat/lng)
    // — Atlaz costuma ter múltiplas bolhas pro mesmo cliente.
    const seen = new Map();
    return filtered.map((p) => {
      const key = `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`;
      const n = seen.get(key) || 0;
      seen.set(key, n + 1);
      if (n === 0) return p;
      // Espiral pequena (~10m por anel)
      const angle = (n * 137.5) * Math.PI / 180;
      const radius = 0.00012 * Math.ceil(n / 5);
      return {
        ...p,
        lat: p.lat + radius * Math.cos(angle),
        lng: p.lng + radius * Math.sin(angle),
      };
    });
  }, [data, hiddenCollabs]);

  // Maps por id pra montar paths de cabos
  const ctosById = useMemo(() => {
    const m = new Map();
    ctos.forEach((c) => m.set(c.id, c));
    return m;
  }, [ctos]);
  const cesById = useMemo(() => {
    const m = new Map();
    ces.forEach((c) => m.set(c.id, c));
    return m;
  }, [ces]);

  // Pra cada pino visível, acha a CTO mais próxima (≤ 2km de raio)
  // — usado pra desenhar linha tracejada serviço → CTO atendendo.
  const pinToCto = useMemo(() => {
    if (!showLinkToCto || ctos.length === 0) return [];
    const links = [];
    for (const p of visiblePins) {
      let best = null;
      let bestKm = Infinity;
      for (const c of ctos) {
        const km = haversineKm(p.lat, p.lng, c.lat, c.lng);
        if (km < bestKm) { bestKm = km; best = c; }
      }
      if (best && bestKm <= 2.0) {
        links.push({ pin: p, cto: best, km: bestKm });
      }
    }
    return links;
  }, [visiblePins, ctos, showLinkToCto]);

  async function turbinaGeocode() {
    if (geocodingNow) return;
    setGeocodingNow(true);
    try {
      const r = await api.lousaMapGeocodeNow(60);
      window.alert(
        `Geocodificou ${r.geocoded} de ${r.processed} tickets. `
        + `${r.remaining_estimate} ainda pendentes — vão sendo processados em background.`,
      );
      await load();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setGeocodingNow(false);
    }
  }

  // Pesquisa de endereço: debounce 400ms
  function handleSearchChange(value) {
    setSearchQ(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!value || value.trim().length < 3) {
      setSearchResults([]);
      return;
    }
    searchTimerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await api.searchAddress(value.trim());
        setSearchResults(r.results || []);
      } catch (e) {
        console.warn("[search-address] err:", e);
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 400);
  }

  function pickSearchResult(it) {
    setSearchPin({ lat: it.lat, lng: it.lng, label: it.label,
                    full: it.full });
    setSearchResults([]);
    setSearchQ(it.label);
  }

  function clearSearch() {
    setSearchQ("");
    setSearchResults([]);
    setSearchPin(null);
  }

  return (
    <div data-testid="lousa-map-modal"
         style={{ position: "fixed", inset: 0,
                   background: "rgba(15,23,42,.7)", zIndex: 9000,
                   display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                     padding: "10px 16px", background: "#fff",
                     borderBottom: "1px solid #e2e8f0" }}>
        <span style={{ fontSize: 18, fontWeight: 800, color: "#0f172a" }}>
          🗺️ Mapa de Serviços
        </span>
        <span style={{ fontSize: 12, color: "#64748b" }}>
          {data?.stats
            ? <>
                {data.stats.with_coords} de {data.stats.total_tickets} no mapa
                {data.stats.without_coords > 0 && (
                  <> · {data.stats.without_coords} sem coords (em geocoding…)</>
                )}
              </>
            : "Carregando…"}
        </span>

        {/* Filtro período */}
        <div style={{ display: "flex", gap: 4, marginLeft: 20 }}>
          {PERIODS.map((p) => (
            <button key={p.id}
                    data-testid={`map-period-${p.id}`}
                    onClick={() => { setPeriod(p.id); load(p.id, statusFilter); }}
                    style={{
                      padding: "5px 10px", borderRadius: 6, fontSize: 12,
                      fontWeight: 700, cursor: "pointer",
                      border: `1.5px solid ${period === p.id ? "#0f172a" : "#e2e8f0"}`,
                      background: period === p.id ? "#0f172a" : "#fff",
                      color: period === p.id ? "#fff" : "#0f172a",
                    }}>
              {p.label}
            </button>
          ))}
        </div>

        {/* Filtro status */}
        <div style={{ display: "flex", gap: 4 }}>
          {STATUSES.map((s) => (
            <button key={s.id}
                    data-testid={`map-status-${s.id}`}
                    onClick={() => { setStatusFilter(s.id); load(period, s.id); }}
                    style={{
                      padding: "5px 10px", borderRadius: 6, fontSize: 12,
                      fontWeight: 700, cursor: "pointer",
                      border: `1.5px solid ${statusFilter === s.id ? s.color : "#e2e8f0"}`,
                      background: statusFilter === s.id ? s.color : "#fff",
                      color: statusFilter === s.id ? "#fff" : s.color,
                    }}>
              {s.label}
            </button>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        {/* Toggle CTOs + Cabos + CEs */}
        {(ctos.length > 0 || ces.length > 0) && (
          <label data-testid="map-toggle-ctos"
                 style={{ display: "flex", alignItems: "center", gap: 6,
                           fontSize: 12, color: "#0f172a", cursor: "pointer",
                           padding: "5px 10px",
                           background: showCtos ? "#dcfce7" : "#f1f5f9",
                           border: `1.5px solid ${
                             showCtos ? "#16a34a" : "#e2e8f0"}`,
                           borderRadius: 6, fontWeight: 700 }}>
            <input type="checkbox" checked={showCtos}
                   onChange={(e) => setShowCtos(e.target.checked)}
                   style={{ accentColor: "#16a34a" }} />
            ▦ Rede ({ctos.length}c · {ces.length}ce · {cables.length}cab)
          </label>
        )}

        {/* Toggle linha tracejada serviço → CTO */}
        {ctos.length > 0 && pinToCto.length > 0 && (
          <label data-testid="map-toggle-linkcto"
                 style={{ display: "flex", alignItems: "center", gap: 6,
                           fontSize: 12, color: "#0f172a", cursor: "pointer",
                           padding: "5px 10px",
                           background: showLinkToCto ? "#fef3c7" : "#f1f5f9",
                           border: `1.5px solid ${
                             showLinkToCto ? "#f59e0b" : "#e2e8f0"}`,
                           borderRadius: 6, fontWeight: 700 }}>
            <input type="checkbox" checked={showLinkToCto}
                   onChange={(e) => setShowLinkToCto(e.target.checked)}
                   style={{ accentColor: "#f59e0b" }} />
            ⤧ Vínculo CTO ({pinToCto.length})
          </label>
        )}

        {/* Toggle Mancha SINAL RUIM (warning - laranja) */}
        <button data-testid="map-toggle-signal-warning"
                onClick={() => setShowSignalWarning((v) => !v)}
                title="Mostra mancha de clientes com sinal RUIM (warning) no mapa"
                style={{
                  padding: "5px 10px", borderRadius: 6, fontSize: 12,
                  fontWeight: 700, cursor: "pointer",
                  background: showSignalWarning ? "#f59e0b" : "#fff",
                  color: showSignalWarning ? "#fff" : "#b45309",
                  border: `1.5px solid #f59e0b`,
                  display: "inline-flex", alignItems: "center", gap: 6,
                }}>
          <span style={{
            width: 9, height: 9, borderRadius: 99,
            background: showSignalWarning ? "#fff" : "#f59e0b",
            display: "inline-block",
          }} />
          {signalLoading
            ? "Carregando…"
            : (showSignalWarning && signalStats
                ? `Sinal Ruim (${signalStats.warning})`
                : "Sinal Ruim")}
        </button>

        {/* Toggle Mancha SINAL CRÍTICO (critical - vermelho) */}
        <button data-testid="map-toggle-signal-critical"
                onClick={() => setShowSignalCritical((v) => !v)}
                title="Mostra mancha de clientes com sinal CRÍTICO no mapa"
                style={{
                  padding: "5px 10px", borderRadius: 6, fontSize: 12,
                  fontWeight: 700, cursor: "pointer",
                  background: showSignalCritical ? "#dc2626" : "#fff",
                  color: showSignalCritical ? "#fff" : "#991b1b",
                  border: `1.5px solid #dc2626`,
                  display: "inline-flex", alignItems: "center", gap: 6,
                }}>
          <span style={{
            width: 9, height: 9, borderRadius: 99,
            background: showSignalCritical ? "#fff" : "#dc2626",
            display: "inline-block",
          }} />
          {signalLoading
            ? "Carregando…"
            : (showSignalCritical && signalStats
                ? `Crítico (${signalStats.critical})`
                : "Crítico")}
        </button>

        {/* Botão geocodificar mais ONUs sem coords (aparece se houver toggle ativo) */}
        {(showSignalWarning || showSignalCritical)
          && signalStats?.without_coords > 0 && (
          <button data-testid="map-signal-geocode-more"
                  onClick={geocodeSignalBatchLousa}
                  disabled={signalLoading}
                  title="Geocodifica mais 40 ONUs sem coords (~40s)"
                  style={{
                    padding: "5px 10px", borderRadius: 6, fontSize: 11,
                    fontWeight: 700,
                    cursor: signalLoading ? "wait" : "pointer",
                    background: "#0ea5e9", color: "#fff", border: 0,
                    opacity: signalLoading ? 0.5 : 1,
                  }}>
            ⚡ +40 ({signalStats.without_coords})
          </button>
        )}

        {data?.stats?.without_coords > 0 && (
          <button data-testid="map-geocode-now-btn"
                  onClick={turbinaGeocode}
                  disabled={geocodingNow}
                  style={{
                    padding: "6px 12px", borderRadius: 7, fontSize: 12,
                    fontWeight: 700, cursor: "pointer", background: "#0ea5e9",
                    color: "#fff", border: 0,
                  }}>
            {geocodingNow ? "⏳ Geocodificando 60 (~1min)…"
                          : "⚡ Geocodificar próximos 60"}
          </button>
        )}

        <button data-testid="map-close-btn" onClick={onClose}
                style={{ padding: "6px 14px", borderRadius: 7,
                          background: "#dc2626", color: "#fff", border: 0,
                          fontWeight: 700, cursor: "pointer" }}>
          Fechar
        </button>
      </div>

      {/* Barra de pesquisa de endereço (segunda linha do header) */}
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                     padding: "8px 16px", background: "#f8fafc",
                     borderBottom: "1px solid #e2e8f0",
                     position: "relative" }}>
        <span style={{ fontSize: 13, color: "#475569", fontWeight: 600 }}>
          🔍 Pesquisar endereço:
        </span>
        <div style={{ flex: 1, maxWidth: 520, position: "relative" }}>
          <input
            data-testid="map-search-input"
            type="text"
            value={searchQ}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Digite rua, bairro ou cidade (mínimo 3 letras)…"
            style={{
              width: "100%", padding: "7px 32px 7px 12px",
              borderRadius: 7, border: "1.5px solid #cbd5e1",
              fontSize: 13, outline: "none",
              background: "#fff",
            }}
          />
          {searchQ && (
            <button data-testid="map-search-clear"
                    onClick={clearSearch}
                    title="Limpar busca"
                    style={{ position: "absolute", right: 6, top: "50%",
                              transform: "translateY(-50%)",
                              background: "transparent", border: 0,
                              color: "#94a3b8", cursor: "pointer",
                              fontSize: 16, padding: "0 4px" }}>
              ×
            </button>
          )}
          {/* Dropdown de resultados */}
          {(searchResults.length > 0 || searching) && (
            <div data-testid="map-search-results"
                 style={{ position: "absolute", top: "100%", left: 0,
                           right: 0, marginTop: 4,
                           background: "#fff",
                           border: "1px solid #cbd5e1",
                           borderRadius: 8,
                           boxShadow: "0 10px 25px rgba(15,23,42,.15)",
                           maxHeight: 320, overflow: "auto",
                           zIndex: 1000 }}>
              {searching && (
                <div style={{ padding: "12px 14px", color: "#64748b",
                               fontSize: 12 }}>
                  ⏳ Pesquisando…
                </div>
              )}
              {!searching && searchResults.length === 0 && searchQ.length >= 3 && (
                <div style={{ padding: "12px 14px", color: "#64748b",
                               fontSize: 12 }}>
                  Nenhum endereço encontrado.
                </div>
              )}
              {!searching && searchResults.map((it, idx) => (
                <button key={`${it.lat}-${it.lng}-${idx}`}
                        data-testid={`map-search-result-${idx}`}
                        onClick={() => pickSearchResult(it)}
                        style={{ display: "block", width: "100%",
                                  textAlign: "left",
                                  padding: "10px 14px",
                                  background: "transparent", border: 0,
                                  borderBottom: idx < searchResults.length - 1
                                    ? "1px solid #f1f5f9" : 0,
                                  cursor: "pointer", fontSize: 13 }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "#f1f5f9";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "transparent";
                        }}>
                  <div style={{ fontWeight: 700, color: "#0f172a" }}>
                    📍 {it.label}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b",
                                 marginTop: 2 }}>
                    {it.neighborhood
                      ? `${it.neighborhood} · ` : ""}
                    {it.city}{it.state ? ` · ${it.state}` : ""}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        {searchPin && (
          <button data-testid="map-search-clear-pin"
                  onClick={() => setSearchPin(null)}
                  style={{ padding: "5px 10px", borderRadius: 6,
                            background: "#fef2f2", color: "#991b1b",
                            border: "1px solid #fecaca", fontSize: 11,
                            fontWeight: 700, cursor: "pointer" }}>
            ✕ Remover pino de pesquisa
          </button>
        )}
      </div>

      {/* Body: legend + map */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Legend lateral */}
        <div style={{
          width: 240, background: "#f8fafc",
          borderRight: "1px solid #e2e8f0", overflow: "auto",
          padding: 12, fontSize: 12,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                         alignItems: "center", marginBottom: 8 }}>
            <span style={{ fontWeight: 800, color: "#0f172a" }}>
              👥 Técnicos
            </span>
            <button onClick={toggleAll} data-testid="map-toggle-all-collabs"
                    style={{ fontSize: 10, color: "#0369a1",
                              background: "transparent", border: 0,
                              cursor: "pointer", textDecoration: "underline" }}>
              {allShown ? "Ocultar todos" : "Mostrar todos"}
            </button>
          </div>
          {!data || (data.legend || []).length === 0 ? (
            <div style={{ color: "#94a3b8", fontSize: 11 }}>
              Sem serviços no período selecionado.
            </div>
          ) : (
            <>
              {(data.legend || []).map((l) => {
                const key = l.collaborator_id || "_unassigned";
                const hidden = hiddenCollabs.has(key);
                return (
                  <button key={key}
                          data-testid={`map-legend-${key}`}
                          onClick={() => toggleCollab(l.collaborator_id)}
                          style={{
                            display: "flex", alignItems: "center", gap: 8,
                            width: "100%", padding: "8px 10px",
                            marginBottom: 4, borderRadius: 7,
                            border: `1px solid ${hidden ? "#e2e8f0" : l.color}`,
                            background: hidden ? "#f1f5f9" : "#fff",
                            cursor: "pointer", textAlign: "left",
                            opacity: hidden ? 0.6 : 1,
                            transition: "all .15s",
                          }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: 4,
                      background: l.color, color: "#fff", fontSize: 10,
                      fontWeight: 800, display: "grid",
                      placeItems: "center",
                    }}>
                      {initialsFrom(l.collaborator_name)}
                    </span>
                    <span style={{
                      flex: 1, fontSize: 12, fontWeight: 600,
                      color: "#0f172a",
                      textDecoration: hidden ? "line-through" : "none",
                    }}>
                      {l.collaborator_name}
                    </span>
                    <span style={{
                      fontSize: 11, fontWeight: 700, color: "#475569",
                      background: "#f1f5f9", padding: "2px 7px",
                      borderRadius: 99,
                    }}>
                      {l.count}
                    </span>
                  </button>
                );
              })}
              {/* Legenda de status do pino */}
              <div style={{ marginTop: 16, padding: "10px 12px",
                             background: "#fff",
                             border: "1px solid #e2e8f0",
                             borderRadius: 7, fontSize: 11 }}>
                <div style={{ fontWeight: 800, color: "#0f172a",
                               marginBottom: 6 }}>
                  🎨 Tonalidade do pino
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center",
                               marginBottom: 4 }}>
                  <span style={{ width: 12, height: 12, borderRadius: 3,
                                  background: "#e6194b" }} />
                  <span style={{ color: "#0f172a", fontWeight: 600 }}>
                    Em execução
                  </span>
                  <span style={{ color: "#94a3b8", fontSize: 10 }}>
                    (cor forte + pulsa)
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center",
                               marginBottom: 4 }}>
                  <span style={{ width: 12, height: 12, borderRadius: 3,
                                  background: "#f4a4b7" }} />
                  <span style={{ color: "#0f172a", fontWeight: 600 }}>
                    Pendente / agendada
                  </span>
                  <span style={{ color: "#94a3b8", fontSize: 10 }}>
                    (claro)
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <span style={{ width: 12, height: 12, borderRadius: 3,
                                  background: "#f8d4dd" }} />
                  <span style={{ color: "#0f172a", fontWeight: 600 }}>
                    Finalizada
                  </span>
                  <span style={{ color: "#94a3b8", fontSize: 10 }}>
                    (✓ pálido)
                  </span>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Mapa */}
        <div style={{ flex: 1, position: "relative" }}>
          {loading && (
            <div data-testid="map-loading"
                 style={{ position: "absolute", inset: 0, zIndex: 500,
                           background: "rgba(248,250,252,.85)",
                           display: "grid", placeItems: "center",
                           fontSize: 14, color: "#475569" }}>
              ⏳ Carregando serviços… (geocoding sob demanda — até 30s)
            </div>
          )}
          {err && (
            <div data-testid="map-error"
                 style={{ position: "absolute", inset: 0, zIndex: 500,
                           background: "#fef2f2",
                           display: "grid", placeItems: "center",
                           padding: 40, color: "#7f1d1d", fontSize: 13 }}>
              ❌ {err}
            </div>
          )}
          {data && (
            <MapContainer
              center={[data.center.lat, data.center.lng]}
              zoom={12}
              style={{ height: "100%", width: "100%" }}
              data-testid="map-container">
              <TileLayer
                attribution='&copy; OpenStreetMap'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <MapAutoFit pins={visiblePins} />
              <MapFlyTo target={searchPin} />
              {/* Pino azul de pesquisa */}
              {searchPin && (
                <Marker position={[searchPin.lat, searchPin.lng]}
                        icon={makeSearchPinIcon()}
                        zIndexOffset={1000}>
                  <Popup>
                    <div style={{ minWidth: 220, fontSize: 12 }}>
                      <div style={{
                        padding: "4px 8px", margin: "-8px -8px 8px",
                        background: "#0ea5e9", color: "#fff",
                        fontWeight: 700, borderRadius: "5px 5px 0 0",
                      }}>
                        🔍 Resultado da pesquisa
                      </div>
                      <div style={{ fontWeight: 700, color: "#0f172a",
                                     marginBottom: 4 }}>
                        {searchPin.label}
                      </div>
                      {searchPin.full && (
                        <div style={{ fontSize: 11, color: "#475569" }}>
                          {searchPin.full}
                        </div>
                      )}
                      <div style={{ marginTop: 8, fontSize: 11,
                                     color: "#94a3b8" }}>
                        📍 {searchPin.lat.toFixed(5)}, {searchPin.lng.toFixed(5)}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              )}
              {/* Cabos do Mapa Interativo (sob CTOs/CEs) */}
              {showCtos && cables.map((cab) => {
                const path = buildCablePath(cab, ctosById, cesById);
                if (!path) return null;
                return (
                  <Polyline key={`cab-${cab.id}`} positions={path}
                    pathOptions={{
                      color: CABLE_COLORS[cab.type] || "#64748b",
                      weight: CABLE_WIDTHS[cab.type] || 3,
                      opacity: 0.7,
                      dashArray: cab.type === "drop" ? "6 6" : null,
                    }}>
                    <Popup>
                      <div style={{ minWidth: 180, fontSize: 12 }}>
                        <div style={{ fontWeight: 800, marginBottom: 4 }}>
                          Cabo {(cab.type || "?").toUpperCase()}
                        </div>
                        <div style={{ fontSize: 11, color: "#64748b" }}>
                          {cab.fo_count} fibras
                          {cab.length_m && ` · ${Math.round(cab.length_m)}m`}
                        </div>
                      </div>
                    </Popup>
                  </Polyline>
                );
              })}
              {/* CEs (concentradores) */}
              {showCtos && ces.map((ce) => (
                <Marker key={`ce-${ce.id}`}
                        position={[ce.lat, ce.lng]}
                        icon={makeCeIcon()}
                        zIndexOffset={-90}>
                  <Popup>
                    <div style={{ minWidth: 180, fontSize: 12 }}>
                      <div style={{ fontWeight: 800, marginBottom: 4,
                                     color: "#1e40af" }}>
                        ◆ CE {ce.name || ce.sigla}
                      </div>
                      {ce.address && (
                        <div style={{ color: "#475569", fontSize: 11 }}>
                          📍 {fmtAddress(ce.address)}
                        </div>
                      )}
                    </div>
                  </Popup>
                </Marker>
              ))}
              {/* Linha tracejada: cada serviço → CTO mais próxima (≤2km) */}
              {showLinkToCto && pinToCto.map((link) => (
                <Polyline key={`link-${link.pin.id}`}
                  positions={[[link.pin.lat, link.pin.lng],
                              [link.cto.lat, link.cto.lng]]}
                  pathOptions={{
                    color: link.pin.color,
                    weight: 1.5,
                    opacity: 0.55,
                    dashArray: "3 6",
                  }} />
              ))}
              {/* CTOs do Mapa Interativo — mesmo visual */}
              {showCtos && ctos.map((c) => (
                <Marker key={`cto-${c.id}`}
                        position={[c.lat, c.lng]}
                        icon={makeCtoIcon(c)}
                        zIndexOffset={-100}>
                  <Popup>
                    <div data-testid={`map-cto-popup-${c.id}`}
                         style={{ minWidth: 200, fontSize: 12 }}>
                      <div style={{
                        padding: "4px 8px", margin: "-8px -8px 8px",
                        background: (CTO_HEALTH_COLORS[c.health?.status]
                          || CTO_HEALTH_COLORS.no_data).fill,
                        color: "#fff", fontWeight: 700,
                        borderRadius: "5px 5px 0 0",
                      }}>
                        ▦ CTO {c.sigla || c.name}
                      </div>
                      <div style={{ marginBottom: 4 }}>
                        <b style={{ fontSize: 13, color: "#0f172a" }}>
                          {c.name}
                        </b>
                      </div>
                      {c.address && (
                        <div style={{ color: "#475569", marginBottom: 4,
                                       fontSize: 11 }}>
                          📍 {fmtAddress(c.address)}
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 6,
                                     fontSize: 11, flexWrap: "wrap" }}>
                        {c.vlan && (
                          <span style={{
                            background: "#dbeafe", color: "#1e3a8a",
                            padding: "2px 6px", borderRadius: 5,
                            fontWeight: 700,
                          }}>VLAN {c.vlan}</span>
                        )}
                        <span style={{
                          background: "#f1f5f9", color: "#0f172a",
                          padding: "2px 6px", borderRadius: 5,
                        }}>
                          {c.used_ports}/{c.capacity} portas
                        </span>
                        <span style={{
                          background: (CTO_HEALTH_COLORS[c.health?.status]
                            || CTO_HEALTH_COLORS.no_data).fill,
                          color: "#fff",
                          padding: "2px 6px", borderRadius: 5,
                          fontWeight: 700, textTransform: "uppercase",
                        }}>
                          {c.health?.status || "no_data"}
                        </span>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}
              {/* Mancha de SINAL — bolinhas pequenas (warning/critical) */}
              {(showSignalWarning || showSignalCritical)
                && signalPoints
                .filter((p) => {
                  if (p.status === "warning") return showSignalWarning;
                  if (p.status === "critical") return showSignalCritical;
                  return false;
                })
                .map((p) => {
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
              {visiblePins.map((p) => (
                <Marker key={p.id}
                        position={[p.lat, p.lng]}
                        icon={makePinIcon(p.color,
                                          initialsFrom(p.collaborator_name),
                                          p.status)}>
                  <Popup>
                    <div data-testid={`map-pin-popup-${p.id}`}
                         style={{ minWidth: 220, fontSize: 12,
                                   fontFamily: "system-ui" }}>
                      <div style={{
                        padding: "4px 8px", margin: "-8px -8px 8px",
                        background: p.color, color: "#fff",
                        fontWeight: 700, borderRadius: "5px 5px 0 0",
                      }}>
                        {initialsFrom(p.collaborator_name)} ·
                        {" "}{p.collaborator_name}
                      </div>
                      <div style={{ marginBottom: 4 }}>
                        <b style={{ color: "#0f172a", fontSize: 13 }}>
                          {p.client_name}
                        </b>
                      </div>
                      <div style={{ color: "#475569", marginBottom: 6 }}>
                        📍 {fmtAddress(p.address)}{p.neighborhood
                          ? ` · ${p.neighborhood}` : ""}
                      </div>
                      <div style={{ display: "flex", gap: 6,
                                     fontSize: 11, marginBottom: 6,
                                     flexWrap: "wrap" }}>
                        <span style={{
                          background: "#f1f5f9", padding: "2px 6px",
                          borderRadius: 5,
                        }}>
                          {p.type}
                        </span>
                        <span style={{
                          background: statusColor(p.status).bg,
                          color: statusColor(p.status).fg,
                          padding: "2px 6px", borderRadius: 5,
                          fontWeight: 700,
                        }}>
                          {p.status}
                        </span>
                        {p.atlaz_protocolo && (
                          <span style={{
                            background: "#fef3c7", color: "#713f12",
                            padding: "2px 6px", borderRadius: 5,
                          }}>
                            #{p.atlaz_protocolo}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: "#64748b" }}>
                        ⏰ {p.scheduled_time
                          ? new Date(p.scheduled_time).toLocaleString("pt-BR")
                          : "—"}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          )}
        </div>
      </div>
    </div>
  );
}

function statusColor(s) {
  if (s === "pendente" || s === "agendada")
    return { bg: "#fef3c7", fg: "#713f12" };
  if (s === "em_execucao")
    return { bg: "#dbeafe", fg: "#1e3a8a" };
  if (s === "executada" || s === "finalizada")
    return { bg: "#dcfce7", fg: "#14532d" };
  if (s === "cancelada")
    return { bg: "#fee2e2", fg: "#7f1d1d" };
  return { bg: "#f1f5f9", fg: "#0f172a" };
}
