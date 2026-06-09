/**
 * FinancialPanel.jsx — FASE 11 V5.0 Financial Foundation
 * Resposta às 10 perguntas executivas — receita, risco, ROI, ação.
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const fmtBRL = (n) =>
  (Number(n) || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 0,
  });
const fmtBRL2 = (n) =>
  (Number(n) || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2,
  });

function KPI({ title, value, sub, color, testid, big = true }) {
  return (
    <div data-testid={testid} style={{
      background: "#0f172a",
      border: `1px solid ${color || "#1e293b"}55`,
      borderRadius: 12, padding: 14, flex: 1, minWidth: 200,
    }}>
      <div style={{ fontSize: 10, color: "#94a3b8", fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: 1.4 }}>
        {title}
      </div>
      <div style={{ fontSize: big ? 24 : 18, fontWeight: 800,
                    color: color || "#f1f5f9", marginTop: 6 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: "#94a3b8",
                            marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

const PRIO_COLOR = {
  ALTA: "#ef4444", MEDIA: "#fbbf24", INFO: "#3b82f6",
};

export default function FinancialPanel() {
  const [data, setData] = useState(null);

  useEffect(() => {
    client.get("/ai-center/financial/summary")
      .then((r) => setData(r.data));
  }, []);

  if (!data) return <div style={{ color: "#94a3b8" }}>
    Carregando motor financeiro…
  </div>;

  return (
    <div data-testid="financial-panel">
      <h2 style={{ color: "#f1f5f9", marginTop: 0, fontSize: 22 }}>
        Financial Foundation · V5.0
      </h2>

      <div style={{ background: "linear-gradient(135deg, #064e3b 0%, #0f172a 100%)",
                    border: "1px solid #10b98166",
                    borderRadius: 12, padding: 18, marginBottom: 18 }}>
        <div style={{ fontSize: 11, color: "#6ee7b7",
                      textTransform: "uppercase", letterSpacing: 1.5,
                      fontWeight: 700 }}>
          Headline executivo
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "#f1f5f9",
                      marginTop: 6 }}>
          {data.headline}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 14,
                    flexWrap: "wrap" }}>
        <KPI testid="mrr" title="MRR · receita recorrente"
             color="#10b981"
             value={fmtBRL(data.mrr.mrr_BRL)}
             sub={`${data.mrr.active_subscribers.toLocaleString()} ativos · ticket ${fmtBRL2(data.mrr.avg_ticket)}`} />
        <KPI testid="arr" title="ARR · run-rate anual"
             color="#10b981"
             value={fmtBRL(data.arr.arr_BRL)} />
        <KPI testid="ltv" title="LTV médio · cliente"
             color="#7dd3fc"
             value={fmtBRL2(data.ltv.ltv_BRL)}
             sub={`tenure ${data.ltv.avg_tenure_months}m · margem ${(data.ltv.margin_assumption * 100).toFixed(0)}%`} />
        <KPI testid="risk" title="Receita em risco / mês"
             color="#ef4444"
             value={fmtBRL(data.revenue_at_risk.monthly_BRL_at_risk)}
             sub={`${data.revenue_at_risk.subscribers_at_risk} clientes em alerta`} />
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 18,
                    flexWrap: "wrap" }}>
        <KPI testid="protected" title="Receita protegida"
             color="#10b981"
             value={fmtBRL(data.revenue_protected_BRL)} big={false} />
        <KPI testid="collected" title="Coletado · mês atual"
             color="#10b981"
             value={fmtBRL(data.collected_mtd.collected_MTD_BRL)}
             sub={`${data.collected_mtd.invoices_paid_MTD} pagamentos`}
             big={false} />
        <KPI testid="overdue" title="Faturas vencidas (overdue)"
             color="#fbbf24"
             value={fmtBRL(data.overdue.overdue_BRL)}
             sub={`${data.overdue.overdue_count} faturas`}
             big={false} />
        <KPI testid="churn-cost" title="Custo de churn 90d"
             color="#ef4444"
             value={fmtBRL(data.churn_cost_90d.ltv_lost_BRL)}
             sub={`${data.churn_cost_90d.churned_count} cancelamentos`}
             big={false} />
        <KPI testid="ia-attribution" title="Atribuído pela IA"
             color="#a78bfa"
             value={fmtBRL2(data.ia_attribution.total_BRL)}
             sub="RevenueOps · acumulado" big={false} />
      </div>

      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "0 0 10px 0" }}>
        Próximas Ações Executivas
      </h3>
      {data.executive_actions.length === 0
        ? <div style={{ color: "#10b981", fontSize: 13 }}>
            ✓ Sem ações urgentes no momento.
          </div>
        : data.executive_actions.map((a, i) => (
          <div key={i} data-testid={`action-${i}`}
               style={{ background: "#0f172a", border: "1px solid #1e293b",
                        borderRadius: 8, padding: 14, marginBottom: 8 }}>
            <div style={{ display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center" }}>
              <b style={{ color: "#f1f5f9", fontSize: 14 }}>
                {a.problem}
              </b>
              <span style={{ background: PRIO_COLOR[a.priority] + "33",
                             color: PRIO_COLOR[a.priority],
                             padding: "2px 8px", borderRadius: 999,
                             fontSize: 10, fontWeight: 800,
                             border: `1px solid ${PRIO_COLOR[a.priority]}` }}>
                {a.priority}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "#cbd5e1",
                          marginTop: 6 }}>
              ↳ Ação: <b>{a.action}</b>
            </div>
            {a.expected_BRL > 0 && (
              <div style={{ fontSize: 12, color: "#86efac",
                            marginTop: 2 }}>
                ✓ Retorno esperado:{" "}
                <b>{fmtBRL2(a.expected_BRL)}</b>
              </div>
            )}
          </div>
        ))}
    </div>
  );
}
