/* =============================================================
   CadastroCTOWizard — Wizard mobile-first com 3 fluxos:

   • CTO (7 passos): tipo → mapa (+ bairro inline) → capacidade →
       tipo rede → splitter (condicional) → nº caixa → resumo
       (VLAN inferida do bairro — não pedimos ao técnico)
   • CE  (4 passos): tipo → mapa (+ bairro inline) → bandejas →
       tipo instalação + foto interna → resumo
       (VLAN também inferida do bairro — sem step de VLAN)
   • CABO (5 passos): tipo → origem (CTO/CE) → destino → fibras +
       tipo cabo + foto plaqueta → resumo

   Alinhado às melhores práticas FOA + Atlas GIS Mobile + BWN Fiber:
   listas fechadas (chips/cards), foto obrigatória, GPS automático,
   poucos campos por tela, touch target ≥ 48px.
============================================================= */
import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  MapContainer, TileLayer, Marker, Tooltip, Polyline, CircleMarker,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/api";
import CTOMapPicker from "@/CTOMapPicker";
import outbox from "@/utils/offlineQueue";
import { getBestPosition } from "@/utils/geo";
import { stampFieldPhoto } from "@/utils/photoStamp";

// Paleta sóbria/corporate — slate/indigo
const C_BG = "#f8fafc";
const C_HEADER_BG = "#0f172a";
const C_PRIMARY = "#1e293b";
const C_PRIMARY_LIGHT = "#f1f5f9";
const C_ACCENT = "#0f766e";
const C_TEXT = "#0f172a";
const C_MUTED = "#64748b";
const C_BORDER = "#e2e8f0";
const C_DANGER = "#b91c1c";

const headerStyle = {
  background: C_HEADER_BG, color: "#fff", padding: "14px 16px",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontWeight: 600, fontSize: 15, letterSpacing: 0.2,
  position: "sticky", top: 0, zIndex: 10,
  borderBottom: "1px solid rgba(255,255,255,0.06)",
};
const stepBadge = {
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  width: 24, height: 24, borderRadius: 6,
  background: "rgba(255,255,255,0.12)", color: "#fff",
  fontSize: 12, fontWeight: 700, marginRight: 10,
  fontVariantNumeric: "tabular-nums",
};
const cardBase = {
  background: "#fff", borderRadius: 10, border: `1px solid ${C_BORDER}`,
  padding: "14px 14px", marginBottom: 10,
};
const inputBase = {
  width: "100%", padding: "12px 13px", borderRadius: 8,
  border: `1px solid ${C_BORDER}`, fontSize: 14, color: C_TEXT,
  background: "#fff", outline: "none", boxSizing: "border-box",
  fontFamily: "inherit",
};
const labelStyle = {
  fontSize: 11, fontWeight: 700, color: C_MUTED,
  marginBottom: 5, marginTop: 12, display: "block",
  textTransform: "uppercase", letterSpacing: 0.6,
};
const primaryBtn = {
  width: "100%", padding: "13px 20px", borderRadius: 8,
  background: C_PRIMARY, color: "#fff", border: 0,
  fontWeight: 600, fontSize: 14, cursor: "pointer",
  letterSpacing: 0.2,
  boxShadow: "0 1px 2px rgba(15,23,42,0.15)",
};
const accentBtn = {
  ...primaryBtn,
  background: C_ACCENT,
  boxShadow: "0 1px 2px rgba(15,118,110,0.25)",
};
const optionCard = (selected) => ({
  padding: "14px 14px", borderRadius: 10,
  border: `1.5px solid ${selected ? C_PRIMARY : C_BORDER}`,
  background: selected ? C_PRIMARY_LIGHT : "#fff",
  cursor: "pointer", textAlign: "left",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontSize: 14, fontWeight: 500, color: C_TEXT,
  marginBottom: 8,
  transition: "background-color .15s, border-color .15s",
});
const checkBox = (selected) => ({
  width: 20, height: 20, borderRadius: 5,
  border: `1.5px solid ${selected ? C_PRIMARY : "#cbd5e1"}`,
  background: selected ? C_PRIMARY : "#fff",
  color: "#fff", fontSize: 12, fontWeight: 700,
  display: "grid", placeItems: "center", flexShrink: 0,
});
const chip = (selected) => ({
  padding: "10px 14px", borderRadius: 999,
  border: `1.5px solid ${selected ? C_PRIMARY : C_BORDER}`,
  background: selected ? C_PRIMARY : "#fff",
  color: selected ? "#fff" : C_TEXT,
  fontSize: 13, fontWeight: 700, cursor: "pointer",
  letterSpacing: 0.2,
});

function TypeCard({ icon, iconUrl, color, bg, title, subtitle, description, onClick, testid }) {
  return (
    <button
      type="button" data-testid={testid} onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: 16, borderRadius: 14,
        border: `1.5px solid ${C_BORDER}`, background: "#fff",
        cursor: "pointer", textAlign: "left", width: "100%",
        transition: "transform 120ms, border-color 120ms",
        WebkitTapHighlightColor: "transparent",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = color; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = C_BORDER; }}>
      <div style={{
        width: 56, height: 56, borderRadius: 14, background: bg,
        display: "grid", placeItems: "center", fontSize: 28, flexShrink: 0,
        overflow: "hidden",
      }}>
        {iconUrl ? (
          <img src={iconUrl} alt={title}
               style={{ width: "100%", height: "100%", objectFit: "contain",
                          padding: 4, display: "block" }} />
        ) : icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontSize: 18, fontWeight: 800, color, lineHeight: 1.1 }}>
            {title}
          </span>
          <span style={{ fontSize: 11, color: C_MUTED, fontWeight: 600 }}>
            {subtitle}
          </span>
        </div>
        <div style={{ fontSize: 11.5, color: C_MUTED, marginTop: 4,
                          lineHeight: 1.45 }}>
          {description}
        </div>
      </div>
      <div style={{ color: color, fontSize: 20, fontWeight: 800,
                       flexShrink: 0 }}>→</div>
    </button>
  );
}

// =============================================================
// ElementMapPicker — mapa Uber-like para escolher Origem/Destino do CABO
// iter186: substitui a lista por um mapa com pinos coloridos
//   • Azul   = CTO
//   • Roxo   = CE
//   • Verde  = Selecionado
//   • Cinza  = Origem (no step Destino, apenas referência, não clicável)
// Centra no GPS atual do técnico. Linha tracejada origem→destino candidato.
// =============================================================
function pinSvg(fill, stroke = "#fff") {
  return `
    <svg width="30" height="40" viewBox="0 0 42 56" xmlns="http://www.w3.org/2000/svg">
      <path d="M21 0 C9.4 0 0 9.4 0 21 c0 15.2 17 31.5 19.4 33.7
               a2.2 2.2 0 0 0 3.2 0 C25 52.5 42 36.2 42 21 42 9.4 32.6 0 21 0 Z"
            fill="${fill}" stroke="${stroke}" stroke-width="1.8"/>
      <circle cx="21" cy="21" r="8" fill="#fff"/>
    </svg>`;
}
const ICON_CTO = L.divIcon({
  className: "el-pick-cto", html: pinSvg("#0ea5e9"),
  iconSize: [30, 40], iconAnchor: [15, 40], popupAnchor: [0, -34],
});
const ICON_CE = L.divIcon({
  className: "el-pick-ce", html: pinSvg("#7c3aed"),
  iconSize: [30, 40], iconAnchor: [15, 40], popupAnchor: [0, -34],
});
const ICON_SEL = L.divIcon({
  className: "el-pick-sel", html: pinSvg("#10b981", "#064e3b"),
  iconSize: [36, 48], iconAnchor: [18, 48], popupAnchor: [0, -40],
});
const ICON_ORIGIN = L.divIcon({
  className: "el-pick-origin", html: pinSvg("#64748b"),
  iconSize: [30, 40], iconAnchor: [15, 40], popupAnchor: [0, -34],
});

// iter187 — Ícone pequeno e arrastável para os waypoints intermediários do
// trajeto OSRM (estilo Google Maps). Bola branca com borda verde.
const ICON_WAYPOINT = L.divIcon({
  className: "cable-waypoint", iconSize: [16, 16], iconAnchor: [8, 8],
  html: `
    <div style="width:16px;height:16px;border-radius:50%;
                  background:#fff;border:3px solid #0d9488;
                  box-shadow:0 1px 4px rgba(0,0,0,0.4);"></div>`,
});

function ElementMapPicker({
  items, loading, selected, onPick, originItem = null,
  excludeId = null, testid,
}) {
  const [center, setCenter] = useState(null);
  const [gpsFix, setGpsFix] = useState(null);
  const [gpsErr, setGpsErr] = useState("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState("mapa"); // "mapa" | "lista" fallback

  useEffect(() => {
    getBestPosition({ cutoffM: 50, timeoutMs: 8000 })
      .then((fix) => {
        setGpsFix({ lat: fix.lat, lng: fix.lng });
        setCenter({ lat: fix.lat, lng: fix.lng });
      })
      .catch(() => {
        setGpsErr("GPS indisponível — centrando na rede.");
        const first = (items || []).find(
          (x) => x?.gps?.lat != null && x?.gps?.lng != null,
        );
        if (first) {
          setCenter({ lat: first.gps.lat, lng: first.gps.lng });
        } else {
          setCenter({ lat: -9.6498, lng: -35.7089 });
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Recentra ao carregar items se ainda não temos GPS válido
  useEffect(() => {
    if (center || !items || items.length === 0) return;
    const first = items.find(
      (x) => x?.gps?.lat != null && x?.gps?.lng != null,
    );
    if (first) setCenter({ lat: first.gps.lat, lng: first.gps.lng });
  }, [items, center]);

  const pickable = useMemo(() => {
    return (items || []).filter((it) => {
      const t = (it.element_type || "cto").toLowerCase();
      if (t === "cabo") return false; // cabos não são pontos de origem/destino
      if (it.id === excludeId) return false;
      const st = (it.status || "").toLowerCase();
      if (st.startsWith("reject") || st.startsWith("cancel")) return false;
      return true;
    });
  }, [items, excludeId]);

  const onMap = useMemo(
    () => pickable.filter((it) => it?.gps?.lat != null && it?.gps?.lng != null),
    [pickable],
  );
  const offMap = useMemo(
    () => pickable.filter((it) => !(it?.gps?.lat != null && it?.gps?.lng != null)),
    [pickable],
  );

  const q = (search || "").trim().toLowerCase();
  const matchSearch = (it) => {
    if (!q) return true;
    return (
      (it.name || "").toLowerCase().includes(q)
      || (it.sigla || "").toLowerCase().includes(q)
      || String(it.vlan || "").includes(q)
      || ((it.address || {}).bairro || "").toLowerCase().includes(q)
    );
  };
  const onMapFiltered = onMap.filter(matchSearch);
  const offMapFiltered = offMap.filter(matchSearch);

  // Recentra mapa quando usuário busca e há 1 match — focar nele
  useEffect(() => {
    if (!q) return;
    if (onMapFiltered.length === 1) {
      const it = onMapFiltered[0];
      setCenter({ lat: it.gps.lat, lng: it.gps.lng });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, onMapFiltered.length]);

  if (loading) {
    return (
      <div data-testid={testid}
              style={{ padding: 24, textAlign: "center", color: C_MUTED }}>
        Carregando elementos da rede...
      </div>
    );
  }
  if (pickable.length === 0) {
    return (
      <div data-testid={testid}
              style={{ padding: 18, textAlign: "center", color: C_MUTED,
                       background: "#fff", borderRadius: 10,
                       border: `1px dashed ${C_BORDER}` }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>
          Nenhum elemento disponível
        </div>
        <div style={{ fontSize: 11.5 }}>
          Cadastre primeiro uma CTO ou CE para depois ligá-las com um cabo.
        </div>
      </div>
    );
  }

  return (
    <div data-testid={testid}>
      {/* Barra superior: busca + toggle de visualização */}
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input
          data-testid={`${testid}-search`}
          style={{ ...inputBase, fontSize: 14, flex: 1 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar por nome, bairro, VLAN..."
        />
        <button data-testid={`${testid}-toggle`}
                  type="button"
                  onClick={() => setView(view === "mapa" ? "lista" : "mapa")}
                  style={{
                    padding: "0 12px", border: `1px solid ${C_BORDER}`,
                    background: "#fff", borderRadius: 10, fontSize: 13,
                    fontWeight: 700, color: C_TEXT, cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}>
          {view === "mapa" ? "Lista" : "Mapa"}
        </button>
      </div>

      {view === "mapa" && (
        <>
          {!center && (
            <div style={{ padding: 32, textAlign: "center", color: C_MUTED,
                            background: "#fff", borderRadius: 12,
                            border: `1px solid ${C_BORDER}` }}>
              Obtendo sua localização...
            </div>
          )}
          {center && (
            <div style={{ height: "55vh", borderRadius: 12,
                            overflow: "hidden",
                            border: `1px solid ${C_BORDER}` }}>
              <MapContainer
                center={[center.lat, center.lng]}
                zoom={16}
                style={{ height: "100%", width: "100%" }}
                key={`${center.lat.toFixed(4)}-${center.lng.toFixed(4)}`}
              >
                <TileLayer
                  url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
                  attribution='© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                />

                {/* Posição GPS do técnico */}
                {gpsFix && (
                  <CircleMarker
                    center={[gpsFix.lat, gpsFix.lng]}
                    radius={7}
                    pathOptions={{
                      color: "#fff", weight: 2,
                      fillColor: "#3b82f6", fillOpacity: 0.9,
                    }}
                  />
                )}

                {/* Pino da Origem (referência, não clicável) */}
                {originItem?.gps?.lat != null && (
                  <Marker
                    position={[originItem.gps.lat, originItem.gps.lng]}
                    icon={ICON_ORIGIN}
                    interactive={false}
                  >
                    <Tooltip direction="top" offset={[0, -32]} permanent>
                      <strong>{originItem.name}</strong> (Origem)
                    </Tooltip>
                  </Marker>
                )}

                {/* Pinos clicáveis */}
                {onMapFiltered.map((it) => {
                  const isSel = selected?.id === it.id;
                  const isCe = (it.element_type || "cto").toLowerCase() === "ce";
                  const icon = isSel ? ICON_SEL : (isCe ? ICON_CE : ICON_CTO);
                  return (
                    <Marker
                      key={it.id}
                      position={[it.gps.lat, it.gps.lng]}
                      icon={icon}
                      eventHandlers={{ click: () => onPick(it) }}
                    >
                      <Tooltip direction="top" offset={[0, -34]}>
                        <strong>{it.name}</strong>
                        <br />
                        {((it.address || {}).bairro) || "—"}
                        {" · VLAN "}{it.vlan || "—"}
                      </Tooltip>
                    </Marker>
                  );
                })}

                {/* Linha tracejada Origem → Destino candidato */}
                {originItem?.gps?.lat != null
                    && selected?.gps?.lat != null
                    && originItem.id !== selected.id && (
                  <Polyline
                    positions={[
                      [originItem.gps.lat, originItem.gps.lng],
                      [selected.gps.lat, selected.gps.lng],
                    ]}
                    pathOptions={{
                      color: "#10b981", weight: 3, dashArray: "8,6",
                    }}
                  />
                )}
              </MapContainer>
            </div>
          )}

          {/* Legenda */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                          fontSize: 11, color: C_MUTED, marginTop: 8 }}>
            <LegendDot color="#0ea5e9" label="CTO" />
            <LegendDot color="#7c3aed" label="CE" />
            {originItem && <LegendDot color="#64748b" label="Origem" />}
            <LegendDot color="#10b981" label="Selecionado" />
          </div>
          {offMap.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#92400e" }}>
              {offMap.length} elemento(s) sem GPS — toque em
              {" "}<button type="button"
                                onClick={() => setView("lista")}
                                style={{
                                  background: "none", border: "none",
                                  color: "#0f766e", textDecoration: "underline",
                                  cursor: "pointer", padding: 0, fontWeight: 700,
                                }}>Lista</button>{" "}
              para vê-los.
            </div>
          )}
        </>
      )}

      {view === "lista" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8,
                          maxHeight: "55vh", overflowY: "auto",
                          paddingRight: 2 }}>
          {[...onMapFiltered, ...offMapFiltered].length === 0 && (
            <div style={{ padding: 16, textAlign: "center", color: C_MUTED }}>
              Nenhum elemento corresponde à busca.
            </div>
          )}
          {[...onMapFiltered, ...offMapFiltered].map((it) => {
            const sel = selected?.id === it.id;
            const elemT = (it.element_type || "cto").toLowerCase();
            const elemBg = elemT === "ce" ? "#ede9fe" : "#e0f2fe";
            const elemColor = elemT === "ce" ? "#7c3aed" : "#0ea5e9";
            const noGps = !(it?.gps?.lat != null && it?.gps?.lng != null);
            return (
              <button key={it.id}
                         data-testid={`${testid}-item-${it.id}`}
                         onClick={() => onPick(it)}
                         style={{
                           ...optionCard(sel), padding: 12,
                           alignItems: "flex-start",
                         }}>
                <span style={{ display: "flex", gap: 10, alignItems: "center",
                                  flex: 1, minWidth: 0 }}>
                  <span style={{
                    width: 38, height: 38, borderRadius: 8,
                    background: elemBg, color: elemColor,
                    display: "grid", placeItems: "center",
                    fontSize: 12, fontWeight: 800, flexShrink: 0,
                  }}>{elemT.toUpperCase().slice(0, 4)}</span>
                  <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                    <div style={{ fontSize: 14, fontWeight: 700,
                                     color: C_TEXT, lineHeight: 1.2,
                                     display: "flex", alignItems: "center",
                                     gap: 6, flexWrap: "wrap" }}>
                      {it.name}
                      {noGps && (
                        <span style={{
                          fontSize: 9, fontWeight: 800, padding: "2px 5px",
                          borderRadius: 4, background: "#fef3c7",
                          color: "#92400e", letterSpacing: 0.5,
                          textTransform: "uppercase",
                        }}>sem GPS</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: C_MUTED, marginTop: 3 }}>
                      {(it.address || {}).bairro || "—"}
                      {" · "}VLAN {it.vlan || "—"}
                      {" · "}{it.sigla || "—"}
                    </div>
                  </span>
                </span>
                <span style={checkBox(sel)}>{sel ? "✓" : ""}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Cartão de confirmação na parte inferior */}
      {selected && (
        <div style={{ marginTop: 12, padding: 12,
                        background: "#ecfdf5", borderRadius: 10,
                        border: "1px solid #10b981",
                        display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            width: 32, height: 32, borderRadius: 8, background: "#10b981",
            color: "#fff", display: "grid", placeItems: "center",
            fontSize: 14, fontWeight: 800, flexShrink: 0,
          }}>✓</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 800, color: "#064e3b" }}>
              {selected.name}
            </div>
            <div style={{ fontSize: 11, color: "#065f46", marginTop: 2 }}>
              {(selected.address || {}).bairro || "—"}
              {" · VLAN "}{selected.vlan || "—"}
              {" · "}{selected.sigla || "—"}
            </div>
          </div>
        </div>
      )}

      {gpsErr && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#92400e" }}>
          {gpsErr}
        </div>
      )}
    </div>
  );
}

function LegendDot({ color, label }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 10, height: 10, borderRadius: "50%",
                          background: color, border: "1.5px solid #fff",
                          boxShadow: "0 0 0 1px " + color }} />
      {label}
    </span>
  );
}

// =============================================================
// OrphanLinkSuggestionCard — Sugere vincular cabos órfãos próximos
// ao GPS desta CTO/CE recém-cadastrada. Aparece no resumo (step 8/CE).
// =============================================================
function OrphanLinkSuggestionCard({ items, checked, onToggle }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{
      marginTop: 14, padding: 14, borderRadius: 12,
      background: "#fff7ed", border: "1px solid #fdba74",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: "#9a3412" }}>
          {items.length} cabo(s) órfão(s) próximo(s)
        </div>
        <label style={{ display: "inline-flex", alignItems: "center",
                            gap: 6, fontSize: 12, color: "#7c2d12",
                            fontWeight: 700, cursor: "pointer" }}>
          <input type="checkbox"
                    data-testid="orphan-link-toggle"
                    checked={checked}
                    onChange={(e) => onToggle(e.target.checked)} />
          Vincular automaticamente
        </label>
      </div>
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column",
                       gap: 4 }}>
        {items.slice(0, 5).map((it, i) => (
          <div key={`${it.cable_id}-${it.end}-${i}`} style={{
            fontSize: 12, color: "#7c2d12",
          }}>
            • <strong>{it.cable_name}</strong>
            {" "}({it.end === "from " ? "Origem" : "Destino"}, {it.distance_m}m)
          </div>
        ))}
        {items.length > 5 && (
          <div style={{ fontSize: 11, color: "#9a3412", marginTop: 2 }}>
            ... e mais {items.length - 5}
          </div>
        )}
      </div>
    </div>
  );
}


// iter188 — Sub-componente do MapContainer que escuta mousedown/touchstart
// na polyline do trajeto, cria waypoint sob o cursor e mantém ele "colado"
// no cursor até o mouseup (drag direto, estilo Google Maps).
function LineDragController({ active, polylinePoints, onDragStart,
                                onDragMove, onDragEnd }) {
  const map = useMap();
  const dragStateRef = useRef({ dragging: false, idx: null });

  useEffect(() => {
    if (!active || polylinePoints.length < 2) return undefined;

    // 1) Captura mousedown/touchstart na polyline SVG.
    //    Leaflet desenha polylines como <path> dentro do pane "overlayPane".
    const overlay = map.getPane("overlayPane");
    if (!overlay) return undefined;

    const onPointerDown = (ev) => {
      // Só age se o alvo for um <path> com a classe da nossa linha
      const target = ev.target;
      if (!(target && target.closest
              && target.closest(".track-polyline-clickable"))) {
        return;
      }
      ev.preventDefault();
      ev.stopPropagation();
      // Posição no mapa
      const point = map.mouseEventToLatLng(ev.touches ? ev.touches[0] : ev);
      // Cria waypoint nessa posição
      const newIdx = onDragStart(point.lat, point.lng);
      if (newIdx == null) return;
      dragStateRef.current = { dragging: true, idx: newIdx };
      // Desabilita drag do mapa durante o gesto
      map.dragging.disable();
      // Captura globalmente
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
      document.addEventListener("touchmove", onMove, { passive: false });
      document.addEventListener("touchend", onUp);
    };

    const onMove = (ev) => {
      if (!dragStateRef.current.dragging) return;
      ev.preventDefault();
      const e = ev.touches ? ev.touches[0] : ev;
      const ll = map.mouseEventToLatLng(e);
      onDragMove(dragStateRef.current.idx, ll.lat, ll.lng);
    };

    const onUp = () => {
      if (!dragStateRef.current.dragging) return;
      const finalIdx = dragStateRef.current.idx;
      dragStateRef.current = { dragging: false, idx: null };
      map.dragging.enable();
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
      onDragEnd(finalIdx);
    };

    overlay.addEventListener("mousedown", onPointerDown);
    overlay.addEventListener("touchstart", onPointerDown, { passive: false });
    return () => {
      overlay.removeEventListener("mousedown", onPointerDown);
      overlay.removeEventListener("touchstart", onPointerDown);
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
      // Garante mapa drag reabilitado se desmontar no meio do gesto
      try { map.dragging.enable(); } catch (e) { /* noop */ }
    };
  }, [active, polylinePoints.length, map, onDragStart, onDragMove, onDragEnd]);

  return null;
}

// =============================================================
// CableTrackRecorder — Step "Trajeto" do cabo
// iter186: técnico grava o caminho REAL andando (GPS) OU desenha
//   waypoints manualmente no mapa. Calcula comprimento ao vivo.
// Props:
//   originItem: CTO/CE de origem (com .gps)
//   destItem:   CTO/CE de destino (com .gps)
//   slackCfg:   { slack_start_m, slack_end_m, gps_min_distance_m,
//                 gps_interval_seconds }
//   value:      { points: [[lat,lng],...], distance_m, mode } | null
//   onChange:   (nextValue) => void
// =============================================================

function CableTrackRecorder({
  originItem, destItem, slackCfg, value, onChange, collabId = null,
}) {
  const [mode, setMode] = useState(value?.mode || "auto"); // "auto" | "gps" | "manual"
  const [recording, setRecording] = useState(false);
  const [points, setPoints] = useState(value?.points || []);
  const [error, setError] = useState("");
  const [gpsFix, setGpsFix] = useState(null);
  // iter186 — modo "auto": técnico só marca início e fim, OSRM completa o
  // trajeto pelas ruas.
  const [autoStart, setAutoStart] = useState(value?.autoStart || null);
  const [autoEnd, setAutoEnd] = useState(value?.autoEnd || null);
  const [autoRouting, setAutoRouting] = useState(false);
  // iter187 — Waypoints arrastáveis estilo Google Maps. Cada item é [lat,lng]
  // Usuário clica na linha para criar; arrasta o marker para mover; clique
  // duplo no marker para remover.
  const [waypoints, setWaypoints] = useState(value?.waypoints || []);
  const watchIdRef = useRef(null);
  const lastSampleRef = useRef({ ts: 0, lat: null, lng: null });
  // iter188 — Drag direto na linha (Google Maps puxa-borracha)
  const dragRef = useRef({ active: false, idx: null });
  const waypointsRef = useRef(waypoints);
  useEffect(() => { waypointsRef.current = waypoints; }, [waypoints]);

  const minDist = Number(slackCfg?.gps_min_distance_m) || 5;
  const minInterval = (Number(slackCfg?.gps_interval_seconds) || 3) * 1000;
  const slackStart = Number(slackCfg?.slack_start_m) || 10;
  const slackEnd = Number(slackCfg?.slack_end_m) || 10;

  const oLat = originItem?.gps?.lat;
  const oLng = originItem?.gps?.lng;
  const dLat = destItem?.gps?.lat;
  const dLng = destItem?.gps?.lng;

  // Distância haversine simples
  const hav = useCallback((aLat, aLng, bLat, bLng) => {
    const R = 6371000;
    const toRad = (x) => x * Math.PI / 180;
    const dLatR = toRad(bLat - aLat);
    const dLngR = toRad(bLng - aLng);
    const la1 = toRad(aLat); const la2 = toRad(bLat);
    const a = Math.sin(dLatR / 2) ** 2
        + Math.cos(la1) * Math.cos(la2) * Math.sin(dLngR / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }, []);

  const polylineLen = useCallback((pts) => {
    if (!pts || pts.length < 2) return 0;
    let total = 0;
    for (let i = 1; i < pts.length; i += 1) {
      total += hav(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]);
    }
    return total;
  }, [hav]);

  // Emite valor pro parent sempre que pontos mudam
  useEffect(() => {
    const dist = polylineLen(points);
    if (points.length === 0) {
      onChange?.(null);
    } else {
      onChange?.({
        points,
        distance_m: Math.round(dist),
        mode,
        autoStart, autoEnd, waypoints,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, mode, autoStart, autoEnd, waypoints]);

  // Inicia/para gravação GPS
  const startGps = () => {
    setError("");
    if (!("geolocation" in navigator)) {
      setError("GPS indisponível neste dispositivo.");
      return;
    }
    setRecording(true);
    // Se ainda não há pontos e temos origem, semeia com a origem
    if (points.length === 0 && oLat != null && oLng != null) {
      setPoints([[oLat, oLng]]);
    }
    watchIdRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        setGpsFix({ lat: latitude, lng: longitude, accuracy });
        const now = Date.now();
        const last = lastSampleRef.current;
        if (last.ts && now - last.ts < minInterval) return;
        if (last.lat != null) {
          const d = hav(last.lat, last.lng, latitude, longitude);
          if (d < minDist) return;
        }
        lastSampleRef.current = { ts: now, lat: latitude, lng: longitude };
        setPoints((prev) => [...prev, [latitude, longitude]]);
      },
      (err) => setError(`Falha GPS: ${err.message || err.code}`),
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 },
    );
  };

  const stopGps = () => {
    setRecording(false);
    if (watchIdRef.current != null) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    // Cravar destino no final
    if (dLat != null && dLng != null) {
      setPoints((prev) => {
        const last = prev[prev.length - 1];
        if (last && hav(last[0], last[1], dLat, dLng) < 2) return prev;
        return [...prev, [dLat, dLng]];
      });
    }
  };

  // cleanup
  useEffect(() => () => {
    if (watchIdRef.current != null) {
      navigator.geolocation.clearWatch(watchIdRef.current);
    }
  }, []);

  // Modo manual: clique no mapa adiciona waypoint
  const addManualWaypoint = (lat, lng) => {
    setPoints((prev) => {
      // Se está vazio e tem origem, semeia origem antes
      if (prev.length === 0 && oLat != null && oLng != null) {
        return [[oLat, oLng], [lat, lng]];
      }
      return [...prev, [lat, lng]];
    });
  };
  const undoLast = () => {
    setPoints((prev) => {
      // Não remove a semente da origem
      if (prev.length <= 1) return [];
      return prev.slice(0, -1);
    });
  };
  const clearAll = () => {
    setPoints([]);
    setAutoStart(null);
    setAutoEnd(null);
    setWaypoints([]);
    lastSampleRef.current = { ts: 0, lat: null, lng: null };
  };

  // ----- Modo AUTO (rua) -----
  // Pega GPS atual do dispositivo (1 fix de alta precisão)
  const captureCurrentPos = () => new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("GPS indisponível neste dispositivo"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve([pos.coords.latitude, pos.coords.longitude]),
      (err) => reject(new Error(err.message || "Falha no GPS")),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 12000 },
    );
  });

  const markStart = async () => {
    setError("");
    try {
      const [lat, lng] = await captureCurrentPos();
      setAutoStart([lat, lng]);
      setGpsFix({ lat, lng });
      // Se já temos fim, recalcula a rota
      if (autoEnd) await calcAutoRoute([lat, lng], autoEnd);
      else setPoints([[lat, lng]]); // mostra o pino do início no mapa
    } catch (e) {
      setError(e.message);
    }
  };

  const markEnd = async () => {
    setError("");
    try {
      const [lat, lng] = await captureCurrentPos();
      setAutoEnd([lat, lng]);
      setGpsFix({ lat, lng });
      if (autoStart) await calcAutoRoute(autoStart, [lat, lng]);
      else setPoints((p) => [...p, [lat, lng]]);
    } catch (e) {
      setError(e.message);
    }
  };

  // iter188 — Versão SÍNCRONA (sem OSRM) usada durante drag direto na linha.
  // Cria o waypoint imediatamente e retorna seu índice, sem esperar API.
  const insertWaypointSync = useCallback((lat, lng) => {
    if (!autoStart || !autoEnd) return null;
    const cur = waypointsRef.current;
    const seq = [autoStart, ...cur, autoEnd];
    let bestIdx = 0;
    let bestDist = Infinity;
    for (let i = 0; i < seq.length - 1; i += 1) {
      const midLat = (seq[i][0] + seq[i + 1][0]) / 2;
      const midLng = (seq[i][1] + seq[i + 1][1]) / 2;
      const d = hav(midLat, midLng, lat, lng);
      if (d < bestDist) { bestDist = d; bestIdx = i; }
    }
    const next = [
      ...cur.slice(0, bestIdx),
      [lat, lng],
      ...cur.slice(bestIdx),
    ];
    setWaypoints(next);
    // Atualiza polyline imediatamente com retas pra feedback visual
    setPoints([autoStart, ...next, autoEnd]);
    return bestIdx;
  }, [autoStart, autoEnd, hav]);

  const updateWaypointSync = useCallback((idx, lat, lng) => {
    setWaypoints((prev) => {
      const next = prev.map((w, i) => (i === idx ? [lat, lng] : w));
      // Atualiza polyline reta imediatamente
      if (autoStart && autoEnd) {
        setPoints([autoStart, ...next, autoEnd]);
      }
      return next;
    });
  }, [autoStart, autoEnd]);

  const onDragEnd = useCallback(async () => {
    if (autoStart && autoEnd) {
      await calcAutoRoute(autoStart, autoEnd, waypointsRef.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, autoEnd]);

  // Chama OSRM (foot) entre 2 pontos + waypoints (iter187) e popula points
  // com a polyline da rua. Aceita override `nextWaypoints` para evitar
  // race condition do setState.
  const calcAutoRoute = async (start, end, nextWaypoints = null) => {
    setAutoRouting(true);
    try {
      const wps = nextWaypoints !== null ? nextWaypoints : waypoints;
      const body = {
        from_lat: start[0], from_lng: start[1],
        to_lat: end[0], to_lng: end[1],
        waypoints: wps && wps.length > 0 ? wps : null,
      };
      const r = collabId
        ? await api.redeIaCableRoutePublic(collabId, body)
        : await api.redeIaCableRoute(body);
      // r.geometry vem como [[lat,lng],...]
      const geom = (r?.geometry && r.geometry.length >= 2)
        ? r.geometry
        : [start, ...(wps || []), end]; // fallback reta passando waypoints
      setPoints(geom);
    } catch (e) {
      // Fallback: linha reta entre os 2 pontos (via waypoints)
      const wps = nextWaypoints !== null ? nextWaypoints : waypoints;
      setPoints([start, ...(wps || []), end]);
      setError("OSRM indisponível — usando linha reta entre os pontos");
    } finally {
      setAutoRouting(false);
    }
  };

  // iter187 — Adiciona um waypoint na posição clicada e recalcula a rota.
  // Insere no waypoint mais próximo do ponto clicado para ficar visualmente
  // coerente com o trajeto (parecido com Google Maps).
  const insertWaypointAt = async (lat, lng) => {
    if (!autoStart || !autoEnd) return;
    // Sequência atual de waypoints + extremidades para calcular distância
    const seq = [autoStart, ...waypoints, autoEnd];
    let bestIdx = 0;
    let bestDist = Infinity;
    for (let i = 0; i < seq.length - 1; i += 1) {
      // Distância perpendicular aproximada ao segmento (haversine média)
      const midLat = (seq[i][0] + seq[i + 1][0]) / 2;
      const midLng = (seq[i][1] + seq[i + 1][1]) / 2;
      const d = hav(midLat, midLng, lat, lng);
      if (d < bestDist) { bestDist = d; bestIdx = i; }
    }
    // Insere após posição `bestIdx` na lista de waypoints (= bestIdx)
    const next = [
      ...waypoints.slice(0, bestIdx),
      [lat, lng],
      ...waypoints.slice(bestIdx),
    ];
    setWaypoints(next);
    await calcAutoRoute(autoStart, autoEnd, next);
  };

  const moveWaypoint = async (idx, lat, lng) => {
    const next = waypoints.map((w, i) => (i === idx ? [lat, lng] : w));
    setWaypoints(next);
    if (autoStart && autoEnd) await calcAutoRoute(autoStart, autoEnd, next);
  };

  const removeWaypoint = async (idx) => {
    const next = waypoints.filter((_, i) => i !== idx);
    setWaypoints(next);
    if (autoStart && autoEnd) await calcAutoRoute(autoStart, autoEnd, next);
  };

  const baseDist = polylineLen(points);
  const totalDist = Math.round(baseDist + slackStart + slackEnd);
  const straightDist = (oLat != null && dLat != null)
    ? hav(oLat, oLng, dLat, dLng) : 0;

  // Centro inicial do mapa
  const mapCenter = autoStart || (oLat != null
    ? [oLat, oLng]
    : (gpsFix ? [gpsFix.lat, gpsFix.lng] : [-9.6498, -35.7089]));

  return (
    <div data-testid="cable-track-recorder">
      {/* Toggle modo */}
      <div style={{ display: "flex", gap: 4, marginBottom: 10,
                       background: "#f1f5f9", padding: 4, borderRadius: 10 }}>
        <button data-testid="track-mode-auto"
                onClick={() => { if (!recording) setMode("auto"); }}
                disabled={recording}
                style={{
                  flex: 1, padding: "10px 6px", borderRadius: 8,
                  border: "none", cursor: recording ? "default" : "pointer",
                  background: mode === "auto" ? "#fff" : "transparent",
                  fontWeight: 700, fontSize: 12, color: C_TEXT,
                  boxShadow: mode === "auto"
                    ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                }}>
          ️ Auto (rua)
        </button>
        <button data-testid="track-mode-gps"
                onClick={() => { if (!recording) setMode("gps"); }}
                disabled={recording}
                style={{
                  flex: 1, padding: "10px 6px", borderRadius: 8,
                  border: "none", cursor: recording ? "default" : "pointer",
                  background: mode === "gps" ? "#fff" : "transparent",
                  fontWeight: 700, fontSize: 12, color: C_TEXT,
                  boxShadow: mode === "gps"
                    ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                }}>
          GPS andando
        </button>
        <button data-testid="track-mode-manual"
                onClick={() => { if (!recording) setMode("manual"); }}
                disabled={recording}
                style={{
                  flex: 1, padding: "10px 6px", borderRadius: 8,
                  border: "none", cursor: recording ? "default" : "pointer",
                  background: mode === "manual" ? "#fff" : "transparent",
                  fontWeight: 700, fontSize: 12, color: C_TEXT,
                  boxShadow: mode === "manual"
                    ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                }}>
          ✏️ Desenhar
        </button>
      </div>

      {/* Mapa */}
      <div style={{ height: "48vh", borderRadius: 12, overflow: "hidden",
                       border: `1px solid ${C_BORDER}`, marginBottom: 10 }}>
        <MapContainer center={mapCenter} zoom={17}
                         style={{ height: "100%", width: "100%" }}
                         key={`${mapCenter[0].toFixed(4)}-${mapCenter[1].toFixed(4)}`}>
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            attribution='© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contribuidores © <a href="https://carto.com/attributions">CARTO</a>' />
          {/* Click handler para modo manual */}
          {mode === "manual" && (
            <MapClickHandlerLeaf onClick={addManualWaypoint} />
          )}
          {/* Pino origem */}
          {oLat != null && (
            <Marker position={[oLat, oLng]} icon={ICON_ORIGIN}>
              <Tooltip permanent direction="top" offset={[0, -32]}>
                <strong>{originItem.name}</strong> (Origem)
              </Tooltip>
            </Marker>
          )}
          {/* Pino destino */}
          {dLat != null && (
            <Marker position={[dLat, dLng]} icon={ICON_SEL}>
              <Tooltip permanent direction="top" offset={[0, -40]}>
                <strong>{destItem.name}</strong> (Destino)
              </Tooltip>
            </Marker>
          )}
          {/* iter188 — Drag direto na linha (Google Maps puxa-borracha) */}
          {mode === "auto" && autoStart && autoEnd && (
            <LineDragController
              active
              polylinePoints={points}
              onDragStart={insertWaypointSync}
              onDragMove={updateWaypointSync}
              onDragEnd={onDragEnd} />
          )}
          {/* Polyline do trajeto — clicável (modo auto) para criar waypoint */}
          {points.length >= 2 && (
            <Polyline positions={points}
                          eventHandlers={mode === "auto" && autoStart && autoEnd
                            ? {
                              click: (e) => insertWaypointAt(
                                e.latlng.lat, e.latlng.lng),
                            }
                            : {}}
                          pathOptions={{
                            color: "#0d9488", weight: 5,
                            ...(mode === "auto" && autoStart && autoEnd
                              ? { className: "track-polyline-clickable" }
                              : {}),
                          }} />
          )}
          {/* iter187 — Waypoints arrastáveis (modo auto / estilo Google Maps) */}
          {mode === "auto" && waypoints.map((wp, idx) => (
            <Marker key={`wp-${idx}`} position={wp}
                       draggable
                       icon={ICON_WAYPOINT}
                       eventHandlers={{
                         dragend: (e) => {
                           const ll = e.target.getLatLng();
                           moveWaypoint(idx, ll.lat, ll.lng);
                         },
                         dblclick: () => removeWaypoint(idx),
                       }}>
              <Tooltip direction="top" offset={[0, -10]}>
                Waypoint {idx + 1} — arraste ou clique duplo p/ remover
              </Tooltip>
            </Marker>
          ))}
          {/* Pinos Início/Fim do modo auto */}
          {autoStart && (
            <CircleMarker center={autoStart} radius={9}
                              pathOptions={{
                                color: "#fff", weight: 3,
                                fillColor: "#10b981", fillOpacity: 1,
                              }}>
              <Tooltip permanent direction="top" offset={[0, -8]}>
                <strong>Início</strong>
              </Tooltip>
            </CircleMarker>
          )}
          {autoEnd && (
            <CircleMarker center={autoEnd} radius={9}
                              pathOptions={{
                                color: "#fff", weight: 3,
                                fillColor: "#dc2626", fillOpacity: 1,
                              }}>
              <Tooltip permanent direction="top" offset={[0, -8]}>
                <strong>Fim</strong>
              </Tooltip>
            </CircleMarker>
          )}
          {/* Linha tracejada de referência (origem→destino direto) */}
          {oLat != null && dLat != null && points.length === 0 && (
            <Polyline positions={[[oLat, oLng], [dLat, dLng]]}
                          pathOptions={{
                            color: "#94a3b8", weight: 2, dashArray: "6,6",
                          }} />
          )}
          {/* Posição GPS atual */}
          {gpsFix && (
            <CircleMarker center={[gpsFix.lat, gpsFix.lng]} radius={7}
                              pathOptions={{
                                color: "#fff", weight: 2,
                                fillColor: "#3b82f6", fillOpacity: 0.9,
                              }} />
          )}
        </MapContainer>
      </div>

      {/* Cartão de comprimento */}
      <div style={{ background: "#fff", padding: 14, borderRadius: 12,
                       border: `1px solid ${C_BORDER}`, marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                         alignItems: "center", gap: 10 }}>
          <div>
            <div style={{ fontSize: 11, color: C_MUTED,
                             textTransform: "uppercase", letterSpacing: 0.4,
                             fontWeight: 700 }}>
              Trajeto medido
            </div>
            <div style={{ fontSize: 22, fontWeight: 900, color: C_TEXT,
                             lineHeight: 1.1, marginTop: 2 }}>
              {Math.round(baseDist)} m
            </div>
            <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4 }}>
              + sobras: <strong>{slackStart}m</strong> início ·
              {" "}<strong>{slackEnd}m</strong> fim
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: C_MUTED,
                             textTransform: "uppercase", letterSpacing: 0.4,
                             fontWeight: 700 }}>
              Cabo final
            </div>
            <div style={{ fontSize: 26, fontWeight: 900,
                             color: C_ACCENT, lineHeight: 1.1, marginTop: 2 }}>
              {totalDist} m
            </div>
            {straightDist > 0 && (
              <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4 }}>
                Reta: {Math.round(straightDist)}m
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Controles */}
      {mode === "auto" && (
        <div>
          <div style={{ display: "flex", gap: 8 }}>
            <button data-testid="track-auto-start"
                       onClick={markStart}
                       disabled={autoRouting}
                       style={{
                         ...primaryBtn, flex: 1, background: "#10b981",
                         opacity: autoRouting ? 0.6 : 1,
                       }}>
              {autoStart ? "Refazer Início" : "Marcar Início"}
            </button>
            <button data-testid="track-auto-end"
                       onClick={markEnd}
                       disabled={autoRouting}
                       style={{
                         ...primaryBtn, flex: 1, background: "#dc2626",
                         opacity: autoRouting ? 0.6 : 1,
                       }}>
              {autoEnd ? "Refazer Fim" : "Marcar Fim"}
            </button>
            {(autoStart || autoEnd) && (
              <button data-testid="track-auto-clear"
                         onClick={clearAll}
                         disabled={autoRouting}
                         style={{
                           padding: "0 14px", borderRadius: 10,
                           border: `1px solid ${C_BORDER}`, background: "#fff",
                           fontWeight: 700, color: C_TEXT, cursor: "pointer",
                         }}>
                Limpar
              </button>
            )}
          </div>
          <div style={{
            marginTop: 10, padding: 10, background: "#eff6ff",
            border: "1px solid #bfdbfe", borderRadius: 10,
            fontSize: 12, color: "#1e40af", lineHeight: 1.45,
          }}>
            {autoRouting ? (
              <>⏳ Calculando trajeto pelas ruas via OSRM...</>
            ) : (
              <>
                <strong>Como usar:</strong> Vá fisicamente até onde o cabo
                {" "}começa, toque <strong>“Marcar Início”</strong>. Depois vá
                {" "}até onde termina e toque <strong>“Marcar Fim”</strong>.
                {" "}O sistema completa o trajeto pelas ruas automaticamente.
                {autoStart && autoEnd && (
                  <>
                    <br /><br />
                    <strong>Ajuste fino (Google Maps-like):</strong>{" "}
                    <strong>Arraste qualquer trecho da linha verde</strong>
                    {" "}pra desviar o trajeto (puxa como borracha). Os
                    {" "}pontos brancos criados podem ser arrastados de novo
                    {" "}ou removidos com clique duplo.
                  </>
                )}
              </>
            )}
          </div>
          {autoStart && autoEnd && points.length >= 2 && (
            <div style={{
              marginTop: 8, padding: 10, background: "#ecfdf5",
              border: "1px solid #a7f3d0", borderRadius: 10,
              fontSize: 12, color: "#065f46", fontWeight: 600,
            }}>
              ✓ Trajeto calculado — {points.length} pontos pelas ruas
            </div>
          )}
        </div>
      )}
      {mode === "gps" && (
        <div style={{ display: "flex", gap: 8 }}>
          {!recording && (
            <button data-testid="track-gps-start"
                       onClick={startGps}
                       style={{ ...primaryBtn, flex: 1, background: "#0d9488" }}>
              {points.length === 0 ? "▶ Iniciar trecho" : "▶ Continuar gravação"}
            </button>
          )}
          {recording && (
            <button data-testid="track-gps-stop"
                       onClick={stopGps}
                       style={{ ...primaryBtn, flex: 1, background: "#dc2626" }}>
              ⏹ Finalizar trecho
            </button>
          )}
          {points.length > 0 && !recording && (
            <button data-testid="track-clear"
                       onClick={clearAll}
                       style={{
                         padding: "0 14px", borderRadius: 10,
                         border: `1px solid ${C_BORDER}`, background: "#fff",
                         fontWeight: 700, color: C_TEXT, cursor: "pointer",
                       }}>
              Limpar
            </button>
          )}
        </div>
      )}
      {mode === "manual" && (
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{
            flex: 1, padding: 12, borderRadius: 10, background: "#eff6ff",
            color: "#1e40af", fontSize: 12, lineHeight: 1.4,
            border: "1px solid #bfdbfe",
          }}>
            Toque no mapa para adicionar waypoints
            {" "}(poste, esquina, emenda...). Origem já incluída como ponto 1.
          </div>
          <button data-testid="track-manual-undo"
                     onClick={undoLast}
                     disabled={points.length === 0}
                     style={{
                       padding: "0 14px", borderRadius: 10,
                       border: `1px solid ${C_BORDER}`, background: "#fff",
                       fontWeight: 700, color: C_TEXT,
                       cursor: points.length === 0 ? "default" : "pointer",
                       opacity: points.length === 0 ? 0.5 : 1,
                     }}>
            ↶ Desfazer
          </button>
        </div>
      )}

      {/* Recording badge */}
      {recording && (
        <div style={{
          marginTop: 10, padding: 10, background: "#fef2f2",
          border: "1px solid #fecaca", borderRadius: 10,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span style={{
            width: 10, height: 10, borderRadius: "50%", background: "#dc2626",
            animation: "pulse 1.2s ease-in-out infinite",
          }} />
          <span style={{ fontSize: 12, color: "#7f1d1d", fontWeight: 700 }}>
            Gravando GPS — caminhe pelo trajeto do cabo
            {" "}({points.length} pontos)
          </span>
        </div>
      )}

      {points.length > 0 && !recording && mode === "gps" && (
        <div style={{
          marginTop: 10, padding: 10, background: "#ecfdf5",
          border: "1px solid #a7f3d0", borderRadius: 10,
          fontSize: 12, color: "#065f46", fontWeight: 600,
        }}>
          ✓ Trecho finalizado — {points.length} ponto(s) GPS gravados
        </div>
      )}

      {error && (
        <div style={{ marginTop: 10, padding: 10, background: "#fef2f2",
                         border: "1px solid #fecaca", borderRadius: 10,
                         fontSize: 12, color: "#991b1b" }}>
          {error}
        </div>
      )}
    </div>
  );
}

// useMapEvents só funciona dentro de MapContainer — wrapper isolado
function MapClickHandlerLeaf({ onClick }) {
  useMapEvents({
    click: (e) => onClick(e.latlng.lat, e.latlng.lng),
  });
  return null;
}




// =============================================================
// Main wizard
// =============================================================
export default function CadastroCTOWizard({ onClose, onCreated, technician }) {
  // step pode ser numérico (CTO) ou string (CE/CABO):
  //   CTO:  1, 2, 4, 5, 6, 7, 8 (step 3 / VLAN removido em iter179)
  //   CE:   1, 2, 'ce-bandejas', 'ce-tipo', 'ce-resumo' (iter180 sem VLAN)
  //   CABO: 1, 'cabo-origem', 'cabo-destino', 'cabo-config', 'cabo-resumo'
  const [step, setStep] = useState(1);
  const [elementType, setElementType] = useState(null); // "cto"|"ce"|"cabo"
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // ----- CTO/CE shared state -----
  const [address, setAddress] = useState({
    endereco: "", numero: "", referencia: "",
    bairro_detected: "", cidade_detected: "", estado_detected: "",
  });
  const [gps, setGps] = useState({ lat: null, lng: null, accuracy: null });
  const [bairros, setBairros] = useState([]);
  const [bairroSelected, setBairroSelected] = useState(null);
  const [bairroAutoMatched, setBairroAutoMatched] = useState(false);
  const [vlanInput, setVlanInput] = useState("");
  const [ensuringBairro, setEnsuringBairro] = useState(false);
  const [suggested, setSuggested] = useState({ name: "", number: null });
  const [photo, setPhoto] = useState(null);
  const [photoExtra, setPhotoExtra] = useState(null);
  // iter180 — Sentinela IA da foto. Estado de validação.
  // null = ainda não validou · obj = resultado · "validating" = em curso.
  const [photoCheck, setPhotoCheck] = useState(null);
  const [photoChecking, setPhotoChecking] = useState(false);
  const [photoTicketOpened, setPhotoTicketOpened] = useState(null);
  const fileInputRef = React.useRef(null);
  const fileInputExtraRef = React.useRef(null);

  // ----- CTO-specific -----
  const [capacity, setCapacity] = useState(null);
  const [networkType, setNetworkType] = useState(null);
  const [splitter, setSplitter] = useState(null);
  const [clientPort, setClientPort] = useState(null);
  // iter178 — Número físico da caixa (gravado pelo técnico na frente)
  const [boxNumber, setBoxNumber] = useState("");
  // iter183 — Número sequencial da CTO (editável; default = sugerido).
  // Compõe a nomenclatura: CTO_{vlan}_{ctoNumber 4 dígitos}
  const [ctoNumber, setCtoNumber] = useState("");
  // iter211ba — input digitado da VLAN; quando bate com um bairro cadastrado,
  // atualiza `bairroSelected`. Sem bairro válido, o Continuar fica disabled.
  const [typedVlan, setTypedVlan] = useState(null);

  // ----- CE-specific -----
  const [bandejasTotal, setBandejasTotal] = useState(null);
  const [ceInstallType, setCeInstallType] = useState(null);

  // ----- CABO-specific -----
  const [caboFrom, setCaboFrom] = useState(null);
  const [caboTo, setCaboTo] = useState(null);
  const [fibrasTotal, setFibrasTotal] = useState(null);
  const [fibrasOcupadas, setFibrasOcupadas] = useState(0);
  const [cableType, setCableType] = useState(null);
  // iter183 — novos campos físicos do cabo
  const [foCount, setFoCount] = useState(null);    // 4|6|8|12|24|48|72|96|144
  const [cableBrand, setCableBrand] = useState("");
  const [cableSerial, setCableSerial] = useState("");
  const [extraMargin, setExtraMargin] = useState(20);  // 10m × 2 pontas (default)
  const [cableRoute, setCableRoute] = useState(null);  // { geometry, distance_m }
  const [routingCable, setRoutingCable] = useState(false);
  // iter186 — Trajeto físico do cabo (GPS andado ou waypoints manuais)
  // Estrutura: { points: [[lat,lng],...], distance_m: number, mode: "gps"|"manual" }
  const [cableTrack, setCableTrack] = useState(null);
  const [slackCfg, setSlackCfg] = useState({
    slack_start_m: 10, slack_end_m: 10,
    gps_min_distance_m: 5, gps_interval_seconds: 3,
  });
  const [elementsList, setElementsList] = useState([]);
  const [elementsLoading, setElementsLoading] = useState(false);
  // iter186 — cabos órfãos próximos ao GPS (sugestão de vínculo no
  // cadastro de CTO/CE); auto-vincula se técnico aceitar
  const [orphanNear, setOrphanNear] = useState([]);
  const [orphanLinking, setOrphanLinking] = useState({});
  const [linkOrphans, setLinkOrphans] = useState(true);

  // ----- Helpers -----
  const collabId = technician?.id || null;
  const useApi = useMemo(() => ({
    bairros: () => collabId ? api.redeIaBairrosPublic(collabId) : api.redeIaBairros(),
    ensureBairro: (data) => collabId
      ? api.redeIaBairroEnsureFromFieldPublic(collabId, data)
      : api.redeIaBairroEnsureFromField(data),
    suggest: (sigla, vlan, num, elemT) => {
      const elt = elemT || "cto";
      return collabId
        ? api.redeIaSuggestNamePublic(collabId, sigla, vlan, num, elt)
        : api.redeIaSuggestName(sigla, vlan, num, elt);
    },
    create: (data) => collabId
      ? api.redeIaCtoCreatePublic(collabId, data)
      : api.redeIaCtoCreate(data),
    listElements: () => collabId
      ? api.redeIaCtosListPublic(collabId, {})
      : api.redeIaCtosList({}),
  }), [collabId]);

  // ----- Photo helpers -----
  const handlePhotoUpload = useCallback((file, setter) => {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      setError("Foto muito grande (limite 4MB).");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const max = 1280;
        let { width: w, height: h } = img;
        if (w > max || h > max) {
          if (w > h) { h = Math.round(h * max / w); w = max; }
          else { w = Math.round(w * max / h); h = max; }
        }
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, w, h);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.78);
        // iter211y/v2 — foto-first UX: salva a foto crua AGORA pra não
        // travar o fluxo (Android + Nominatim lento causava tela branca
        // intermitente). O selo é aplicado em background e substitui
        // a dataUrl quando pronto, sem bloquear o usuário.
        setter(dataUrl);
        setError("");
        // iter211az — Stamp aplicado a CTO, CE E CABO (antes só cto/ce).
        // O selo é uma prova de campo, então faz sentido em todos eles.
        if (elementType === "cto" || elementType === "ce"
            || elementType === "cabo") {
          // iter211az — inclui colaborador + nomenclatura sugerida do elemento.
          const elementName = suggested?.name
            || (elementType === "cto" && bairroSelected?.vlan && ctoNumber
                  ? `CTO_${bairroSelected.vlan}_${String(parseInt(ctoNumber, 10) || 0).padStart(4, "0")}`
                  : "");
          const stampPromise = stampFieldPhoto(dataUrl, {
            lat: gps?.lat, lng: gps?.lng,
            label: elementType === "cto" ? "FOTO CTO"
                    : elementType === "ce" ? "FOTO CE" : "FOTO CABO",
            collaborator: technician?.name || "",
            element: elementName,
          });
          const timeoutPromise = new Promise((resolve) =>
            setTimeout(() => resolve(dataUrl), 7000));
          Promise.race([stampPromise, timeoutPromise])
            .then((stamped) => {
              if (stamped && stamped !== dataUrl) setter(stamped);
            })
            .catch(() => { /* silencioso */ });
        }
      };
      img.onerror = () => {
        setError("Não foi possível ler a foto. Tente novamente.");
      };
      img.src = reader.result;
    };
    reader.onerror = () => {
      setError("Erro ao ler arquivo.");
    };
    reader.readAsDataURL(file);
  }, [elementType, gps]);

  const onPhotoChange = useCallback((e) => {
    handlePhotoUpload(e.target.files?.[0], setPhoto);
    setPhotoCheck(null); // reset validação ao trocar a foto
    setPhotoTicketOpened(null);
  }, [handlePhotoUpload]);
  const onPhotoExtraChange = useCallback((e) => {
    handlePhotoUpload(e.target.files?.[0], setPhotoExtra);
  }, [handlePhotoUpload]);

  // iter180 — dispara a Sentinela IA assim que a foto principal estiver
  // carregada. Roda só uma vez por foto (resetado em onPhotoChange).
  useEffect(() => {
    if (!photo || photoCheck || photoChecking) return;
    // Só roda para CTO/CE (CABO não tem critério visual claro de "tem caixa")
    if (elementType !== "cto" && elementType !== "ce") return;
    if (!gps?.lat || !gps?.lng) return;
    setPhotoChecking(true);
    const fn = collabId
      ? (data) => api.redeIaPhotoValidatePublic(collabId, data)
      : api.redeIaPhotoValidate;
    fn({
      photo_data_url: photo,
      lat: gps.lat, lng: gps.lng,
      element_type: elementType,
    }).then((r) => setPhotoCheck(r))
      .catch((e) => {
        // Em caso de erro de rede, não bloqueia o fluxo — só não exibe
        console.warn("[sentinela-ia] falha:", e); // eslint-disable-line
        setPhotoCheck({ action: "approve", score: 0,
                          message: "Sentinela IA indisponível.", _failed: true });
      })
      .finally(() => setPhotoChecking(false));
  }, [photo, photoCheck, photoChecking, elementType, gps, collabId]);

  // ----- Bairros auto-match (CTO/CE) -----
  useEffect(() => {
    if (!address.bairro_detected) return;
    useApi.bairros().then((r) => {
      const list = r.items || [];
      setBairros(list);
      if (list.length === 0) return;
      const norm = (s) => (s || "").toString().normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
      const target = norm(address.bairro_detected);
      const match = list.find((b) => norm(b.bairro) === target)
        || list.find((b) => norm(b.bairro).includes(target) || target.includes(norm(b.bairro)));
      if (match) {
        setBairroSelected(match);
        setBairroAutoMatched(true);
      } else {
        setBairroAutoMatched(false);
      }
    }).catch(() => setBairros([]));
  }, [address.bairro_detected, useApi]);

  // iter183 — Calcula rota OSRM quando ambos os pontos estão definidos
  useEffect(() => {
    if (elementType !== "cabo") return;
    const fLat = caboFrom?.gps?.lat;
    const fLng = caboFrom?.gps?.lng;
    const tLat = caboTo?.gps?.lat;
    const tLng = caboTo?.gps?.lng;
    if (fLat == null || fLng == null || tLat == null || tLng == null) {
      setCableRoute(null);
      return;
    }
    setRoutingCable(true);
    const fn = collabId
      ? () => api.redeIaCableRoutePublic(collabId,
            { from_lat: fLat, from_lng: fLng, to_lat: tLat, to_lng: tLng })
      : () => api.redeIaCableRoute(
            { from_lat: fLat, from_lng: fLng, to_lat: tLat, to_lng: tLng });
    fn().then((r) => {
      setCableRoute({
        geometry: r.geometry,
        distance_m: r.distance_m,
        source: r.source,
        warning: r.warning,
      });
    }).catch(() => setCableRoute(null))
      .finally(() => setRoutingCable(false));
  }, [elementType, caboFrom, caboTo, collabId]);

  // iter211bb — Auto-sugere VLAN baseada no GPS quando entra no step 7.
  // Chama /api/rede-ia/public/suggest-vlan-from-gps que descobre a OLT
  // que atende essa região (RIO_HUAWEI / MAGE_ZTE / PENHA_HUAWEI / ...)
  // e retorna a VLAN do bairro cadastrado pra essa OLT (ou 1 como fallback).
  const [gpsVlanSuggestion, setGpsVlanSuggestion] = useState(null);
  useEffect(() => {
    if (step !== 7 || !gps?.lat || !gps?.lng || typedVlan != null
        || elementType !== "cto") return;
    const base = process.env.REACT_APP_BACKEND_URL;
    if (!base) return;
    fetch(`${base}/api/rede-ia/public/suggest-vlan-from-gps`
          + `?lat=${gps.lat}&lng=${gps.lng}`
          + (collabId ? `&collab_id=${collabId}` : ""))
      .then((r) => r.json())
      .then((j) => {
        if (!j || j.suggested_vlan == null) return;
        setGpsVlanSuggestion(j);
        // Auto-preenche o input com a VLAN sugerida
        const v = String(j.suggested_vlan);
        setTypedVlan(v);
        const b = bairros.find((x) => Number(x.vlan) === Number(j.suggested_vlan));
        if (b) {
          setBairroSelected(b);
          setCtoNumber("");
        }
      })
      .catch(() => { /* silencioso — usuário pode digitar manualmente */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, gps?.lat, gps?.lng, elementType]);
  useEffect(() => {
    if (bairroSelected && elementType !== "cabo") {
      useApi.suggest(bairroSelected.sigla, bairroSelected.vlan, undefined, elementType)
        .then((r) => {
          setSuggested({
            name: r.suggested_name, number: r.suggested_number,
          });
          // iter211aq — Pré-preenchimento automático do ctoNumber removido.
          // O técnico deve digitar o número manualmente. A sugestão fica
          // apenas como dica visual (suggested.number) se o usuário quiser.
        })
        .catch(() => setSuggested({ name: "", number: null }));
    }
  }, [bairroSelected, elementType, useApi]);

  // ----- Load elements list when CABO origem step opens -----
  useEffect(() => {
    if (step !== "cabo-origem" && step !== "cabo-destino"
        && step !== "cabo-lancar") return;
    if (elementsList.length > 0) return;
    setElementsLoading(true);
    useApi.listElements()
      .then((r) => setElementsList(r.items || []))
      .catch(() => setElementsList([]))
      .finally(() => setElementsLoading(false));
  }, [step, elementsList.length, useApi]);

  // ----- Load cable slack config when CABO flow starts -----
  useEffect(() => {
    if (elementType !== "cabo") return;
    const fn = collabId
      ? () => api.redeIaCableSlackPublic(collabId)
      : () => api.redeIaCableSlackGet();
    fn().then((cfg) => {
      if (!cfg) return;
      const start = Number(cfg.slack_start_m) || 10;
      const end = Number(cfg.slack_end_m) || 10;
      setSlackCfg({
        slack_start_m: start,
        slack_end_m: end,
        gps_min_distance_m: Number(cfg.gps_min_distance_m) || 5,
        gps_interval_seconds: Number(cfg.gps_interval_seconds) || 3,
      });
      setExtraMargin(start + end);
    }).catch(() => { /* mantém defaults */ });
  }, [elementType, collabId]);

  // iter186 — Detecta cabos órfãos a <=30m do GPS atual (só CTO/CE).
  // Roda quando GPS muda; mostra card de sugestão antes do submit.
  useEffect(() => {
    if (elementType !== "cto" && elementType !== "ce") {
      setOrphanNear([]);
      return;
    }
    if (!gps?.lat || !gps?.lng) return;
    const fn = collabId
      ? () => api.redeIaCablesOrphanNearPublic(collabId,
            gps.lat, gps.lng, 30)
      : () => api.redeIaCablesOrphanNear(gps.lat, gps.lng, 30);
    fn().then((r) => setOrphanNear(r.items || []))
      .catch(() => setOrphanNear([]));
  }, [elementType, gps?.lat, gps?.lng, collabId]);

  // ----- Load suggested name for CABO from origem -----
  useEffect(() => {
    if (elementType !== "cabo" || !caboFrom) return;
    const sigla = caboFrom.sigla;
    const vlan = caboFrom.vlan;
    if (!sigla || !vlan) return;
    useApi.suggest(sigla, vlan, undefined, "cabo")
      .then((r) => setSuggested({
        name: r.suggested_name, number: r.suggested_number,
      }))
      .catch(() => setSuggested({ name: "", number: null }));
  }, [elementType, caboFrom, useApi]);

  // ----- Navigation helpers -----
  // iter183 — Verifica se há dados não-salvos antes de fechar/voltar pra evitar
  // perda involuntária quando o técnico tocar "←" sem querer.
  const hasUnsavedData = useCallback(() => {
    if (step === 1) return false;
    // Indícios de progresso: foto, endereço completo, gps, ctoNumber etc.
    return !!(
      photo || photoExtra
        || (address?.endereco && address?.numero)
        || (gps?.lat && gps?.lng && elementType !== "cabo")
        || ctoNumber
        || caboFrom || caboTo
    );
  }, [step, photo, photoExtra, address, gps, ctoNumber, elementType,
        caboFrom, caboTo]);

  const goBack = () => {
    // CTO: 4→2 (pula step 3 VLAN); 8→7 (Nº Caixa)
    if (typeof step === "number" && step > 1) {
      if (elementType === "cto" && step === 4) { setStep(2); return; }
      setStep(step - 1); return;
    }
    // CE chain (iter180 — sem step de VLAN; volta de bandejas → mapa step 2)
    if (step === "ce-bandejas") { setStep(2); return; }
    if (step === "ce-tipo") { setStep("ce-bandejas"); return; }
    if (step === "ce-resumo") { setStep("ce-tipo"); return; }
    // CABO chain (iter186 — entrada direta em "lancar"; origem/destino opcionais)
    if (step === "cabo-lancar") { setStep(1); return; }
    if (step === "cabo-origem") { setStep("cabo-lancar"); return; }
    if (step === "cabo-destino") { setStep("cabo-lancar"); return; }
    if (step === "cabo-trajeto") { setStep("cabo-lancar"); return; }
    if (step === "cabo-config") { setStep("cabo-lancar"); return; }
    if (step === "cabo-resumo") { setStep("cabo-config"); return; }
    // step === 1 e queremos fechar — confirma se houver dados
    if (hasUnsavedData()) {
      const ok = window.confirm(
        "Você tem dados não salvos neste cadastro. Tem certeza que deseja sair?\n\n"
        + "Dica: termine o cadastro — se estiver sem internet, ele é "
        + "salvo automaticamente na fila offline.",
      );
      if (!ok) return;
    }
    onClose?.();
  };

  // ----- GPS capture (fallback button) — iter183: usa helper híbrido -----
  const captureGps = useCallback(() => {
    setError("");
    getBestPosition({ cutoffM: 25, timeoutMs: 12000 })
      .then((fix) => setGps({
        lat: fix.lat, lng: fix.lng, accuracy: fix.accuracy,
      }))
      .catch((err) => setError(`Falha GPS: ${err.message || err}`));
  }, []);

  // ----- Submit -----
  const submit = async () => {
    setBusy(true); setError("");
    try {
      let payload;
      if (elementType === "cabo") {
        // iter186 — Cabo pode ser lançado SEM origem/destino (cabo solto).
        // Endereço/GPS derivam do trajeto desenhado/gravado quando não há
        // CTO/CE vinculadas; ficam visíveis no mapa principal em laranja
        // tracejado até alguém vincular as pontas (status "cabo_solto").
        const from = caboFrom; const to = caboTo;
        const trk = cableTrack?.points || [];
        const startPt = (from?.gps?.lat != null)
          ? [from.gps.lat, from.gps.lng]
          : (trk.length > 0 ? trk[0] : null);
        const endPt = (to?.gps?.lat != null)
          ? [to.gps.lat, to.gps.lng]
          : (trk.length > 0 ? trk[trk.length - 1] : null);
        const midLat = (startPt && endPt)
          ? (startPt[0] + endPt[0]) / 2
          : (startPt ? startPt[0] : null);
        const midLng = (startPt && endPt)
          ? (startPt[1] + endPt[1]) / 2
          : (startPt ? startPt[1] : null);

        // Endereço: prioriza CTO de origem; senão usa bairro/sigla auto-detectado
        // (técnico pode vincular depois e atualizar).
        const refSigla = from?.sigla || to?.sigla
          || bairroSelected?.sigla || "GEN";
        const refVlan = from?.vlan || to?.vlan || bairroSelected?.vlan || 0;
        const refName = from ? from.name : (to ? to.name : "ponto-aberto");
        const refToName = to ? to.name : (from ? "ponto-aberto" : "ponto-aberto");

        payload = {
          element_type: "cabo",
          rua: (from?.address || {}).rua
            || (to?.address || {}).rua || "—",
          numero: (from?.address || {}).numero
            || (to?.address || {}).numero || "—",
          bairro: (from?.address || {}).bairro
            || (to?.address || {}).bairro
            || bairroSelected?.bairro || "—",
          cidade: (from?.address || {}).cidade
            || (to?.address || {}).cidade || "",
          estado: (from?.address || {}).estado
            || (to?.address || {}).estado || "",
          referencia: `${refName} → ${refToName}`,
          lat: midLat, lng: midLng,
          capacity: 0, network_type: "", splitter: null,
          client_port: null,
          sigla: refSigla, vlan: refVlan,
          suggested_name: suggested.name,
          technician_id: collabId,
          technician_name: technician?.name || "",
          photo_data_url: photo || null,
          photo_extra_data_url: photoExtra || null,
          // CABO-specific
          from_element_id: from?.id || null,
          to_element_id: to?.id || null,
          fibras_total: fibrasTotal,
          fibras_ocupadas: fibrasOcupadas || 0,
          cable_type: cableType,
          // iter183 — Roteamento OSRM + identificação física
          // iter186 — Trajeto real (GPS andado ou waypoints manuais) tem
          // PRIORIDADE sobre OSRM. Se o técnico gravou/desenhou, usa isso.
          fo_count: foCount || null,
          cable_brand: cableBrand || null,
          cable_serial: cableSerial || null,
          route_geometry: cableTrack?.points || cableRoute?.geometry || null,
          route_distance_m: cableTrack?.distance_m
            || cableRoute?.distance_m || null,
          route_source: cableTrack ? cableTrack.mode : "osrm",
          extra_margin_m: extraMargin,
          to_lat: endPt ? endPt[0] : null,
          to_lng: endPt ? endPt[1] : null,
          // Flag de cabo solto (backend pode usar pra status)
          is_loose: !from || !to,
        };
      } else if (elementType === "ce") {
        payload = {
          element_type: "ce",
          rua: address.endereco, numero: address.numero,
          bairro: bairroSelected.bairro,
          cidade: bairroSelected.cidade || address.cidade_detected || "",
          estado: bairroSelected.estado || address.estado_detected || "",
          referencia: address.referencia,
          lat: gps.lat, lng: gps.lng,
          capacity: 0, network_type: "", splitter: null,
          client_port: null,
          sigla: bairroSelected.sigla, vlan: bairroSelected.vlan,
          suggested_name: suggested.name,
          technician_id: collabId,
          technician_name: technician?.name || "",
          photo_data_url: photo || null,
          photo_extra_data_url: photoExtra || null,
          // CE-specific
          bandejas_total: bandejasTotal,
          ce_install_type: ceInstallType,
        };
      } else {
        // CTO — iter211ar: "Sem splitter" e "Outro" viram null no payload
        // (backend já interpreta como "sem informação útil").
        const splitterValue = (splitter && !splitter.startsWith("Sem")
                                  && splitter !== "Outro")
          ? splitter : null;
        payload = {
          element_type: "cto",
          rua: address.endereco, numero: address.numero,
          bairro: bairroSelected.bairro,
          cidade: bairroSelected.cidade || address.cidade_detected || "",
          estado: bairroSelected.estado || address.estado_detected || "",
          referencia: address.referencia,
          lat: gps.lat, lng: gps.lng,
          capacity, network_type: networkType, splitter: splitterValue,
          // iter178 — porta removida, número da caixa adicionado
          box_number: boxNumber.trim() || null,
          sigla: bairroSelected.sigla,
          // CTO não precisa de VLAN (iter178). Backend ainda aceita por compat;
          // enviamos vlan do bairro como fallback p/ não quebrar API existente.
          vlan: bairroSelected.vlan || null,
          suggested_name: suggested.name,
          // iter211aq — Nº da CTO agora é OBRIGATÓRIO, sem fallback pra
          // suggested.number. Backend rejeita duplicidade no bairro/VLAN.
          cto_number: ctoNumber && parseInt(ctoNumber, 10) > 0
                        ? parseInt(ctoNumber, 10)
                        : null,
          technician_id: collabId,
          technician_name: technician?.name || "",
          photo_data_url: photo || null,
          photo_extra_data_url: photoExtra || null,
        };
      }
      const isOnline = typeof navigator === "undefined" ? true : navigator.onLine;
      // iter183 — Se OFFLINE, salva direto na fila (não tenta network)
      if (!isOnline) {
        await outbox.enqueue({
          kind: elementType || "cto",
          endpoint: collabId
            ? `/api/rede-ia/public/ctos/${collabId}`
            : `/api/rede-ia/ctos`,
          method: "POST",
          body: payload,
          collab_id: collabId,
          collab_name: technician?.name || "",
          description: `${(elementType || "cto").toUpperCase()} ${suggested?.name || ""} · ${payload.rua || ""} ${payload.numero || ""}`.trim(),
        });
        setError("");
        onCreated?.({
          _offline: true,
          name: suggested?.name || `${elementType?.toUpperCase()} (offline)`,
        });
        return;
      }
      const r = await useApi.create(payload);
      // iter186 — Auto-vínculo de cabos órfãos próximos
      if (linkOrphans && orphanNear.length > 0 && r?.id
          && (elementType === "cto" || elementType === "ce")) {
        const newId = r.id;
        setOrphanLinking({ total: orphanNear.length, done: 0 });
        for (let i = 0; i < orphanNear.length; i += 1) {
          const ep = orphanNear[i];
          try {
            await api.redeIaCableLinkEndpoint(ep.cable_id, ep.end, newId);
            setOrphanLinking({ total: orphanNear.length, done: i + 1 });
          } catch (e) {
            console.warn("[orphan-link] falhou:", ep.cable_id, e); // eslint-disable-line
          }
        }
      }
      onCreated?.(r);
      // iter211bg — feedback SmartOLT pro técnico após criar a CTO.
      // Se a CTO foi marcada smartolt_eligible, mostra toast informativo.
      try {
        if (r && r.smartolt_eligible && r.smartolt_olt_name) {
          window.dispatchEvent(new CustomEvent("smartprov:toast", {
            detail: {
              kind: "info",
              icon: "",
              title: "Sincronizando com SmartOLT…",
              message: `CTO ${r.name || ""} será registrada em ${r.smartolt_olt_name}.`,
              durationMs: 8000,
            },
          }));
          // Polling pra detectar quando o sync completar (a cada 20s, max 3min)
          // — o worker roda a cada 60s, então normalmente bate no 2º poll.
          const ctoId = r.id;
          const base = process.env.REACT_APP_BACKEND_URL;
          const collabId = window.__currentCollabId || null;
          if (ctoId && base && collabId) {
            let tries = 0;
            const maxTries = 9; // ~3min
            const poll = async () => {
              tries += 1;
              try {
                const u = await fetch(
                  `${base}/api/rede-ia/public/ctos/by-id/${ctoId}?collab_id=${collabId}`,
                ).then((x) => x.json()).catch(() => null);
                if (u && u.smartolt_synced_at) {
                  window.dispatchEvent(new CustomEvent("smartprov:toast", {
                    detail: {
                      kind: "success",
                      icon: "✅",
                      title: "CTO sincronizada no SmartOLT",
                      message: `Zone "${u.smartolt_zone_name || u.name}" criada em ${u.smartolt_olt_name}.`,
                      durationMs: 6000,
                    },
                  }));
                  return;
                }
              } catch { /* */ }
              if (tries < maxTries) setTimeout(poll, 20000);
            };
            setTimeout(poll, 15000);
          }
        }
      } catch { /* noop */ }
    } catch (e) {
      // iter183 — Network error (TypeError "Failed to fetch") OU 5xx → enfileira
      const isNetErr = e?.name === "TypeError"
                         || /network|fetch|offline/i.test(e?.message || "")
                         || (e?.response?.status >= 500);
      if (isNetErr) {
        try {
          await outbox.enqueue({
            kind: elementType || "cto",
            endpoint: collabId
              ? `/api/rede-ia/public/ctos/${collabId}`
              : `/api/rede-ia/ctos`,
            method: "POST",
            body: payload,
            collab_id: collabId,
            collab_name: technician?.name || "",
            description: `${(elementType || "cto").toUpperCase()} ${suggested?.name || ""} · ${payload.rua || ""} ${payload.numero || ""}`.trim(),
          });
          setError("");
          onCreated?.({
            _offline: true,
            name: suggested?.name || `${elementType?.toUpperCase()} (offline)`,
          });
          return;
        } catch (eo) {
          setError("Falha de rede e falha ao salvar localmente: "
                      + (eo?.message || "erro desconhecido"));
          return;
        }
      }
      const d = e?.response?.data?.detail;
      if (typeof d === "object" && d?.suggested_name) {
        setError(`${d.msg}. Sugerido: ${d.suggested_name}`);
        setSuggested({ name: d.suggested_name, number: d.suggested_number });
      } else {
        setError(typeof d === "string" ? d : "Falha ao criar elemento.");
      }
    } finally { setBusy(false); }
  };

  // ----- Header label -----
  const elementLabel = useMemo(() => {
    if (elementType === "ce") return "Caixa de Emenda";
    if (elementType === "cabo") return "Cabo";
    if (elementType === "cto") return "CTO";
    return "Elemento de Rede";
  }, [elementType]);

  const stepLabel = useMemo(() => {
    if (step === 1) return "Tipo";
    if (typeof step === "number") {
      // iter179 — CTO pula VLAN (step 3) e tem Nº Caixa no step 7
      const ctoLabels = ["", "Tipo", "Mapa", "", "Capacidade",
                            "Tipo de rede", "Splitter", "Nº Caixa", "Resumo"];
      const ceLabels = ["", "Tipo", "Mapa", "VLAN", "Capacidade",
                            "Tipo de rede", "Splitter", "Porta", "Resumo"];
      const labels = elementType === "cto" ? ctoLabels : ceLabels;
      return labels[step] || "";
    }
    const m = {
      "ce-bandejas": "Bandejas",
      "ce-tipo": "Instalação",
      "ce-resumo": "Resumo",
      "cabo-lancar": "Lançar cabo",
      "cabo-origem": "Origem",
      "cabo-destino": "Destino",
      "cabo-trajeto": "Trajeto",
      "cabo-config": "Configuração",
      "cabo-resumo": "Resumo",
    };
    return m[step] || "";
  }, [step]);

  return (
    <div data-testid="cto-wizard" style={{
      position: "fixed", inset: 0, background: C_BG, zIndex: 9999,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <button data-testid="cto-back-btn" onClick={goBack}
                  style={{ background: "transparent", border: 0, color: "#fff",
                            fontSize: 24, marginRight: 4, cursor: "pointer",
                            padding: 4 }}>
            ←
          </button>
          <span style={stepBadge}>
            {typeof step === "number" ? step : "•"}
          </span>
          <span>Cadastro de {elementLabel}</span>
        </div>
        <span style={{ fontSize: 11, opacity: 0.85 }}>{stepLabel}</span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "20px 16px",
                       fontSize: 14, color: C_TEXT }}>
        {error && (
          <div data-testid="cto-error" style={{
            background: "#fef2f2", color: C_DANGER, borderRadius: 10,
            padding: "10px 14px", marginBottom: 12, fontSize: 13,
            border: "1px solid #fecaca",
          }}>{error}</div>
        )}

        {/* === STEP 1 — Type chooser === */}
        {step === 1 && (
          <div data-testid="cadastro-tipo-selector" style={{ padding: "20px 8px 8px" }}>
            <div style={{ textAlign: "center", marginBottom: 18 }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: C_TEXT,
                                letterSpacing: -0.3, marginBottom: 6 }}>
                O que você quer cadastrar?
              </div>
              <div style={{ color: C_MUTED, fontSize: 13 }}>
                Identifique o elemento de rede a ser registrado no mapa
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <TypeCard testid="cadastro-tipo-cto"
                iconUrl="https://customer-assets.emergentagent.com/job_dual-combine-3/artifacts/6g3df7tv_ChatGPT%20Image%2028%20de%20mai.%20de%202026%2C%2022_17_10%20%281%29.png"
                color="#0ea5e9" bg="#e0f2fe"
                title="CTO" subtitle="Caixa Terminal Óptica"
                description="Caixa com splitter onde os clientes são conectados via porta."
                onClick={() => { setElementType("cto"); setStep(2); }}
              />
              <TypeCard testid="cadastro-tipo-ce"
                iconUrl="https://customer-assets.emergentagent.com/job_dual-combine-3/artifacts/hdvm2vpx_ChatGPT%20Image%2028%20de%20mai.%20de%202026%2C%2022_17_10%20%282%29.png"
                color="#7c3aed" bg="#ede9fe"
                title="CE" subtitle="Caixa de Emenda"
                description="Closure intermediária com bandejas de emenda (sem porta de cliente)."
                onClick={() => { setElementType("ce"); setStep(2); }}
              />
              <TypeCard testid="cadastro-tipo-cabo"
                iconUrl="https://customer-assets.emergentagent.com/job_dual-combine-3/artifacts/5gv6yxgf_ChatGPT%20Image%2028%20de%20mai.%20de%202026%2C%2022_17_10%20%283%29.png"
                color="#0d9488" bg="#ccfbf1"
                title="CABO" subtitle="Lance de Fibra"
                description="Trecho de cabo ligando dois elementos (CTO↔CTO, CE↔CTO, CE↔CE)."
                onClick={() => { setElementType("cabo"); setStep("cabo-lancar"); }}
              />
            </div>
          </div>
        )}

        {/* === STEP 2 — Map + Address + Photo (CTO/CE) === */}
        {step === 2 && (
          <div style={{ display: "flex", flexDirection: "column",
                          height: "calc(100vh - 110px)", marginTop: -20,
                          marginLeft: -16, marginRight: -16 }}>
            <div style={{ flex: "0 0 62%", position: "relative",
                            background: "#e2e8f0" }}>
              <CTOMapPicker
                collabId={collabId}
                onMove={({ lat, lng, address: a }) => {
                  setGps({ lat, lng, accuracy: null });
                  setAddress((prev) => {
                    const newHN = a.house_number || "";
                    // iter183 — Se o pino foi movido e o novo local NÃO traz
                    // número, limpa o número auto antigo. Mas preserva
                    // se o técnico digitou manualmente (numero_auto=false).
                    let nextNumero;
                    if (newHN) {
                      nextNumero = newHN;
                    } else if (prev.numero_auto) {
                      nextNumero = "";  // limpa "auto" antigo
                    } else {
                      nextNumero = prev.numero;  // preserva edição manual
                    }
                    return {
                      ...prev,
                      endereco: a.road || prev.endereco,
                      numero: nextNumero,
                      numero_auto: !!newHN,
                      bairro_detected: a.suburb || prev.bairro_detected,
                      cidade_detected: a.city || prev.cidade_detected,
                      estado_detected: a.state || prev.estado_detected,
                    };
                  });
                  setError("");
                }}
                onError={(m) => setError(m)}
              />
            </div>

            <div style={{ flex: 1, overflowY: "auto",
                            padding: "12px 16px 16px",
                            background: "#fff", borderTopLeftRadius: 16,
                            borderTopRightRadius: 16, marginTop: -16,
                            position: "relative", zIndex: 5,
                            boxShadow: "0 -6px 18px rgba(0,0,0,0.08)" }}>
              <h2 style={{ fontSize: 16, fontWeight: 800,
                              margin: "2px 0 10px", letterSpacing: -0.2 }}>
                Posicione o pino na {elementLabel}
              </h2>

              <label style={{ ...labelStyle, marginTop: 4 }}>Endereço (auto)</label>
              <input data-testid="cto-rua" style={inputBase} value={address.endereco}
                onChange={(e) => setAddress({ ...address, endereco: e.target.value })}
                placeholder="Detectado pelo mapa" />

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                              gap: 10 }}>
                <div>
                  <label style={labelStyle}>
                    Número {address.numero_auto && address.numero ? (
                      <span data-testid="cto-numero-auto-badge"
                            style={{ marginLeft: 4, fontSize: 9, padding: "1px 5px",
                                       borderRadius: 4, background: "#dbeafe",
                                       color: "#1e40af", fontWeight: 700 }}>
                        AUTO
                      </span>
                    ) : (
                      <span style={{ marginLeft: 4, fontSize: 9, padding: "1px 5px",
                                       borderRadius: 4, background: "#fef3c7",
                                       color: "#92400e", fontWeight: 700 }}>
                        DIGITE
                      </span>
                    )}
                  </label>
                  <input data-testid="cto-numero" style={inputBase} value={address.numero}
                    onChange={(e) => setAddress({ ...address, numero: e.target.value,
                                                     numero_auto: false })}
                    placeholder="Digite o nº" />
                </div>
                <div>
                  <label style={labelStyle}>
                    Bairro {address.bairro_detected ? (
                      <span style={{ marginLeft: 4, fontSize: 9, padding: "1px 5px",
                                       borderRadius: 4, background: "#dbeafe",
                                       color: "#1e40af", fontWeight: 700 }}>
                        AUTO
                      </span>
                    ) : (
                      <span style={{ marginLeft: 4, fontSize: 9, padding: "1px 5px",
                                       borderRadius: 4, background: "#fef3c7",
                                       color: "#92400e", fontWeight: 700 }}>
                        DIGITE
                      </span>
                    )}
                  </label>
                  <input data-testid="cto-bairro-detected" style={inputBase}
                    value={address.bairro_detected}
                    onChange={(e) => setAddress({ ...address,
                                                     bairro_detected: e.target.value })}
                    placeholder="Digite o bairro" />
                </div>
              </div>

              {/* iter182 — Campo "Referência" removido a pedido do gestor:
                  a localização vem do GPS + rede telefônica, suficiente. */}

              <label style={labelStyle}>
                Foto da {elementLabel} (recomendado)
              </label>
              <input ref={fileInputRef} type="file" accept="image/*"
                capture="environment" onChange={onPhotoChange}
                style={{ display: "none" }} data-testid="cto-photo-input" />
              {photo ? (
                <div style={{
                  position: "relative", borderRadius: 12,
                  overflow: "hidden", border: `1.5px solid ${C_BORDER}`,
                  marginBottom: 6,
                }}>
                  <img src={photo} alt="Foto" data-testid="cto-photo-preview"
                    style={{ width: "100%", display: "block",
                              maxHeight: 220, objectFit: "cover" }} />
                  <button data-testid="cto-photo-remove"
                    onClick={() => { setPhoto(null);
                                       if (fileInputRef.current) fileInputRef.current.value = ""; }}
                    style={{
                      position: "absolute", top: 8, right: 8,
                      background: "rgba(0,0,0,0.6)", color: "#fff",
                      border: 0, borderRadius: "50%", width: 28, height: 28,
                      fontSize: 14, fontWeight: 800, cursor: "pointer",
                    }}>×</button>
                </div>
              ) : (
                <button data-testid="cto-photo-btn"
                        onClick={() => fileInputRef.current?.click()}
                        style={{
                          ...inputBase, display: "flex", alignItems: "center",
                          justifyContent: "space-between", cursor: "pointer",
                          padding: "14px 14px",
                        }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 20 }}></span>
                    <span style={{ color: C_TEXT, fontWeight: 600 }}>
                      Tirar foto da {elementLabel}
                    </span>
                  </span>
                  <span style={{ color: C_MUTED, fontSize: 20 }}>›</span>
                </button>
              )}

              {/* iter180 — Painel da Sentinela IA logo abaixo da foto */}
              {photo && (elementType === "cto" || elementType === "ce") && (
                <SentinelaPanel
                  checking={photoChecking}
                  result={photoCheck}
                  ticketOpened={photoTicketOpened}
                  onOpenTicket={async () => {
                    if (!photoCheck?.open_ticket_hint || !collabId) return;
                    try {
                      const r = await api.redeIaPhotoOpenTicketPublic(collabId, {
                        photo_validation_id: photoCheck.validation_id || null,
                        lat: gps.lat, lng: gps.lng,
                        condition: photoCheck.vision?.condition || "quebrada",
                        summary: photoCheck.vision?.reasoning || "",
                      });
                      setPhotoTicketOpened(r);
                    } catch (e) {
                      // eslint-disable-next-line
                      console.warn("[sentinela-ia] open ticket failed:", e);
                    }
                  }}
                  onRetake={() => {
                    setPhoto(null); setPhotoCheck(null);
                    setPhotoTicketOpened(null);
                    if (fileInputRef.current) fileInputRef.current.value = "";
                  }}
                />
              )}

              {/* iter180 — exibimos o feedback APENAS quando o bairro NÃO foi
                  identificado E ainda não foi auto-criado em background. */}
              {address.bairro_detected && bairros.length > 0
                && !bairroAutoMatched && !bairroSelected && (
                <div data-testid="cto-bairro-feedback" style={{
                  marginTop: 10, padding: "8px 10px",
                  borderRadius: 6, fontSize: 11.5, lineHeight: 1.4,
                  background: "#f0f9ff",
                  color: "#075985",
                  border: "1px solid #bae6fd",
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <span style={{ fontSize: 13 }}>ⓘ</span>
                  <span>
                    Bairro <strong>{address.bairro_detected}</strong> ainda não está
                    na base — será criado automaticamente ao continuar
                    (sigla auto-gerada, VLAN default).
                  </span>
                </div>
              )}

              <div style={{ marginTop: 16 }}>
                <button data-testid="cto-step2-continue"
                        disabled={ensuringBairro
                            || photoChecking
                            || (photo && photoCheck?.action === "retake")}
                        onClick={async () => {
                          if (!gps.lat || !gps.lng) {
                            setError("Posicione o pino no mapa antes de continuar.");
                            return;
                          }
                          if (!address.endereco) {
                            setError("Endereço não detectado. Mova o pino até a rua.");
                            return;
                          }
                          // iter180 — bloqueio da Sentinela IA: se foi solicitado
                          // refazer a foto, o técnico precisa fazer isso antes
                          // de avançar (sem espaço para escapar do gate).
                          if (photo && photoCheck?.action === "retake") {
                            setError(photoCheck.message
                              || "Refaça a foto antes de continuar.");
                            return;
                          }
                          setError("");
                          // iter180 — CTO/CE: se o bairro do GPS não bate com
                          // nenhum cadastrado, auto-cria com VLAN=1 default
                          // (gestor pode revisar depois). Técnico não precisa
                          // mais escolher na lista nem informar VLAN.
                          if ((elementType === "cto" || elementType === "ce")
                              && !bairroSelected) {
                            if (!address.bairro_detected) {
                              setError("Bairro não detectado pelo GPS. Ajuste o pino.");
                              return;
                            }
                            setEnsuringBairro(true);
                            try {
                              const fn = collabId
                                ? (data) => api.redeIaBairroEnsureFromFieldPublic(collabId, data)
                                : api.redeIaBairroEnsureFromField;
                              const r = await fn({
                                bairro: address.bairro_detected,
                                vlan: 1,
                                cidade: address.cidade_detected || "",
                                estado: address.estado_detected || "",
                              });
                              setBairroSelected(r.bairro);
                              if (r.created) {
                                setBairros((prev) => [...prev, r.bairro]);
                              }
                            } catch (e) {
                              setError(e?.response?.data?.detail
                                || "Falha ao registrar bairro automaticamente.");
                              setEnsuringBairro(false);
                              return;
                            }
                            setEnsuringBairro(false);
                          }
                          // CTO → step 4 (capacidade) · CE → ce-bandejas
                          if (elementType === "cto") setStep(4);
                          else if (elementType === "ce") setStep("ce-bandejas");
                          else setStep(3);
                        }}
                        style={{ ...primaryBtn, opacity: ensuringBairro ? 0.6 : 1 }}>
                  {ensuringBairro ? "Registrando bairro..." : "Continuar"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* === STEP 3 — VLAN (CTO/CE) === */}
        {step === 3 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Qual é a VLAN dessa {elementLabel}?
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18,
                          lineHeight: 1.4 }}>
              Bairro detectado: <strong>{address.bairro_detected || "—"}</strong>.
              Informe a VLAN da rede no local. Reusamos se já existir;
              senão, criamos automaticamente.
            </p>

            {(() => {
              const norm = (s) => (s || "").normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
              const target = norm(address.bairro_detected);
              const sameBairro = bairros.filter(
                (b) => norm(b.bairro) === target,
              );
              if (sameBairro.length === 0) return null;
              return (
                <div data-testid="cto-vlan-suggestions" style={{ marginBottom: 16 }}>
                  <div style={{ ...labelStyle, marginTop: 0 }}>
                    Bairro já tem cadastro — toque para reutilizar:
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {sameBairro.map((b) => (
                      <button key={b.id}
                              data-testid={`cto-vlan-chip-${b.vlan}`}
                              type="button"
                              onClick={() => {
                                setVlanInput(String(b.vlan));
                                setBairroSelected(b);
                              }}
                              style={{
                                padding: "8px 12px", borderRadius: 999,
                                border: bairroSelected?.id === b.id
                                  ? `1.5px solid ${C_PRIMARY}` : `1px solid ${C_BORDER}`,
                                background: bairroSelected?.id === b.id
                                  ? C_PRIMARY_LIGHT : "#fff",
                                fontSize: 12, fontWeight: 700, color: C_TEXT,
                                cursor: "pointer",
                              }}>
                        VLAN <strong>{b.vlan}</strong> · {b.sigla}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })()}

            <label style={labelStyle}>VLAN (número de 1 a 4094)</label>
            <input data-testid="cto-vlan-input" type="number" inputMode="numeric"
              min="1" max="4094" value={vlanInput}
              onChange={(e) => {
                setVlanInput(e.target.value);
                if (bairroSelected && String(bairroSelected.vlan) !== e.target.value) {
                  setBairroSelected(null);
                }
              }}
              style={{ ...inputBase, fontSize: 18, fontWeight: 700,
                       fontFamily: "monospace", letterSpacing: 1 }}
              placeholder="Ex: 301" />

            {vlanInput && parseInt(vlanInput, 10) > 0 && (
              <div style={{
                marginTop: 14, padding: "12px 14px",
                background: "#f1f5f9", borderRadius: 8,
                border: `1px solid ${C_BORDER}`,
                fontSize: 12, color: C_MUTED, lineHeight: 1.5,
              }}>
                {bairroSelected ? (
                  <>✓ Reutilizando: <strong>{bairroSelected.bairro}</strong>
                  {" "}· sigla <strong>{bairroSelected.sigla}</strong>
                  {" "}· VLAN <strong>{bairroSelected.vlan}</strong></>
                ) : (
                  <>Será criado: bairro <strong>{address.bairro_detected || "?"}</strong>
                  {" "}· VLAN <strong>{vlanInput}</strong> (sigla auto-gerada)</>
                )}
              </div>
            )}

            <button data-testid="cto-step3-continue"
                    disabled={!vlanInput || parseInt(vlanInput, 10) < 1
                              || parseInt(vlanInput, 10) > 4094 || ensuringBairro}
                    onClick={async () => {
                      const vlanNum = parseInt(vlanInput, 10);
                      if (!vlanNum || vlanNum < 1 || vlanNum > 4094) {
                        setError("VLAN deve ser um número entre 1 e 4094.");
                        return;
                      }
                      setError("");
                      const goToNext = () => {
                        if (elementType === "ce") setStep("ce-bandejas");
                        else setStep(4);
                      };
                      if (bairroSelected && bairroSelected.vlan === vlanNum) {
                        goToNext(); return;
                      }
                      setEnsuringBairro(true);
                      try {
                        const fn = collabId
                          ? (data) => api.redeIaBairroEnsureFromFieldPublic(collabId, data)
                          : api.redeIaBairroEnsureFromField;
                        const r = await fn({
                          bairro: address.bairro_detected || "Bairro detectado",
                          vlan: vlanNum,
                          cidade: address.cidade_detected || "",
                          estado: address.estado_detected || "",
                        });
                        setBairroSelected(r.bairro);
                        if (r.created) setBairros((prev) => [...prev, r.bairro]);
                        goToNext();
                      } catch (e) {
                        setError(e?.response?.data?.detail
                                    || "Falha ao registrar bairro/VLAN.");
                      } finally { setEnsuringBairro(false); }
                    }}
                    style={{ ...primaryBtn, marginTop: 22,
                              opacity: (!vlanInput || ensuringBairro) ? 0.5 : 1 }}>
              {ensuringBairro ? "Registrando..." : "Continuar"}
            </button>
          </div>
        )}

        {/* === CTO Steps 4-7 === */}
        {step === 4 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Quantas portas tem essa CTO?
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              Selecione a capacidade física.
            </p>
            {[4, 8, 16].map((cap) => (
              <button key={cap} data-testid={`cto-cap-${cap}`}
                      onClick={() => setCapacity(cap)}
                      style={optionCard(capacity === cap)}>
                <span style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <span style={{
                    width: 36, height: 36, borderRadius: 8,
                    background: capacity === cap ? "#ddd6fe" : "#f1f5f9",
                    color: C_PRIMARY, display: "grid", placeItems: "center",
                    fontSize: 18, fontWeight: 800,
                  }}>▦</span>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>{cap} portas</span>
                </span>
                <span style={checkBox(capacity === cap)}>
                  {capacity === cap ? "✓" : ""}
                </span>
              </button>
            ))}
            <div style={{ marginTop: 18 }}>
              <button data-testid="cto-step4-continue"
                      disabled={!capacity} onClick={() => setStep(5)}
                      style={{ ...primaryBtn, opacity: !capacity ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {step === 5 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Tipo de rede
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              Selecione o tipo de rede utilizada nesta CTO.
            </p>
            {[
              { v: "balanceada", l: "Rede balanceada",
                d: "Sinal distribuído de forma equilibrada entre as portas.",
                icon: "️" },
              { v: "desbalanceada", l: "Rede desbalanceada",
                d: "Sinal distribuído de forma desbalanceada entre as portas.",
                icon: "️" },
            ].map((opt) => (
              <button key={opt.v} data-testid={`cto-net-${opt.v.slice(0,3)}`}
                      onClick={() => setNetworkType(opt.v)}
                      style={{ ...optionCard(networkType === opt.v),
                                alignItems: "flex-start" }}>
                <span style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <span style={{
                    width: 38, height: 38, borderRadius: 8,
                    background: networkType === opt.v ? "#ddd6fe" : "#f1f5f9",
                    display: "grid", placeItems: "center", fontSize: 18,
                    flexShrink: 0,
                  }}>{opt.icon}</span>
                  <span>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{opt.l}</div>
                    <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4,
                                     lineHeight: 1.4 }}>{opt.d}</div>
                  </span>
                </span>
                <span style={checkBox(networkType === opt.v)}>
                  {networkType === opt.v ? "✓" : ""}
                </span>
              </button>
            ))}
            <div style={{ marginTop: 18 }}>
              <button data-testid="cto-step5-continue"
                      disabled={!networkType} onClick={() => setStep(6)}
                      style={{ ...primaryBtn, opacity: !networkType ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {step === 6 && (() => {
          // iter211ar — opções de splitter condicionadas ao tipo de rede:
          // • balanceada: 1:2, 1:4, 1:8, 1:16
          // • desbalanceada: 5/95, 10/90, 20/80, 35/65, 50/50
          // Em ambos os casos: "Outro" e "Sem splitter".
          const balOpts = ["1:2", "1:4", "1:8", "1:16"];
          const desbOpts = ["5/95", "10/90", "20/80", "35/65", "50/50"];
          const baseOpts = networkType === "desbalanceada" ? desbOpts : balOpts;
          const opts = [...baseOpts, "Outro", "Sem splitter"];
          return (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              {networkType === "desbalanceada"
                ? "Qual é o splitter de balanceamento?"
                : "Qual é o splitter desta CTO?"}
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              {networkType === "desbalanceada"
                ? "Selecione a razão de divisão usada na rede desbalanceada."
                : "Selecione o splitter padrão. Se não houver, use \"Sem splitter\"."}
            </p>
            {opts.map((s) => (
              <button key={s} data-testid={`cto-splitter-${s.replace(/[^a-z0-9]/gi,'_')}`}
                      onClick={() => setSplitter(s)}
                      style={optionCard(splitter === s)}>
                <span style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <span style={{
                    width: 36, height: 36, borderRadius: 8,
                    background: splitter === s ? "#ddd6fe" : "#f1f5f9",
                    color: C_PRIMARY, display: "grid", placeItems: "center",
                    fontSize: 18, fontWeight: 800,
                  }}>{s.startsWith("Sem") || s === "Outro" ? "—" : "▣"}</span>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>{s}</span>
                </span>
                <span style={checkBox(splitter === s)}>
                  {splitter === s ? "✓" : ""}
                </span>
              </button>
            ))}
            <div style={{ marginTop: 18 }}>
              <button data-testid="cto-step6-continue"
                      disabled={!splitter} onClick={() => setStep(7)}
                      style={{ ...primaryBtn, opacity: !splitter ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
          );
        })()}

        {step === 7 && (() => {
          // iter211ba — VLAN agora é digitada.
          // iter216a — Se a VLAN digitada não tem bairro mapeado, NÃO bloqueia
          // mais o fluxo. A gente registra automaticamente ao clicar em
          // Continuar (ensure-from-field), usando o bairro detectado pelo GPS.
          const vlanNum = parseInt(typedVlan || bairroSelected?.vlan || 0, 10);
          const ctoNum = parseInt(ctoNumber, 10);
          const previewName = (vlanNum > 0 && ctoNum > 0)
            ? `CTO_${vlanNum}_${String(ctoNum).padStart(4, "0")}`
            : "";
          const vlanInputVal = bairroSelected?.vlan ? String(bairroSelected.vlan) : "";
          const vlanTyped = (typedVlan == null) ? vlanInputVal : typedVlan;
          const vlanTypedNum = parseInt(vlanTyped, 10);
          const vlanMatchedBairro = bairros.find((b) => Number(b.vlan) === vlanTypedNum);
          // VLAN nova (>= 2): vai ser auto-cadastrada — feedback informativo.
          const vlanWillBeCreated = vlanTyped && !vlanMatchedBairro
            && vlanTypedNum >= 2 && vlanTypedNum <= 4094;
          return (
          <div>
            {/* iter211at — Tela enxuta: só VLAN + Nº CTO + preview.
                iter211ba — VLAN passou a ser INPUT digitado. */}
            <label style={labelStyle}>
              VLAN da CTO <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <input
              data-testid="cto-vlan-input"
              type="number" inputMode="numeric" min="1" max="4094"
              value={vlanTyped}
              placeholder="Digite a VLAN (ex: 301)"
              onChange={(e) => {
                const v = e.target.value.replace(/[^0-9]/g, "");
                setTypedVlan(v);
                // Se bater com um bairro cadastrado, ativa
                const b = bairros.find((x) => Number(x.vlan) === parseInt(v, 10));
                if (b) {
                  setBairroSelected(b);
                  setCtoNumber("");
                } else {
                  setBairroSelected(null);
                }
              }}
              style={{ ...inputBase, fontSize: 22, fontWeight: 800,
                       fontFamily: "monospace", letterSpacing: 1 }} />
            {/* iter211bb — Indicador da sugestão automática de VLAN via GPS/OLT */}
            {gpsVlanSuggestion && gpsVlanSuggestion.matched_olt && (
              <div data-testid="cto-vlan-gps-hint" style={{
                marginTop: 6, padding: "8px 10px", borderRadius: 8,
                background: "#ecfdf5", border: "1px solid #6ee7b7",
                fontSize: 11, color: "#065f46",
              }}>
                OLT detectada pelo GPS: <strong>{gpsVlanSuggestion.matched_olt}</strong>
                {gpsVlanSuggestion.bairro_match
                  ? ` · Bairro ${gpsVlanSuggestion.bairro_match.bairro} (VLAN ${gpsVlanSuggestion.suggested_vlan})`
                  : ` · sem bairro cadastrado nessa OLT — usando VLAN 1`}
              </div>
            )}
            {gpsVlanSuggestion && !gpsVlanSuggestion.matched_olt && (
              <div data-testid="cto-vlan-gps-nomatch" style={{
                marginTop: 6, padding: "8px 10px", borderRadius: 8,
                background: "#fef3c7", border: "1px solid #fcd34d",
                fontSize: 11, color: "#78350f",
              }}>
                ℹ️ Localização não atendida por nenhuma SmartOLT — usando VLAN 1.
                Você pode editar manualmente.
              </div>
            )}
            {vlanWillBeCreated && (
              <div data-testid="cto-vlan-autocreate-hint" style={{
                marginTop: 6, padding: "8px 10px", borderRadius: 8,
                background: "#ecfdf5", border: "1px solid #6ee7b7",
                fontSize: 11.5, color: "#065f46", fontWeight: 600,
                lineHeight: 1.45,
              }}>
                ✨ VLAN {vlanTypedNum} ainda não existe — vou cadastrá-la
                automaticamente no bairro <b>{address.bairro_detected || "atual"}</b>{" "}
                quando você clicar em Continuar.
              </div>
            )}

            <label style={{ ...labelStyle, marginTop: 22 }}>
              Nº da CTO <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <input data-testid="cto-sequence-number"
              type="number" inputMode="numeric" min="1" max="9999"
              value={ctoNumber}
              onChange={(e) => {
                const v = e.target.value.replace(/[^0-9]/g, "");
                setCtoNumber(v);
                const n = parseInt(v, 10);
                if (n > 0 && bairroSelected?.vlan) {
                  setSuggested({
                    name: `CTO_${bairroSelected.vlan}_${String(n).padStart(4, "0")}`,
                    number: n,
                  });
                }
              }}
              style={{ ...inputBase, fontSize: 22, fontWeight: 800,
                       fontFamily: "monospace", letterSpacing: 1,
                       textAlign: "center" }}
              placeholder="Digite o número" />

            {/* iter211ba — Preview da nomenclatura final, antes do Continuar */}
            {previewName && (
              <div data-testid="cto-name-preview" style={{
                marginTop: 18, padding: "12px 14px", borderRadius: 10,
                background: "linear-gradient(135deg,#eff6ff,#dbeafe)",
                border: "1px solid #93c5fd",
              }}>
                <div style={{ fontSize: 10, color: "#1e40af", fontWeight: 800,
                                textTransform: "uppercase", letterSpacing: 0.6,
                                marginBottom: 4 }}>
                  Nomenclatura final
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: "#0c4a6e",
                                fontFamily: "monospace", letterSpacing: 1 }}>
                  {previewName}
                </div>
              </div>
            )}

            <div style={{ marginTop: 24 }}>
              <button data-testid="cto-step7-continue"
                      onClick={async () => {
                        // iter216a — Auto-cadastro de VLAN quando o
                        // técnico digita uma VLAN que ainda não existe.
                        if (!vlanMatchedBairro && vlanTypedNum >= 2
                            && vlanTypedNum <= 4094) {
                          try {
                            setEnsuringBairro(true);
                            const r = await useApi.ensureBairro({
                              bairro: address.bairro_detected || "Bairro " + vlanTypedNum,
                              vlan: vlanTypedNum,
                              cidade: address.cidade_detected || "",
                              estado: address.estado_detected || "",
                            });
                            setBairroSelected(r.bairro);
                            if (r.created) {
                              setBairros((prev) => [...prev, r.bairro]);
                            }
                          } catch (e) {
                            setError(e?.response?.data?.detail
                              || "Falha ao cadastrar a VLAN. Tente de novo.");
                            setEnsuringBairro(false);
                            return;
                          }
                          setEnsuringBairro(false);
                        }
                        setStep(8);
                      }}
                      disabled={ensuringBairro || !ctoNumber || ctoNum < 1
                        || !(vlanTypedNum >= 1 && vlanTypedNum <= 4094)}
                      style={{ ...primaryBtn,
                               opacity: (ensuringBairro || !ctoNumber
                                          || ctoNum < 1
                                          || !(vlanTypedNum >= 1 && vlanTypedNum <= 4094))
                                          ? 0.5 : 1 }}>
                {ensuringBairro
                  ? "Cadastrando VLAN..."
                  : (vlanWillBeCreated ? "Cadastrar VLAN e continuar" : "Continuar")}
              </button>
            </div>
          </div>
          );
        })()}

        {/* === CTO Step 8 — Summary === */}
        {step === 8 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3, textAlign: "center" }}>
              Resumo do cadastro
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18,
                          textAlign: "center" }}>
              Confira os dados antes de salvar
            </p>

            <div style={{ ...cardBase, padding: "4px 0" }}>
              <SummaryRow icon="" label="Endereço de referência"
                value={`${address.endereco}, ${address.numero}${address.referencia ? "\n" + address.referencia : ""}`} />
              <SummaryRow icon="" label="Bairro" value={bairroSelected?.bairro} />
              <SummaryRow icon="" label="Posição GPS"
                value={gps.lat ? `${gps.lat.toFixed(6)}, ${gps.lng.toFixed(6)}` : "—"} />
              <SummaryRow icon="" label="Nomenclatura da CTO"
                value={suggested.name} highlight />
              <SummaryRow icon="▦" label="Quantidade de portas"
                value={`${capacity} portas`} />
              <SummaryRow icon="" label="Tipo de rede"
                value={networkType === "balanceada" ? "Rede balanceada" : "Rede desbalanceada"} />
              <SummaryRow icon="" label="Splitter"
                value={splitter || "—"} />
              <SummaryRow icon="" label="Nº da caixa"
                value={boxNumber.trim() || "Não informado"}
                last={!photo} />
              {photo && (
                <div style={{ padding: "12px 14px",
                                 borderTop: `1px solid ${C_BORDER}` }}>
                  <div style={{ fontSize: 10, color: C_MUTED, fontWeight: 700,
                                   textTransform: "uppercase", letterSpacing: 0.5,
                                   marginBottom: 8 }}>Foto da CTO</div>
                  <img src={photo} alt="Foto CTO"
                    style={{ width: "100%", borderRadius: 10,
                              border: `1px solid ${C_BORDER}`,
                              maxHeight: 200, objectFit: "cover" }} />
                </div>
              )}
            </div>

            <OrphanLinkSuggestionCard
              items={orphanNear}
              checked={linkOrphans}
              onToggle={setLinkOrphans} />

            <FinalButtons busy={busy} submit={submit}
                onBack={() => setStep(7)} />
          </div>
        )}

        {/* === CE Step: Bandejas === */}
        {step === "ce-bandejas" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Quantas bandejas/emendas tem esta CE?
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              Capacidade física da caixa de emenda óptica.
            </p>
            {[4, 8, 12, 24, 48].map((cap) => (
              <button key={cap} data-testid={`ce-bandejas-${cap}`}
                      onClick={() => setBandejasTotal(cap)}
                      style={optionCard(bandejasTotal === cap)}>
                <span style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <span style={{
                    width: 36, height: 36, borderRadius: 8,
                    background: bandejasTotal === cap ? "#ddd6fe" : "#f1f5f9",
                    color: C_PRIMARY, display: "grid", placeItems: "center",
                    fontSize: 18, fontWeight: 800,
                  }}>▤</span>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>
                    {cap} {cap === 1 ? "emenda" : "emendas"}
                  </span>
                </span>
                <span style={checkBox(bandejasTotal === cap)}>
                  {bandejasTotal === cap ? "✓" : ""}
                </span>
              </button>
            ))}
            <div style={{ marginTop: 18 }}>
              <button data-testid="ce-bandejas-continue"
                      disabled={!bandejasTotal} onClick={() => setStep("ce-tipo")}
                      style={{ ...primaryBtn, opacity: !bandejasTotal ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === CE Step: Install Type === */}
        {step === "ce-tipo" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Tipo de instalação da CE
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              Selecione onde a caixa está fisicamente instalada.
            </p>
            {[
              { v: "aerea", l: "Aérea",
                d: "Instalada no poste, suspensa pelo cordoalha do cabo.",
                icon: "" },
              { v: "subterranea", l: "Subterrânea",
                d: "Direcional/enterrada (dutos plásticos no solo).",
                icon: "️" },
              { v: "camara", l: "Câmara/Caixa de passagem",
                d: "Em câmara de inspeção concreto/PVC (handhole/manhole).",
                icon: "️" },
            ].map((opt) => (
              <button key={opt.v} data-testid={`ce-tipo-${opt.v}`}
                      onClick={() => setCeInstallType(opt.v)}
                      style={{ ...optionCard(ceInstallType === opt.v),
                                alignItems: "flex-start" }}>
                <span style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <span style={{
                    width: 38, height: 38, borderRadius: 8,
                    background: ceInstallType === opt.v ? "#ede9fe" : "#f1f5f9",
                    display: "grid", placeItems: "center", fontSize: 18,
                    flexShrink: 0,
                  }}>{opt.icon}</span>
                  <span>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{opt.l}</div>
                    <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4,
                                     lineHeight: 1.4 }}>{opt.d}</div>
                  </span>
                </span>
                <span style={checkBox(ceInstallType === opt.v)}>
                  {ceInstallType === opt.v ? "✓" : ""}
                </span>
              </button>
            ))}

            <label style={labelStyle}>Foto interna (bandejas) — recomendado</label>
            <input ref={fileInputExtraRef} type="file" accept="image/*"
              capture="environment" onChange={onPhotoExtraChange}
              style={{ display: "none" }} data-testid="ce-photo-interna-input" />
            {photoExtra ? (
              <div style={{
                position: "relative", borderRadius: 12,
                overflow: "hidden", border: `1.5px solid ${C_BORDER}`,
                marginBottom: 6,
              }}>
                <img src={photoExtra} alt="Bandejas"
                  data-testid="ce-photo-interna-preview"
                  style={{ width: "100%", display: "block",
                            maxHeight: 220, objectFit: "cover" }} />
                <button data-testid="ce-photo-interna-remove"
                  onClick={() => { setPhotoExtra(null);
                                     if (fileInputExtraRef.current) fileInputExtraRef.current.value = ""; }}
                  style={{
                    position: "absolute", top: 8, right: 8,
                    background: "rgba(0,0,0,0.6)", color: "#fff",
                    border: 0, borderRadius: "50%", width: 28, height: 28,
                    fontSize: 14, fontWeight: 800, cursor: "pointer",
                  }}>×</button>
              </div>
            ) : (
              <button data-testid="ce-photo-interna-btn"
                      onClick={() => fileInputExtraRef.current?.click()}
                      style={{
                        ...inputBase, display: "flex", alignItems: "center",
                        justifyContent: "space-between", cursor: "pointer",
                        padding: "14px 14px",
                      }}>
                <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 20 }}></span>
                  <span style={{ color: C_TEXT, fontWeight: 600 }}>
                    Foto da bandeja aberta
                  </span>
                </span>
                <span style={{ color: C_MUTED, fontSize: 20 }}>›</span>
              </button>
            )}

            <div style={{ marginTop: 18 }}>
              <button data-testid="ce-tipo-continue"
                      disabled={!ceInstallType}
                      onClick={() => setStep("ce-resumo")}
                      style={{ ...primaryBtn, opacity: !ceInstallType ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === CE Step: Resumo === */}
        {step === "ce-resumo" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3, textAlign: "center" }}>
              Resumo da CE
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18,
                          textAlign: "center" }}>
              Confira os dados antes de salvar
            </p>

            <div style={{ ...cardBase, padding: "4px 0" }}>
              <SummaryRow icon="" label="Endereço"
                value={`${address.endereco}, ${address.numero}${address.referencia ? "\n" + address.referencia : ""}`} />
              <SummaryRow icon="" label="Bairro" value={bairroSelected?.bairro} />
              <SummaryRow icon="" label="Posição GPS"
                value={gps.lat ? `${gps.lat.toFixed(6)}, ${gps.lng.toFixed(6)}` : "—"} />
              <SummaryRow icon="" label="Nomenclatura"
                value={suggested.name} highlight />
              <SummaryRow icon="▤" label="Bandejas/Emendas"
                value={`${bandejasTotal} emendas`} />
              <SummaryRow icon="️" label="Tipo de instalação"
                value={({ aerea: "Aérea", subterranea: "Subterrânea",
                            camara: "Câmara de passagem" })[ceInstallType] || "—"}
                last={!photo && !photoExtra} />
              {(photo || photoExtra) && (
                <div style={{ padding: "12px 14px",
                                 borderTop: `1px solid ${C_BORDER}` }}>
                  <div style={{ fontSize: 10, color: C_MUTED, fontWeight: 700,
                                   textTransform: "uppercase", letterSpacing: 0.5,
                                   marginBottom: 8 }}>Fotos</div>
                  <div style={{ display: "grid",
                                   gridTemplateColumns: photo && photoExtra ? "1fr 1fr" : "1fr",
                                   gap: 8 }}>
                    {photo && (
                      <img src={photo} alt="CE externa"
                        style={{ width: "100%", borderRadius: 10,
                                  border: `1px solid ${C_BORDER}`,
                                  maxHeight: 180, objectFit: "cover" }} />
                    )}
                    {photoExtra && (
                      <img src={photoExtra} alt="Bandejas"
                        style={{ width: "100%", borderRadius: 10,
                                  border: `1px solid ${C_BORDER}`,
                                  maxHeight: 180, objectFit: "cover" }} />
                    )}
                  </div>
                </div>
              )}
            </div>

            <OrphanLinkSuggestionCard
              items={orphanNear}
              checked={linkOrphans}
              onToggle={setLinkOrphans} />

            <FinalButtons busy={busy} submit={submit}
                onBack={() => setStep("ce-tipo")} />
          </div>
        )}


        {/* === CABO Step: Lançar (iter186 — consolidado: trajeto + vínculo opcional) === */}
        {step === "cabo-lancar" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Lançar cabo
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 14,
                            lineHeight: 1.5 }}>
              Marque o <strong>início</strong> e o <strong>fim</strong> do cabo.
              {" "}O sistema completa o trajeto pelas ruas (modo Auto), ou você
              {" "}pode gravar com GPS andando / desenhar manualmente.
              {" "}<em>+ {slackCfg.slack_start_m}m início e
              {" "}{slackCfg.slack_end_m}m fim somados automaticamente.</em>
            </p>

            <CableTrackRecorder
              originItem={caboFrom}
              destItem={caboTo}
              slackCfg={slackCfg}
              value={cableTrack}
              onChange={setCableTrack}
              collabId={collabId} />

            {/* Vínculo opcional CTO/CE — pode ser feito agora ou depois */}
            <div style={{ marginTop: 16, padding: 12, background: "#f8fafc",
                              borderRadius: 12, border: `1px dashed ${C_BORDER}` }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: C_TEXT,
                                marginBottom: 8 }}>
                Vínculos (opcional — pode fazer depois)
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button data-testid="cabo-lancar-link-origem"
                          onClick={() => setStep("cabo-origem")}
                          style={{
                            flex: "1 1 0",
                            minWidth: 130,
                            padding: "10px 12px", borderRadius: 10,
                            border: caboFrom
                              ? "1px solid #10b981" : `1px solid ${C_BORDER}`,
                            background: caboFrom ? "#ecfdf5" : "#fff",
                            fontWeight: 700, color: C_TEXT, cursor: "pointer",
                            fontSize: 13, textAlign: "left",
                          }}>
                  {caboFrom ? (
                    <>✓ Origem: <strong>{caboFrom.name}</strong></>
                  ) : (
                    <>Vincular Origem</>
                  )}
                </button>
                <button data-testid="cabo-lancar-link-destino"
                          onClick={() => setStep("cabo-destino")}
                          style={{
                            flex: "1 1 0",
                            minWidth: 130,
                            padding: "10px 12px", borderRadius: 10,
                            border: caboTo
                              ? "1px solid #10b981" : `1px solid ${C_BORDER}`,
                            background: caboTo ? "#ecfdf5" : "#fff",
                            fontWeight: 700, color: C_TEXT, cursor: "pointer",
                            fontSize: 13, textAlign: "left",
                          }}>
                  {caboTo ? (
                    <>✓ Destino: <strong>{caboTo.name}</strong></>
                  ) : (
                    <>Vincular Destino</>
                  )}
                </button>
              </div>
              {(!caboFrom || !caboTo) && (
                <div style={{ marginTop: 8, fontSize: 11, color: "#92400e" }}>
                  ️ Cabo ficará como <strong>“cabo solto”</strong> até as
                  pontas serem vinculadas (linha laranja tracejada no mapa).
                </div>
              )}
            </div>

            <div style={{ marginTop: 18 }}>
              <button data-testid="cabo-lancar-continue"
                         onClick={() => setStep("cabo-config")}
                         disabled={!cableTrack
                              || (cableTrack.points || []).length < 2}
                         style={{
                           ...primaryBtn,
                           opacity: (!cableTrack
                                || (cableTrack.points || []).length < 2)
                              ? 0.5 : 1,
                         }}>
                Continuar
              </button>
            </div>
          </div>
        )}


        {/* === CABO Step: Origem === */}
        {step === "cabo-origem" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Ponto de origem do cabo
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 14 }}>
              Selecione a CTO ou CE de onde o cabo SAI.
            </p>
            <ElementMapPicker testid="cabo-origem-picker"
              items={elementsList} loading={elementsLoading}
              selected={caboFrom} onPick={setCaboFrom} />

            <div style={{ marginTop: 18 }}>
              <button data-testid="cabo-origem-continue"
                      disabled={!caboFrom}
                      onClick={() => setStep("cabo-lancar")}
                      style={{ ...primaryBtn, opacity: !caboFrom ? 0.5 : 1 }}>
                Voltar ao lançamento
              </button>
            </div>
          </div>
        )}

        {/* === CABO Step: Destino === */}
        {step === "cabo-destino" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Ponto de destino do cabo
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 14 }}>
              Selecione a CTO ou CE onde o cabo CHEGA.
              <br />
              Origem: <strong>{caboFrom?.name}</strong>
            </p>
            <ElementMapPicker testid="cabo-destino-picker"
              items={elementsList} loading={elementsLoading}
              selected={caboTo} onPick={setCaboTo}
              originItem={caboFrom} excludeId={caboFrom?.id} />

            <div style={{ marginTop: 18 }}>
              <button data-testid="cabo-destino-continue"
                      disabled={!caboTo}
                      onClick={() => setStep("cabo-lancar")}
                      style={{ ...primaryBtn, opacity: !caboTo ? 0.5 : 1 }}>
                Voltar ao lançamento
              </button>
            </div>
          </div>
        )}

        {/* === CABO Step: Trajeto (iter186) === */}
        {step === "cabo-trajeto" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Lançar trecho do cabo
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 14 }}>
              <strong>{caboFrom?.name}</strong> → <strong>{caboTo?.name}</strong>
              <br />
              Grave o trajeto andando com GPS ou desenhe os waypoints
              {" "}manualmente no mapa.
              {" "}<em>+ {slackCfg.slack_start_m}m no início e
              {" "}{slackCfg.slack_end_m}m no fim</em> serão somados
              {" "}automaticamente.
            </p>

            <CableTrackRecorder
              originItem={caboFrom}
              destItem={caboTo}
              slackCfg={slackCfg}
              value={cableTrack}
              onChange={setCableTrack} />

            <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
              <button data-testid="cabo-trajeto-skip"
                         onClick={() => setStep("cabo-config")}
                         style={{
                           flex: 1, padding: "14px 12px", borderRadius: 10,
                           border: `1px solid ${C_BORDER}`, background: "#fff",
                           fontWeight: 700, color: C_TEXT, cursor: "pointer",
                           fontSize: 14,
                         }}>
                Pular (usar reta + sobras)
              </button>
              <button data-testid="cabo-trajeto-continue"
                         onClick={() => setStep("cabo-config")}
                         disabled={!cableTrack
                              || (cableTrack.points || []).length < 2}
                         style={{
                           ...primaryBtn, flex: 1.4,
                           opacity: (!cableTrack
                                || (cableTrack.points || []).length < 2)
                              ? 0.5 : 1,
                         }}>
                Continuar
              </button>
            </div>
          </div>
        )}


        {/* === CABO Step: Config === */}
        {step === "cabo-config" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Configuração do cabo
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18 }}>
              <strong>{caboFrom?.name}</strong> → <strong>{caboTo?.name}</strong>
            </p>

            {/* iter183 — Resumo da rota OSRM */}
            <div data-testid="cabo-route-summary" style={{
              padding: "10px 12px", background: "#f0f9ff",
              border: `1px solid #bae6fd`, borderRadius: 10, marginBottom: 16,
            }}>
              <div style={{ fontSize: 10, color: "#0369a1", fontWeight: 700,
                              textTransform: "uppercase", letterSpacing: 0.5,
                              marginBottom: 4 }}>
                Trajeto calculado
              </div>
              {routingCable && (
                <div style={{ fontSize: 13, color: "#64748b" }}>
                  Calculando rota pela rua…
                </div>
              )}
              {!routingCable && cableRoute && (
                <div style={{ fontSize: 13, color: "#0c4a6e", lineHeight: 1.5 }}>
                  <div><strong>Trajeto OSRM:</strong> {(cableRoute.distance_m || 0).toFixed(0)} m</div>
                  <div><strong>+ Margem (sobra):</strong> {extraMargin} m
                    ({Math.round(extraMargin/2)}m × 2 pontas)</div>
                  <div style={{ marginTop: 4, fontWeight: 800 }}>
                    Total: {((cableRoute.distance_m || 0) + extraMargin).toFixed(0)} m
                  </div>
                  {cableRoute.source === "haversine_fallback" && (
                    <div style={{ fontSize: 10, color: "#a16207", marginTop: 4 }}>
                      ️ OSRM offline · usando linha reta como aproximação
                    </div>
                  )}
                </div>
              )}
              {!routingCable && !cableRoute && (
                <div style={{ fontSize: 12, color: "#dc2626" }}>
                  Pontos de origem/destino sem GPS. Não foi possível rotear.
                </div>
              )}
            </div>

            <label style={labelStyle}>
              FO (quantidade de fibras) <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {[4, 6, 8, 12, 24, 36, 48, 72, 96, 144].map((f) => (
                <button key={f} data-testid={`cabo-fo-${f}`}
                        onClick={() => { setFoCount(f); setFibrasTotal(f); }}
                        style={chip(foCount === f)}>
                  {f} FO
                </button>
              ))}
            </div>

            <label style={labelStyle}>Marca do cabo</label>
            <input data-testid="cabo-marca" style={inputBase}
              value={cableBrand}
              onChange={(e) => setCableBrand(e.target.value)}
              placeholder="Furukawa, Prysmian, Optitech…" />

            <label style={labelStyle}>Nº de série / lote</label>
            <input data-testid="cabo-ns" style={inputBase}
              value={cableSerial}
              onChange={(e) => setCableSerial(e.target.value)}
              placeholder="NS / lote do fabricante" />

            <label style={labelStyle}>
              Margem de sobra total (metros)
            </label>
            <input data-testid="cabo-margin" type="number" min="0" max="200"
              step="2" style={inputBase}
              value={extraMargin}
              onChange={(e) => setExtraMargin(Math.max(0, parseInt(e.target.value || "0", 10)))}
              placeholder="20" />
            <div style={{ fontSize: 10, color: C_MUTED, marginTop: -4,
                            marginBottom: 14 }}>
              Padrão: 10m em cada ponta (CE/CTO) = 20m total
            </div>

            <label style={labelStyle}>Fibras ocupadas (opcional)</label>
            <input data-testid="cabo-fibras-ocupadas"
              type="number" inputMode="numeric" min="0"
              max={fibrasTotal || undefined}
              value={fibrasOcupadas} style={inputBase}
              onChange={(e) => setFibrasOcupadas(
                Math.max(0, parseInt(e.target.value || "0", 10) || 0))}
              placeholder="0" />

            <label style={labelStyle}>Tipo de cabo</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {[
                { v: "drop", l: "Drop", d: "Lance até o cliente final (last mile)." },
                { v: "distribuicao", l: "Distribuição",
                  d: "CTO ↔ CTO ou CE ↔ CTO dentro do bairro." },
                { v: "backbone", l: "Backbone",
                  d: "Tronco entre cabines/bairros (alta capacidade)." },
              ].map((opt) => (
                <button key={opt.v} data-testid={`cabo-tipo-${opt.v}`}
                        onClick={() => setCableType(opt.v)}
                        style={{ ...optionCard(cableType === opt.v),
                                  alignItems: "flex-start" }}>
                  <span style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{opt.l}</div>
                    <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4,
                                     lineHeight: 1.4 }}>{opt.d}</div>
                  </span>
                  <span style={checkBox(cableType === opt.v)}>
                    {cableType === opt.v ? "✓" : ""}
                  </span>
                </button>
              ))}
            </div>

            <label style={labelStyle}>Foto da plaqueta (recomendado)</label>
            <input ref={fileInputExtraRef} type="file" accept="image/*"
              capture="environment" onChange={onPhotoExtraChange}
              style={{ display: "none" }} data-testid="cabo-photo-input" />
            {photoExtra ? (
              <div style={{
                position: "relative", borderRadius: 12,
                overflow: "hidden", border: `1.5px solid ${C_BORDER}`,
                marginBottom: 6,
              }}>
                <img src={photoExtra} alt="Plaqueta"
                  data-testid="cabo-photo-preview"
                  style={{ width: "100%", display: "block",
                            maxHeight: 220, objectFit: "cover" }} />
                <button data-testid="cabo-photo-remove"
                  onClick={() => { setPhotoExtra(null);
                                     if (fileInputExtraRef.current) fileInputExtraRef.current.value = ""; }}
                  style={{
                    position: "absolute", top: 8, right: 8,
                    background: "rgba(0,0,0,0.6)", color: "#fff",
                    border: 0, borderRadius: "50%", width: 28, height: 28,
                    fontSize: 14, fontWeight: 800, cursor: "pointer",
                  }}>×</button>
              </div>
            ) : (
              <button data-testid="cabo-photo-btn"
                      onClick={() => fileInputExtraRef.current?.click()}
                      style={{
                        ...inputBase, display: "flex", alignItems: "center",
                        justifyContent: "space-between", cursor: "pointer",
                        padding: "14px 14px",
                      }}>
                <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 20 }}></span>
                  <span style={{ color: C_TEXT, fontWeight: 600 }}>
                    Foto da plaqueta de identificação
                  </span>
                </span>
                <span style={{ color: C_MUTED, fontSize: 20 }}>›</span>
              </button>
            )}

            <div style={{ marginTop: 18 }}>
              <button data-testid="cabo-config-continue"
                      disabled={!foCount || !cableType}
                      onClick={() => setStep("cabo-resumo")}
                      style={{ ...primaryBtn,
                                opacity: (!foCount || !cableType) ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === CABO Step: Resumo === */}
        {step === "cabo-resumo" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3, textAlign: "center" }}>
              Resumo do cabo
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18,
                          textAlign: "center" }}>
              Confira os dados antes de salvar
            </p>

            <div style={{ ...cardBase, padding: "4px 0" }}>
              <SummaryRow icon="" label="Nomenclatura"
                value={suggested.name} highlight />
              <SummaryRow icon="➡️" label="De" value={caboFrom?.name} />
              <SummaryRow icon="" label="Para" value={caboTo?.name} />
              <SummaryRow icon="" label="Capacidade de fibras"
                value={`${fibrasTotal} FO`} />
              <SummaryRow icon="" label="Fibras ocupadas"
                value={`${fibrasOcupadas || 0} / ${fibrasTotal || 0}`} />
              <SummaryRow icon="" label="Tipo de cabo"
                value={({ drop: "Drop",
                            distribuicao: "Distribuição",
                            backbone: "Backbone" })[cableType] || "—"}
                last={!photoExtra} />
              {photoExtra && (
                <div style={{ padding: "12px 14px",
                                 borderTop: `1px solid ${C_BORDER}` }}>
                  <div style={{ fontSize: 10, color: C_MUTED, fontWeight: 700,
                                   textTransform: "uppercase", letterSpacing: 0.5,
                                   marginBottom: 8 }}>
                    Foto da plaqueta
                  </div>
                  <img src={photoExtra} alt="Plaqueta"
                    style={{ width: "100%", borderRadius: 10,
                              border: `1px solid ${C_BORDER}`,
                              maxHeight: 200, objectFit: "cover" }} />
                </div>
              )}
            </div>

            <FinalButtons busy={busy} submit={submit}
                onBack={() => setStep("cabo-config")} />
          </div>
        )}

      </div>
    </div>
  );
}

function FinalButtons({ busy, submit, onBack }) {
  return (
    <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 10 }}>
      <button data-testid="cto-summary-submit" style={accentBtn}
              disabled={busy} onClick={submit}>
        {busy ? "Salvando..." : "Salvar cadastro"}
      </button>
      <button data-testid="cto-summary-back" onClick={onBack}
              style={{
                ...primaryBtn,
                background: "#fff", color: C_TEXT,
                border: `1.5px solid ${C_BORDER}`,
                boxShadow: "none",
              }}>
        Voltar e editar
      </button>
    </div>
  );
}

function SummaryRow({ icon, label, value, highlight, last }) {
  return (
    <div style={{
      display: "flex", gap: 12, padding: "12px 14px",
      borderBottom: last ? "none" : `1px solid ${C_BORDER}`,
      background: highlight ? C_PRIMARY_LIGHT : "transparent",
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: highlight ? "#ddd6fe" : "#f1f5f9",
        display: "grid", placeItems: "center", fontSize: 14, flexShrink: 0,
      }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 10, color: highlight ? "#5b21b6" : C_MUTED,
                       textTransform: "uppercase", letterSpacing: 0.5,
                       fontWeight: 700, marginBottom: 3 }}>{label}</div>
        <div style={{ fontSize: 14, fontWeight: highlight ? 800 : 600,
                       color: highlight ? C_PRIMARY : C_TEXT,
                       whiteSpace: "pre-line", lineHeight: 1.4 }}>
          {value || "—"}
        </div>
      </div>
    </div>
  );
}


// =============================================================================
// SentinelaPanel — iter180. Painel de feedback da Sentinela IA da foto.
// Renderiza:
//   - estado "analisando" enquanto a IA processa
//   - banner verde quando aprovada
//   - banner amarelo + botão "Abrir chamado" quando condition ∈
//     {quebrada, sem_tampa}
//   - banner vermelho com motivo + botão "Tirar nova foto" quando retake
// =============================================================================
function SentinelaPanel({ checking, result, ticketOpened, onOpenTicket, onRetake }) {
  if (checking) {
    return (
      <div data-testid="sentinela-checking" style={{
        marginTop: 10, padding: "10px 12px", borderRadius: 8,
        background: "#f1f5f9", border: "1px solid #cbd5e1",
        display: "flex", alignItems: "center", gap: 10,
        fontSize: 12, color: "#475569",
      }}>
        <span style={{ fontSize: 16 }}></span>
        <span><strong>Sentinela IA</strong> analisando a foto...</span>
      </div>
    );
  }
  if (!result) return null;

  const action = result.action;
  const palette = action === "approve"
    ? { bg: "#f0fdf4", bd: "#86efac", fg: "#15803d", icon: "✓" }
    : action === "open_ticket"
      ? { bg: "#fffbeb", bd: "#fde68a", fg: "#a16207", icon: "" }
      : { bg: "#fef2f2", bd: "#fca5a5", fg: "#b91c1c", icon: "✕" };
  const score = result.score ?? 0;

  return (
    <div data-testid="sentinela-result" style={{
      marginTop: 10, padding: "10px 12px", borderRadius: 8,
      background: palette.bg, border: `1px solid ${palette.bd}`,
      fontSize: 12.5, color: palette.fg,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start",
                       gap: 10, marginBottom: 6 }}>
        <span style={{ fontSize: 16, lineHeight: 1 }}>{palette.icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, fontSize: 12, marginBottom: 2,
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
            Sentinela IA · {score}/100
          </div>
          <div style={{ lineHeight: 1.4 }}>{result.message}</div>
          {result.vision?.reasoning && (
            <div style={{ marginTop: 4, fontSize: 11, opacity: 0.85 }}>
              IA: {result.vision.reasoning}
            </div>
          )}
        </div>
      </div>

      {action === "retake" && (
        <button data-testid="sentinela-retake-btn"
                onClick={onRetake}
                style={{
                  marginTop: 4, padding: "8px 14px", borderRadius: 8,
                  background: "#b91c1c", color: "#fff", border: 0,
                  fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                  width: "100%",
                }}>
          Tirar nova foto
        </button>
      )}

      {action === "open_ticket" && !ticketOpened && (
        <button data-testid="sentinela-open-ticket-btn"
                onClick={onOpenTicket}
                style={{
                  marginTop: 4, padding: "8px 14px", borderRadius: 8,
                  background: "#a16207", color: "#fff", border: 0,
                  fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                  width: "100%",
                }}>
          Abrir chamado de manutenção
        </button>
      )}

      {action === "open_ticket" && ticketOpened?.ticket_id && (
        <div data-testid="sentinela-ticket-opened"
              style={{
                marginTop: 6, padding: "6px 10px", borderRadius: 6,
                background: "#d1fae5", color: "#065f46",
                fontSize: 11.5, fontWeight: 700,
              }}>
          ✓ Chamado {ticketOpened.ticket_id} aberto. Pode continuar o cadastro.
        </div>
      )}
    </div>
  );
}
