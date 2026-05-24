import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  CreditCard, Receipt, Plus, Search, RefreshCw, XCircle, ExternalLink,
  CheckCircle, AlertTriangle, Copy, QrCode, Banknote, Settings,
} from "lucide-react";

/* =============================================================
   PaymentsPanel — Módulo 3 (Gateway de Pagamentos).
   Lista cobranças, mostra status, permite emitir nova cobrança (boleto/Pix),
   cancelar e atualizar via webhook. Suporta múltiplos gateways
   (atualmente: Asaas — Cora/Sicoob futuro).
============================================================= */
const STATUS_COLORS = {
  PENDING: { bg: "#f1f5f9", fg: "#475569", label: "Pendente" },
  RECEIVED: { bg: "#dcfce7", fg: "#15803d", label: "Recebido" },
  CONFIRMED: { bg: "#dcfce7", fg: "#15803d", label: "Confirmado" },
  OVERDUE: { bg: "#fee2e2", fg: "#b91c1c", label: "Vencido" },
  CANCELED: { bg: "#fef3c7", fg: "#92400e", label: "Cancelado" },
  CANCELLED: { bg: "#fef3c7", fg: "#92400e", label: "Cancelado" },
  REFUNDED: { bg: "#e0e7ff", fg: "#3730a3", label: "Estornado" },
  AWAITING_RISK_ANALYSIS: { bg: "#fef9c3", fg: "#854d0e", label: "Análise" },
};

export default function PaymentsPanel() {
  const [gateways, setGateways] = useState([]);
  const [charges, setCharges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [g, c] = await Promise.all([
        api.paymentsGatewaysStatus().catch(() => ({ items: [] })),
        api.paymentsChargesList({ status: statusFilter || undefined }),
      ]);
      setGateways(g.items || []);
      setCharges(c.items || []);
    } catch (e) {
      console.error(e);
    } finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const filtered = charges.filter((c) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (c.gateway_charge_id || "").toLowerCase().includes(q)
        || (c.description || "").toLowerCase().includes(q)
        || (c.subscriber_id || "").toLowerCase().includes(q);
  });

  const totals = {
    pending: charges.filter((c) => c.status === "PENDING").length,
    paid: charges.filter((c) =>
      ["RECEIVED", "CONFIRMED"].includes(c.status)).length,
    overdue: charges.filter((c) => c.status === "OVERDUE").length,
    sumPending: charges
      .filter((c) => c.status === "PENDING")
      .reduce((s, c) => s + (c.amount || 0), 0),
  };

  const asaas = gateways.find((g) => g.name === "asaas");

  return (
    <div data-testid="payments-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(79,70,229,.10) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #4f46e5, #7c3aed)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(79,70,229,.35)",
        }}>
          <CreditCard size={22} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                       letterSpacing: "-0.02em" }}>
            Pagamentos (Boleto · Pix)
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            Módulo 3 · Cobranças via gateway com webhook automático.
            {asaas?.configured
              ? <span style={{ color: "#15803d", marginLeft: 6 }}>
                  ✓ Asaas configurado ({asaas.env})
                </span>
              : <span style={{ color: "#b45309", marginLeft: 6 }}>
                  ⚠ Asaas não configurado — adicione ASAAS_API_KEY em /app/backend/.env
                </span>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn btn-ghost btn-sm" onClick={load}
                  data-testid="payments-refresh"
                  title="Atualizar lista">
            <RefreshCw size={13} /> Atualizar
          </button>
          <button className="btn btn-primary btn-sm"
                  onClick={() => setShowCreate(true)}
                  disabled={!asaas?.configured}
                  data-testid="payments-new-btn">
            <Plus size={13} /> Emitir cobrança
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div style={{ display: "grid",
                     gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))",
                     gap: 10 }}>
        <Kpi icon={Receipt} color="#475569" label="Pendentes"
             value={totals.pending}
             sub={`R$ ${totals.sumPending.toFixed(2)}`} />
        <Kpi icon={CheckCircle} color="#15803d" label="Pagas"
             value={totals.paid} />
        <Kpi icon={AlertTriangle} color="#b91c1c" label="Vencidas"
             value={totals.overdue} />
        <Kpi icon={Banknote} color="#7c3aed" label="Total"
             value={charges.length} />
      </div>

      {/* Filtros */}
      <div className="surface" style={{
        padding: 12, borderRadius: 10,
        display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
      }}>
        <div style={{ position: "relative", flex: "1 1 240px" }}>
          <Search size={13} style={{
            position: "absolute", left: 10, top: "50%",
            transform: "translateY(-50%)", color: "var(--text-muted)",
          }} />
          <input className="input"
                  placeholder="Buscar por descrição, id, assinante..."
                  value={search} onChange={(e) => setSearch(e.target.value)}
                  data-testid="payments-search"
                  style={{ paddingLeft: 30, width: "100%" }} />
        </div>
        <select className="input" value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  data-testid="payments-status-filter"
                  style={{ minWidth: 150 }}>
          <option value="">Todos os status</option>
          <option value="PENDING">Pendente</option>
          <option value="RECEIVED">Recebido</option>
          <option value="CONFIRMED">Confirmado</option>
          <option value="OVERDUE">Vencido</option>
          <option value="CANCELED">Cancelado</option>
          <option value="REFUNDED">Estornado</option>
        </select>
      </div>

      {/* Lista */}
      {loading ? (
        <div className="surface" style={{ padding: 30, textAlign: "center",
                                            color: "var(--text-muted)" }}>
          Carregando cobranças...
        </div>
      ) : filtered.length === 0 ? (
        <div className="surface" style={{ padding: 30, textAlign: "center",
                                            color: "var(--text-muted)" }}>
          {charges.length === 0
            ? "Nenhuma cobrança emitida ainda. Clique em 'Emitir cobrança' pra começar."
            : "Nenhuma cobrança bate com os filtros."}
        </div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {filtered.map((c) => (
            <ChargeRow key={c.id} charge={c}
                       onClick={() => setDetail(c)} />
          ))}
        </div>
      )}

      {showCreate && (
        <ChargeCreateModal onClose={() => setShowCreate(false)}
                            onCreated={() => { setShowCreate(false); load(); }} />
      )}
      {detail && (
        <ChargeDetailModal charge={detail}
                           onClose={() => setDetail(null)}
                           onChanged={() => { setDetail(null); load(); }} />
      )}
    </div>
  );
}

function Kpi({ icon: Ico, color, label, value, sub }) {
  return (
    <div className="surface" style={{ padding: 14, borderRadius: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                     marginBottom: 6 }}>
        <Ico size={13} style={{ color }} />
        <span style={{ fontSize: 10, fontWeight: 800, color,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function ChargeRow({ charge, onClick }) {
  const s = STATUS_COLORS[charge.status] || STATUS_COLORS.PENDING;
  const due = charge.due_date
    ? new Date(charge.due_date + "T12:00:00").toLocaleDateString("pt-BR")
    : "—";
  return (
    <button onClick={onClick} className="surface"
             data-testid={`charge-row-${charge.id}`}
             style={{
               textAlign: "left", display: "grid",
               gridTemplateColumns: "1fr auto auto auto",
               gap: 12, alignItems: "center",
               padding: "12px 14px", borderRadius: 10, cursor: "pointer",
               border: "1px solid var(--border-default)", width: "100%",
             }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center",
                       marginBottom: 3 }}>
          <span style={{
            padding: "2px 8px", borderRadius: 999, fontSize: 9,
            fontWeight: 800, letterSpacing: 0.4,
            background: charge.billing_type === "PIX" ? "#dcfce7"
              : charge.billing_type === "BOLETO" ? "#dbeafe" : "#f3e8ff",
            color: charge.billing_type === "PIX" ? "#15803d"
              : charge.billing_type === "BOLETO" ? "#1d4ed8" : "#6d28d9",
          }}>
            {charge.billing_type}
          </span>
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
            {charge.gateway} · {charge.gateway_charge_id?.slice(-8)}
          </span>
        </div>
        <div style={{ fontSize: 13, fontWeight: 700,
                       color: "var(--text-primary)",
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
          {charge.description || "—"}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
          Vence em {due}
        </div>
      </div>
      <div style={{ fontSize: 17, fontWeight: 800, textAlign: "right",
                     color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
        R$ {(charge.amount || 0).toFixed(2)}
      </div>
      <span style={{
        padding: "4px 10px", borderRadius: 999,
        background: s.bg, color: s.fg,
        fontSize: 10, fontWeight: 800, letterSpacing: 0.4,
      }}>{s.label}</span>
      <span style={{ color: "var(--text-muted)" }}>›</span>
    </button>
  );
}

/* ============================================================
   ChargeCreateModal — formulário pra emitir cobrança nova.
   ============================================================ */
function ChargeCreateModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    subscriber_id: "", invoice_id: "",
    billing_type: "UNDEFINED", due_date: "",
    amount: "", description: "",
    fine_pct: 2.0, interest_pct: 1.0,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [subs, setSubs] = useState([]);

  useEffect(() => {
    // Carrega lista de assinantes pra dropdown
    api.subscribersList?.({ limit: 200 })
      .then((r) => setSubs(r.items || []))
      .catch(() => {});
    // default vencimento = +7 dias
    const d = new Date(); d.setDate(d.getDate() + 7);
    setForm((f) => ({ ...f, due_date: d.toISOString().slice(0, 10) }));
  }, []);

  const submit = async () => {
    if (!form.subscriber_id) { setErr("Selecione o assinante."); return; }
    if (!form.amount || Number(form.amount) <= 0) {
      setErr("Informe o valor."); return;
    }
    if (!form.description.trim()) {
      setErr("Informe a descrição."); return;
    }
    setBusy(true); setErr("");
    try {
      await api.paymentsChargeCreate({
        ...form, amount: Number(form.amount),
        fine_pct: Number(form.fine_pct), interest_pct: Number(form.interest_pct),
        gateway: "asaas",
      });
      onCreated();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div onClick={onClose} data-testid="charge-create-modal" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.7)",
      zIndex: 1100, display: "grid", placeItems: "center", padding: 16,
      overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: 12, padding: 22,
        width: "min(94vw, 560px)", maxHeight: "92vh", overflowY: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,.35)",
      }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 800 }}>
          💳 Emitir cobrança via Asaas
        </h3>
        <p style={{ fontSize: 11, color: "#64748b", marginBottom: 14 }}>
          Cria o cliente no Asaas (se ainda não existir) e emite boleto/Pix.
          O cliente recebe e‑mail automático com link de pagamento.
        </p>

        <Field label="Assinante *">
          <select className="input" value={form.subscriber_id}
                    data-testid="charge-sub-select"
                    onChange={(e) => setForm({
                      ...form, subscriber_id: e.target.value })}>
            <option value="">— selecione —</option>
            {subs.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} {s.cpf_cnpj ? `(${s.cpf_cnpj})` : "(sem CPF)"}
              </option>
            ))}
          </select>
        </Field>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 10, marginTop: 10 }}>
          <Field label="Tipo de cobrança *">
            <select className="input" value={form.billing_type}
                      data-testid="charge-type"
                      onChange={(e) => setForm({
                        ...form, billing_type: e.target.value })}>
              <option value="UNDEFINED">Boleto + Pix (cliente escolhe)</option>
              <option value="BOLETO">Apenas Boleto</option>
              <option value="PIX">Apenas Pix</option>
            </select>
          </Field>
          <Field label="Vencimento *">
            <input className="input" type="date" value={form.due_date}
                    data-testid="charge-due"
                    onChange={(e) => setForm({
                      ...form, due_date: e.target.value })} />
          </Field>
        </div>

        <Field label="Valor (R$) *">
          <input className="input" type="number" step="0.01" min="0"
                  data-testid="charge-amount"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  placeholder="99.90" />
        </Field>

        <Field label="Descrição *">
          <input className="input" value={form.description}
                  data-testid="charge-desc"
                  onChange={(e) => setForm({
                    ...form, description: e.target.value })}
                  placeholder="Ex.: Mensalidade 200 Mega - Jun/2026" />
        </Field>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 10, marginTop: 10 }}>
          <Field label="Multa por atraso (%)">
            <input className="input" type="number" step="0.1" min="0"
                    value={form.fine_pct}
                    onChange={(e) => setForm({
                      ...form, fine_pct: e.target.value })} />
          </Field>
          <Field label="Juros ao mês (%)">
            <input className="input" type="number" step="0.1" min="0"
                    value={form.interest_pct}
                    onChange={(e) => setForm({
                      ...form, interest_pct: e.target.value })} />
          </Field>
        </div>

        {err && (
          <div style={{
            marginTop: 10, padding: 9, borderRadius: 7,
            background: "#fef2f2", color: "#991b1b", fontSize: 12,
            border: "1px solid #fecaca",
          }}>⚠ {err}</div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                        marginTop: 16 }}>
          <button onClick={onClose} className="btn btn-ghost btn-sm">
            Cancelar
          </button>
          <button onClick={submit} disabled={busy}
                    data-testid="charge-submit"
                    className="btn btn-primary btn-sm"
                    style={{ minWidth: 120 }}>
            {busy ? "Emitindo..." : "▶ Emitir cobrança"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   ChargeDetailModal — detalhes + ações (refresh, cancel, abrir boleto/Pix).
   ============================================================ */
function ChargeDetailModal({ charge, onClose, onChanged }) {
  const [c, setC] = useState(charge);
  const [busy, setBusy] = useState(false);
  const s = STATUS_COLORS[c.status] || STATUS_COLORS.PENDING;
  const fmt = (v) => new Intl.NumberFormat("pt-BR",
    { style: "currency", currency: "BRL" }).format(v || 0);

  const refresh = async () => {
    setBusy(true);
    try {
      const r = await api.paymentsChargeGet(c.id, true);
      setC(r);
    } finally { setBusy(false); }
  };
  const cancel = async () => {
    if (!await window.confirm("Cancelar esta cobrança?")) return;
    setBusy(true);
    try { await api.paymentsChargeCancel(c.id); onChanged(); }
    catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };
  const copyToClipboard = (text) => {
    navigator.clipboard?.writeText(text);
  };

  return (
    <div onClick={onClose} data-testid="charge-detail-modal" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.7)",
      zIndex: 1100, display: "grid", placeItems: "center", padding: 16,
      overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: 12, padding: 22,
        width: "min(94vw, 620px)", maxHeight: "92vh", overflowY: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,.35)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
                        marginBottom: 6 }}>
          <span style={{
            width: 40, height: 40, borderRadius: 10,
            background: "linear-gradient(135deg, #4f46e5, #7c3aed)",
            color: "#fff", display: "grid", placeItems: "center",
          }}><CreditCard size={18} /></span>
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>
              Cobrança {c.gateway_charge_id?.slice(-8)}
            </h3>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              {c.gateway.toUpperCase()} · {c.billing_type}
            </div>
          </div>
          <span style={{ padding: "4px 10px", borderRadius: 999,
                            background: s.bg, color: s.fg,
                            fontSize: 11, fontWeight: 800,
                            letterSpacing: 0.4 }}>{s.label}</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 8, marginTop: 12,
                        padding: 12, borderRadius: 8,
                        background: "#f8fafc",
                        border: "1px solid #e2e8f0" }}>
          <Cell label="Valor">{fmt(c.amount)}</Cell>
          <Cell label="Vencimento">
            {new Date(c.due_date + "T12:00:00").toLocaleDateString("pt-BR")}
          </Cell>
          <Cell label="Criada em">
            {new Date(c.created_at).toLocaleString("pt-BR")}
          </Cell>
          <Cell label="Atualizada em">
            {new Date(c.updated_at).toLocaleString("pt-BR")}
          </Cell>
        </div>

        <div style={{ fontSize: 12, color: "#0f172a", marginTop: 10,
                        padding: 10, borderRadius: 8,
                        background: "#fafafa", border: "1px solid #e2e8f0" }}>
          <strong>Descrição:</strong> {c.description}
        </div>

        {c.boleto_url && (
          <div style={{ marginTop: 12, padding: 12, borderRadius: 9,
                          background: "#dbeafe",
                          border: "1px solid #93c5fd" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8,
                            marginBottom: 6 }}>
              <Receipt size={14} style={{ color: "#1d4ed8" }} />
              <strong style={{ fontSize: 12, color: "#1e3a8a" }}>Boleto</strong>
            </div>
            {c.boleto_digitable_line && (
              <div style={{ display: "flex", gap: 6, alignItems: "center",
                              marginBottom: 6 }}>
                <code style={{ flex: 1, fontSize: 11,
                                  fontFamily: "ui-monospace, monospace",
                                  padding: "6px 8px",
                                  background: "#fff", borderRadius: 5,
                                  overflow: "auto", whiteSpace: "nowrap" }}>
                  {c.boleto_digitable_line}
                </code>
                <button onClick={() => copyToClipboard(c.boleto_digitable_line)}
                          className="btn btn-ghost btn-sm" title="Copiar">
                  <Copy size={12} />
                </button>
              </div>
            )}
            <a href={c.boleto_url} target="_blank" rel="noopener noreferrer"
                className="btn btn-primary btn-sm" data-testid="charge-open-boleto">
              <ExternalLink size={12} /> Abrir boleto PDF
            </a>
          </div>
        )}

        {c.pix_qr_code_image_url && (
          <div style={{ marginTop: 12, padding: 12, borderRadius: 9,
                          background: "#dcfce7",
                          border: "1px solid #86efac" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8,
                            marginBottom: 6 }}>
              <QrCode size={14} style={{ color: "#15803d" }} />
              <strong style={{ fontSize: 12, color: "#14532d" }}>Pix</strong>
            </div>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <img src={c.pix_qr_code_image_url} alt="Pix QR"
                    style={{ width: 130, height: 130, borderRadius: 6,
                              background: "#fff", padding: 4 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, color: "#14532d",
                                marginBottom: 4 }}>
                  Copia e cola:
                </div>
                <code style={{ display: "block", fontSize: 10,
                                  fontFamily: "ui-monospace, monospace",
                                  padding: "6px 8px",
                                  background: "#fff", borderRadius: 5,
                                  maxHeight: 70, overflow: "auto",
                                  wordBreak: "break-all" }}>
                  {c.pix_copy_paste}
                </code>
                <button onClick={() => copyToClipboard(c.pix_copy_paste)}
                          className="btn btn-ghost btn-sm"
                          style={{ marginTop: 6 }}>
                  <Copy size={12} /> Copiar
                </button>
              </div>
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                        marginTop: 16 }}>
          <button onClick={refresh} disabled={busy}
                    data-testid="charge-refresh"
                    className="btn btn-ghost btn-sm">
            <RefreshCw size={12} /> Atualizar status
          </button>
          {c.status === "PENDING" && (
            <button onClick={cancel} disabled={busy}
                      data-testid="charge-cancel"
                      className="btn btn-secondary btn-sm"
                      style={{ background: "#fef2f2", color: "#991b1b",
                                border: "1px solid #fecaca" }}>
              <XCircle size={12} /> Cancelar
            </button>
          )}
          <button onClick={onClose} className="btn btn-ghost btn-sm">
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}

function Cell({ label, children }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b",
                       textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a",
                       marginTop: 2 }}>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginTop: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: "#475569",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       marginBottom: 4 }}>{label}</div>
      {children}
    </label>
  );
}
