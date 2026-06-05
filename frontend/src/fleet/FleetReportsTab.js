/* FleetReportsTab.js — Relatórios de km, horas em movimento, paradas. */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

export default function FleetReportsTab() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    setLoading(true);
    try {
      const r = await api._client.get(`/fleet-tracking/reports/summary?days=${days}`)
        .then((x) => x.data);
      setData(r);
    } catch (e) { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [days]);

  return (
    <div data-testid="fleet-reports-tab" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        Período:
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                 style={{ padding: "6px 10px", borderRadius: 6,
                            border: "1px solid #cbd5e1", fontSize: 13 }}
                 data-testid="fleet-reports-days">
          <option value={1}>Hoje</option>
          <option value={7}>7 dias</option>
          <option value={30}>30 dias</option>
          <option value={90}>90 dias</option>
        </select>
      </div>

      <div style={{ background: "white", border: "1px solid #e2e8f0",
                     borderRadius: 12, padding: 12, overflowX: "auto" }}>
        {loading ? "Carregando…" : !data?.rows?.length ? (
          <div style={{ padding: 16, textAlign: "center", color: "#94a3b8" }}>
            Sem posições no período.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={th}>Placa</th>
                <th style={th}>Modelo</th>
                <th style={th}>KM rodados</th>
                <th style={th}>Horas em movimento</th>
                <th style={th}>Paradas</th>
                <th style={th}>Pontos GPS</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.vehicle_id}>
                  <td style={td}><b>{r.placa}</b></td>
                  <td style={td}>{r.modelo || "—"}</td>
                  <td style={td}>{r.km.toFixed(1)} km</td>
                  <td style={td}>{r.moving_hours} h</td>
                  <td style={td}>{r.stops}</td>
                  <td style={td}>{r.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const th = { textAlign: "left", padding: "8px 10px",
              borderBottom: "1px solid #e2e8f0", fontSize: 12,
              color: "#475569", textTransform: "uppercase" };
const td = { padding: "8px 10px", borderBottom: "1px solid #f1f5f9" };
