import React, { useState } from "react";
import { api } from "@/api";

const ACCENT = "#10b981";
const BG_DARK = "#0a1322";

export default function SignupPage({ onSuccess, onBack, defaultPlan = "trial" }) {
  const [companyName, setCompanyName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [plan, setPlan] = useState(defaultPlan === "free" ? "free" : "trial");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e) {
    e.preventDefault();
    setErr("");
    if (password.length < 6) { setErr("Senha precisa ter no mínimo 6 caracteres."); return; }
    setBusy(true);
    try {
      const r = await api.saasSignup({
        company_name: companyName.trim(),
        admin_name: adminName.trim(),
        email: email.trim().toLowerCase(),
        password,
        phone: phone.trim() || null,
        plan,
      });
      try { window.localStorage.setItem("ponto_token", r.access_token); } catch {}
      if (onSuccess) onSuccess(r);
      else window.location.href = "/app";
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join(" · ") : (detail || e.message);
      setErr(msg);
    } finally {
      setBusy(false);
    }
  }

  const inputStyle = {
    width: "100%", padding: "13px 16px", borderRadius: 12,
    border: "1px solid rgba(255,255,255,.1)",
    background: "rgba(255,255,255,.04)", color: "white",
    fontSize: 14.5, outline: "none",
    transition: "border-color .2s, background .2s",
    fontFamily: "inherit",
  };
  const labelStyle = { display: "block", color: "#cbd5e1", fontSize: 12, fontWeight: 700, marginBottom: 7, letterSpacing: "0.02em", textTransform: "uppercase" };

  return (
    <div data-testid="signup-page" style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse 80% 60% at 50% -20%, rgba(16,185,129,.15) 0%, ${BG_DARK} 55%, #050b16 100%)`,
      color: "#e2e8f0",
      fontFamily: "'Inter', system-ui, sans-serif",
      padding: "48px 22px",
    }}>
      <div style={{ maxWidth: 480, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <button
            onClick={onBack}
            data-testid="signup-back-btn"
            style={{
              background: "transparent", border: "1px solid rgba(255,255,255,.1)",
              color: "#94a3b8", padding: "6px 12px", borderRadius: 999,
              fontSize: 12, cursor: "pointer", marginBottom: 24,
            }}
          >← Voltar</button>
          <div style={{
            width: 44, height: 44, borderRadius: 12, margin: "0 auto 14px",
            background: "linear-gradient(135deg,#10b981,#059669)",
            display: "grid", placeItems: "center", fontSize: 22,
            boxShadow: "0 14px 30px rgba(16,185,129,.3)",
          }}>📍</div>
          <h1 style={{ margin: 0, color: "white", fontSize: 30, fontWeight: 850, letterSpacing: "-0.02em" }}>Criar conta da empresa</h1>
          <p style={{ marginTop: 10, color: "#94a3b8", fontSize: 14, lineHeight: 1.5 }}>
            {plan === "free"
              ? "Plano Free para sempre, até 3 colaboradores. Sem cartão."
              : "14 dias grátis no Pro. Sem cartão. Até 25 colaboradores."}
          </p>
        </div>

        {/* Seletor de plano */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 18 }} data-testid="plan-selector">
          <button
            type="button"
            onClick={() => setPlan("free")}
            data-testid="plan-free-btn"
            style={{
              padding: "12px 14px", borderRadius: 14, cursor: "pointer",
              border: plan === "free" ? "1px solid #10b981" : "1px solid rgba(255,255,255,.12)",
              background: plan === "free" ? "rgba(16,185,129,.08)" : "rgba(255,255,255,.03)",
              color: "white", fontSize: 13, fontWeight: 700, textAlign: "left",
              fontFamily: "inherit",
            }}
          >
            <div style={{ fontSize: 11, color: plan === "free" ? "#34d399" : "#64748b", letterSpacing: "0.04em" }}>FREE</div>
            <div style={{ fontSize: 18, fontWeight: 900, marginTop: 2 }}>R$ 0</div>
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>3 colaboradores · sem expiração</div>
          </button>
          <button
            type="button"
            onClick={() => setPlan("trial")}
            data-testid="plan-trial-btn"
            style={{
              padding: "12px 14px", borderRadius: 14, cursor: "pointer",
              border: plan === "trial" ? "1px solid #10b981" : "1px solid rgba(255,255,255,.12)",
              background: plan === "trial" ? "rgba(16,185,129,.08)" : "rgba(255,255,255,.03)",
              color: "white", fontSize: 13, fontWeight: 700, textAlign: "left",
              fontFamily: "inherit",
            }}
          >
            <div style={{ fontSize: 11, color: plan === "trial" ? "#34d399" : "#64748b", letterSpacing: "0.04em" }}>PRO TRIAL</div>
            <div style={{ fontSize: 18, fontWeight: 900, marginTop: 2 }}>R$ 99/mês</div>
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>25 colaboradores · 14d grátis</div>
          </button>
        </div>

        <form
          onSubmit={submit}
          data-testid="signup-form"
          style={{
            background: "rgba(255,255,255,.03)",
            border: "1px solid rgba(255,255,255,.08)",
            borderRadius: 22, padding: 28,
            backdropFilter: "blur(8px)",
          }}
        >
          {err && (
            <div data-testid="signup-error" style={{
              background: "rgba(239,68,68,.1)", border: "1px solid rgba(239,68,68,.3)",
              color: "#fca5a5", padding: "11px 14px", borderRadius: 10,
              fontSize: 13, marginBottom: 18,
            }}>{err}</div>
          )}

          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Nome da empresa *</label>
            <input
              type="text" required value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="Ex.: Acme Tecnologia"
              data-testid="signup-company"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Seu nome *</label>
            <input
              type="text" required value={adminName}
              onChange={(e) => setAdminName(e.target.value)}
              placeholder="Como gostaria de ser chamado(a)"
              data-testid="signup-admin-name"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Email *</label>
            <input
              type="email" required value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="voce@suaempresa.com"
              data-testid="signup-email"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Senha *</label>
            <input
              type="password" required value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Mínimo 6 caracteres"
              data-testid="signup-password"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: 22 }}>
            <label style={labelStyle}>WhatsApp (opcional)</label>
            <input
              type="tel" value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="(11) 99999-9999"
              data-testid="signup-phone"
              style={inputStyle}
            />
          </div>

          <button
            type="submit" disabled={busy}
            data-testid="signup-submit"
            style={{
              width: "100%", padding: "15px 20px", borderRadius: 14,
              border: 0, background: ACCENT, color: "#050b16",
              fontSize: 15, fontWeight: 800, cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.7 : 1, transition: "opacity .2s, transform .2s",
              boxShadow: "0 14px 30px rgba(16,185,129,.35)",
            }}
          >{busy
              ? "Criando conta..."
              : (plan === "free" ? "Começar grátis →" : "Criar conta e iniciar trial →")
          }</button>

          <p style={{ marginTop: 18, color: "#64748b", fontSize: 12, textAlign: "center", lineHeight: 1.5 }}>
            Ao criar a conta você concorda com os Termos de Uso. {plan === "free" ? "Plano gratuito sem expiração." : "Não cobramos cartão durante o trial."}
          </p>
        </form>
      </div>
    </div>
  );
}
