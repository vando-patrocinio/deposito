/* FleetGeofencesTab.js — CRUD de geofences (círculo + polígono).
 * Modos: por coordenadas (formulário) OU desenhando direto no mapa. */
import React, { useState } from "react";
import { api } from "@/api";
import FleetGeofenceMapEditor from "@/fleet/FleetGeofenceMapEditor";

export default function FleetGeofencesTab({ geofences, onReload, vehicles }) {
  const [showMapEditor, setShowMapEditor] = useState(false);
  const [form, setForm] = useState({
    name: "", kind: "circle",
    center_lat: "", center_lng: "", radius_m: 500,
    polygon_text: "",
    vehicle_ids: [],
    alert_on: "both",
    active: true,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true); setErr("");
    try {
      const body = {
        name: form.name,
        kind: form.kind,
        center_lat: form.kind === "circle" ? Number(form.center_lat) : null,
        center_lng: form.kind === "circle" ? Number(form.center_lng) : null,
        radius_m: form.kind === "circle" ? Number(form.radius_m) : null,
        polygon: form.kind === "polygon"
          ? form.polygon_text.split("\n").map((l) => {
              const [a, b] = l.split(",").map((x) => Number(x.trim()));
              return [a, b];
            }).filter(([a, b]) => !isNaN(a) && !isNaN(b))
          : null,
        vehicle_ids: form.vehicle_ids,
        alert_on: form.alert_on,
        active: form.active,
      };
      await api._client.post("/fleet-tracking/geofences", body);
      setForm({ name: "", kind: "circle", center_lat: "", center_lng: "",
                radius_m: 500, polygon_text: "", vehicle_ids: [],
                alert_on: "both", active: true });
      onReload?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  const remove = async (gid) => {
    if (!window.confirm("Excluir esta geofence?")) return;
    try {
      await api._client.delete(`/fleet-tracking/geofences/${gid}`);
      onReload?.();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
  };

  return (
    <div data-testid="fleet-geofences-tab" style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Cercas virtuais</h3>
        <button onClick={() => setShowMapEditor(true)}
                 data-testid="fleet-gf-open-map-editor"
                 style={{ padding: "8px 16px", background: "#7c3aed",
                           color: "white", border: 0, borderRadius: 6,
                           fontWeight: 700, fontSize: 13, cursor: "pointer" }}>
          ️ Desenhar no mapa
        </button>
      </div>

      {showMapEditor && (
        <FleetGeofenceMapEditor
          vehicles={vehicles}
          onClose={() => setShowMapEditor(false)}
          onSaved={() => { setShowMapEditor(false); onReload?.(); }} />
      )}

      <div style={card}>
        <h3 style={{ margin: "0 0 12px" }}>Nova cerca virtual (por coordenadas)</h3>
        <div style={{ display: "grid",
                       gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <label style={lbl}>Nome
            <input value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    style={inp}
                    data-testid="fleet-gf-name" />
          </label>
          <label style={lbl}>Tipo
            <select value={form.kind}
                     onChange={(e) => setForm({ ...form, kind: e.target.value })}
                     style={inp}
                     data-testid="fleet-gf-kind">
              <option value="circle">Círculo (raio)</option>
              <option value="polygon">Polígono</option>
            </select>
          </label>
          {form.kind === "circle" && <>
            <label style={lbl}>Latitude centro
              <input value={form.center_lat}
                      onChange={(e) => setForm({ ...form, center_lat: e.target.value })}
                      placeholder="-23.5505"
                      style={inp}
                      data-testid="fleet-gf-lat" />
            </label>
            <label style={lbl}>Longitude centro
              <input value={form.center_lng}
                      onChange={(e) => setForm({ ...form, center_lng: e.target.value })}
                      placeholder="-46.6333"
                      style={inp}
                      data-testid="fleet-gf-lng" />
            </label>
            <label style={lbl}>Raio (m)
              <input type="number" value={form.radius_m}
                      onChange={(e) => setForm({ ...form, radius_m: e.target.value })}
                      style={inp}
                      data-testid="fleet-gf-radius" />
            </label>
          </>}
          {form.kind === "polygon" && (
            <label style={{ ...lbl, gridColumn: "1 / -1" }}>
              Polígono (uma linha por ponto, formato lat,lng)
              <textarea value={form.polygon_text}
                          onChange={(e) => setForm({ ...form, polygon_text: e.target.value })}
                          placeholder="-23.5505, -46.6333
-23.5510, -46.6400
-23.5550, -46.6380"
                          rows={5}
                          style={{ ...inp, fontFamily: "monospace" }}
                          data-testid="fleet-gf-polygon" />
            </label>
          )}
          <label style={lbl}>Alerta quando
            <select value={form.alert_on}
                     onChange={(e) => setForm({ ...form, alert_on: e.target.value })}
                     style={inp}>
              <option value="both">Entra OU sai</option>
              <option value="entry">Só entrada</option>
              <option value="exit">Só saída</option>
            </select>
          </label>
          <label style={lbl}>Veículos (vazio = todos)
            <select multiple value={form.vehicle_ids}
                     onChange={(e) => setForm({ ...form,
                       vehicle_ids: Array.from(e.target.selectedOptions)
                         .map((o) => o.value) })}
                     style={{ ...inp, minHeight: 80 }}>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.placa} {v.modelo ? `· ${v.modelo}` : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        {err && <div style={errBox}>{err}</div>}
        <button onClick={save} disabled={busy} style={primaryBtn}
                 data-testid="fleet-gf-save">
          {busy ? "Salvando…" : "Criar cerca"}
        </button>
      </div>

      <div style={card}>
        <h3 style={{ margin: "0 0 12px" }}>Cercas existentes
          ({geofences.length})</h3>
        {!geofences.length && (
          <div style={empty}>Nenhuma cerca cadastrada.</div>
        )}
        {geofences.map((g) => (
          <div key={g.id} style={row}>
            <div style={{ flex: 1 }}>
              <b>{g.name}</b> · <span style={{ color: "#64748b" }}>
                {g.kind === "circle"
                  ? `círculo raio ${g.radius_m}m em ${g.center_lat?.toFixed(4)}, ${g.center_lng?.toFixed(4)}`
                  : `polígono ${g.polygon?.length || 0} vértices`}
              </span>
            </div>
            <span style={{ fontSize: 11, color: "#475569" }}>
              {g.vehicle_ids?.length ? `${g.vehicle_ids.length} veíc.` : "todos"}
            </span>
            <button onClick={() => remove(g.id)} style={dangerBtn}>
              Excluir
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

const card = { background: "white", border: "1px solid #e2e8f0",
                 borderRadius: 12, padding: 16 };
const lbl = { display: "block", fontSize: 11, color: "#475569" };
const inp = { width: "100%", padding: "6px 10px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13, marginTop: 4,
                boxSizing: "border-box" };
const primaryBtn = {
  padding: "7px 16px", background: "#0f172a", color: "white",
  border: 0, borderRadius: 6, fontWeight: 700, fontSize: 13, cursor: "pointer",
  marginTop: 10,
};
const dangerBtn = {
  padding: "4px 12px", background: "#dc2626", color: "white",
  border: 0, borderRadius: 6, fontSize: 11, cursor: "pointer",
};
const row = { display: "flex", gap: 10, alignItems: "center",
               padding: "8px 10px", borderBottom: "1px solid #f1f5f9",
               fontSize: 13 };
const empty = { padding: 12, textAlign: "center", color: "#94a3b8",
                 fontSize: 12 };
const errBox = { padding: 10, background: "#fee2e2", color: "#991b1b",
                  borderRadius: 6, fontSize: 12, marginTop: 8 };
