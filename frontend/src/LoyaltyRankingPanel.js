/* LoyaltyRankingPanel — ranking dos clientes mais antigos (fidelidade).
 *
 * Pra criar campanhas/promoções/brindes pra clientes VIP (5+ anos) e
 * identificar relacionamentos de longa data. Mostra:
 * - Cards de stats (total ativos, VIPs, cliente mais antigo, % VIP)
 * - Tabela ranqueada com nome, plano, filial, contato, tempo
 * - Filtros: filial, plano, tempo mínimo
 * - Botão" Exportar CSV" para campanhas externas
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Crown, Users, Database, Brain, MapPin, Heart, ArrowLeftRight, TrendingDown } from "lucide-react";
import { api } from "@/api";
import LoyaltyDeactivatedTab from "@/lousa/LoyaltyDeactivatedTab";
import LoyaltyMigrationTab from "@/lousa/LoyaltyMigrationTab";
import LoyaltyChurnTab from "@/lousa/LoyaltyChurnTab";
import LoyaltyDatabaseTab from "@/lousa/LoyaltyDatabaseTab";
import LoyaltyAITab from "@/lousa/LoyaltyAITab";
import LoyaltyOpportunitiesAITab from "@/lousa/LoyaltyOpportunitiesAITab";
import LoyaltyWinbackReadyTab from "@/lousa/LoyaltyWinbackReadyTab";

const COLOR_VIP_BG ="linear-gradient(135deg,#fef3c7,#fde68a)";
const COLOR_VIP_TXT ="#78350f";

function fmtTenure(years) {
 if (years == null) return"—";
 const y = Math.floor(years);
 const m = Math.round((years - y) * 12);
 if (y < 1) return `${m} ${m === 1 ?"mês" : "meses"}`;
 if (m === 0) return `${y} ${y === 1 ?"ano" : "anos"}`;
 return `${y}a ${m}m`;
}

function fmtPhone(p) {
 const d = (p ||"").replace(/\D/g,"");
 if (d.length === 11) return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`;
 if (d.length === 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`;
 return p ||"—";
}

export default function LoyaltyRankingPanel() {
 const [tab, setTab] = useState("ranking");
 // iter215w — banner global "base atualizada" (3s) após import
 const [refreshBanner, setRefreshBanner] = useState(null);
 React.useEffect(() =>{
 const handler = (e) =>{
 const s = e.detail?.stats || {};
 setRefreshBanner(
 `✓ Base atualizada: ${s.rows_imported || 0} linhas processadas. ` +
 `Todas as abas foram recarregadas automaticamente.`,
);
 setTimeout(() =>setRefreshBanner(null), 6000);
 };
 window.addEventListener("loyalty-db-imported", handler);
 return () =>window.removeEventListener("loyalty-db-imported", handler);
 }, []);

 return (
 <div style={{ display: "grid", gap: 16, padding:"0 4px" }}>
 <div>
 <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800,
 color: "var(--text-primary)" }}>
 Clientes Fidelidade
 </h1>
 <div style={{ fontSize: 11, color:"#64748b", marginTop: 4 }}>
                 <b>Regra global:</b> toda importação na aba <code>Base de Dados</code>{" "}
                atualiza automaticamente todas as outras abas.
 </div>
 </div>
 {refreshBanner && (
 <div data-testid="loyalty-refresh-banner" style={{
 background: "linear-gradient(135deg,#16a34a,#14532d)",
 color: "white", padding:"10px 14px", borderRadius: 10,
 fontSize: 12, fontWeight: 700,
 boxShadow:"0 4px 12px rgba(22,163,74,0.3)",
 }}>
 {refreshBanner}
 </div>
)}
 {/* Tabs */}
 <div role="tablist" style={{
 display: "flex", gap: 4, borderBottom:"2px solid #e2e8f0",
 }}>
                 <TabBtn active={tab ==="ranking"} onClick={() =>setTab("ranking")}
                  testid="loyalty-tab-ranking">
                  <Crown size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Ranking Antiguidade
                </TabBtn>
                <TabBtn active={tab ==="migration"} onClick={() =>setTab("migration")}
                  testid="loyalty-tab-migration">
                  <ArrowLeftRight size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Migração de Plano
                </TabBtn>
                <TabBtn active={tab ==="deactivated"} onClick={() =>setTab("deactivated")}
                  testid="loyalty-tab-deactivated">
                  <Users size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Desativados
                </TabBtn>
                <TabBtn active={tab ==="churn"} onClick={() =>setTab("churn")}
                  testid="loyalty-tab-churn">
                  <TrendingDown size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Análise de Churn
                </TabBtn>
                <TabBtn active={tab ==="db"} onClick={() =>setTab("db")}
                  testid="loyalty-tab-db">
                  <Database size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Base de Dados
                </TabBtn>
                <TabBtn active={tab ==="ai"} onClick={() =>setTab("ai")}
                  testid="loyalty-tab-ai">
                  <Brain size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Clientes IA
                </TabBtn>
                <TabBtn active={tab ==="opp_ai"} onClick={() =>setTab("opp_ai")}
                  testid="loyalty-tab-opp-ai">
                  <MapPin size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Oportunidades IA
                </TabBtn>
                <TabBtn active={tab ==="winback"} onClick={() =>setTab("winback")}
                  testid="loyalty-tab-winback">
                  <Heart size={14} strokeWidth={2} style={{ marginRight: 6, verticalAlign: -2 }} />
                  Quem Voltar?
                </TabBtn>
 </div>
 {tab ==="ranking" && <RankingAntiguidadeTab />}
 {tab ==="migration" && <LoyaltyMigrationTab />}
 {tab ==="deactivated" && <LoyaltyDeactivatedTab />}
 {tab ==="churn" && <LoyaltyChurnTab />}
 {tab ==="db" && <LoyaltyDatabaseTab />}
 {tab ==="ai" && <LoyaltyAITab />}
 {tab ==="opp_ai" && <LoyaltyOpportunitiesAITab />}
 {tab ==="winback" && <LoyaltyWinbackReadyTab />}
 </div>
);
}

function TabBtn({ active, onClick, children, testid }) {
 return (
 <button
 onClick={onClick}
 data-testid={testid}
 role="tab"
 aria-selected={active}
 style={{
 border: 0,
 background: "transparent",
 padding:"10px 16px",
 fontSize: 13,
 fontWeight: 800,
 color: active ?"#0f172a" :"#64748b",
 borderBottom: active ?"3px solid #0f172a" :"3px solid transparent",
 marginBottom: -2,
 cursor: "pointer",
 }}
 >
 {children}
 </button>
);
}

function RankingAntiguidadeTab() {
 const [stats, setStats] = useState(null);
 const [items, setItems] = useState([]);
 const [loading, setLoading] = useState(true);
 const [err, setErr] = useState("");
 const [minYears, setMinYears] = useState(0);
 const [filial, setFilial] = useState("");
 const [limit, setLimit] = useState(100);
 // iter215k — filtro: só clientes que voltaram
 const [onlyReturned, setOnlyReturned] = useState(false);
 // iter215f — meta do backend: total disponível e quantos sem data
 const [meta, setMeta] = useState({ total_available: 0,
 without_install_date: 0 });

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const [s, r] = await Promise.all([
 api._client.get("/customer/loyalty-stats"),
 api._client.get("/customer/loyalty-ranking", {
 params: { limit, min_years: minYears, filial: filial || undefined,
 only_returned: onlyReturned || undefined,
 status: onlyReturned ?"all" : undefined },
 }),
 ]);
 setStats(s.data);
 setItems(r.data.items || []);
 setMeta({
 total_available: r.data.total_available || 0,
 without_install_date: r.data.without_install_date || 0,
 });
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setLoading(false);
 }, [limit, minYears, filial, onlyReturned]);

 useEffect(() =>{ load(); }, [load]);
 // iter215w — Recarrega quando uma nova base é importada (regra global)
 useEffect(() =>{
 const h = () =>load();
 window.addEventListener("loyalty-db-imported", h);
 return () =>window.removeEventListener("loyalty-db-imported", h);
 }, [load]);

 const exportCSV = () =>{
 const head = ["rank","name","document","phone","plan_name","filial",
"installation_date","tenure_years","is_vip","status",
"financial_status","pppoe_user"];
 const rows = items.map((it) =>head.map((k) =>`"${(it[k] ??"")
 .toString().replace(/"/g, '""')}"`).join(","));
 const csv = [head.join(","), ...rows].join("\n");
 const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url; a.download = `clientes-fidelidade-${Date.now()}.csv`;
 a.click(); URL.revokeObjectURL(url);
 };

 const filiaisUnique = useMemo(() =>{
 const s = new Set();
 items.forEach((i) =>i.filial && s.add(i.filial));
 return Array.from(s).sort();
 }, [items]);

 return (
 <div style={{ display: "grid", gap: 16 }}
 data-testid="loyalty-ranking-tab">
 <div style={{ fontSize: 13, color:"#64748b" }}>
 Identifique clientes de longa data pra campanhas, brindes e ações VIP.
 Clientes que cancelaram e retornaram têm o tempo total somado.
 </div>

 {/* Cards de stats */}
 {stats && (
 <div style={{ display: "grid", gap: 12,
 gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
 <StatCard title="Total ativos" value={stats.total_active} />
 <StatCard title=" VIPs (5+ anos)" value={stats.vip_count}
 sub={`${stats.vip_pct}% da base`}
 bg={COLOR_VIP_BG} color={COLOR_VIP_TXT} />
 <StatCard title=" Cliente mais antigo"
 value={`${stats.oldest_years} anos`} />
 <div style={{
 padding: 14, background: "white", borderRadius: 12,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 10, color:"#64748b", fontWeight: 800,
 textTransform: "uppercase", letterSpacing: 0.5 }}>
 Distribuição
 </div>
 <div style={{ marginTop: 6, display: "flex", gap: 4,
 flexWrap: "wrap" }}>
 {Object.entries(stats.buckets || {}).map(([label, v]) =>(
 <div key={label} style={{
 fontSize: 10, padding:"2px 8px", borderRadius: 999,
 background:"#f1f5f9", color:"#475569", fontWeight: 700,
 }}>
 {label}: <b style={{ color:"#0f172a" }}>{v}</b>
 </div>
))}
 </div>
 </div>
 </div>
)}

 {/* Filtros */}
 <div style={{
 display: "flex", gap: 8, flexWrap: "wrap",
 padding: 12, background: "white", borderRadius: 12,
 border:"1px solid #e2e8f0", alignItems: "center",
 }}>
 <label style={{ fontSize: 12, color:"#475569" }}>Top
 <select value={limit} onChange={(e) =>setLimit(+e.target.value)}
 data-testid="loyalty-limit"
 style={{ marginLeft: 6, padding:"4px 8px",
 border:"1px solid #cbd5e1", borderRadius: 6,
 fontSize: 12 }}>
 <option value={50}>50</option>
 <option value={100}>100</option>
 <option value={200}>200</option>
 <option value={500}>500</option>
 <option value={1000}>1000</option>
 <option value={3000}>3000</option>
 <option value={5000}>Todos (5k)</option>
 </select>
 </label>
 <label style={{ fontSize: 12, color:"#475569" }}>Mín. anos
 <input type="number" value={minYears} min={0} step={1}
 onChange={(e) =>setMinYears(+e.target.value || 0)}
 data-testid="loyalty-min-years"
 style={{ marginLeft: 6, padding:"4px 8px", width: 60,
 border:"1px solid #cbd5e1", borderRadius: 6,
 fontSize: 12 }} />
 </label>
 <label style={{ fontSize: 12, color:"#475569" }}>Filial
 <input value={filial} onChange={(e) =>setFilial(e.target.value)}
 placeholder="(todas)"
 data-testid="loyalty-filial"
 list="loyalty-filiais"
 style={{ marginLeft: 6, padding:"4px 8px",
 border:"1px solid #cbd5e1", borderRadius: 6,
 fontSize: 12 }} />
 <datalist id="loyalty-filiais">
 {filiaisUnique.map((f) =><option key={f} value={f} />)}
 </datalist>
 </label>
 {/* iter215k — filtro de retornados */}
 <label data-testid="loyalty-only-returned-label"
 style={{
 fontSize: 12, color: onlyReturned ?"#15803d" :"#475569",
 fontWeight: onlyReturned ? 800 : 400,
 cursor: "pointer", display: "inline-flex",
 alignItems: "center", gap: 4,
 background: onlyReturned ?"#dcfce7" : "transparent",
 padding:"4px 10px", borderRadius: 6,
 border: `1px solid ${onlyReturned ?"#86efac" :"#cbd5e1"}`,
 }}>
 <input type="checkbox" checked={onlyReturned}
 onChange={(e) =>setOnlyReturned(e.target.checked)}
 data-testid="loyalty-only-returned"
 style={{ accentColor:"#15803d" }} />
 Só retornados
 </label>
 <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
 <button onClick={load} disabled={loading}
 data-testid="loyalty-reload"
 style={btnStyle("#0f172a")}>
 {loading ?"Carregando…" : "Atualizar"}
 </button>
 <button onClick={exportCSV} disabled={items.length === 0}
 data-testid="loyalty-export-csv"
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

 {/* iter215f — Aviso de clientes Atlaz sem data de instalação */}
 {meta.without_install_date >0 && (
 <div data-testid="loyalty-no-date-warning"
 style={{
 background:"#fef3c7", color:"#78350f",
 padding:"10px 14px", borderRadius: 8, fontSize: 12,
 border:"1px solid #fcd34d", lineHeight: 1.5,
 }}>
 <b>{meta.without_install_date}</b>de <b>{meta.total_available}</b>clientes
 sem data de instalação cadastrada (Atlaz não fornece). Eles aparecem
 no fim da lista. Importe uma planilha CPF + data de instalação pra
 enriquecer o ranking.
 </div>
)}

 {/* Tabela ranqueada */}
 <div style={{
 background: "white", borderRadius: 12, overflow: "hidden",
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ overflowX: "auto" }}>
 <table style={{ width:"100%", borderCollapse: "collapse",
 fontSize: 12, minWidth: 900 }}>
 <thead>
 <tr style={{ background:"#f8fafc",
 borderBottom:"1px solid #e2e8f0" }}>
 <Th>#</Th>
 <Th>Cliente</Th>
 <Th>Tempo</Th>
 <Th>Plano</Th>
 <Th>Filial</Th>
 <Th>Contato</Th>
 <Th>Status</Th>
 </tr>
 </thead>
 <tbody>
 {items.map((it) =>(
 <tr key={it.id}
 data-testid={`loyalty-row-${it.id}`}
 style={{
 borderBottom:"1px solid #f1f5f9",
 background: it.is_vip ?"rgba(254,243,199,0.4)" : "white",
 }}>
 <Td><b>{it.rank}</b></Td>
 <Td>
 <div style={{ fontWeight: 700, color:"#0f172a",
 display: "flex", gap: 6, alignItems: "center",
 flexWrap: "wrap" }}>
 {it.is_vip &&""}{it.name}
 {it.returned && (
 <span title={`Cliente retornou — ${it.returned_count} contratos somados (passado: ${it.past_tenure_years || 0}a)`}
 style={{
 fontSize: 9, padding:"1px 6px", borderRadius: 999,
 background:"#15803d", color: "white",
 fontWeight: 800,
 }}>
 {it.returned_count}x
 {it.past_tenure_years >0
 ? ` · +${it.past_tenure_years.toFixed(1)}a passado`
 :""}
 </span>
)}
 </div>
 <div style={{ fontSize: 10, color:"#64748b",
 fontFamily: "monospace" }}>
 {it.document} {it.external_code ? `· ${it.external_code}` :""}
 </div>
 </Td>
 <Td>
 <div style={{ fontWeight: 800,
 color: it.is_vip ?"#92400e" :"#0f172a" }}>
 {fmtTenure(it.tenure_years)}
 </div>
 <div style={{ fontSize: 10, color:"#64748b" }}>
 desde {(it.installation_date ||"").slice(0, 10)}
 </div>
 </Td>
 <Td>{it.plan_name ||"—"}</Td>
 <Td>{it.filial ||"—"}</Td>
 <Td>
 <div>{fmtPhone(it.phone)}</div>
 <div style={{ fontSize: 10, color:"#64748b" }}>
 {it.email ||""}
 </div>
 </Td>
 <Td>
 <span style={{
 padding:"2px 8px", borderRadius: 6, fontSize: 10,
 fontWeight: 700,
 background: it.status ==="ATIVO" ?"#dcfce7" :"#fee2e2",
 color: it.status ==="ATIVO" ?"#166534" :"#991b1b",
 }}>{it.status}</span>
 </Td>
 </tr>
))}
 {items.length === 0 && !loading && (
 <tr><td colSpan={7} style={{ padding: 24, textAlign: "center",
 color:"#64748b" }}>
 Nenhum cliente encontrado com os filtros atuais.
 </td></tr>
)}
 </tbody>
 </table>
 </div>
 </div>
 </div>
);
}

function btnStyle(bg) {
 return {
 border: 0, borderRadius: 8, padding:"8px 14px",
 fontSize: 12, fontWeight: 700, color: "white", background: bg,
 cursor: "pointer",
 };
}

function StatCard({ title, value, sub, bg, color }) {
 return (
 <div style={{
 padding: 14, borderRadius: 12,
 background: bg ||"white",
 color: color ||"#0f172a",
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 10, fontWeight: 800,
 textTransform: "uppercase", letterSpacing: 0.5,
 opacity: 0.7 }}>
 {title}
 </div>
 <div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>
 {value}
 </div>
 {sub && (
 <div style={{ fontSize: 11, marginTop: 2, opacity: 0.8 }}>{sub}</div>
)}
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
