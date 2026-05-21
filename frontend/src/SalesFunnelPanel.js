/* SalesFunnelPanel.js — Pipeline de Vendas WhatsApp
 *
 * 3 tabs:
 *   - Pipeline (leads hot/warm/cold com intent score)
 *   - Reativação (leads frios → disparo de mensagem)
 *   - Dashboard (KPIs)
 *
 * Integra com /api/sales/* (sales_funnel.py).
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { api } from "./api";

const COLORS = {
  hot: { bg: "#fef2f2", border: "#dc2626", text: "#991b1b", icon: "🔥" },
  warm: { bg: "#fef3c7", border: "#f59e0b", text: "#92400e", icon: "🌡️" },
  cold: { bg: "#dbeafe", border: "#3b82f6", text: "#1e40af", icon: "❄️" },
  none: { bg: "#f1f5f9", border: "#94a3b8", text: "#475569", icon: "💤" },
};

const TABS = [
  { id: "pipeline", label: "🎯 Pipeline" },
  { id: "reativacao", label: "♻️ Reativação" },
  { id: "dashboard", label: "📊 Dashboard" },
];

export default function SalesFunnelPanel() {
  const [tab, setTab] = useState("pipeline");
  return (
    <div data-testid="sales-funnel-panel" style={{ padding: 18 }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "#0f172a" }}>
          💼 Funil de Vendas · WhatsApp
        </h2>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>
          Leads classificados por intenção em tempo real. Converta hot leads em
          tickets de instalação com 1 clique.
        </p>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t.id}
                  data-testid={`sales-tab-${t.id}`}
                  onClick={() => setTab(t.id)}
                  style={{
                    padding: "8px 16px", borderRadius: 8, border: 0,
                    background: tab === t.id ? "#0f172a" : "#e2e8f0",
                    color: tab === t.id ? "#fff" : "#475569",
                    fontSize: 13, fontWeight: 700, cursor: "pointer",
                  }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "pipeline" && <PipelineTab />}
      {tab === "reativacao" && <ReactivationTab />}
      {tab === "dashboard" && <DashboardTab />}
    </div>
  );
}

// ============================================================
// PIPELINE
// ============================================================
function PipelineTab() {
  const [filter, setFilter] = useState("");
  const [days, setDays] = useState(30);
  const [data, setData] = useState({ items: [] });
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.salesLeads({
        days, temperature: filter || undefined, limit: 200,
      });
      setData(r);
    } catch (e) { /* eslint-disable-next-line no-console */
      console.warn("salesLeads failed", e);
    } finally { setLoading(false); }
  }, [filter, days]);

  useEffect(() => { reload(); }, [reload]);

  const counts = useMemo(() => {
    const c = { hot: 0, warm: 0, cold: 0, none: 0 };
    (data.items || []).forEach((it) => { c[it.temperature] = (c[it.temperature] || 0) + 1; });
    return c;
  }, [data]);

  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 12,
                      flexWrap: "wrap", alignItems: "center" }}>
        <select value={filter}
                data-testid="pipeline-filter-temp"
                onChange={(e) => setFilter(e.target.value)}
                style={selectStyle}>
          <option value="">Todos ({(data.items || []).length})</option>
          <option value="hot">🔥 Hot ({counts.hot})</option>
          <option value="warm">🌡️ Warm ({counts.warm})</option>
          <option value="cold">❄️ Cold ({counts.cold})</option>
        </select>
        <select value={days}
                data-testid="pipeline-days"
                onChange={(e) => setDays(Number(e.target.value))}
                style={selectStyle}>
          <option value={7}>Últimos 7 dias</option>
          <option value={30}>Últimos 30 dias</option>
          <option value={90}>Últimos 90 dias</option>
        </select>
        <button onClick={reload} disabled={loading} style={btnSec}>
          {loading ? "Carregando…" : "↻ Atualizar"}
        </button>
        <div style={{ marginLeft: "auto", fontSize: 12, color: "#64748b" }}>
          {data.total || 0} leads no período
        </div>
      </div>

      <div style={{ display: "grid",
                      gridTemplateColumns: selected ? "1.4fr 1fr" : "1fr",
                      gap: 12 }}>
        <div style={{ maxHeight: "70vh", overflow: "auto" }}>
          {(data.items || []).map((lead) => (
            <LeadCard key={lead.phone} lead={lead}
                       selected={selected?.phone === lead.phone}
                       onClick={() => setSelected(lead)} />
          ))}
          {(data.items || []).length === 0 && !loading && (
            <div style={{ padding: 30, textAlign: "center", color: "#94a3b8",
                            background: "#f8fafc", borderRadius: 10 }}>
              Nenhum lead nesse filtro 🍃
            </div>
          )}
        </div>
        {selected && (
          <LeadDetailPanel lead={selected}
                            onClose={() => setSelected(null)}
                            onConverted={() => { setSelected(null); reload(); }} />
        )}
      </div>
    </>
  );
}

function LeadCard({ lead, selected, onClick }) {
  const c = COLORS[lead.temperature] || COLORS.none;
  return (
    <button
      data-testid={`lead-card-${lead.phone}`}
      onClick={onClick}
      style={{
        display: "block", width: "100%", marginBottom: 8, padding: 12,
        border: `2px solid ${selected ? "#0f172a" : c.border}`,
        background: selected ? "#0f172a" : c.bg,
        color: selected ? "#fff" : c.text,
        borderRadius: 10, cursor: "pointer", textAlign: "left",
        transition: "all .15s ease",
      }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "baseline", gap: 8 }}>
        <strong style={{ fontSize: 13 }}>
          {c.icon} {lead.push_name || lead.phone}
        </strong>
        <span style={{ fontSize: 11, fontWeight: 700 }}>
          Score {lead.score}
          {lead.has_sale_marker && " · ✅ AGENDADA"}
        </span>
      </div>
      <div style={{ fontSize: 11, opacity: 0.85, marginTop: 4, lineHeight: 1.3,
                      maxHeight: 32, overflow: "hidden" }}>
        {lead.last_text || "(sem texto)"}
      </div>
      <div style={{ fontSize: 10, opacity: 0.65, marginTop: 4 }}>
        📱 {lead.phone}
        {lead.unread_count > 0 && ` · ${lead.unread_count} não lidas`}
      </div>
    </button>
  );
}

function LeadDetailPanel({ lead, onClose, onConverted }) {
  const [form, setForm] = useState({
    client_name: lead.push_name || "",
    cpf: "", address: "", neighborhood: "", city: "",
    plan_name: "", scheduled_date: "", scheduled_time: "09:00", notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(null);

  const submit = async () => {
    setErr(""); setBusy(true);
    try {
      const r = await api.salesConvertLead(lead.phone, form);
      setDone(r);
      setTimeout(() => onConverted?.(), 1200);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  if (done) {
    return (
      <div style={{ padding: 16, background: "#ecfdf5",
                      border: "2px solid #10b981", borderRadius: 10 }}>
        <div style={{ fontSize: 16, fontWeight: 800, color: "#065f46" }}>
          ✅ Lead convertido!
        </div>
        <div style={{ fontSize: 12, color: "#065f46", marginTop: 6 }}>
          Ticket de instalação: <code>{done.ticket_id}</code>
          <br />Pré-cadastro: <code>{done.pre_subscriber_id}</code>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="lead-detail-panel"
          style={{ padding: 16, background: "#fff",
                    border: "1px solid #e2e8f0", borderRadius: 10,
                    maxHeight: "70vh", overflow: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
          Converter em instalação · {lead.phone}
        </div>
        <button onClick={onClose} style={btnSec}>✕</button>
      </div>

      <FormField label="Nome completo *" value={form.client_name}
                  testid="convert-name"
                  onChange={(v) => setForm({ ...form, client_name: v })} />
      <FormField label="CPF" value={form.cpf} testid="convert-cpf"
                  onChange={(v) => setForm({ ...form, cpf: v })} />
      <FormField label="Endereço completo *" value={form.address}
                  testid="convert-address"
                  onChange={(v) => setForm({ ...form, address: v })} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <FormField label="Bairro" value={form.neighborhood}
                    testid="convert-neighborhood"
                    onChange={(v) => setForm({ ...form, neighborhood: v })} />
        <FormField label="Cidade" value={form.city} testid="convert-city"
                    onChange={(v) => setForm({ ...form, city: v })} />
      </div>
      <FormField label="Plano" value={form.plan_name} testid="convert-plan"
                  placeholder="Ex.: 500 MB · R$ 109,90"
                  onChange={(v) => setForm({ ...form, plan_name: v })} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <FormField label="Data instalação" type="date"
                    testid="convert-date"
                    value={form.scheduled_date}
                    onChange={(v) => setForm({ ...form, scheduled_date: v })} />
        <FormField label="Hora" type="time" value={form.scheduled_time}
                    testid="convert-time"
                    onChange={(v) => setForm({ ...form, scheduled_time: v })} />
      </div>
      <FormField label="Observações" textarea value={form.notes}
                  testid="convert-notes"
                  onChange={(v) => setForm({ ...form, notes: v })} />

      {err && <div style={{ color: "#dc2626", fontSize: 12, marginTop: 8 }}>{err}</div>}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
        <button onClick={onClose} style={btnSec}>Cancelar</button>
        <button onClick={submit} disabled={busy} data-testid="convert-submit"
                style={{
                  padding: "8px 16px", borderRadius: 8, border: 0,
                  background: busy ? "#cbd5e1" : "linear-gradient(135deg,#10b981,#059669)",
                  color: "#fff", fontSize: 13, fontWeight: 800,
                  cursor: busy ? "wait" : "pointer",
                }}>
          {busy ? "Convertendo…" : "✓ Criar ticket de instalação"}
        </button>
      </div>
    </div>
  );
}

// ============================================================
// REATIVAÇÃO
// ============================================================
const REACTIVATE_TEMPLATE = (
  "Oi! 👋 Vi que você se interessou pelos nossos planos de fibra " +
  "há alguns dias. Liberei um cupom especial para você: 30% OFF nos " +
  "3 primeiros meses se fechar até sexta-feira 🚀\n\n" +
  "Posso te enviar a simulação?"
);

function ReactivationTab() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [message, setMessage] = useState(REACTIVATE_TEMPLATE);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try { setItems((await api.salesColdLeads()).items || []); }
    catch (e) { /* eslint-disable-next-line no-console */ console.warn(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const toggleAll = () => {
    if (selected.size === items.length) setSelected(new Set());
    else setSelected(new Set(items.map((i) => i.phone)));
  };
  const toggleOne = (ph) => {
    const next = new Set(selected);
    if (next.has(ph)) next.delete(ph); else next.add(ph);
    setSelected(next);
  };

  const submit = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await api.salesReactivate([...selected], message);
      setResult(r);
      setSelected(new Set());
    } catch (e) {
      setResult({ error: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 12 }}>
      <div>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 8 }}>
          <strong style={{ fontSize: 13, color: "#0f172a" }}>
            Leads frios ({items.length})
            <span style={{ fontSize: 11, fontWeight: 400, color: "#64748b", marginLeft: 6 }}>
              · perguntaram entre 14-90 dias atrás e não fecharam
            </span>
          </strong>
          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={reload} disabled={loading} style={btnSec}>
              {loading ? "…" : "↻"}
            </button>
            <button onClick={toggleAll} style={btnSec}>
              {selected.size === items.length && items.length > 0
                ? "Limpar seleção" : "Selecionar tudo"}
            </button>
          </div>
        </div>
        <div style={{ maxHeight: "65vh", overflow: "auto" }}>
          {items.map((it) => (
            <label key={it.phone}
                    data-testid={`cold-lead-${it.phone}`}
                    style={{
                      display: "flex", gap: 8, alignItems: "center",
                      padding: 10, marginBottom: 4,
                      background: selected.has(it.phone) ? "#dbeafe" : "#f8fafc",
                      border: `1px solid ${selected.has(it.phone) ? "#3b82f6" : "#e2e8f0"}`,
                      borderRadius: 8, cursor: "pointer", fontSize: 12,
                    }}>
              <input type="checkbox" checked={selected.has(it.phone)}
                      onChange={() => toggleOne(it.phone)} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700 }}>
                  {it.push_name || it.phone}
                  <span style={{ fontSize: 11, fontWeight: 400, color: "#64748b" }}>
                    {" · "}{it.days_idle}d sem responder · score then: {it.score_then}
                  </span>
                </div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div style={{ padding: 14, background: "#f8fafc",
                      border: "1px solid #e2e8f0", borderRadius: 10 }}>
        <strong style={{ fontSize: 13, color: "#0f172a" }}>
          Mensagem de reativação
        </strong>
        <p style={{ fontSize: 11, color: "#64748b", margin: "2px 0 8px" }}>
          Pode usar {`{nome}`} no texto (ainda não substituído nesta versão).
        </p>
        <textarea value={message}
                    data-testid="reactivate-message"
                    onChange={(e) => setMessage(e.target.value)}
                    rows={8}
                    style={{
                      width: "100%", padding: 10, borderRadius: 6,
                      border: "1px solid #cbd5e1", fontSize: 12,
                      fontFamily: "inherit", boxSizing: "border-box",
                      resize: "vertical",
                    }} />
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
          {selected.size} leads selecionados · {message.length} caracteres
        </div>
        <button onClick={submit} disabled={busy || selected.size === 0}
                data-testid="reactivate-submit"
                style={{
                  width: "100%", marginTop: 10, padding: "10px 14px",
                  borderRadius: 8, border: 0,
                  background: (busy || selected.size === 0)
                    ? "#cbd5e1" : "linear-gradient(135deg,#3b82f6,#1e40af)",
                  color: "#fff", fontSize: 13, fontWeight: 800,
                  cursor: (busy || selected.size === 0) ? "not-allowed" : "pointer",
                }}>
          {busy ? "Enfileirando…" : `📨 Disparar para ${selected.size} leads`}
        </button>
        {result && (
          <div style={{ marginTop: 8, padding: 10, borderRadius: 6,
                          background: result.error ? "#fef2f2" : "#ecfdf5",
                          color: result.error ? "#991b1b" : "#065f46",
                          fontSize: 12, fontWeight: 600 }}>
            {result.error || `✓ Enfileirado · job ${result.job_id} · ${result.queued} msgs`}
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// DASHBOARD
// ============================================================
function DashboardTab() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);

  useEffect(() => {
    api.salesDashboard(days).then(setData).catch(() => {});
  }, [days]);

  if (!data) return <div style={{ padding: 30, color: "#94a3b8" }}>Carregando…</div>;
  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                style={selectStyle}>
          <option value={7}>7 dias</option>
          <option value={30}>30 dias</option>
          <option value={90}>90 dias</option>
        </select>
      </div>
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))",
                      gap: 10 }}>
        <Kpi label="Leads no período" value={data.leads_total} color="#3b82f6" />
        <Kpi label="🔥 Hot leads" value={data.hot_leads} color="#dc2626" />
        <Kpi label="✅ Vendas agendadas" value={data.sales_agreed} color="#10b981" />
        <Kpi label="📦 Convertidos em OS" value={data.converted_to_install} color="#8b5cf6" />
        <Kpi label="% Conversão" value={`${data.conversion_rate}%`} color="#f59e0b" />
      </div>
    </>
  );
}

function Kpi({ label, value, color }) {
  return (
    <div style={{ padding: 16, background: "#fff",
                    border: `2px solid ${color}33`,
                    borderTop: `4px solid ${color}`,
                    borderRadius: 10, textAlign: "center" }}>
      <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color: "#0f172a", marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}

// ============================================================
// Helpers de formulário
// ============================================================
function FormField({ label, value, onChange, type = "text", placeholder, textarea, testid }) {
  const Tag = textarea ? "textarea" : "input";
  return (
    <label style={{ display: "block", marginBottom: 8 }}>
      <div style={{ fontSize: 11, color: "#475569", fontWeight: 700, marginBottom: 3 }}>
        {label}
      </div>
      <Tag type={type} value={value || ""}
            data-testid={testid}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            rows={textarea ? 3 : undefined}
            style={{
              width: "100%", padding: "7px 10px", boxSizing: "border-box",
              border: "1px solid #cbd5e1", borderRadius: 6, fontSize: 12,
              fontFamily: "inherit",
            }} />
    </label>
  );
}

const selectStyle = {
  padding: "6px 10px", borderRadius: 6, border: "1px solid #cbd5e1",
  background: "white", fontSize: 12, cursor: "pointer",
};
const btnSec = {
  padding: "6px 12px", borderRadius: 6, border: "1px solid #cbd5e1",
  background: "white", color: "#475569", fontSize: 12, fontWeight: 600,
  cursor: "pointer",
};
