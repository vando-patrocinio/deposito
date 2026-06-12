/**
 * AccountsList.jsx — gerencia múltiplas contas de pagamento e a "conta padrão".
 * Inspirado em Conta Azul: tabela enxuta + ação "Tornar padrão" inline.
 */
import React, { useEffect, useState } from "react";
import { Check, Star, Trash2, Plus } from "lucide-react";
import { treasuryApi, C } from "./api";

export default function AccountsList() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [err, setErr] = useState(null);

  const reload = async () => {
    setLoading(true);
    try {
      const d = await treasuryApi.listAccounts();
      setAccounts(d.accounts || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };

  useEffect(() => { reload(); }, []);

  const setDefault = async (id) => {
    try {
      await treasuryApi.setDefaultAccount(id);
      await reload();
    } catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
  };

  const del = async (id) => {
    if (!window.confirm("Inativar esta conta?")) return;
    try { await treasuryApi.deleteAccount(id); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
  };

  return (
    <div data-testid="treasury-accounts-tab" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 16 }}>
        <div>
          <h3 style={{ color: C.text, margin: 0, fontSize: 18 }}>Contas de pagamento</h3>
          <div style={{ color: C.muted, fontSize: 12, marginTop: 4 }}>
            A conta marcada com ⭐ será usada como origem padrão dos pagamentos.
          </div>
        </div>
        <button
          data-testid="btn-new-account"
          onClick={() => setShowNew(true)}
          style={btnPrimary}>
          <Plus size={14} /> Nova conta
        </button>
      </div>

      {loading && <div style={{ color: C.muted }}>Carregando...</div>}
      {err && <div style={errBox}>{err}</div>}

      <div style={{ background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, overflow: "hidden" }}>
        <table data-testid="accounts-table" style={{ width: "100%",
          borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: C.cardSoft }}>
              <Th>Conta</Th><Th>Banco</Th><Th>CNPJ</Th>
              <Th>Chaves Pix</Th><Th style={{ textAlign: "center" }}>Padrão</Th>
              <Th style={{ textAlign: "right" }}>Ações</Th>
            </tr>
          </thead>
          <tbody>
            {accounts.length === 0 && !loading && (
              <tr><td colSpan={6} style={{ padding: 24, color: C.muted,
                textAlign: "center" }}>Nenhuma conta cadastrada.</td></tr>
            )}
            {accounts.map((a) => (
              <tr key={a.account_id} data-testid={`account-row-${a.account_id}`}
                  style={{ borderTop: `1px solid ${C.border}` }}>
                <Td><strong style={{ color: C.text }}>{a.name}</strong></Td>
                <Td>{a.bank || "—"}</Td>
                <Td>{a.cnpj || "—"}</Td>
                <Td>{(a.pix_keys || []).join(", ") || "—"}</Td>
                <Td style={{ textAlign: "center" }}>
                  {a.is_default
                    ? <span style={{ color: C.amber, fontWeight: 700,
                        display: "inline-flex", alignItems: "center", gap: 4 }}>
                        <Star size={14} fill={C.amber}/> PADRÃO</span>
                    : <button data-testid={`btn-set-default-${a.account_id}`}
                        onClick={() => setDefault(a.account_id)}
                        style={btnGhost}>Tornar padrão</button>}
                </Td>
                <Td style={{ textAlign: "right" }}>
                  {!a.is_default && (
                    <button data-testid={`btn-del-account-${a.account_id}`}
                      onClick={() => del(a.account_id)}
                      style={{ ...btnGhost, color: C.red }}>
                      <Trash2 size={14}/>
                    </button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showNew && <NewAccountModal
        onClose={() => setShowNew(false)}
        onCreated={() => { setShowNew(false); reload(); }} />}
    </div>
  );
}

function NewAccountModal({ onClose, onCreated }) {
  const [f, setF] = useState({ name: "", bank: "Asaas", cnpj: "",
    pix_keys: "", description: "", is_default: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async () => {
    if (!f.name) { setErr("Nome é obrigatório"); return; }
    setBusy(true); setErr(null);
    try {
      await treasuryApi.createAccount({
        ...f,
        pix_keys: f.pix_keys.split(",").map((s) => s.trim()).filter(Boolean),
      });
      onCreated();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose} title="Nova conta de pagamento" testid="modal-new-account">
      <Field label="Nome*"><input data-testid="acc-name" value={f.name}
        onChange={(e) => setF({ ...f, name: e.target.value })} style={input}/></Field>
      <Field label="Banco"><input data-testid="acc-bank" value={f.bank}
        onChange={(e) => setF({ ...f, bank: e.target.value })} style={input}/></Field>
      <Field label="CNPJ"><input data-testid="acc-cnpj" value={f.cnpj}
        onChange={(e) => setF({ ...f, cnpj: e.target.value })} style={input}/></Field>
      <Field label="Chaves Pix (separadas por vírgula)">
        <input data-testid="acc-pix-keys" value={f.pix_keys}
          onChange={(e) => setF({ ...f, pix_keys: e.target.value })} style={input}
          placeholder="CNPJ, email@dominio.com, +5511..." /></Field>
      <label style={{ display: "flex", gap: 6, color: C.text, fontSize: 13,
        marginTop: 8, alignItems: "center" }}>
        <input type="checkbox" data-testid="acc-is-default"
          checked={f.is_default}
          onChange={(e) => setF({ ...f, is_default: e.target.checked })}/>
        Definir como conta padrão
      </label>
      {err && <div style={errBox}>{err}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button data-testid="btn-create-account" onClick={submit} disabled={busy}
          style={{ ...btnPrimary, flex: 1 }}>
          {busy ? "Criando..." : "Criar conta"}</button>
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
  <div style={{ marginBottom: 12 }}>
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
        width: 460, maxWidth: "92vw", maxHeight: "92vh", overflowY: "auto",
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
