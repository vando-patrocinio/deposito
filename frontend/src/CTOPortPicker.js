/*
CTOPortPicker.js — Seletor de CTO + porta para uso na finalização da OS.

Fluxo (técnico mobile durante encerrar instalação):
  1. Mapa com CTOs próximas (cinza) → técnico toca em uma OU "Cadastrar nova"
  2. Após escolher: mostra as portas em grid (verde livre, vermelho usada)
  3. Técnico toca na porta usada → callback com (cto, port_number)

Props:
- collabId: ID do colaborador (para usar endpoints públicos)
- onSelect({ cto, port_number }): chamado quando técnico confirma
- onRegisterNewCto(): callback p/ abrir o CadastroCTOWizard
*/
import React, { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, Marker, Tooltip } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/api";

const ctoIcon = (selected) =>
  L.divIcon({
    className: "cto-port-picker-icon",
    html: `<svg width="${selected ? 38 : 26}" height="${selected ? 50 : 34}" viewBox="0 0 42 56" xmlns="http://www.w3.org/2000/svg">
      <path d="M21 0 C9.4 0 0 9.4 0 21 c0 15.2 17 31.5 19.4 33.7 a2.2 2.2 0 0 0 3.2 0 C25 52.5 42 36.2 42 21 42 9.4 32.6 0 21 0 Z"
            fill="${selected ? "#dc2626" : "#64748b"}" stroke="#fff" stroke-width="1.5" opacity="${selected ? 1 : 0.85}"/>
      <rect x="10" y="11" width="22" height="18" rx="2"
            fill="#fff" stroke="${selected ? "#7f1d1d" : "#334155"}" stroke-width="1"/>
    </svg>`,
    iconSize: [selected ? 38 : 26, selected ? 50 : 34],
    iconAnchor: [selected ? 19 : 13, selected ? 50 : 34],
  });

export default function CTOPortPicker({
  collabId,
  initialCenter = [-9.6498, -35.7089],
  onSelect,
  onRegisterNewCto,
}) {
  const [ctos, setCtos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCto, setSelectedCto] = useState(null);
  const [selectedPort, setSelectedPort] = useState(null);
  const [center, setCenter] = useState(initialCenter);

  // Tenta usar GPS do dispositivo
  useEffect(() => {
    if (typeof navigator !== "undefined" && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => setCenter([pos.coords.latitude, pos.coords.longitude]),
        () => { /* silent */ },
        { enableHighAccuracy: true, timeout: 8000 },
      );
    }
  }, []);

  // Carrega CTOs da empresa
  useEffect(() => {
    setLoading(true);
    api.redeIaCtosListPublic(collabId, { status: "approved" })
      .then((r) => {
        const items = (r?.items || []).filter(
          (c) => (c?.gps?.lat || c?.lat) && (c?.gps?.lng || c?.lng),
        );
        setCtos(items);
      })
      .catch(() => setCtos([]))
      .finally(() => setLoading(false));
  }, [collabId]);

  const freePortsCount = useMemo(() => {
    if (!selectedCto) return 0;
    return (selectedCto.ports || []).filter((p) => p.status === "free").length;
  }, [selectedCto]);

  const allFull = selectedCto && freePortsCount === 0;

  return (
    <div data-testid="cto-port-picker">
      {/* MAPA */}
      <div style={{
        position: "relative", width: "100%", height: 260,
        borderRadius: 12, overflow: "hidden",
        border: "1px solid #e2e8f0", marginBottom: 12,
      }}>
        <MapContainer center={center} zoom={16}
                         style={{ width: "100%", height: "100%" }}
                         scrollWheelZoom>
          <TileLayer
            attribution='&copy; OpenStreetMap, CARTO'
            url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            subdomains="abcd"
            maxZoom={20}
          />
          {ctos.map((c) => {
            const lat = c.lat ?? c.gps?.lat;
            const lng = c.lng ?? c.gps?.lng;
            if (lat == null || lng == null) return null;
            const isSel = selectedCto?.id === c.id;
            return (
              <Marker key={c.id} position={[lat, lng]}
                         icon={ctoIcon(isSel)}
                         eventHandlers={{
                           click: () => {
                             setSelectedCto(c);
                             setSelectedPort(null);
                           },
                         }}>
                <Tooltip direction="top" offset={[0, -32]} opacity={0.95}>
                  <div style={{ fontSize: 11, fontWeight: 700 }}>{c.name}</div>
                </Tooltip>
              </Marker>
            );
          })}
        </MapContainer>
        {loading && (
          <div style={overlayCenter}>Carregando CTOs...</div>
        )}
        {!loading && ctos.length === 0 && (
          <div style={overlayCenter}>
            Nenhuma CTO próxima.<br/>
            <button onClick={onRegisterNewCto} style={primaryBtn}>
              + Cadastrar nova CTO
            </button>
          </div>
        )}
      </div>

      {/* Botão sempre disponível pra cadastrar nova */}
      <button data-testid="cto-port-picker-new"
                onClick={onRegisterNewCto}
                style={ghostBtn}>
        + Cadastrar nova CTO se não estiver no mapa
      </button>

      {/* Seleção da CTO em cards (alternativa ao mapa) */}
      {!selectedCto && ctos.length > 0 && (
        <div data-testid="cto-list" style={{ marginTop: 12 }}>
          <div style={sectionLabel}>OU SELECIONE UMA CTO:</div>
          <div style={{ display: "grid", gap: 6 }}>
            {ctos.map((c) => {
              const freeN = (c.ports || []).filter((p) => p.status === "free").length;
              const total = c.capacity || (c.ports || []).length;
              const full = freeN === 0;
              return (
                <button key={c.id}
                          data-testid={`cto-list-item-${c.id}`}
                          disabled={full}
                          onClick={() => setSelectedCto(c)}
                          style={listItemBtn(full)}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>
                      {c.name}
                    </div>
                    <div style={{ fontSize: 11, color: full ? "#991b1b" : "#475569",
                                    marginTop: 2 }}>
                      {full ? "🔴 LOTADA" : `${freeN}/${total} portas livres`}
                    </div>
                  </div>
                  <span style={{ color: "#94a3b8" }}>›</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* PORTAS da CTO selecionada */}
      {selectedCto && (
        <div data-testid="cto-port-grid" style={{
          padding: 12, background: "#f8fafc",
          border: "1px solid #e2e8f0", borderRadius: 12,
          marginTop: 10,
        }}>
          <div style={{ display: "flex", alignItems: "center",
                          justifyContent: "space-between", marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
                {selectedCto.name}
              </div>
              <div style={{ fontSize: 11, color: "#64748b" }}>
                {freePortsCount}/{selectedCto.capacity} portas livres
              </div>
            </div>
            <button onClick={() => { setSelectedCto(null); setSelectedPort(null); }}
                      style={{ background: "transparent", border: 0,
                                color: "#64748b", fontSize: 12,
                                cursor: "pointer", textDecoration: "underline" }}>
              Trocar
            </button>
          </div>

          {allFull && (
            <div data-testid="cto-full-warning" style={{
              padding: 10, marginBottom: 10, borderRadius: 8,
              background: "#fee2e2", color: "#991b1b",
              border: "1px solid #fca5a5", fontSize: 12, lineHeight: 1.4,
            }}>
              🔴 CTO está <strong>LOTADA</strong>. Cadastre uma nova CTO
              para conectar este cliente.
            </div>
          )}

          {!allFull && (
            <>
              <div style={sectionLabel}>QUAL PORTA O CLIENTE ESTÁ CONECTADO?</div>
              <div data-testid="port-grid" style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)", gap: 6, marginTop: 6,
              }}>
                {(selectedCto.ports || []).map((p) => {
                  const used = p.status === "used";
                  const isSel = selectedPort === p.number;
                  return (
                    <button key={p.number}
                              data-testid={`cto-port-${p.number}`}
                              disabled={used}
                              onClick={() => setSelectedPort(p.number)}
                              style={portBtn(used, isSel)}>
                      <div style={{ fontSize: 15, fontWeight: 800 }}>
                        {p.number}
                      </div>
                      <div style={{ fontSize: 9, marginTop: 1, opacity: 0.85 }}>
                        {used ? "USADA" : "LIVRE"}
                      </div>
                    </button>
                  );
                })}
              </div>

              <button data-testid="cto-port-confirm"
                        disabled={!selectedPort}
                        onClick={() => onSelect?.({
                          cto: selectedCto, port_number: selectedPort,
                        })}
                        style={{
                          ...primaryBtn, marginTop: 12, width: "100%",
                          opacity: selectedPort ? 1 : 0.5,
                        }}>
                {selectedPort
                  ? `Confirmar porta ${selectedPort}`
                  : "Selecione uma porta"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const sectionLabel = {
  fontSize: 10, fontWeight: 800, color: "#475569",
  textTransform: "uppercase", letterSpacing: 0.6, marginTop: 4,
};
const overlayCenter = {
  position: "absolute", inset: 0, display: "grid", placeItems: "center",
  background: "rgba(255,255,255,0.92)", fontSize: 13, color: "#475569",
  textAlign: "center", padding: 16,
};
const primaryBtn = {
  padding: "10px 16px", border: 0, borderRadius: 8,
  background: "#1e293b", color: "#fff", fontWeight: 700,
  fontSize: 13, cursor: "pointer",
};
const ghostBtn = {
  width: "100%", padding: "10px 14px", border: "1px dashed #cbd5e1",
  borderRadius: 8, background: "#fff", color: "#1d4ed8",
  fontSize: 12, fontWeight: 700, cursor: "pointer",
};
const listItemBtn = (full) => ({
  padding: "12px 14px", border: `1px solid ${full ? "#fecaca" : "#e2e8f0"}`,
  borderRadius: 10, background: full ? "#fef2f2" : "#fff",
  display: "flex", alignItems: "center", gap: 8,
  cursor: full ? "not-allowed" : "pointer", color: "#0f172a",
  textAlign: "left",
});
const portBtn = (used, sel) => ({
  padding: "10px 4px", border: `1.5px solid ${
    sel ? "#0f766e" : used ? "#fca5a5" : "#86efac"
  }`,
  borderRadius: 8,
  background: sel ? "#ccfbf1"
              : used ? "#fee2e2" : "#dcfce7",
  color: sel ? "#0f766e" : used ? "#991b1b" : "#166534",
  cursor: used ? "not-allowed" : "pointer",
  textAlign: "center", lineHeight: 1.1,
});
