/* LoyaltyAITab — sub-aba" Clientes IA": análise inteligente da base
 * de fidelidade usando Claude Sonnet 4.6. Identifica oportunidades de
 * winback, upgrade, retenção e gera plano de ação de 30 dias.
 *
 * iter215i — Backend: GET /api/customer/loyalty-ai/insights (cache 24h)
 * POST /api/customer/loyalty-ai/regenerate (força refresh)
 * GET /api/customer/loyalty-ai/top-winback-targets
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const PRIORITY_COLOR = {
 alta: { bg:"#fee2e2", txt:"#7f1d1d", border:"#fca5a5" },
 media: { bg:"#fef3c7", txt:"#78350f", border:"#fcd34d" },
 baixa: { bg:"#dbeafe", txt:"#1e3a8a", border:"#93c5fd" },
};

function priorityChip(p) {
 const c = PRIORITY_COLOR[p] || PRIORITY_COLOR.baixa;
 return {
 background: c.bg, color: c.txt, border: `1px solid ${c.border}`,
 padding:"2px 8px", borderRadius: 999, fontSize: 10,
 fontWeight: 800, textTransform: "uppercase",
 };
}

function fmtAge(h) {
 if (h == null) return"—";
 if (h < 1) return `${Math.round(h * 60)} min`;
 if (h < 24) return `${h.toFixed(1)} h`;
 return `${Math.round(h / 24)} d`;
}

export default function LoyaltyAITab() {
 const [data, setData] = useState(null);
 const [winback, setWinback] = useState([]);
 const [loading, setLoading] = useState(true);
 const [generating, setGenerating] = useState(false);
 const [err, setErr] = useState("");

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const [r, w] = await Promise.all([
 api._client.get("/customer/loyalty-ai/insights"),
 api._client.get("/customer/loyalty-ai/top-winback-targets",
 { params: { limit: 30 } }),
 ]);
 setData(r.data);
 setWinback(w.data?.items || []);
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setLoading(false);
 }, []);

 useEffect(() =>{ load(); }, [load]);
 // iter215w — Recarrega quando uma nova base é importada (regra global)
 useEffect(() =>{
 const h = () =>load();
 window.addEventListener("loyalty-db-imported", h);
 return () =>window.removeEventListener("loyalty-db-imported", h);
 }, [load]);

 const regenerate = async () =>{
 setGenerating(true); setErr("");
 try {
 const r = await api._client.post(
"/customer/loyalty-ai/regenerate", { force: true },
 { timeout: 180000 }, // 3min — Claude pode demorar
);
 setData({
 cached: true, stale: false,
 generated_at: r.data.generated_at,
 age_hours: 0,
 model: r.data.model,
 summary: r.data.summary,
 insights: r.data.insights,
 });
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setGenerating(false);
 };

 if (loading) {
 return <div style={{ padding: 20, color:"#64748b" }}>
 Carregando análise IA…
 </div>;
 }

 const ins = data?.insights;
 const sum = data?.summary;
 const hasData = !!ins;

 return (
 <div style={{ display: "grid", gap: 16 }} data-testid="loyalty-ai-tab">
 {/* Header com info do modelo */}
 <div style={{
 display: "flex", justifyContent: "space-between",
 alignItems: "center", flexWrap: "wrap", gap: 8,
 }}>
 <div style={{ fontSize: 13, color:"#64748b" }}>
 Análise inteligente da base de clientes via{""}
 <b style={{ color:"#7c3aed" }}>Claude Sonnet 4.6</b>
 {""}(OpenRouter).
 Identifica winback, upgrade, retenção e gera plano de ação.
 </div>
 <button onClick={regenerate} disabled={generating}
 data-testid="loyalty-ai-regenerate"
 style={{
 border: 0, borderRadius: 8, padding:"8px 16px",
 fontSize: 12, fontWeight: 800, color: "white",
 background: generating
 ?"#94a3b8"
 : "linear-gradient(135deg, #7c3aed, #ec4899)",
 cursor: generating ?"wait" : "pointer",
 }}>
 {generating ?"Analisando com Claude…" :" Regenerar Análise"}
 </button>
 </div>

 {/* Estado vazio */}
 {!hasData && (
 <div style={{
 padding: 40, textAlign: "center", background: "white",
 border:"2px dashed #e2e8f0", borderRadius: 12,
 }}>
 <div style={{ fontSize: 56 }}></div>
 <div style={{ fontSize: 16, fontWeight: 700, marginTop: 12,
 color:"#0f172a" }}>
 Nenhuma análise gerada ainda
 </div>
 <div style={{ fontSize: 13, color:"#64748b", marginTop: 6 }}>
 Clique em <code>Regenerar Análise</code> pra Claude analisar sua base e
 sugerir as melhores oportunidades.
 </div>
 </div>
)}

 {err && (
 <div style={{
 background:"#fee2e2", color:"#7f1d1d",
 padding: 10, borderRadius: 8, fontSize: 13,
 }}>️ {err}</div>
)}

 {hasData && (
 <>
 {/* Metadados do report */}
 <div style={{
 fontSize: 11, color:"#64748b", display: "flex", gap: 12,
 flexWrap: "wrap", padding:"6px 12px", background:"#f1f5f9",
 borderRadius: 8, width: "fit-content",
 }}>
 <span>modelo: <b>{data.model}</b></span>
 <span>· geração há <b>{fmtAge(data.age_hours)}</b></span>
 {data.stale && <span style={{ color:"#dc2626", fontWeight: 800 }}>
 Stale (24h+)
 </span>}
 </div>

 {/* Health Score gigante + Executive Summary */}
 <div style={{
 display: "grid", gap: 16,
 gridTemplateColumns:"200px 1fr",
 }}>
 <div style={{
 padding: 24, borderRadius: 16,
 background: `linear-gradient(135deg, ${
 ins.health_score >= 70 ?"#22c55e"
 : ins.health_score >= 40 ?"#eab308"
 :"#dc2626"
 }, ${
 ins.health_score >= 70 ?"#15803d"
 : ins.health_score >= 40 ?"#a16207"
 :"#7f1d1d"
 })`,
 color: "white", textAlign: "center",
 }}>
 <div style={{
 fontSize: 11, textTransform: "uppercase",
 letterSpacing: 1, opacity: 0.85, fontWeight: 800,
 }}>Health Score</div>
 <div style={{ fontSize: 56, fontWeight: 900, lineHeight: 1,
 marginTop: 4 }}>
 {ins.health_score ??"—"}
 </div>
 <div style={{ fontSize: 11, opacity: 0.85, marginTop: 4 }}>/ 100</div>
 </div>
 <div style={{
 padding: 20, background: "white", borderRadius: 16,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{
 fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5,
 color:"#64748b", fontWeight: 800,
 }}>Resumo Executivo</div>
 <div style={{ fontSize: 14, marginTop: 8, lineHeight: 1.6,
 color:"#0f172a" }}>
 {ins.executive_summary}
 </div>
 {sum && (
 <div style={{ marginTop: 12, fontSize: 11, color:"#64748b",
 display: "flex", gap: 12, flexWrap: "wrap" }}>
 <span>Base total: <b>{sum.total_base?.toLocaleString("pt-BR")}</b></span>
 <span>· Ativos: <b style={{ color:"#15803d" }}>
 {sum.total_active?.toLocaleString("pt-BR")}
 </b></span>
 <span>· Desativados: <b style={{ color:"#dc2626" }}>
 {sum.total_deactivated?.toLocaleString("pt-BR")}
 </b></span>
 <span>· Churn: <b style={{ color:"#dc2626" }}>{sum.churn_rate_pct}%</b></span>
 </div>
)}
 </div>
 </div>

 {/* Risk Alerts */}
 {ins.risk_alerts && ins.risk_alerts.length >0 && (
 <div style={{
 background:"#fef3c7", border:"1px solid #fcd34d",
 borderRadius: 12, padding:"12px 16px",
 }}>
 <div style={{ fontSize: 12, fontWeight: 800, color:"#78350f",
 marginBottom: 6 }}>
 ️ Alertas de Risco
 </div>
 <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12,
 color:"#78350f", lineHeight: 1.7 }}>
 {ins.risk_alerts.map((a, i) =><li key={i}>{a}</li>)}
 </ul>
 </div>
)}

 {/* 3 grupos: Winback / Retenção / Upgrade */}
 <div style={{
 display: "grid", gap: 16,
 gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
 }}>
 <OppCard title="️ Winback (Reconquistar)" accent="#ec4899"
 items={ins.top_winback_opportunities} />
 <OppCard title=" Retenção" accent="#0ea5e9"
 items={ins.top_retention_strategies} />
 <OppCard title="⬆️ Upgrade" accent="#7c3aed"
 items={ins.upgrade_opportunities} />
 </div>

 {/* 30-day action plan */}
 {ins["30_day_action_plan"] && (
 <div style={{
 background: "white", borderRadius: 12, padding: 16,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 14, fontWeight: 800, color:"#0f172a",
 marginBottom: 12 }}>
 Plano de Ação dos Próximos 30 Dias
 </div>
 <div style={{
 display: "grid", gap: 12,
 gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
 }}>
 {ins["30_day_action_plan"].map((w) =>(
 <div key={w.week} style={{
 padding: 12, background:"#f8fafc", borderRadius: 8,
 borderLeft:"3px solid #7c3aed",
 }}>
 <div style={{
 fontSize: 10, fontWeight: 800, color:"#7c3aed",
 textTransform: "uppercase", letterSpacing: 0.5,
 }}>
 Semana {w.week}
 </div>
 <ul style={{ margin:"6px 0 0", paddingLeft: 16,
 fontSize: 11, lineHeight: 1.6,
 color:"#475569" }}>
 {(w.actions || []).map((a, i) =><li key={i}>{a}</li>)}
 </ul>
 </div>
))}
 </div>
 </div>
)}

 {/* Top alvos de winback (lista nominal) */}
 {winback.length >0 && (
 <div style={{
 background: "white", borderRadius: 12, overflow: "hidden",
 border:"1px solid #e2e8f0",
 }}>
 <div style={{
 padding:"12px 16px", borderBottom:"1px solid #e2e8f0",
 fontSize: 14, fontWeight: 800, color:"#0f172a",
 }}>
 Top {winback.length} Alvos Quentes — Lista Acionável
 <div style={{ fontSize: 11, fontWeight: 400, color:"#64748b",
 marginTop: 2 }}>
 Score = tempo de casa + ticket + recência do cancelamento
 </div>
 </div>
 <div style={{ overflowX: "auto" }}>
 <table style={{
 width:"100%", borderCollapse: "collapse",
 fontSize: 12, minWidth: 800,
 }}>
 <thead>
 <tr style={{ background:"#f8fafc",
 borderBottom:"1px solid #e2e8f0" }}>
 <Th>#</Th>
 <Th>Cliente</Th>
 <Th>Cidade / Plano</Th>
 <Th>Tempo casa</Th>
 <Th>Cancelou há</Th>
 <Th>Ticket</Th>
 <Th>Score</Th>
 <Th>Contato</Th>
 </tr>
 </thead>
 <tbody>
 {winback.map((it, idx) =>(
 <tr key={`${it.document}-${idx}`}
 data-testid={`loyalty-ai-winback-${it.document}`}
 style={{ borderBottom:"1px solid #f1f5f9" }}>
 <Td><b>{idx + 1}</b></Td>
 <Td>
 <div style={{ fontWeight: 700 }}>{it.name}</div>
 <div style={{ fontSize: 10, color:"#64748b",
 fontFamily: "monospace" }}>
 {it.document}
 </div>
 </Td>
 <Td>
 <div>{it.city}</div>
 <div style={{ fontSize: 10, color:"#64748b" }}>
 {it.plan_name}
 </div>
 </Td>
 <Td>{Math.round(it.tenure_months)}m</Td>
 <Td>{it.days_since_cancel}d</Td>
 <Td>R$ {Number(it.monthly_fee).toFixed(2)}</Td>
 <Td>
 <span style={{
 background: it.score >= 350 ?"#dc2626"
 : it.score >= 250 ?"#f97316" :"#64748b",
 color: "white",
 padding:"2px 8px", borderRadius: 999,
 fontSize: 11, fontWeight: 800,
 }}>
 {Math.round(it.score)}
 </span>
 </Td>
 <Td>
 <a href={`https://wa.me/${(it.phone ||"").replace(/\D/g,"")}`}
 target="_blank" rel="noreferrer"
 style={{ color:"#15803d", fontWeight: 700,
 textDecoration: "none" }}>
 WhatsApp
 </a>
 </Td>
 </tr>
))}
 </tbody>
 </table>
 </div>
 </div>
)}
 </>
)}
 </div>
);
}

function OppCard({ title, accent, items }) {
 return (
 <div style={{
 background: "white", borderRadius: 12, padding: 16,
 border:"1px solid #e2e8f0",
 borderTop: `3px solid ${accent}`,
 }}>
 <div style={{ fontSize: 14, fontWeight: 800, color:"#0f172a",
 marginBottom: 12 }}>
 {title}
 </div>
 <div style={{ display: "grid", gap: 10 }}>
 {(items || []).map((it, idx) =>(
 <div key={idx} style={{
 padding: 10, background:"#f8fafc", borderRadius: 8,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{
 display: "flex", justifyContent: "space-between",
 alignItems: "start", gap: 6,
 }}>
 <div style={{ fontSize: 13, fontWeight: 800, color:"#0f172a",
 lineHeight: 1.3 }}>
 {it.title}
 </div>
 <span style={priorityChip(it.priority)}>
 {it.priority}
 </span>
 </div>
 <div style={{ fontSize: 11, color:"#475569", marginTop: 4,
 lineHeight: 1.5 }}>
 {it.description}
 </div>
 {it.target_segment && (
 <div style={{ fontSize: 10, color:"#7c3aed", marginTop: 4,
 fontWeight: 700 }}>
 {it.target_segment}
 </div>
)}
 {it.estimated_impact && (
 <div style={{ fontSize: 10, color:"#15803d", marginTop: 2,
 fontWeight: 700 }}>
 {it.estimated_impact}
 </div>
)}
 {(it.action_steps || []).length >0 && (
 <details style={{ marginTop: 6 }}>
 <summary style={{ fontSize: 10, fontWeight: 700,
 color:"#64748b", cursor: "pointer" }}>
 Ver passos ({it.action_steps.length})
 </summary>
 <ol style={{ margin:"4px 0 0", paddingLeft: 16,
 fontSize: 10, color:"#475569",
 lineHeight: 1.5 }}>
 {it.action_steps.map((s, i) =><li key={i}>{s}</li>)}
 </ol>
 </details>
)}
 </div>
))}
 {(!items || items.length === 0) && (
 <div style={{
 fontSize: 11, color:"#94a3b8", padding: 12,
 textAlign: "center", fontStyle: "italic",
 }}>
 Nenhuma oportunidade identificada.
 </div>
)}
 </div>
 </div>
);
}

function Th({ children }) {
 return (
 <th style={{
 textAlign: "left", padding:"8px 12px", fontSize: 10,
 fontWeight: 800, color:"#475569", textTransform: "uppercase",
 letterSpacing: 0.5, whiteSpace: "nowrap",
 }}>{children}</th>
);
}

function Td({ children }) {
 return (
 <td style={{ padding:"10px 12px", verticalAlign: "top" }}>
 {children}
 </td>
);
}
