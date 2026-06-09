/**
 * SmartProvLanding.jsx — FASE 9 (V5.0 Prioridade Nº 4)
 * Landing pública /smartprov-ai-center — SEM auth.
 * Pitch executivo em 60 segundos com dados reais ao vivo.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;

const fmtBRL = (n) =>
  (Number(n) || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 0,
  });
const fmtBRL2 = (n) =>
  (Number(n) || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2,
  });
const fmtN = (n) => (Number(n) || 0).toLocaleString("pt-BR");

const PRIO_COLOR = {
  ALTA: "#ef4444", MEDIA: "#fbbf24", INFO: "#3b82f6",
};

function Hero({ d }) {
  return (
    <section data-testid="landing-hero"
             style={{
      background: "radial-gradient(circle at 30% 20%, #1e3a8a44, transparent 50%), radial-gradient(circle at 80% 60%, #06b6d433, transparent 50%), #020617",
      borderBottom: "1px solid #1e293b",
      padding: "80px 8% 60px 8%",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    marginBottom: 14 }}>
        <span style={{
          background: "#06b6d4", color: "#020617",
          padding: "3px 10px", borderRadius: 999, fontSize: 10,
          fontWeight: 800, letterSpacing: 1.5,
        }}>● AO VIVO</span>
        <span style={{ color: "#7dd3fc", fontSize: 12,
                       letterSpacing: 2, fontWeight: 600 }}>
          SMARTPROV AI OS · CONSTITUIÇÃO V5.0
        </span>
      </div>
      <h1 style={{ color: "#f1f5f9", fontSize: 56, fontWeight: 900,
                   lineHeight: 1.05, margin: "0 0 18px 0",
                   maxWidth: 900 }}>
        O Sistema Operacional Autônomo<br />
        que <span style={{ color: "#10b981" }}>gera receita</span>,{" "}
        <span style={{ color: "#06b6d4" }}>recupera caixa</span> e{" "}
        <span style={{ color: "#a78bfa" }}>antecipa falhas</span><br />
        no seu provedor de internet.
      </h1>
      <p style={{ color: "#cbd5e1", fontSize: 17, maxWidth: 760,
                  lineHeight: 1.6, marginBottom: 28 }}>
        Não é ERP. É uma diretoria executiva digital com IA explicável que
        toma decisões, executa ações no WhatsApp, monitora a rede em tempo
        real e aprende a cada interação. Tudo abaixo é{" "}
        <b style={{ color: "#f1f5f9" }}>dado real</b> de uma instalação ativa.
      </p>
      <div style={{ background: "#0b1220AA", border: "1px solid #1e293b",
                    backdropFilter: "blur(8px)",
                    borderRadius: 12, padding: 16, maxWidth: 900,
                    color: "#7dd3fc", fontSize: 14, fontWeight: 600 }}>
        ► {d.headline}
      </div>
    </section>
  );
}

function KPIBlock({ label, value, sub, color, testid }) {
  return (
    <div data-testid={testid}
         style={{
      background: "#0b1220", border: `1px solid ${color || "#1e293b"}55`,
      borderRadius: 14, padding: "20px 18px", flex: 1, minWidth: 220,
    }}>
      <div style={{ color: "#94a3b8", fontSize: 10, fontWeight: 700,
                    letterSpacing: 1.5, textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ color: color || "#f1f5f9", fontSize: 32,
                    fontWeight: 800, marginTop: 6,
                    lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (<div style={{ color: "#64748b", fontSize: 12,
                              marginTop: 6 }}>{sub}</div>)}
    </div>
  );
}

function Section({ title, subtitle, children }) {
  return (
    <section style={{ padding: "60px 8%",
                       borderBottom: "1px solid #1e293b" }}>
      <div style={{ color: "#06b6d4", fontSize: 11, fontWeight: 800,
                    letterSpacing: 2, textTransform: "uppercase",
                    marginBottom: 6 }}>
        {subtitle}
      </div>
      <h2 style={{ color: "#f1f5f9", fontSize: 32, fontWeight: 800,
                   margin: "0 0 28px 0" }}>
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function SmartProvLanding() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    axios.get(`${API}/api/public/smartprov-ai-center/kpis`)
      .then((r) => setD(r.data))
      .catch((e) => setErr(e.message || "erro"));
    const t = setInterval(() => {
      axios.get(`${API}/api/public/smartprov-ai-center/kpis`)
        .then((r) => setD(r.data));
    }, 30000);
    return () => clearInterval(t);
  }, []);

  if (err) return <div style={{ padding: 40, color: "#ef4444" }}>{err}</div>;
  if (!d) return (
    <div style={{ background: "#020617", color: "#94a3b8",
                  minHeight: "100vh", display: "flex",
                  alignItems: "center", justifyContent: "center",
                  fontSize: 18 }}>
      Carregando demo ao vivo…
    </div>
  );

  return (
    <div data-testid="smartprov-landing"
         style={{ background: "#020617", minHeight: "100vh",
                   fontFamily: "Inter, sans-serif" }}>
      <Hero d={d} />

      <Section subtitle="A Realidade Financeira"
               title="Receita, risco e ROI da IA — em tempo real.">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
          <KPIBlock testid="kpi-mrr" label="MRR · Receita Recorrente"
                    color="#10b981"
                    value={fmtBRL(d.financial.mrr_BRL)}
                    sub={`${fmtN(d.financial.active_subscribers)} clientes ativos · ticket ${fmtBRL2(d.financial.avg_ticket_BRL)}`} />
          <KPIBlock testid="kpi-arr" label="ARR · Run-rate anual"
                    color="#10b981"
                    value={fmtBRL(d.financial.arr_BRL)} />
          <KPIBlock testid="kpi-ltv" label="LTV médio por cliente"
                    color="#7dd3fc"
                    value={fmtBRL2(d.financial.ltv_BRL)} />
          <KPIBlock testid="kpi-risk" label="Receita em risco · mês"
                    color="#ef4444"
                    value={fmtBRL(d.financial.revenue_at_risk_BRL)}
                    sub={`${fmtN(d.financial.subscribers_at_risk)} clientes sinalizados pela IA`} />
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14,
                      marginTop: 14 }}>
          <KPIBlock testid="kpi-collected"
                    label="Recuperado no mês"
                    color="#10b981"
                    value={fmtBRL(d.financial.collected_mtd_BRL)} />
          <KPIBlock testid="kpi-overdue"
                    label="Receita represada (overdue)"
                    color="#fbbf24"
                    value={fmtBRL(d.financial.overdue_BRL)}
                    sub={`${fmtN(d.financial.overdue_count)} faturas a recuperar`} />
          <KPIBlock testid="kpi-ia-attribution"
                    label="Atribuído pela IA"
                    color="#a78bfa"
                    value={fmtBRL2(d.financial.ia_attribution_BRL)}
                    sub="RevenueOps · acumulado" />
        </div>
      </Section>

      <Section subtitle="O Sistema Nervoso"
               title="A IA agiu hoje. Veja o que ela fez.">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
          <KPIBlock testid="kpi-events" label="Eventos monitorados / 24h"
                    color="#06b6d4"
                    value={fmtN(d.nervous_system_24h.events)} />
          <KPIBlock testid="kpi-decisions"
                    label="Decisões executadas / 24h"
                    color="#06b6d4"
                    value={fmtN(d.nervous_system_24h.decisions)} />
          <KPIBlock testid="kpi-actions"
                    label="Ações realizadas / 24h"
                    color="#06b6d4"
                    value={fmtN(d.nervous_system_24h.actions)} />
        </div>
      </Section>

      <Section subtitle="Isabella · Revenue Engine"
               title="Cada cliente, escorado por intenção real.">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
          <KPIBlock testid="kpi-churn-risk"
                    label="Em alto risco de churn"
                    color="#ef4444"
                    value={fmtN(d.isabella_engine.high_churn_risk)}
                    sub="score ≥ 0.7" />
          <KPIBlock testid="kpi-upgrade"
                    label="Potencial de upgrade"
                    color="#10b981"
                    value={fmtN(d.isabella_engine.high_upgrade_potential)}
                    sub="score ≥ 0.7" />
          <KPIBlock testid="kpi-buy"
                    label="Intenção de nova compra"
                    color="#10b981"
                    value={fmtN(d.isabella_engine.high_buy_intent)}
                    sub="score ≥ 0.7" />
        </div>
      </Section>

      <Section subtitle="SmartOLT · Digital Twin"
               title="A rede inteira em uma tela.">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
          <KPIBlock testid="kpi-ctos" label="CTOs monitoradas"
                    color="#7dd3fc"
                    value={fmtN(d.network.ctos_total)}
                    sub={`${d.network.ctos_critical} críticas`} />
          <KPIBlock testid="kpi-onus" label="ONUs sob gestão"
                    color="#7dd3fc"
                    value={fmtN(d.network.onus_total)} />
          <KPIBlock testid="kpi-onu-health"
                    label="Saúde da fibra"
                    color="#10b981"
                    value={`${d.network.onu_health_pct}%`}
                    sub={`${fmtN(d.network.onus_online)} online · ${fmtN(d.network.onus_offline)} degradadas`} />
        </div>
      </Section>

      <Section subtitle="Próximas Ações Recomendadas"
               title="O que executar agora — e quanto isso vale.">
        {d.executive_actions.map((a, i) => (
          <div key={i} data-testid={`action-${i}`}
               style={{ background: "#0b1220",
                        border: "1px solid #1e293b",
                        borderRadius: 12, padding: 18, marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "flex-start", gap: 16 }}>
              <div style={{ flex: 1 }}>
                <div style={{ color: "#f1f5f9", fontWeight: 700,
                              fontSize: 16 }}>
                  {a.problem}
                </div>
                <div style={{ color: "#94a3b8", fontSize: 13,
                              marginTop: 6 }}>
                  Ação recomendada: <b style={{ color: "#cbd5e1" }}>
                    {a.action}
                  </b>
                </div>
                {a.expected_BRL > 0 && (
                  <div style={{ color: "#86efac", fontSize: 13,
                                marginTop: 4 }}>
                    Retorno esperado:{" "}
                    <b>{fmtBRL2(a.expected_BRL)}</b>
                  </div>
                )}
              </div>
              <span style={{ background: PRIO_COLOR[a.priority] + "22",
                             color: PRIO_COLOR[a.priority],
                             border: `1px solid ${PRIO_COLOR[a.priority]}`,
                             padding: "4px 12px", borderRadius: 999,
                             fontSize: 10, fontWeight: 800,
                             letterSpacing: 1.5 }}>
                {a.priority}
              </span>
            </div>
          </div>
        ))}
      </Section>

      <Section subtitle="Governança Enterprise"
               title="Multi-tenant blindado. Dados auditáveis.">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
          <KPIBlock testid="kpi-multitenant"
                    label="Multi-tenant"
                    color={d.governance.multitenant_status === "BLINDADO"
                           ? "#10b981" : "#ef4444"}
                    value={d.governance.multitenant_status} />
          <KPIBlock testid="kpi-coverage"
                    label="Cobertura de dados"
                    color="#10b981"
                    value={`${d.governance.data_coverage_pct}%`}
                    sub={`${d.governance.multitenant_orphans} órfãos`} />
          <KPIBlock testid="kpi-modules"
                    label="Módulos ativos"
                    color="#a78bfa"
                    value={d.modules_active.length} />
        </div>
        <div style={{ marginTop: 18, display: "flex", flexWrap: "wrap",
                      gap: 8 }}>
          {d.modules_active.map((m) => (
            <span key={m} style={{
              background: "#0b1220", border: "1px solid #1e293b",
              padding: "6px 12px", borderRadius: 999, fontSize: 12,
              color: "#7dd3fc", fontWeight: 600,
            }}>{m}</span>
          ))}
        </div>
      </Section>

      <footer style={{ padding: "40px 8%", textAlign: "center",
                        color: "#475569", fontSize: 12 }}>
        SmartProv AI OS · Constituição V5.0 · Atualização ao vivo a cada 30s
        <br />
        <span style={{ color: "#64748b" }}>
          Gerado em {new Date(d.generated_at).toLocaleString("pt-BR")}
        </span>
      </footer>
    </div>
  );
}
