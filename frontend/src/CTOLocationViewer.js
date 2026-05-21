/*
CTOLocationViewer.js — Modal read-only para visualizar a localização
onde uma CTO foi cadastrada (usado em validações/auditoria).

Diferente do CTOMapPicker:
- NÃO pede GPS do gestor (a localização já é a da CTO)
- Pino fixo nas coords da CTO
- Não tem botão "Minha localização"
- Foto da CTO aparece em side panel/abaixo (se houver)
- Botão "Abrir no Google Maps" pra navegar até o local
*/
import React from "react";
import {
  MapContainer, TileLayer, Marker, Popup, Tooltip,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Ícone customizado de CTO (mesmo estilo do CTOMapPicker)
const ctoIcon = L.divIcon({
  className: "cto-marker-icon",
  html: `
    <svg width="42" height="56" viewBox="0 0 42 56" xmlns="http://www.w3.org/2000/svg">
      <path d="M21 0 C9.4 0 0 9.4 0 21 c0 15.2 17 31.5 19.4 33.7 a2.2 2.2 0 0 0 3.2 0 C25 52.5 42 36.2 42 21 42 9.4 32.6 0 21 0 Z"
            fill="#dc2626" stroke="#fff" stroke-width="1.5"/>
      <rect x="10" y="11" width="22" height="18" rx="2"
            fill="#fff" stroke="#7f1d1d" stroke-width="1"/>
      <circle cx="13" cy="16" r="1.3" fill="#dc2626"/>
      <circle cx="18" cy="16" r="1.3" fill="#dc2626"/>
      <circle cx="23" cy="16" r="1.3" fill="#dc2626"/>
      <circle cx="28" cy="16" r="1.3" fill="#dc2626"/>
      <circle cx="13" cy="24" r="1.3" fill="#dc2626"/>
      <circle cx="18" cy="24" r="1.3" fill="#dc2626"/>
      <circle cx="23" cy="24" r="1.3" fill="#dc2626"/>
      <circle cx="28" cy="24" r="1.3" fill="#dc2626"/>
      <line x1="21" y1="29" x2="21" y2="34" stroke="#7f1d1d" stroke-width="1.5"/>
    </svg>
  `,
  iconSize: [42, 56],
  iconAnchor: [21, 56],
  popupAnchor: [0, -50],
});

export default function CTOLocationViewer({ cto, onClose }) {
  // Aceita ambas formas:
  // - flat: { lat, lng, rua, numero, bairro }
  // - nested: { gps: {lat, lng}, address: {rua, numero, bairro} }
  const lat = cto?.lat ?? cto?.gps?.lat;
  const lng = cto?.lng ?? cto?.gps?.lng;
  if (lat == null || lng == null) return null;
  const a = cto.address || cto;
  const name = cto.name || "CTO";
  const addr = [a.rua, a.numero && `n° ${a.numero}`, a.bairro]
    .filter(Boolean).join(" · ");
  const gmapsUrl = `https://www.google.com/maps?q=${lat},${lng}&z=18`;
  const wazeUrl = `https://waze.com/ul?ll=${lat},${lng}&navigate=yes`;

  return (
    <div onClick={onClose} data-testid="cto-location-modal" style={overlay}>
      <div onClick={(e) => e.stopPropagation()} style={modalBox}>
        {/* Header */}
        <div style={modalHeader}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
              {name}
            </div>
            {addr && (
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                {addr}
              </div>
            )}
          </div>
          <button data-testid="cto-location-close" onClick={onClose} style={closeBtn}>
            ×
          </button>
        </div>

        {/* Mapa */}
        <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
          <MapContainer center={[lat, lng]} zoom={18}
                          style={{ width: "100%", height: "100%" }}
                          scrollWheelZoom>
            <TileLayer
              attribution='Mapa &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contribuidores &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
              subdomains="abcd"
              maxZoom={20}
            />
            <Marker position={[lat, lng]} icon={ctoIcon}>
              <Tooltip permanent direction="top" offset={[0, -50]}
                          className="cto-tooltip">
                {name}
              </Tooltip>
              <Popup>
                <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                  <strong>{name}</strong><br/>
                  {addr}<br/>
                  <code style={{ fontSize: 10 }}>
                    {lat.toFixed(6)}, {lng.toFixed(6)}
                  </code>
                </div>
              </Popup>
            </Marker>
          </MapContainer>
        </div>

        {/* Footer: coords + atalhos */}
        <div style={footer}>
          <div style={{ fontSize: 11, color: "#64748b", fontFamily: "monospace" }}>
            📍 {lat.toFixed(6)}, {lng.toFixed(6)}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <a data-testid="cto-location-gmaps" href={gmapsUrl} target="_blank"
                rel="noopener noreferrer" style={btnExt}>
              Google Maps
            </a>
            <a data-testid="cto-location-waze" href={wazeUrl} target="_blank"
                rel="noopener noreferrer" style={btnExt}>
              Waze
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

const overlay = {
  position: "fixed", inset: 0, background: "rgba(15,23,42,0.65)",
  backdropFilter: "blur(2px)", zIndex: 9999,
  display: "grid", placeItems: "center", padding: 16,
};
const modalBox = {
  background: "#fff", borderRadius: 12,
  width: "min(900px, 96vw)", height: "min(640px, 92vh)",
  display: "flex", flexDirection: "column",
  boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
  overflow: "hidden",
};
const modalHeader = {
  padding: "12px 16px",
  borderBottom: "1px solid #e2e8f0",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  background: "#f8fafc",
};
const closeBtn = {
  border: 0, background: "transparent", fontSize: 28,
  color: "#64748b", cursor: "pointer", lineHeight: 1,
  padding: "0 6px",
};
const footer = {
  padding: "10px 16px", borderTop: "1px solid #e2e8f0",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  background: "#f8fafc", gap: 10, flexWrap: "wrap",
};
const btnExt = {
  padding: "6px 12px", fontSize: 12, fontWeight: 700,
  background: "#1e293b", color: "#fff",
  borderRadius: 6, textDecoration: "none",
  border: 0, cursor: "pointer",
};
