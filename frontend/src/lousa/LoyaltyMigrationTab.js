/* LoyaltyMigrationTab — sub-aba "Migração de Plano".
 * Identifica clientes pagando por planos antigos quando há plano novo
 * com a MESMA faixa de preço e MAIOR velocidade na mesma região. Vira
 * uma lista de oportunidades de upgrade gratuito (fidelização + retenção).
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

function btnStyle(bg) {
 return {
 border: 0, borderRadius: 8, padding:"8px 14px",
 fontSize: 12, fontWeight: 700, color: "white", background: bg,
 cursor: "pointer",
 };
}

export default function LoyaltyMigrationTab() {
 const [data, setData] = useState(null);
 const [loading, setLoading] = useState(true);
 const [err, setErr] = useState("");
 const [minDelta, setMinDelta] = useState(50);
 const [limit, setLimit] = useState(200);

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const r = await api._client.get(
"/customer/plan-migration-opportunities",
 { params: { limit, min_savings_mbps: minDelta } },
);
 setData(r.data);
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setLoading(false);
 }, [limit, minDelta]);

 useEffect(() =>{ load(); }, [load]);
 // iter215w — Recarrega quando uma nova base é importada (regra global)
 useEffect(() =>{
 const h = () =>load();
 window.addEventListener("loyalty-db-imported", h);
 return () =>window.removeEventListener("loyalty-db-imported", h);
 }, [load]);

 const exportCSV = () =>{
 if (!data?.items) return;
 const head = ["name","document","phone","filial","current_plan",
"current_speed_mbps","best_plan","best_speed_mbps",
"delta_mbps","price_brl","tenure_years","is_vip"];
 const rows = data.items.map((it) =>head.map((k) =>
 `"${(it[k] ??"").toString().replace(/"/g, '""')}"`).join(","));
 const csv = [head.join(","), ...rows].join("\n");
 const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url; a.download = `oportunidades-upgrade-${Date.now()}.csv`;
 a.click(); URL.revokeObjectURL(url);
 };

 return (
 <div style={{ display: "grid", gap: 16 }}
 data-testid="loyalty-migration-tab">
 <div style={{ fontSize: 13, color:"#64748b" }}>
 Clientes pagando o MESMO preço por planos antigos quando existe um
 novo plano com velocidade maior disponível na sua região. Use pra
 upgrade gratuito — fideliza, valoriza e protege contra churn.
 </div>

 {/* Stats */}
 {data && (
 <div style={{ display: "grid", gap: 12,
 gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
 <Stat title="Oportunidades" value={data.count}
 sub={data.count === 0 ?"Nenhuma identificada" : null} />
 <Stat title=" VIPs elegíveis" value={data.vip_count}
 bg="linear-gradient(135deg,#fef3c7,#fde68a)"
 color="#78350f" />
 <Stat title=" Total de upgrade"
 value={`${(data.total_savings_mbps / 1000).toFixed(1)} GB`}
 sub="velocidade somada do parque" />
 </div>
)}

 {/* Filtros */}
 <div style={{
 display: "flex", gap: 8, flexWrap: "wrap",
 padding: 12, background: "white", borderRadius: 12,
 border:"1px solid #e2e8f0", alignItems: "center",
 }}>
 <label style={{ fontSize: 12, color:"#475569" }}>Ganho mínimo
 <select value={minDelta} onChange={(e) =>setMinDelta(+e.target.value)}
 data-testid="migration-min-delta"
 style={{ marginLeft: 6, padding:"4px 8px",
 border:"1px solid #cbd5e1", borderRadius: 6,
 fontSize: 12 }}>
 <option value={30}>+30 Mbps</option>
 <option value={50}>+50 Mbps</option>
 <option value={100}>+100 Mbps</option>
 <option value={200}>+200 Mbps</option>
 <option value={400}>+400 Mbps</option>
 </select>
 </label>
 <label style={{ fontSize: 12, color:"#475569" }}>Top
 <select value={limit} onChange={(e) =>setLimit(+e.target.value)}
 data-testid="migration-limit"
 style={{ marginLeft: 6, padding:"4px 8px",
 border:"1px solid #cbd5e1", borderRadius: 6,
 fontSize: 12 }}>
 <option value={100}>100</option>
 <option value={500}>500</option>
 <option value={1000}>1000</option>
 <option value={2000}>2000</option>
 </select>
 </label>
 <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
 <button onClick={load} disabled={loading}
 data-testid="migration-reload"
 style={btnStyle("#0f172a")}>
 {loading ?"…" : "Atualizar"}
 </button>
 <button onClick={exportCSV} disabled={!data?.items?.length}
 data-testid="migration-export-csv"
 style={btnStyle("#15803d")}>
 Exportar CSV
 </button>
 </div>
 </div>

 {err && (
 <div style={{
 background:"#fee2e2", color:"#7f1d1d",
 padding: 10, borderRadius: 8, fontSize: 13,
 }}>️ {err}</div>
)}

 {/* Tabela */}
 <div style={{
 background: "white", borderRadius: 12, overflow: "hidden",
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ overflowX: "auto" }}>
 <table style={{ width:"100%", borderCollapse: "collapse",
 fontSize: 12, minWidth: 1000 }}>
 <thead>
 <tr style={{ background:"#f8fafc",
 borderBottom:"1px solid #e2e8f0" }}>
 <Th>Cliente</Th>
 <Th>Filial</Th>
 <Th>Preço</Th>
 <Th>Plano atual</Th>
 <Th>Upgrade disponível</Th>
 <Th>Ganho</Th>
 </tr>
 </thead>
 <tbody>
 {(data?.items || []).map((it) =>(
 <tr key={it.id}
 data-testid={`migration-row-${it.id}`}
 style={{
 borderBottom:"1px solid #f1f5f9",
 background: it.is_vip ?"rgba(254,243,199,0.4)" : "white",
 }}>
 <Td>
 <div style={{ fontWeight: 700, color:"#0f172a" }}>
 {it.is_vip &&""}{it.name}
 </div>
 <div style={{ fontSize: 10, color:"#64748b",
 fontFamily: "monospace" }}>
 {it.document} {it.tenure_years
 ? `· ${Math.floor(it.tenure_years)}a cliente`
 :""}
 </div>
 </Td>
 <Td>{it.filial ||"—"}</Td>
 <Td>
 <b style={{ color:"#15803d" }}>
 R$ {it.price_brl.toFixed(2).replace(".",",")}
 </b>
 </Td>
 <Td>
 <div style={{ fontFamily: "monospace", fontSize: 11,
 color:"#64748b" }}>
 {it.current_plan}
 </div>
 <div style={{ fontWeight: 800, color:"#dc2626",
 fontSize: 14, marginTop: 2 }}>
 {it.current_speed_mbps} Mbps
 </div>
 </Td>
 <Td>
 <div style={{ fontFamily: "monospace", fontSize: 11,
 color:"#64748b" }}>
 {it.best_plan}
 </div>
 <div style={{ fontWeight: 800, color:"#15803d",
 fontSize: 14, marginTop: 2 }}>
 → {it.best_speed_mbps} Mbps
 </div>
 </Td>
 <Td>
 <span style={{
 padding:"4px 10px", borderRadius: 999,
 background: "linear-gradient(135deg,#bbf7d0,#86efac)",
 color:"#14532d", fontWeight: 800, fontSize: 13,
 }}>
 +{it.delta_mbps} Mbps
 </span>
 </Td>
 </tr>
))}
 {(!data?.items || data.items.length === 0) && !loading && (
 <tr><td colSpan={6} style={{ padding: 24, textAlign: "center",
 color:"#64748b" }}>
 Nenhuma oportunidade de upgrade encontrada com os filtros atuais.
 </td></tr>
)}
 </tbody>
 </table>
 </div>
 </div>
 </div>
);
}

function Stat({ title, value, sub, bg, color }) {
 return (
 <div style={{
 padding: 14, borderRadius: 12,
 background: bg ||"white",
 color: color ||"#0f172a",
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 10, fontWeight: 800,
 textTransform: "uppercase", letterSpacing: 0.5,
 opacity: 0.7 }}>{title}</div>
 <div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{value}</div>
 {sub && <div style={{ fontSize: 11, marginTop: 2, opacity: 0.8 }}>{sub}</div>}
 </div>
);
}

function Th({ children }) {
 return (
 <th style={{ textAlign: "left", padding:"10px 12px",
 fontSize: 10, fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5,
 whiteSpace: "nowrap" }}>
 {children}
 </th>
);
}

function Td({ children }) {
 return (
 <td style={{ padding:"10px 12px", verticalAlign: "top" }}>
 {children}
 </td>
);
}
