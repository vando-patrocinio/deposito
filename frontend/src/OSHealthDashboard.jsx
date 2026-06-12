/**
 * OSHealthDashboard — Dashboard de saúde do fluxo de OSs (CTO P1)
 * ----------------------------------------------------------------
 * Mostra distribuição por lifecycle_state, breach de SLA, idade média e
 * gargalo identificado. Permite drilldown nas OSs em breach.
 *
 * Pedido CTO 12/06/2026.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const PAGE = {
  maxWidth: 1280, margin: "0 auto", padding: 20,
  fontFamily: "Inter, system-ui, sans-serif",
};

function formatAge(min) {
  if (!min) return "-";
  if (min < 60) return `${min}min`;
  if (min < 1440) return `${(min / 60).toFixed(1)}h`;
  return `${(min / 1440).toFixed(1)}d`;
}

export default function OSHealthDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true); setError(null);
    try {
      const r = await api.osLifecycleHealth();
      setData(r);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }
  useEffect(() => { load(); }, []);

  if (loading) return <div style={PAGE} data-testid="os-health-loading">Carregando…</div>;
  if (error) return <div style={{ ...PAGE, color: "#dc2626" }} data-testid="os-health-error">Erro: {error}</div>;
  if (!data) return null;

  return (
    <div style={PAGE} data-testid="os-health-dashboard">
      {/* Cabeçalho com KPIs gerais */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 24,
      }}>
        <KPI label="OSs ativas" value={data.total_active_tickets} color="#0f172a" />
        <KPI label="Breach SLA" value={data.total_breach}
              sub={`${data.breach_percent}%`}
              color={data.total_breach > 0 ? "#dc2626" : "#16a34a"} />
        <KPI label="Gargalo" value={data.gargalo?.label || "—"}
              sub={`${data.gargalo?.count || 0} OSs · idade média ${formatAge(data.gargalo?.avg_age_minutes)}`}
              color="#f59e0b" small />
        <button
          onClick={load}
          data-testid="os-health-refresh"
          style={{
            background: "#0f172a", color: "white", border: "none",
            borderRadius: 12, fontWeight: 700, fontSize: 13, cursor: "pointer",
            padding: 12,
          }}>↻ Recarregar</button>
      </div>

      {/* Stats por estado */}
      <h2 style={{ fontSize: 16, fontWeight: 800, margin: "0 0 12px",
                     letterSpacing: ".01em" }}>OSs por estado</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12, marginBottom: 30 }}>
        {data.state_stats?.map((s) => (
          <div
            key={s.state}
            data-testid={`os-health-state-${s.state}`}
            style={{
              background: "white",
              border: `2px solid ${s.color}33`,
              borderLeft: `5px solid ${s.color}`,
              borderRadius: 10, padding: 14,
              boxShadow: "0 1px 3px rgba(15,23,42,.04)",
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 800, color: s.color,
                            letterSpacing: ".05em", textTransform: "uppercase" }}>
              {s.label}
            </div>
            <div style={{ fontSize: 28, fontWeight: 900, margin: "4px 0", color: "#0f172a" }}>
              {s.count}
            </div>
            <div style={{ display: "flex", gap: 10, fontSize: 11 }}>
              {s.breach_count > 0 && (
                <span style={{ color: "#dc2626", fontWeight: 700 }}>
                  🔴 {s.breach_count} breach
                </span>
              )}
              {s.warning_count > 0 && (
                <span style={{ color: "#f59e0b", fontWeight: 700 }}>
                  ⚠ {s.warning_count} alerta
                </span>
              )}
              {!s.breach_count && !s.warning_count && (
                <span style={{ color: "#16a34a", fontWeight: 700 }}>✓ ok</span>
              )}
            </div>
            <div style={{ marginTop: 8, fontSize: 11, color: "#64748b" }}>
              Idade média: <strong>{formatAge(s.avg_age_minutes)}</strong>
              {s.max_age_minutes > s.avg_age_minutes && (
                <> · máx <strong>{formatAge(s.max_age_minutes)}</strong></>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Por work_type */}
      <h2 style={{ fontSize: 16, fontWeight: 800, margin: "0 0 12px" }}>Por tipo de OS</h2>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 30 }}>
        {Object.entries(data.by_work_type || {}).map(([wt, n]) => (
          <div key={wt} data-testid={`os-health-wt-${wt}`} style={{
            background: "#f8fafc", border: "1px solid #e2e8f0",
            borderRadius: 999, padding: "6px 14px", fontSize: 12,
          }}>
            <strong>{wt}</strong> <span style={{ color: "#64748b" }}>·</span> <strong>{n}</strong>
          </div>
        ))}
      </div>

      {/* Lista de breach */}
      {data.breach_tickets?.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 800, margin: "0 0 12px", color: "#dc2626" }}>
            🔴 OSs em BREACH de SLA ({data.breach_tickets.length})
          </h2>
          <div data-testid="os-health-breach-list">
            <table style={{ width: "100%", borderCollapse: "collapse",
                              background: "white", borderRadius: 10, overflow: "hidden",
                              boxShadow: "0 1px 3px rgba(15,23,42,.06)" }}>
              <thead>
                <tr style={{ background: "#fef2f2", borderBottom: "2px solid #fecaca" }}>
                  <Th>Protocolo / ID</Th>
                  <Th>Tipo</Th>
                  <Th>Estado</Th>
                  <Th>Motivo</Th>
                  <Th align="right">Idade</Th>
                  <Th align="right">SLA</Th>
                  <Th align="right">% usado</Th>
                </tr>
              </thead>
              <tbody>
                {data.breach_tickets.map((b) => (
                  <tr key={b.ticket_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <Td>
                      <code style={{ fontSize: 11, fontFamily: "ui-monospace,monospace" }}>
                        {b.atlaz_protocolo || b.ticket_id}
                      </code>
                    </Td>
                    <Td>{b.work_type}</Td>
                    <Td>{b.lifecycle_state}</Td>
                    <Td>{b.reason_code || "—"}</Td>
                    <Td align="right">{formatAge(b.consumed_minutes)}</Td>
                    <Td align="right">{formatAge(b.sla_minutes)}</Td>
                    <Td align="right">
                      <span style={{
                        color: "#dc2626", fontWeight: 800,
                      }}>{b.percent_used}%</span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function KPI({ label, value, sub, color, small }) {
  return (
    <div style={{
      background: "white", border: "1px solid #e2e8f0",
      borderRadius: 12, padding: 16,
      boxShadow: "0 1px 3px rgba(15,23,42,.04)",
    }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: "#94a3b8",
                      letterSpacing: ".08em", textTransform: "uppercase" }}>{label}</div>
      <div style={{
        fontSize: small ? 16 : 30, fontWeight: 900, color, marginTop: 4,
        lineHeight: 1.1,
      }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}

const Th = ({ children, align }) => (
  <th style={{
    fontSize: 10, fontWeight: 800, letterSpacing: ".06em",
    textTransform: "uppercase", color: "#475569",
    padding: "10px 14px", textAlign: align || "left",
  }}>{children}</th>
);
const Td = ({ children, align }) => (
  <td style={{
    fontSize: 12, padding: "10px 14px",
    textAlign: align || "left", color: "#0f172a",
  }}>{children}</td>
);
