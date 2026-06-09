/**
 * AutonomousCenterPanel.jsx — FASE 10 V5.0
 * Autonomous Center · Loop Evento→Análise→Decisão→Ação→Resultado→Aprendizado
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
const fmtN = (n) => (Number(n) || 0).toLocaleString("pt-BR");

const CLASS_COLOR = {
  ASSISTIDO: "#ef4444",
  SEMI_AUTONOMO: "#fbbf24",
  INTELIGENTE: "#60a5fa",
  AUTONOMO: "#10b981",
  OPERACAO_AUTONOMA: "#06b6d4",
};
const CLASS_LABEL = {
  ASSISTIDO: "Assistido",
  SEMI_AUTONOMO: "Semi-Autônomo",
  INTELIGENTE: "Inteligente",
  AUTONOMO: "Autônomo",
  OPERACAO_AUTONOMA: "Operação Autônoma",
};

function Card({ title, value, sub, color, testid, wide }) {
  return (
    <div data-testid={testid}
         style={{
      background: "#0f172a",
      border: `1px solid ${color || "#1e293b"}55`,
      borderRadius: 12, padding: 16, flex: wide ? 2 : 1, minWidth: 200,
    }}>
      <div style={{ fontSize: 10, color: "#94a3b8", fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: 1.4 }}>
        {title}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800,
                    color: color || "#f1f5f9", marginTop: 6 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: "#94a3b8",
                       marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}

export default function AutonomousCenterPanel() {
  const [summary, setSummary] = useState(null);
  const [briefing, setBriefing] = useState(null);
  const [cycles, setCycles] = useState([]);
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    Promise.all([
      client.get("/ai-center/autonomous/summary"),
      client.get("/ai-center/autonomous/daily-briefing"),
      client.get("/ai-center/autonomous/cycles?limit=20"),
    ]).then(([s, b, c]) => {
      setSummary(s.data); setBriefing(b.data);
      setCycles(c.data.items || []);
    });
  };
  useEffect(() => { load(); }, []);

  const drive = async (kind, limit = 5) => {
    setBusy(true);
    try {
      await client.post(
        `/ai-center/autonomous/drive/${kind}?limit=${limit}`);
      load();
    } finally { setBusy(false); }
  };

  const openCycle = async (cid) => {
    const r = await client.get(`/ai-center/autonomous/cycle/${cid}`);
    setDetail(r.data);
  };

  if (!summary || !briefing) return (
    <div style={{ color: "#94a3b8" }}>Carregando Autonomous Engine…</div>
  );

  const s = summary.autonomy_score;
  const classColor = CLASS_COLOR[s.classification] || "#94a3b8";

  return (
    <div data-testid="autonomous-center-panel">
      <h2 style={{ color: "#f1f5f9", marginTop: 0, fontSize: 22 }}>
        Autonomous Center · V5.0
      </h2>

      {/* Hero Autonomy Score */}
      <div style={{
        background: `linear-gradient(135deg, ${classColor}22 0%, #020617 100%)`,
        border: `1px solid ${classColor}66`,
        borderRadius: 14, padding: 22, marginBottom: 18,
        display: "flex", alignItems: "center", gap: 24,
      }}>
        <div data-testid="autonomy-score-badge"
             style={{
          width: 130, height: 130, borderRadius: "50%",
          border: `4px solid ${classColor}`,
          display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          background: "#020617",
        }}>
          <div style={{ fontSize: 36, fontWeight: 900,
                        color: classColor }}>{s.score}%</div>
          <div style={{ fontSize: 9, color: "#94a3b8",
                        fontWeight: 700, letterSpacing: 1.4 }}>
            AUTONOMY
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: "#94a3b8",
                        fontWeight: 700, letterSpacing: 1.5,
                        textTransform: "uppercase" }}>
            Classificação atual
          </div>
          <div data-testid="autonomy-classification"
               style={{ fontSize: 28, fontWeight: 800,
                          color: classColor, marginTop: 4 }}>
            {CLASS_LABEL[s.classification]}
          </div>
          <div style={{ fontSize: 13, color: "#cbd5e1",
                        marginTop: 8 }}>
            ✓ {s.successful_actions} bem-sucedidas{" "}
            · ⚠ {s.blocked_actions || 0} bloqueadas{" "}
            · ✗ {s.failed_actions} falhas{" "}
            · 👤 {s.human_interventions} intervenções humanas
          </div>
          {s.capped_reason && (
            <div data-testid="capped-reason"
                 style={{ fontSize: 12, color: "#fbbf24",
                            marginTop: 6, fontWeight: 600,
                            background: "#78350f33",
                            padding: "6px 10px",
                            borderRadius: 6,
                            border: "1px solid #fbbf2466" }}>
              ⚠ Score capado: {s.capped_reason}
            </div>
          )}
          <div style={{ fontSize: 13, color: "#7dd3fc",
                        marginTop: 6, fontWeight: 600 }}>
            {briefing.headline}
          </div>
        </div>
      </div>

      {/* Score por domínio */}
      {s.by_domain && (
        <div data-testid="domain-scores"
             style={{ display: "grid",
                        gridTemplateColumns:
                          "repeat(auto-fit, minmax(180px, 1fr))",
                        gap: 10, marginBottom: 18 }}>
          {[
            ["operational", "Operacional"],
            ["commercial", "Comercial"],
            ["financial", "Financeira"],
            ["technical", "Técnica"],
          ].map(([k, lbl]) => {
            const d = s.by_domain[k] || {};
            const c = d.score >= 75 ? "#10b981"
              : d.score >= 50 ? "#fbbf24"
              : d.total === 0 ? "#64748b" : "#ef4444";
            return (
              <div key={k} data-testid={`domain-${k}`}
                   style={{ background: "#0f172a",
                              border: `1px solid ${c}55`,
                              borderRadius: 10, padding: 12 }}>
                <div style={{ fontSize: 10, color: "#94a3b8",
                                textTransform: "uppercase",
                                letterSpacing: 1.4,
                                fontWeight: 700 }}>
                  Autonomia {lbl}
                </div>
                <div style={{ fontSize: 22, fontWeight: 800,
                                color: c, marginTop: 4 }}>
                  {d.score}%
                </div>
                <div style={{ fontSize: 11, color: "#94a3b8",
                                marginTop: 2 }}>
                  ✓{d.success || 0} · ⚠{d.blocked || 0} · total {d.total || 0}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Transport status */}
      {summary.transport && (
        <div data-testid="transport-status"
             style={{
          background: summary.transport.can_send ? "#064e3b" : "#7f1d1d",
          border: `1px solid ${summary.transport.can_send ? "#10b981" : "#ef4444"}66`,
          borderRadius: 10, padding: 14, marginBottom: 18,
          display: "flex", justifyContent: "space-between",
          alignItems: "center", gap: 14,
        }}>
          <div>
            <div style={{ fontSize: 10, color: "#cbd5e1",
                            fontWeight: 700, letterSpacing: 1.4,
                            textTransform: "uppercase" }}>
              Canal WhatsApp · Operação Tese
            </div>
            <div style={{ fontSize: 18, fontWeight: 800,
                            color: summary.transport.can_send
                              ? "#10b981" : "#ef4444",
                            marginTop: 4 }}>
              {summary.transport.status}
            </div>
          </div>
          <div style={{ fontSize: 11, color: "#cbd5e1",
                          textAlign: "right" }}>
            {summary.transport.can_send
              ? "✓ Ações financeiras serão executadas em produção"
              : `${summary.transport.blockers.length} bloqueador(es): ${summary.transport.blockers.join(", ")}`}
          </div>
        </div>
      )}

      {/* Drive buttons */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                    marginBottom: 18 }}>
        <button data-testid="drive-overdue"
                disabled={busy}
                onClick={() => drive("overdue", 5)}
                style={btn("#10b981")}>
          ⚡ Drive Overdue · 5 ciclos
        </button>
        <button data-testid="drive-churn"
                disabled={busy}
                onClick={() => drive("churn", 5)}
                style={btn("#ef4444")}>
          ⚡ Drive Isabella High-Churn · 5
        </button>
        <button data-testid="drive-onu"
                disabled={busy}
                onClick={() => drive("onu-degraded", 5)}
                style={btn("#fbbf24")}>
          ⚡ Drive ONU Degradada · 5
        </button>
        <button data-testid="reconcile-btn"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await client.post(
                      "/ai-center/autonomous/reconcile?hours=168");
                    load();
                  } finally { setBusy(false); }
                }}
                style={btn("#06b6d4")}>
          🔄 Reconcile · 7d
        </button>
        <button data-testid="briefing-btn"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const r = await client.post(
                      "/ai-center/autonomous/briefing/dispatch?slot=07h");
                    alert(`Status: ${r.data.delivery_status}\n${r.data.reason || ""}`);
                  } finally { setBusy(false); }
                }}
                style={btn("#a78bfa")}>
          📨 Dispatch Briefing · 07h
        </button>
      </div>

      {/* KPIs */}
      <div style={{ display: "flex", gap: 12, marginBottom: 14,
                    flexWrap: "wrap" }}>
        <Card testid="kpi-cycles" title="Ciclos hoje"
              color="#06b6d4" value={fmtN(summary.cycles_today)} />
        <Card testid="kpi-decisions" title="Decisões hoje"
              color="#7dd3fc" value={fmtN(summary.decisions_today)} />
        <Card testid="kpi-actions" title="Ações hoje"
              color="#a78bfa" value={fmtN(summary.actions_today)} />
        <Card testid="kpi-learnings" title="Aprendizados hoje"
              color="#10b981" value={fmtN(summary.learnings_today)} />
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 18,
                    flexWrap: "wrap" }}>
        <Card testid="kpi-generated" title="Receita gerada hoje"
              color="#10b981"
              value={fmtBRL(summary.revenue_generated_BRL)} />
        <Card testid="kpi-protected" title="Receita protegida"
              color="#10b981"
              value={fmtBRL(summary.revenue_protected_BRL)} />
        <Card testid="kpi-lost" title="Receita perdida"
              color="#ef4444"
              value={fmtBRL(summary.revenue_lost_BRL)} />
        <Card testid="kpi-blocked" title="Ações bloqueadas hoje"
              color="#fbbf24"
              value={fmtN(summary.blocked_today || 0)} />
        <Card testid="kpi-recommend" title="Somente recomendação"
              color="#94a3b8"
              value={fmtN(summary.recommend_only_today || 0)} />
        <Card testid="kpi-tunings" title="Auto-tunings"
              color="#a78bfa"
              value={fmtN(summary.auto_tunings_today)} />
      </div>

      {/* 8 perguntas executivas */}
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "8px 0 10px 0" }}>
        Presidente IA · 8 perguntas obrigatórias
      </h3>
      <div data-testid="daily-questions"
           style={{ background: "#0f172a", borderRadius: 10,
                      border: "1px solid #1e293b", padding: 14,
                      marginBottom: 18 }}>
        {Object.entries({
          "1. Quanto a IA gerou hoje?": fmtBRL2(briefing.questions["1_generated_today_BRL"]),
          "2. Quanto recuperou hoje?": fmtBRL2(briefing.questions["2_recovered_today_BRL"]),
          "3. Quanto protegeu hoje?": fmtBRL2(briefing.questions["3_protected_today_BRL"]),
          "4. Quanto perdeu hoje?": fmtBRL2(briefing.questions["4_lost_today_BRL"]),
          "5. O que aprendeu hoje?": `${briefing.questions["5_learnings_today"]} aprendizados`,
          "6. O que fará amanhã?": `${briefing.questions["6_planned_for_tomorrow_actions"]} ações · ${fmtBRL2(briefing.questions["6_planned_for_tomorrow_BRL"])} em pipeline`,
          "7. Hoje está melhor que ontem?": briefing.questions["7_better_than_yesterday"] ? "✓ Sim" : "✗ Não",
          "8. Prove com números": `Hoje ${fmtBRL2(briefing.questions["8_proof"].today_BRL)} vs Ontem ${fmtBRL2(briefing.questions["8_proof"].yesterday_BRL)} · Δ ${fmtBRL2(briefing.questions["8_proof"].diff_BRL)}`,
        }).map(([q, v]) => (
          <div key={q} style={{ display: "flex",
                                  justifyContent: "space-between",
                                  padding: "6px 0",
                                  borderBottom: "1px solid #1e293b" }}>
            <span style={{ color: "#cbd5e1", fontSize: 13 }}>{q}</span>
            <b style={{ color: "#7dd3fc", fontSize: 13 }}>{v}</b>
          </div>
        ))}
      </div>

      {/* Ciclos recentes */}
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "0 0 10px 0" }}>
        Últimos ciclos autônomos (clique p/ ver detalhe)
      </h3>
      <table data-testid="cycles-table"
             style={{ width: "100%", color: "#cbd5e1", fontSize: 12,
                        borderCollapse: "collapse", background: "#0f172a",
                        borderRadius: 8 }}>
        <thead>
          <tr style={{ color: "#64748b", background: "#1e293b",
                        textAlign: "left" }}>
            <th style={{ padding: 8 }}>Cycle ID</th>
            <th style={{ padding: 8 }}>Ação</th>
            <th style={{ padding: 8, textAlign: "right" }}>Esperado</th>
            <th style={{ padding: 8, textAlign: "right" }}>Real</th>
            <th style={{ padding: 8 }}>Status</th>
            <th style={{ padding: 8 }}>Quando</th>
          </tr>
        </thead>
        <tbody>
          {cycles.map((c) => (
            <tr key={c.cycle_id}
                onClick={() => openCycle(c.cycle_id)}
                style={{ cursor: "pointer",
                          borderBottom: "1px solid #1e293b" }}>
              <td style={{ padding: 8, fontFamily: "monospace",
                            color: "#7dd3fc" }}>
                {c.cycle_id?.substring(0, 16)}
              </td>
              <td style={{ padding: 8 }}>{c.action_kind || "—"}</td>
              <td style={{ padding: 8, textAlign: "right" }}>
                {fmtBRL2(c.expected_BRL)}
              </td>
              <td style={{ padding: 8, textAlign: "right",
                            color: (c.actual_BRL || 0) >= (c.expected_BRL || 0)
                                       ? "#10b981" : "#94a3b8" }}>
                {fmtBRL2(c.actual_BRL)}
              </td>
              <td style={{ padding: 8, color: c.status === "complete"
                                                  ? "#10b981" : "#fbbf24" }}>
                {c.status}
              </td>
              <td style={{ padding: 8, color: "#94a3b8" }}>
                {c.started_at?.substring(11, 19)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Detalhe modal */}
      {detail && (
        <div data-testid="cycle-detail"
             onClick={() => setDetail(null)}
             style={{ position: "fixed", inset: 0,
                        background: "rgba(0,0,0,0.85)", padding: 40,
                        overflow: "auto", zIndex: 50 }}>
          <div onClick={(e) => e.stopPropagation()}
               style={{ background: "#0f172a", borderRadius: 14,
                          border: "1px solid #06b6d466", padding: 24,
                          maxWidth: 900, margin: "0 auto" }}>
            <div style={{ display: "flex",
                            justifyContent: "space-between",
                            marginBottom: 14 }}>
              <h3 style={{ color: "#f1f5f9", margin: 0 }}>
                Ciclo · {detail.cycle.cycle_id}
              </h3>
              <button onClick={() => setDetail(null)}
                      style={{ background: "transparent",
                                  border: "1px solid #1e293b",
                                  color: "#94a3b8", padding: "4px 10px",
                                  borderRadius: 6, cursor: "pointer" }}>
                Fechar
              </button>
            </div>
            {["analysis", "decisions", "actions", "outcomes",
              "learnings"].map((k) => detail[k] && (
                <details key={k} open style={{
                  marginBottom: 10, background: "#020617",
                  border: "1px solid #1e293b", borderRadius: 8,
                  padding: 10 }}>
                  <summary style={{ color: "#06b6d4", fontWeight: 700,
                                       cursor: "pointer",
                                       textTransform: "uppercase",
                                       fontSize: 11,
                                       letterSpacing: 1.4 }}>
                    {k}
                  </summary>
                  <pre style={{ color: "#cbd5e1", fontSize: 11,
                                  margin: "8px 0 0 0",
                                  whiteSpace: "pre-wrap",
                                  wordBreak: "break-word" }}>
                    {JSON.stringify(detail[k], null, 2)}
                  </pre>
                </details>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function btn(color) {
  return {
    background: "#020617", color, border: `1px solid ${color}`,
    padding: "10px 16px", borderRadius: 10, cursor: "pointer",
    fontWeight: 700, fontSize: 13,
  };
}
