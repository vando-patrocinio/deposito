/**
 * RecurringList.jsx — Recorrências com data início/fim/valor total.
 * Geração automática de N parcelas (drafts) — mostra o cronograma.
 */
import React, { useEffect, useState } from "react";
import { Repeat, Plus, XCircle } from "lucide-react";
import { treasuryApi, C, BRL, DateBR } from "./api";

export default function RecurringList() {
  const [items, setItems] = useState([]);
  const [payees, setPayees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [err, setErr] = useState(null);

  const reload = async () => {
    setLoading(true); setErr(null);
    try {
      const [r, p] = await Promise.all([
        treasuryApi.listRecurring(), treasuryApi.listPayees()]);
      setItems(r.recurring || []); setPayees(p.payees || []);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, []);

  const cancel = async (id) => {
    if (!window.confirm("Cancelar a recorrência? Drafts futuros serão cancelados.")) return;
    try { await treasuryApi.cancelRecurring(id); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
  };

  return (
    <div data-testid="treasury-recurring-tab" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 14 }}>
        <div>
          <h3 style={{ color: C.text, margin: 0, fontSize: 18,
            display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Repeat size={18} color={C.accent}/> Recorrências
          </h3>
          <div style={{ color: C.muted, fontSize: 12, marginTop: 4 }}>
            Contas com data início/fim e valor total. Parcelas são geradas automaticamente.
          </div>
        </div>
        <button data-testid="btn-new-recurring" onClick={() => setShowNew(true)}
          style={btnPrimary}><Plus size={14}/> Nova recorrência</button>
      </div>

      {err && <div style={errBox}>{err}</div>}
      {loading && <div style={{ color: C.muted }}>Carregando...</div>}

      <div style={{ background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, overflow: "hidden" }}>
        <table data-testid="recurring-table" style={{ width: "100%",
          borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: C.cardSoft }}>
              <Th>Beneficiário</Th><Th>Período</Th><Th>Parcelas</Th>
              <Th style={{ textAlign: "right" }}>Parcela</Th>
              <Th style={{ textAlign: "right" }}>Total</Th>
              <Th>Status</Th>
              <Th style={{ textAlign: "right" }}>Ações</Th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !loading && (
              <tr><td colSpan={7} style={{ padding: 28, color: C.muted,
                textAlign: "center" }}>
                <Repeat size={28} color={C.muted} style={{ marginBottom: 8 }}/>
                <div>Nenhuma recorrência cadastrada.</div>
              </td></tr>
            )}
            {items.map((r) => (
              <tr key={r.recurring_id}
                data-testid={`recurring-row-${r.recurring_id}`}
                style={{ borderTop: `1px solid ${C.border}` }}>
                <Td>
                  <strong style={{ color: C.text }}>{r.payee_name}</strong>
                  {r.description && (
                    <div style={{ color: C.muted, fontSize: 11 }}>{r.description}</div>
                  )}
                </Td>
                <Td>{DateBR(r.start_date)} → {DateBR(r.end_date)}</Td>
                <Td>{r.installments}× ({r.frequency})</Td>
                <Td style={{ textAlign: "right" }}>{BRL(r.parcel_amount_brl)}</Td>
                <Td style={{ textAlign: "right", fontWeight: 700 }}>
                  {BRL(r.amount_total_brl)}</Td>
                <Td>
                  <span style={{
                    background: r.status === "active" ? C.green : C.muted,
                    color: "white", padding: "2px 8px", borderRadius: 6,
                    fontSize: 11, fontWeight: 600,
                  }}>{r.status}</span>
                </Td>
                <Td style={{ textAlign: "right" }}>
                  {r.status === "active" && (
                    <button data-testid={`btn-cancel-rec-${r.recurring_id}`}
                      onClick={() => cancel(r.recurring_id)}
                      style={{ ...btnGhost, color: C.red }}>
                      <XCircle size={14}/> Cancelar
                    </button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showNew && <NewRecurringModal payees={payees}
        onClose={() => setShowNew(false)}
        onCreated={() => { setShowNew(false); reload(); }} />}
    </div>
  );
}

function NewRecurringModal({ payees, onClose, onCreated }) {
  const [f, setF] = useState({
    payee_id: payees[0]?.payee_id || "",
    amount_total_brl: "", start_date: "", end_date: "",
    frequency: "monthly", method: "pix", pay_day: 5,
    description: "", category: "", pix_key: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async () => {
    if (!f.payee_id || !f.amount_total_brl || !f.start_date || !f.end_date) {
      setErr("Preencha beneficiário, valor total e período."); return;
    }
    setBusy(true); setErr(null);
    try {
      await treasuryApi.createRecurring({
        ...f, amount_total_brl: parseFloat(f.amount_total_brl),
        pay_day: parseInt(f.pay_day, 10) || 5,
      });
      onCreated();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose} title="Nova recorrência" testid="modal-new-recurring">
      <Field label="Beneficiário*">
        <select data-testid="rec-payee" value={f.payee_id}
          onChange={(e) => setF({ ...f, payee_id: e.target.value })} style={input}>
          <option value="">— selecione —</option>
          {payees.map((p) => <option key={p.payee_id} value={p.payee_id}>{p.name}</option>)}
        </select>
      </Field>
      <Field label="Valor TOTAL (será dividido em N parcelas)*">
        <input type="number" step="0.01" data-testid="rec-total"
          value={f.amount_total_brl}
          onChange={(e) => setF({ ...f, amount_total_brl: e.target.value })}
          style={input} placeholder="12000"/>
      </Field>
      <div style={{ display: "flex", gap: 10 }}>
        <Field label="Início*"><input type="date" data-testid="rec-start"
          value={f.start_date}
          onChange={(e) => setF({ ...f, start_date: e.target.value })} style={input}/></Field>
        <Field label="Fim*"><input type="date" data-testid="rec-end"
          value={f.end_date}
          onChange={(e) => setF({ ...f, end_date: e.target.value })} style={input}/></Field>
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <Field label="Frequência">
          <select data-testid="rec-freq" value={f.frequency}
            onChange={(e) => setF({ ...f, frequency: e.target.value })} style={input}>
            <option value="monthly">Mensal</option>
            <option value="weekly">Semanal</option>
            <option value="biweekly">Quinzenal</option>
          </select></Field>
        <Field label="Dia do pagamento (1-28)">
          <input type="number" min="1" max="28" data-testid="rec-payday"
            value={f.pay_day}
            onChange={(e) => setF({ ...f, pay_day: e.target.value })} style={input}/></Field>
        <Field label="Forma">
          <select data-testid="rec-method" value={f.method}
            onChange={(e) => setF({ ...f, method: e.target.value })} style={input}>
            <option value="pix">Pix</option>
            <option value="bill">Boleto</option>
          </select></Field>
      </div>
      <Field label="Descrição"><input data-testid="rec-desc" value={f.description}
        onChange={(e) => setF({ ...f, description: e.target.value })} style={input}
        placeholder="Aluguel matriz, internet escritório..."/></Field>
      <Field label="Categoria"><input data-testid="rec-category"
        value={f.category}
        onChange={(e) => setF({ ...f, category: e.target.value })} style={input}/></Field>
      {err && <div style={errBox}>{err}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button data-testid="btn-create-rec" onClick={submit} disabled={busy}
          style={{ ...btnPrimary, flex: 1 }}>
          {busy ? "Criando..." : "Criar recorrência"}</button>
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
        width: 540, maxWidth: "92vw", maxHeight: "92vh", overflowY: "auto",
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
