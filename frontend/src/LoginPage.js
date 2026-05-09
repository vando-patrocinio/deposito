import React, { useState } from "react";
import { useAuth } from "@/AuthContext";
import { Button, Card, Field, Icon, inputStyle } from "@/ui";

export default function LoginPage({ onBack }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e?.preventDefault?.();
    setBusy(true); setError("");
    try {
      await login(email.trim().toLowerCase(), password);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : (err.message || "Erro ao entrar."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: "linear-gradient(180deg,#0f172a 0%,#1e293b 100%)", display: "grid", placeItems: "center", padding: 18 }}>
      <div style={{ width: "100%", maxWidth: 420 }}>
        {onBack && (
          <button
            onClick={onBack}
            data-testid="login-back-btn"
            style={{
              background: "transparent", border: "1px solid rgba(255,255,255,.15)",
              color: "#94a3b8", padding: "6px 14px", borderRadius: 999,
              fontSize: 12, cursor: "pointer", marginBottom: 16,
            }}
          >← Voltar à página inicial</button>
        )}
        <h1 style={{ color: "white", fontSize: 26, marginBottom: 6, textAlign: "center" }}>PontoIA</h1>
        <p style={{ color: "#94a3b8", textAlign: "center", marginTop: 0, marginBottom: 22, fontSize: 14 }}>
          Entre com seu e-mail e senha.
        </p>

        <Card style={{ marginBottom: 0 }}>
          <form onSubmit={submit}>
            <Field label="E-mail">
              <input
                data-testid="login-email"
                type="email"
                style={inputStyle}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="seu@email.com"
              />
            </Field>
            <Field label="Senha">
              <input
                data-testid="login-password"
                type="password"
                style={inputStyle}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </Field>
            {error && (
              <div data-testid="login-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10, fontSize: 13 }}>
                {error}
              </div>
            )}
            <Button type="submit" onClick={submit} disabled={busy || !email || !password} data-testid="login-submit" style={{ width: "100%" }}>
              <Icon name="shield" /> {busy ? "Entrando..." : "Entrar"}
            </Button>
          </form>
        </Card>
        <p style={{ color: "#94a3b8", fontSize: 11, marginTop: 14, textAlign: "center" }}>
          Esqueceu a senha? Procure o auditor para redefini-la.<br />
          O Google deve usar o mesmo e-mail cadastrado no sistema.
        </p>
      </div>
    </div>
  );
}
