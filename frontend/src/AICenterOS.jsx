/**
 * AICenterOS.jsx — FASE 5 da Constituição V3.0
 *
 * Página única /ai-center que consolida TODA a inteligência do SmartProv.
 * O usuário não sente módulos — sente um cérebro único.
 *
 * Layout:
 *   ┌─ Sidebar (11 abas)
 *   ├─ Header: "Como está a empresa agora?" + headline
 *   ├─ Home: KPIs grid + Briefing IA em linguagem natural
 *   └─ Conteúdo da aba selecionada
 */
import React, { useEffect, useMemo, useState } from "react";
import { client } from "@/api";
import RevenueOpsPanel from "@/RevenueOpsPanel";
import DataQualityPanel from "@/DataQualityPanel";
import NervousSystemPanel from "@/NervousSystemPanel";
import SmartOLTTwinPanel from "@/SmartOLTTwinPanel";
import IsabellaPanel from "@/IsabellaPanel";
import IsabellaMemoryInspector from "@/IsabellaMemoryInspector";
import KnowledgeGraphPanel from "@/KnowledgeGraphPanel";
import AlvaroPanel from "@/AlvaroDirectorPanel";
import MultiTenantPanel from "@/MultiTenantPanel";
import FinancialPanel from "@/FinancialPanel";
import AutonomousCenterPanel from "@/AutonomousCenterPanel";
import BlockersPanel from "@/BlockersPanel";
import PredictivePanel from "@/PredictivePanel";
import RealRevenuePanel from "@/RealRevenuePanel";
import CashOperationPanel from "@/CashOperationPanel";


const TABS = [
  { id: "cash",        label: "💰 Operação Caixa",    icon: "💰" },
  { id: "home",        label: "Presidente IA",       icon: "🧠" },
  { id: "real-revenue", label: "Real Revenue · ROI",  icon: "💎" },
  { id: "autonomous",  label: "Autonomous Center",   icon: "🤖" },
  { id: "blockers",    label: "Self Healing",         icon: "🛠️" },
  { id: "predictive",  label: "SmartOLT Preditivo",   icon: "🔮" },
  { id: "financial",   label: "Financeiro",          icon: "💵" },
  { id: "war-room",    label: "Sala de Guerra",      icon: "⚔️" },
  { id: "revenue",     label: "RevenueOps IA",       icon: "💰" },
  { id: "isabella",    label: "Isabella IA",         icon: "👩‍💼" },
  { id: "isabella-memory", label: "Memória Isabella", icon: "🧠" },
  { id: "alvaro",      label: "Álvaro Diretor",      icon: "👨‍💼" },
  { id: "kg",          label: "Knowledge Graph",     icon: "🧬" },
  { id: "dq",          label: "Data Quality",        icon: "🩺" },
  { id: "nervous",     label: "Sistema Nervoso",     icon: "🌐" },
  { id: "twin",        label: "SmartOLT Twin",       icon: "📡" },
  { id: "decisions",   label: "Decision Center",     icon: "🎯" },
  { id: "actions",     label: "Action Center",       icon: "⚡" },
  { id: "predictions", label: "Predictions",         icon: "🔮" },
  { id: "learnings",   label: "Learnings",           icon: "📚" },
  { id: "audit",       label: "Audit Trail",         icon: "🛡️" },
  { id: "multitenant", label: "Multi-Tenant",        icon: "🏢" },
];


function fmtBRL(n) {
  return (n || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2 });
}

function fmtN(n) { return (n || 0).toLocaleString("pt-BR"); }


/* =====  HOME EXECUTIVA  ===== */
const CLASS_COLOR_BADGE = {
  ASSISTIDO: "#ef4444", SEMI_AUTONOMO: "#fbbf24",
  INTELIGENTE: "#60a5fa", AUTONOMO: "#10b981",
  OPERACAO_AUTONOMA: "#06b6d4",
};
function AutonomyBadge() {
  const [s, setS] = useState(null);
  useEffect(() => {
    client.get("/ai-center/autonomous/autonomy-score?days=1")
      .then((r) => setS(r.data)).catch(() => {});
  }, []);
  if (!s) return null;
  const color = CLASS_COLOR_BADGE[s.classification] || "#94a3b8";
  return (
    <div data-testid="autonomy-badge-sidebar"
         style={{
      background: "#020617", border: `1px solid ${color}55`,
      borderRadius: 10, padding: "10px 12px", marginBottom: 14,
    }}>
      <div style={{ fontSize: 9, color: "#94a3b8", fontWeight: 700,
                    letterSpacing: 1.5, textTransform: "uppercase" }}>
        Autonomy Score
      </div>
      <div style={{ display: "flex", alignItems: "baseline",
                    gap: 6, marginTop: 2 }}>
        <span style={{ fontSize: 22, fontWeight: 900, color }}>
          {s.score}%
        </span>
      </div>
      <div style={{ fontSize: 9, color, fontWeight: 700,
                    letterSpacing: 0.8 }}>
        {s.classification?.replace("_", " ")}
      </div>
    </div>
  );
}

function HomeExecutiva() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await client.get("/ai-center/executive-summary");
      setData(r.data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  if (loading && !data) {
    return <div style={{ padding: 40, color: "#94a3b8" }}>
             Carregando briefing executivo…
           </div>;
  }
  if (!data) return null;

  const alertColor = {
    VERDE: "#10b981", AMARELO: "#facc15", VERMELHO: "#ef4444",
  }[data.alert_level] || "#64748b";

  const k = data.kpis;
  const kpis = [
    { l: "Receita Gerada (MTD)", v: fmtBRL(k.receita_gerada_MTD),
      c: "#10b981", testid: "kpi-rev-gen" },
    { l: "Receita Recuperada (MTD)", v: fmtBRL(k.receita_recuperada_MTD),
      c: "#22c55e", testid: "kpi-rev-rec" },
    { l: "Receita em Risco (mensal)", v: fmtBRL(k.receita_em_risco_mensal),
      c: "#fbbf24", testid: "kpi-rev-risk" },
    { l: "Churn Previsto (30d)", v: fmtN(k.churn_previsto_30d),
      c: "#f97316", testid: "kpi-churn" },
    { l: "Clientes em Risco", v: fmtN(k.clientes_em_risco),
      c: "#ef4444", testid: "kpi-clients-risk" },
    { l: "CTOs Críticas", v: fmtN(k.ctos_criticas),
      c: "#ef4444", testid: "kpi-ctos" },
    { l: "Data Quality", v: `${k.data_quality_score}%`,
      sub: k.data_quality_level, c: "#a855f7", testid: "kpi-dq" },
    { l: "Eventos hoje", v: fmtN(k.eventos_hoje),
      c: "#7dd3fc", testid: "kpi-events" },
    { l: "Decisões IA (24h)", v: fmtN(k.decisoes_24h),
      c: "#3b82f6", testid: "kpi-decisions" },
    { l: "Ações IA (24h)", v: `${k.acoes_executadas_24h}/${k.acoes_24h}`,
      c: "#06b6d4", testid: "kpi-actions" },
  ];

  return (
    <div data-testid="ai-center-home">
      {/* Pergunta executiva */}
      <div data-testid="executive-question"
           style={{ background: "linear-gradient(135deg, #020617 0%, #0b1220 100%)",
                    border: `2px solid ${alertColor}66`,
                    borderRadius: 16, padding: 26, marginBottom: 20,
                    boxShadow: `0 4px 32px ${alertColor}22` }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "baseline" }}>
          <div>
            <div style={{ fontSize: 11, color: "#7dd3fc",
                          textTransform: "uppercase", letterSpacing: 1.5,
                          fontWeight: 700, marginBottom: 6 }}>
              Pergunta Executiva · Presidente IA
            </div>
            <div style={{ fontSize: 24, fontWeight: 800,
                          color: "#f1f5f9", lineHeight: 1.1 }}>
              "Como está a empresa agora?"
            </div>
          </div>
          <div style={{ background: alertColor + "22",
                        color: alertColor,
                        padding: "8px 18px", borderRadius: 999,
                        fontSize: 15, fontWeight: 800,
                        letterSpacing: 1 }}>
            {data.headline}
          </div>
        </div>
        <pre data-testid="briefing-text"
             style={{ marginTop: 16, fontSize: 14, color: "#e2e8f0",
                      fontFamily: "inherit", whiteSpace: "pre-wrap",
                      lineHeight: 1.6 }}>
          {data.briefing.replace(/\*\*/g, "")}
        </pre>
      </div>

      {/* KPIs grid */}
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
                    gap: 12, marginBottom: 20 }}>
        {kpis.map((k) => (
          <div key={k.l}
               data-testid={k.testid}
               style={{ background: "#0f172a",
                        border: `1px solid ${k.c}33`,
                        borderRadius: 10, padding: 14,
                        position: "relative", overflow: "hidden" }}>
            <div style={{ position: "absolute", top: 0, right: 0,
                          width: 4, height: "100%",
                          background: k.c, opacity: 0.8 }} />
            <div style={{ fontSize: 10, color: "#64748b",
                          textTransform: "uppercase", letterSpacing: 1,
                          fontWeight: 700 }}>{k.l}</div>
            <div style={{ fontSize: 22, fontWeight: 800,
                          color: "#f1f5f9", marginTop: 4 }}>{k.v}</div>
            {k.sub && (
              <div style={{ fontSize: 10, color: k.c,
                            fontWeight: 600, marginTop: 2 }}>{k.sub}</div>
            )}
          </div>
        ))}
      </div>

      <div style={{ textAlign: "center", fontSize: 11, color: "#475569" }}>
        Gerado em {new Date(data.generated_at).toLocaleString("pt-BR")}.
        Refresh automático a cada visita.
      </div>
    </div>
  );
}


/* =====  DECISION CENTER  ===== */
function DecisionCenter() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    client.get("/ai-center/decisions").then((r) => setItems(r.data.items));
  }, []);
  return (
    <div data-testid="decision-center">
      <h2 style={{ color: "#f1f5f9", marginBottom: 14, fontSize: 22 }}>
        Decision Center
      </h2>
      {items.length === 0
        ? <div style={{ color: "#475569" }}>Sem decisões.</div>
        : items.map((d, i) => (
          <div key={d.id || i}
               data-testid={`decision-${i}`}
               style={{ background: "#0f172a",
                        border: "1px solid #1e293b",
                        borderRadius: 10, padding: 14,
                        marginBottom: 10, color: "#e2e8f0" }}>
            <div style={{ display: "flex",
                          justifyContent: "space-between",
                          fontSize: 12 }}>
              <span style={{ color: "#7dd3fc", fontWeight: 700 }}>
                {d.kind || "decision"}
              </span>
              <span style={{ color: "#64748b" }}>
                {(d.created_at || "").substring(0, 19)}
              </span>
            </div>
            <div style={{ marginTop: 6, fontSize: 13 }}>
              {d.rationale || "(sem rationale)"}
            </div>
            <div style={{ marginTop: 6, fontSize: 11, color: "#94a3b8",
                          display: "flex", gap: 16 }}>
              {d.target_count != null &&
                <span>Alvos: <b>{d.target_count}</b></span>}
              {d.carteira_BRL != null &&
                <span>Carteira: <b>{fmtBRL(d.carteira_BRL)}</b></span>}
              {d.expected_recovery_p18_BRL != null &&
                <span>Recuperação esperada (18%): <b>
                  {fmtBRL(d.expected_recovery_p18_BRL)}</b></span>}
            </div>
          </div>
        ))}
    </div>
  );
}


/* =====  ACTION CENTER  ===== */
function ActionCenter() {
  const [data, setData] = useState({ items: [], stats: {} });
  useEffect(() => {
    client.get("/ai-center/actions").then((r) => setData(r.data));
  }, []);
  return (
    <div data-testid="action-center">
      <h2 style={{ color: "#f1f5f9", marginBottom: 14, fontSize: 22 }}>
        Action Center
      </h2>
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(4, 1fr)",
                    gap: 12, marginBottom: 16 }}>
        {[
          ["Total", data.stats.total, "#7dd3fc"],
          ["Concluídas", data.stats.done, "#10b981"],
          ["Falhadas", data.stats.failed, "#ef4444"],
          ["Taxa sucesso", `${data.stats.success_rate || 0}%`, "#fbbf24"],
        ].map(([l, v, c]) => (
          <div key={l}
               style={{ background: "#0f172a",
                        border: `1px solid ${c}33`,
                        borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 10, color: "#64748b",
                          textTransform: "uppercase",
                          letterSpacing: 1 }}>{l}</div>
            <div style={{ fontSize: 22, fontWeight: 800,
                          color: c }}>{v ?? 0}</div>
          </div>
        ))}
      </div>
      <div style={{ background: "#0f172a", border: "1px solid #1e293b",
                    borderRadius: 10, padding: 14, color: "#e2e8f0" }}>
        <table style={{ width: "100%", fontSize: 13,
                        borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "#64748b", textAlign: "left" }}>
              <th style={{ padding: 6 }}>Ação</th>
              <th style={{ padding: 6 }}>Status</th>
              <th style={{ padding: 6 }}>Criada em</th>
            </tr>
          </thead>
          <tbody>
            {data.items.slice(0, 30).map((a, i) => (
              <tr key={a.id || i}>
                <td style={{ padding: 6,
                             borderBottom: "1px solid #1e293b" }}>
                  {a.action_type}
                </td>
                <td style={{ padding: 6,
                             borderBottom: "1px solid #1e293b",
                             color: a.status === "done" ? "#10b981"
                                    : a.status === "failed" ? "#ef4444"
                                    : "#fbbf24" }}>
                  {a.status}
                </td>
                <td style={{ padding: 6,
                             borderBottom: "1px solid #1e293b",
                             color: "#64748b", fontSize: 11 }}>
                  {(a.created_at || "").substring(0, 19)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


/* =====  PREDICTIONS CENTER  ===== */
function PredictionsCenter() {
  const [pred, setPred] = useState(null);
  useEffect(() => {
    client.get("/ai-center/smartolt-twin/predictions")
      .then((r) => setPred(r.data));
  }, []);
  if (!pred) return <div style={{ color: "#94a3b8" }}>Carregando…</div>;
  return (
    <div data-testid="predictions-center">
      <h2 style={{ color: "#f1f5f9", marginBottom: 14, fontSize: 22 }}>
        Predictions Center
      </h2>
      <div style={{ color: "#64748b", marginBottom: 16, fontSize: 12 }}>
        Horizontes: 7 · 15 · 30 dias
      </div>
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 14 }}>
        {Object.entries({
          CTO_DEGRADED: { label: "CTOs degradando", c: "#f97316" },
          CTO_CRITICAL: { label: "CTOs críticas", c: "#ef4444" },
          VLAN_SATURATED: { label: "VLANs saturando", c: "#fbbf24" },
          MASS_OFFLINE: { label: "Mass offline", c: "#ef4444" },
          CHURN_BY_SIGNAL: { label: "Churn por sinal", c: "#a855f7" },
        }).map(([k, meta]) => (
          <div key={k}
               data-testid={`prediction-${k}`}
               style={{ background: "#0f172a",
                        border: `1px solid ${meta.c}33`,
                        borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 10, color: "#94a3b8",
                          textTransform: "uppercase",
                          letterSpacing: 1, fontWeight: 700 }}>
              {meta.label}
            </div>
            <div style={{ fontSize: 30, fontWeight: 800,
                          color: meta.c }}>
              {pred[k]?.predicted_count ?? 0}
            </div>
            {(pred[k]?.top || []).slice(0, 4).map((t, i) => (
              <div key={i} style={{ fontSize: 11, color: "#cbd5e1" }}>
                • {String(t)}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}


/* =====  LEARNINGS CENTER  ===== */
function LearningsCenter() {
  const [data, setData] = useState({ items: [], top_templates: [] });
  useEffect(() => {
    client.get("/ai-center/learnings").then((r) => setData(r.data));
  }, []);
  return (
    <div data-testid="learnings-center">
      <h2 style={{ color: "#f1f5f9", marginBottom: 14, fontSize: 22 }}>
        Learnings Center
      </h2>
      <div style={{ background: "#0f172a", border: "1px solid #1e293b",
                    borderRadius: 10, padding: 14, marginBottom: 14 }}>
        <div style={{ color: "#7dd3fc", fontWeight: 700,
                      fontSize: 13, marginBottom: 10 }}>
          Templates que mais convertem (R$)
        </div>
        {data.top_templates.length === 0
          ? <div style={{ color: "#475569" }}>Sem dados.</div>
          : data.top_templates.slice(0, 10).map((t, i) => (
            <div key={t.template}
                 style={{ display: "flex",
                          justifyContent: "space-between",
                          padding: "6px 0",
                          borderBottom: "1px dotted #1e293b",
                          fontSize: 13, color: "#cbd5e1" }}>
              <span>{i + 1}. {t.template}</span>
              <span><b style={{ color: "#10b981" }}>
                {fmtBRL(t.total_BRL)}</b>
                {" · "}{t.count} acionamentos
              </span>
            </div>
          ))}
      </div>
      <div style={{ background: "#0f172a", border: "1px solid #1e293b",
                    borderRadius: 10, padding: 14, color: "#cbd5e1" }}>
        <div style={{ color: "#7dd3fc", fontWeight: 700,
                      fontSize: 13, marginBottom: 10 }}>
          Aprendizados estruturados ({data.items.length})
        </div>
        {data.items.slice(0, 20).map((l, i) => (
          <div key={l.id || i} data-testid={`learning-${i}`}
               style={{ padding: "8px 0",
                        borderBottom: "1px dotted #1e293b",
                        fontSize: 12 }}>
            <span style={{ color: "#a855f7", fontWeight: 600 }}>
              {l.kind}
            </span>
            <span style={{ color: "#64748b", marginLeft: 8 }}>
              {(l.created_at || "").substring(0, 19)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


/* =====  AUDIT TRAIL (minimal)  ===== */
function AuditTrail() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    client.get("/ai-center/nervous-system/timeline-today?limit=80")
      .then((r) => setItems(r.data.items));
  }, []);
  return (
    <div data-testid="audit-trail">
      <h2 style={{ color: "#f1f5f9", marginBottom: 14, fontSize: 22 }}>
        Audit Trail
      </h2>
      <div style={{ background: "#0f172a", border: "1px solid #1e293b",
                    borderRadius: 10, padding: 14,
                    maxHeight: 600, overflowY: "auto" }}>
        {items.length === 0
          ? <div style={{ color: "#475569" }}>Sem eventos hoje.</div>
          : items.map((t, i) => (
            <div key={i} data-testid={`audit-${i}`}
                 style={{ display: "flex", gap: 10,
                          padding: "6px 0",
                          borderBottom: "1px dotted #1e293b",
                          fontSize: 12 }}>
              <span style={{ color: "#64748b",
                             fontFamily: "monospace", width: 70 }}>
                {(t.ts || "").substring(11, 19)}
              </span>
              <span style={{ color: "#a855f7",
                             textTransform: "uppercase",
                             fontSize: 10, fontWeight: 700,
                             width: 60 }}>{t.kind}</span>
              <span style={{ color: "#e2e8f0", flex: 1 }}>{t.label}</span>
            </div>
          ))}
      </div>
    </div>
  );
}


/* =====  WAR ROOM (placeholder reutilizando audit trail)  ===== */
function WarRoomTab() {
  return <AuditTrail />;
}


/* =====  AI CENTER OS  ===== */
export default function AICenterOS() {
  const [tab, setTab] = useState("cash");
  const renderTab = useMemo(() => {
    switch (tab) {
      case "cash":        return <CashOperationPanel />;
      case "home":        return <HomeExecutiva />;
      case "real-revenue": return <RealRevenuePanel />;
      case "autonomous":  return <AutonomousCenterPanel />;
      case "blockers":    return <BlockersPanel />;
      case "predictive":  return <PredictivePanel />;
      case "financial":   return <FinancialPanel />;
      case "war-room":    return <WarRoomTab />;
      case "revenue":     return <RevenueOpsPanel />;
      case "isabella":    return <IsabellaPanel />;
      case "isabella-memory": return <IsabellaMemoryInspector />;
      case "alvaro":      return <AlvaroPanel />;
      case "kg":          return <KnowledgeGraphPanel />;
      case "dq":          return <DataQualityPanel />;
      case "nervous":     return <NervousSystemPanel />;
      case "twin":        return <SmartOLTTwinPanel />;
      case "decisions":   return <DecisionCenter />;
      case "actions":     return <ActionCenter />;
      case "predictions": return <PredictionsCenter />;
      case "learnings":   return <LearningsCenter />;
      case "audit":       return <AuditTrail />;
      case "multitenant": return <MultiTenantPanel />;
      default:            return <HomeExecutiva />;
    }
  }, [tab]);

  return (
    <div data-testid="ai-center-os"
         style={{ display: "flex", minHeight: "100vh",
                  background: "#020617" }}>
      {/* Sidebar interna */}
      <aside style={{ width: 220, background: "#0b1220",
                      borderRight: "1px solid #1e293b",
                      padding: "20px 12px", flexShrink: 0 }}>
        <div style={{ color: "#7dd3fc", fontSize: 11,
                      letterSpacing: 2, textTransform: "uppercase",
                      fontWeight: 700, marginBottom: 12,
                      paddingLeft: 8 }}>
          AI Center · OS
        </div>
        <AutonomyBadge />
        {TABS.map((t) => (
          <button key={t.id}
                  data-testid={`tab-${t.id}`}
                  onClick={() => setTab(t.id)}
                  style={{ display: "flex", alignItems: "center",
                           gap: 10, width: "100%", textAlign: "left",
                           padding: "10px 12px", marginBottom: 4,
                           background: tab === t.id ? "#1e293b"
                                                     : "transparent",
                           color: tab === t.id ? "#7dd3fc" : "#94a3b8",
                           border: "none", borderRadius: 8,
                           cursor: "pointer", fontSize: 13,
                           fontWeight: tab === t.id ? 700 : 500,
                           transition: "background 0.15s" }}>
            <span style={{ fontSize: 16 }}>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
        <div style={{ marginTop: 20, padding: 10, fontSize: 10,
                      color: "#475569", textAlign: "center",
                      borderTop: "1px solid #1e293b" }}>
          Constituição V5.0
          <br />Financial Foundation · Autônomo
        </div>
      </aside>

      {/* Conteúdo */}
      <main style={{ flex: 1, padding: 24, overflow: "auto" }}>
        {renderTab}
      </main>
    </div>
  );
}
