/**
 * CTO 12/06/2026 — Modal de troca forçada de senha após recuperação via WhatsApp.
 *
 * Bloqueia totalmente a app enquanto não trocar (overlay full screen, sem botão
 * de fechar). Usuário só consegue prosseguir após trocar.
 *
 * Renderizado pelo App.js quando `mustChangePassword` do AuthContext está true.
 */
import React, { useState } from "react";
import { api } from "@/api";
import { useAuth } from "@/AuthContext";
import { ShieldCheck } from "lucide-react";

export default function ForcedPasswordChangeModal() {
  const { clearMustChangePassword } = useAuth();
  const [pwd, setPwd] = useState("");
  const [pwd2, setPwd2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const valid = pwd.length >= 8 && pwd === pwd2;

  async function submit(e) {
    e?.preventDefault?.();
    setError("");
    if (pwd.length < 8) return setError("A senha precisa ter no mínimo 8 caracteres.");
    if (pwd !== pwd2) return setError("As senhas não conferem.");
    setBusy(true);
    try {
      await api.changePasswordForced(pwd);
      clearMustChangePassword();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : (err.message || "Erro ao alterar senha."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="forced-password-modal"
      style={{
        position: "fixed", inset: 0, zIndex: 99999,
        background: "rgba(15, 23, 42, 0.85)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
    >
      <div style={{
        background: "white", borderRadius: 16, padding: 32,
        maxWidth: 460, width: "100%",
        boxShadow: "0 20px 50px rgba(0,0,0,0.4)",
      }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 12,
            background: "#ddd6fe", display: "grid", placeItems: "center",
            color: "#5b21b6",
          }}>
            <ShieldCheck size={22} strokeWidth={2} />
          </div>
          <h3 style={{ margin: 0, fontSize: 19, fontWeight: 700 }}>
            Troca de senha obrigatória
          </h3>
        </div>
        <p style={{ margin: "0 0 18px 0", fontSize: 13, color: "#475569", lineHeight: 1.5 }}>
          Você acabou de logar com uma senha temporária enviada por WhatsApp.
          Por segurança, defina uma nova senha agora.
        </p>
        <form onSubmit={submit}>
          <label style={{ fontSize: 11, fontWeight: 700, color: "#64748b", letterSpacing: ".05em", textTransform: "uppercase" }}>
            Nova senha
          </label>
          <input
            data-testid="forced-pwd-1"
            type="password"
            value={pwd}
            onChange={(e) => setPwd(e.target.value)}
            placeholder="Mínimo 8 caracteres"
            autoFocus
            style={{
              width: "100%", padding: "10px 14px",
              border: "1px solid #cbd5e1", borderRadius: 10,
              fontSize: 14, marginTop: 4, marginBottom: 12,
            }}
          />
          <label style={{ fontSize: 11, fontWeight: 700, color: "#64748b", letterSpacing: ".05em", textTransform: "uppercase" }}>
            Confirme a nova senha
          </label>
          <input
            data-testid="forced-pwd-2"
            type="password"
            value={pwd2}
            onChange={(e) => setPwd2(e.target.value)}
            placeholder="Digite de novo"
            style={{
              width: "100%", padding: "10px 14px",
              border: "1px solid #cbd5e1", borderRadius: 10,
              fontSize: 14, marginTop: 4, marginBottom: 12,
            }}
          />
          {error && (
            <div data-testid="forced-pwd-error" style={{
              padding: 10, borderRadius: 8,
              background: "#fee2e2", color: "#991b1b",
              fontSize: 12, marginBottom: 12,
            }}>{error}</div>
          )}
          {pwd && pwd2 && pwd === pwd2 && (
            <div style={{
              padding: 8, borderRadius: 6,
              background: "#dcfce7", color: "#166534",
              fontSize: 11, marginBottom: 12,
            }}>✓ Senhas conferem</div>
          )}
          <button
            type="submit"
            data-testid="forced-pwd-submit"
            disabled={busy || !valid}
            style={{
              width: "100%", padding: "12px 20px", borderRadius: 10,
              background: (busy || !valid) ? "#cbd5e1" : "#7c3aed",
              color: "white", border: 0, fontWeight: 700,
              cursor: (busy || !valid) ? "not-allowed" : "pointer",
              fontSize: 14,
            }}
          >{busy ? "Salvando…" : "Alterar senha e continuar"}</button>
        </form>
      </div>
    </div>
  );
}
