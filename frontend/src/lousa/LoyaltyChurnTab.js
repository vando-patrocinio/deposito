/* LoyaltyChurnTab — sub-aba" Análise de Churn".
 * KPIs agregados de TODOS os clientes desativados/cancelados:
 * - Tempo médio que permaneceram ativos (antes de cancelar)
 * - Taxa de churn (% da base que saiu)
 * - Distribuição em faixas (<6m, 6m-1a, 1-2a, 2-5a, 5+a)
 * - Breakdown por praça (count + tempo médio)
 * - Top motivos de cancelamento
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const TENURE_COLORS = {
"<6 meses":"#dc2626","6m-1ano":"#f97316","1-2 anos":"#eab308",
"2-5 anos":"#22c55e","5+ anos":"#0ea5e9",
};

function fmtMonths(m) {
 if (m == null || m === 0) return"—";
 const y = Math.floor(m / 12);
 const r = Math.round(m - y * 12);
 if (y < 1) return `${Math.round(m)} meses`;
 if (r === 0) return `${y} ${y === 1 ?"ano" : "anos"}`;
 return `${y}a ${r}m`;
}

function fmtYears(y) {
 if (y == null) return"—";
 return `${y.toFixed(1)}a`;
}

export default function LoyaltyChurnTab() {
 const [d, setD] = useState(null);
 const [returned, setReturned] = useState(null);
 const [loading, setLoading] = useState(true);
 const [err, setErr] = useState("");

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const [r1, r2] = await Promise.all([
 api._client.get("/customer/churn-kpis"),
 api._client.get("/customer/returned-clients", { params: { limit: 500 } }),
 ]);
 setD(r1.data);
 setReturned(r2.data);
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

 if (loading && !d) {
 return <div style={{ padding: 20, color:"#64748b" }}>Carregando KPIs…</div>;
 }
 if (err) {
 return <div style={{ background:"#fee2e2", color:"#7f1d1d",
 padding: 12, borderRadius: 8 }}>️ {err}</div>;
 }
 if (!d) return null;

 const totalBuckets = Object.values(d.buckets || {})
 .reduce((a, b) =>a + b, 0) || 1;

 return (
 <div style={{ display: "grid", gap: 16 }}
 data-testid="loyalty-churn-tab">
 <div style={{ fontSize: 13, color:"#64748b" }}>
 Análise agregada de TODOS os clientes desativados da base. Mostra
 quanto tempo eles ficaram ativos antes de sair, distribuição e
 principais motivos. Use pra calibrar ações de retenção.
 </div>

 {/* KPIs principais */}
 <div style={{ display: "grid", gap: 12,
 gridTemplateColumns: "repeat(auto-fit, minmax(180px,1fr))" }}>
 <Kpi title="Cancelamentos" value={d.total_deactivated}
 sub="histórico total" data-testid="kpi-deactivated" />
 <Kpi title="Taxa de Churn"
 value={`${d.churn_rate_pct}%`}
 sub={`${d.total_deactivated}/${d.total_active + d.total_deactivated}`}
 bg="linear-gradient(135deg,#fee2e2,#fecaca)" color="#7f1d1d" />
 <Kpi title=" Tempo médio ativo"
 value={fmtMonths(d.avg_tenure_months_before_cancel)}
 sub="antes de cancelar"
 bg="linear-gradient(135deg,#dbeafe,#bfdbfe)" color="#1e3a8a" />
 <Kpi title=" Mediana"
 value={fmtMonths(d.median_tenure_months)}
 sub="metade aguentou +" />
 </div>

 {/* Distribuição em faixas (bar chart) */}
 <div style={{ background: "white", border:"1px solid #e2e8f0",
 borderRadius: 12, padding: 14 }}>
 <div style={{ fontSize: 11, fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5,
 marginBottom: 12 }}>
 Distribuição por tempo até o cancelamento
 </div>
 <div style={{ display: "grid", gap: 6 }}>
 {Object.entries(d.buckets || {}).map(([label, count]) =>{
 const pct = Math.round(100 * count / totalBuckets);
 return (
 <div key={label}
 style={{ display: "flex", alignItems: "center", gap: 10 }}
 data-testid={`churn-bucket-${label}`}>
 <div style={{ width: 90, fontSize: 12, fontWeight: 700,
 color: TENURE_COLORS[label] }}>
 {label}
 </div>
 <div style={{ flex: 1, height: 22, background:"#f1f5f9",
 borderRadius: 6, overflow: "hidden" }}>
 <div style={{
 width: `${pct}%`, height:"100%",
 background: TENURE_COLORS[label],
 transition: "width .4s ease",
 }} />
 </div>
 <div style={{ minWidth: 60, fontSize: 12, fontWeight: 700,
 color:"#0f172a", textAlign: "right" }}>
 {count} ({pct}%)
 </div>
 </div>
);
 })}
 </div>
 </div>

 {/* iter215k — Clientes que voltaram (winback realizado) */}
 {returned && returned.total >0 && (
 <div data-testid="returned-clients-card" style={{
 background: "linear-gradient(135deg,#dcfce7,#bbf7d0)",
 border:"1px solid #86efac", borderRadius: 12, padding: 16,
 }}>
 <div style={{ display: "flex", justifyContent: "space-between",
 alignItems: "start", gap: 12, flexWrap: "wrap" }}>
 <div>
 <div style={{ fontSize: 11, fontWeight: 800, color:"#14532d",
 textTransform: "uppercase", letterSpacing: 0.5 }}>
 Clientes Recuperados (winback realizado)
 </div>
 <div style={{ marginTop: 8, fontSize: 13, color:"#14532d",
 lineHeight: 1.6, maxWidth: 700 }}>
 <b>{returned.total}</b>clientes ativos hoje já cancelaram antes e
 voltaram com novo cadastro (match por CPF). Eles acumulam{""}
 <b>{returned.total_past_records}</b>cadastros desativados
 no histórico — prova viva de que campanhas de winback funcionam.
 </div>
 </div>
 <div style={{ display: "flex", gap: 8 }}>
 <BigNum value={returned.total} sub="clientes" bg="#15803d" />
 <BigNum value={returned.vip_count} sub=" VIPs"
 bg="#a16207" />
 </div>
 </div>

 {/* Top 10 retornados */}
 {(returned.items || []).slice(0, 10).length >0 && (
 <div style={{ marginTop: 14, background: "rgba(255,255,255,0.6)",
 borderRadius: 8, overflow: "hidden" }}>
 <table style={{ width:"100%", borderCollapse: "collapse",
 fontSize: 11 }}>
 <thead>
 <tr style={{ background:"#15803d", color: "white" }}>
 <th style={thStyle}>#</th>
 <th style={thStyle}>Cliente</th>
 <th style={thStyle}>Plano atual</th>
 <th style={thStyle}>Lealdade real</th>
 <th style={thStyle}>Atual</th>
 <th style={thStyle}>Passado</th>
 <th style={thStyle}>Cadastros</th>
 </tr>
 </thead>
 <tbody>
 {returned.items.slice(0, 10).map((it, i) =>(
 <tr key={it.document}
 data-testid={`returned-row-${it.document}`}
 style={{ borderBottom:"1px solid rgba(0,0,0,0.05)" }}>
 <td style={tdStyle}><b>{i + 1}</b></td>
 <td style={tdStyle}>
 {it.is_vip &&""}
 <b>{it.name ||"—"}</b>
 <div style={{ fontSize: 10, color:"#15803d" }}>
 {it.current_city}
 </div>
 </td>
 <td style={tdStyle}>{it.current_plan ||"—"}</td>
 <td style={tdStyle}>
 <b style={{ fontSize: 14 }}>
 {fmtYears(it.total_loyalty_years)}
 </b>
 </td>
 <td style={tdStyle}>{fmtYears(it.current_tenure_years)}</td>
 <td style={tdStyle}>{fmtYears(it.past_total_years)}</td>
 <td style={tdStyle}>
 <span style={{ background:"#15803d", color: "white",
 padding:"2px 6px", borderRadius: 6,
 fontSize: 10, fontWeight: 800 }}>
 {it.past_count + 1}x
 </span>
 </td>
 </tr>
))}
 </tbody>
 </table>
 </div>
)}

 {returned.total >10 && (
 <div style={{ marginTop: 10, fontSize: 11, color:"#14532d" }}>
 ... e mais <b>{returned.total - 10}</b>clientes recuperados
 (veja todos no Ranking, filtrando por Cliente Retornado).
 </div>
)}
 </div>
)}

 {/* Por praça */}
 {d.by_praca?.length >0 && (
 <div style={{ background: "white", border:"1px solid #e2e8f0",
 borderRadius: 12, padding: 14 }}>
 <div style={{ fontSize: 11, fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5,
 marginBottom: 12 }}>
 Cancelamentos por praça
 </div>
 <table style={{ width:"100%", fontSize: 12,
 borderCollapse: "collapse" }}>
 <thead><tr style={{ borderBottom:"1px solid #e2e8f0" }}>
 <th style={th}>Praça</th>
 <th style={th}>Cancelamentos</th>
 <th style={th}>Tempo médio antes cancelar</th>
 </tr></thead>
 <tbody>
 {d.by_praca.map((p) =>(
 <tr key={p.praca}
 style={{ borderBottom:"1px solid #f1f5f9" }}>
 <td style={td}>{p.praca}</td>
 <td style={td}><b>{p.count}</b></td>
 <td style={td}>{fmtMonths(p.avg_months)}</td>
 </tr>
))}
 </tbody>
 </table>
 </div>
)}

 {/* Top motivos */}
 {d.top_reasons?.length >0 && (
 <div style={{ background: "white", border:"1px solid #e2e8f0",
 borderRadius: 12, padding: 14 }}>
 <div style={{ fontSize: 11, fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5,
 marginBottom: 12 }}>
 Top motivos de cancelamento
 </div>
 <div style={{ display: "grid", gap: 4 }}>
 {d.top_reasons.map((r, i) =>(
 <div key={i} style={{
 display: "flex", justifyContent: "space-between",
 padding:"8px 4px", borderBottom:"1px solid #f1f5f9",
 fontSize: 12,
 }}>
 <span style={{ color:"#0f172a" }}>
 <b>{i + 1}.</b>{r.reason}
 </span>
 <span style={{ fontWeight: 800, color:"#dc2626" }}>
 {r.count}
 </span>
 </div>
))}
 </div>
 </div>
)}

 {d.total_deactivated === 0 && (
 <div style={{ padding: 24, textAlign: "center", color:"#64748b",
 background:"#f8fafc", borderRadius: 12 }}>
 Nenhum cliente desativado na base — taxa de retenção 100%!
 </div>
)}
 </div>
);
}

const th = { textAlign: "left", padding:"8px 4px", fontSize: 10,
 fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5 };
const td = { padding:"10px 4px", color:"#0f172a" };

const thStyle = { textAlign: "left", padding:"6px 10px", fontSize: 10,
 fontWeight: 800, textTransform: "uppercase",
 letterSpacing: 0.5 };
const tdStyle = { padding:"6px 10px", color:"#0f172a",
 verticalAlign: "top" };

function BigNum({ value, sub, bg }) {
 return (
 <div style={{
 padding:"8px 14px", borderRadius: 10, background: bg,
 color: "white", textAlign: "center", minWidth: 70,
 }}>
 <div style={{ fontSize: 22, fontWeight: 900, lineHeight: 1 }}>
 {value}
 </div>
 <div style={{ fontSize: 10, opacity: 0.85, marginTop: 2 }}>{sub}</div>
 </div>
);
}

function Kpi({ title, value, sub, bg, color }) {
 return (
 <div data-testid={`kpi-${title.replace(/\s+/g,"-").toLowerCase()}`}
 style={{
 padding: 14, borderRadius: 12,
 background: bg ||"white",
 color: color ||"#0f172a",
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 10, fontWeight: 800, opacity: 0.7,
 textTransform: "uppercase", letterSpacing: 0.5 }}>
 {title}
 </div>
 <div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{value}</div>
 {sub && <div style={{ fontSize: 11, marginTop: 2, opacity: 0.8 }}>{sub}</div>}
 </div>
);
}
