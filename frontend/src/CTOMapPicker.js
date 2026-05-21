/*
CTOMapPicker.js — Mapa "Uber-like" para posicionar a CTO.

UX:
- Mapa ocupa ~70% da viewport com pino fixo no centro (sobre uma camada
  overlay; pino NÃO está no mapa, está em CSS absoluto centralizado).
- Técnico arrasta o mapa por baixo do pino até a posição da CTO.
- Após `moveend` (idle), chama Nominatim (OSM) reverse geocode e devolve
  via prop `onMove({ lat, lng, address: {road, house_number, suburb, city, state} })`.
- Tenta usar GPS do dispositivo na primeira renderização; se falhar,
  cai no centro `defaultCenter` (Maceió-AL).
*/
import React, { useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";

const NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse";

async function reverseGeocode(lat, lng) {
  const url = `${NOMINATIM_URL}?lat=${lat}&lon=${lng}&format=json&zoom=18&addressdetails=1&accept-language=pt-BR`;
  const r = await fetch(url, {
    headers: { "Accept": "application/json" },
  });
  if (!r.ok) throw new Error("Nominatim falhou");
  const j = await r.json();
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

function Recenter({ lat, lng }) {
  const map = useMap();
  useEffect(() => {
    if (lat != null && lng != null) {
      map.setView([lat, lng], map.getZoom() || 18, { animate: true });
    }
  }, [lat, lng, map]);
  return null;
}

export default function CTOMapPicker({
  defaultCenter = [-9.6498, -35.7089], // Maceió-AL como fallback
  initialZoom = 18,
  onMove,           // ({lat, lng, address}) => void
  onError,          // (string) => void
}) {
  const [center, setCenter] = useState(defaultCenter);
  const [gpsReady, setGpsReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lastAddr, setLastAddr] = useState(null);
  const lastReqRef = useRef(0);

  // Tenta pegar GPS na montagem
  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGpsReady(true);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCenter([pos.coords.latitude, pos.coords.longitude]);
        setGpsReady(true);
      },
      (err) => {
        onError?.(`GPS não disponível (${err.message}). Arraste o mapa manualmente.`);
        setGpsReady(true);
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleIdle = async (lat, lng) => {
    setCenter([lat, lng]);
    const reqId = Date.now();
    lastReqRef.current = reqId;
    setLoading(true);
    try {
      const j = await reverseGeocode(lat, lng);
      if (lastReqRef.current !== reqId) return; // race condition
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
      onError?.("Endereço não encontrado. Verifique conexão.");
    } finally {
      if (lastReqRef.current === reqId) setLoading(false);
    }
  };

  // primeira identificação após GPS pegar
  useEffect(() => {
    if (gpsReady) handleIdle(center[0], center[1]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gpsReady]);

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
          attribution='&copy; OpenStreetMap'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Recenter lat={center[0]} lng={center[1]} />
        <MoveListener onIdle={handleIdle} />
      </MapContainer>

      {/* Pino fixo no centro */}
      <div style={pinWrap} data-testid="cto-map-pin">
        <div style={pinShadow} />
        <div style={pinIcon}>📍</div>
      </div>

      {/* Loader + endereço atual no topo */}
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
    </div>
  );
}

const pinWrap = {
  position: "absolute", left: "50%", top: "50%",
  transform: "translate(-50%, -100%)",
  pointerEvents: "none", zIndex: 999,
  display: "flex", flexDirection: "column", alignItems: "center",
};
const pinIcon = {
  fontSize: 38, lineHeight: 1, filter: "drop-shadow(0 3px 4px rgba(0,0,0,0.4))",
  animation: "ctoPinBounce 1.4s ease-in-out infinite",
};
const pinShadow = {
  position: "absolute", bottom: -4, left: "50%",
  transform: "translateX(-50%)",
  width: 14, height: 4, borderRadius: "50%",
  background: "rgba(0,0,0,0.35)", filter: "blur(2px)",
};
const addrChip = {
  position: "absolute", top: 10, left: 10, right: 10, zIndex: 999,
  background: "rgba(255,255,255,0.97)",
  backdropFilter: "blur(8px)",
  padding: "9px 12px", borderRadius: 10,
  boxShadow: "0 4px 14px rgba(0,0,0,0.12)",
  border: "1px solid #e2e8f0",
};

// Inject keyframes once
if (typeof document !== "undefined" && !document.getElementById("cto-pin-kf")) {
  const s = document.createElement("style");
  s.id = "cto-pin-kf";
  s.innerHTML = `@keyframes ctoPinBounce {
    0%, 100% { transform: translateY(0); }
    50%      { transform: translateY(-6px); }
  }`;
  document.head.appendChild(s);
}
