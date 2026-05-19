/*
UberGpsPicker.js — Picker de localização tipo Uber.

Comportamento:
  - Botão "📍 Usar minha localização" usa Geolocation API
  - Mapa Leaflet centrado no ponto, com pin FIXO no centro do mapa
  - Usuário arrasta o mapa pra reposicionar o pin (estilo Uber/iFood)
  - A cada movimento, faz reverse geocode via Nominatim (OSM) — gratuito
  - Auto-preenche rua, número, bairro, cidade, estado e exibe na tela
  - Confirmar dispara onConfirm({ lat, lng, address: {...} })

Sem dependências novas: usa o Leaflet/react-leaflet que já está no projeto.
*/
import React, { useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, useMapEvents, useMap } from "react-leaflet";
import L from "leaflet";
import { X, MapPin, Loader2, Crosshair, CheckCircle2 } from "lucide-react";

const DEFAULT_CENTER = [-22.9068, -43.1729]; // Rio de Janeiro (fallback)

/* Reverse geocoding via Nominatim (OpenStreetMap). Sem chave, rate limit ~1 req/s. */
async function reverseGeocode(lat, lng) {
  const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}`
    + `&format=jsonv2&accept-language=pt-BR&zoom=18&addressdetails=1`;
  const res = await fetch(url, {
    headers: { "Accept-Language": "pt-BR" },
  });
  if (!res.ok) throw new Error("Falha no reverse geocode");
  const data = await res.json();
  const a = data.address || {};
  return {
    rua: a.road || a.pedestrian || a.path || "",
    numero: a.house_number || "",
    bairro: a.suburb || a.neighbourhood || a.quarter
      || a.city_district || a.district || "",
    cidade: a.city || a.town || a.village || a.municipality || "",
    estado: a.state_code || a.state || "",
    cep: a.postcode || "",
    display: data.display_name || "",
  };
}

/* Componente interno que captura eventos de "move" do mapa
   pra atualizar o pin no centro */
function MapMoveTracker({ onMove }) {
  const map = useMapEvents({
    moveend: () => {
      const c = map.getCenter();
      onMove({ lat: c.lat, lng: c.lng });
    },
  });
  return null;
}

/* Recentraliza o mapa quando o parent passa novo center */
function MapRecenter({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.setView(center, map.getZoom(), { animate: true });
  }, [center, map]);
  return null;
}

export default function UberGpsPicker({
  initialLat,
  initialLng,
  title = "Ajustar localização",
  onConfirm,
  onClose,
}) {
  const [center, setCenter] = useState(
    initialLat && initialLng ? [initialLat, initialLng] : DEFAULT_CENTER,
  );
  const [forceCenter, setForceCenter] = useState(null);
  const [address, setAddress] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [resolveErr, setResolveErr] = useState("");
  const [usingGps, setUsingGps] = useState(false);
  const debounceRef = useRef(null);

  const onMove = ({ lat, lng }) => {
    setCenter([lat, lng]);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setResolving(true); setResolveErr("");
      try {
        const a = await reverseGeocode(lat, lng);
        setAddress(a);
      } catch (e) {
        setResolveErr(e.message);
      } finally { setResolving(false); }
    }, 600);
  };

  const useMyLocation = async () => {
    if (!navigator.geolocation) {
      await window.alert("Seu navegador não suporta geolocalização.");
      return;
    }
    setUsingGps(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        setForceCenter([latitude, longitude]);
        setCenter([latitude, longitude]);
        setUsingGps(false);
        onMove({ lat: latitude, lng: longitude });
      },
      async (err) => {
        setUsingGps(false);
        await window.alert("Não foi possível obter sua localização: " + err.message);
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  };

  // Carrega inicial
  useEffect(() => {
    if (initialLat && initialLng) {
      onMove({ lat: initialLat, lng: initialLng });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirm = () => {
    onConfirm?.({
      lat: center[0], lng: center[1], address,
    });
  };

  return (
    <div
      data-testid="uber-gps-modal"
      style={{
        position: "fixed", inset: 0, zIndex: 99999,
        background: "#0f172a",
        display: "flex", flexDirection: "column",
      }}>
      {/* Header */}
      <div style={{
        padding: "12px 14px", background: "#0f172a", color: "#fff",
        display: "flex", alignItems: "center", gap: 10,
        borderBottom: "1px solid #1e293b",
      }}>
        <MapPin size={18} color="#a78bfa" />
        <strong style={{ flex: 1, fontSize: 14 }}>{title}</strong>
        <button onClick={onClose} data-testid="uber-gps-close"
                  style={{
                    padding: 6, border: 0, background: "transparent",
                    color: "#cbd5e1", cursor: "pointer",
                  }}>
          <X size={20} />
        </button>
      </div>

      {/* Mapa */}
      <div style={{ flex: 1, position: "relative" }}>
        <MapContainer
          center={center}
          zoom={18}
          minZoom={4}
          maxZoom={20}
          style={{ height: "100%", width: "100%" }}
          zoomControl={false}
          attributionControl={false}>
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MapMoveTracker onMove={onMove} />
          {forceCenter && <MapRecenter center={forceCenter} />}
        </MapContainer>

        {/* Pin fixo no centro (estilo Uber) */}
        <div style={{
          position: "absolute", top: "50%", left: "50%",
          transform: "translate(-50%, -100%)",
          pointerEvents: "none", zIndex: 500,
          filter: "drop-shadow(0 4px 6px rgba(0,0,0,0.4))",
        }}>
          <svg width="36" height="48" viewBox="0 0 36 48" fill="none">
            <path d="M18 0 C8 0 0 8 0 18 C0 30 18 48 18 48 C18 48 36 30 36 18 C36 8 28 0 18 0 Z"
                  fill="#8b5cf6" />
            <circle cx="18" cy="18" r="6" fill="#fff" />
          </svg>
          <div style={{
            position: "absolute", bottom: -8, left: "50%",
            transform: "translateX(-50%)",
            width: 8, height: 8, borderRadius: 999,
            background: "#000", opacity: 0.3,
          }} />
        </div>

        {/* Botão GPS (canto inferior direito) */}
        <button onClick={useMyLocation} disabled={usingGps}
                  data-testid="uber-gps-locate-btn"
                  style={{
                    position: "absolute", bottom: 18, right: 14, zIndex: 600,
                    padding: 12, border: 0, borderRadius: 999,
                    background: "#fff", color: "#0f172a",
                    boxShadow: "0 4px 14px rgba(0,0,0,0.25)",
                    cursor: usingGps ? "wait" : "pointer",
                  }}>
          {usingGps
            ? <Loader2 size={20} className="animate-spin" />
            : <Crosshair size={20} />}
        </button>
      </div>

      {/* Bottom sheet com endereço resolvido */}
      <div style={{
        padding: 14, background: "#fff", color: "#0f172a",
        borderTopLeftRadius: 16, borderTopRightRadius: 16,
        boxShadow: "0 -8px 30px rgba(0,0,0,0.15)",
      }}>
        {resolving ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6,
                          fontSize: 13, color: "#64748b" }}>
            <Loader2 size={14} className="animate-spin" />
            Buscando endereço…
          </div>
        ) : address ? (
          <>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>
              Endereço detectado
            </div>
            <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.35,
                            color: "#0f172a", marginBottom: 4 }}
                  data-testid="uber-gps-resolved-street">
              {address.rua || "(rua não detectada)"}
              {address.numero ? `, ${address.numero}` : ""}
            </div>
            <div style={{ fontSize: 12, color: "#475569", marginBottom: 8 }}
                  data-testid="uber-gps-resolved-rest">
              <strong>{address.bairro || "Bairro?"}</strong>
              {address.cidade ? ` · ${address.cidade}` : ""}
              {address.estado ? ` · ${address.estado}` : ""}
              {address.cep ? ` · CEP ${address.cep}` : ""}
            </div>
            <div style={{ fontSize: 10.5, color: "#94a3b8" }}>
              Lat {center[0].toFixed(6)} · Lng {center[1].toFixed(6)}
            </div>
          </>
        ) : resolveErr ? (
          <div style={{ fontSize: 12.5, color: "#be123c" }}>
            ⚠️ {resolveErr}
          </div>
        ) : (
          <div style={{ fontSize: 12.5, color: "#64748b" }}>
            Arraste o mapa pra ajustar o pino exatamente em cima da CTO.
          </div>
        )}

        <button onClick={confirm}
                  disabled={!address}
                  data-testid="uber-gps-confirm-btn"
                  style={{
                    width: "100%", marginTop: 10,
                    padding: "12px 16px", border: 0, borderRadius: 12,
                    background: !address
                      ? "#cbd5e1"
                      : "linear-gradient(135deg, #10b981, #059669)",
                    color: "#fff", fontSize: 14, fontWeight: 700,
                    cursor: !address ? "not-allowed" : "pointer",
                    display: "inline-flex", alignItems: "center",
                    justifyContent: "center", gap: 6,
                  }}>
          <CheckCircle2 size={16} /> Confirmar localização
        </button>
      </div>
    </div>
  );
}
