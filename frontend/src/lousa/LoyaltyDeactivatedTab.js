/* LoyaltyDeactivatedTab — sub-aba "Desativados": clientes que cancelaram,
 * agrupados por praça/filial. Útil pra ações de recuperação.
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

function fmtTenure(years) {
 if (years == null) return"—";
 const y = Math.floor(years);
 const m = Math.round((years - y) * 12);
 if (y < 1) return `${m}m`;
 if (m === 0) return `${y}a`;
 return `${y}a ${m}m`;
}

function fmtPhone(p) {
 const d = (p ||"").replace(/\D/g,"");
 if (d.length === 11) return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`;
 if (d.length === 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`;
 return p ||"—";
}

export default function LoyaltyDeactivatedTab() {
 const [data, setData] = useState(null);
 const [loading, setLoading] = useState(true);
 const [err, setErr] = useState("");
 const [praca, setPraca] = useState("");
 const [limit, setLimit] = useState(100); // iter215v — default 100 (era 200)
 // iter215 — disparo manual da sync Atlaz pra forçar a detecção de
 // cancelados via snapshot diff. Útil pós-deploy ou quando suspeitar
 // que algum cliente foi cancelado mas ainda não apareceu aqui.
 const [syncing, setSyncing] = useState(false);
 const [syncMsg, setSyncMsg] = useState("");
 // iter215p — filtro por período (clicar KPI). Valor ="YYYY-MM","Q","all"
 const [periodFilter, setPeriodFilter] = useState("all");
 // iter215y — quando user clica numa barra do gráfico, auto-seleciona
 // os clientes desse mês (com telefone válido). Guarda o YM pendente.
 const [pendingAutoSelectYm, setPendingAutoSelectYm] = useState(null);
 // iter215q — seleção pra disparo em massa
 const [selectedIds, setSelectedIds] = useState(() =>new Set());
 const [campaigns, setCampaigns] = useState([]);
 const [channels, setChannels] = useState([]);
 const [agents, setAgents] = useState([]);
 const [dispatchOpen, setDispatchOpen] = useState(false);
 const [dispatchForm, setDispatchForm] = useState({
 campaign_id:"", channel_id:"", agent_id:"", start_now: true,
 });
 const [dispatching, setDispatching] = useState(false);
 const [dispatchMsg, setDispatchMsg] = useState("");
 // iter215r — filtro "só com telefone" pra disparos
 const [onlyWithPhone, setOnlyWithPhone] = useState(false);
 // iter215u — modo de disparo: 'selected' ou 'all_filtered'
 const [dispatchMode, setDispatchMode] = useState("selected");

 // iter215y — quando filtrando por período específico, precisamos de TODA
 // a base pra mostrar todos os clientes do mês (não só os 100 mais recentes).
 const effectiveLimit = periodFilter ==="all" ? limit : 10000;

 const load = useCallback(async () =>{
 setLoading(true); setErr("");
 try {
 const r = await api._client.get("/customer/deactivated-list", {
 params: { praca: praca || undefined, limit: effectiveLimit },
 });
 setData(r.data);
 } catch (e) {
 setErr(e?.response?.data?.detail || e.message);
 }
 setLoading(false);
 }, [praca, effectiveLimit]);

 // iter215p — Filtra a lista de items pelo período selecionado
 // iter215r — também filtra por has_valid_phone se solicitado
 const filteredItems = React.useMemo(() =>{
 if (!data?.items) return [];
 let list = data.items;
 if (onlyWithPhone) {
 list = list.filter((it) =>it.has_valid_phone);
 }
 if (periodFilter ==="all") return list;
 return list.filter((it) =>{
 if (!it.deactivation_date) return false;
 const dt = new Date(it.deactivation_date);
 if (isNaN(dt)) return false;
 if (periodFilter.startsWith("Q")) {
 // Trimestre atual: 2026-Q2 = Abr-Mai-Jun de 2026
 const [yr, q] = periodFilter.slice(0, 4).split("-")[0]
 ? [periodFilter.slice(0, 4), periodFilter.slice(6)]
 : [String(dt.getFullYear()),"?"];
 const qNum = parseInt(q, 10);
 const y = parseInt(yr, 10);
 const month = dt.getMonth() + 1;
 return (
 dt.getFullYear() === y
 && month >= (qNum - 1) * 3 + 1 && month <= qNum * 3
);
 }
 // periodFilter ="YYYY-MM"
 const [y, m] = periodFilter.split("-").map(Number);
 return dt.getFullYear() === y && dt.getMonth() + 1 === m;
 });
 }, [data, periodFilter, onlyWithPhone]);

 useEffect(() =>{ load(); }, [load]);

 // iter215y — após o filtro por período recalcular, auto-seleciona os
 // clientes com telefone válido do mês clicado no gráfico (UX: 1 clique
 // pra filtrar + selecionar tudo pronto pra disparo). Espera o reload
 // do backend (limit=10000) terminar pra ter todos os clientes do mês.
 useEffect(() =>{
 if (!pendingAutoSelectYm) return;
 if (periodFilter !== pendingAutoSelectYm) return;
 if (loading) return; // espera o fetch terminar
 const valids = filteredItems.filter((it) =>it.has_valid_phone);
 setSelectedIds(new Set(valids.map((it) =>it.id)));
 setPendingAutoSelectYm(null);
 }, [pendingAutoSelectYm, periodFilter, filteredItems, loading]);

 // iter215w — Recarrega quando uma nova base é importada (regra global)
 useEffect(() =>{
 const handler = () =>load();
 window.addEventListener("loyalty-db-imported", handler);
 return () =>window.removeEventListener("loyalty-db-imported", handler);
 }, [load]);

 // iter215q — carrega campanhas/canais/agentes na abertura do popover
 const loadDispatchOptions = useCallback(async () =>{
 try {
 const [cps, chs, ags] = await Promise.all([
 api._client.get("/mass-messaging/campaigns"),
 api._client.get("/whatsapp-channels"),
 api._client.get("/customer/loyalty-dispatch/agents"),
 ]);
 setCampaigns((cps.data || []).filter(
 (c) =>c.status !=="done" && c.status !=="running"));
 setChannels(chs.data?.channels || []);
 setAgents(ags.data?.items || []);
 } catch (e) {
 setDispatchMsg(`✗ ${e?.response?.data?.detail || e.message}`);
 }
 }, []);

 // iter215q — Toggle seleção de cliente
 // iter215y — Toggle de período (compartilhado entre KPI cards + bar chart):
 // se já tá filtrando, limpa tudo. Senão, filtra E auto-seleciona os
 // clientes daquele período com telefone válido (1 clique = pronto p/ disparo).
 const togglePeriod = useCallback((key) =>{
 if (periodFilter === key) {
 setPeriodFilter("all");
 setSelectedIds(new Set());
 setPendingAutoSelectYm(null);
 } else {
 setPeriodFilter(key);
 setPendingAutoSelectYm(key);
 }
 }, [periodFilter]);

 const toggleSelect = (id) =>{
 setSelectedIds((prev) =>{
 const next = new Set(prev);
 if (next.has(id)) next.delete(id); else next.add(id);
 return next;
 });
 };
 const toggleSelectAll = () =>{
 // iter215r — só seleciona quem tem telefone válido
 const valids = filteredItems.filter((it) =>it.has_valid_phone);
 const allValidsSelected = valids.length >0
 && valids.every((it) =>selectedIds.has(it.id));
 if (allValidsSelected) {
 setSelectedIds(new Set());
 } else {
 setSelectedIds(new Set(valids.map((it) =>it.id)));
 }
 };

 const openDispatch = async () =>{
 setDispatchMode("selected");
 setDispatchOpen(true);
 setDispatchMsg("");
 await loadDispatchOptions();
 };

 // iter215u — modo bulk: dispara pra TODA a base filtrada
 const openDispatchAll = async () =>{
 setDispatchMode("all_filtered");
 setDispatchOpen(true);
 setDispatchMsg("");
 await loadDispatchOptions();
 };

 const runDispatch = async () =>{
 if (!dispatchForm.campaign_id) {
 setDispatchMsg("✗ Selecione uma campanha.");
 return;
 }
 setDispatching(true); setDispatchMsg("");
 try {
 if (dispatchMode ==="all_filtered") {
 // iter215v — server-side por filtro em BACKGROUND (resposta imediata)
 const r2 = await api._client.post(
"/customer/loyalty-dispatch/by-filter",
 {
 campaign_id: dispatchForm.campaign_id,
 channel_id: dispatchForm.channel_id || undefined,
 agent_id: dispatchForm.agent_id || undefined,
 praca: praca || undefined,
 period_ym: periodFilter !=="all" && !periodFilter.startsWith("Q")
 ? periodFilter : undefined,
 only_with_phone: true,
 max_limit: 20000,
 start_now: dispatchForm.start_now,
 },
 { timeout: 15000 },
);
 // Polling do job
 const jobId = r2.data?.job_id;
 if (!jobId) throw new Error("Job não criado");
 setDispatchMsg(` Job ${jobId} iniciado em background…`);
 // Poll a cada 2s, max 60 tentativas (2 min)
 let lastInserted = 0;
 for (let i = 0; i < 60; i++) {
 await new Promise((res) =>setTimeout(res, 2000));
 try {
 const jr = await api._client.get(
 `/customer/loyalty-dispatch/jobs/${jobId}`);
 const j = jr.data;
 lastInserted = j.inserted || 0;
 if (j.status ==="done") {
 setDispatchMsg(
 `✓ ${j.inserted} disparos · avaliados ${j.evaluated} · ` +
 `${j.skipped_dup} duplicados · ${j.skipped_invalid} inválidos` +
 (j.started_now ?" · Campanha INICIADA" :""),
);
 break;
 } else if (j.status ==="error") {
 setDispatchMsg(`✗ Job falhou: ${j.error}`);
 break;
 } else {
 setDispatchMsg(
 `Em andamento… ${j.inserted || 0} disparos enfileirados`,
);
 }
 } catch {
 // ignora erros transientes de polling
 }
 }
 setSelectedIds(new Set());
 setDispatching(false);
 return;
 }
 // modo seleção da página
 const selectedClients = filteredItems
 .filter((it) =>selectedIds.has(it.id) && it.has_valid_phone)
 .map((it) =>({
 document: it.document, name: it.name, phone: it.phone,
 plan_name: it.plan_name, city: it.filial,
 }));
 if (!selectedClients.length) {
 setDispatchMsg("✗ Nenhum cliente válido selecionado.");
 setDispatching(false);
 return;
 }
 const r = await api._client.post("/customer/loyalty-dispatch", {
 campaign_id: dispatchForm.campaign_id,
 channel_id: dispatchForm.channel_id || undefined,
 agent_id: dispatchForm.agent_id || undefined,
 clients: selectedClients,
 start_now: dispatchForm.start_now,
 });
 const d = r.data;
 setDispatchMsg(
 `✓ ${d.inserted} disparos · ${d.skipped_dup} duplicados · ` +
 `${d.skipped_invalid} inválidos` +
 (d.started_now ?" · Campanha INICIADA" :" · em rascunho"),
);
 setSelectedIds(new Set());
 } catch (e) {
 setDispatchMsg(`✗ ${e?.response?.data?.detail || e.message}`);
 }
 setDispatching(false);
 };

 // iter215 — dispara POST /api/atlaz/customers/sync (snapshot diff já
 // marca os sumidos como INATIVO). No fim, recarrega a lista local.
 const runAtlazSync = async () =>{
 setSyncing(true); setSyncMsg("");
 try {
 const r = await api._client.post("/atlaz/customers/sync");
 const s = r.data || {};
 const deact = s.snapshot_deactivated ?? 0;
 const ins = s.inserted ?? 0;
 const upd = s.updated ?? 0;
 setSyncMsg(
 `✓ Sync OK · ${deact} desativados detectados · ` +
 `${ins} novos · ${upd} atualizados`
);
 await load();
 } catch (e) {
 setSyncMsg(`✗ Falha: ${e?.response?.data?.detail || e.message}`);
 }
 setSyncing(false);
 };

 const exportCSV = () =>{
 if (!data?.items) return;
 const head = ["name","document","phone","pppoe_user","plan_name","filial",
"installation_date","deactivation_date","tenure_years_before_cancel",
"days_since_cancel","cancellation_reason"];
 const rows = data.items.map((it) =>head.map((k) =>
 `"${(it[k] ??"").toString().replace(/"/g, '""')}"`
).join(","));
 const csv = [head.join(","), ...rows].join("\n");
 const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url; a.download = `clientes-desativados-${Date.now()}.csv`;
 a.click(); URL.revokeObjectURL(url);
 };

 const pracas = (data?.by_praca || []);

 return (
 <div style={{ display: "grid", gap: 16 }}
 data-testid="loyalty-deactivated-tab">
 <div>
 <div style={{ fontSize: 13, color:"#64748b" }}>
 Clientes cancelados agrupados por praça. Ideal pra campanhas de
 retomada (winback).
 </div>
 </div>

 {/* iter215o — KPIs de cancelamentos: meses calendário (não rolling)
 iter215p — clicáveis, filtram a tabela abaixo */}
 {data?.recent_kpis && (
 <div data-testid="deactivated-kpis" style={{
 display: "grid",
 gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
 gap: 10,
 }}>
 <KpiBox label=" Mês atual"
 period={data.recent_kpis.current_month?.label}
 value={data.recent_kpis.current_month?.count || 0}
 sub="quente p/ winback (oferta agressiva)"
 bg="linear-gradient(135deg,#dc2626,#991b1b)"
 active={periodFilter === data.recent_kpis.current_month?.ym}
 onClick={() =>togglePeriod(
 data.recent_kpis.current_month?.ym)} />
 <KpiBox label=" Mês anterior"
 period={data.recent_kpis.prev_month?.label}
 value={data.recent_kpis.prev_month?.count || 0}
 sub="ainda recuperável (15-25% conversão)"
 bg="linear-gradient(135deg,#ea580c,#9a3412)"
 active={periodFilter === data.recent_kpis.prev_month?.ym}
 onClick={() =>togglePeriod(
 data.recent_kpis.prev_month?.ym)} />
 <KpiBox label=" -2 meses"
 period={data.recent_kpis.prev2_month?.label}
 value={data.recent_kpis.prev2_month?.count || 0}
 sub="prazo crítico (oferta + bônus)"
 bg="linear-gradient(135deg,#ca8a04,#854d0e)"
 active={periodFilter === data.recent_kpis.prev2_month?.ym}
 onClick={() =>togglePeriod(
 data.recent_kpis.prev2_month?.ym)} />
 <KpiBox label=" -3 meses"
 period={data.recent_kpis.prev3_month?.label}
 value={data.recent_kpis.prev3_month?.count || 0}
 sub="resfriado (precisa abordagem nova)"
 bg="linear-gradient(135deg,#2563eb,#1e3a8a)"
 active={periodFilter === data.recent_kpis.prev3_month?.ym}
 onClick={() =>togglePeriod(
 data.recent_kpis.prev3_month?.ym)} />
 <KpiBox label=" Trimestre atual"
 period={data.recent_kpis.current_quarter?.label}
 value={data.recent_kpis.current_quarter?.count || 0}
 sub="pipeline acumulado"
 bg="linear-gradient(135deg,#16a34a,#14532d)"
 active={periodFilter === data.recent_kpis.current_quarter?.key}
 onClick={() =>togglePeriod(
 data.recent_kpis.current_quarter?.key)} />
 <KpiBox label=" TOTAL"
 period="histórico completo"
 value={data.total_count || 0}
 sub={`${data?.recent_kpis?.last_365d || 0} no último ano`}
 bg="linear-gradient(135deg,#0f172a,#1e293b)"
 active={periodFilter ==="all"}
 onClick={() =>setPeriodFilter("all")} />
 </div>
)}

 {/* iter215p — Mini gráfico de tendência (últimos 13 meses) */}
 {data?.recent_kpis?.monthly_history?.length >1 && (
 <MonthlyTrendChart history={data.recent_kpis.monthly_history}
 onClickMonth={togglePeriod}
 activeYm={periodFilter} />
)}

 {periodFilter !=="all" && (
 <div data-testid="deactivated-period-banner" style={{
 background:"#fef3c7", color:"#78350f",
 padding:"8px 14px", borderRadius: 8, fontSize: 12,
 fontWeight: 700, display: "flex", justifyContent: "space-between",
 alignItems: "center",
 }}>
 <span>Filtrando lista por <b>{periodFilter}</b>· {filteredItems.length} de {data.items.length} clientes</span>
 <button onClick={() =>setPeriodFilter("all")}
 data-testid="clear-period-filter"
 style={{
 border: 0, background:"#78350f", color: "white",
 padding:"4px 10px", borderRadius: 6, fontSize: 11,
 fontWeight: 700, cursor: "pointer",
 }}>✕ Limpar filtro</button>
 </div>
)}

 {/* Chips por praça */}
 {pracas.length >0 && (
 <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
 <button onClick={() =>setPraca("")}
 data-testid="deactivated-chip-all"
 style={chipStyle(!praca,"#0f172a")}>
 Todas ({data?.total_count || 0})
 </button>
 {pracas.map((p) =>(
 <button key={p.praca} onClick={() =>setPraca(p.praca)}
 data-testid={`deactivated-chip-${p.praca}`}
 style={chipStyle(praca === p.praca,"#dc2626")}>
 {p.praca} ({p.count})
 </button>
))}
 </div>
)}

 {/* Filtros */}
 <div style={{
 display: "flex", gap: 8, flexWrap: "wrap",
 padding: 12, background: "white", borderRadius: 12,
 border:"1px solid #e2e8f0", alignItems: "center",
 }}>
 <label style={{ fontSize: 12, color:"#475569" }}>Limite
 <select value={limit} onChange={(e) =>setLimit(+e.target.value)}
 data-testid="deactivated-limit"
 style={{ marginLeft: 6, padding:"4px 8px",
 border:"1px solid #cbd5e1", borderRadius: 6,
 fontSize: 12 }}>
 <option value={100}>100</option>
 <option value={200}>200</option>
 <option value={500}>500</option>
 <option value={2000}>2000</option>
 <option value={5000}>5000</option>
 <option value={10000}>Todos (até 10k)</option>
 </select>
 </label>
 {/* iter215r — Filtro: só clientes com telefone válido (winback) */}
 <label data-testid="deactivated-only-with-phone-label"
 style={{
 fontSize: 12,
 color: onlyWithPhone ?"#15803d" :"#475569",
 fontWeight: onlyWithPhone ? 800 : 400,
 cursor: "pointer", display: "inline-flex",
 alignItems: "center", gap: 4,
 background: onlyWithPhone ?"#dcfce7" : "transparent",
 padding:"4px 10px", borderRadius: 6,
 border: `1px solid ${onlyWithPhone ?"#86efac" :"#cbd5e1"}`,
 }}>
 <input type="checkbox" checked={onlyWithPhone}
 onChange={(e) =>setOnlyWithPhone(e.target.checked)}
 data-testid="deactivated-only-with-phone"
 style={{ accentColor:"#15803d" }} />
 só com telefone
 {data?.total_no_phone >0 && (
 <span style={{
 fontSize: 10, color:"#7f1d1d", background:"#fee2e2",
 padding:"1px 6px", borderRadius: 999, fontWeight: 700,
 marginLeft: 2,
 }}>
 {data.total_no_phone} sem
 </span>
)}
 </label>
 <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
 <button onClick={runAtlazSync} disabled={syncing || loading}
 data-testid="deactivated-atlaz-sync"
 style={btnStyle("#7c3aed")}>
 {syncing ?"Sincronizando…" :"▶ Rodar Sync Atlaz"}
 </button>
 <button onClick={load} disabled={loading}
 data-testid="deactivated-reload"
 style={btnStyle("#0f172a")}>
 {loading ?"…" : "Atualizar"}
 </button>
 <button onClick={exportCSV} disabled={!data?.items?.length}
 data-testid="deactivated-export-csv"
 style={btnStyle("#15803d")}>
 Exportar CSV
 </button>
 </div>
 </div>

 {syncMsg && (
 <div data-testid="deactivated-sync-msg"
 style={{
 background: syncMsg.startsWith("✗") ?"#fee2e2" :"#dbeafe",
 color: syncMsg.startsWith("✗") ?"#7f1d1d" :"#1e3a8a",
 padding: 10, borderRadius: 8, fontSize: 12, fontWeight: 700,
 }}>
 {syncMsg}
 </div>
)}

 {err && (
 <div style={{
 background:"#fee2e2", color:"#7f1d1d",
 padding: 10, borderRadius: 8, fontSize: 13,
 }}>️ {err}</div>
)}

 {/* iter215q — Toolbar de disparo (sticky quando há seleção)
 iter215u — também mostra opção "TODA a base" se filtro ativo */}
 {(selectedIds.size >0 || onlyWithPhone) && (
 <div data-testid="deactivated-dispatch-toolbar"
 style={{
 position: "sticky", top: 8, zIndex: 10,
 background: "linear-gradient(135deg,#7c3aed,#ec4899)",
 color: "white", padding: 14, borderRadius: 12,
 boxShadow:"0 8px 24px rgba(124,58,237,0.3)",
 }}>
 <div style={{ display: "flex", justifyContent: "space-between",
 alignItems: "center", flexWrap: "wrap", gap: 12 }}>
 <div>
 <div style={{ fontSize: 11, fontWeight: 800, opacity: 0.85,
 textTransform: "uppercase", letterSpacing: 0.5 }}>
 ✓ Seleção
 </div>
 <div style={{ fontSize: 20, fontWeight: 900, marginTop: 2 }}>
 {selectedIds.size >0 ? (
 <>{selectedIds.size} cliente{selectedIds.size >1 ?"s" :""} da página</>
) : (
 <>Nenhum cliente selecionado</>
)}
 </div>
 {onlyWithPhone && data?.total_with_phone >0 && (
 <div style={{ fontSize: 11, opacity: 0.9, marginTop: 4 }}>
 Disponíveis na base inteira:{""}
 <b>{data.total_with_phone} com telefone válido</b>
 </div>
)}
 </div>
 <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
 {selectedIds.size >0 && (
 <button onClick={() =>setSelectedIds(new Set())}
 data-testid="deactivated-clear-selection"
 style={{
 border:"1px solid rgba(255,255,255,0.4)",
 background: "transparent", color: "white",
 padding:"8px 14px", borderRadius: 8,
 fontSize: 12, fontWeight: 700, cursor: "pointer",
 }}>✕ Limpar</button>
)}
 {selectedIds.size >0 && (
 <button onClick={openDispatch}
 data-testid="deactivated-open-dispatch"
 style={{
 border: 0, background: "white", color:"#7c3aed",
 padding:"8px 18px", borderRadius: 8,
 fontSize: 13, fontWeight: 900, cursor: "pointer",
 }}>
 Disparar (página: {selectedIds.size})
 </button>
)}
 {onlyWithPhone && data?.total_with_phone >0 && (
 <button onClick={openDispatchAll}
 data-testid="deactivated-open-dispatch-all"
 style={{
 border:"2px solid white", background:"#facc15",
 color:"#7c2d12",
 padding:"8px 18px", borderRadius: 8,
 fontSize: 13, fontWeight: 900, cursor: "pointer",
 }}>
 Disparar pra TODA a base ({data.total_with_phone})
 </button>
)}
 </div>
 </div>
 </div>
)}

 {/* iter215q — Modal de disparo */}
 {dispatchOpen && (
 <DispatchModal
 campaigns={campaigns}
 channels={channels}
 agents={agents}
 form={dispatchForm}
 setForm={setDispatchForm}
 selectedCount={selectedIds.size}
 dispatchMode={dispatchMode}
 totalInBase={data?.total_with_phone}
 dispatching={dispatching}
 dispatchMsg={dispatchMsg}
 onClose={() =>{ setDispatchOpen(false); setDispatchMsg(""); }}
 onRun={runDispatch} />
)}

 {/* Tabela */}
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
 <Th>
 <input type="checkbox"
 checked={selectedIds.size === filteredItems.length
 && filteredItems.length >0}
 onChange={toggleSelectAll}
 data-testid="deactivated-select-all"
 style={{ accentColor:"#7c3aed", cursor: "pointer" }} />
 </Th>
 <Th>Cliente</Th>
 <Th>Plano</Th>
 <Th>Praça</Th>
 <Th>Tempo (antes)</Th>
 <Th>Cancelou há</Th>
 <Th>Motivo</Th>
 <Th>Contato</Th>
 </tr>
 </thead>
 <tbody>
 {(filteredItems || []).map((it) =>(
 <tr key={it.id}
 data-testid={`deactivated-row-${it.id}`}
 style={{
 borderBottom:"1px solid #f1f5f9",
 background: selectedIds.has(it.id) ?"#f5f3ff" : "white",
 }}>
 <Td>
 <input type="checkbox"
 checked={selectedIds.has(it.id)}
 onChange={() =>toggleSelect(it.id)}
 data-testid={`deactivated-select-${it.id}`}
 disabled={!it.has_valid_phone}
 title={it.has_valid_phone ?"Selecionar" : "Sem telefone válido"}
 style={{
 accentColor:"#7c3aed",
 cursor: it.has_valid_phone ?"pointer" : "not-allowed",
 opacity: it.has_valid_phone ? 1 : 0.3,
 }} />
 </Td>
 <Td>
 <div style={{ fontWeight: 700, color:"#0f172a" }}>
 {it.name}
 </div>
 <div style={{ fontSize: 10, color:"#64748b",
 fontFamily: "monospace" }}>
 {it.document} {it.external_code ? `· ${it.external_code}` :""}
 </div>
 </Td>
 <Td>{it.plan_name}</Td>
 <Td>{it.filial}</Td>
 <Td>{fmtTenure(it.tenure_years_before_cancel)}</Td>
 <Td>
 {it.days_since_cancel != null
 ? `${it.days_since_cancel} dias`
 :"—"}
 </Td>
 <Td>
 <span style={{ fontSize: 11, color:"#475569" }}>
 {it.cancellation_reason ||"—"}
 </span>
 </Td>
 <Td>
 {it.has_valid_phone ? (
 fmtPhone(it.phone)
) : (
 <span data-testid={`deactivated-no-phone-${it.id}`}
 style={{
 fontSize: 10, fontWeight: 800, color:"#7f1d1d",
 background:"#fee2e2",
 padding:"2px 8px", borderRadius: 999,
 }}>
 sem telefone
 </span>
)}
 </Td>
 </tr>
))}
 {(!filteredItems || filteredItems.length === 0) && !loading && (
 <tr><td colSpan={8} style={{ padding: 24, textAlign: "center",
 color:"#64748b" }}>
 Nenhum cliente desativado encontrado.
 </td></tr>
)}
 </tbody>
 </table>
 </div>
 </div>
 </div>
);
}

function chipStyle(active, accent) {
 return {
 border: 0, borderRadius: 999, padding:"6px 12px",
 fontSize: 11, fontWeight: 800,
 background: active ? accent :"#f1f5f9",
 color: active ?"white" :"#475569",
 cursor: "pointer",
 };
}

// iter215o — Card de KPI com período em destaque (mês/trim) + descrição
// iter215p — agora clicável (filtra a tabela)
function KpiBox({ label, period, value, sub, bg, onClick, active }) {
 return (
 <button data-testid={`deactivated-kpi-${(period || label).replace(/\W/g,"")}`}
 onClick={onClick}
 style={{
 padding: 14, borderRadius: 12, background: bg,
 color: "white", textAlign: "left", border: 0,
 cursor: onClick ?"pointer" : "default",
 outline: active ?"3px solid #facc15" : "none",
 outlineOffset: 2,
 transition: "transform 0.15s, outline 0.15s",
 transform: active ?"scale(1.02)" : "scale(1)",
 }}>
 <div style={{
 fontSize: 10, fontWeight: 800, textTransform: "uppercase",
 letterSpacing: 0.5, opacity: 0.85,
 }}>
 {label}
 </div>
 {period && (
 <div style={{
 fontSize: 13, fontWeight: 800, marginTop: 2,
 background: "rgba(255,255,255,0.18)", display: "inline-block",
 padding:"2px 8px", borderRadius: 6,
 }}>
 {period}
 </div>
)}
 <div style={{
 fontSize: 30, fontWeight: 900, lineHeight: 1, marginTop: 6,
 }}>
 {Number(value).toLocaleString("pt-BR")}
 <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7,
 marginLeft: 4 }}>
 {value === 1 ?"cancelamento" : "cancelamentos"}
 </span>
 </div>
 {sub && (
 <div style={{ fontSize: 11, opacity: 0.85, marginTop: 4 }}>
 {sub}
 </div>
)}
 </button>
);
}

// iter215p — Gráfico de barras mini (últimos 13 meses)
const MONTHS_PT = ["Jan","Fev","Mar","Abr","Mai","Jun",
"Jul","Ago","Set","Out","Nov","Dez"];
function MonthlyTrendChart({ history, onClickMonth, activeYm }) {
 // history vem ordenado desc, vamos virar pra asc no eixo X
 const data = [...history].reverse();
 const max = Math.max(...data.map((d) =>d.count), 1);
 return (
 <div data-testid="deactivated-monthly-trend"
 style={{
 background: "white", borderRadius: 12, padding: 14,
 border:"1px solid #e2e8f0",
 }}>
 <div style={{ fontSize: 12, fontWeight: 800, color:"#475569",
 marginBottom: 10, display: "flex",
 justifyContent: "space-between" }}>
 <span>Tendência mensal de cancelamentos (últimos {data.length} meses)</span>
 <span style={{ fontWeight: 400, color:"#94a3b8" }}>
 clique numa barra pra filtrar + selecionar
 </span>
 </div>
 <div style={{
 display: "flex", alignItems: "flex-end", gap: 6, height: 110,
 borderBottom:"1px solid #e2e8f0", paddingBottom: 4,
 }}>
 {data.map((d) =>{
 const [y, m] = d.ym.split("-").map(Number);
 const h = (d.count / max) * 100;
 const isActive = activeYm === d.ym;
 return (
 <button key={d.ym}
 onClick={() =>onClickMonth(d.ym)}
 data-testid={`trend-bar-${d.ym}`}
 title={`${d.ym}: ${d.count} cancelamentos`}
 style={{
 flex: 1, height: `${h}%`,
 background: isActive
 ?"linear-gradient(180deg,#facc15,#ca8a04)"
 : "linear-gradient(180deg,#dc2626,#7f1d1d)",
 borderRadius:"4px 4px 0 0",
 border: 0, cursor: "pointer",
 position: "relative",
 minWidth: 22,
 }}>
 <span style={{
 position: "absolute", top: -16, left:"50%",
 transform: "translateX(-50%)",
 fontSize: 9, fontWeight: 800,
 color: isActive ?"#ca8a04" :"#64748b",
 }}>{d.count}</span>
 </button>
);
 })}
 </div>
 <div style={{
 display: "flex", gap: 6, fontSize: 9, color:"#64748b",
 marginTop: 4, fontWeight: 700,
 }}>
 {data.map((d) =>{
 const [y, m] = d.ym.split("-").map(Number);
 return (
 <div key={d.ym} style={{ flex: 1, textAlign: "center",
 minWidth: 22 }}>
 {MONTHS_PT[m - 1]}/{String(y).slice(-2)}
 </div>
);
 })}
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

// iter215q — Modal de disparo de campanha
function DispatchModal({
 campaigns, channels, agents, form, setForm,
 selectedCount, dispatching, dispatchMsg, onClose, onRun,
 invalidPhoneCount = 0, dispatchMode ="selected", totalInBase = 0,
}) {
 const setField = (k, v) =>setForm((p) =>({ ...p, [k]: v }));
 const selectedCamp = campaigns.find((c) =>c.id === form.campaign_id);
 const targetCount = dispatchMode ==="all_filtered"
 ? totalInBase : selectedCount;
 return (
 <div data-testid="dispatch-modal-backdrop"
 onClick={(e) =>{ if (e.target === e.currentTarget) onClose(); }}
 style={{
 position: "fixed", inset: 0, zIndex: 100,
 background: "rgba(15,23,42,0.6)",
 display: "flex", alignItems: "center", justifyContent: "center",
 padding: 20,
 }}>
 <div style={{
 background: "white", borderRadius: 16, width:"100%",
 maxWidth: 560, padding: 24,
 boxShadow:"0 20px 60px rgba(0,0,0,0.3)",
 maxHeight:"90vh", overflowY: "auto",
 }}>
 <div style={{ display: "flex", justifyContent: "space-between",
 alignItems: "center", marginBottom: 12 }}>
 <div>
 <div style={{ fontSize: 18, fontWeight: 900, color:"#0f172a" }}>
 Disparar campanha
 {dispatchMode ==="all_filtered" && (
 <span style={{
 marginLeft: 8, background:"#facc15", color:"#7c2d12",
 fontSize: 11, padding:"2px 10px", borderRadius: 999,
 fontWeight: 800,
 }}>TODA A BASE</span>
)}
 </div>
 <div style={{ fontSize: 12, color:"#64748b", marginTop: 2 }}>
 {dispatchMode ==="all_filtered" ? (
 <>~<b>{targetCount}</b>clientes da base inteira (com telefone válido,{""}
 server-side bulk insert){""}
 <span style={{ color:"#dc2626", fontWeight: 700 }}>
 ação em massa
 </span></>
) : (
 <>{selectedCount} cliente{selectedCount >1 ?"s" :""} selecionado{selectedCount >1 ?"s" :""}{""}
 <span style={{ color:"#15803d", fontWeight: 700 }}>
 ✓ todos com telefone válido
 </span></>
)}
 </div>
 </div>
 <button onClick={onClose} data-testid="dispatch-modal-close"
 style={{ background: "transparent", border: 0, fontSize: 22,
 cursor: "pointer", color:"#94a3b8" }}>
 ✕
 </button>
 </div>

 <div style={{ display: "grid", gap: 14 }}>
 {/* Campanha */}
 <label style={{ display: "grid", gap: 4 }}>
 <span style={{ fontSize: 11, fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5 }}>
 Mensagem (campanha cadastrada) *
 </span>
 <select value={form.campaign_id}
 onChange={(e) =>setField("campaign_id", e.target.value)}
 data-testid="dispatch-campaign"
 style={selectStyle}>
 <option value="">— Selecione uma campanha —</option>
 {campaigns.map((c) =>(
 <option key={c.id} value={c.id}>
 {c.name} [{c.channel}/{c.mode}] · {c.status}
 </option>
))}
 </select>
 {selectedCamp?.text && (
 <div data-testid="dispatch-preview" style={{
 fontSize: 11, color:"#475569", background:"#f1f5f9",
 padding: 8, borderRadius: 6, marginTop: 4,
 whiteSpace: "pre-wrap", lineHeight: 1.5,
 }}>
 <b>Preview:</b><br />
 {selectedCamp.text}
 </div>
)}
 {campaigns.length === 0 && (
 <div style={{
 fontSize: 11, color:"#78350f", background:"#fef3c7",
 padding: 8, borderRadius: 6,
 }}>
 Nenhuma campanha disponível. Crie uma em <code>Disparo em Massa</code>
 primeiro.
 </div>
)}
 </label>

 {/* Canal */}
 <label style={{ display: "grid", gap: 4 }}>
 <span style={{ fontSize: 11, fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5 }}>
 Canal WhatsApp (opcional — sobrescreve o da campanha)
 </span>
 <select value={form.channel_id}
 onChange={(e) =>setField("channel_id", e.target.value)}
 data-testid="dispatch-channel"
 style={selectStyle}>
 <option value="">— Usar canal default da campanha —</option>
 {channels.map((c) =>(
 <option key={c.id} value={c.id}
 disabled={!c.live_connected}>
 {c.id} {c.phone_number ? `(${c.phone_number})` :""}
 {" ·"}{c.live_state ||"?"}
 {c.live_connected ?" ✓" :" ✗"}
 </option>
))}
 </select>
 {channels.length >0
 && !channels.some((c) =>c.live_connected) && (
 <div data-testid="dispatch-no-channel-warning" style={{
 marginTop: 6, padding: 10, borderRadius: 8,
 background:"#fef2f2", border:"1px solid #fecaca",
 fontSize: 12, color:"#7f1d1d",
 display: "flex", alignItems: "center", justifyContent: "space-between",
 gap: 10, flexWrap: "wrap",
 }}>
 <span>
 <b>Nenhum canal conectado.</b>Os disparos ficarão na fila
 até pelo menos 1 canal estar online.
 </span>
 <button
 type="button"
 data-testid="dispatch-open-channels"
 onClick={() =>{
 onClose?.();
 window.dispatchEvent(new CustomEvent("ponto:navigate", {
 detail: { view: "atendimento", sub: "channels" },
 }));
 }}
 style={{
 border: 0, background:"#dc2626", color: "white",
 padding:"6px 12px", borderRadius: 6, fontSize: 12,
 fontWeight: 800, cursor: "pointer", whiteSpace: "nowrap",
 }}
 >
 Conectar canal
 </button>
 </div>
)}
 </label>

 {/* Agente */}
 <label style={{ display: "grid", gap: 4 }}>
 <span style={{ fontSize: 11, fontWeight: 800, color:"#475569",
 textTransform: "uppercase", letterSpacing: 0.5 }}>
 Agente responsável (follow-up)
 </span>
 <select value={form.agent_id}
 onChange={(e) =>setField("agent_id", e.target.value)}
 data-testid="dispatch-agent"
 style={selectStyle}>
 <option value="">— Sem agente atribuído —</option>
 {agents.map((a) =>(
 <option key={a.id} value={a.id}>
 {a.name} · {a.role}
 </option>
))}
 </select>
 </label>

 {/* Start now */}
 <label data-testid="dispatch-start-now-label"
 style={{
 display: "inline-flex", alignItems: "center", gap: 6,
 fontSize: 12, color:"#475569", cursor: "pointer",
 }}>
 <input type="checkbox" checked={form.start_now}
 onChange={(e) =>setField("start_now", e.target.checked)}
 data-testid="dispatch-start-now"
 style={{ accentColor:"#15803d" }} />
 Iniciar campanha imediatamente após adicionar
 </label>

 {dispatchMsg && (
 <div style={{
 fontSize: 12, fontWeight: 700, padding: 10, borderRadius: 6,
 background: dispatchMsg.startsWith("✗") ?"#fee2e2" :"#dcfce7",
 color: dispatchMsg.startsWith("✗") ?"#7f1d1d" :"#14532d",
 }}>
 {dispatchMsg}
 </div>
)}

 {/* Buttons */}
 <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
 <button onClick={onClose} data-testid="dispatch-cancel"
 style={{
 border:"1px solid #cbd5e1", background: "white",
 color:"#475569", padding:"8px 16px",
 borderRadius: 8, fontSize: 12, fontWeight: 700,
 cursor: "pointer",
 }}>
 Cancelar
 </button>
 <button onClick={onRun}
 disabled={dispatching || !form.campaign_id}
 data-testid="dispatch-run"
 style={{
 border: 0,
 background: (dispatching || !form.campaign_id)
 ?"#94a3b8"
 : "linear-gradient(135deg,#7c3aed,#ec4899)",
 color: "white", padding:"8px 18px",
 borderRadius: 8, fontSize: 13, fontWeight: 900,
 cursor: (dispatching || !form.campaign_id)
 ?"wait" : "pointer",
 }}>
 {dispatching ?"Disparando…" :" Disparar agora"}
 </button>
 </div>
 </div>
 </div>
 </div>
);
}

const selectStyle = {
 padding:"8px 10px", border:"1px solid #cbd5e1", borderRadius: 6,
 fontSize: 12, background: "white", color:"#0f172a",
 cursor: "pointer", width:"100%",
};
