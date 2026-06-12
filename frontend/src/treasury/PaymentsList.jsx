/**
 * PaymentsList.jsx — A Pagar / Histórico (iter237).
 * Mudanças vs versão anterior:
 *  - Seletor de mês (← Mês → ) ou range customizado
 *  - Agrupamento visual POR MÊS com subtotal
 *  - Badges fortes: PAGO / AGENDADO / RASCUNHO / AGUARDA CTO
 *  - Checkbox "auto-elegível" pra autorizar manualmente >R$ 500 sem CTO
 *  - Ação "Marcar como pago manual" pra registrar pagamentos por fora
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Plus, CheckCircle2, Send, XCircle, MessageSquare, Banknote,
  ChevronLeft, ChevronRight, BadgeCheck, Calendar,
} from "lucide-react";
import {
  treasuryApi, C, BRL, DateBR, monthLabel, currentMonth, addMonths, monthOf,
} from "./api";

const TABS = [
  { id: "all", label: "Todos", filter: null },
  { id: "draft", label: "Rascunhos", filter: "draft" },
  { id: "pending_human_approval", label: "Aguarda CTO", filter: "pending_human_approval" },
  { id: "approved", label: "Aprovados", filter: "approved" },
  { id: "sent_to_bank", label: "Enviados", filter: "sent_to_bank" },
  { id: "paid", label: "Pagos", filter: "paid" },
  { id: "failed", label: "Falhou", filter: "failed" },
];

// Badges grandes — mais visíveis que o pill genérico
const STATUS_BADGE = {
  paid: { label: "PAGO", bg: "#10b981", icon: BadgeCheck },
  sent_to_bank: { label: "AGENDADO", bg: "#3b82f6", icon: Send },
  approved: { label: "APROVADO", bg: "#0ea5e9", icon: CheckCircle2 },
  draft: { label: "RASCUNHO", bg: "#94a3b8", icon: null },
  pending_human_approval: { label: "AGUARDA CTO", bg: "#f59e0b", icon: null },
  blocked_risk: { label: "BLOQUEADO", bg: "#ef4444", icon: null },
  failed: { label: "FALHOU", bg: "#ef4444", icon: null },
  cancelled: { label: "CANCELADO", bg: "#64748b", icon: null },
};

const AUTO_THRESHOLD = 500;

export default function PaymentsList({ refreshKey }) {
  const [payments, setPayments] = useState([]);
  const [payees, setPayees] = useState([]);
  const [tab, setTab] = useState("all");
  const [month, setMonth] = useState(currentMonth());
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [showReceipt, setShowReceipt] = useState(null);
  const [err, setErr] = useState(null);

  const reload = async () => {
    setLoading(true); setErr(null);
    try {
      const params = { month };
      const filter = TABS.find((t) => t.id === tab)?.filter;
      if (filter) params.status_eq = filter;
      const [pays, pys] = await Promise.all([
        treasuryApi.listPayments(params),
        treasuryApi.listPayees(),
      ]);
      setPayments(pays.payments || []);
      setPayees(pys.payees || []);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [tab, refreshKey, month]);

  const approve = async (id) => {
    setBusyId(id);
    try { await treasuryApi.approve(id, "Aprovado via painel"); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };
  const cancel = async (id) => {
    const reason = window.prompt("Motivo do cancelamento?", "Cancelado pelo CTO");
    if (!reason) return;
    setBusyId(id);
    try { await treasuryApi.cancel(id, reason); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };
  const send = async (id) => {
    if (!window.confirm("Enviar para o Asaas agora?")) return;
    setBusyId(id);
    try {
      const r = await treasuryApi.send(id);
      if (!r.ok) {
        const msg = r.asaas?.asaas_error?.errors?.[0]?.description || JSON.stringify(r);
        alert("Asaas recusou: " + msg);
      }
      await reload();
    } catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };
  const markPaidManual = async (id) => {
    const note = window.prompt("Observação (ex: pagamento feito por TED direta):") || "";
    setBusyId(id);
    try { await treasuryApi.markPaidManual(id, note); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };
  const toggleAuto = async (id, current) => {
    setBusyId(id);
    try { await treasuryApi.toggleAutoEligible(id, !current); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };

  // Agrupa pagamentos por mês de vencimento
  const grouped = useMemo(() => {
    const map = new Map();
    payments.forEach((p) => {
      const ym = monthOf(p.scheduled_for || p.due_date);
      if (!map.has(ym)) map.set(ym, []);
      map.get(ym).push(p);
    });
    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([ym, items]) => ({
        ym,
        items,
        total: items.reduce((s, x) => s + (x.amount_brl || 0), 0),
        paid: items.filter((x) => x.status === "paid")
          .reduce((s, x) => s + (x.amount_brl || 0), 0),
      }));
  }, [payments]);

  return (
    <div data-testid="treasury-payments-tab" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 14, gap: 12, flexWrap: "wrap" }}>
        <h3 style={{ color: C.text, margin: 0, fontSize: 18,
          display: "inline-flex", alignItems: "center", gap: 8 }}>
          <Banknote size={18} color={C.accent}/> A pagar / Histórico
        </h3>
        <button data-testid="btn-new-payment" onClick={() => setShowNew(true)}
          style={btnPrimary}><Plus size={14}/> Novo pagamento</button>
      </div>

      {/* Seletor de período */}
      <MonthFilter month={month} setMonth={setMonth} />

      {/* Filtros por status */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t.id} data-testid={`pay-filter-${t.id}`}
            onClick={() => setTab(t.id)}
            style={{
              padding: "7px 12px", borderRadius: 8, fontSize: 12,
              fontWeight: 600, cursor: "pointer",
              background: tab === t.id ? C.accent : C.cardSoft,
              color: tab === t.id ? "white" : C.text,
              border: `1px solid ${tab === t.id ? C.accent : C.border}`,
            }}>{t.label}</button>
        ))}
      </div>

      {err && <div style={errBox}>{err}</div>}
      {loading && <div style={{ color: C.muted }}>Carregando...</div>}

      {/* Lista agrupada por mês */}
      {grouped.length === 0 && !loading && (
        <div style={{ background: C.card, border: `1px solid ${C.border}`,
          borderRadius: 12, padding: 32, textAlign: "center", color: C.muted }}>
          Nenhum pagamento neste filtro/período.
        </div>
      )}

      {grouped.map(({ ym, items, total, paid }) => (
        <div key={ym} data-testid={`month-group-${ym}`}
          style={{ marginBottom: 18 }}>
          <div style={{
            background: C.cardSoft, border: `1px solid ${C.border}`,
            borderRadius: 10, padding: "10px 14px",
            display: "flex", justifyContent: "space-between",
            alignItems: "center", marginBottom: 8,
          }}>
            <strong style={{ color: C.text, fontSize: 13,
              textTransform: "uppercase", letterSpacing: 0.6 }}>
              <Calendar size={14} style={{ marginRight: 6,
                verticalAlign: "middle" }}/>
              {monthLabel(ym)}
              <span style={{ marginLeft: 8, color: C.muted,
                fontSize: 11, fontWeight: 500 }}>
                ({items.length} pagamentos)
              </span>
            </strong>
            <div style={{ fontSize: 12, color: C.muted }}>
              Total: <strong style={{ color: C.text }}>{BRL(total)}</strong>
              {" · "}
              Pago: <strong style={{ color: C.green }}>{BRL(paid)}</strong>
            </div>
          </div>
          <div style={{ background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 10, overflow: "hidden" }}>
            <table data-testid={`payments-table-${ym}`} style={{ width: "100%",
              borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: C.cardSoft }}>
                  <Th style={{ width: 30 }}/>
                  <Th>Beneficiário</Th><Th>Forma</Th><Th>Vencimento</Th>
                  <Th style={{ textAlign: "right" }}>Valor</Th>
                  <Th>Status</Th>
                  <Th style={{ textAlign: "center", width: 90 }}>Auto</Th>
                  <Th style={{ textAlign: "right" }}>Ações</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <PaymentRow key={p.payment_id} p={p}
                    busy={busyId === p.payment_id}
                    onApprove={() => approve(p.payment_id)}
                    onSend={() => send(p.payment_id)}
                    onCancel={() => cancel(p.payment_id)}
                    onReceipt={() => setShowReceipt(p)}
                    onMarkPaid={() => markPaidManual(p.payment_id)}
                    onToggleAuto={() => toggleAuto(p.payment_id,
                      p.auto_approval_eligible)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {showNew && <NewPaymentModal payees={payees}
        onClose={() => setShowNew(false)}
        onCreated={() => { setShowNew(false); reload(); }} />}

      {showReceipt && <SendReceiptModal payment={showReceipt}
        onClose={() => setShowReceipt(null)} />}
    </div>
  );
}

function PaymentRow({ p, busy, onApprove, onSend, onCancel, onReceipt,
                     onMarkPaid, onToggleAuto }) {
  const s = STATUS_BADGE[p.status] || { label: p.status.toUpperCase(),
                                          bg: C.muted, icon: null };
  const IconStatus = s.icon;
  const isHigh = (p.amount_brl || 0) >= AUTO_THRESHOLD;
  return (
    <tr data-testid={`payment-row-${p.payment_id}`}
      style={{ borderTop: `1px solid ${C.border}` }}>
      <Td style={{ paddingLeft: 14 }}>
        {/* Checkbox de auto-elegível só faz sentido pra valores >= teto */}
        {isHigh && (p.status === "draft"
                    || p.status === "pending_human_approval") && (
          <input type="checkbox" data-testid={`chk-auto-${p.payment_id}`}
            checked={!!p.auto_approval_eligible} onChange={onToggleAuto}
            disabled={busy} title="Marcar como elegível para auto-aprovação"
            style={{ cursor: "pointer" }}/>
        )}
      </Td>
      <Td>
        <div style={{ color: C.text, fontWeight: 600 }}>{p.payee_name}</div>
        <div style={{ color: C.muted, fontSize: 11 }}>
          {p.description || ""}
          {p.paid_manually && (
            <span style={{ color: "#0ea5e9", marginLeft: 4 }}>
              · pago manual</span>
          )}
        </div>
      </Td>
      <Td>
        <span style={{
          background: p.method === "bill" ? C.blue : C.accent2,
          color: "white", padding: "2px 8px", borderRadius: 4,
          fontSize: 10, fontWeight: 700, letterSpacing: .5,
        }}>{(p.method || "pix").toUpperCase()}</span>
      </Td>
      <Td>{DateBR(p.scheduled_for || p.due_date)}</Td>
      <Td style={{ textAlign: "right", color: C.text, fontWeight: 700 }}>
        {BRL(p.amount_brl)}</Td>
      <Td>
        <span data-testid={`status-${p.payment_id}`} style={{
          background: s.bg, color: "white", padding: "4px 10px",
          borderRadius: 6, fontSize: 11, fontWeight: 700, letterSpacing: .5,
          display: "inline-flex", alignItems: "center", gap: 4,
        }}>
          {IconStatus && <IconStatus size={12}/>}
          {s.label}
        </span>
      </Td>
      <Td style={{ textAlign: "center" }}>
        {p.auto_approval_eligible
          ? <span style={{ color: C.green, fontWeight: 700, fontSize: 11 }}>✓ ELEGÍVEL</span>
          : (isHigh ? <span style={{ color: C.muted, fontSize: 11 }}>—</span>
                    : <span style={{ color: C.muted, fontSize: 10 }}>auto ≤ R$ 500</span>)}
      </Td>
      <Td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
        {(p.status === "draft" || p.status === "pending_human_approval") && (
          <button data-testid={`btn-approve-${p.payment_id}`}
            onClick={onApprove} disabled={busy} title="Aprovar"
            style={{ ...btnGhost, color: C.green, marginRight: 4 }}>
            <CheckCircle2 size={14}/></button>
        )}
        {p.status === "approved" && (
          <button data-testid={`btn-send-${p.payment_id}`}
            onClick={onSend} disabled={busy} title="Enviar pro banco"
            style={{ ...btnGhost, color: C.blue, marginRight: 4 }}>
            <Send size={14}/></button>
        )}
        {(p.status === "approved" || p.status === "sent_to_bank") && (
          <button data-testid={`btn-mark-paid-${p.payment_id}`}
            onClick={onMarkPaid} disabled={busy} title="Marcar como pago manual"
            style={{ ...btnGhost, color: C.green, marginRight: 4 }}>
            <BadgeCheck size={14}/></button>
        )}
        {(p.status === "sent_to_bank" || p.status === "paid") && (
          <button data-testid={`btn-receipt-${p.payment_id}`}
            onClick={onReceipt} title="Enviar comprovante WhatsApp"
            style={{ ...btnGhost, color: "#22c55e", marginRight: 4 }}>
            <MessageSquare size={14}/></button>
        )}
        {p.status !== "paid" && p.status !== "cancelled" && (
          <button data-testid={`btn-cancel-${p.payment_id}`}
            onClick={onCancel} disabled={busy} title="Cancelar"
            style={{ ...btnGhost, color: C.red }}>
            <XCircle size={14}/></button>
        )}
      </Td>
    </tr>
  );
}

function MonthFilter({ month, setMonth }) {
  return (
    <div data-testid="month-filter" style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 10,
      padding: 10, marginBottom: 14, display: "flex", gap: 8,
      alignItems: "center", flexWrap: "wrap",
    }}>
      <Calendar size={14} color={C.muted}/>
      <button data-testid="month-prev"
        onClick={() => setMonth(addMonths(month, -1))}
        style={btnNav}><ChevronLeft size={14}/></button>
      <input type="month" data-testid="month-input" value={month}
        onChange={(e) => setMonth(e.target.value)} style={input}/>
      <button data-testid="month-next"
        onClick={() => setMonth(addMonths(month, +1))}
        style={btnNav}><ChevronRight size={14}/></button>
      <strong style={{ color: C.text, marginLeft: 6, fontSize: 13 }}>
        {monthLabel(month)}
      </strong>
      <button data-testid="month-now"
        onClick={() => setMonth(currentMonth())}
        style={{ ...btnNav, marginLeft: "auto", padding: "5px 10px",
          fontSize: 11, fontWeight: 600 }}>
        Mês atual
      </button>
    </div>
  );
}

// ─── Modal Novo Pagamento + Modal Comprovante (mesmos da versão anterior) ───
function NewPaymentModal({ payees, onClose, onCreated }) {
  const [tab, setTab] = useState("pix");
  const [f, setF] = useState({
    payee_id: payees[0]?.payee_id || "",
    amount_brl: "", scheduled_for: "", description: "", category: "",
    pix_key: "", pix_key_type: "CPF",
    identification_field: "", bar_code: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async () => {
    if (!f.payee_id || !f.amount_brl || !f.scheduled_for) {
      setErr("Preencha beneficiário, valor e data."); return;
    }
    if (tab === "bill" && !f.identification_field && !f.bar_code) {
      setErr("Cole a linha digitável ou código de barras do boleto."); return;
    }
    setBusy(true); setErr(null);
    try {
      await treasuryApi.createPayment({
        payee_id: f.payee_id, amount_brl: parseFloat(f.amount_brl),
        scheduled_for: f.scheduled_for, description: f.description,
        category: f.category, method: tab,
        ...(tab === "pix" ? { pix_key: f.pix_key } : {}),
        ...(tab === "bill" ? {
          identification_field: f.identification_field, bar_code: f.bar_code,
        } : {}),
      });
      onCreated();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose} title="Novo pagamento" testid="modal-new-payment">
      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {[{ id: "pix", label: "Pix" }, { id: "bill", label: "Boleto" }].map((t) => (
          <button key={t.id} data-testid={`pay-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            style={{
              flex: 1, padding: "8px", borderRadius: 8, fontSize: 13,
              fontWeight: 700, cursor: "pointer",
              background: tab === t.id ? C.accent : C.cardSoft,
              color: tab === t.id ? "white" : C.text,
              border: `1px solid ${tab === t.id ? C.accent : C.border}`,
            }}>{t.label}</button>
        ))}
      </div>
      <Field label="Beneficiário*">
        <select data-testid="pay-payee" value={f.payee_id}
          onChange={(e) => setF({ ...f, payee_id: e.target.value })} style={input}>
          <option value="">— selecione —</option>
          {payees.map((p) => (
            <option key={p.payee_id} value={p.payee_id}>
              {p.name} {p.pix_key ? `(${p.pix_key})` : ""}
            </option>
          ))}
        </select>
      </Field>
      <div style={{ display: "flex", gap: 10 }}>
        <Field label="Valor (R$)*"><input type="number" step="0.01"
          data-testid="pay-amount" value={f.amount_brl}
          onChange={(e) => setF({ ...f, amount_brl: e.target.value })} style={input}/></Field>
        <Field label="Data agendada*"><input type="date" data-testid="pay-date"
          value={f.scheduled_for}
          onChange={(e) => setF({ ...f, scheduled_for: e.target.value })} style={input}/></Field>
      </div>
      {tab === "pix" && (
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="Tipo chave Pix">
            <select data-testid="pay-pix-type" value={f.pix_key_type}
              onChange={(e) => setF({ ...f, pix_key_type: e.target.value })} style={input}>
              <option value="CPF">CPF</option><option value="CNPJ">CNPJ</option>
              <option value="EMAIL">Email</option><option value="PHONE">Telefone</option>
              <option value="EVP">EVP (aleatória)</option>
            </select></Field>
          <Field label="Chave Pix (sobrescreve)">
            <input data-testid="pay-pix-key" value={f.pix_key}
              onChange={(e) => setF({ ...f, pix_key: e.target.value })} style={input}
              placeholder={f.pix_key_type === "PHONE" ? "+5511999999999" : ""}/></Field>
        </div>
      )}
      {tab === "bill" && (
        <>
          <Field label="Linha digitável (47 dígitos)">
            <input data-testid="pay-bill-line" value={f.identification_field}
              onChange={(e) => setF({ ...f, identification_field: e.target.value })}
              style={input}/></Field>
          <Field label="OU código de barras (44 dígitos)">
            <input data-testid="pay-bill-barcode" value={f.bar_code}
              onChange={(e) => setF({ ...f, bar_code: e.target.value })} style={input}/></Field>
        </>
      )}
      <Field label="Descrição"><input data-testid="pay-desc" value={f.description}
        onChange={(e) => setF({ ...f, description: e.target.value })} style={input}/></Field>
      <Field label="Categoria"><input data-testid="pay-category" value={f.category}
        onChange={(e) => setF({ ...f, category: e.target.value })} style={input}/></Field>
      {err && <div style={errBox}>{err}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button data-testid="btn-create-payment" onClick={submit} disabled={busy}
          style={{ ...btnPrimary, flex: 1 }}>
          {busy ? "Criando..." : "Criar pagamento"}</button>
        <button onClick={onClose} style={btnGhost}>Cancelar</button>
      </div>
    </Overlay>
  );
}

function SendReceiptModal({ payment, onClose }) {
  const [phone, setPhone] = useState("");
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    treasuryApi.receiptPreview(payment.payment_id)
      .then((d) => setPreview(d.text || "")).catch(() => {});
  }, [payment.payment_id]);

  const send = async () => {
    if (!phone) { alert("Informe o telefone (DDD + número)"); return; }
    setBusy(true); setResult(null);
    try { setResult(await treasuryApi.sendReceipt(payment.payment_id, phone)); }
    catch (e) { setResult({ ok: false, error: e?.response?.data?.detail || e.message }); }
    finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose} title="Enviar comprovante via WhatsApp"
      testid="modal-send-receipt">
      <div style={{ color: C.muted, fontSize: 12, marginBottom: 8 }}>
        Beneficiário: <strong style={{ color: C.text }}>{payment.payee_name}</strong>
        {" · "}{BRL(payment.amount_brl)}
      </div>
      <Field label="Telefone do destinatário (DDD + número)*">
        <input data-testid="receipt-phone" value={phone}
          onChange={(e) => setPhone(e.target.value)} style={input}
          placeholder="11999999999"/>
      </Field>
      <div style={{ color: C.muted, fontSize: 11, marginTop: 8, marginBottom: 4 }}>
        Preview do comprovante (assinado by SmartProv):
      </div>
      <pre data-testid="receipt-preview" style={{
        background: C.cardSoft, color: C.text, padding: 12, borderRadius: 8,
        fontSize: 11, whiteSpace: "pre-wrap", maxHeight: 240, overflowY: "auto",
        border: `1px solid ${C.border}`,
      }}>{preview || "carregando..."}</pre>
      {result && (
        <div style={{
          marginTop: 12, padding: 10, borderRadius: 8, fontSize: 12,
          background: result.ok ? "#d1fae5" : "#fee2e2",
          color: result.ok ? "#065f46" : "#991b1b",
        }}>
          {result.ok
            ? `✓ Enviado para ${result.phone} (msg ${result.message_id || "-"})`
            : `✗ Falhou: ${result.error || JSON.stringify(result)}`}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button data-testid="btn-send-receipt" onClick={send} disabled={busy}
          style={{ ...btnPrimary, flex: 1 }}>
          {busy ? "Enviando..." : "Enviar comprovante"}</button>
        <button onClick={onClose} style={btnGhost}>Fechar</button>
      </div>
    </Overlay>
  );
}

const Th = ({ children, style }) => <th style={{ padding: "10px 12px",
  textAlign: "left", color: C.muted, fontWeight: 600, fontSize: 11,
  textTransform: "uppercase", letterSpacing: 0.5, ...style }}>{children}</th>;
const Td = ({ children, style }) => <td style={{ padding: "12px",
  color: C.text, ...style }}>{children}</td>;
const Field = ({ label, children }) => (
  <div style={{ marginBottom: 12, flex: 1 }}>
    <div style={{ color: C.muted, fontSize: 11, marginBottom: 4 }}>{label}</div>
    {children}
  </div>);
const input = { padding: "8px 10px", borderRadius: 8,
  border: `1px solid ${C.border}`, background: C.card, color: C.text,
  fontSize: 13, width: "100%" };
const btnPrimary = { background: C.accent, color: "white", border: 0,
  borderRadius: 8, padding: "8px 14px", fontWeight: 700, fontSize: 13,
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 };
const btnGhost = { background: "transparent", color: C.text,
  border: `1px solid ${C.border}`, borderRadius: 8, padding: "6px 10px",
  fontSize: 12, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4 };
const btnNav = { background: C.cardSoft, color: C.text, border: `1px solid ${C.border}`,
  borderRadius: 6, padding: "5px 8px", cursor: "pointer",
  display: "inline-flex", alignItems: "center" };
const errBox = { background: "#fee2e2", color: "#991b1b", padding: 10,
  borderRadius: 8, marginTop: 12, fontSize: 12 };

function Overlay({ children, onClose, title, testid }) {
  return (
    <div data-testid={testid} style={{ position: "fixed", inset: 0,
      background: "rgba(15,23,42,.45)", zIndex: 9000, display: "flex",
      alignItems: "center", justifyContent: "center" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: C.card, padding: 20, borderRadius: 14,
        width: 560, maxWidth: "92vw", maxHeight: "92vh", overflowY: "auto",
        border: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", justifyContent: "space-between",
          marginBottom: 16, alignItems: "center" }}>
          <h3 style={{ color: C.text, margin: 0, fontSize: 16 }}>{title}</h3>
          <button onClick={onClose} data-testid={`${testid}-close`}
            style={{ background: "transparent", border: 0, color: C.muted,
              fontSize: 24, cursor: "pointer" }}>×</button>
        </div>
        {children}
      </div>
    </div>);
}
