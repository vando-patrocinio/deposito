import React, { useEffect, useMemo, useState } from "react";
import {
  FileText, Play, Settings, AlertCircle, CheckCircle2,
  RefreshCw, X, Clock, DollarSign, TrendingUp,
} from "lucide-react";
import { api } from "@/api";

const STATUS_LABEL = {
  open: "Em aberto", paid: "Paga", overdue: "Vencida",
  canceled: "Cancelada", pending: "Pendente",
};
const STATUS_COLOR = {
  open: "#0ea5e9", paid: "#16a34a", overdue: "#dc2626",
  canceled: "#6b7280", pending: "#eab308",
};

function fmtBRL(v) {
  const n = Number(v || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s.length === 10 ? s + "T00:00:00" : s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleDateString("pt-BR");
}

function monthList() {
  const out = [];
  const now = new Date();
  for (let i = -3; i <= 3; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

function KpiCard({ label, value, hint, color = "#0f766e", testid }) {
  return (
    <div data-testid={testid} style={{
      background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10,
      padding: 14, minWidth: 160, borderLeft: `4px solid ${color}`,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase",
                     fontWeight: 600, letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4, color: "#0f172a" }}>
        {value}
      </div>
      {hint && <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 3 }}>{hint}</div>}
    </div>
  );
}

function Pill({ children, color = "#64748b", bg = "#f1f5f9" }) {
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 999,
      fontSize: 11, fontWeight: 600, color, background: bg,
    }}>{children}</span>
  );
}

// ===================================================================
// MAIN
// ===================================================================
export default function BillingPanel() {
  const [tab, setTab] = useState("dashboard");
  return (
    <div data-testid="billing-panel" style={{ padding: 20 }}>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "#0f172a",
                     display: "flex", alignItems: "center", gap: 10 }}>
          <FileText size={24} /> Faturamento (Billing Engine)
        </h1>
        <div style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
          Módulo nativo de faturas e régua de cobrança — substitui o Atlaz.
        </div>
      </header>

      <nav style={{ display: "flex", gap: 4, marginBottom: 16,
                     borderBottom: "1px solid #e2e8f0" }}>
        {[
          { id: "dashboard", label: "Visão Geral", icon: TrendingUp },
          { id: "invoices",  label: "Faturas",     icon: FileText },
          { id: "generate",  label: "Gerar Lote",  icon: Play },
          { id: "dunning",   label: "Régua de Cobrança", icon: Clock },
          { id: "events",    label: "Histórico Régua", icon: AlertCircle },
        ].map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button key={t.id} data-testid={`billing-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "10px 14px", border: "none", cursor: "pointer",
                background: "none",
                borderBottom: active ? "2px solid #0d9488" : "2px solid transparent",
                color: active ? "#0d9488" : "#64748b",
                fontWeight: active ? 600 : 500, fontSize: 13,
              }}>
              <Icon size={15} /> {t.label}
            </button>
          );
        })}
      </nav>

      {tab === "dashboard" && <DashboardTab />}
      {tab === "invoices"  && <InvoicesTab />}
      {tab === "generate"  && <GenerateBatchTab />}
      {tab === "dunning"   && <DunningRulesTab />}
      {tab === "events"    && <DunningEventsTab />}
    </div>
  );
}

// ===================================================================
// Tab 1 — Dashboard com KPIs
// ===================================================================
function DashboardTab() {
  const [stats, setStats] = useState(null);
  const [competence, setCompetence] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const params = competence ? { competence } : {};
      const data = await api.billingStats(params);
      setStats(data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Falha ao carregar");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [competence]);

  if (loading && !stats) return <div style={{ padding: 20 }}>Carregando...</div>;
  if (err) return (
    <div style={{ padding: 14, background: "#fef2f2", border: "1px solid #fecaca",
                   borderRadius: 8, color: "#991b1b" }}>{err}</div>
  );
  if (!stats) return null;

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center" }}>
        <label style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>Competência:</label>
        <select value={competence} onChange={(e) => setCompetence(e.target.value)}
          data-testid="billing-stats-competence"
          style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                   borderRadius: 6, fontSize: 13 }}>
          <option value="">Todas</option>
          {monthList().map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button onClick={load} data-testid="billing-stats-refresh"
          style={{ padding: "6px 10px", border: "1px solid #0d9488",
                   color: "#0d9488", background: "#fff", borderRadius: 6,
                   fontSize: 12, cursor: "pointer", display: "flex",
                   alignItems: "center", gap: 4 }}>
          <RefreshCw size={13} /> Atualizar
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                     gap: 12, marginBottom: 18 }}>
        <KpiCard testid="kpi-mrr" label="MRR" value={fmtBRL(stats.mrr)}
          hint={`${stats.active_subscribers} assinantes ativos`} color="#0d9488" />
        <KpiCard testid="kpi-invoiced" label="Total Faturado"
          value={fmtBRL(stats.total_invoiced)} hint={`${stats.total_count} faturas`}
          color="#0ea5e9" />
        <KpiCard testid="kpi-paid" label="Recebido"
          value={fmtBRL(stats.total_paid_amount)}
          hint={`${stats.collection_rate}% arrecadação`} color="#16a34a" />
        <KpiCard testid="kpi-open" label="Em Aberto"
          value={fmtBRL(stats.total_open_amount)}
          hint={`${(stats.by_status.open?.count || 0) + (stats.by_status.overdue?.count || 0)} faturas`}
          color="#dc2626" />
      </div>

      <div style={{ background: "#fff", border: "1px solid #e2e8f0",
                     borderRadius: 10, padding: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12,
                     color: "#0f172a" }}>Distribuição por status</h3>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f8fafc" }}>
              <th style={{ padding: 8, textAlign: "left", fontWeight: 600 }}>Status</th>
              <th style={{ padding: 8, textAlign: "right", fontWeight: 600 }}>Qtd</th>
              <th style={{ padding: 8, textAlign: "right", fontWeight: 600 }}>Valor faturado</th>
              <th style={{ padding: 8, textAlign: "right", fontWeight: 600 }}>Valor recebido</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.by_status || {}).map(([st, v]) => (
              <tr key={st} data-testid={`stats-row-${st}`}
                style={{ borderTop: "1px solid #f1f5f9" }}>
                <td style={{ padding: 8 }}>
                  <Pill color={STATUS_COLOR[st]} bg={`${STATUS_COLOR[st]}15`}>
                    {STATUS_LABEL[st] || st}
                  </Pill>
                </td>
                <td style={{ padding: 8, textAlign: "right", fontFamily: "JetBrains Mono, monospace" }}>{v.count}</td>
                <td style={{ padding: 8, textAlign: "right", fontFamily: "JetBrains Mono, monospace" }}>{fmtBRL(v.total_amount)}</td>
                <td style={{ padding: 8, textAlign: "right", fontFamily: "JetBrains Mono, monospace" }}>{fmtBRL(v.total_paid)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ===================================================================
// Tab 2 — Lista de faturas
// ===================================================================
function InvoicesTab() {
  const [items, setItems] = useState([]);
  const [filters, setFilters] = useState({ status: "", competence: "" });
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (filters.status) params.status = filters.status;
      if (filters.competence) params.competence = filters.competence;
      const data = await api.billingInvoicesList(params);
      setItems(data.items || []);
      setTotal(data.total || 0);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filters]);

  const handleMarkPaid = async (inv) => {
    if (!window.confirm(`Marcar fatura de ${inv.subscriber_name} (${fmtBRL(inv.amount)}) como PAGA?`)) return;
    await api.billingInvoiceMarkPaid(inv.id);
    load();
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
        <select value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          data-testid="invoices-filter-status"
          style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                   borderRadius: 6, fontSize: 13 }}>
          <option value="">Todos status</option>
          <option value="open">Em aberto</option>
          <option value="paid">Pagas</option>
          <option value="overdue">Vencidas</option>
          <option value="canceled">Canceladas</option>
        </select>
        <select value={filters.competence}
          onChange={(e) => setFilters({ ...filters, competence: e.target.value })}
          data-testid="invoices-filter-competence"
          style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                   borderRadius: 6, fontSize: 13 }}>
          <option value="">Todas competências</option>
          {monthList().map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button onClick={load} data-testid="invoices-refresh"
          style={{ padding: "6px 10px", border: "1px solid #0d9488",
                   color: "#0d9488", background: "#fff", borderRadius: 6,
                   fontSize: 12, cursor: "pointer" }}>
          <RefreshCw size={13} style={{ display: "inline" }} /> Atualizar
        </button>
        <div style={{ marginLeft: "auto", fontSize: 12, color: "#64748b" }}>
          Mostrando {items.length} de {total} faturas
        </div>
      </div>

      {loading ? <div>Carregando...</div> : (
        <div style={{ background: "#fff", border: "1px solid #e2e8f0",
                       borderRadius: 10, overflow: "hidden" }}>
          <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={{ padding: 10, textAlign: "left", fontWeight: 600 }}>Cliente</th>
                <th style={{ padding: 10, textAlign: "left", fontWeight: 600 }}>Competência</th>
                <th style={{ padding: 10, textAlign: "left", fontWeight: 600 }}>Vencimento</th>
                <th style={{ padding: 10, textAlign: "right", fontWeight: 600 }}>Valor</th>
                <th style={{ padding: 10, textAlign: "center", fontWeight: 600 }}>Status</th>
                <th style={{ padding: 10, textAlign: "center", fontWeight: 600 }}>Atraso</th>
                <th style={{ padding: 10, textAlign: "right", fontWeight: 600 }}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td colSpan={7} style={{ padding: 20, textAlign: "center", color: "#94a3b8" }}>
                  Nenhuma fatura encontrada com esses filtros.
                </td></tr>
              )}
              {items.map((inv) => (
                <tr key={inv.id} data-testid={`invoice-row-${inv.id}`}
                  style={{ borderTop: "1px solid #f1f5f9", cursor: "pointer" }}
                  onClick={() => setSelected(inv)}>
                  <td style={{ padding: 10 }}>
                    <div style={{ fontWeight: 600 }}>{inv.subscriber_name || "—"}</div>
                    <div style={{ fontSize: 11, color: "#94a3b8",
                                  fontFamily: "JetBrains Mono, monospace" }}>
                      {inv.subscriber_document || inv.subscriber_external_id}
                    </div>
                  </td>
                  <td style={{ padding: 10, fontFamily: "JetBrains Mono, monospace" }}>
                    {inv.competence || "—"}
                  </td>
                  <td style={{ padding: 10, fontFamily: "JetBrains Mono, monospace" }}>
                    {fmtDate(inv.due_date)}
                  </td>
                  <td style={{ padding: 10, textAlign: "right",
                                fontFamily: "JetBrains Mono, monospace", fontWeight: 600 }}>
                    {fmtBRL(inv.amount)}
                  </td>
                  <td style={{ padding: 10, textAlign: "center" }}>
                    <Pill color={STATUS_COLOR[inv.status]} bg={`${STATUS_COLOR[inv.status]}15`}>
                      {STATUS_LABEL[inv.status] || inv.status}
                    </Pill>
                  </td>
                  <td style={{ padding: 10, textAlign: "center",
                                fontFamily: "JetBrains Mono, monospace",
                                color: inv.days_late > 0 ? "#dc2626" : "#94a3b8" }}>
                    {inv.days_late > 0 ? `+${inv.days_late}d` : "—"}
                  </td>
                  <td style={{ padding: 10, textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                    {inv.status !== "paid" && inv.status !== "canceled" && (
                      <button data-testid={`invoice-mark-paid-${inv.id}`}
                        onClick={() => handleMarkPaid(inv)}
                        style={{ padding: "4px 8px", border: "1px solid #16a34a",
                                 color: "#16a34a", background: "#fff", borderRadius: 4,
                                 fontSize: 11, cursor: "pointer", fontWeight: 600 }}>
                        Marcar paga
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && <InvoiceDetailModal invoice={selected}
        onClose={() => setSelected(null)} onChange={load} />}
    </div>
  );
}

function InvoiceDetailModal({ invoice, onClose, onChange }) {
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    api.billingInvoiceGet(invoice.id).then(setDetail).catch(() => {});
  }, [invoice.id]);

  const handleCancel = async () => {
    if (!window.confirm("Cancelar esta fatura?")) return;
    await api.billingInvoiceCancel(invoice.id);
    onClose(); onChange();
  };

  const inv = detail?.invoice || invoice;
  const events = detail?.dunning_events || [];

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
                  zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
         data-testid="invoice-detail-modal">
      <div style={{ background: "#fff", borderRadius: 10, padding: 20,
                    maxWidth: 720, width: "92%", maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Fatura {inv.id}</h2>
          <button onClick={onClose} data-testid="invoice-detail-close"
            style={{ background: "none", border: "none", cursor: "pointer" }}>
            <X size={20} />
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
          <div><div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>CLIENTE</div>
            <div style={{ fontSize: 14 }}>{inv.subscriber_name}</div></div>
          <div><div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>DOCUMENTO</div>
            <div style={{ fontSize: 14, fontFamily: "JetBrains Mono, monospace" }}>{inv.subscriber_document || "—"}</div></div>
          <div><div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>VENCIMENTO</div>
            <div style={{ fontSize: 14 }}>{fmtDate(inv.due_date)}</div></div>
          <div><div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>VALOR ORIGINAL</div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{fmtBRL(inv.amount)}</div></div>
          {inv.amount_with_fees && inv.amount_with_fees !== inv.amount && (
            <div><div style={{ fontSize: 11, color: "#dc2626", fontWeight: 600 }}>VALOR ATUALIZADO (multa+juros)</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#dc2626" }}>{fmtBRL(inv.amount_with_fees)}</div></div>
          )}
          <div><div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>STATUS</div>
            <Pill color={STATUS_COLOR[inv.status]} bg={`${STATUS_COLOR[inv.status]}15`}>
              {STATUS_LABEL[inv.status] || inv.status}
            </Pill></div>
        </div>

        {inv.description && (
          <div style={{ marginBottom: 14, padding: 10, background: "#f8fafc", borderRadius: 6 }}>
            <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>DESCRIÇÃO</div>
            <div style={{ fontSize: 13 }}>{inv.description}</div>
          </div>
        )}

        <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#0f172a" }}>
          Histórico da régua de cobrança ({events.length})
        </h3>
        {events.length === 0 ? (
          <div style={{ fontSize: 12, color: "#94a3b8", padding: 10 }}>
            Nenhum evento de cobrança disparado para esta fatura.
          </div>
        ) : (
          <div style={{ maxHeight: 240, overflowY: "auto", border: "1px solid #e2e8f0",
                          borderRadius: 6 }}>
            {events.map((e) => (
              <div key={e.id} style={{ padding: 10, borderTop: "1px solid #f1f5f9", fontSize: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <strong>{e.rule_label}</strong>
                  <span style={{ color: "#94a3b8" }}>{fmtDate(e.ts)}</span>
                </div>
                <div style={{ color: "#64748b", marginTop: 4 }}>
                  {e.template_rendered}
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
          {inv.status !== "paid" && inv.status !== "canceled" && (
            <button onClick={handleCancel} data-testid="invoice-cancel-btn"
              style={{ padding: "8px 14px", border: "1px solid #dc2626",
                       color: "#dc2626", background: "#fff", borderRadius: 6,
                       cursor: "pointer", fontSize: 13 }}>
              Cancelar fatura
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ===================================================================
// Tab 3 — Gerar lote
// ===================================================================
function GenerateBatchTab() {
  const now = new Date();
  const defaultComp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [competence, setCompetence] = useState(defaultComp);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillResult, setBackfillResult] = useState(null);

  const doBackfill = async () => {
    if (!window.confirm("Buscar telefones faltantes em todas as faturas (via subscriber_phones + cache Atlaz)?")) return;
    setBackfilling(true); setBackfillResult(null);
    try { setBackfillResult(await api.billingBackfillPhones()); }
    catch (e) { alert(e?.response?.data?.detail || "Falha"); }
    finally { setBackfilling(false); }
  };

  const doPreview = async () => {
    setLoading(true); setPreview(null); setResult(null);
    try { setPreview(await api.billingGenerateBatchPreview(competence)); }
    catch (e) { alert(e?.response?.data?.detail || "Falha"); }
    finally { setLoading(false); }
  };
  const doRun = async () => {
    if (!preview || preview.invoices_created === 0) { alert("Faça preview primeiro."); return; }
    if (!window.confirm(`Gerar ${preview.invoices_created} faturas (total ${fmtBRL(preview.total_amount)})?`)) return;
    setRunning(true);
    try {
      const r = await api.billingGenerateBatch({ competence, dry_run: false });
      setResult(r); setPreview(null); loadHistory();
    } catch (e) { alert(e?.response?.data?.detail || "Falha"); }
    finally { setRunning(false); }
  };
  const loadHistory = async () => {
    try { setHistory((await api.billingRunsList(20)).items || []); }
    catch { /* ignore */ }
  };
  useEffect(() => { loadHistory(); }, []);

  return (
    <div>
      <div style={{ background: "#fff", border: "1px solid #e2e8f0",
                     borderRadius: 10, padding: 18, marginBottom: 14 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
          Gerar faturas mensais em lote
        </h3>
        <p style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>
          Cria faturas para todos os assinantes <strong>ATIVOS</strong> com plano vinculado e preço cadastrado.
          Assinantes que já têm fatura para a competência selecionada são pulados automaticamente (idempotente).
        </p>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14 }}>
          <label style={{ fontSize: 12, fontWeight: 600 }}>Competência:</label>
          <select value={competence} onChange={(e) => setCompetence(e.target.value)}
            data-testid="batch-competence"
            style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                     borderRadius: 6, fontSize: 13 }}>
            {monthList().map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <button onClick={doPreview} disabled={loading} data-testid="batch-preview-btn"
            style={{ padding: "8px 14px", border: "1px solid #0d9488",
                     color: "#0d9488", background: "#fff", borderRadius: 6,
                     fontSize: 13, cursor: "pointer", fontWeight: 600 }}>
            {loading ? "Calculando..." : "Calcular preview"}
          </button>
        </div>

        {preview && (
          <div data-testid="batch-preview-result"
            style={{ padding: 14, background: "#f0fdfa", border: "1px solid #99f6e4",
                     borderRadius: 8, marginBottom: 12 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                            gap: 12, marginBottom: 10 }}>
              <div><div style={{ fontSize: 10, color: "#0f766e", fontWeight: 600 }}>AVALIADOS</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{preview.subscribers_evaluated}</div></div>
              <div><div style={{ fontSize: 10, color: "#0f766e", fontWeight: 600 }}>A GERAR</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "#0d9488" }}>{preview.invoices_created}</div></div>
              <div><div style={{ fontSize: 10, color: "#0f766e", fontWeight: 600 }}>JÁ EXISTEM</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "#64748b" }}>{preview.skipped_existing}</div></div>
              <div><div style={{ fontSize: 10, color: "#0f766e", fontWeight: 600 }}>SEM PREÇO</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "#dc2626" }}>{preview.skipped_no_price}</div></div>
              <div><div style={{ fontSize: 10, color: "#0f766e", fontWeight: 600 }}>TOTAL R$</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "#0f766e" }}>{fmtBRL(preview.total_amount)}</div></div>
            </div>
            <button onClick={doRun} disabled={running || preview.invoices_created === 0}
              data-testid="batch-run-btn"
              style={{ padding: "10px 18px", border: "none", background: "#0d9488",
                       color: "#fff", borderRadius: 6, fontWeight: 600,
                       cursor: running ? "wait" : "pointer", fontSize: 13 }}>
              {running ? "Gerando..." : `Confirmar geração de ${preview.invoices_created} faturas`}
            </button>
          </div>
        )}

        {result && (
          <div data-testid="batch-result"
            style={{ padding: 12, background: "#ecfdf5", border: "1px solid #6ee7b7",
                       borderRadius: 8, color: "#065f46", fontSize: 13 }}>
            <CheckCircle2 size={16} style={{ display: "inline", marginRight: 6 }} />
            <strong>{result.invoices_created}</strong> faturas geradas com sucesso ({fmtBRL(result.total_amount)} em receita).
          </div>
        )}
      </div>

      <div style={{ background: "#fff", border: "1px solid #e2e8f0",
                     borderRadius: 10, padding: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>
          Backfill de telefones em faturas
        </h3>
        <p style={{ fontSize: 12, color: "#64748b", marginBottom: 10 }}>
          Preenche o campo <code style={{ background: "#f1f5f9", padding: "2px 4px",
            borderRadius: 3 }}>subscriber_phone</code> em faturas legadas (vindas do Atlaz)
          ou geradas antes do hotfix. Lê primário de <code>subscriber_phones</code> + fallback
          no cache Atlaz. Idempotente.
        </p>
        <button onClick={doBackfill} disabled={backfilling} data-testid="billing-backfill-phones"
          style={{ padding: "8px 14px", border: "1px solid #f59e0b",
                   color: "#b45309", background: "#fffbeb", borderRadius: 6,
                   fontSize: 13, cursor: backfilling ? "wait" : "pointer", fontWeight: 600,
                   marginRight: 10 }}>
          {backfilling ? "Procurando telefones..." : "Buscar telefones faltantes"}
        </button>
        {backfillResult && (
          <span data-testid="billing-backfill-result" style={{ fontSize: 12, color: "#15803d" }}>
            Checadas: <strong>{backfillResult.checked}</strong> ·
            Atualizadas: <strong>{backfillResult.updated}</strong> ·
            Sem assinante: <strong>{backfillResult.skipped_no_subscriber}</strong>
          </span>
        )}
      </div>

      <div style={{ background: "#fff", border: "1px solid #e2e8f0",
                     borderRadius: 10, padding: 14, marginTop: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>
          Histórico de execuções
        </h3>
        {history.length === 0 ? (
          <div style={{ fontSize: 12, color: "#94a3b8", textAlign: "center", padding: 10 }}>
            Nenhuma execução registrada ainda.
          </div>
        ) : (
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "#f8fafc" }}>
              <th style={{ padding: 8, textAlign: "left" }}>Data</th>
              <th style={{ padding: 8, textAlign: "left" }}>Competência</th>
              <th style={{ padding: 8, textAlign: "right" }}>Geradas</th>
              <th style={{ padding: 8, textAlign: "right" }}>Puladas</th>
              <th style={{ padding: 8, textAlign: "right" }}>Total R$</th>
              <th style={{ padding: 8, textAlign: "left" }}>Por</th>
            </tr></thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id} data-testid={`run-row-${r.id}`} style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={{ padding: 8 }}>{fmtDate(r.ts)}</td>
                  <td style={{ padding: 8, fontFamily: "JetBrains Mono, monospace" }}>{r.competence}</td>
                  <td style={{ padding: 8, textAlign: "right", fontWeight: 600 }}>{r.invoices_created}</td>
                  <td style={{ padding: 8, textAlign: "right", color: "#94a3b8" }}>{r.skipped_existing + r.skipped_no_price}</td>
                  <td style={{ padding: 8, textAlign: "right", fontWeight: 600 }}>{fmtBRL(r.total_amount)}</td>
                  <td style={{ padding: 8, color: "#64748b" }}>{r.actor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ===================================================================
// Tab 4 — Régua de cobrança (dunning rules editor)
// ===================================================================
function DunningRulesTab() {
  const [rules, setRules] = useState([]);
  const [usingDefaults, setUsingDefaults] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState(null);

  const load = async () => {
    const d = await api.billingDunningRulesGet();
    setRules(d.rules || []);
    setUsingDefaults(d.using_defaults);
    setDirty(false);
  };
  useEffect(() => { load(); }, []);

  const updateRule = (idx, key, value) => {
    setRules((rs) => rs.map((r, i) => i === idx ? { ...r, [key]: value } : r));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.billingDunningRulesUpdate(rules);
      await load();
      alert("Regras salvas com sucesso");
    } catch (e) { alert(e?.response?.data?.detail || "Falha"); }
    finally { setSaving(false); }
  };

  const runNow = async (dry = false) => {
    if (!dry && !window.confirm("Executar régua de cobrança AGORA? Isso pode disparar bloqueios e marcações.")) return;
    setRunning(true);
    try {
      const r = await api.billingDunningRun(dry);
      setLastRun(r);
    } catch (e) { alert(e?.response?.data?.detail || "Falha"); }
    finally { setRunning(false); }
  };

  return (
    <div>
      <div style={{ background: "#fffbeb", border: "1px solid #fde68a",
                     borderRadius: 8, padding: 12, marginBottom: 14, fontSize: 12,
                     color: "#92400e" }}>
        <strong>Régua de Cobrança (Dunning):</strong> regras configuráveis por dias em relação ao vencimento.
        Cron diário às 07:00 avalia automaticamente e registra eventos. {usingDefaults && (
          <span> Atualmente usando <strong>configuração default</strong> — salve para personalizar.</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <button onClick={() => runNow(true)} disabled={running} data-testid="dunning-run-dry"
          style={{ padding: "8px 14px", border: "1px solid #0ea5e9",
                   color: "#0ea5e9", background: "#fff", borderRadius: 6,
                   cursor: "pointer", fontSize: 13 }}>
          Simular (dry-run)
        </button>
        <button onClick={() => runNow(false)} disabled={running} data-testid="dunning-run-real"
          style={{ padding: "8px 14px", border: "none", background: "#dc2626",
                   color: "#fff", borderRadius: 6, cursor: "pointer", fontSize: 13 }}>
          Executar agora
        </button>
      </div>

      {lastRun && (
        <div data-testid="dunning-last-run"
          style={{ padding: 12, background: lastRun.dry_run ? "#eff6ff" : "#ecfdf5",
                   border: `1px solid ${lastRun.dry_run ? "#bfdbfe" : "#6ee7b7"}`,
                   borderRadius: 8, marginBottom: 14, fontSize: 13 }}>
          {lastRun.dry_run ? "[SIMULAÇÃO]" : "[EXECUTADO]"} {" "}
          {lastRun.invoices_evaluated} faturas avaliadas · {" "}
          <strong>{lastRun.events_triggered}</strong> eventos disparados ·
          {" Por ação: "}
          {Object.entries(lastRun.by_action || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "nenhum"}
        </div>
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {rules.map((rule, idx) => (
          <div key={rule.id || idx} data-testid={`dunning-rule-${rule.id || idx}`}
            style={{ background: "#fff", border: "1px solid #e2e8f0",
                     borderRadius: 8, padding: 14 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 10 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600 }}>
                <input type="checkbox" checked={rule.enabled !== false}
                  onChange={(e) => updateRule(idx, "enabled", e.target.checked)}
                  data-testid={`dunning-rule-enabled-${rule.id || idx}`} />
                {rule.label || `Regra ${idx + 1}`}
              </label>
              <span style={{ marginLeft: "auto", fontSize: 11, color: "#64748b" }}>
                Dia <strong>{rule.offset_days >= 0 ? `D+${rule.offset_days}` : `D${rule.offset_days}`}</strong> · {rule.channel} · {rule.action}
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "80px 1fr 120px 100px", gap: 10, marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600 }}>OFFSET (dias)</div>
                <input type="number" value={rule.offset_days}
                  onChange={(e) => updateRule(idx, "offset_days", parseInt(e.target.value, 10) || 0)}
                  style={{ width: "100%", padding: 6, fontSize: 13, border: "1px solid #cbd5e1", borderRadius: 4 }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600 }}>RÓTULO</div>
                <input type="text" value={rule.label || ""}
                  onChange={(e) => updateRule(idx, "label", e.target.value)}
                  style={{ width: "100%", padding: 6, fontSize: 13, border: "1px solid #cbd5e1", borderRadius: 4 }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600 }}>CANAL</div>
                <select value={rule.channel || "whatsapp"}
                  onChange={(e) => updateRule(idx, "channel", e.target.value)}
                  style={{ width: "100%", padding: 6, fontSize: 13, border: "1px solid #cbd5e1", borderRadius: 4 }}>
                  <option value="whatsapp">WhatsApp</option>
                  <option value="sms">SMS</option>
                  <option value="email">E-mail</option>
                  <option value="system">Sistema</option>
                </select>
              </div>
              <div>
                <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600 }}>AÇÃO</div>
                <select value={rule.action || "notify"}
                  onChange={(e) => updateRule(idx, "action", e.target.value)}
                  style={{ width: "100%", padding: 6, fontSize: 13, border: "1px solid #cbd5e1", borderRadius: 4 }}>
                  <option value="reminder">Lembrete</option>
                  <option value="first_notice">1ª cobrança</option>
                  <option value="second_notice">2ª cobrança</option>
                  <option value="suspend">Suspender</option>
                  <option value="final_notice">Aviso final</option>
                </select>
              </div>
            </div>
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600 }}>TEMPLATE</div>
              <textarea value={rule.template || ""}
                onChange={(e) => updateRule(idx, "template", e.target.value)}
                placeholder="Olá {nome}, sua fatura de {valor} vence em {vencimento}..."
                rows={2}
                style={{ width: "100%", padding: 6, fontSize: 12, border: "1px solid #cbd5e1",
                          borderRadius: 4, fontFamily: "JetBrains Mono, monospace", resize: "vertical" }} />
              <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>
                Placeholders: {`{nome}, {valor}, {valor_atualizado}, {vencimento}, {competencia}`}
              </div>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#64748b" }}>
              <input type="checkbox" checked={rule.apply_fees || false}
                onChange={(e) => updateRule(idx, "apply_fees", e.target.checked)} />
              Aplicar multa (2%) + juros (1%/mês) no valor exibido
            </label>
          </div>
        ))}
      </div>

      <div style={{ position: "sticky", bottom: 0, background: "#fff",
                     padding: 12, marginTop: 14, borderTop: "1px solid #e2e8f0",
                     display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={load} disabled={saving} data-testid="dunning-rules-reset"
          style={{ padding: "8px 14px", border: "1px solid #cbd5e1",
                   background: "#fff", borderRadius: 6, cursor: "pointer", fontSize: 13 }}>
          Descartar
        </button>
        <button onClick={save} disabled={saving || !dirty} data-testid="dunning-rules-save"
          style={{ padding: "8px 14px", border: "none",
                   background: dirty ? "#0d9488" : "#cbd5e1",
                   color: "#fff", borderRadius: 6,
                   cursor: dirty ? "pointer" : "not-allowed", fontWeight: 600, fontSize: 13 }}>
          {saving ? "Salvando..." : (dirty ? "Salvar regras" : "Sem alterações")}
        </button>
      </div>
    </div>
  );
}

// ===================================================================
// Tab 5 — Histórico de eventos
// ===================================================================
function DunningEventsTab() {
  const [items, setItems] = useState([]);
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const params = { limit: 200 };
      if (action) params.action = action;
      setItems((await api.billingDunningEventsList(params)).items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [action]);

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center" }}>
        <select value={action} onChange={(e) => setAction(e.target.value)}
          data-testid="events-filter-action"
          style={{ padding: "6px 10px", border: "1px solid #cbd5e1",
                   borderRadius: 6, fontSize: 13 }}>
          <option value="">Todas ações</option>
          <option value="reminder">Lembrete</option>
          <option value="first_notice">1ª cobrança</option>
          <option value="second_notice">2ª cobrança</option>
          <option value="suspend">Suspender</option>
          <option value="final_notice">Aviso final</option>
        </select>
        <button onClick={load}
          style={{ padding: "6px 10px", border: "1px solid #0d9488",
                   color: "#0d9488", background: "#fff", borderRadius: 6,
                   fontSize: 12, cursor: "pointer" }}>Atualizar</button>
        <span style={{ marginLeft: "auto", fontSize: 12, color: "#64748b" }}>
          {items.length} eventos
        </span>
      </div>

      {loading ? <div>Carregando...</div> : items.length === 0 ? (
        <div style={{ padding: 30, textAlign: "center", color: "#94a3b8" }}>
          Nenhum evento registrado. Execute a régua manualmente ou aguarde o cron diário (07:00).
        </div>
      ) : (
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, overflow: "hidden" }}>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "#f8fafc" }}>
              <th style={{ padding: 8, textAlign: "left" }}>Data</th>
              <th style={{ padding: 8, textAlign: "left" }}>Cliente</th>
              <th style={{ padding: 8, textAlign: "left" }}>Regra</th>
              <th style={{ padding: 8, textAlign: "left" }}>Ação</th>
              <th style={{ padding: 8, textAlign: "right" }}>Atraso</th>
              <th style={{ padding: 8, textAlign: "right" }}>Valor atualizado</th>
            </tr></thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} data-testid={`event-row-${e.id}`} style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={{ padding: 8 }}>{fmtDate(e.ts)}</td>
                  <td style={{ padding: 8 }}>
                    <div style={{ fontWeight: 600 }}>{e.subscriber_name || "—"}</div>
                    <div style={{ fontSize: 10, color: "#94a3b8" }}>{e.subscriber_phone || ""}</div>
                  </td>
                  <td style={{ padding: 8 }}>{e.rule_label}</td>
                  <td style={{ padding: 8 }}><Pill>{e.action}</Pill></td>
                  <td style={{ padding: 8, textAlign: "right",
                                color: e.days_late > 0 ? "#dc2626" : "#94a3b8",
                                fontFamily: "JetBrains Mono, monospace" }}>
                    {e.days_late > 0 ? `+${e.days_late}d` : `${e.days_late}d`}
                  </td>
                  <td style={{ padding: 8, textAlign: "right", fontWeight: 600,
                                fontFamily: "JetBrains Mono, monospace" }}>
                    {fmtBRL(e.amount_updated)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
