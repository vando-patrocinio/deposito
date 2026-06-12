import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { useAuth } from "@/AuthContext";
import { Button, Card, Field, Icon, inputStyle } from "@/ui";
import AccessTagsPicker from "@/AccessTagsPicker";

// Apenas papéis que ACESSAM o sistema. Colaboradores que batem ponto vão na aba Cadastro.
const ROLES = [
  { value: "gestor", label: "Gestor (Painel, Cadastro, Praças, Espelho)" },
  { value: "auditor", label: "Auditor (acesso total)" },
];

const ROLE_THEME = {
  auditor: { bg: "#fde68a", fg: "#92400e", ring: "#f59e0b", emoji: "" },
  gestor: { bg: "#bbf7d0", fg: "#166534", ring: "#16a34a", emoji: "‍" },
  colaborador: { bg: "#e2e8f0", fg: "#475569", ring: "#94a3b8", emoji: "" },
};

function initials(name) {
  if (!name) return "?";
  const p = name.trim().split(/\s+/);
  if (p.length === 1) return p[0].slice(0, 2).toUpperCase();
  return (p[0][0] + p[p.length - 1][0]).toUpperCase();
}

const EMPTY = { email: "", password: "", name: "", role: "gestor", can_attend_whatsapp: false, access_tags: null, collaborator_id: "" };

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
  // Magic link modal state
  const [mlUser, setMlUser] = useState(null);     // user-alvo do modal
  const [mlData, setMlData] = useState(null);     // {active, reserve}
  const [mlLoading, setMlLoading] = useState(false);
  const [mlCopied, setMlCopied] = useState("");
  const [mlExpiresIn, setMlExpiresIn] = useState(0);
  const [mlPhone, setMlPhone] = useState("");
  async function openMagicLink(u) {
    setMlUser(u);
    setMlData(null);
    setMlLoading(true);
    setMlPhone("");
    setMlExpiresIn(0);
    try {
      const d = await api.getUserMagicLink(u.id);
      setMlData(d);
      // Pré-preenche telefone do colaborador vinculado, se houver
      if (u.collaborator_id) {
        const c = collabs.find((x) => x.id === u.collaborator_id);
        if (c?.phone) setMlPhone(c.phone);
      }
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
    } finally {
      setMlLoading(false);
    }
  }
  async function rotateMagicLink() {
    if (!mlUser) return;
    if (!await window.confirm("Renovar o link?\n\nO link ATIVO será revogado IMEDIATAMENTE. O link RESERVA assumirá o lugar e um novo reserva será gerado. Quem ainda usar o link antigo verá 'Link expirado'.")) return;
    setMlLoading(true);
    try {
      const body = { reason: "rotação manual via painel" };
      if (mlExpiresIn > 0) body.expires_in_days = mlExpiresIn;
      const d = await api.rotateUserMagicLink(mlUser.id, body);
      setMlData({ active: d.active, reserve: d.reserve, user_id: mlUser.id, user_email: mlUser.email, user_name: mlUser.name });
      setFlash("✅ Link renovado." + (mlExpiresIn > 0 ? ` Expira em ${mlExpiresIn} dias.` : ""));
      setTimeout(() => setFlash(""), 5000);
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
    } finally {
      setMlLoading(false);
    }
  }
  async function sendMagicLink() {
    if (!mlUser) return;
    setMlLoading(true);
    try {
      const r = await api.sendUserMagicLink(mlUser.id, { phone: mlPhone || null, channel: "whatsapp" });
      setFlash(`✅ Enviado por WhatsApp para ${r.phone}.`);
      setTimeout(() => setFlash(""), 5000);
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
    } finally {
      setMlLoading(false);
    }
  }
  function magicUrl(token) {
    if (!token) return "";
    // Magic URL roteia via index — backend permite endpoint público; o front
    // detecta ?ml=<token> no boot e chama /api/auth/magic-login, salvando JWT.
    const origin = (typeof window !== "undefined" && window.location?.origin) || "";
    return `${origin}/?ml=${token}`;
  }
  async function copyToClipboard(label, val) {
    try {
      await navigator.clipboard.writeText(val);
      setMlCopied(label);
      setTimeout(() => setMlCopied(""), 1800);
    } catch {
      setFlash("Não foi possível copiar. Selecione e copie manualmente.");
    }
  }
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

  // Só o "grantor" (Vando) opera o tik de super admin. Backend valida.
  const canGrantSuperAdmin = !!currentUser?.can_grant_super_admin;

  async function toggleSuperAdmin(u) {
    const wanted = !u.is_super_admin;
    if (!window.confirm(
      wanted
        ? `Tornar ${u.name} (${u.email}) SUPER ADMIN? Ele(a) terá acesso à aba Financeiro e visão cross-tenant.`
        : `Revogar SUPER ADMIN de ${u.name} (${u.email})?`,
    )) return;
    try {
      await api.toggleSuperAdmin(u.id, wanted);
      setFlash(wanted ? `✅ Super admin concedido a ${u.name}` : `↩️ Super admin revogado de ${u.name}`);
      setTimeout(() => setFlash(""), 4000);
      await reload();
    } catch (e) {
      setFlash("❌ " + (e?.response?.data?.detail || e.message));
      setTimeout(() => setFlash(""), 5000);
    }
  }

  function startNew() { setForm(EMPTY); setEditing("new"); setError(""); }
  function startEdit(u) {
    setForm({
      email: u.email, password: "", name: u.name, role: u.role,
      can_attend_whatsapp: u.can_attend_whatsapp ?? false,
      access_tags: Array.isArray(u.access_tags) ? u.access_tags : null,
      collaborator_id: u.collaborator_id || "",
    });
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
          can_attend_whatsapp: !!form.can_attend_whatsapp,
          collaborator_id: form.collaborator_id || null,
          ...(Array.isArray(form.access_tags) ? { access_tags: form.access_tags } : {}),
        });
      } else {
        const payload = {
          name: form.name,
          role: form.role,
          email: form.email.trim().toLowerCase(),
          can_attend_whatsapp: !!form.can_attend_whatsapp,
          collaborator_id: form.collaborator_id || null,
        };
        if (Array.isArray(form.access_tags)) {
          payload.access_tags = form.access_tags;
        }
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
    if (!await window.confirm("Excluir este usuário? A ação não pode ser desfeita.")) return;
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
            <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#94a3b8" }}></span>
          </div>
          <div style={{ display: "flex", gap: 4, background: "#f1f5f9", borderRadius: 12, padding: 4 }}>
            {[
              { v: "all", label: "Todos", n: counts.all },
              { v: "gestor", label: "‍", n: counts.gestor || 0 },
              { v: "auditor", label: "", n: counts.auditor || 0 },
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
                    {u.is_super_admin && (
                      <span data-testid={`super-admin-badge-${u.id}`}
                            style={{ fontSize: 10, fontWeight: 800,
                                      padding: "2px 8px", borderRadius: 999,
                                      background: "#0f172a", color: "#facc15",
                                      letterSpacing: ".04em" }}>
                        ⭐ SUPER ADMIN
                      </span>
                    )}
                    {isMe && (
                      <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#0f172a", color: "white" }}>você</span>
                    )}
                    {!u.active && (
                      <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#fee2e2", color: "#991b1b" }}>inativo</span>
                    )}
                  </div>
                  <div style={{ color: "#64748b", fontSize: 12, marginTop: 2 }}>{u.email}</div>
                  {linked && (
                    <div style={{ color: "#0d9488", fontSize: 11, marginTop: 4,
                                    display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      {linked.code && (
                        <code
                          data-testid={`u-code-${u.id}`}
                          style={{
                            background: "#0d9488", color: "#fff",
                            padding: "1px 6px", borderRadius: 4,
                            fontFamily: "ui-monospace, monospace",
                            fontWeight: 700, fontSize: 10,
                          }}
                        >{linked.code}</code>
                      )}
                      <span>vinculado a {linked.name} ({linked.cpf})</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Ações na linha de baixo */}
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #f1f5f9", display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center" }}>
                {canGrantSuperAdmin && (
                  <label
                    data-testid={`super-admin-toggle-${u.id}`}
                    title={u.is_super_admin
                      ? "Clique para REVOGAR poderes de Super Admin"
                      : "Clique para CONCEDER poderes de Super Admin (aba Financeiro + cross-tenant)"}
                    style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "6px 10px",
                      background: u.is_super_admin ? "#0f172a" : "#f1f5f9",
                      color: u.is_super_admin ? "#facc15" : "#475569",
                      border: `1px solid ${u.is_super_admin
                        ? "#facc15" : "#cbd5e1"}`,
                      borderRadius: 999, cursor: "pointer",
                      fontSize: 11, fontWeight: 700,
                      marginRight: "auto",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={!!u.is_super_admin}
                      onChange={() => toggleSuperAdmin(u)}
                      style={{ accentColor: "#facc15", cursor: "pointer" }}
                    />
                    ⭐ Super Admin
                  </label>
                )}
                {currentUser?.role === "auditor" && !isMe && (
                  <Button
                    variant="soft"
                    onClick={() => startImpersonation(u.id)}
                    data-testid={`impersonate-${u.id}`}
                    title="Logar temporariamente como este usuário (auditoria)"
                  >
                    Logar como
                  </Button>
                )}
                <Button variant="soft" onClick={() => { setPwUserId(u.id); setPwValue(""); }} data-testid={`pw-${u.id}`}>
                  <Icon name="shield" /> Senha
                </Button>
                <Button variant="soft" onClick={() => openMagicLink(u)} data-testid={`magic-link-${u.id}`} title="Link de acesso direto + reserva">
                  🔗 Link
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

          <Field label="Vincular a colaborador (cadastro)">
            <select
              data-testid="u-collaborator-id"
              style={inputStyle}
              value={form.collaborator_id || ""}
              onChange={(e) => setForm({ ...form, collaborator_id: e.target.value })}
            >
              <option value="">— Sem vínculo —</option>
              {collabs.map((c) => {
                // Marca quem já está vinculado a outro user (não bloqueia, só sinaliza)
                const other = users.find((uu) => uu.collaborator_id === c.id && uu.id !== editing);
                const suffix = other ? ` ⚠ já vinculado a ${other.email}` : "";
                const codePrefix = c.code ? `[${c.code}] ` : "";
                return (
                  <option key={c.id} value={c.id} disabled={!!other}>
                    {codePrefix}{c.name} · {c.role || c.cargo || "—"}{suffix}
                  </option>
                );
              })}
            </select>
            {/* CTO 12/06/2026 — exibe o code LIGO-NNNN do colaborador vinculado */}
            {form.collaborator_id && (() => {
              const linked = collabs.find((c) => c.id === form.collaborator_id);
              if (!linked) return null;
              return (
                <div
                  data-testid="u-collaborator-code-badge"
                  style={{
                    marginTop: 8, padding: "6px 12px",
                    background: "#f0fdf4", border: "1px solid #bbf7d0",
                    borderRadius: 6, fontSize: 12, color: "#166534",
                    display: "inline-flex", alignItems: "center", gap: 8,
                  }}
                >
                  <strong>Código:</strong>
                  <code style={{ fontFamily: "ui-monospace, monospace",
                                   fontWeight: 700 }}>
                    {linked.code || "—"}
                  </code>
                  {!linked.code && (
                    <span style={{ fontSize: 11, color: "#92400e" }}>
                      (sem código — rode Auditoria)
                    </span>
                  )}
                </div>
              );
            })()}
            <p style={{ fontSize: 11, color: "#64748b", margin: "4px 0 0" }}>
              Cada usuário aceita 1 cadastro de colaborador. Apenas
              colaboradores cadastrados podem virar usuários do sistema.
            </p>
          </Field>

          <Field label="Tags de acesso (módulos liberados)">
            <AccessTagsPicker
              role={form.role}
              selected={form.access_tags}
              onChange={(tags) => setForm({ ...form, access_tags: tags })}
            />
          </Field>
          <p style={{ color: "#64748b", fontSize: 12, margin: "4px 0 12px",
                       background: "#eff6ff", padding: 10, borderRadius: 8,
                       border: "1px solid #bfdbfe" }}>
            ℹ️ Esta tela é apenas para usuários que <strong>acessam o sistema</strong> (gestores e auditores).
            Colaboradores que batem ponto são cadastrados na aba <strong>Cadastro</strong>.
            <br/>
            <span style={{ fontSize: 11.5 }}>
              Para liberar acesso ao <strong>Atendimento WhatsApp</strong> de um colaborador,
              vá em <strong>Cadastro → Colaboradores</strong>. Apenas <strong>auditor</strong>
              pode liberar esse acesso.
            </span>
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <Button onClick={save} data-testid="save-user-btn">Salvar</Button>
            <Button variant="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
          </div>
        </Card>
      )}

      {/* Magic Link modal */}
      {mlUser && (
        <div
          role="dialog"
          data-testid="magic-link-modal"
          onClick={(e) => { if (e.target === e.currentTarget) setMlUser(null); }}
          style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
        >
          <div style={{ background: "white", borderRadius: 22, width: "100%", maxWidth: 640, boxShadow: "0 24px 60px rgba(15,23,42,.32)" }}>
            <div style={{ padding: "18px 22px 8px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #f1f5f9" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 17 }}>🔗 Links de acesso</h3>
                <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 12.5 }}>
                  <strong>{mlUser.name}</strong> · {mlUser.email}
                </p>
              </div>
              <button onClick={() => setMlUser(null)} style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
            </div>
            <div style={{ padding: 18 }}>
              {mlLoading && <p style={{ color: "#64748b" }}>Carregando…</p>}
              {!mlLoading && mlData && (
                <>
                  <div style={{ background: "#ecfdf5", border: "1px solid #6ee7b7", borderRadius: 14, padding: 14, marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                      <strong style={{ color: "#065f46", fontSize: 13 }}>🟢 LINK ATIVO</strong>
                      <span style={{ fontSize: 11, color: "#047857" }}>geração {mlData.active?.generation}</span>
                    </div>
                    <input
                      readOnly
                      value={magicUrl(mlData.active?.token)}
                      data-testid="ml-active-url"
                      style={{ ...inputStyle, fontSize: 12, fontFamily: "monospace", background: "white", marginBottom: 6 }}
                      onClick={(e) => e.target.select()}
                    />
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="soft" onClick={() => copyToClipboard("active", magicUrl(mlData.active?.token))} data-testid="ml-copy-active">
                        {mlCopied === "active" ? "✓ Copiado" : "📋 Copiar"}
                      </Button>
                    </div>
                  </div>
                  <div style={{ background: "#fef3c7", border: "1px solid #fcd34d", borderRadius: 14, padding: 14, marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                      <strong style={{ color: "#92400e", fontSize: 13 }}>🟡 RESERVA (armada para próxima troca)</strong>
                      <span style={{ fontSize: 11, color: "#b45309" }}>geração {mlData.reserve?.generation}</span>
                    </div>
                    <input
                      readOnly
                      value={magicUrl(mlData.reserve?.token)}
                      data-testid="ml-reserve-url"
                      style={{ ...inputStyle, fontSize: 12, fontFamily: "monospace", background: "white", marginBottom: 6 }}
                      onClick={(e) => e.target.select()}
                    />
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="soft" onClick={() => copyToClipboard("reserve", magicUrl(mlData.reserve?.token))} data-testid="ml-copy-reserve">
                        {mlCopied === "reserve" ? "✓ Copiado" : "📋 Copiar"}
                      </Button>
                    </div>
                  </div>
                  <div style={{ background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: 12, padding: 12, marginBottom: 12 }}>
                    <p style={{ margin: 0, fontSize: 12, color: "#475569" }}>
                      Ao <strong>Renovar</strong>: o ATIVO atual morre, o RESERVA vira ATIVO e um novo RESERVA é gerado.
                      Quem ainda usar o antigo verá &quot;Link expirado&quot;.
                    </p>
                  </div>
                  {/* Expiração + envio via WhatsApp */}
                  <div style={{ background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 14, padding: 14, marginBottom: 12 }}>
                    <strong style={{ color: "#1e40af", fontSize: 13, display: "block", marginBottom: 8 }}>⏱ Expiração no próximo Renovar</strong>
                    <select
                      data-testid="ml-expires-select"
                      style={{ ...inputStyle, marginBottom: 10 }}
                      value={mlExpiresIn}
                      onChange={(e) => setMlExpiresIn(Number(e.target.value))}
                    >
                      <option value={0}>Sem expiração (até o próximo renovar)</option>
                      <option value={7}>Expirar em 7 dias</option>
                      <option value={30}>Expirar em 30 dias</option>
                      <option value={90}>Expirar em 90 dias</option>
                    </select>
                    {mlData?.active?.expires_at && (
                      <p style={{ margin: "0 0 8px", fontSize: 12, color: "#1e40af" }}>
                        Link atual expira em: <strong>{new Date(mlData.active.expires_at).toLocaleString("pt-BR")}</strong>
                      </p>
                    )}
                    <strong style={{ color: "#1e40af", fontSize: 13, display: "block", marginBottom: 6 }}>📱 Enviar por WhatsApp</strong>
                    <input
                      data-testid="ml-phone-input"
                      placeholder="ex: 5511999998888 (com DDD/DDI)"
                      style={{ ...inputStyle, marginBottom: 8 }}
                      value={mlPhone}
                      onChange={(e) => setMlPhone(e.target.value)}
                    />
                    <Button
                      variant="soft"
                      onClick={sendMagicLink}
                      disabled={mlLoading}
                      data-testid="ml-send-whatsapp-btn"
                    >
                      📤 Enviar link ativo via WhatsApp
                    </Button>
                  </div>
                </>
              )}
              <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", borderTop: "1px solid #f1f5f9", paddingTop: 12 }}>
                <Button variant="secondary" onClick={() => setMlUser(null)}>Fechar</Button>
                <Button onClick={rotateMagicLink} data-testid="ml-rotate-btn" disabled={mlLoading}>
                  ↻ Renovar link
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showLog && (
        <div role="dialog" data-testid="imp-log-modal" onClick={(e) => { if (e.target === e.currentTarget) setShowLog(false); }} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, gridColumn: "1 / -1" }}>
          <div style={{ background: "white", borderRadius: 22, width: "100%", maxWidth: 720, maxHeight: "85vh", display: "flex", flexDirection: "column", boxShadow: "0 24px 60px rgba(15,23,42,.32)" }}>
            <div style={{ padding: "18px 22px 8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Auditoria de impersonation</h3>
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
                        <span style={{ color: "#0d9488" }}>{l.target_email}</span> ({l.target_role})
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
