import React, { useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, Icon, inputStyle } from "@/ui";

const KEY = "ponto_admin_session";

export function isAdminLogged() {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(KEY) === "1";
}

export function setAdminLogged(v) {
  if (typeof window === "undefined") return;
  if (v) window.localStorage.setItem(KEY, "1");
  else window.localStorage.removeItem(KEY);
}

export default function AdminLogin({ onSuccess }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e?.preventDefault?.();
    setBusy(true);
    setError("");
    try {
      await api.adminLogin(password);
      setAdminLogged(true);
      onSuccess?.();
    } catch (err) {
      setError(err?.response?.data?.detail || "Senha inválida.");
    }
    setBusy(false);
  }

  return (
    <div style={{ maxWidth: 420, margin: "60px auto" }}>
      <Card title="Acesso do gestor">
        <p style={{ color: "#64748b", marginTop: 0 }}>
          Esta área é restrita ao administrador. Informe a senha para continuar.
        </p>
        <form onSubmit={submit}>
          <Field label="Senha do administrador">
            <input
              data-testid="admin-password"
              type="password"
              autoFocus
              style={inputStyle}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </Field>
          {error && (
            <div data-testid="login-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>
              {error}
            </div>
          )}
          <Button type="submit" onClick={submit} disabled={busy || !password} data-testid="admin-login-btn">
            <Icon name="shield" /> {busy ? "Entrando..." : "Entrar"}
          </Button>
        </form>
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 16 }}>
          Use a senha de administrador configurada em <code>backend/.env → ADMIN_PASSWORD</code>.
        </p>
      </Card>
    </div>
  );
}
