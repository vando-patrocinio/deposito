/**
 * PaymentsList.jsx — Lista de pagamentos com filtros por status.
 * Inclui: criar pagamento manual (Pix chave/telefone/boleto), aprovar,
 * cancelar, enviar (ao banco), e enviar COMPROVANTE via WhatsApp.
 */
import React, { useEffect, useState } from "react";
import {
  Plus, CheckCircle2, Send, XCircle, MessageSquare, Eye, Banknote,
} from "lucide-react";
import { treasuryApi, C, BRL, DateBR, STATUS_META } from "./api";

const TABS = [
  { id: "all", label: "Todos", filter: null },
  { id: "draft", label: "Rascunhos", filter: "draft" },
  { id: "pending_human_approval", label: "Aguarda CTO", filter: "pending_human_approval" },
  { id: "approved", label: "Aprovados", filter: "approved" },
  { id: "sent_to_bank", label: "Enviados", filter: "sent_to_bank" },
  { id: "paid", label: "Pagos", filter: "paid" },
  { id: "failed", label: "Falhou", filter: "failed" },
];

export default function PaymentsList({ refreshKey }) {
  const [payments, setPayments] = useState([]);
  const [payees, setPayees] = useState([]);
  const [tab, setTab] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [showReceipt, setShowReceipt] = useState(null); // payment object
  const [err, setErr] = useState(null);

  const reload = async () => {
    setLoading(true); setErr(null);
    try {
      const filter = TABS.find((t) => t.id === tab)?.filter;
      const [pays, pys] = await Promise.all([
        treasuryApi.listPayments(filter),
        treasuryApi.listPayees(),
      ]);
      setPayments(pays.payments || []);
      setPayees(pys.payees || []);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  // eslint-disable-next-line
  useEffect(() => { reload(); }, [tab, refreshKey]);

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
    if (!window.confirm("Enviar para o Asaas agora? (operação real)")) return;
    setBusyId(id);
    try {
      const r = await treasuryApi.send(id);
      if (!r.ok) {
        const msg = r.asaas?.asaas_error?.errors?.[0]?.description
          || JSON.stringify(r);
        alert("Asaas recusou: " + msg);
      }
      await reload();
    } catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };

  return (
    <div data-testid="treasury-payments-tab" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 14 }}>
        <h3 style={{ color: C.text, margin: 0, fontSize: 18,
          display: "inline-flex", alignItems: "center", gap: 8 }}>
          <Banknote size={18} color={C.accent}/> A pagar / Histórico
        </h3>
        <button data-testid="btn-new-payment" onClick={() => setShowNew(true)}
          style={btnPrimary}><Plus size={14}/> Novo pagamento</button>
      </div>

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

      <div style={{ background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, overflow: "hidden" }}>
        <table data-testid="payments-table" style={{ width: "100%",
          borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: C.cardSoft }}>
              <Th>Beneficiário</Th><Th>Forma</Th><Th>Vencimento</Th>
              <Th style={{ textAlign: "right" }}>Valor</Th>
              <Th>Status</Th><Th style={{ textAlign: "right" }}>Ações</Th>
            </tr>
          </thead>
          <tbody>
            {payments.length === 0 && !loading && (
              <tr><td colSpan={6} style={{ padding: 28, color: C.muted,
                textAlign: "center" }}>Nenhum pagamento neste filtro.</td></tr>
            )}
            {payments.map((p) => {
              const s = STATUS_META[p.status] || { label: p.status, color: C.muted };
              return (
                <tr key={p.payment_id}
                  data-testid={`payment-row-${p.payment_id}`}
                  style={{ borderTop: `1px solid ${C.border}` }}>
                  <Td>
                    <div style={{ color: C.text, fontWeight: 600 }}>{p.payee_name}</div>
                    <div style={{ color: C.muted, fontSize: 11 }}>{p.description || ""}</div>
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
                    <span style={{
                      background: s.color, color: "white", padding: "2px 8px",
                      borderRadius: 6, fontSize: 11, fontWeight: 600,
                    }}>{s.label}</span>
                  </Td>
                  <Td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {(p.status === "draft" || p.status === "pending_human_approval") && (
                      <button data-testid={`btn-approve-${p.payment_id}`}
                        onClick={() => approve(p.payment_id)} disabled={busyId === p.payment_id}
                        style={{ ...btnGhost, color: C.green, marginRight: 4 }}>
                        <CheckCircle2 size={14}/></button>
                    )}
                    {p.status === "approved" && (
                      <button data-testid={`btn-send-${p.payment_id}`}
                        onClick={() => send(p.payment_id)} disabled={busyId === p.payment_id}
                        style={{ ...btnGhost, color: C.blue, marginRight: 4 }}>
                        <Send size={14}/></button>
                    )}
                    {(p.status === "sent_to_bank" || p.status === "paid") && (
                      <button data-testid={`btn-receipt-${p.payment_id}`}
                        onClick={() => setShowReceipt(p)}
                        style={{ ...btnGhost, color: "#22c55e", marginRight: 4 }}>
                        <MessageSquare size={14}/></button>
                    )}
                    {p.status !== "paid" && p.status !== "cancelled" && (
                      <button data-testid={`btn-cancel-${p.payment_id}`}
                        onClick={() => cancel(p.payment_id)} disabled={busyId === p.payment_id}
                        style={{ ...btnGhost, color: C.red }}>
                        <XCircle size={14}/></button>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showNew && <NewPaymentModal payees={payees}
        onClose={() => setShowNew(false)}
        onCreated={() => { setShowNew(false); reload(); }} />}

      {showReceipt && <SendReceiptModal payment={showReceipt}
        onClose={() => setShowReceipt(null)} />}
    </div>
  );
}

function NewPaymentModal({ payees, onClose, onCreated }) {
  const [tab, setTab] = useState("pix"); // pix | bill
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
    if (tab === "pix" && !f.pix_key) {
      const payee = payees.find((p) => p.payee_id === f.payee_id);
      if (!payee?.pix_key) { setErr("Defina uma chave Pix manualmente (o beneficiário não tem)."); return; }
    }
    if (tab === "bill" && !f.identification_field && !f.bar_code) {
      setErr("Cole a linha digitável ou código de barras do boleto."); return;
    }
    setBusy(true); setErr(null);
    try {
      await treasuryApi.createPayment({
        payee_id: f.payee_id,
        amount_brl: parseFloat(f.amount_brl),
        scheduled_for: f.scheduled_for,
        description: f.description, category: f.category,
        method: tab,
        ...(tab === "pix" ? { pix_key: f.pix_key } : {}),
        ...(tab === "bill"
          ? { identification_field: f.identification_field, bar_code: f.bar_code }
          : {}),
      });
      onCreated();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose} title="Novo pagamento" testid="modal-new-payment">
      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {[
          { id: "pix", label: "Pix" },
          { id: "bill", label: "Boleto" },
        ].map((t) => (
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
              {p.name} {p.pix_key ? `(Pix: ${p.pix_key})` : ""}
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
        <>
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
        </>
      )}

      {tab === "bill" && (
        <>
          <Field label="Linha digitável (47 dígitos)">
            <input data-testid="pay-bill-line" value={f.identification_field}
              onChange={(e) => setF({ ...f, identification_field: e.target.value })}
              style={input} placeholder="00190.00009 03374.477008 06367.180005 1 12345678901234"/>
          </Field>
          <Field label="OU código de barras (44 dígitos)">
            <input data-testid="pay-bill-barcode" value={f.bar_code}
              onChange={(e) => setF({ ...f, bar_code: e.target.value })} style={input}/>
          </Field>
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
      .then((d) => setPreview(d.text || ""))
      .catch(() => {});
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
          background: result.ok ? "#064e3b" : "#7f1d1d", color: "white",
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
const input = { width: "100%", padding: "8px 10px", borderRadius: 8,
  border: `1px solid ${C.border}`, background: C.cardSoft, color: C.text,
  fontSize: 13 };
const btnPrimary = { background: C.accent, color: "white", border: 0,
  borderRadius: 8, padding: "8px 14px", fontWeight: 700, fontSize: 13,
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 };
const btnGhost = { background: "transparent", color: C.text,
  border: `1px solid ${C.border}`, borderRadius: 8, padding: "6px 10px",
  fontSize: 12, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4 };
const errBox = { background: "#7f1d1d", color: "white", padding: 10,
  borderRadius: 8, marginTop: 12, fontSize: 12 };

function Overlay({ children, onClose, title, testid }) {
  return (
    <div data-testid={testid} style={{ position: "fixed", inset: 0,
      background: "rgba(0,0,0,.6)", zIndex: 9000, display: "flex",
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
