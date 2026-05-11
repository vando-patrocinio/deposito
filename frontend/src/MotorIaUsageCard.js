import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Card, Metric } from "@/ui";
import { DollarSign, RefreshCw, Loader2, BarChart3 } from "lucide-react";

const PERIODS = [
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
  { label: "90 dias", days: 90 },
];

function fmtUSD(n) {
  const v = Number(n || 0);
  if (v === 0) return "US$ 0,00";
  if (v < 0.01) return `US$ ${v.toFixed(4)}`;
  return `US$ ${v.toFixed(2)}`;
}
function fmtNum(n) {
  return Number(n || 0).toLocaleString("pt-BR");
}

/**
 * Motor IA — Dashboard de Custos.
 * Mostra tokens consumidos e custo estimado (USD) por agente, modelo e dia.
 * Permite identificar onde o orçamento de IA está sendo gasto.
 */
export default function MotorIaUsageCard() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = async (d = days) => {
    setLoading(true); setErr("");
    try {
      const res = await api.motorIaUsage(d);
      setData(res);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro ao carregar uso");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(days); /* eslint-disable-next-line */ }, [days]);

  const maxCostAgent = useMemo(() => {
    if (!data?.by_agent?.length) return 0;
    return Math.max(...data.by_agent.map((a) => a.cost_usd || 0), 0.0001);
  }, [data]);

  const maxDaily = useMemo(() => {
    if (!data?.daily?.length) return 0;
    return Math.max(...data.daily.map((d) => d.cost_usd || 0), 0.0001);
  }, [data]);

  return (
    <Card
      title="Custo do Motor IA"
      subtitle="Tokens e custo estimado por agente, modelo e dia. Use para identificar onde o orçamento de IA é gasto."
      action={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 4, background: "var(--surface-2, #f1f5f9)",
                          padding: 3, borderRadius: 8 }}>
            {PERIODS.map((p) => (
              <button
                key={p.days}
                onClick={() => setDays(p.days)}
                data-testid={`usage-period-${p.days}`}
                style={{
                  padding: "5px 10px", border: 0, borderRadius: 6, cursor: "pointer",
                  fontSize: 12, fontWeight: 600,
                  background: days === p.days ? "var(--surface, #fff)" : "transparent",
                  color: days === p.days ? "var(--text-primary, #0f172a)" : "var(--text-muted, #64748b)",
                  boxShadow: days === p.days ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                }}
              >{p.label}</button>
            ))}
          </div>
          <button
            onClick={() => load(days)} disabled={loading}
            data-testid="usage-refresh-btn"
            style={{
              padding: "6px 10px", border: "1px solid var(--border, #e2e8f0)",
              background: "var(--surface, #fff)", borderRadius: 8, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12,
              color: "var(--text-muted, #64748b)",
            }}
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Atualizar
          </button>
        </div>
      }
      data-testid="motor-ia-usage-card"
    >
      {err && (
        <div style={{ padding: 10, background: "#fef2f2", color: "#be123c",
                        borderRadius: 8, fontSize: 13, marginBottom: 12 }}>
          {err}
        </div>
      )}

      {/* Totais */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                      gap: 12, marginBottom: 20 }}>
        <Metric label="Custo estimado"
                  value={fmtUSD(data?.totals?.cost_usd)}
                  hint={`${data?.totals?.calls || 0} chamada(s)`} />
        <Metric label="Tokens (entrada)"
                  value={fmtNum(data?.totals?.prompt_tokens)} mono />
        <Metric label="Tokens (saída)"
                  value={fmtNum(data?.totals?.completion_tokens)} mono />
        <Metric label="Tokens totais"
                  value={fmtNum(data?.totals?.total_tokens)} mono />
      </div>

      {/* Por agente — barras horizontais */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10,
                        color: "var(--text-primary, #0f172a)",
                        display: "flex", alignItems: "center", gap: 6 }}>
          <BarChart3 size={14} /> Custo por Agente
        </div>
        {!data?.by_agent?.length ? (
          <div style={{ fontSize: 12, color: "var(--text-muted, #64748b)",
                          padding: 12, textAlign: "center",
                          background: "var(--surface-2, #f8fafc)", borderRadius: 8 }}>
            Sem chamadas registradas no período.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }} data-testid="usage-by-agent">
            {data.by_agent.map((a) => {
              const pct = Math.max(2, ((a.cost_usd || 0) / maxCostAgent) * 100);
              return (
                <div key={a.agent}
                     style={{ display: "grid",
                                gridTemplateColumns: "150px 1fr 90px 90px",
                                gap: 10, alignItems: "center", fontSize: 12 }}>
                  <div style={{ fontWeight: 600, color: "var(--text-primary, #0f172a)",
                                  whiteSpace: "nowrap", overflow: "hidden",
                                  textOverflow: "ellipsis" }}
                       title={a.label}>
                    {a.label}
                  </div>
                  <div style={{ background: "var(--surface-2, #f1f5f9)",
                                  height: 18, borderRadius: 4, overflow: "hidden" }}>
                    <div style={{
                      width: `${pct}%`,
                      height: "100%",
                      background: "linear-gradient(90deg, #6366f1, #8b5cf6)",
                      transition: "width 0.5s ease",
                    }} />
                  </div>
                  <div style={{ textAlign: "right", color: "var(--text-muted, #64748b)",
                                  fontVariantNumeric: "tabular-nums" }}>
                    {fmtNum(a.total_tokens)} tok
                  </div>
                  <div style={{ textAlign: "right", fontWeight: 700,
                                  color: "var(--text-primary, #0f172a)",
                                  fontVariantNumeric: "tabular-nums" }}>
                    {fmtUSD(a.cost_usd)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Por modelo */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10,
                        color: "var(--text-primary, #0f172a)",
                        display: "flex", alignItems: "center", gap: 6 }}>
          <DollarSign size={14} /> Custo por Modelo
        </div>
        {!data?.by_model?.length ? (
          <div style={{ fontSize: 12, color: "var(--text-muted, #64748b)" }}>—</div>
        ) : (
          <div style={{ display: "grid", gap: 6 }} data-testid="usage-by-model">
            {data.by_model.map((m) => (
              <div key={m.model}
                   style={{ display: "grid",
                              gridTemplateColumns: "1fr 90px 80px 90px",
                              gap: 10, alignItems: "center", fontSize: 12,
                              padding: "6px 10px",
                              background: "var(--surface-2, #f8fafc)",
                              borderRadius: 6 }}>
                <code style={{ fontSize: 11, color: "var(--text-primary, #0f172a)",
                                  whiteSpace: "nowrap", overflow: "hidden",
                                  textOverflow: "ellipsis" }}>
                  {m.model}
                </code>
                <div style={{ textAlign: "right", color: "var(--text-muted, #64748b)" }}>
                  {fmtNum(m.total_tokens)} tok
                </div>
                <div style={{ textAlign: "right", color: "var(--text-muted, #64748b)" }}>
                  {m.calls} call
                </div>
                <div style={{ textAlign: "right", fontWeight: 700,
                                color: "var(--text-primary, #0f172a)" }}>
                  {fmtUSD(m.cost_usd)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Série diária — sparkline */}
      {data?.daily?.length > 1 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10,
                          color: "var(--text-primary, #0f172a)" }}>
            Tendência diária ({data.window_days} dias)
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3,
                          height: 70, padding: 8,
                          background: "var(--surface-2, #f8fafc)",
                          borderRadius: 8 }}
               data-testid="usage-daily-sparkline">
            {data.daily.map((d) => {
              const h = Math.max(2, ((d.cost_usd || 0) / maxDaily) * 100);
              return (
                <div key={d.date}
                     title={`${d.date}: ${fmtUSD(d.cost_usd)} • ${fmtNum(d.total_tokens)} tok`}
                     style={{
                       flex: 1,
                       height: `${h}%`,
                       minHeight: 2,
                       background: "linear-gradient(180deg, #8b5cf6, #6366f1)",
                       borderRadius: "2px 2px 0 0",
                       cursor: "pointer",
                     }} />
              );
            })}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between",
                          fontSize: 10, color: "var(--text-muted, #94a3b8)",
                          marginTop: 4 }}>
            <span>{data.daily[0]?.date}</span>
            <span>{data.daily[data.daily.length - 1]?.date}</span>
          </div>
        </div>
      )}

      <div style={{ marginTop: 16, padding: 10,
                      background: "var(--surface-2, #f8fafc)", borderRadius: 8,
                      fontSize: 11, color: "var(--text-muted, #64748b)",
                      lineHeight: 1.5 }}>
        <strong>Como é calculado:</strong> tokens reportados pelo OpenRouter são
        multiplicados pela tabela de preços oficial (entrada/saída) de cada modelo.
        Valores em USD aproximados; consulte a fatura do provedor para o valor exato.
      </div>
    </Card>
  );
}
