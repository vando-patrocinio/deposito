/**
 * IsabellaPjConsultoresCard.jsx — Configuração de Consultores PJ (V16.1)
 *
 * Permite ao gestor cadastrar N consultores que receberão leads PJ via
 * WhatsApp. A Isabella distribui em round-robin entre os consultores
 * ATIVOS (ordenando por `last_notified_at` ASC).
 *
 * Regra de Ouro PJ: Isabella NUNCA pede selfie/foto de CNPJ — apenas
 * qualifica o lead e aciona o consultor humano.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Briefcase, Plus, Pencil, Trash2, Save, X, UserCheck, UserX, Phone, Mail, Clock,
} from "lucide-react";
import { api } from "@/api";

const BLANK_FORM = {
  nome: "", whatsapp: "", email: "", sla_minutos: 15, ativo: true,
};

function formatPhonePretty(raw) {
  const d = String(raw || "").replace(/\D/g, "");
  if (d.length === 13 && d.startsWith("55")) {
    return `+55 (${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`;
  }
  if (d.length === 11) {
    return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  }
  if (d.length === 10) {
    return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  }
  return raw || "";
}

function formatRelative(iso) {
  if (!iso) return "nunca";
  try {
    const d = new Date(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return "agora";
    if (diff < 3600) return `há ${Math.floor(diff / 60)}min`;
    if (diff < 86400) return `há ${Math.floor(diff / 3600)}h`;
    return `há ${Math.floor(diff / 86400)}d`;
  } catch (e) {
    return iso;
  }
}

export default function IsabellaPjConsultoresCard() {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const [editingId, setEditingId] = useState(null); // null = nenhum; "__new" = criando
  const [form, setForm] = useState(BLANK_FORM);

  const load = async () => {
    try {
      const r = await api.isabellaPjConsultoresList();
      setItems(r.items || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };

  useEffect(() => { load(); }, []);

  const activeCount = useMemo(
    () => (items || []).filter((x) => x.ativo).length,
    [items],
  );

  const startCreate = () => {
    setForm(BLANK_FORM);
    setEditingId("__new");
    setErr(null); setMsg(null);
  };

  const startEdit = (c) => {
    setForm({
      nome: c.nome || "",
      whatsapp: c.whatsapp || "",
      email: c.email || "",
      sla_minutos: c.sla_minutos ?? 15,
      ativo: !!c.ativo,
    });
    setEditingId(c.id);
    setErr(null); setMsg(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(BLANK_FORM);
  };

  const save = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const payload = { ...form };
      if (editingId === "__new") {
        await api.isabellaPjConsultorCreate(payload);
        setMsg("Consultor adicionado.");
      } else {
        await api.isabellaPjConsultorUpdate(editingId, payload);
        setMsg("Consultor atualizado.");
      }
      cancelEdit();
      await load();
      setTimeout(() => setMsg(null), 3500);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (c) => {
    if (!window.confirm(`Remover consultor "${c.nome}"?`)) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      await api.isabellaPjConsultorDelete(c.id);
      setMsg("Consultor removido.");
      await load();
      setTimeout(() => setMsg(null), 3500);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  if (items === null) {
    return (
      <div data-testid="pj-consultores-loading" className="card"
        style={{ padding: 16, gridColumn: "1 / -1" }}>
        <Briefcase size={16} /> Carregando consultores PJ…
      </div>
    );
  }

  return (
    <div data-testid="pj-consultores-card" className="card"
      style={{ padding: 16, gridColumn: "1 / -1" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
        marginBottom: 6, flexWrap: "wrap" }}>
        <Briefcase size={18} style={{ color: "#0d9488" }} />
        <div>
          <h3 style={{ margin: 0, fontSize: 16 }}>
            Consultores PJ · Isabella V16
          </h3>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            A Isabella encaminha leads de empresas em <strong>round-robin</strong>
            entre os consultores ativos. Ela nunca pede selfie ou foto de CNPJ.
          </div>
        </div>
        <span data-testid="pj-consultores-badge" style={{
          marginLeft: "auto", fontSize: 11, fontWeight: 700,
          padding: "4px 10px", borderRadius: 999,
          background: activeCount > 0 ? "#dcfce7" : "#fee2e2",
          color: activeCount > 0 ? "#166534" : "#991b1b",
          display: "inline-flex", alignItems: "center", gap: 4,
        }}>
          {activeCount > 0
            ? <><UserCheck size={12} /> {activeCount} ativo(s)</>
            : <><UserX size={12} /> NENHUM ATIVO</>}
        </span>
      </div>

      {/* Lista de consultores */}
      <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
        {items.length === 0 && editingId !== "__new" && (
          <div data-testid="pj-consultores-empty" style={{
            padding: 16, background: "#fafafa", border: "1px dashed #cbd5e1",
            borderRadius: 10, fontSize: 13, color: "#64748b",
            textAlign: "center",
          }}>
            Nenhum consultor PJ cadastrado. A Isabella seguirá o fluxo normal
            quando detectar uma empresa.
          </div>
        )}

        {items.map((c) => (
          <div key={c.id} data-testid={`pj-consultor-row-${c.id}`}
            style={{
              border: `1px solid ${c.ativo ? "#10b981" : "#e2e8f0"}`,
              background: c.ativo ? "#f0fdfa" : "#fafafa",
              borderRadius: 10, padding: 12,
              display: editingId === c.id ? "none" : "grid",
              gridTemplateColumns: "1fr auto",
              gap: 10, alignItems: "center",
            }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8,
                flexWrap: "wrap" }}>
                <strong style={{ fontSize: 14, color: "#0f172a" }}>
                  {c.nome}
                </strong>
                <span style={{
                  fontSize: 10, fontWeight: 700, padding: "2px 8px",
                  borderRadius: 999,
                  background: c.ativo ? "#10b981" : "#94a3b8",
                  color: "white", letterSpacing: 0.3,
                }}>
                  {c.ativo ? "ATIVO" : "INATIVO"}
                </span>
                <span style={{ fontSize: 11, color: "#64748b" }}>
                  <Clock size={10} style={{ verticalAlign: "middle" }} /> SLA {c.sla_minutos}min
                </span>
              </div>
              <div style={{ display: "flex", gap: 14, marginTop: 6,
                flexWrap: "wrap", fontSize: 12, color: "#475569" }}>
                <span><Phone size={11} style={{ verticalAlign: "middle" }} /> {formatPhonePretty(c.whatsapp)}</span>
                {c.email && (
                  <span><Mail size={11} style={{ verticalAlign: "middle" }} /> {c.email}</span>
                )}
                <span style={{ color: "#94a3b8" }}>
                  Último lead: {formatRelative(c.last_notified_at)}
                  {c.notify_count > 0 && ` · ${c.notify_count} total`}
                </span>
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button data-testid={`pj-consultor-edit-${c.id}`}
                onClick={() => startEdit(c)}
                style={{
                  padding: "6px 10px", border: "1px solid #cbd5e1",
                  background: "white", borderRadius: 8, cursor: "pointer",
                  display: "inline-flex", alignItems: "center", gap: 4,
                  fontSize: 12,
                }}>
                <Pencil size={12} /> Editar
              </button>
              <button data-testid={`pj-consultor-delete-${c.id}`}
                onClick={() => remove(c)}
                disabled={busy}
                style={{
                  padding: "6px 10px", border: "1px solid #fecaca",
                  background: "#fef2f2", color: "#b91c1c",
                  borderRadius: 8, cursor: busy ? "wait" : "pointer",
                  display: "inline-flex", alignItems: "center", gap: 4,
                  fontSize: 12,
                }}>
                <Trash2 size={12} /> Remover
              </button>
            </div>
          </div>
        ))}

        {/* Formulário de edição/criação inline */}
        {editingId !== null && (
          <ConsultorForm
            form={form}
            setForm={setForm}
            onSave={save}
            onCancel={cancelEdit}
            busy={busy}
            isNew={editingId === "__new"}
          />
        )}
      </div>

      {/* Ações */}
      {editingId === null && (
        <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end" }}>
          <button data-testid="pj-consultor-add-btn"
            onClick={startCreate}
            style={{
              padding: "8px 14px", background: "#0d9488", color: "white",
              border: "none", borderRadius: 8, fontWeight: 700, fontSize: 13,
              cursor: "pointer", display: "inline-flex",
              alignItems: "center", gap: 6,
            }}>
            <Plus size={14} /> Adicionar consultor
          </button>
        </div>
      )}

      {err && (
        <div data-testid="pj-consultor-err" style={{
          background: "#fee2e2", color: "#991b1b", padding: 10,
          borderRadius: 8, marginTop: 12, fontSize: 12,
        }}>{err}</div>
      )}
      {msg && (
        <div data-testid="pj-consultor-msg" style={{
          background: "#dcfce7", color: "#166534", padding: 10,
          borderRadius: 8, marginTop: 12, fontSize: 12,
        }}>{msg}</div>
      )}
    </div>
  );
}

function ConsultorForm({ form, setForm, onSave, onCancel, busy, isNew }) {
  const update = (k, v) => setForm((s) => ({ ...s, [k]: v }));
  return (
    <div data-testid="pj-consultor-form" style={{
      border: "2px solid #0d9488", borderRadius: 10, padding: 14,
      background: "#f0fdfa",
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#0f766e",
        marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
        {isNew ? <Plus size={14} /> : <Pencil size={14} />}
        {isNew ? "Novo consultor PJ" : "Editar consultor"}
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: 10,
      }}>
        <FormField label="Nome*" testid="pj-form-nome">
          <input
            data-testid="pj-form-nome-input"
            type="text"
            placeholder="João Silva"
            value={form.nome}
            onChange={(e) => update("nome", e.target.value)}
            style={fieldStyle}
            maxLength={120}
          />
        </FormField>
        <FormField label="WhatsApp* (com DDI+DDD)" testid="pj-form-whatsapp">
          <input
            data-testid="pj-form-whatsapp-input"
            type="text"
            placeholder="5511987654321"
            value={form.whatsapp}
            onChange={(e) => update("whatsapp", e.target.value)}
            style={fieldStyle}
          />
        </FormField>
        <FormField label="E-mail (opcional)" testid="pj-form-email">
          <input
            data-testid="pj-form-email-input"
            type="email"
            placeholder="consultor@empresa.com"
            value={form.email}
            onChange={(e) => update("email", e.target.value)}
            style={fieldStyle}
          />
        </FormField>
        <FormField label="SLA (min, 1-240)" testid="pj-form-sla">
          <input
            data-testid="pj-form-sla-input"
            type="number"
            min={1}
            max={240}
            value={form.sla_minutos}
            onChange={(e) => update("sla_minutos", Number(e.target.value))}
            style={fieldStyle}
          />
        </FormField>
      </div>

      <label style={{ display: "inline-flex", alignItems: "center", gap: 8,
        marginTop: 12, cursor: "pointer" }}>
        <input
          data-testid="pj-form-ativo-input"
          type="checkbox"
          checked={!!form.ativo}
          onChange={(e) => update("ativo", e.target.checked)}
          style={{ width: 18, height: 18, cursor: "pointer" }}
        />
        <span style={{ fontSize: 13, color: "#0f172a", fontWeight: 600 }}>
          Ativo (recebe leads PJ via round-robin)
        </span>
      </label>

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
        marginTop: 14 }}>
        <button data-testid="pj-form-cancel-btn"
          onClick={onCancel} disabled={busy}
          style={{
            padding: "8px 14px", background: "white", color: "#475569",
            border: "1px solid #cbd5e1", borderRadius: 8, fontSize: 13,
            cursor: busy ? "wait" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
          <X size={13} /> Cancelar
        </button>
        <button data-testid="pj-form-save-btn"
          onClick={onSave} disabled={busy}
          style={{
            padding: "8px 14px", background: "#0d9488", color: "white",
            border: "none", borderRadius: 8, fontSize: 13, fontWeight: 700,
            cursor: busy ? "wait" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
          <Save size={13} /> {busy ? "Salvando…" : "Salvar"}
        </button>
      </div>
    </div>
  );
}

function FormField({ label, testid, children }) {
  return (
    <div data-testid={testid}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
        marginBottom: 4 }}>
        {label}
      </div>
      {children}
    </div>
  );
}

const fieldStyle = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #cbd5e1", borderRadius: 8,
  background: "white",
};
