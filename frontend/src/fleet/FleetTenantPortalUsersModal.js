/* FleetTenantPortalUsersModal.js — Gerencia usuários do portal de
 * um cliente (fleet_tenant). Acessível via "Usuários do portal" no
 * FleetTenantsTab. */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

export default function FleetTenantPortalUsersModal({ tenant, onClose }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ email: "", password: "", name: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [createdInfo, setCreatedInfo] = useState(null);

  const reload = async () => {
    try {
      const r = await api._client.get(
        `/fleet-tracking/tenants/${tenant.id}/portal-users`,
      ).then((x) => x.data);
      setUsers(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, []);

  const create = async () => {
    setErr("");
    if (!form.email || !form.password) {
      setErr("E-mail e senha são obrigatórios");
      return;
    }
    if (form.password.length < 6) {
      setErr("Senha precisa ter pelo menos 6 caracteres");
      return;
    }
    setBusy(true);
    try {
      const r = await api._client.post(
        `/fleet-tracking/tenants/${tenant.id}/portal-users`,
        form,
      ).then((x) => x.data);
      const portalUrl = `${window.location.origin}/?portal=fleet`;
      setCreatedInfo({ ...r, password: form.password, portal_url: portalUrl });
      setForm({ email: "", password: "", name: "" });
      reload();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  const remove = async (uid, email) => {
    if (!window.confirm(`Remover acesso de ${email}?`)) return;
    try {
      await api._client.delete(`/fleet-tracking/portal-users/${uid}`);
      reload();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
  };

  return (
    <div style={overlay} data-testid="fleet-portal-users-modal">
      <div style={modal}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 8 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18 }}>
              Usuários do portal — {tenant.name}
            </h2>
            <p style={{ margin: "2px 0 0", fontSize: 12,
                          color: "#64748b" }}>
              Crie acessos para o cliente final acompanhar seus veículos.
              Eles entram em <code style={{ background: "#f1f5f9",
                                              padding: "1px 4px",
                                              borderRadius: 3 }}>
                {window.location.origin}/?portal=fleet
              </code>
            </p>
          </div>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>

        {createdInfo && (
          <div style={successBox}>
            <b>✅ Usuário criado!</b><br />
            E-mail: <code>{createdInfo.email}</code><br />
            Senha: <code>{createdInfo.password}</code><br />
            URL do portal: <a href={createdInfo.portal_url}
                                 target="_blank" rel="noreferrer"
                                 style={{ color: "#1d4ed8" }}>
              {createdInfo.portal_url}
            </a>
            <button onClick={() => {
              navigator.clipboard.writeText(
                `Portal: ${createdInfo.portal_url}\nE-mail: ${createdInfo.email}\nSenha: ${createdInfo.password}`,
              );
              alert("Credenciais copiadas! Envie ao cliente.");
            }}
                     style={{ ...primaryBtn, marginLeft: 8, padding: "4px 10px",
                                fontSize: 11 }}>
              Copiar credenciais
            </button>
          </div>
        )}

        <div style={card}>
          <h4 style={{ margin: "0 0 8px" }}>Novo acesso</h4>
          <div style={{ display: "grid",
                          gridTemplateColumns: "2fr 2fr 1fr auto",
                          gap: 8, alignItems: "end" }}>
            <input value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    placeholder="e-mail do cliente"
                    data-testid="fleet-portal-new-email"
                    style={inp} />
            <input value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    placeholder="senha (mín. 6 char)"
                    data-testid="fleet-portal-new-password"
                    type="text"
                    style={inp} />
            <input value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="nome"
                    style={inp} />
            <button onClick={create} disabled={busy} style={primaryBtn}
                     data-testid="fleet-portal-new-save">
              {busy ? "…" : "Criar"}
            </button>
          </div>
          {err && <div style={errBox}>{err}</div>}
        </div>

        <div style={{ marginTop: 12 }}>
          <h4 style={{ margin: "0 0 8px" }}>
            Acessos ativos ({users.length})
          </h4>
          {!users.length && <div style={empty}>
            Nenhum acesso criado ainda.
          </div>}
          {users.map((u) => (
            <div key={u.id} style={row}>
              <div style={{ flex: 1 }}>
                <b>{u.email}</b>
                {u.name && <span style={{ color: "#64748b",
                                             marginLeft: 8 }}>· {u.name}</span>}
                <div style={{ fontSize: 11, color: "#94a3b8" }}>
                  criado {new Date(u.created_at).toLocaleString("pt-BR")}
                </div>
              </div>
              <button onClick={() => remove(u.id, u.email)} style={dangerBtn}>
                Remover
              </button>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 12, textAlign: "right" }}>
          <button onClick={onClose} style={secBtn}>Fechar</button>
        </div>
      </div>
    </div>
  );
}

const overlay = { position: "fixed", inset: 0, background: "rgba(0,0,0,.45)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", zIndex: 1100, padding: 16 };
const modal = { background: "white", borderRadius: 12, padding: 16,
                 maxWidth: 760, width: "100%", maxHeight: "92vh",
                 overflow: "auto" };
const closeBtn = { background: "transparent", border: 0, fontSize: 20,
                    cursor: "pointer", color: "#94a3b8" };
const card = { background: "#f8fafc", border: "1px solid #e2e8f0",
                 borderRadius: 8, padding: 12 };
const row = { display: "flex", gap: 10, alignItems: "center",
               padding: "10px 12px", borderBottom: "1px solid #f1f5f9" };
const inp = { padding: "7px 10px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13,
                boxSizing: "border-box", width: "100%" };
const primaryBtn = { padding: "8px 16px", background: "#0f172a",
                      color: "white", border: 0, borderRadius: 6,
                      fontWeight: 700, fontSize: 13, cursor: "pointer" };
const secBtn = { ...primaryBtn, background: "white", color: "#475569",
                  border: "1px solid #cbd5e1", fontWeight: 600 };
const dangerBtn = { padding: "4px 12px", background: "#dc2626",
                     color: "white", border: 0, borderRadius: 6,
                     fontSize: 11, cursor: "pointer" };
const empty = { padding: 16, textAlign: "center", color: "#94a3b8",
                 fontSize: 13 };
const errBox = { padding: 10, background: "#fee2e2", color: "#991b1b",
                  borderRadius: 6, fontSize: 12, marginTop: 8 };
const successBox = { padding: 12, background: "#dcfce7", color: "#14532d",
                      borderRadius: 6, fontSize: 13, marginBottom: 12 };
