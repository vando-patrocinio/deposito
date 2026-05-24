import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card } from "@/ui";

/**
 * Painel "Avaliação IA" — ranking de técnicos por score IA dos últimos N dias.
 * Usa o score heurístico em cada ticket (sem chamar LLM em lote).
 */
export default function AiRankingPanel() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    setLoading(true); setErr("");
    try {
      const r = await api.lousaAiRankings(days);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro");
    }
    setLoading(false);
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [days]);

  return (
    <div data-testid="ai-ranking-panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <div>
          <h2 style={{ margin: 0 }}>Avaliação IA por Técnico</h2>
          <p style={{ color: "#64748b", fontSize: 13, margin: "4px 0 0" }}>
            Ranking de score heurístico (sinais cumulativos: SLA, distância, gap, geofence, histórico).
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              data-testid={`ai-rank-period-${d}`}
              onClick={() => setDays(d)}
              style={{
                padding: "6px 12px", fontSize: 12, fontWeight: 700,
                border: days === d ? "2px solid #3b82f6" : "1px solid #cbd5e1",
                background: days === d ? "#dbeafe" : "white", borderRadius: 999,
                cursor: "pointer", color: days === d ? "#1e40af" : "#475569",
              }}
            >
              {d}d
            </button>
          ))}
          <Button variant="soft" onClick={load} data-testid="ai-rank-refresh-btn">🔄 Atualizar</Button>
        </div>
      </div>

      {err && (
        <div data-testid="ai-rank-error" style={{ background: "#fee2e2", color: "#7f1d1d", padding: 10, borderRadius: 8 }}>
          {err}
        </div>
      )}

      {loading && (
        <div data-testid="ai-rank-loading" style={{ textAlign: "center", padding: 30, color: "#64748b" }}>
          Calculando rankings…
        </div>
      )}

      {!loading && data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginBottom: 16 }}>
            <KpiCard testid="ai-rank-kpi-total" label="Tickets avaliados" value={data.total_evaluated} color="#3b82f6" />
            <KpiCard testid="ai-rank-kpi-avg" label="Score médio geral" value={data.overall_avg.toFixed(2)} color={scoreColor(data.overall_avg)} />
            <KpiCard testid="ai-rank-kpi-techs" label="Técnicos no ranking" value={data.items.length} color="#0d9488" />
            <KpiCard testid="ai-rank-kpi-period" label="Período" value={`${days}d`} color="#64748b" />
          </div>

          <Card title={`Ranking (${data.items.length} técnico(s))`}>
            {data.items.length === 0 ? (
              <p data-testid="ai-rank-empty" style={{ color: "#94a3b8", textAlign: "center", padding: 20 }}>
                Sem tickets avaliados no período selecionado.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {data.items.map((it, idx) => (
                  <RankingRow key={it.collaborator_id} item={it} position={idx + 1} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function RankingRow({ item, position }) {
  const sc = item.avg_score;
  const color = scoreColor(sc);
  const total = (item.verdicts.Excelente || 0) + (item.verdicts.Bom || 0) + (item.verdicts["Atenção"] || 0) + (item.verdicts["Crítico"] || 0);

  return (
    <div data-testid={`ai-rank-row-${item.collaborator_id}`} style={{
      display: "grid", gridTemplateColumns: "32px 56px 1fr 130px 240px 110px",
      gap: 12, alignItems: "center",
      padding: 10, borderRadius: 12,
      background: position === 1 ? "linear-gradient(90deg,#fef9c3,#fefce8)" : "#f8fafc",
      border: `1px solid ${position === 1 ? "#fcd34d" : "#e2e8f0"}`,
    }}>
      <span style={{
        fontSize: 14, fontWeight: 900, textAlign: "center",
        color: position === 1 ? "#92400e" : position === 2 ? "#475569" : position === 3 ? "#9a3412" : "#64748b",
      }}>
        {position === 1 ? "🥇" : position === 2 ? "🥈" : position === 3 ? "🥉" : `#${position}`}
      </span>
      <div style={{
        width: 44, height: 44, borderRadius: "50%",
        background: item.avatar ? `url(${item.avatar}) center/cover` : "linear-gradient(135deg,#0ea5e9,#0284c7)",
        display: "grid", placeItems: "center", color: "white", fontWeight: 800, fontSize: 14,
      }}>
        {!item.avatar && (item.collaborator_name?.[0] || "?").toUpperCase()}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 800, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 6 }}>
          {item.collaborator_name}
          {item.is_motorista_mes && (
            <span
              data-testid={`motorista-mes-badge-${item.collaborator_id}`}
              title="🏆 Motorista do mês — vistorias semanais com IA ≥ 90"
              style={{
                fontSize: 10, fontWeight: 900, padding: "2px 7px",
                borderRadius: 999, background: "linear-gradient(135deg,#fbbf24,#f59e0b)",
                color: "white", letterSpacing: 0.5,
                boxShadow: "0 2px 6px rgba(245,158,11,0.4)",
              }}>
              🏆 MOTORISTA DO MÊS
            </span>
          )}
          {!item.is_motorista_mes && item.fleet_score != null && (
            <span
              data-testid={`fleet-score-badge-${item.collaborator_id}`}
              title={`Score médio de vistorias semanais (${item.fleet_inspections_count} vistorias)`}
              style={{
                fontSize: 10, fontWeight: 800, padding: "2px 6px",
                borderRadius: 999,
                background: item.fleet_score >= 90 ? "#dcfce7"
                  : item.fleet_score >= 70 ? "#dbeafe" : "#fee2e2",
                color: item.fleet_score >= 90 ? "#166534"
                  : item.fleet_score >= 70 ? "#1e40af" : "#991b1b",
              }}>
              🚗 {item.fleet_score}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: "#64748b" }}>
          {item.praca || "—"} · {item.total_evaluated} ticket(s)
          {item.fleet_inspections_count > 0 && ` · ${item.fleet_inspections_count} vistoria(s)`}
        </div>
      </div>
      <div data-testid={`ai-rank-score-${item.collaborator_id}`} style={{
        background: color, color: "white", borderRadius: 10,
        padding: "8px 10px", textAlign: "center",
      }}>
        <div style={{ fontSize: 22, fontWeight: 900, lineHeight: 1 }}>{sc.toFixed(1)}</div>
        <div style={{ fontSize: 9, fontWeight: 700, opacity: 0.85, letterSpacing: 0.5 }}>
          MIN {item.min_score?.toFixed(1) ?? "—"} · MAX {item.max_score?.toFixed(1) ?? "—"}
        </div>
      </div>
      <div style={{ display: "flex", gap: 4, fontSize: 10, fontWeight: 700 }}>
        {[
          ["Excelente", "#10b981", item.verdicts.Excelente || 0],
          ["Bom", "#3b82f6", item.verdicts.Bom || 0],
          ["Atenção", "#f59e0b", item.verdicts["Atenção"] || 0],
          ["Crítico", "#dc2626", item.verdicts["Crítico"] || 0],
        ].map(([label, c, n]) => {
          const pct = total > 0 ? (n / total) * 100 : 0;
          return (
            <div key={label} title={`${label}: ${n}`} style={{
              flex: 1, textAlign: "center", padding: "4px 2px", borderRadius: 6,
              background: c + "15", color: c, border: `1px solid ${c}33`,
            }}>
              <div>{n}</div>
              <div style={{ fontSize: 9, opacity: 0.75 }}>{pct.toFixed(0)}%</div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: "#475569" }}>
        {item.worst_ticket && (
          <div title={item.worst_ticket.client}>
            🔴 <strong>{item.worst_ticket.score?.toFixed(1)}</strong> {item.worst_ticket.client?.substring(0, 18)}
          </div>
        )}
        {item.best_ticket && (
          <div title={item.best_ticket.client}>
            🟢 <strong>{item.best_ticket.score?.toFixed(1)}</strong> {item.best_ticket.client?.substring(0, 18)}
          </div>
        )}
      </div>
    </div>
  );
}

function KpiCard({ testid, label, value, color }) {
  return (
    <div data-testid={testid} style={{
      background: "white", border: "1px solid #e2e8f0", borderRadius: 14, padding: 14,
      borderTop: `4px solid ${color}`,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 900, color, marginTop: 4 }}>{value}</div>
    </div>
  );
}

function scoreColor(s) {
  if (s == null) return "#94a3b8";
  if (s >= 8.5) return "#10b981";
  if (s >= 7.0) return "#3b82f6";
  if (s >= 5.0) return "#f59e0b";
  return "#dc2626";
}
