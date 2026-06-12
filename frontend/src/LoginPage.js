import React, { useState } from "react";
import { useAuth } from "@/AuthContext";
import { ArrowLeft, ShieldCheck, Activity, Layers, Map } from "lucide-react";
import { api } from "@/api";

export default function LoginPage({ onBack }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // CTO 12/06/2026 — Modal "Esqueci a senha"
  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotBusy, setForgotBusy] = useState(false);
  const [forgotMsg, setForgotMsg] = useState("");
  // Mostra aviso quando o usuário cai aqui após sessão invalidada (login em outro device)
  const sessionExpired = typeof window !== "undefined"
    && new URLSearchParams(window.location.search).get("session_expired") === "1";

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

  async function submitForgot(e) {
    e?.preventDefault?.();
    if (!forgotEmail.trim() || !forgotEmail.includes("@")) return;
    setForgotBusy(true); setForgotMsg("");
    try {
      const r = await api.forgotPassword(forgotEmail.trim().toLowerCase());
      setForgotMsg(r?.message || "Se a conta existir, uma nova senha será enviada por WhatsApp em instantes.");
    } catch (err) {
      if (err?.response?.status === 429) {
        const detail = err?.response?.data?.detail;
        setForgotMsg("⚠ " + (typeof detail === "string" ? detail : "Muitas tentativas. Aguarde 1 hora."));
      } else {
        setForgotMsg("Se a conta existir, uma nova senha será enviada por WhatsApp em instantes.");
      }
    } finally {
      setForgotBusy(false);
    }
  }

  const Pillar = ({ icon: Ico, title, desc }) => (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div style={{
        width: 36, height: 36, borderRadius: 8,
        background: "rgba(94,234,212,0.08)",
        border: "1px solid rgba(94,234,212,0.18)",
        display: "grid", placeItems: "center", color: "#5eead4", flexShrink: 0,
      }}>
        <Ico size={18} strokeWidth={1.75} />
      </div>
      <div>
        <div style={{ color: "#f1f5f9", fontSize: 14, fontWeight: 600, letterSpacing: "-0.01em" }}>{title}</div>
        <div style={{ color: "#94a3b8", fontSize: 12.5, marginTop: 2, lineHeight: 1.5 }}>{desc}</div>
      </div>
    </div>
  );

  return (
    <div style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", background: "var(--bg-app)" }}>
      {/* Left — form (light, sober) */}
      <div style={{ display: "flex", flexDirection: "column", padding: "32px 56px", justifyContent: "center", alignItems: "stretch", minWidth: 0 }}>
        <div style={{ maxWidth: 380, width: "100%", margin: "0 auto" }}>
          {onBack && (
            <button
              onClick={onBack}
              data-testid="login-back-btn"
              className="btn btn-ghost btn-sm"
              style={{ marginBottom: 28, paddingLeft: 6 }}
            >
              <ArrowLeft size={14} strokeWidth={1.75} /> Voltar
            </button>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28 }}>
            <img src="/smartprov_icon.png" alt="SmartProv"
                  style={{ width: 36, height: 36, objectFit: "contain" }} />
            <div>
              <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--text-primary)" }}>SmartProv</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", letterSpacing: "0.04em", textTransform: "uppercase", fontWeight: 600 }}>Operações ISP</div>
            </div>
          </div>

          {sessionExpired && (
            <div data-testid="session-expired-banner" style={{
              padding: "10px 14px", borderRadius: 8,
              background: "var(--warning-soft)", color: "var(--warning-soft-fg)",
              border: "1px solid rgba(245,158,11,.3)",
              fontSize: 12.5, marginBottom: 16, lineHeight: 1.5,
            }}>
              <strong>Sua sessão expirou.</strong> Outro acesso foi feito com a mesma conta ou seu token venceu. Entre novamente.
            </div>
          )}

          <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.025em", margin: "0 0 6px" }}>Bem-vindo de volta</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 14, margin: "0 0 28px" }}>
            Acesse o painel da sua operação.
          </p>

          <form onSubmit={submit}>
            <label style={{ display: "block", marginBottom: 14 }}>
              <span className="field-label">E-mail</span>
              <input
                data-testid="login-email"
                type="email"
                className="input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="seu@email.com"
                autoComplete="email"
              />
            </label>
            <label style={{ display: "block", marginBottom: 14 }}>
              <span className="field-label">Senha</span>
              <input
                data-testid="login-password"
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </label>

            {error && (
              <div data-testid="login-error" style={{
                background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
                padding: "10px 12px", borderRadius: 8, marginBottom: 14, fontSize: 13,
                border: "1px solid #fecaca",
              }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              onClick={submit}
              disabled={busy || !email || !password}
              data-testid="login-submit"
              className="btn btn-primary btn-lg"
              style={{ width: "100%" }}
            >
              <ShieldCheck size={16} strokeWidth={1.75} /> {busy ? "Entrando…" : "Entrar"}
            </button>
          </form>

          <p style={{ color: "var(--text-muted)", fontSize: 11.5, marginTop: 18, lineHeight: 1.6 }}>
            <button
              type="button"
              data-testid="forgot-password-link"
              onClick={() => { setForgotOpen(true); setForgotEmail(email || ""); setForgotMsg(""); }}
              style={{
                background: "none", border: 0, padding: 0, cursor: "pointer",
                color: "#7c3aed", fontWeight: 600, fontSize: 11.5,
                textDecoration: "underline",
              }}
            >Esqueceu a senha?</button> Receba uma nova senha por WhatsApp.<br />
            O Google deve usar o mesmo e-mail cadastrado no sistema.
          </p>
          {forgotOpen && (
            <div
              data-testid="forgot-password-modal"
              onClick={(e) => { if (e.target === e.currentTarget) setForgotOpen(false); }}
              style={{
                position: "fixed", inset: 0, zIndex: 1000,
                background: "rgba(0,0,0,0.5)",
                display: "flex", alignItems: "center", justifyContent: "center",
                padding: 20,
              }}
            >
              <div style={{
                background: "white", borderRadius: 16, padding: 24,
                maxWidth: 420, width: "100%",
                boxShadow: "0 20px 50px rgba(0,0,0,0.2)",
              }}>
                <h3 style={{ margin: "0 0 8px 0", fontSize: 20, fontWeight: 700 }}>
                  🔐 Recuperar senha
                </h3>
                <p style={{ margin: "0 0 16px 0", fontSize: 13, color: "#475569", lineHeight: 1.5 }}>
                  Digite seu email. Se houver um colaborador vinculado com
                  telefone cadastrado, uma nova senha será enviada para o
                  WhatsApp dele.
                </p>
                <form onSubmit={submitForgot}>
                  <input
                    data-testid="forgot-email-input"
                    type="email"
                    value={forgotEmail}
                    onChange={(e) => setForgotEmail(e.target.value)}
                    placeholder="seu@email.com"
                    autoFocus
                    style={{
                      width: "100%", padding: "10px 14px",
                      border: "1px solid #cbd5e1", borderRadius: 10,
                      fontSize: 14, marginBottom: 12,
                    }}
                  />
                  {forgotMsg && (
                    <div data-testid="forgot-feedback" style={{
                      padding: 10, borderRadius: 8,
                      background: forgotMsg.startsWith("⚠") ? "#fef3c7" : "#dcfce7",
                      color: forgotMsg.startsWith("⚠") ? "#92400e" : "#166534",
                      fontSize: 12, marginBottom: 12,
                    }}>{forgotMsg}</div>
                  )}
                  <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                    <button
                      type="button"
                      data-testid="forgot-cancel"
                      onClick={() => setForgotOpen(false)}
                      style={{
                        padding: "8px 16px", borderRadius: 8,
                        border: "1px solid #e2e8f0", background: "white",
                        cursor: "pointer", fontSize: 13,
                      }}
                    >Fechar</button>
                    <button
                      type="submit"
                      data-testid="forgot-submit"
                      disabled={forgotBusy || !forgotEmail.includes("@")}
                      style={{
                        padding: "8px 20px", borderRadius: 8,
                        background: forgotBusy ? "#cbd5e1" : "#7c3aed",
                        color: "white", border: 0, fontWeight: 600,
                        cursor: forgotBusy ? "not-allowed" : "pointer",
                        fontSize: 13,
                      }}
                    >{forgotBusy ? "Enviando…" : "Enviar"}</button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right — brand pillar (dark, sober) */}
      <div style={{
        background: "linear-gradient(180deg, #0b1220 0%, #0f172a 100%)",
        position: "relative", overflow: "hidden",
        display: "flex", flexDirection: "column", justifyContent: "center", padding: "56px",
      }}>
        {/* Subtle grid texture */}
        <div aria-hidden="true" style={{
          position: "absolute", inset: 0,
          backgroundImage: `
            linear-gradient(rgba(94,234,212,0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(94,234,212,0.04) 1px, transparent 1px)
          `,
          backgroundSize: "32px 32px",
          maskImage: "radial-gradient(ellipse at center, rgba(0,0,0,1) 30%, rgba(0,0,0,0) 75%)",
          WebkitMaskImage: "radial-gradient(ellipse at center, rgba(0,0,0,1) 30%, rgba(0,0,0,0) 75%)",
        }} />
        <div style={{ position: "relative", zIndex: 1, maxWidth: 460 }}>
          <div className="eyebrow" style={{ color: "#5eead4" }}>Plataforma 2026</div>
          <h2 style={{ color: "#f8fafc", fontSize: 32, lineHeight: 1.2, fontWeight: 700, letterSpacing: "-0.025em", margin: "10px 0 16px" }}>
            Toda sua operação<br />em um só lugar.
          </h2>
          <p style={{ color: "#94a3b8", fontSize: 14.5, lineHeight: 1.6, margin: "0 0 36px", maxWidth: 420 }}>
            Lousa de despacho, ponto facial, estoque, integrações Atlaz V2 e SmartOLT — com IA e auditoria nativas.
          </p>
          <div style={{ display: "grid", gap: 18, gridTemplateColumns: "1fr" }}>
            <Pillar icon={Layers} title="Lousa Kanban em tempo real" desc="Sincronização Atlaz V2, SLA por bolha, drag-and-drop por técnico." />
            <Pillar icon={Activity} title="Estoque automático" desc="Dedução por chamado, sinal ONU SmartOLT, alertas preventivos." />
            <Pillar icon={Map} title="IA com geofence" desc="Heatmaps OSM, IQR de outliers, ranking de produtividade." />
          </div>
        </div>
      </div>
    </div>
  );
}
