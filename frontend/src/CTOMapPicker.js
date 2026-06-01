/*
CTOMapPicker.js — Mapa "Uber-like" para posicionar a CTO.

UX:
- Tiles OpenStreetMap (rótulos já vêm em português do Brasil para o Brasil).
- Controles e textos da UI em pt-BR (attribution, botões, mensagens).
- Pino da CTO fixo no centro (overlay CSS, não no mapa).
- Indicador "ponto azul pulsante" da posição GPS atual do colaborador
  (separado do pino da CTO, igual ao Google/Uber).
- Botão "Minha localização" recentra no GPS.
- Reverse geocoding via Nominatim com accept-language=pt-BR.
*/
import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  MapContainer, TileLayer, useMap, useMapEvents, CircleMarker, Marker, Tooltip,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { getBestPosition } from "@/utils/geo";

const NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse";
const NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search";

async function reverseGeocode(lat, lng) {
  const url = `${NOMINATIM_URL}?lat=${lat}&lon=${lng}&format=json&zoom=18`
            + `&addressdetails=1&accept-language=pt-BR`;
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!r.ok) throw new Error("Nominatim falhou");
  const j = await r.json();
  // iter183 — Confiamos APENAS no `address.house_number` retornado pela
  // Nominatim. Removemos:
  //   1. regex sobre display_name (capturava o CEP por engano, ex: "57036")
  //   2. busca pelo número mais próximo da mesma rua (retornava nº de
  //      outra quadra como se fosse o do local).
  // Se o pino caiu numa via/área verde sem nº oficial, deixa em branco
  // pra o técnico digitar manualmente — preferimos vazio a um número errado.
  const a = j.address || {};
  // Sanity: descarta valores que pareçam CEP (5+ dígitos contínuos sem
  // hífen, ou padrão XXXXX-XXX). Casa coberta porque Nominatim devolve
  // o nº em `house_number` separado do `postcode`, mas defesa em
  // profundidade não custa.
  if (a.house_number) {
    const hn = String(a.house_number).trim();
    const looksLikeCEP = /^\d{5}(-?\d{3})?$/.test(hn)
                            || (a.postcode && hn === String(a.postcode).replace(/-/g, ""));
    if (looksLikeCEP) {
      delete a.house_number;
    }
  }
  j.address = a;
  return j;
}

function MoveListener({ onIdle }) {
  const map = useMap();
  useMapEvents({
    moveend: () => {
      const c = map.getCenter();
      onIdle?.(c.lat, c.lng);
    },
  });
  return null;
}

/** Recentra o mapa quando lat/lng mudam externamente. */
function Recenter({ lat, lng, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (lat != null && lng != null) {
      map.setView([lat, lng], zoom ?? (map.getZoom() || 18),
                  { animate: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lat, lng]);
  return null;
}

/** Traduz tooltips/aria-label dos botões de zoom para pt-BR. */
function LocalizeZoomControl() {
  const map = useMap();
  useEffect(() => {
    const z = map.zoomControl;
    if (!z) return;
    const inBtn = z._zoomInButton, outBtn = z._zoomOutButton;
    if (inBtn) { inBtn.title = "Aproximar"; inBtn.setAttribute("aria-label", "Aproximar"); }
    if (outBtn) { outBtn.title = "Afastar"; outBtn.setAttribute("aria-label", "Afastar"); }
  }, [map]);
  return null;
}

// Ícone cinza para CTOs já cadastradas (apenas referência visual)
const existingCtoIcon = L.divIcon({
  className: "cto-existing-icon",
  html: `
    <svg width="26" height="34" viewBox="0 0 42 56" xmlns="http://www.w3.org/2000/svg">
      <path d="M21 0 C9.4 0 0 9.4 0 21 c0 15.2 17 31.5 19.4 33.7 a2.2 2.2 0 0 0 3.2 0 C25 52.5 42 36.2 42 21 42 9.4 32.6 0 21 0 Z"
            fill="#64748b" stroke="#fff" stroke-width="1.5" opacity="0.85"/>
      <rect x="10" y="11" width="22" height="18" rx="2"
            fill="#fff" stroke="#334155" stroke-width="1"/>
    </svg>
  `,
  iconSize: [26, 34],
  iconAnchor: [13, 34],
  popupAnchor: [0, -28],
});

export default function CTOMapPicker({
  defaultCenter = [-9.6498, -35.7089],
  initialZoom = 18,
  onMove,
  onError,
  existingCtos = null,  // array de {id, name, lat, lng} OU null = busca sozinho
  collabId = null,      // se passado, busca CTOs públicas via collab_id
  onSelectExistingCto = null,  // callback ao clicar num pin de CTO existente
}) {
  const [center, setCenter] = useState(defaultCenter);
  const [gpsPos, setGpsPos] = useState(null);
  const [gpsReady, setGpsReady] = useState(false);
  const [gpsError, setGpsError] = useState(null);
  const [requestingGps, setRequestingGps] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lastAddr, setLastAddr] = useState(null);
  const [ctosNearby, setCtosNearby] = useState([]);
  const [radiusInfo, setRadiusInfo] = useState(null); // {radius_km, filtered_out, shown}
  const lastReqRef = useRef(0);
  const watchIdRef = useRef(null);
  // iter183 — flag pra carregar CTOs próximas só UMA vez (no primeiro fix
  // de GPS). Sem isso, watchPosition disparava re-fetch a cada 5s.
  const ctosLoadedRef = useRef(false);

  // Carrega CTOs já cadastradas para mostrar no mapa
  useEffect(() => {
    if (existingCtos !== null) {
      setCtosNearby(existingCtos);
      return;
    }
    // Aguarda GPS antes de chamar a API — para que o backend aplique o
    // filtro de raio (5km default) baseado na posição atual do técnico.
    // Sem GPS o backend retorna lista completa (não bloqueia o fluxo).
    if (collabId && !gpsPos) return;
    if (ctosLoadedRef.current) return;
    ctosLoadedRef.current = true;
    // fetch automático via API
    (async () => {
      try {
        const { api } = await import("@/api");
        const params = gpsPos ? { lat: gpsPos.lat, lng: gpsPos.lng } : {};
        const r = collabId
          ? await api.redeIaCtosListPublic?.(collabId, params)
          : await api.redeIaCtosList?.({ status: "approved" });
        const items = (r?.items || []).filter(
          (c) => (c?.gps?.lat || c?.lat) && (c?.gps?.lng || c?.lng),
        );
        setCtosNearby(items);
        if (r?.role_filter_applied) {
          setRadiusInfo({
            radius_km: r.radius_km,
            filtered_out: r.filtered_out_count || 0,
            shown: items.length,
          });
        }
      } catch (e) {
        ctosLoadedRef.current = false;  // permite retry se falhou
      }
    })();
  }, [existingCtos, collabId, gpsPos]);

  // iter182 — Estratégia híbrida GPS + REDE TELEFÔNICA (best practice):
  //  1. dispara request COARSE (rede/wifi/torre) — rápido (~2s)
  //  2. em paralelo, dispara HIGH-ACCURACY (GPS satélite) — preciso
  //     mas pode levar até 15s
  //  3. se a coarse responder antes do GPS, usa-a TEMPORARIAMENTE pra
  //     centrar o mapa; ao GPS chegar, sobrescreve com posição precisa
  //  4. se nenhum chegar em 20s, erro
  // iter183 — usa helper global `getBestPosition`: dispara GPS (high acc) +
  // rede (low acc) em paralelo; resolve com o primeiro fix <= 25m, ou o
  // melhor disponível no timeout. Substitui a implementação manual.
  const requestGps = useCallback(() => {
    return getBestPosition({ cutoffM: 25, timeoutMs: 20000, maxAgeMs: 0 })
      .then((fix) => ({
        coords: {
          latitude: fix.lat,
          longitude: fix.lng,
          accuracy: fix.accuracy,
        },
        _source: fix.source,
        _elapsed_ms: fix.elapsed_ms,
      }));
  }, []);

  // Captura inicial: tenta GPS e centra o mapa nele
  useEffect(() => {
    let cancelled = false;
    setRequestingGps(true);
    requestGps()
      .then((pos) => {
        if (cancelled) return;
        const lat = pos.coords.latitude, lng = pos.coords.longitude;
        setGpsPos({ lat, lng, accuracy: pos.coords.accuracy });
        setCenter([lat, lng]);
        setGpsError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = err?.code === 1
          ? "Permissão de localização negada. Toque em 🔒 na barra do navegador → permita Localização."
          : err?.code === 2
          ? "Sinal de GPS fraco. Vá para uma área aberta e toque em ◎ para tentar de novo."
          : err?.code === 3
          ? "Tempo esgotado ao obter GPS. Toque em ◎ para tentar de novo."
          : `GPS indisponível: ${err?.message || err}`;
        setGpsError(msg);
        onError?.(msg);
      })
      .finally(() => {
        if (!cancelled) {
          setRequestingGps(false);
          setGpsReady(true);
        }
      });

    // watchPosition para atualizar o pontinho azul em tempo real
    if (navigator.geolocation && navigator.geolocation.watchPosition) {
      try {
        watchIdRef.current = navigator.geolocation.watchPosition(
          (pos) => {
            if (cancelled) return;
            setGpsPos({
              lat: pos.coords.latitude,
              lng: pos.coords.longitude,
              accuracy: pos.coords.accuracy,
            });
          },
          () => { /* silent */ },
          { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
        );
      } catch { /* noop */ }
    }
    return () => {
      cancelled = true;
      if (watchIdRef.current != null && navigator.geolocation?.clearWatch) {
        navigator.geolocation.clearWatch(watchIdRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reverse geocode após cada moveend
  // iter183 — NÃO chamamos setCenter aqui. O mapa já está na nova posição
  // após o drag do usuário; setar `center` dispararia o <Recenter> a
  // chamar map.setView() de volta, causando um loop que travava o drag e,
  // em alguns casos, derrubava o wizard pra step 1.
  const handleIdle = useCallback(async (lat, lng) => {
    const reqId = Date.now();
    lastReqRef.current = reqId;
    setLoading(true);
    try {
      const j = await reverseGeocode(lat, lng);
      if (lastReqRef.current !== reqId) return;
      const a = j.address || {};
      const compact = {
        road: a.road || a.pedestrian || a.path || "",
        house_number: a.house_number || "",
        suburb: a.suburb || a.neighbourhood || a.city_district || "",
        city: a.city || a.town || a.village || a.municipality || "",
        state: a.state || "",
        full: j.display_name || "",
      };
      setLastAddr(compact);
      onMove?.({ lat, lng, address: compact });
    } catch (e) {
      onError?.("Endereço não encontrado. Verifique a conexão.");
    } finally {
      if (lastReqRef.current === reqId) setLoading(false);
    }
  }, [onMove, onError]);

  // Primeira identificação após GPS pegar
  useEffect(() => {
    if (gpsReady) handleIdle(center[0], center[1]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gpsReady]);

  // Botão "Minha localização": refaz request e centra
  const recenterOnMe = useCallback(async () => {
    setRequestingGps(true);
    setGpsError(null);
    try {
      const pos = await requestGps();
      const lat = pos.coords.latitude, lng = pos.coords.longitude;
      setGpsPos({ lat, lng, accuracy: pos.coords.accuracy });
      setCenter([lat, lng]);
    } catch (err) {
      const msg = err?.code === 1
        ? "Permissão de localização negada."
        : "Não foi possível obter a localização.";
      setGpsError(msg);
      onError?.(msg);
    } finally {
      setRequestingGps(false);
    }
  }, [requestGps, onError]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}
         data-testid="cto-map-picker">
      <MapContainer
        center={center}
        zoom={initialZoom}
        style={{ width: "100%", height: "100%" }}
        zoomControl
        scrollWheelZoom
      >
        <TileLayer
          attribution='Mapa &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contribuidores &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={20}
        />
        <LocalizeZoomControl />
        <Recenter lat={center[0]} lng={center[1]} />
        <MoveListener onIdle={handleIdle} />

        {/* CTOs já cadastradas (referência cinza) */}
        {ctosNearby.map((c) => {
          const clat = c.lat ?? c.gps?.lat;
          const clng = c.lng ?? c.gps?.lng;
          if (clat == null || clng == null) return null;
          return (
            <Marker key={c.id} position={[clat, clng]} icon={existingCtoIcon}
                      eventHandlers={onSelectExistingCto ? {
                        click: () => onSelectExistingCto(c),
                      } : undefined}>
              <Tooltip direction="top" offset={[0, -28]} opacity={0.92}>
                <div style={{ fontSize: 11, fontWeight: 700 }}>
                  {c.name || "CTO"}
                </div>
                <div style={{ fontSize: 10, color: "#475569" }}>
                  {(c.ports || []).filter((p) => p.status === "free").length}/{c.capacity || "?"} portas livres
                </div>
                {onSelectExistingCto && (
                  <div style={{ fontSize: 9, color: "#0891b2",
                                  fontWeight: 700, marginTop: 2 }}>
                    Toque para usar esta CTO →
                  </div>
                )}
              </Tooltip>
            </Marker>
          );
        })}

        {/* Indicador da posição GPS do COLABORADOR (ponto azul) */}
        {gpsPos && (
          <>
            <CircleMarker
              center={[gpsPos.lat, gpsPos.lng]}
              pathOptions={{
                color: "#fff", weight: 2,
                fillColor: "#1d4ed8", fillOpacity: 0.95,
              }}
              radius={7}
              data-testid="gps-dot"
            />
            {gpsPos.accuracy && gpsPos.accuracy < 200 && (
              <CircleMarker
                center={[gpsPos.lat, gpsPos.lng]}
                pathOptions={{
                  color: "#3b82f6", weight: 1,
                  fillColor: "#3b82f6", fillOpacity: 0.12,
                }}
                radius={Math.max(20, Math.min(50, gpsPos.accuracy / 2))}
              />
            )}
          </>
        )}
      </MapContainer>

      {/* Pino fixo da CTO no centro — ícone SVG de caixa CTO */}
      <div style={pinWrap} data-testid="cto-map-pin">
        <div style={pinShadow} />
        <svg width="42" height="56" viewBox="0 0 42 56"
              xmlns="http://www.w3.org/2000/svg"
              style={ctoPinSvg}>
          {/* Gota (pin) */}
          <path d="M21 0 C9.4 0 0 9.4 0 21 c0 15.2 17 31.5 19.4 33.7 a2.2 2.2 0 0 0 3.2 0 C25 52.5 42 36.2 42 21 42 9.4 32.6 0 21 0 Z"
                fill="#dc2626"
                stroke="#fff"
                strokeWidth="1.5" />
          {/* Caixa CTO */}
          <rect x="10" y="11" width="22" height="18" rx="2"
                fill="#fff" stroke="#7f1d1d" strokeWidth="1" />
          {/* Portas da CTO (8 fibras) */}
          {Array.from({ length: 8 }).map((_, i) => (
            <circle key={i}
                    cx={13 + (i % 4) * 5}
                    cy={i < 4 ? 16 : 24}
                    r="1.3" fill="#dc2626" />
          ))}
          {/* Cabo principal saindo embaixo */}
          <line x1="21" y1="29" x2="21" y2="34"
                stroke="#7f1d1d" strokeWidth="1.5" />
        </svg>
      </div>

      {/* Chip topo: endereço atual em pt-BR */}
      <div style={addrChip}>
        {loading ? (
          <span style={{ fontSize: 11, color: "#475569" }}>
            🔄 Detectando endereço...
          </span>
        ) : lastAddr ? (
          <>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a",
                            lineHeight: 1.3 }}>
              {lastAddr.road || "Sem rua"}
              {lastAddr.house_number ? `, ${lastAddr.house_number}` : ""}
            </div>
            <div style={{ fontSize: 10, color: "#64748b",
                            marginTop: 1 }}>
              {[lastAddr.suburb, lastAddr.city].filter(Boolean).join(" · ")
                || "Bairro não identificado"}
            </div>
          </>
        ) : (
          <span style={{ fontSize: 11, color: "#475569" }}>
            Arraste o mapa até a CTO
          </span>
        )}
      </div>

      {/* Banner de erro GPS — só aparece se há falha */}
      {gpsError && (
        <div data-testid="cto-gps-error" style={gpsErrorBanner}>
          <span style={{ fontSize: 14 }}>📡</span>
          <span>{gpsError}</span>
        </div>
      )}

      {/* Indicador "Buscando GPS..." durante o request inicial */}
      {requestingGps && !gpsPos && (
        <div data-testid="cto-gps-loading" style={gpsLoadingBanner}>
          <span className="cto-spinner" style={spinnerStyle} />
          <span>Buscando localização...</span>
        </div>
      )}

      {/* iter183 — Badge "Raio X km · N CTO(s) próxima(s)" removido a pedido
          do usuário. Mantemos o estado `radiusInfo` para uso interno do
          filtro, mas não exibimos o pill. */}

      {/* Botão flutuante "Minha localização" */}
      <button
        type="button"
        data-testid="cto-locate-me"
        onClick={recenterOnMe}
        disabled={requestingGps}
        title="Minha localização"
        aria-label="Centralizar na minha localização"
        style={{
          ...locateBtn,
          opacity: requestingGps ? 0.5 : 1,
          cursor: requestingGps ? "wait" : "pointer",
        }}
      >
        {requestingGps ? "…" : "◎"}
      </button>
    </div>
  );
}

const pinWrap = {
  position: "absolute", left: "50%", top: "50%",
  transform: "translate(-50%, -100%)",
  pointerEvents: "none", zIndex: 999,
  display: "flex", flexDirection: "column", alignItems: "center",
};
const ctoPinSvg = {
  filter: "drop-shadow(0 3px 4px rgba(0,0,0,0.45))",
  animation: "ctoPinBounce 1.4s ease-in-out infinite",
};
const pinShadow = {
  position: "absolute", bottom: -4, left: "50%",
  transform: "translateX(-50%)",
  width: 14, height: 4, borderRadius: "50%",
  background: "rgba(0,0,0,0.35)", filter: "blur(2px)",
};
const addrChip = {
  position: "absolute", top: 10, left: 10, right: 64, zIndex: 999,
  background: "rgba(255,255,255,0.97)",
  backdropFilter: "blur(8px)",
  padding: "9px 12px", borderRadius: 10,
  boxShadow: "0 4px 14px rgba(0,0,0,0.12)",
  border: "1px solid #e2e8f0",
};
const locateBtn = {
  position: "absolute", top: 10, right: 10, zIndex: 999,
  width: 44, height: 44, borderRadius: "50%",
  background: "#fff", border: "1px solid #cbd5e1",
  boxShadow: "0 4px 14px rgba(0,0,0,0.18)",
  display: "grid", placeItems: "center",
  fontSize: 22, color: "#1d4ed8", fontWeight: 800,
  lineHeight: 1,
};
const gpsErrorBanner = {
  position: "absolute", bottom: 14, left: 10, right: 10, zIndex: 998,
  background: "#fef3c7", color: "#854d0e",
  border: "1px solid #fcd34d",
  padding: "9px 12px", borderRadius: 8,
  fontSize: 11.5, lineHeight: 1.4,
  display: "flex", alignItems: "center", gap: 8,
  boxShadow: "0 4px 14px rgba(0,0,0,0.10)",
};
const gpsLoadingBanner = {
  position: "absolute", bottom: 14, left: 10, right: 10, zIndex: 998,
  background: "rgba(15,23,42,0.92)", color: "#fff",
  padding: "8px 12px", borderRadius: 8,
  fontSize: 12, fontWeight: 600,
  display: "flex", alignItems: "center", gap: 8,
  boxShadow: "0 4px 14px rgba(0,0,0,0.18)",
};
const spinnerStyle = {
  width: 12, height: 12, borderRadius: "50%",
  border: "2px solid rgba(255,255,255,0.3)",
  borderTopColor: "#fff",
  animation: "ctoSpin 0.8s linear infinite",
  display: "inline-block",
};

// Inject keyframes once
if (typeof document !== "undefined" && !document.getElementById("cto-pin-kf")) {
  const s = document.createElement("style");
  s.id = "cto-pin-kf";
  s.innerHTML = `@keyframes ctoPinBounce {
    0%, 100% { transform: translateY(0); }
    50%      { transform: translateY(-6px); }
  }
  @keyframes ctoSpin {
    0%   { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }`;
  document.head.appendChild(s);
}
