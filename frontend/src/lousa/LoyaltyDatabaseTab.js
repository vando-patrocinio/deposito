/* LoyaltyDatabaseTab — sub-aba "Base de Dados": lista todos os clientes
 * importados do arquivo XLSX (full contatos.xlsx). Permite busca, filtros
 * e upload de novo arquivo pra atualizar a base.
 *
 * iter215g — Importa via POST /api/customer/loyalty-db/import e exibe
 * os dados via GET /api/customer/loyalty-db.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";

const PAGE_SIZE = 50;

function fmtDate(iso) {
 if (!iso) return"—";
 try {
 const d = new Date(iso);
 return d.toLocaleDateString("pt-BR");
 } catch {
 return"—";
 }
}

function fmtPhone(p) {
 const d = (p ||"").toString().replace(/\D/g,"");
 if (d.length === 13) {
 // 55 + DDD + 9 dígitos
 return `(${d.slice(2,4)}) ${d.slice(4,9)}-${d.slice(9)}`;
 }
 if (d.length === 11) return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`;
 if (d.length === 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`;
 return p ||"—";
}

function fmtCPF(d) {
 const s = (d ||"").toString().replace(/\D/g,"");
 if (s.length === 11) {
 return `${s.slice(0,3)}.${s.slice(3,6)}.${s.slice(6,9)}-${s.slice(9)}`;
 }
 if (s.length === 14) {
 return `${s.slice(0,2)}.${s.slice(2,5)}.${s.slice(5,8)}/${s.slice(8,12)}-${s.slice(12)}`;
 }
 return d ||"—";
}

const STATUS_COLORS = {
"Ativo": { bg:"#dcfce7", txt:"#14532d" },
"Desativado": { bg:"#fee2e2", txt:"#7f1d1d" },
"Bloqueado": { bg:"#fef3c7", txt:"#78350f" },
"Interessado": { bg:"#dbeafe", txt:"#1e3a8a" },
"Fila": { bg:"#e0e7ff", txt:"#3730a3" },
"Observação": { bg:"#f3e8ff", txt:"#6b21a8" },
};

export default function LoyaltyDatabaseTab() {
 const [items, setItems] = useState([]);
 const [stats, setStats] = useState(null);
 const [total, setTotal] = useState(0);
 const [loading, setLoading] = useState(true);
 const [err, setErr] = useState("");
 const [q, setQ] = useState("");
 const [statusFilter, setStatusFilter] = useState("");
 const [cityFilter, setCityFilter] = useState("");
 const [page, setPage] = useState(0);

 const [uploading, setUploading] = useState(false);
 const [uploadMsg, setUploadMsg] = useState("");
 const fileInputRef = useRef(null);

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const [s, r] = await Promise.all([
 api._client.get("/customer/loyalty-db/stats"),
 api._client.get("/customer/loyalty-db", {
 params: {
 q: q || undefined,
 status: statusFilter || undefined,
 city: cityFilter || undefined,
 skip: page * PAGE_SIZE,
 limit: PAGE_SIZE,
 },
 }),
 ]);
 setStats(s.data);
 setItems(r.data.items || []);
 setTotal(r.data.total || 0);
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setLoading(false);
 }, [q, statusFilter, cityFilter, page]);

 useEffect(() =>{ load(); }, [load]);

 const handleUpload = async (e) =>{
 const file = e.target.files?.[0];
 if (!file) return;
 setUploading(true); setUploadMsg("Enviando arquivo…");
 const fd = new FormData();
 fd.append("file", file);
 try {
 const r = await api._client.post(
"/customer/loyalty-db/import", fd,
 { headers: {"Content-Type": "multipart/form-data" }, timeout: 300000 },
);
 const s = r.data?.stats || {};
 const inv = r.data?.cache_invalidated || {};
 setUploadMsg(
 `✓ Importado · ${s.rows_imported} linhas · ` +
 `${s.subscribers_matched} clientes batidos · ` +
 `${s.subscribers_install_date_filled} datas preenchidas` +
 (inv.deactivated_cache_cleared
 ? ` · caches invalidados (regra automática)`
 :""),
);
 setPage(0);
 await load();
 // iter215w — REGRA: ao terminar o import, dispara evento global pra
 // que outras abas (Desativados, Ranking, Churn, IA…) recarreguem.
 window.dispatchEvent(new CustomEvent("loyalty-db-imported", {
 detail: { filename: file.name, stats: s, cache: inv },
 }));
 } catch (ex) {
 setUploadMsg(`✗ Falha: ${ex?.response?.data?.detail || ex.message}`);
 }
 setUploading(false);
 if (fileInputRef.current) fileInputRef.current.value ="";
 };

 const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

 return (
 <div style={{ display: "grid", gap: 16 }}
 data-testid="loyalty-db-tab">
 <div style={{ fontSize: 13, color:"#64748b" }}>
 Base de dados completa importada do ERP/Atlaz. Os dados aqui
 enriquecem o ranking de antiguidade via match por CPF.
 </div>

 {/* KPIs */}
 {stats && (
 <div style={{
 display: "grid", gap: 12,
 gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
 }}>
 <KpiCard title="Total na base" value={stats.total} />
 {(stats.by_status || []).slice(0, 4).map((s) =>(
 <KpiCard key={s.status} title={s.status}
 value={s.count}
 bg={STATUS_COLORS[s.status]?.bg}
 color={STATUS_COLORS[s.status]?.txt} />
))}
 </div>
)}

 {/* Último import */}
 {stats?.last_import && (
 <div style={{
 fontSize: 11, color:"#64748b",
 background:"#f1f5f9", padding:"6px 12px",
 borderRadius: 8, display: "inline-block", width: "fit-content",
 }}>
 Último import:
 <b style={{ marginLeft: 4 }}>
 {stats.last_import.filename}
 </b>
 {" ·"}
 {fmtDate(stats.last_import.at)} {" ·"}
 <span>{stats.last_import.stats?.rows_imported || 0} linhas</span>
 </div>
)}

 {/* Toolbar */}
 <div style={{
 display: "flex", gap: 8, flexWrap: "wrap",
 padding: 12, background: "white", borderRadius: 12,
 border:"1px solid #e2e8f0", alignItems: "center",
 }}>
 <input value={q} onChange={(e) =>{ setQ(e.target.value); setPage(0); }}
 placeholder=" Buscar nome, CPF, login..."
 data-testid="loyalty-db-search"
 style={{
 padding:"6px 10px", fontSize: 12, minWidth: 280,
 border:"1px solid #cbd5e1", borderRadius: 6,
 }} />
 <select value={statusFilter}
 onChange={(e) =>{ setStatusFilter(e.target.value); setPage(0); }}
 data-testid="loyalty-db-status"
 style={{
 padding:"6px 10px", fontSize: 12,
 border:"1px solid #cbd5e1", borderRadius: 6,
 }}>
 <option value="">Todos os status</option>
 {(stats?.by_status || []).map((s) =>(
 <option key={s.status} value={s.status}>
 {s.status} ({s.count})
 </option>
))}
 </select>
 <select value={cityFilter}
 onChange={(e) =>{ setCityFilter(e.target.value); setPage(0); }}
 data-testid="loyalty-db-city"
 style={{
 padding:"6px 10px", fontSize: 12,
 border:"1px solid #cbd5e1", borderRadius: 6,
 }}>
 <option value="">Todas as cidades</option>
 {(stats?.by_city || []).map((c) =>(
 <option key={c.city} value={c.city}>
 {c.city} ({c.count})
 </option>
))}
 </select>

 <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
 <label data-testid="loyalty-db-upload-label"
 style={{
 ...btnStyle("#7c3aed"),
 display: "inline-flex", alignItems: "center", gap: 4,
 cursor: uploading ?"wait" : "pointer", opacity: uploading ? 0.6 : 1,
 }}>
 {uploading ?"Importando…" :"⬆ Importar XLSX"}
 <input ref={fileInputRef} type="file" accept=".xlsx,.xlsm"
 onChange={handleUpload} disabled={uploading}
 data-testid="loyalty-db-upload"
 style={{ display: "none" }} />
 </label>
 <button onClick={load} disabled={loading}
 data-testid="loyalty-db-reload"
 style={btnStyle("#0f172a")}>
 {loading ?"…" : "Atualizar"}
 </button>
 </div>
 </div>

 {uploadMsg && (
 <div data-testid="loyalty-db-upload-msg"
 style={{
 background: uploadMsg.startsWith("✗") ?"#fee2e2" :"#dbeafe",
 color: uploadMsg.startsWith("✗") ?"#7f1d1d" :"#1e3a8a",
 padding: 10, borderRadius: 8, fontSize: 12, fontWeight: 700,
 }}>
 {uploadMsg}
 </div>
)}

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
 <table style={{
 width:"100%", borderCollapse: "collapse",
 fontSize: 12, minWidth: 1100,
 }}>
 <thead>
 <tr style={{ background:"#f8fafc",
 borderBottom:"1px solid #e2e8f0" }}>
 <Th>Cliente</Th>
 <Th>CPF / Login</Th>
 <Th>Status</Th>
 <Th>Plano</Th>
 <Th>Cidade / Bairro</Th>
 <Th>Cadastro</Th>
 <Th>Ativação</Th>
 <Th>Instalação</Th>
 <Th>Contato</Th>
 </tr>
 </thead>
 <tbody>
 {items.map((it) =>{
 const sc = STATUS_COLORS[it.status] ||
 { bg:"#f1f5f9", txt:"#475569" };
 return (
 <tr key={`${it.document}-${it.external_id}`}
 data-testid={`loyalty-db-row-${it.document}`}
 style={{ borderBottom:"1px solid #f1f5f9" }}>
 <Td>
 <div style={{ fontWeight: 700, color:"#0f172a" }}>
 {it.name ||"—"}
 </div>
 {it.seller && (
 <div style={{ fontSize: 10, color:"#64748b" }}>
 Vendedor: {it.seller}
 </div>
)}
 </Td>
 <Td>
 <div style={{ fontFamily: "monospace", fontSize: 11 }}>
 {fmtCPF(it.document)}
 </div>
 <div style={{ fontSize: 10, color:"#64748b" }}>
 {it.login ||"—"}
 </div>
 </Td>
 <Td>
 <span style={{
 background: sc.bg, color: sc.txt,
 padding:"2px 8px", borderRadius: 999,
 fontSize: 10, fontWeight: 800,
 }}>
 {it.status ||"—"}
 </span>
 </Td>
 <Td>
 <div style={{ fontSize: 11 }}>
 {it.plan_name ||"—"}
 </div>
 {it.monthly_fee != null && (
 <div style={{ fontSize: 10, color:"#64748b" }}>
 R$ {Number(it.monthly_fee).toFixed(2)}
 </div>
)}
 </Td>
 <Td>
 <div style={{ fontSize: 11 }}>{it.city ||"—"}</div>
 <div style={{ fontSize: 10, color:"#64748b" }}>
 {it.district ||""}
 </div>
 </Td>
 <Td>{fmtDate(it.registration_date)}</Td>
 <Td>{fmtDate(it.activation_date)}</Td>
 <Td>
 {it.installation_date
 ? <b>{fmtDate(it.installation_date)}</b>
 : (it.cancellation_date
 ? <span style={{ color:"#dc2626" }}>
 Cancelou {fmtDate(it.cancellation_date)}
 </span>
 :"—")}
 </Td>
 <Td>{fmtPhone(it.phone1)}</Td>
 </tr>
);
 })}
 {items.length === 0 && !loading && (
 <tr>
 <td colSpan={9} style={{
 padding: 24, textAlign: "center", color:"#64748b",
 }}>
 {total === 0 && stats?.total === 0
 ?"Base vazia — faça upload do arquivo XLSX para começar."
 : "Nenhum resultado encontrado."}
 </td>
 </tr>
)}
 </tbody>
 </table>
 </div>
 {/* Paginação */}
 {total >PAGE_SIZE && (
 <div style={{
 display: "flex", justifyContent: "space-between",
 alignItems: "center", padding: 10, borderTop:"1px solid #e2e8f0",
 background:"#f8fafc",
 }}>
 <div style={{ fontSize: 11, color:"#64748b" }}>
 Mostrando {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} de {total}
 </div>
 <div style={{ display: "flex", gap: 6 }}>
 <button onClick={() =>setPage(Math.max(0, page - 1))}
 disabled={page === 0 || loading}
 data-testid="loyalty-db-prev"
 style={btnSmall(page === 0)}>← Anterior</button>
 <div style={{ fontSize: 11, color:"#475569", padding:"6px 8px" }}>
 pg {page + 1} / {pageCount}
 </div>
 <button onClick={() =>setPage(Math.min(pageCount - 1, page + 1))}
 disabled={page >= pageCount - 1 || loading}
 data-testid="loyalty-db-next"
 style={btnSmall(page >= pageCount - 1)}>Próximo →</button>
 </div>
 </div>
)}
 </div>
 </div>
);
}

function KpiCard({ title, value, sub, bg, color }) {
 return (
 <div style={{
 padding: 14, background: bg ||"white", borderRadius: 12,
 border:"1px solid #e2e8f0", color: color ||"#0f172a",
 }}>
 <div style={{
 fontSize: 10, fontWeight: 800, textTransform: "uppercase",
 letterSpacing: 0.5, opacity: 0.7,
 }}>{title}</div>
 <div style={{ fontSize: 22, fontWeight: 800, marginTop: 4 }}>
 {(value ?? 0).toLocaleString("pt-BR")}
 </div>
 {sub && <div style={{ fontSize: 11, marginTop: 2, opacity: 0.7 }}>{sub}</div>}
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

function btnSmall(disabled) {
 return {
 border:"1px solid #cbd5e1", borderRadius: 6, padding:"4px 10px",
 fontSize: 11, fontWeight: 700,
 background: disabled ?"#f1f5f9" : "white",
 color: disabled ?"#94a3b8" :"#0f172a",
 cursor: disabled ?"not-allowed" : "pointer",
 };
}

function Th({ children }) {
 return (
 <th style={{
 textAlign: "left", padding:"10px 12px", fontSize: 10,
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
