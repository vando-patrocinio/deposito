/**
 * PredictivePanel.jsx — V6.0 Bloco 8
 * SmartOLT Preditivo: prever falhas ANTES do cliente reclamar.
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const fmtBRL = (n) => (Number(n) || 0).toLocaleString("pt-BR",
  { style: "currency", currency: "BRL", maximumFractionDigits: 2 });
const fmtN = (n) => (Number(n) || 0).toLocaleString("pt-BR");

const SEV_COLOR = {
  OK: "#10b981", ATENCAO: "#fbbf24",
  ALTO: "#f97316", CRITICO: "#ef4444",
};

export default function PredictivePanel() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => client.get("/ai-center/predictive/summary")
    .then((r) => setData(r.data));
  useEffect(() => { load(); }, []);

  const autoTickets = async () => {
    setBusy(true);
    try {
      const r = await client.post(
        "/ai-center/predictive/auto-tickets?max_tickets=10");
      alert(`${r.data.created} tickets preventivos criados`);
      load();
    } finally { setBusy(false); }
  };

  if (!data) return <div style={{ color: "#94a3b8" }}>
    Calculando preditivo da rede…
  </div>;

  return (
    <div data-testid="predictive-panel">
      <h2 style={{ color: "#f1f5f9", marginTop: 0, fontSize: 22 }}>
        SmartOLT Preditivo · V6.0
      </h2>

      <div style={{ background: "linear-gradient(135deg, #581c87 0%, #020617 100%)",
                    border: "1px solid #a78bfa66",
                    borderRadius: 12, padding: 18, marginBottom: 18 }}>
        <div style={{ fontSize: 11, color: "#c4b5fd",
                      letterSpacing: 1.5, fontWeight: 700,
                      textTransform: "uppercase" }}>
          Previsão de Falhas · 24h adiante
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "#f1f5f9",
                      marginTop: 6 }}>
          {data.headline}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 18,
                    flexWrap: "wrap" }}>
        <Card testid="kpi-cto-risk" title="CTOs em risco"
              value={fmtN(data.summary.ctos_at_risk)}
              color="#fbbf24" />
        <Card testid="kpi-cto-crit" title="CTOs críticas"
              value={fmtN(data.summary.ctos_critical)}
              color="#ef4444" />
        <Card testid="kpi-onu-rec" title="ONUs recorrentes"
              value={fmtN(data.summary.recurrent_onus)}
              color="#f97316" />
        <Card testid="kpi-sig-churn" title="Churn por sinal"
              value={fmtN(data.summary.signal_churn_risks)}
              color="#ef4444" />
        <Card testid="kpi-monthly-risk" title="Risco / mês"
              value={fmtBRL(data.total_monthly_risk_BRL)}
              color="#ef4444" />
      </div>

      <div style={{ marginBottom: 18 }}>
        <button data-testid="auto-tickets-btn" onClick={autoTickets}
                disabled={busy}
                style={{ background: "#020617",
                            color: "#a78bfa",
                            border: "1px solid #a78bfa",
                            padding: "10px 16px", borderRadius: 10,
                            cursor: "pointer", fontWeight: 700,
                            fontSize: 13 }}>
          🎫 Criar tickets preventivos · top 10
        </button>
      </div>

      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "0 0 10px 0" }}>
        CTOs em risco (top 20)
      </h3>
      {data.ctos_at_risk.length === 0 ? (
        <div style={{ color: "#10b981", fontSize: 13, padding: 14,
                        background: "#064e3b22", borderRadius: 8 }}>
          ✓ Nenhuma CTO em risco no momento.
        </div>
      ) : (
        <table style={{ width: "100%", color: "#cbd5e1",
                          fontSize: 12, borderCollapse: "collapse",
                          background: "#0f172a", borderRadius: 8 }}>
          <thead>
            <tr style={{ color: "#64748b", background: "#1e293b",
                            textAlign: "left" }}>
              <th style={{ padding: 8 }}>Zone</th>
              <th style={{ padding: 8 }}>Severidade</th>
              <th style={{ padding: 8, textAlign: "right" }}>Score</th>
              <th style={{ padding: 8, textAlign: "right" }}>Subs</th>
              <th style={{ padding: 8, textAlign: "right" }}>Offline%</th>
              <th style={{ padding: 8, textAlign: "right" }}>Tickets 30d</th>
              <th style={{ padding: 8, textAlign: "right" }}>Impacto/mês</th>
            </tr>
          </thead>
          <tbody>
            {data.ctos_at_risk.map((c) => (
              <tr key={c.zone}
                  style={{ borderBottom: "1px solid #1e293b" }}>
                <td style={{ padding: 8, fontFamily: "monospace",
                                color: "#7dd3fc" }}>{c.zone}</td>
                <td style={{ padding: 8, color: SEV_COLOR[c.severity],
                                fontWeight: 700 }}>{c.severity}</td>
                <td style={{ padding: 8, textAlign: "right" }}>
                  {c.score}
                </td>
                <td style={{ padding: 8, textAlign: "right" }}>
                  {c.subscribers_total}
                </td>
                <td style={{ padding: 8, textAlign: "right",
                                color: c.offline_pct > 20 ? "#ef4444"
                                  : "#cbd5e1" }}>
                  {c.offline_pct}%
                </td>
                <td style={{ padding: 8, textAlign: "right" }}>
                  {c.tickets_last_30d}
                </td>
                <td style={{ padding: 8, textAlign: "right",
                                color: "#fbbf24",
                                fontWeight: 700 }}>
                  {fmtBRL(c.impact_BRL_monthly)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "18px 0 10px 0" }}>
        Churn por sinal (clientes ATIVOS com ONU degradada)
      </h3>
      <div style={{ display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(280px, 1fr))",
                    gap: 8 }}>
        {data.signal_churn_risks.slice(0, 12).map((s) => (
          <div key={s.subscriber_id}
               style={{ background: "#0f172a",
                          border: "1px solid #ef444444",
                          borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 10, color: "#64748b",
                            fontFamily: "monospace" }}>
              {s.subscriber_id?.substring(0, 24)}
            </div>
            <div style={{ fontSize: 13, color: "#f1f5f9",
                            marginTop: 4 }}>
              Zone: <b>{s.zone || "—"}</b>
            </div>
            <div style={{ fontSize: 12, color: "#ef4444",
                            fontWeight: 700, marginTop: 2 }}>
              {s.onu_status} · {fmtBRL(s.monthly_plan_BRL)}/mês em risco
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Card({ title, value, color, testid }) {
  return (
    <div data-testid={testid}
         style={{ background: "#0f172a",
                    border: `1px solid ${color}55`,
                    borderRadius: 12, padding: 14, flex: 1,
                    minWidth: 180 }}>
      <div style={{ fontSize: 10, color: "#94a3b8",
                    fontWeight: 700, letterSpacing: 1.4,
                    textTransform: "uppercase" }}>{title}</div>
      <div style={{ fontSize: 24, fontWeight: 800, color,
                    marginTop: 4 }}>{value}</div>
    </div>
  );
}
