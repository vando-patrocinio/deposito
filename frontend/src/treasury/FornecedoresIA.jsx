/**
 * FornecedoresIA.jsx — Sub-aba "Fornecedores IA" do painel Tesouraria.
 * Cadastro completo de fornecedor com:
 *   - Dados básicos (nome, CNPJ/CPF)
 *   - Endereço completo (CEP, rua, número, complemento, bairro, cidade, UF)
 *   - Chave Pix + tipo
 *   - WhatsApp (envio automático de comprovante após pagamento)
 *   - Email (opcional)
 *   - Conta padrão de pagamento (vincula a uma das contas em /accounts)
 *   - Auto-send comprovante (toggle)
 *   - Observações
 */
import React, { useEffect, useState } from "react";
import {
  Plus, Edit2, Trash2, MapPin, Phone, Mail, CreditCard, ToggleLeft,
  ToggleRight, Users,
} from "lucide-react";
import { treasuryApi, C } from "./api";
import ReceiptConfigCard from "./ReceiptConfigCard";

export default function FornecedoresIA() {
  const [payees, setPayees] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(null); // null | "new" | payee obj
  const [err, setErr] = useState(null);

  const reload = async () => {
    setLoading(true); setErr(null);
    try {
      const [py, ac] = await Promise.all([
        treasuryApi.listPayees(), treasuryApi.listAccounts(),
      ]);
      setPayees((py.payees || []).filter((p) => p.active !== false));
      setAccounts(ac.accounts || []);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, []);

  const del = async (id) => {
    if (!window.confirm("Inativar este fornecedor?")) return;
    try { await treasuryApi.deletePayee(id); await reload(); }
    catch (e) { alert("Falhou: " + (e?.response?.data?.detail || e.message)); }
  };

  return (
    <div data-testid="treasury-fornecedores-tab" style={{ padding: 20 }}>
      <ReceiptConfigCard />

      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 14 }}>
        <div>
          <h3 style={{ color: C.text, margin: 0, fontSize: 18,
            display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Users size={18} color={C.accent}/> Fornecedores IA
          </h3>
          <div style={{ color: C.muted, fontSize: 12, marginTop: 4 }}>
            Cadastro completo de fornecedores: endereço, Pix, WhatsApp pra comprovante e conta vinculada.
          </div>
        </div>
        <button data-testid="btn-new-payee" onClick={() => setShowForm("new")}
          style={btnPrimary}><Plus size={14}/> Novo fornecedor</button>
      </div>

      {err && <div style={errBox}>{err}</div>}
      {loading && <div style={{ color: C.muted }}>Carregando...</div>}

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
        gap: 12,
      }}>
        {payees.length === 0 && !loading && (
          <div style={{ gridColumn: "1 / -1", padding: 32, textAlign: "center",
            color: C.muted, background: C.card,
            border: `1px solid ${C.border}`, borderRadius: 12 }}>
            <Users size={28} color={C.muted}/>
            <div style={{ marginTop: 8 }}>Nenhum fornecedor cadastrado.</div>
          </div>
        )}
        {payees.map((p) => (
          <PayeeCard key={p.payee_id} p={p} accounts={accounts}
            onEdit={() => setShowForm(p)} onDelete={() => del(p.payee_id)} />
        ))}
      </div>

      {showForm && <PayeeFormModal
        payee={showForm === "new" ? null : showForm}
        accounts={accounts}
        onClose={() => setShowForm(null)}
        onSaved={() => { setShowForm(null); reload(); }} />}
    </div>
  );
}

function PayeeCard({ p, accounts, onEdit, onDelete }) {
  const addr = p.address || {};
  const account = accounts.find((a) => a.account_id === p.default_account_id);
  return (
    <div data-testid={`payee-card-${p.payee_id}`} style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <div style={{ color: C.text, fontSize: 15, fontWeight: 700 }}>
            {p.name}
          </div>
          <div style={{ color: C.muted, fontSize: 11 }}>{p.document}</div>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          <button data-testid={`btn-edit-payee-${p.payee_id}`}
            onClick={onEdit} style={iconBtn} title="Editar"><Edit2 size={13}/></button>
          <button data-testid={`btn-del-payee-${p.payee_id}`}
            onClick={onDelete} style={{ ...iconBtn, color: C.red }}
            title="Inativar"><Trash2 size={13}/></button>
        </div>
      </div>

      <Row icon={CreditCard} label="Pix"
        value={p.pix_key ? `${p.pix_key_type} · ${p.pix_key}` : "—"}/>
      <Row icon={Phone} label="WhatsApp"
        value={p.whatsapp || "—"}
        tail={p.auto_send_receipt
          ? <ToggleRight size={14} color={C.green} title="Comprovante automático"/>
          : <ToggleLeft size={14} color={C.muted} title="Comprovante manual"/>}/>
      <Row icon={Mail} label="Email" value={p.email || "—"}/>
      <Row icon={MapPin} label="Endereço"
        value={[addr.street && `${addr.street}, ${addr.number || "S/N"}`,
                addr.neighborhood, addr.city && `${addr.city}/${addr.state || ""}`,
                addr.cep].filter(Boolean).join(" · ") || "—"}/>
      <Row icon={CreditCard} label="Conta vinculada"
        value={account ? account.name : "padrão da empresa"}/>

      {p.notes && (
        <div style={{ marginTop: 8, paddingTop: 8,
          borderTop: `1px solid ${C.border}`, fontSize: 11, color: C.muted,
          fontStyle: "italic" }}>
          {p.notes}
        </div>
      )}
    </div>
  );
}

function Row({ icon: Icon, label, value, tail }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 8,
      marginBottom: 5 }}>
      <Icon size={12} color={C.muted} style={{ marginTop: 2, flexShrink: 0 }}/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: C.muted, fontSize: 10, textTransform: "uppercase",
          letterSpacing: 0.4 }}>{label}</div>
        <div style={{ color: C.text, fontSize: 12, wordBreak: "break-word" }}>
          {value}
        </div>
      </div>
      {tail}
    </div>);
}

function PayeeFormModal({ payee, accounts, onClose, onSaved }) {
  const isEdit = !!payee;
  const addr = payee?.address || {};
  const [f, setF] = useState({
    name: payee?.name || "",
    document: payee?.document || "",
    pix_key: payee?.pix_key || "",
    pix_key_type: payee?.pix_key_type || "CPF",
    whatsapp: payee?.whatsapp || "",
    email: payee?.email || "",
    auto_send_receipt: payee?.auto_send_receipt !== false,
    default_account_id: payee?.default_account_id || "",
    cep: addr.cep || "",
    street: addr.street || "",
    number: addr.number || "",
    complement: addr.complement || "",
    neighborhood: addr.neighborhood || "",
    city: addr.city || "",
    state: addr.state || "",
    category: payee?.category || "",
    notes: payee?.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const lookupCep = async () => {
    const cep = (f.cep || "").replace(/\D+/g, "");
    if (cep.length !== 8) return;
    try {
      const r = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
      const d = await r.json();
      if (d.erro) return;
      setF((s) => ({ ...s,
        street: d.logradouro || s.street,
        neighborhood: d.bairro || s.neighborhood,
        city: d.localidade || s.city,
        state: d.uf || s.state,
      }));
    } catch { /* ignore */ }
  };

  const submit = async () => {
    if (!f.name || !f.document || !f.pix_key) {
      setErr("Nome, CPF/CNPJ e chave Pix são obrigatórios."); return;
    }
    setBusy(true); setErr(null);
    const payload = {
      name: f.name, document: f.document,
      pix_key: f.pix_key, pix_key_type: f.pix_key_type,
      whatsapp: f.whatsapp || null, email: f.email || null,
      auto_send_receipt: f.auto_send_receipt,
      default_account_id: f.default_account_id || null,
      category: f.category || null, notes: f.notes || null,
      address: {
        cep: f.cep, street: f.street, number: f.number,
        complement: f.complement, neighborhood: f.neighborhood,
        city: f.city, state: f.state,
      },
    };
    try {
      if (isEdit) await treasuryApi.updatePayee(payee.payee_id, payload);
      else await treasuryApi.createPayee(payload);
      onSaved();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose}
      title={isEdit ? `Editar ${payee.name}` : "Novo fornecedor"}
      testid="modal-payee-form">
      <Section title="Identificação">
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="Nome / Razão Social*">
            <input data-testid="payee-name" value={f.name}
              onChange={(e) => setF({ ...f, name: e.target.value })} style={input}/>
          </Field>
          <Field label="CPF/CNPJ*">
            <input data-testid="payee-document" value={f.document}
              onChange={(e) => setF({ ...f, document: e.target.value })} style={input}/>
          </Field>
        </div>
        <Field label="Categoria">
          <input data-testid="payee-category" value={f.category}
            onChange={(e) => setF({ ...f, category: e.target.value })} style={input}
            placeholder="Energia, Telefonia, Aluguel, Combustível..."/>
        </Field>
      </Section>

      <Section title="Chave Pix">
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="Tipo*">
            <select data-testid="payee-pix-type" value={f.pix_key_type}
              onChange={(e) => setF({ ...f, pix_key_type: e.target.value })} style={input}>
              <option value="CPF">CPF</option>
              <option value="CNPJ">CNPJ</option>
              <option value="EMAIL">Email</option>
              <option value="PHONE">Telefone</option>
              <option value="EVP">EVP (aleatória)</option>
            </select>
          </Field>
          <Field label="Chave Pix*">
            <input data-testid="payee-pix-key" value={f.pix_key}
              onChange={(e) => setF({ ...f, pix_key: e.target.value })} style={input}/>
          </Field>
        </div>
      </Section>

      <Section title="Comunicação (envio de comprovante)">
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="WhatsApp (DDD + número)">
            <input data-testid="payee-whatsapp" value={f.whatsapp}
              onChange={(e) => setF({ ...f, whatsapp: e.target.value })} style={input}
              placeholder="11999999999"/>
          </Field>
          <Field label="Email">
            <input type="email" data-testid="payee-email" value={f.email}
              onChange={(e) => setF({ ...f, email: e.target.value })} style={input}/>
          </Field>
        </div>
        <label style={{ display: "flex", gap: 6, color: C.text, fontSize: 12,
          marginTop: 6, alignItems: "center" }}>
          <input type="checkbox" data-testid="payee-auto-receipt"
            checked={f.auto_send_receipt}
            onChange={(e) => setF({ ...f, auto_send_receipt: e.target.checked })}/>
          Enviar comprovante via WhatsApp automaticamente após o pagamento
        </label>
      </Section>

      <Section title="Endereço">
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="CEP">
            <input data-testid="payee-cep" value={f.cep}
              onChange={(e) => setF({ ...f, cep: e.target.value })}
              onBlur={lookupCep} style={input}
              placeholder="00000-000 (auto-preenche)"/>
          </Field>
          <Field label="Estado (UF)">
            <input data-testid="payee-state" value={f.state}
              onChange={(e) => setF({ ...f, state: e.target.value.toUpperCase().slice(0, 2) })}
              style={input} maxLength={2}/>
          </Field>
        </div>
        <Field label="Rua / Logradouro">
          <input data-testid="payee-street" value={f.street}
            onChange={(e) => setF({ ...f, street: e.target.value })} style={input}/>
        </Field>
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="Número">
            <input data-testid="payee-number" value={f.number}
              onChange={(e) => setF({ ...f, number: e.target.value })} style={input}/>
          </Field>
          <Field label="Complemento">
            <input data-testid="payee-complement" value={f.complement}
              onChange={(e) => setF({ ...f, complement: e.target.value })} style={input}/>
          </Field>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="Bairro">
            <input data-testid="payee-neighborhood" value={f.neighborhood}
              onChange={(e) => setF({ ...f, neighborhood: e.target.value })} style={input}/>
          </Field>
          <Field label="Cidade">
            <input data-testid="payee-city" value={f.city}
              onChange={(e) => setF({ ...f, city: e.target.value })} style={input}/>
          </Field>
        </div>
      </Section>

      <Section title="Conta de pagamento">
        <Field label="Conta padrão para pagar este fornecedor">
          <select data-testid="payee-account" value={f.default_account_id}
            onChange={(e) => setF({ ...f, default_account_id: e.target.value })} style={input}>
            <option value="">Conta padrão da empresa</option>
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.name} {a.is_default ? "(padrão)" : ""}
              </option>
            ))}
          </select>
        </Field>
      </Section>

      <Field label="Observações">
        <textarea data-testid="payee-notes" value={f.notes}
          onChange={(e) => setF({ ...f, notes: e.target.value })}
          style={{ ...input, minHeight: 60, resize: "vertical" }}/>
      </Field>

      {err && <div style={errBox}>{err}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button data-testid="btn-save-payee" onClick={submit} disabled={busy}
          style={{ ...btnPrimary, flex: 1 }}>
          {busy ? "Salvando..." : (isEdit ? "Salvar alterações" : "Cadastrar fornecedor")}
        </button>
        <button onClick={onClose} style={btnGhost}>Cancelar</button>
      </div>
    </Overlay>
  );
}

const Section = ({ title, children }) => (
  <div style={{ marginBottom: 14 }}>
    <div style={{ color: C.accent, fontSize: 10, fontWeight: 700,
      textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 8 }}>
      {title}
    </div>
    {children}
  </div>
);

const Field = ({ label, children }) => (
  <div style={{ marginBottom: 8, flex: 1 }}>
    <div style={{ color: C.muted, fontSize: 11, marginBottom: 3 }}>{label}</div>
    {children}
  </div>);

const input = { padding: "8px 10px", borderRadius: 8,
  border: `1px solid ${C.border}`, background: C.card, color: C.text,
  fontSize: 13, width: "100%" };
const btnPrimary = { background: C.accent, color: "white", border: 0,
  borderRadius: 8, padding: "8px 14px", fontWeight: 700, fontSize: 13,
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 };
const btnGhost = { background: "transparent", color: C.text,
  border: `1px solid ${C.border}`, borderRadius: 8, padding: "6px 12px",
  fontSize: 12, cursor: "pointer" };
const iconBtn = { background: "transparent", color: C.muted,
  border: `1px solid ${C.border}`, borderRadius: 6, padding: 4,
  cursor: "pointer", display: "inline-flex", alignItems: "center" };
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
