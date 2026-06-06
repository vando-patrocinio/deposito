/*
 * FleetGeofenceMapEditor.js — Editor visual de cerca virtual diretamente no mapa.
 *
 * Modos:
 *  • CÍRCULO: 1º clique define o centro, depois ajusta o raio com o controle
 *             (clica de novo para mover o centro, slider muda o raio).
 *  • POLÍGONO: cada clique adiciona um vértice. Botão "Finalizar" fecha o
 *              polígono. "Limpar" zera. Min 3 pontos.
 *
 * Sem libs externas — usa apenas react-leaflet + Leaflet nativo.
 */
import React, { useState, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Circle, Polygon, useMapEvents,
         CircleMarker } from "react-leaflet";
import L from "leaflet";
import { api } from "@/api";

const pinIcon = L.divIcon({
  className: "fleet-gf-pin",
  html: `<div style="width:22px;height:22px;background:#7c3aed;border:2px solid #fff;border-radius:50%;box-shadow:0 2px 4px rgba(0,0,0,.4)"></div>`,
  iconSize: [22, 22], iconAnchor: [11, 11],
});

function MapClickHandler({ onClick }) {
  useMapEvents({
    click: (e) => onClick(e.latlng),
  });
  return null;
}

export default function FleetGeofenceMapEditor({ onClose, onSaved, vehicles }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("circle");
  const [center, setCenter] = useState(null);   // {lat,lng} (circle)
  const [radiusM, setRadiusM] = useState(500);
  const [polygon, setPolygon] = useState([]);    // [[lat,lng],...]
  const [vehicleIds, setVehicleIds] = useState([]);
  const [alertOn, setAlertOn] = useState("both");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  // Centro inicial do mapa: primeiro veículo com posição, ou São Paulo
  const mapCenter = useMemo(() => {
    const valid = vehicles.find((v) => v.lat && v.lng);
    if (valid) return [valid.lat, valid.lng];
    return [-23.55, -46.63];
  }, [vehicles]);

  const onMapClick = (latlng) => {
    if (kind === "circle") {
      setCenter({ lat: latlng.lat, lng: latlng.lng });
    } else {
      setPolygon((prev) => [...prev, [latlng.lat, latlng.lng]]);
    }
  };

  const save = async () => {
    setErr("");
    if (!name.trim()) return setErr("Dê um nome para a cerca");
    if (kind === "circle" && !center) {
      return setErr("Clique no mapa para definir o centro do círculo");
    }
    if (kind === "polygon" && polygon.length < 3) {
      return setErr("Polígono precisa de pelo menos 3 pontos");
    }
    setBusy(true);
    try {
      await api._client.post("/fleet-tracking/geofences", {
        name: name.trim(),
        kind,
        center_lat: kind === "circle" ? center.lat : null,
        center_lng: kind === "circle" ? center.lng : null,
        radius_m: kind === "circle" ? Number(radiusM) : null,
        polygon: kind === "polygon" ? polygon : null,
        vehicle_ids: vehicleIds,
        alert_on: alertOn,
        active: true,
      });
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  return (
    <div style={overlay} data-testid="fleet-gf-map-editor">
      <div style={modal}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Desenhar cerca no mapa</h2>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                       gap: 10, marginBottom: 10 }}>
          <input value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Nome da cerca *"
                  data-testid="fleet-gf-editor-name"
                  style={inp} />
          <select value={kind}
                   onChange={(e) => {
                     setKind(e.target.value);
                     setCenter(null); setPolygon([]);
                   }}
                   data-testid="fleet-gf-editor-kind"
                   style={inp}>
            <option value="circle">Círculo (clique no centro)</option>
            <option value="polygon">Polígono (clique nos vértices)</option>
          </select>
          <select value={alertOn}
                   onChange={(e) => setAlertOn(e.target.value)}
                   style={inp}>
            <option value="both">Alerta entrada e saída</option>
            <option value="entry">Só entrada</option>
            <option value="exit">Só saída</option>
          </select>
        </div>

        {kind === "circle" && (
          <div style={{ display: "flex", gap: 8, alignItems: "center",
                          marginBottom: 8, fontSize: 12 }}>
            Raio:
            <input type="range" min="50" max="5000" step="50"
                    value={radiusM}
                    onChange={(e) => setRadiusM(Number(e.target.value))}
                    style={{ flex: 1 }}
                    data-testid="fleet-gf-editor-radius" />
            <span style={{ width: 70, fontWeight: 700 }}>{radiusM}m</span>
          </div>
        )}

        {kind === "polygon" && (
          <div style={{ display: "flex", gap: 8, marginBottom: 8,
                          fontSize: 12, alignItems: "center" }}>
            <span>Pontos: <b>{polygon.length}</b></span>
            <button onClick={() => setPolygon((p) => p.slice(0, -1))}
                     style={miniBtn}
                     data-testid="fleet-gf-editor-undo">↶ Desfazer ponto</button>
            <button onClick={() => setPolygon([])} style={miniBtn}>
              ️ Limpar
            </button>
          </div>
        )}

        <div style={{ position: "relative", border: "1px solid #e2e8f0",
                       borderRadius: 8, overflow: "hidden",
                       marginBottom: 10 }}>
          <MapContainer center={mapCenter} zoom={13} style={{ height: 380 }}>
            <TileLayer attribution='&copy; OpenStreetMap'
                         url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png" />
            <MapClickHandler onClick={onMapClick} />
            {kind === "circle" && center && (
              <>
                <Marker position={[center.lat, center.lng]} icon={pinIcon} />
                <Circle center={[center.lat, center.lng]}
                          radius={Number(radiusM)}
                          pathOptions={{ color: "#7c3aed", weight: 2,
                                          fillOpacity: 0.15 }} />
              </>
            )}
            {kind === "polygon" && polygon.length >= 1 && (
              <>
                {polygon.length >= 3 && (
                  <Polygon positions={polygon}
                             pathOptions={{ color: "#7c3aed", weight: 2,
                                             fillOpacity: 0.15 }} />
                )}
                {polygon.map((p, idx) => (
                  <CircleMarker key={idx} center={p} radius={6}
                                  pathOptions={{ color: "#7c3aed",
                                                  fillColor: "#fff",
                                                  fillOpacity: 1, weight: 2 }} />
                ))}
              </>
            )}
          </MapContainer>
          <div style={{ position: "absolute", top: 8, left: 8, right: 8,
                          background: "rgba(255,255,255,.95)",
                          padding: "6px 10px", borderRadius: 6,
                          fontSize: 12, color: "#475569", pointerEvents: "none" }}>
            {kind === "circle"
              ? "Clique no mapa para definir o centro · use o slider acima para o raio"
              : "Clique no mapa para adicionar vértices (mínimo 3) · use 'Desfazer' se errar"}
          </div>
        </div>

        <label style={{ display: "block", fontSize: 11, color: "#475569",
                          marginBottom: 8 }}>
          Veículos afetados (vazio = todos)
          <select multiple value={vehicleIds}
                   onChange={(e) => setVehicleIds(
                     Array.from(e.target.selectedOptions).map((o) => o.value))}
                   style={{ ...inp, minHeight: 60 }}>
            {vehicles.map((v) => (
              <option key={v.id} value={v.id}>
                {v.placa} {v.modelo ? `· ${v.modelo}` : ""}
              </option>
            ))}
          </select>
        </label>

        {err && <div style={errBox}>{err}</div>}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} disabled={busy} style={secBtn}>
            Cancelar
          </button>
          <button onClick={save} disabled={busy} style={primaryBtn}
                   data-testid="fleet-gf-editor-save">
            {busy ? "Salvando…" : "Salvar cerca"}
          </button>
        </div>
      </div>
    </div>
  );
}

const overlay = { position: "fixed", inset: 0,
                    background: "rgba(0,0,0,.45)", display: "flex",
                    alignItems: "center", justifyContent: "center",
                    zIndex: 1000, padding: 16 };
const modal = { background: "white", borderRadius: 12, padding: 16,
                 maxWidth: 820, width: "100%", maxHeight: "92vh",
                 overflow: "auto" };
const closeBtn = { background: "transparent", border: 0, fontSize: 20,
                    cursor: "pointer", color: "#94a3b8" };
const inp = { padding: "6px 10px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13,
                boxSizing: "border-box", width: "100%" };
const miniBtn = { padding: "4px 10px", background: "white",
                    border: "1px solid #cbd5e1", borderRadius: 4,
                    fontSize: 11, cursor: "pointer" };
const primaryBtn = { padding: "8px 16px", background: "#0f172a",
                      color: "white", border: 0, borderRadius: 6,
                      fontWeight: 700, fontSize: 13, cursor: "pointer" };
const secBtn = { ...primaryBtn, background: "white", color: "#475569",
                  border: "1px solid #cbd5e1", fontWeight: 600 };
const errBox = { padding: 10, background: "#fee2e2", color: "#991b1b",
                  borderRadius: 6, fontSize: 12, marginBottom: 8 };
