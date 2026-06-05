/* FleetEventsTab.js — Lista de eventos/alertas (geofence, speed, panic, etc). */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const KIND_LABEL = {
  geofence_entry: "📍 Entrou em cerca",
  geofence_exit: "🚪 Saiu de cerca",
  speed: "⚡ Excesso de velocidade",
  panic: "🆘 Pânico",
  low_battery: "🪫 Bateria fraca",
  sos: "🚨 SOS",
};

export default function FleetEventsTab({ vehicles }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterKind, setFilterKind] = useState("");
  const [filterVid, setFilterVid] = useState("");

  const reload = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterKind) params.set("kind", filterKind);
      if (filterVid) params.set("vehicle_id", filterVid);
      params.set("limit", "200");
      const r = await api._client.get(`/fleet-tracking/events?${params}`)
        .then((x) => x.data);
      setEvents(r);
    } catch (e) { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [filterKind, filterVid]);

  const vmap = Object.fromEntries(vehicles.map((v) => [v.id, v]));

  return (
    <div data-testid="fleet-events-tab" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center",
                     flexWrap: "wrap" }}>
        <select value={filterKind}
                 onChange={(e) => setFilterKind(e.target.value)}
                 style={inp}
                 data-testid="fleet-events-filter-kind">
          <option value="">Todos os tipos</option>
          <option value="geofence_entry">Entrou em cerca</option>
          <option value="geofence_exit">Saiu de cerca</option>
          <option value="speed">Excesso velocidade</option>
          <option value="panic">Pânico</option>
          <option value="sos">SOS</option>
        </select>
        <select value={filterVid}
                 onChange={(e) => setFilterVid(e.target.value)}
                 style={inp}
                 data-testid="fleet-events-filter-vid">
          <option value="">Todos os veículos</option>
          {vehicles.map((v) => (
            <option key={v.id} value={v.id}>{v.placa}</option>
          ))}
        </select>
        <button onClick={reload} style={btn}>🔄 Atualizar</button>
      </div>

      <div style={card}>
        {loading ? "Carregando…" : !events.length ? (
          <div style={empty}>Nenhum evento registrado.</div>
        ) : events.map((e) => {
          const v = vmap[e.vehicle_id];
          return (
            <div key={e.id} style={row}>
              <span style={{ fontWeight: 700, fontSize: 13 }}>
                {KIND_LABEL[e.kind] || e.kind}
              </span>
              <span style={{ fontSize: 12, color: "#475569" }}>
                {v?.placa || e.vehicle_id}
              </span>
              <span style={{ flex: 1, fontSize: 11, color: "#64748b" }}>
                {e.kind === "speed" && `${e.payload.speed_kmh}km/h (limite ${e.payload.limit_kmh}km/h)`}
                {e.kind?.startsWith("geofence") && e.payload.geofence_name}
              </span>
              <span style={{ fontSize: 11, color: "#94a3b8" }}>
                {new Date(e.ts).toLocaleString("pt-BR")}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const card = { background: "white", border: "1px solid #e2e8f0",
                 borderRadius: 12, padding: 12 };
const row = { display: "flex", gap: 10, alignItems: "center",
               padding: "8px 10px", borderBottom: "1px solid #f1f5f9" };
const inp = { padding: "6px 10px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13 };
const btn = { padding: "6px 14px", background: "#0f172a", color: "white",
                border: 0, borderRadius: 6, fontSize: 12, cursor: "pointer",
                fontWeight: 700 };
const empty = { padding: 16, textAlign: "center", color: "#94a3b8",
                 fontSize: 13 };
