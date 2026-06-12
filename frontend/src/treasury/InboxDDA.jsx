/**
 * InboxDDA.jsx — Inbox de boletos DDA (Débito Direto Autorizado).
 * Padrão Bill.com: lista com vendor, valor, vencimento, status, ações
 * inline (Aprovar/Rejeitar). Boletos aprovados viram scheduled_payments.
 */
import React, { useEffect, useState } from "react";
import { Inbox, CheckCircle2, XCircle, Plus, AlertTriangle } from "lucide-react";
import { treasuryApi, C, BRL, DateBR } from "./api";

const TAB_FILTERS = [
  { id: "pending", label: "Aguardando", color: C.amber },
  { id: "scheduled", label: "Aprovados", color: C.blue },
  { id: "rejected", label: "Rejeitados", color: C.muted },
];

export default function InboxDDA({ onPaymentCreated }) {
  const [data, setData] = useState({ inbox: [], counts: {} });
  const [active, setActive] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [err, setErr] = useState(null);

  const reload = async () => {
    setLoading(true); setErr(null);
    try { setData(await treasuryApi.listDDA(active)); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [active]);

  const approve = async (id) => {
    setBusyId(id);
    try {
      const r = await treasuryApi.approveDDA(id);
      if (r?.ok) {
        onPaymentCreated && onPaymentCreated(r.payment_id);
        await reload();
      } else { alert("Falhou: " + JSON.stringify(r)); }
    } catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };
  const reject = async (id) => {
    const reason = window.prompt("Motivo da rejeição?");
    if (!reason) return;
    setBusyId(id);
    try { await treasuryApi.rejectDDA(id, reason); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusyId(null); }
  };

  return (
    <div data-testid="treasury-dda-tab" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 14 }}>
        <div>
          <h3 style={{ color: C.text, margin: 0, fontSize: 18,
            display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Inbox size={18} color={C.accent}/> Inbox DDA
          </h3>
          <div style={{ color: C.muted, fontSize: 12, marginTop: 4 }}>
            Boletos recebidos aguardando aprovação. Aprovar gera um pagamento agendado.
          </div>
        </div>
        <button data-testid="btn-new-dda" onClick={() => setShowNew(true)}
          style={btnPrimary}><Plus size={14}/> Adicionar boleto</button>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {TAB_FILTERS.map((t) => (
          <button key={t.id} data-testid={`dda-filter-${t.id}`}
            onClick={() => setActive(t.id)}
            style={{
              padding: "8px 14px", borderRadius: 8, fontSize: 13,
              fontWeight: 600, cursor: "pointer",
              background: active === t.id ? t.color : C.cardSoft,
              color: active === t.id ? "white" : C.text,
              border: `1px solid ${active === t.id ? t.color : C.border}`,
            }}>
            {t.label}
            <span style={{ marginLeft: 8, opacity: .8, fontSize: 11 }}>
              {data.counts?.[t.id] ?? 0}
            </span>
          </button>
        ))}
      </div>

      {err && <div style={errBox}>{err}</div>}
      {loading && <div style={{ color: C.muted }}>Carregando...</div>}

      <div style={{ background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, overflow: "hidden" }}>
        <table data-testid="dda-table" style={{ width: "100%",
          borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: C.cardSoft }}>
              <Th>Fornecedor</Th><Th>Vencimento</Th>
              <Th style={{ textAlign: "right" }}>Valor</Th>
              <Th>Categoria</Th><Th>Origem</Th>
              <Th style={{ textAlign: "right" }}>Ações</Th>
            </tr>
          </thead>
          <tbody>
            {data.inbox?.length === 0 && !loading && (
              <tr><td colSpan={6} style={{ padding: 28, color: C.muted,
                textAlign: "center" }}>
                <Inbox size={32} color={C.muted} style={{ marginBottom: 8 }}/>
                <div>Nenhum boleto neste status.</div>
              </td></tr>
            )}
            {(data.inbox || []).map((d) => {
              const overdue = d.due_date &&
                new Date(d.due_date) < new Date(new Date().toDateString());
              return (
                <tr key={d.dda_id} data-testid={`dda-row-${d.dda_id}`}
                    style={{ borderTop: `1px solid ${C.border}` }}>
                  <Td>
                    <div style={{ color: C.text, fontWeight: 600 }}>{d.payee_name}</div>
                    <div style={{ color: C.muted, fontSize: 11 }}>{d.payee_document || ""}</div>
                  </Td>
                  <Td>
                    <span style={{ color: overdue && active === "pending" ? C.red : C.text }}>
                      {DateBR(d.due_date)}
                    </span>
                    {overdue && active === "pending" && (
                      <span style={{ marginLeft: 4 }}>
                        <AlertTriangle size={12} color={C.red}/>
                      </span>
                    )}
                  </Td>
                  <Td style={{ textAlign: "right", color: C.text, fontWeight: 700 }}>
                    {BRL(d.amount_brl)}
                  </Td>
                  <Td>{d.category || "—"}</Td>
                  <Td><span style={{ fontSize: 11, color: C.muted,
                    textTransform: "uppercase", letterSpacing: .4 }}>
                    {d.source}</span></Td>
                  <Td style={{ textAlign: "right" }}>
                    {active === "pending" && (
                      <>
                        <button data-testid={`btn-approve-dda-${d.dda_id}`}
                          onClick={() => approve(d.dda_id)}
                          disabled={busyId === d.dda_id}
                          style={{ ...btnGhost, color: C.green, marginRight: 6 }}>
                          <CheckCircle2 size={14}/> Aprovar
                        </button>
                        <button data-testid={`btn-reject-dda-${d.dda_id}`}
                          onClick={() => reject(d.dda_id)}
                          disabled={busyId === d.dda_id}
                          style={{ ...btnGhost, color: C.red }}>
                          <XCircle size={14}/> Rejeitar
                        </button>
                      </>
                    )}
                    {active === "scheduled" && d.linked_payment_id && (
                      <span style={{ color: C.blue, fontSize: 11 }}>
                        → {d.linked_payment_id}
                      </span>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showNew && <NewDDAModal onClose={() => setShowNew(false)}
        onCreated={() => { setShowNew(false); reload(); }} />}
    </div>
  );
}

function NewDDAModal({ onClose, onCreated }) {
  const [f, setF] = useState({ payee_name: "", payee_document: "",
    amount_brl: "", due_date: "", identification_field: "",
    category: "", description: "", source: "manual" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [sim, setSim] = useState(null);

  const simulate = async () => {
    if (!f.identification_field) return;
    setBusy(true); setErr(null);
    try {
      const r = await treasuryApi.simulateBill(
        { identification_field: f.identification_field });
      setSim(r);
      if (r?.ok) {
        const amount = r.value ?? f.amount_brl;
        const due = (r.dueDate || "").slice(0, 10) || f.due_date;
        setF({ ...f, amount_brl: amount || f.amount_brl, due_date: due });
      }
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  const submit = async () => {
    if (!f.payee_name || !f.amount_brl || !f.due_date || !f.identification_field) {
      setErr("Preencha fornecedor, valor, vencimento e linha digitável.");
      return;
    }
    setBusy(true); setErr(null);
    try {
      await treasuryApi.createDDA({
        ...f, amount_brl: parseFloat(f.amount_brl),
      });
      onCreated();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose} title="Adicionar boleto ao Inbox DDA" testid="modal-new-dda">
      <Field label="Linha digitável (47 dígitos)*">
        <div style={{ display: "flex", gap: 6 }}>
          <input data-testid="dda-line" value={f.identification_field}
            onChange={(e) => setF({ ...f, identification_field: e.target.value })}
            style={{ ...input, flex: 1 }} placeholder="00190.00009 03374.477008 06367.180005 1 12345678901234"/>
          <button data-testid="btn-simulate-dda" onClick={simulate}
            disabled={busy || !f.identification_field}
            style={btnGhost}>Validar</button>
        </div>
        {sim?.ok === false && (
          <div style={{ color: C.red, fontSize: 11, marginTop: 4 }}>
            {sim?.asaas_error?.errors?.[0]?.description || "Boleto inválido"}
          </div>
        )}
        {sim?.ok && (
          <div style={{ color: C.green, fontSize: 11, marginTop: 4 }}>
            ✓ Boleto válido — valor {BRL(sim.value || 0)} venc. {DateBR(sim.dueDate)}
          </div>
        )}
      </Field>
      <Field label="Fornecedor*"><input data-testid="dda-payee" value={f.payee_name}
        onChange={(e) => setF({ ...f, payee_name: e.target.value })} style={input}/></Field>
      <Field label="CNPJ/CPF do fornecedor"><input data-testid="dda-doc"
        value={f.payee_document}
        onChange={(e) => setF({ ...f, payee_document: e.target.value })} style={input}/></Field>
      <div style={{ display: "flex", gap: 10 }}>
        <Field label="Valor (R$)*"><input type="number" step="0.01"
          data-testid="dda-amount" value={f.amount_brl}
          onChange={(e) => setF({ ...f, amount_brl: e.target.value })} style={input}/></Field>
        <Field label="Vencimento*"><input type="date" data-testid="dda-due"
          value={f.due_date}
          onChange={(e) => setF({ ...f, due_date: e.target.value })} style={input}/></Field>
      </div>
      <Field label="Categoria"><input data-testid="dda-category"
        value={f.category}
        onChange={(e) => setF({ ...f, category: e.target.value })} style={input}
        placeholder="Energia, Telefonia, Aluguel..."/></Field>
      <Field label="Descrição"><input data-testid="dda-desc" value={f.description}
        onChange={(e) => setF({ ...f, description: e.target.value })} style={input}/></Field>
      {err && <div style={errBox}>{err}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button data-testid="btn-create-dda" onClick={submit} disabled={busy}
          style={{ ...btnPrimary, flex: 1 }}>
          {busy ? "Salvando..." : "Adicionar ao Inbox"}</button>
        <button onClick={onClose} style={btnGhost}>Cancelar</button>
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
        width: 520, maxWidth: "92vw", maxHeight: "92vh", overflowY: "auto",
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
