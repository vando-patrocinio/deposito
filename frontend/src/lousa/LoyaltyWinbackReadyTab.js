/* LoyaltyWinbackReadyTab — sub-aba" Quem Voltar?"
 *
 * IA Claude 4.6 analisa quem está na hora ideal de receber promoção
 * pra voltar a ser cliente, baseado em:
 * - Cancelamento recente (14-540 dias)
 * - Histórico de pagamentos (títulos pagos)
 * - Resolução de chamados (relacionamento positivo)
 * - Sem títulos vencidos (não foi calote)
 * - Pelo menos 1 telefone válido
 *
 * Mostra:
 * - Resumo executivo + 3 tiers (A/B/C) com oferta sugerida
 * - Top 50 candidatos com tier + score + oferta personalizada
 * - Comparativo cancelamentos x novos clientes por mês
 *
 * iter215t
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const TIER_STYLES = {
 A: { bg:"#dc2626", color: "white", label:" Tier A — Imediato" },
 B: { bg:"#ea580c", color: "white", label:" Tier B — Promocional" },
 C: { bg:"#ca8a04", color: "white", label:" Tier C — Cuidado" },
};

const MONTHS_PT = ["Jan","Fev","Mar","Abr","Mai","Jun",
"Jul","Ago","Set","Out","Nov","Dez"];

function fmtAge(h) {
 if (h == null) return"—";
 if (h < 1) return `${Math.round(h * 60)} min`;
 if (h < 24) return `${h.toFixed(1)} h`;
 return `${Math.round(h / 24)} d`;
}

export default function LoyaltyWinbackReadyTab() {
 const [data, setData] = useState(null);
 const [series, setSeries] = useState(null);
 const [loading, setLoading] = useState(true);
 const [generating, setGenerating] = useState(false);
 const [err, setErr] = useState("");
 const [tierFilter, setTierFilter] = useState("");

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const [r, s] = await Promise.all([
 api._client.get("/customer/loyalty-ai/winback-ready"),
 api._client.get("/customer/loyalty/tickets-vs-cancellations",
 { params: { months: 13 } }),
 ]);
 if (r.data?.cached) setData(r.data);
 setSeries(s.data);
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
"/customer/loyalty-ai/winback-ready", {},
 { timeout: 240000 },
);
 setData({ cached: true, age_hours: 0, ...r.data });
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setGenerating(false);
 };

 if (loading) {
 return <div style={{ padding: 20, color:"#64748b" }}>Carregando…</div>;
 }

 const ins = data?.insights;
 const tiers = ins?.tiers || {};
 const top = data?.top || [];
 const filteredTop = tierFilter
 ? top.filter((t) =>t.ai_tier === tierFilter)
 : top;

 return (
 <div style={{ display: "grid", gap: 16 }}
 data-testid="loyalty-winback-ready-tab">
 <div style={{ fontSize: 13, color:"#64748b" }}>
 IA <b style={{ color:"#7c3aed" }}>Claude Sonnet 4.6</b>analisa
 ex-clientes (cancelados 14-540 dias) baseado em pagamentos, chamados
 e relacionamento, classifica em 3 tiers e sugere oferta personalizada.
 </div>

 {/* Header + ação */}
 <div style={{ display: "flex", justifyContent: "space-between",
 alignItems: "center", flexWrap: "wrap", gap: 8 }}>
 <div style={{ fontSize: 11, color:"#64748b", display: "flex",
 gap: 12, flexWrap: "wrap" }}>
 {data && (
 <>
 <span>modelo: <b>{data.model}</b></span>
 <span>· {data.total_eligible} elegíveis</span>
 <span>· análise há <b>{fmtAge(data.age_hours)}</b></span>
 </>
)}
 </div>
 <button onClick={regenerate} disabled={generating}
 data-testid="winback-regenerate"
 style={{
 border: 0, borderRadius: 8, padding:"8px 16px",
 fontSize: 12, fontWeight: 800, color: "white",
 background: generating ?"#94a3b8"
 : "linear-gradient(135deg,#7c3aed,#ec4899)",
 cursor: generating ?"wait" : "pointer",
 }}>
 {generating ?"IA Analisando…" :" Regenerar análise IA"}
 </button>
 </div>

 {/* Série mensal cancels x novos */}
 {series && (
 <div style={{
 background: "white", borderRadius: 12, padding: 14,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 12, fontWeight: 800, color:"#475569",
 marginBottom: 8 }}>
 Cancelamentos x Novos clientes — últimos {(series.series || []).length} meses
 </div>
 <div style={{ display: "flex", alignItems: "flex-end", gap: 4,
 height: 130, borderBottom:"1px solid #e2e8f0" }}>
 {(series.series || []).map((s) =>{
 const maxV = Math.max(...series.series.map(
 (x) =>Math.max(x.cancellations, x.new_customers)), 1);
 return (
 <div key={s.ym} style={{ flex: 1, display: "flex",
 alignItems: "flex-end", gap: 1 }}>
 <div title={`${s.label}: ${s.new_customers} novos`}
 style={{
 flex: 1,
 height: `${(s.new_customers / maxV) * 100}%`,
 background: "linear-gradient(180deg,#16a34a,#14532d)",
 borderRadius:"3px 3px 0 0",
 position: "relative", minHeight: 2,
 }}>
 <span style={{ position: "absolute", top: -14, left: 0,
 fontSize: 8, color:"#15803d",
 fontWeight: 800 }}>
 {s.new_customers}
 </span>
 </div>
 <div title={`${s.label}: ${s.cancellations} cancels`}
 style={{
 flex: 1,
 height: `${(s.cancellations / maxV) * 100}%`,
 background: "linear-gradient(180deg,#dc2626,#7f1d1d)",
 borderRadius:"3px 3px 0 0",
 position: "relative", minHeight: 2,
 }}>
 <span style={{ position: "absolute", top: -14, right: 0,
 fontSize: 8, color:"#7f1d1d",
 fontWeight: 800 }}>
 {s.cancellations}
 </span>
 </div>
 </div>
);
 })}
 </div>
 <div style={{ display: "flex", gap: 4, fontSize: 9,
 color:"#64748b", marginTop: 4, fontWeight: 700 }}>
 {(series.series || []).map((s) =>(
 <div key={s.ym} style={{ flex: 1, textAlign: "center" }}>
 {s.label}
 </div>
))}
 </div>
 <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 11,
 color:"#475569", flexWrap: "wrap" }}>
 <span><span style={{ display: "inline-block", width: 10, height: 10,
 background:"#16a34a", borderRadius: 2,
 marginRight: 4 }} />Novos</span>
 <span><span style={{ display: "inline-block", width: 10, height: 10,
 background:"#dc2626", borderRadius: 2,
 marginRight: 4 }} />Cancelamentos</span>
 <b style={{ marginLeft: "auto", color:"#15803d" }}>
 {series.current_quarter?.label}:{""}
 cancels {series.current_quarter?.cancellations}{""}
 · novos {series.current_quarter?.new_customers}{""}
 · net {series.current_quarter?.net_growth >= 0 ?"+" :""}
 {series.current_quarter?.net_growth}
 </b>
 </div>
 </div>
)}

 {err && (
 <div style={{
 background:"#fee2e2", color:"#7f1d1d",
 padding: 10, borderRadius: 8, fontSize: 13,
 }}>️ {err}</div>
)}

 {!ins && !err && (
 <div style={{
 padding: 40, textAlign: "center", background: "white",
 border:"2px dashed #e2e8f0", borderRadius: 12,
 }}>
 <div style={{ fontSize: 56 }}></div>
 <div style={{ fontSize: 16, fontWeight: 700, marginTop: 12 }}>
 Nenhuma análise gerada ainda
 </div>
 <div style={{ fontSize: 13, color:"#64748b", marginTop: 6 }}>
 Clique em <code>Regenerar análise IA</code> pra Claude identificar quem está na
 hora certa de receber promoção.
 </div>
 </div>
)}

 {ins && (
 <>
 {/* Sumário */}
 <div style={{
 padding: 14, background: "white", borderRadius: 12,
 border:"1px solid #e2e8f0", fontSize: 13, lineHeight: 1.6,
 color:"#0f172a",
 }}>
 <div style={{
 fontSize: 11, fontWeight: 800, textTransform: "uppercase",
 letterSpacing: 0.5, color:"#7c3aed", marginBottom: 6,
 }}>
 Análise da IA
 </div>
 {ins.summary}
 </div>

 {/* Tiers */}
 <div style={{
 display: "grid", gap: 12,
 gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
 }}>
 {Object.entries(tiers).map(([key, t]) =>{
 const tierLetter = key.includes("tier_a") ?"A"
 : key.includes("tier_b") ?"B" : "C";
 const st = TIER_STYLES[tierLetter];
 const isActive = tierFilter === tierLetter;
 return (
 <button key={key}
 onClick={() =>setTierFilter(
 isActive ?"" : tierLetter)}
 data-testid={`winback-tier-${tierLetter}`}
 style={{
 padding: 14, borderRadius: 12,
 background: st.bg, color: st.color,
 textAlign: "left", border: 0, cursor: "pointer",
 outline: isActive ?"3px solid #facc15" : "none",
 outlineOffset: 2,
 transform: isActive ?"scale(1.02)" : "scale(1)",
 transition: "transform 0.15s, outline 0.15s",
 }}>
 <div style={{ fontSize: 13, fontWeight: 900 }}>
 {st.label}
 </div>
 <div style={{ fontSize: 28, fontWeight: 900, lineHeight: 1,
 marginTop: 4 }}>
 {t.count}
 <span style={{ fontSize: 11, fontWeight: 600,
 opacity: 0.85, marginLeft: 4 }}>
 clientes
 </span>
 </div>
 <div style={{ fontSize: 11, opacity: 0.9, marginTop: 6,
 lineHeight: 1.4 }}>
 {t.description}
 </div>
 <div style={{ fontSize: 11, marginTop: 6,
 background: "rgba(0,0,0,0.2)",
 padding: 6, borderRadius: 6,
 lineHeight: 1.4 }}>
 <b>{t.recommended_offer}</b>
 </div>
 <div style={{ display: "flex", justifyContent: "space-between",
 marginTop: 6, fontSize: 11 }}>
 <span>{(t.approach ||"").slice(0, 40)}</span>
 <span>✓ {t.estimated_conversion}</span>
 </div>
 </button>
);
 })}
 </div>

 {/* Avisos */}
 {ins.global_warnings && ins.global_warnings.length >0 && (
 <div style={{
 background:"#fef3c7", border:"1px solid #fcd34d",
 borderRadius: 12, padding:"10px 14px", fontSize: 12,
 color:"#78350f",
 }}>
 <b>️ Alertas:</b>{""}
 <ul style={{ margin:"4px 0 0", paddingLeft: 18,
 lineHeight: 1.6 }}>
 {ins.global_warnings.map((w, i) =><li key={i}>{w}</li>)}
 </ul>
 </div>
)}

 {/* Top com filtro por tier */}
 <div style={{
 background: "white", borderRadius: 12, overflow: "hidden",
 border:"1px solid #e2e8f0",
 }}>
 <div style={{
 padding:"10px 16px", borderBottom:"1px solid #e2e8f0",
 fontSize: 13, fontWeight: 800, color:"#0f172a",
 display: "flex", justifyContent: "space-between",
 alignItems: "center",
 }}>
 <span>Top {filteredTop.length} alvos
 {tierFilter && ` · Tier ${tierFilter}`}
 </span>
 {tierFilter && (
 <button onClick={() =>setTierFilter("")}
 style={{
 background:"#f1f5f9", border: 0,
 padding:"4px 10px", borderRadius: 6,
 fontSize: 10, fontWeight: 700, cursor: "pointer",
 }}>
 ✕ Limpar filtro
 </button>
)}
 </div>
 <div style={{ overflowX: "auto" }}>
 <table style={{ width:"100%", borderCollapse: "collapse",
 fontSize: 12, minWidth: 1100 }}>
 <thead>
 <tr style={{ background:"#f8fafc",
 borderBottom:"1px solid #e2e8f0" }}>
 <Th>Tier</Th>
 <Th>Cliente</Th>
 <Th>Plano</Th>
 <Th>Pagto/Chamado</Th>
 <Th>Cancelou há</Th>
 <Th>Score</Th>
 <Th>Oferta IA</Th>
 <Th>Telefones</Th>
 </tr>
 </thead>
 <tbody>
 {filteredTop.map((c, i) =>{
 const st = TIER_STYLES[c.ai_tier] || TIER_STYLES.B;
 return (
 <tr key={c.document}
 data-testid={`winback-row-${c.document}`}
 style={{ borderBottom:"1px solid #f1f5f9" }}>
 <Td>
 <span style={{
 background: st.bg, color: st.color,
 padding:"2px 8px", borderRadius: 999,
 fontSize: 11, fontWeight: 900,
 }}>{c.ai_tier ||"?"}</span>
 </Td>
 <Td>
 <b>{c.name}</b>
 <div style={{ fontSize: 10, color:"#64748b" }}>
 {c.city}
 </div>
 </Td>
 <Td>
 {c.plan_name}
 <div style={{ fontSize: 10, color:"#64748b" }}>
 R$ {c.monthly_fee?.toFixed(2)}
 </div>
 </Td>
 <Td>
 <div style={{ fontSize: 11 }}>
 <b style={{ color:"#15803d" }}>{c.invoices_paid}</b>pagos ·{""}
 <b style={{ color:"#0ea5e9" }}>{c.tickets_closed}</b>fech.
 </div>
 {c.invoices_overdue >0 && (
 <div style={{ fontSize: 10, color:"#dc2626",
 fontWeight: 700 }}>
 {c.invoices_overdue} vencido(s)
 </div>
)}
 </Td>
 <Td>{c.days_since_cancel}d</Td>
 <Td>
 <span style={{
 background: c.score >= 70 ?"#dc2626"
 : c.score >= 60 ?"#ea580c"
 :"#64748b",
 color: "white",
 padding:"2px 8px", borderRadius: 999,
 fontSize: 11, fontWeight: 800,
 }}>{c.score?.toFixed(0)}</span>
 </Td>
 <Td>
 <div style={{ fontSize: 11, lineHeight: 1.4,
 maxWidth: 280 }}>
 {c.ai_offer ||"—"}
 </div>
 </Td>
 <Td>
 {(c.phones || []).map((p, k) =>(
 <a key={k} href={`https://wa.me/${p.replace(/\D/g,"")}`}
 target="_blank" rel="noreferrer"
 style={{
 display: "inline-block",
 color:"#15803d", fontWeight: 700,
 fontSize: 10, marginRight: 6,
 textDecoration: "none",
 }}>
 {p}
 </a>
))}
 </Td>
 </tr>
);
 })}
 </tbody>
 </table>
 </div>
 </div>
 </>
)}
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
