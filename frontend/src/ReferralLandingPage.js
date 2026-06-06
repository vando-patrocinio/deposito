import React, { useEffect, useState } from "react";
import { api } from "@/api";

/**
 * Landing pública /r/:code — "Convite especial de indicação"
 *
 * Amigo abre o link recebido no WhatsApp do indicador. Captura
 * nome + telefone + bairro → cria lead + Isabella dispara mensagem
 * WhatsApp imediatamente. Visual alinhado ao padrão "Indique e Ganhe"
 * (iter148): glass-morphism, gradient text, big number, chips,
 * SVG art animado, shine sweep — paleta roxo Ligo + laranja sorriso.
 */
export default function ReferralLandingPage({ code }) {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({
    friend_name: "", friend_phone: "", friend_neighborhood: "",
  });

  useEffect(() => {
    api.publicReferralInfo(code)
      .then(setInfo)
      .catch((e) => setErr(e?.response?.data?.detail || "Link inválido"))
      .finally(() => setLoading(false));
  }, [code]);

  async function submit() {
    setBusy(true); setErr(null);
    try {
      await api.publicReferralSubmit(code, form);
      setSubmitted(true);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Erro ao enviar");
    } finally { setBusy(false); }
  }

  return (
    <PageShell>
      <Animations />
      {loading ? (
        <SkeletonHero />
      ) : err && !info ? (
        <InvalidLinkCard message={err} />
      ) : submitted ? (
        <SuccessCard ownerName={info.owner_first_name} />
      ) : (
        <FormCard
          info={info} form={form} setForm={setForm}
          busy={busy} err={err} onSubmit={submit}
        />
      )}
    </PageShell>
  );
}

/* ──────────────────────────────────────────────────────────────────────── */
/*  Shell + animations                                                     */
/* ──────────────────────────────────────────────────────────────────────── */

function PageShell({ children }) {
  return (
    <div data-testid="referral-landing-shell" style={{
      minHeight: "100vh",
      background:
        "radial-gradient(1200px 700px at 8% -10%, #FF6A1A33 0%, transparent 60%),"
        + "radial-gradient(900px 600px at 110% 10%, #9333EA44 0%, transparent 60%),"
        + "linear-gradient(160deg, #1a0840 0%, #2d0b6e 38%, #4C1D95 80%, #6B2BFB 130%)",
      padding: "26px 16px 60px",
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "flex-start",
      position: "relative", overflow: "hidden",
    }}>
      {/* Noise texture overlay */}
      <div aria-hidden style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage:
          "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.07 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")",
        opacity: 0.55, mixBlendMode: "overlay",
      }} />
      <BrandTopBar />
      <div style={{
        maxWidth: 480, width: "100%",
        position: "relative", zIndex: 2,
      }}>
        {children}
      </div>
    </div>
  );
}

function BrandTopBar() {
  return (
    <div style={{
      width: "100%", maxWidth: 480, display: "flex",
      alignItems: "center", justifyContent: "space-between",
      marginBottom: 22, position: "relative", zIndex: 2,
    }}>
      <img src="/ligo-logo-white.png" alt="Ligo Fibra"
            style={{
              height: "clamp(46px, 7.5vw, 64px)", width: "auto",
              filter: "drop-shadow(0 8px 24px rgba(255,106,26,.35))",
            }} />
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "5px 11px", borderRadius: 999,
        background: "rgba(255,255,255,.08)",
        border: "1px solid rgba(255,255,255,.18)",
        fontSize: 10.5, fontWeight: 800,
        letterSpacing: 1.5, textTransform: "uppercase",
        color: "#FFE6D2",
        backdropFilter: "blur(10px)",
      }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%",
                        background: "#4ade80",
                        boxShadow: "0 0 10px #4ade80" }} />
        Convite especial
      </span>
    </div>
  );
}

function Animations() {
  return (
    <style>{`
      @keyframes ligo-fadeup{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
      @keyframes ligo-shine{0%{transform:translateX(-120%) skewX(-12deg)}100%{transform:translateX(220%) skewX(-12deg)}}
      @keyframes ligo-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
      @keyframes ligo-pulse{0%,100%{box-shadow:0 0 0 0 rgba(74,222,128,.6)}50%{box-shadow:0 0 0 14px rgba(74,222,128,0)}}
      @keyframes ligo-pop{0%{transform:scale(.6);opacity:0}60%{transform:scale(1.1);opacity:1}100%{transform:scale(1)}}
      .ligo-anim-up{animation:ligo-fadeup .55s cubic-bezier(.2,.7,.2,1) both}
      .ligo-anim-art{animation:ligo-float 6s ease-in-out infinite}
      .ligo-anim-pop{animation:ligo-pop .6s cubic-bezier(.2,.7,.2,1) both}
      .ligo-anim-pulse{animation:ligo-pulse 2.2s ease infinite}
      .ligo-cta:hover .ligo-shine{animation:ligo-shine 1.1s ease forwards}
      .ligo-cta:hover{transform:translateY(-2px) scale(1.012)}
      .ligo-cta:active{transform:translateY(0) scale(.992)}
      .ligo-input:focus{outline:none;border-color:#FF6A1A;box-shadow:0 0 0 4px rgba(255,106,26,.18)}
    `}</style>
  );
}

/* ──────────────────────────────────────────────────────────────────────── */
/*  Form card                                                              */
/* ──────────────────────────────────────────────────────────────────────── */

function FormCard({ info, form, setForm, busy, err, onSubmit }) {
  const canSubmit = form.friend_name.trim() && form.friend_phone.trim();
  return (
    <div data-testid="referral-landing"
          className="ligo-anim-up"
          style={cardShell}>
      {/* Header roxo-laranja com art SVG */}
      <div style={{
        position: "relative", overflow: "hidden",
        background:
          "linear-gradient(155deg, #6B2BFB 0%, #7C3AED 40%, #4C1D95 100%)",
        padding: "26px 22px 28px", color: "#fff",
      }}>
        <FiberArt />
        <div style={{
          fontSize: 10.5, fontWeight: 800, letterSpacing: 2,
          textTransform: "uppercase", color: "#FFE6D2",
          opacity: 0.85, position: "relative", zIndex: 2,
        }}>
          Programa Indique e Ganhe
        </div>
        <h1 style={{
          fontSize: "clamp(26px, 6.5vw, 34px)", fontWeight: 900,
          margin: "8px 0 4px", letterSpacing: -1.2, lineHeight: 1.05,
          textShadow: "0 4px 14px rgba(0,0,0,.25)",
          position: "relative", zIndex: 2,
        }}>
          <span style={{
            background: "linear-gradient(90deg,#FFB74D 0%,#FF6A1A 60%,#FB923C 100%)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>{info.owner_first_name}</span>{" "}
          te indicou pra LIGO!
        </h1>
        <p style={{
          fontSize: 13.5, lineHeight: 1.55, margin: "8px 0 0",
          color: "#ede9fe", opacity: 0.95,
          position: "relative", zIndex: 2, maxWidth: 360,
        }}>
          Internet de fibra óptica direto na sua casa: mais velocidade,
          estabilidade e atendimento de verdade.
        </p>

        {/* Chips de proof */}
        <div style={{
          display: "flex", flexWrap: "wrap", gap: 6,
          marginTop: 14, position: "relative", zIndex: 2,
        }}>
          <Chip>100% Fibra Óptica</Chip>
          <Chip>Wi-Fi premium</Chip>
          <Chip>Instalação rápida</Chip>
        </div>
      </div>

      {/* Form body */}
      <div style={{ padding: "22px 22px 24px" }}>
        <Field label="Seu nome" required>
          <input data-testid="ref-name"
                  className="ligo-input"
                  style={inputStyle}
                  value={form.friend_name}
                  onChange={(e) => setForm({ ...form, friend_name: e.target.value })}
                  placeholder="João da Silva" />
        </Field>

        <Field label="WhatsApp" required hint="Receba a proposta no zap">
          <input data-testid="ref-phone"
                  className="ligo-input"
                  style={inputStyle}
                  value={form.friend_phone}
                  onChange={(e) => setForm({ ...form, friend_phone: e.target.value })}
                  placeholder="(21) 99999-9999"
                  inputMode="tel" />
        </Field>

        <Field label="Bairro / Cidade">
          <input data-testid="ref-neighborhood"
                  className="ligo-input"
                  style={inputStyle}
                  value={form.friend_neighborhood}
                  onChange={(e) => setForm({ ...form, friend_neighborhood: e.target.value })}
                  placeholder="Ex: Tijuca / Rio de Janeiro" />
        </Field>

        {err && (
          <div style={{
            background: "#fef2f2", color: "#b91c1c",
            padding: "10px 12px", borderRadius: 10,
            fontSize: 13, marginTop: 12,
            border: "1px solid #fecaca",
          }}>{err}</div>
        )}

        <button data-testid="ref-submit"
                className="ligo-cta"
                onClick={onSubmit}
                disabled={busy || !canSubmit}
                style={{
                  position: "relative", overflow: "hidden",
                  width: "100%", padding: "15px 18px", marginTop: 18,
                  background: !canSubmit || busy
                    ? "#cbd5e1"
                    : "linear-gradient(135deg, #25D366 0%, #128C7E 100%)",
                  color: "white", border: "none", borderRadius: 14,
                  fontSize: 15.5, fontWeight: 900, letterSpacing: 0.3,
                  cursor: !canSubmit || busy ? "not-allowed" : "pointer",
                  boxShadow: !canSubmit || busy
                    ? "none"
                    : "0 14px 30px rgba(37,211,102,.45)",
                  transition: "transform .25s ease, box-shadow .25s ease",
                  display: "inline-flex", alignItems: "center",
                  justifyContent: "center", gap: 10,
                }}>
          {/* Shine */}
          {canSubmit && !busy && (
            <span className="ligo-shine" aria-hidden style={{
              position: "absolute", top: 0, bottom: 0, width: "45%",
              left: 0, transform: "translateX(-120%) skewX(-12deg)",
              background: "linear-gradient(90deg, transparent, rgba(255,255,255,.4), transparent)",
              pointerEvents: "none",
            }} />
          )}
          <WhatsIcon />
          {busy ? "Enviando…" : "Chamar no WhatsApp"}
        </button>

        <div style={{
          marginTop: 12, display: "flex", alignItems: "center",
          gap: 6, justifyContent: "center",
          color: "#94a3b8", fontSize: 11,
        }}>
          <span></span> Seus dados ficam protegidos · Sem spam
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, required, children }) {
  return (
    <div style={{ marginTop: 12 }}>
      <label style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "baseline", fontSize: 11.5, fontWeight: 700,
        color: "#475569", marginBottom: 6, textTransform: "uppercase",
        letterSpacing: 0.6,
      }}>
        <span>{label}{required && <span style={{ color: "#FF6A1A" }}> *</span>}</span>
        {hint && <span style={{ color: "#94a3b8", textTransform: "none",
                                  letterSpacing: 0, fontWeight: 500,
                                  fontSize: 10.5 }}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

function Chip({ children }) {
  return (
    <span style={{
      padding: "5px 10px", borderRadius: 999,
      background: "rgba(255,255,255,.14)",
      backdropFilter: "blur(8px)",
      fontSize: 11, fontWeight: 700, color: "#fff",
      border: "1px solid rgba(255,255,255,.22)",
      whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

function WhatsIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 32 32" fill="currentColor"
          aria-hidden style={{ filter: "drop-shadow(0 2px 4px rgba(0,0,0,.2))" }}>
      <path d="M16 .5A15.5 15.5 0 0 0 2.5 23.6L0 31.5l8.1-2.5A15.5 15.5 0 1 0 16 .5zm9 22.4c-.4 1-2.3 2.1-3.1 2.2-.8.1-1.8.5-6-1.3-5-2.1-8.2-7.1-8.5-7.4-.2-.4-2-2.7-2-5.1s1.3-3.6 1.8-4.1c.5-.5 1-.6 1.3-.6h1c.3 0 .8 0 1.1.8.4 1 1.4 3.4 1.5 3.6.1.2.2.5 0 .8-.2.4-.4.6-.7 1-.4.4-.8.9-1.1 1.2-.4.4-.7.8-.3 1.5.4.8 1.8 2.9 3.8 4.7 2.6 2.3 4.8 3 5.5 3.4.7.4 1.1.3 1.5-.2.4-.5 1.7-2 2.2-2.7.5-.7.9-.6 1.5-.4.6.2 4 1.9 4.6 2.2.6.3 1.1.5 1.2.7.2.2.2 1.1-.3 2.7z" />
    </svg>
  );
}

/* ──────────────────────────────────────────────────────────────────────── */
/*  Success / Invalid / Skeleton                                           */
/* ──────────────────────────────────────────────────────────────────────── */

function SuccessCard({ ownerName }) {
  return (
    <div className="ligo-anim-up" data-testid="referral-success" style={cardShell}>
      <div style={{
        background:
          "linear-gradient(155deg, #25D366 0%, #128C7E 60%, #075E54 100%)",
        padding: "44px 22px 28px", color: "#fff",
        textAlign: "center", position: "relative", overflow: "hidden",
      }}>
        <div className="ligo-anim-pop" style={{
          width: 88, height: 88, margin: "0 auto 14px",
          borderRadius: "50%", background: "rgba(255,255,255,.18)",
          display: "grid", placeItems: "center",
          boxShadow: "0 12px 30px rgba(0,0,0,.18)",
        }}>
          <span style={{ fontSize: 44 }}></span>
        </div>
        <h1 style={{
          margin: 0, fontSize: 28, fontWeight: 900, letterSpacing: -1,
          textShadow: "0 4px 14px rgba(0,0,0,.25)",
        }}>Tudo certo!</h1>
        <p style={{
          margin: "10px auto 0", maxWidth: 320, fontSize: 14,
          lineHeight: 1.55, color: "rgba(255,255,255,.92)",
        }}>
          Em alguns segundos a <b>Isabella</b> vai te chamar no WhatsApp
          com os planos disponíveis na sua região.
        </p>
      </div>
      <div style={{ padding: "20px 22px 24px", textAlign: "center" }}>
        <div className="ligo-anim-pulse" style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          padding: "9px 16px", borderRadius: 999,
          background: "#ecfdf5", color: "#065f46",
          fontSize: 12.5, fontWeight: 800,
          border: "1px solid #6ee7b7",
        }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%",
                          background: "#22c55e" }} />
          Aguardando contato no WhatsApp
        </div>
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 16 }}>
          Pode fechar essa página. {ownerName} também será notificado(a).
        </p>
      </div>
    </div>
  );
}

function InvalidLinkCard({ message }) {
  return (
    <div className="ligo-anim-up" style={cardShell}>
      <div style={{
        padding: "32px 22px", textAlign: "center", color: "#0f172a",
      }}>
        <div style={{ fontSize: 56, marginBottom: 8 }}></div>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 900,
                      color: "#dc2626" }}>Link inválido</h1>
        <p style={{ color: "#64748b", marginTop: 8, fontSize: 14 }}>
          {message}
        </p>
        <a href="/" style={{
          display: "inline-block", marginTop: 14,
          padding: "10px 18px", borderRadius: 10,
          background: "#6B2BFB", color: "white",
          fontSize: 13, fontWeight: 700, textDecoration: "none",
        }}>Ir pra LIGO →</a>
      </div>
    </div>
  );
}

function SkeletonHero() {
  return (
    <div style={{
      ...cardShell, padding: 24, color: "#fff",
      background: "rgba(255,255,255,.06)",
      border: "1px solid rgba(255,255,255,.12)",
    }}>
      <div style={{ height: 14, width: 120, background: "rgba(255,255,255,.12)",
                      borderRadius: 6, marginBottom: 12 }} />
      <div style={{ height: 26, width: "80%", background: "rgba(255,255,255,.16)",
                      borderRadius: 6, marginBottom: 10 }} />
      <div style={{ height: 14, width: "60%", background: "rgba(255,255,255,.1)",
                      borderRadius: 6 }} />
      <div style={{ marginTop: 18, color: "rgba(255,255,255,.7)",
                      fontSize: 13 }}>Carregando seu convite…</div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────── */
/*  Background SVG art (fibra/sinal)                                       */
/* ──────────────────────────────────────────────────────────────────────── */

function FiberArt() {
  return (
    <div className="ligo-anim-art" aria-hidden style={{
      position: "absolute", top: -20, right: -30,
      width: 220, height: 220, opacity: 0.55, zIndex: 1,
      pointerEvents: "none",
    }}>
      <svg viewBox="0 0 200 200" width="100%" height="100%">
        <defs>
          <linearGradient id="fb-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#FFB74D" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#FF6A1A" stopOpacity="0.55" />
          </linearGradient>
          <radialGradient id="fb-r" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#fff" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#fff" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="150" cy="60" r="50" fill="url(#fb-r)" />
        <circle cx="150" cy="60" r="58" fill="none"
                stroke="url(#fb-g)" strokeWidth="2" opacity="0.7" />
        <circle cx="150" cy="60" r="40" fill="none"
                stroke="url(#fb-g)" strokeWidth="3" opacity="0.85" />
        <circle cx="150" cy="60" r="22" fill="url(#fb-g)" />
        {/* Linhas de fibra ondulada */}
        <path d="M20 130 Q90 80 155 110 T220 90" fill="none"
              stroke="url(#fb-g)" strokeWidth="2.5"
              strokeLinecap="round" opacity="0.55" />
        <path d="M10 160 Q70 130 130 150 T210 130" fill="none"
              stroke="url(#fb-g)" strokeWidth="2"
              strokeLinecap="round" opacity="0.4" />
      </svg>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────── */
/*  Styles                                                                 */
/* ──────────────────────────────────────────────────────────────────────── */

const cardShell = {
  background: "white",
  borderRadius: 24,
  overflow: "hidden",
  width: "100%",
  boxShadow: "0 30px 70px -10px rgba(0,0,0,.45)",
  border: "1px solid rgba(255,255,255,.12)",
};

const inputStyle = {
  width: "100%", padding: "13px 14px",
  border: "1px solid #cbd5e1", borderRadius: 12,
  fontSize: 15, outline: "none", boxSizing: "border-box",
  background: "#fff", color: "#0f172a",
  transition: "border-color .2s ease, box-shadow .2s ease",
  fontFamily: "inherit",
};
