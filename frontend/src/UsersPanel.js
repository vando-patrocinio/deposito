import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { useAuth } from "@/AuthContext";
import { Button, Card, Field, Icon, inputStyle } from "@/ui";

// Apenas papéis que ACESSAM o sistema. Colaboradores que batem ponto vão na aba Cadastro.
const ROLES = [
  { value: "gestor", label: "Gestor (Painel, Cadastro, Praças, Espelho)" },
  { value: "auditor", label: "Auditor (acesso total)" },
];

const ROLE_THEME = {
  auditor: { bg: "#fde68a", fg: "#92400e", ring: "#f59e0b", emoji: "🔑" },
  gestor: { bg: "#bbf7d0", fg: "#166534", ring: "#16a34a", emoji: "🧑‍💼" },
  colaborador: { bg: "#e2e8f0", fg: "#475569", ring: "#94a3b8", emoji: "👤" },
};

function initials(name) {
  if (!name) return "?";
  const p = name.trim().split(/\s+/);
  if (p.length === 1) return p[0].slice(0, 2).toUpperCase();
  return (p[0][0] + p[p.length - 1][0]).toUpperCase();
}

const EMPTY = { email: "", password: "", name: "", role: "gestor" };

export default function UsersPanel() {
  const { user: currentUser, impersonate } = useAuth();
  const [users, setUsers] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [pwUserId, setPwUserId] = useState(null);
  const [pwValue, setPwValue] = useState("");
  const [showLog, setShowLog] = useState(false);
  const [logEntries, setLogEntries] = useState([]);
  const [filterRole, setFilterRole] = useState("all");
  const [search, setSearch] = useState("");

  async function reload() {
    try {
      const [u, c] = await Promise.all([api.listUsers(), api.listCollaborators()]);
      setUsers(u);
      setCollabs(c);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  }
  useEffect(() => { reload(); }, []);

  async function loadLog() {
    try {
      const l = await api.impersonationLog(50);
      setLogEntries(l);
      setShowLog(true);
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 4000);
    }
  }

  async function startImpersonation(uid) {
    try {
      await impersonate(uid);
      // após troca de token, App.js redireciona automaticamente baseado no role
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 5000);
    }
  }

  function startNew() { setForm(EMPTY); setEditing("new"); setError(""); }
  function startEdit(u) {
    setForm({ email: u.email, password: "", name: u.name, role: u.role });
    setEditing(u.id); setError("");
  }

  async function save() {
    setError("");
    try {
      if (editing === "new") {
        await api.createUser({
          email: form.email.trim().toLowerCase(),
          password: form.password,
          name: form.name,
          role: form.role,
        });
      } else {
        const payload = {
          name: form.name,
          role: form.role,
          email: form.email.trim().toLowerCase(),
        };
        if (form.password && form.password.length > 0) {
          if (form.password.length < 6) { setError("Nova senha deve ter no mínimo 6 caracteres."); return; }
          payload.password = form.password;
        }
        await api.updateUser(editing, payload);
      }
      await reload();
      setEditing(null);
      setFlash("✅ Usuário salvo.");
      setTimeout(() => setFlash(""), 4000);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  }

  async function remove(uid) {
    if (!window.confirm("Excluir este usuário? A ação não pode ser desfeita.")) return;
    try {
      await api.deleteUser(uid);
      await reload();
      setFlash("✅ Usuário excluído.");
      setTimeout(() => setFlash(""), 2500);
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 4000);
    }
  }

  async function setPassword() {
    if (!pwValue || pwValue.length < 6) { setError("Senha deve ter no mínimo 6 caracteres."); return; }
    try {
      await api.setUserPassword(pwUserId, pwValue);
      setPwUserId(null); setPwValue(""); setError("");
      setFlash("✅ Senha redefinida.");
      setTimeout(() => setFlash(""), 2500);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  }

  const counts = useMemo(() => {
    const c = { all: users.length, colaborador: 0, gestor: 0, auditor: 0 };
    users.forEach((u) => { c[u.role] = (c[u.role] || 0) + 1; });
    return c;
  }, [users]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter((u) => {
      if (filterRole !== "all" && u.role !== filterRole) return false;
      if (!q) return true;
      return (u.name || "").toLowerCase().includes(q) || (u.email || "").toLowerCase().includes(q);
    });
  }, [users, search, filterRole]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: editing !== null ? "1fr 1fr" : "1fr", gap: 18 }}>
      <Card title={`Usuários do sistema (${counts.all})`} action={
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="soft" onClick={loadLog} data-testid="open-imp-log-btn"><Icon name="history" /> Auditoria</Button>
          <Button onClick={startNew} data-testid="new-user-btn"><Icon name="plus" /> Novo</Button>
        </div>
      }>
        {flash && <div data-testid="user-flash" style={{ background: flash.startsWith("✅") ? "#dcfce7" : "#fee2e2", color: flash.startsWith("✅") ? "#166534" : "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10, fontWeight: 700 }}>{flash}</div>}

        {/* Toolbar: busca + filtros por papel */}
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
          <div style={{ flex: 1, minWidth: 220, position: "relative" }}>
            <input
              data-testid="user-search"
              placeholder="Buscar por nome ou e-mail..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ ...inputStyle, paddingLeft: 36 }}
            />
            <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#94a3b8" }}>🔍</span>
          </div>
          <div style={{ display: "flex", gap: 4, background: "#f1f5f9", borderRadius: 12, padding: 4 }}>
            {[
              { v: "all", label: "Todos", n: counts.all },
              { v: "gestor", label: "🧑‍💼", n: counts.gestor || 0 },
              { v: "auditor", label: "🔑", n: counts.auditor || 0 },
            ].map((t) => (
              <button
                key={t.v}
                onClick={() => setFilterRole(t.v)}
                data-testid={`filter-${t.v}`}
                title={t.v === "all" ? "Todos" : t.v}
                style={{
                  background: filterRole === t.v ? "white" : "transparent",
                  color: filterRole === t.v ? "#0f172a" : "#64748b",
                  border: "none", padding: "6px 12px", borderRadius: 8,
                  fontWeight: 800, fontSize: 12, cursor: "pointer",
                  boxShadow: filterRole === t.v ? "0 2px 6px rgba(15,23,42,.08)" : "none",
                }}
              >
                {t.label}
                <span style={{ marginLeft: 6, fontSize: 10, opacity: 0.7 }}>{t.n}</span>
              </button>
            ))}
          </div>
        </div>

        {filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: 32, color: "#64748b", background: "#f8fafc", borderRadius: 14, border: "1px dashed #cbd5e1" }}>
            {users.length === 0 ? "Nenhum usuário cadastrado ainda." : "Nenhum usuário corresponde ao filtro."}
          </div>
        )}

        {filtered.map((u) => {
          const theme = ROLE_THEME[u.role] || ROLE_THEME.colaborador;
          const isMe = currentUser?.id === u.id;
          const linked = u.collaborator_id ? collabs.find((c) => c.id === u.collaborator_id) : null;
          return (
            <div
              key={u.id}
              data-testid={`user-row-${u.id}`}
              style={{
                background: "white",
                border: `1px solid ${isMe ? theme.ring : "#e2e8f0"}`,
                borderRadius: 16,
                padding: 14,
                marginBottom: 10,
                boxShadow: "0 2px 6px rgba(15,23,42,.04)",
              }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                {/* Avatar com iniciais */}
                <div style={{
                  width: 44, height: 44, borderRadius: "50%",
                  background: theme.bg, color: theme.fg,
                  display: "grid", placeItems: "center",
                  fontWeight: 900, fontSize: 14,
                  border: `2px solid ${theme.ring}`, flexShrink: 0,
                }}>
                  {initials(u.name)}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 15 }}>{u.name}</strong>
                    <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: theme.bg, color: theme.fg }}>
                      {theme.emoji} {u.role}
                    </span>
                    {isMe && (
                      <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#0f172a", color: "white" }}>você</span>
                    )}
                    {!u.active && (
                      <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#fee2e2", color: "#991b1b" }}>inativo</span>
                    )}
                  </div>
                  <div style={{ color: "#64748b", fontSize: 12, marginTop: 2 }}>{u.email}</div>
                  {linked && (
                    <div style={{ color: "#7c3aed", fontSize: 11, marginTop: 4 }}>
                      🔗 vinculado a {linked.name} ({linked.cpf})
                    </div>
                  )}
                </div>
              </div>

              {/* Ações na linha de baixo */}
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #f1f5f9", display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {currentUser?.role === "auditor" && !isMe && (
                  <Button
                    variant="soft"
                    onClick={() => startImpersonation(u.id)}
                    data-testid={`impersonate-${u.id}`}
                    title="Logar temporariamente como este usuário (auditoria)"
                  >
                    🎭 Logar como
                  </Button>
                )}
                <Button variant="soft" onClick={() => { setPwUserId(u.id); setPwValue(""); }} data-testid={`pw-${u.id}`}>
                  <Icon name="shield" /> Senha
                </Button>
                <Button variant="secondary" onClick={() => startEdit(u)} data-testid={`edit-user-${u.id}`}>
                  <Icon name="gear" /> Editar
                </Button>
                {!isMe && (
                  <Button variant="danger" onClick={() => remove(u.id)} data-testid={`del-user-${u.id}`} title="Excluir usuário">
                    <Icon name="trash" />
                  </Button>
                )}
              </div>

              {pwUserId === u.id && (
                <div style={{ marginTop: 12, padding: 12, background: "#f8fafc", borderRadius: 12, border: "1px dashed #cbd5e1", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                  <input
                    type="password" autoComplete="new-password"
                    placeholder="Nova senha (mínimo 6 caracteres)"
                    value={pwValue}
                    onChange={(e) => setPwValue(e.target.value)}
                    style={{ ...inputStyle, flex: 1, minWidth: 180 }}
                    data-testid={`pw-input-${u.id}`}
                  />
                  <Button onClick={setPassword} data-testid={`pw-save-${u.id}`}>Salvar</Button>
                  <Button variant="secondary" onClick={() => { setPwUserId(null); setPwValue(""); }}>Cancelar</Button>
                </div>
              )}
            </div>
          );
        })}
      </Card>

      {editing !== null && (
        <Card title={editing === "new" ? "Novo usuário" : "Editar usuário"}>
          {error && <div data-testid="user-form-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>{String(error)}</div>}
          <Field label="Nome">
            <input data-testid="u-name" style={inputStyle} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="E-mail (login)">
            <input data-testid="u-email" type="email" style={inputStyle} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label={editing === "new" ? "Senha (mínimo 6)" : "Nova senha (deixe em branco para manter)"}>
            <input
              data-testid="u-password" type="password" autoComplete="new-password"
              style={inputStyle} value={form.password}
              placeholder={editing === "new" ? "" : "••••••••"}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
          </Field>
          <Field label="Papel">
            <select data-testid="u-role" style={inputStyle} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </Field>
          <p style={{ color: "#64748b", fontSize: 12, margin: "4px 0 12px" }}>
            ℹ️ Esta tela é apenas para usuários que <strong>acessam o sistema</strong> (gestores e auditores).
            Colaboradores que batem ponto são cadastrados na aba <strong>Cadastro</strong>.
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <Button onClick={save} data-testid="save-user-btn">Salvar</Button>
            <Button variant="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
          </div>
        </Card>
      )}

      {showLog && (
        <div role="dialog" data-testid="imp-log-modal" onClick={(e) => { if (e.target === e.currentTarget) setShowLog(false); }} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, gridColumn: "1 / -1" }}>
          <div style={{ background: "white", borderRadius: 22, width: "100%", maxWidth: 720, maxHeight: "85vh", display: "flex", flexDirection: "column", boxShadow: "0 24px 60px rgba(15,23,42,.32)" }}>
            <div style={{ padding: "18px 22px 8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>🎭 Auditoria de impersonation</h3>
              <button onClick={() => setShowLog(false)} style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
            </div>
            <div style={{ overflowY: "auto", padding: "0 22px 22px" }}>
              {logEntries.length === 0 ? (
                <p style={{ color: "#64748b" }}>Nenhuma sessão de impersonation registrada.</p>
              ) : (
                logEntries.map((l, i) => (
                  <div key={i} data-testid={`imp-log-${i}`} style={{ borderBottom: "1px solid #f1f5f9", padding: "10px 0" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                      <strong style={{ fontSize: 13 }}>
                        {l.action === "start" ? "Início → " : "Fim ← "}
                        <span style={{ color: "#7c3aed" }}>{l.target_email}</span> ({l.target_role})
                      </strong>
                      <span style={{ fontSize: 11, color: "#94a3b8" }}>{new Date(l.at).toLocaleString("pt-BR")}</span>
                    </div>
                    <div style={{ fontSize: 12, color: "#64748b" }}>Auditor: {l.auditor_email}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
