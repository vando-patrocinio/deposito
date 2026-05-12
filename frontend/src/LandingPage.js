/**
 * SmartProv — Landing Page
 * Design system: "Swiss & High-Contrast" (light), Stripe-meets-Linear aesthetic.
 * Refer to /app/design_guidelines.json for tokens.
 */
import React, { useEffect } from "react";

// --------- design tokens ---------
const C = {
  bg: "#FFFFFF",
  bgMuted: "#F8FAFC",
  bgSubtle: "#F1F5F9",
  border: "#E2E8F0",
  borderHover: "#CBD5E1",
  text: "#0F172A",
  textSecondary: "#475569",
  textMuted: "#64748B",
  brand: "#0055FF",
  brandHover: "#0044CC",
  accent: "#00C2FF",
  success: "#10B981",
  warning: "#F59E0B",
  ink: "#020617",
};

const css = `
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; }

.sp-page {
  background: ${C.bg};
  color: ${C.text};
  font-family: 'Inter', -apple-system, system-ui, sans-serif;
  font-feature-settings: "ss01", "cv11";
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
}

.sp-display { font-family: 'Space Grotesk', 'Inter', sans-serif; letter-spacing: -0.025em; font-weight: 600; }
.sp-mono { font-family: 'JetBrains Mono', monospace; }

@keyframes sp-fade-up { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
@keyframes sp-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes sp-shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
@keyframes sp-pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
@keyframes sp-tick { from { stroke-dashoffset: 100; } to { stroke-dashoffset: 0; } }
.sp-fade-up { opacity: 0; animation: sp-fade-up .7s cubic-bezier(.16,1,.3,1) forwards; }

.sp-grid-bg {
  background-image:
    linear-gradient(${C.border}66 1px, transparent 1px),
    linear-gradient(90deg, ${C.border}66 1px, transparent 1px);
  background-size: 56px 56px;
  background-position: center;
  mask-image: radial-gradient(ellipse 60% 60% at center, black 30%, transparent 80%);
  -webkit-mask-image: radial-gradient(ellipse 60% 60% at center, black 30%, transparent 80%);
}

.sp-cta-primary {
  display: inline-flex; align-items: center; gap: 8px;
  background: ${C.ink}; color: white;
  padding: 12px 22px; border-radius: 8px;
  font-weight: 600; font-size: 14.5px;
  border: 1px solid ${C.ink};
  cursor: pointer; text-decoration: none;
  transition: all .2s cubic-bezier(.4,0,.2,1);
}
.sp-cta-primary:hover { background: ${C.brand}; border-color: ${C.brand}; transform: translateY(-1px); box-shadow: 0 10px 30px -10px ${C.brand}66; }

.sp-cta-secondary {
  display: inline-flex; align-items: center; gap: 8px;
  background: white; color: ${C.text};
  padding: 12px 22px; border-radius: 8px;
  font-weight: 600; font-size: 14.5px;
  border: 1px solid ${C.border};
  cursor: pointer; text-decoration: none;
  transition: all .2s;
}
.sp-cta-secondary:hover { border-color: ${C.text}; }

.sp-bento {
  background: ${C.bg};
  border: 1px solid ${C.border};
  border-radius: 16px;
  padding: 26px;
  transition: all .35s cubic-bezier(.4,0,.2,1);
  position: relative;
  overflow: hidden;
}
.sp-bento:hover { border-color: ${C.borderHover}; transform: translateY(-2px); box-shadow: 0 12px 32px -16px rgba(15,23,42,.12); }
.sp-bento-dark { background: ${C.ink}; color: white; border-color: ${C.ink}; }
.sp-bento-dark:hover { border-color: ${C.brand}; box-shadow: 0 20px 60px -20px ${C.brand}88; }

.sp-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 11px; border-radius: 999px;
  background: ${C.bgSubtle}; color: ${C.text};
  font-size: 11.5px; font-weight: 600;
  border: 1px solid ${C.border};
  letter-spacing: 0.02em;
}

.sp-pill-accent {
  background: ${C.brand}11; color: ${C.brand};
  border-color: ${C.brand}33;
}

.sp-link { color: ${C.textSecondary}; text-decoration: none; transition: color .15s; font-size: 14px; font-weight: 500; }
.sp-link:hover { color: ${C.text}; }

.sp-feature-icon {
  width: 44px; height: 44px; border-radius: 10px;
  background: ${C.bgSubtle}; border: 1px solid ${C.border};
  display: grid; place-items: center;
  color: ${C.text}; flex-shrink: 0;
}

.sp-stat-num {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 44px; font-weight: 700;
  letter-spacing: -0.04em; line-height: 1; color: ${C.text};
}

.sp-divider { height: 1px; background: ${C.border}; border: 0; margin: 0; }

.sp-shimmer {
  background-image: linear-gradient(90deg, transparent, ${C.bgSubtle}, transparent);
  background-size: 200% 100%;
  animation: sp-shimmer 2.6s linear infinite;
}

/* Hero blueprint mock */
.sp-blueprint {
  background:
    linear-gradient(${C.ink}, ${C.ink}),
    radial-gradient(circle at 20% 0%, ${C.brand}33, transparent 50%);
  background-blend-mode: overlay;
  background-color: ${C.ink};
}

/* Mobile */
@media (max-width: 768px) {
  .sp-h1 { font-size: 44px !important; line-height: 1.05 !important; }
  .sp-h2 { font-size: 32px !important; }
  .sp-hero-grid { grid-template-columns: 1fr !important; }
  .sp-bento-grid { grid-template-columns: 1fr !important; }
  .sp-features-grid { grid-template-columns: 1fr !important; }
  .sp-nav-links { display: none !important; }
  .sp-stat-num { font-size: 32px !important; }
  .sp-section { padding: 60px 22px !important; }
}
`;

// ============================================================
// Icones (sem dependência externa de SVG sprite)
// ============================================================
const Ico = {
  ArrowRight: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
  ),
  Check: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M20 6L9 17l-5-5"/></svg>
  ),
  Antenna: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4l14 14M19 4l-14 14M12 9v13M9 22h6"/><circle cx="12" cy="9" r="1.4" fill="currentColor"/></svg>
  ),
  Network: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="9" width="6" height="6" rx="1"/><rect x="15" y="9" width="6" height="6" rx="1"/><rect x="9" y="3" width="6" height="6" rx="1"/><rect x="9" y="15" width="6" height="6" rx="1"/><path d="M12 9V6M12 18v-3M9 12H6M18 12h-3"/></svg>
  ),
  Chat: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/></svg>
  ),
  Kanban: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="6" height="14" rx="1"/><rect x="15" y="3" width="6" height="10" rx="1"/><rect x="9" y="3" width="6" height="18" rx="1" fill="currentColor" fillOpacity="0.1"/></svg>
  ),
  Brain: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9.5 2A2.5 2.5 0 0 0 7 4.5v0A2.5 2.5 0 0 0 4.5 7v0A2.5 2.5 0 0 0 4.5 12v0A2.5 2.5 0 0 0 7 14.5v3a2.5 2.5 0 0 0 5 0V4.5A2.5 2.5 0 0 0 9.5 2z"/><path d="M14.5 2A2.5 2.5 0 0 1 17 4.5v0A2.5 2.5 0 0 1 19.5 7v0A2.5 2.5 0 0 1 19.5 12v0A2.5 2.5 0 0 1 17 14.5v3a2.5 2.5 0 0 1-5 0V4.5A2.5 2.5 0 0 1 14.5 2z"/></svg>
  ),
  Shield: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2L4 6v6c0 5 3.5 9 8 10 4.5-1 8-5 8-10V6l-8-4z"/><path d="M9 12l2 2 4-4"/></svg>
  ),
  Lightning: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></svg>
  ),
  Globe: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a14 14 0 0 1 0 20M12 2a14 14 0 0 0 0 20"/></svg>
  ),
  Map: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M1 6l8-3 6 3 8-3v15l-8 3-6-3-8 3z"/><path d="M9 3v15M15 6v15"/></svg>
  ),
  Phone: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .3 1.9.6 2.8a2 2 0 0 1-.4 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.5 2.8.6a2 2 0 0 1 1.7 2z"/></svg>
  ),
};

// ============================================================
// Componentes
// ============================================================
function Logo({ size = 22, dark = false }) {
  return (
    <span data-testid="brand-logo" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span style={{
        width: size + 6, height: size + 6, borderRadius: 7,
        background: dark ? "white" : C.ink,
        color: dark ? C.ink : "white",
        display: "grid", placeItems: "center",
        fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 13,
        letterSpacing: "-0.04em",
      }}>S</span>
      <span className="sp-display" style={{
        fontSize: size, color: dark ? "white" : C.text, lineHeight: 1,
        display: "inline-flex", alignItems: "baseline",
      }}>
        Smart<span style={{ color: dark ? C.accent : C.brand, fontWeight: 700 }}>Prov</span>
      </span>
    </span>
  );
}

function Nav({ onLogin, onSignup }) {
  return (
    <header style={{
      position: "sticky", top: 0, zIndex: 50,
      background: "rgba(255,255,255,.85)",
      backdropFilter: "blur(12px)",
      borderBottom: `1px solid ${C.border}`,
    }}>
      <div style={{
        maxWidth: 1280, margin: "0 auto",
        padding: "14px 28px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <Logo />
        <nav className="sp-nav-links" style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <a className="sp-link" href="#produto">Produto</a>
          <a className="sp-link" href="#modulos">Módulos</a>
          <a className="sp-link" href="#precos">Preços</a>
          <a className="sp-link" href="#contato">Contato</a>
        </nav>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            data-testid="nav-login-btn"
            onClick={onLogin}
            style={{ background: "transparent", border: 0, color: C.text, fontSize: 14, fontWeight: 600, cursor: "pointer", padding: "8px 14px" }}
          >Entrar</button>
          <button
            data-testid="nav-signup-btn"
            onClick={() => onSignup({ plan: "trial" })}
            className="sp-cta-primary"
            style={{ padding: "9px 18px", fontSize: 13.5 }}
          >Começar grátis <Ico.ArrowRight /></button>
        </div>
      </div>
    </header>
  );
}

function Hero({ onSignup }) {
  return (
    <section style={{ position: "relative", overflow: "hidden", padding: "100px 28px 80px" }}>
      <div className="sp-grid-bg" style={{ position: "absolute", inset: 0, opacity: 0.4 }} />
      <div style={{ position: "relative", maxWidth: 1280, margin: "0 auto" }}>
        <div className="sp-hero-grid" style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: 60, alignItems: "center" }}>
          <div className="sp-fade-up">
            <div className="sp-pill sp-pill-accent" style={{ marginBottom: 24 }} data-testid="hero-badge">
              <span style={{ width: 6, height: 6, borderRadius: 999, background: C.brand, animation: "sp-pulse 1.8s infinite" }} />
              Plataforma ISP 2026
            </div>
            <h1 className="sp-display sp-h1" style={{
              fontSize: 64, lineHeight: 1.02, margin: "0 0 22px",
              fontWeight: 600, letterSpacing: "-0.035em", color: C.text,
            }}>
              Seu provedor<br/>de internet<br/>
              <span style={{ color: C.brand }}>operado por IA.</span>
            </h1>
            <p style={{ fontSize: 18, lineHeight: 1.55, color: C.textSecondary, margin: "0 0 32px", maxWidth: 540 }}>
              SmartProv reúne lousa de campo, omnichannel WhatsApp, observabilidade de rede óptica e uma camada de inteligência artificial que aprende com seu time — em um sistema só.
            </p>
            <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              <button
                data-testid="hero-signup-btn"
                onClick={() => onSignup({ plan: "trial" })}
                className="sp-cta-primary"
              >Começar teste gratuito <Ico.ArrowRight /></button>
              <a href="#produto" className="sp-cta-secondary">Ver produto</a>
              <a
                href="/preview"
                data-testid="hero-demo-link"
                style={{ color: C.textMuted, fontSize: 13, fontWeight: 500, textDecoration: "underline", textDecorationColor: C.border, textUnderlineOffset: 4 }}
              >Acessar demo</a>
            </div>
            <div style={{ marginTop: 36, display: "flex", gap: 28, color: C.textMuted, fontSize: 13 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><Ico.Check /> 14 dias grátis</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><Ico.Check /> Sem cartão</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><Ico.Check /> Suporte humano</span>
            </div>
          </div>
          <HeroBlueprint />
        </div>
      </div>
    </section>
  );
}

function HeroBlueprint() {
  return (
    <div className="sp-fade-up" style={{ position: "relative", animationDelay: "150ms" }}>
      <div className="sp-bento sp-bento-dark sp-blueprint" style={{
        padding: 0, borderRadius: 18, overflow: "hidden",
        boxShadow: "0 40px 80px -30px rgba(0,85,255,.4)",
      }}>
        {/* Window chrome */}
        <div style={{ padding: "12px 18px", borderBottom: "1px solid rgba(255,255,255,.08)", display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ width: 10, height: 10, borderRadius: 999, background: "#EF4444" }}/>
          <span style={{ width: 10, height: 10, borderRadius: 999, background: "#F59E0B" }}/>
          <span style={{ width: 10, height: 10, borderRadius: 999, background: "#10B981" }}/>
          <span className="sp-mono" style={{ marginLeft: 12, fontSize: 11, color: "rgba(255,255,255,.45)" }}>app.smartprov.com.br/dashboard</span>
        </div>
        {/* Body — dashboard mockup */}
        <div style={{ padding: 22, display: "grid", gap: 14 }}>
          {/* KPIs */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            {[
              { label: "ONUs online", val: "1.690", sub: "+ 12 hoje" },
              { label: "Tickets ativos", val: "23", sub: "SLA OK" },
              { label: "Churn 30d", val: "0,4%", sub: "↓ 0,2 p.p." },
            ].map((k, i) => (
              <div key={i} style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, padding: 14 }}>
                <div className="sp-mono" style={{ fontSize: 10, color: "rgba(255,255,255,.5)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>{k.label}</div>
                <div className="sp-display" style={{ fontSize: 22, fontWeight: 600, color: "white", lineHeight: 1 }}>{k.val}</div>
                <div style={{ fontSize: 11, color: C.success, marginTop: 4 }}>{k.sub}</div>
              </div>
            ))}
          </div>
          {/* Graph mock */}
          <div style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, padding: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontSize: 12, color: "rgba(255,255,255,.7)", fontWeight: 600 }}>Tráfego de rede (24h)</span>
              <span className="sp-pill" style={{ background: "rgba(16,185,129,.15)", border: "1px solid rgba(16,185,129,.3)", color: "#34d399", fontSize: 10 }}>● Online</span>
            </div>
            <svg width="100%" height="80" viewBox="0 0 280 80" preserveAspectRatio="none" style={{ display: "block" }}>
              <defs>
                <linearGradient id="grad" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor={C.brand} stopOpacity="0.4"/>
                  <stop offset="100%" stopColor={C.brand} stopOpacity="0"/>
                </linearGradient>
              </defs>
              <path d="M0 60 L20 55 L40 50 L60 56 L80 42 L100 38 L120 44 L140 30 L160 20 L180 28 L200 18 L220 22 L240 14 L260 18 L280 12 L280 80 L0 80 Z" fill="url(#grad)"/>
              <path d="M0 60 L20 55 L40 50 L60 56 L80 42 L100 38 L120 44 L140 30 L160 20 L180 28 L200 18 L220 22 L240 14 L260 18 L280 12" fill="none" stroke={C.brand} strokeWidth="2"/>
            </svg>
          </div>
          {/* Ticket strip */}
          <div style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, padding: 12, display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ width: 8, height: 8, borderRadius: 999, background: C.warning, animation: "sp-pulse 1.5s infinite" }}/>
            <div style={{ flex: 1, fontSize: 12, color: "rgba(255,255,255,.85)" }}>
              <strong>Pane detectada</strong> — OLT-CENTRO-01 | 14 ONUs afetadas
            </div>
            <span className="sp-mono" style={{ fontSize: 10, color: "rgba(255,255,255,.5)" }}>há 2 min</span>
          </div>
        </div>
      </div>
      {/* floating mini-card */}
      <div className="sp-bento" style={{
        position: "absolute", bottom: -32, left: -32,
        padding: 16, width: 220,
        boxShadow: "0 20px 50px -10px rgba(15,23,42,.18)",
      }}>
        <div className="sp-mono" style={{ fontSize: 9.5, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 6 }}>Secretária Ligo (IA)</div>
        <div style={{ fontSize: 13, color: C.text, lineHeight: 1.45 }}>
          <strong>Você tem 2 clientes ativos.</strong> Eddy fechou 5 chamados hoje.
        </div>
      </div>
    </div>
  );
}

function LogoStrip() {
  return (
    <section style={{ borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`, padding: "32px 28px", background: C.bgMuted }}>
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <p className="sp-mono" style={{ textAlign: "center", margin: 0, fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".15em", marginBottom: 18 }}>
          Provedores que já operam com tecnologia SmartProv
        </p>
        <div style={{ display: "flex", justifyContent: "center", gap: 44, flexWrap: "wrap", opacity: 0.55 }}>
          {["LigoFibra", "VeloNet", "FibraNet", "TecnoLink", "SkyTelecom", "OpticFlow"].map((name) => (
            <span key={name} className="sp-display" style={{ fontSize: 18, color: C.textSecondary, fontWeight: 500 }}>{name}</span>
          ))}
        </div>
      </div>
    </section>
  );
}

function StatsSection() {
  const stats = [
    { num: "+38%", label: "Aumento médio na produtividade do campo", note: "vs. operação anterior" },
    { num: "12 min", label: "Tempo médio de resposta no WhatsApp", note: "com Co-Pilot IA" },
    { num: "0,4%", label: "Churn mensal médio", note: "abaixo da média do setor" },
    { num: "99,8%", label: "Uptime monitorado da rede óptica", note: "alertas em < 30s" },
  ];
  return (
    <section style={{ padding: "80px 28px" }} className="sp-section">
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 0, borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}` }} className="sp-bento-grid">
          {stats.map((s, i) => (
            <div key={i} className="sp-fade-up" style={{
              padding: "32px 28px",
              borderRight: i < stats.length - 1 ? `1px solid ${C.border}` : "none",
              animationDelay: `${i * 80}ms`,
            }}>
              <div className="sp-stat-num">{s.num}</div>
              <div style={{ fontSize: 14, color: C.text, fontWeight: 600, marginTop: 12, lineHeight: 1.4 }}>{s.label}</div>
              <div className="sp-mono" style={{ fontSize: 11, color: C.textMuted, marginTop: 6, textTransform: "uppercase", letterSpacing: ".06em" }}>{s.note}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ModulesSection() {
  const modules = [
    {
      icon: <Ico.Kanban />, title: "Lousa de Campo (Kanban)",
      desc: "Distribua chamados por técnico, acompanhe SLA em tempo real e visualize onde cada equipe está agora.",
      bullets: ["Drag-and-drop", "Geolocalização integrada", "SLA com alertas"],
    },
    {
      icon: <Ico.Chat />, title: "WhatsApp Omnichannel",
      desc: "Centralize conversas, automatize boletos e use o Co-Pilot IA pra sugerir respostas que melhoram o CSAT.",
      bullets: ["Múltiplos atendentes", "Sugestões IA contextuais", "Histórico unificado"],
    },
    {
      icon: <Ico.Network />, title: "SmartOLT",
      desc: "Observabilidade total da rede óptica. Detecta panes, gera ordens preventivas e calcula impacto financeiro.",
      bullets: ["Suporte multi-vendor", "Alarmes em < 30s", "Impacto MRR projetado"],
    },
    {
      icon: <Ico.Brain />, title: "Motor IA Centralizado",
      desc: "Claude Sonnet 4.5 orquestrando agentes especializados em triagem, atendimento, churn e suporte técnico.",
      bullets: ["Kill-switch global", "Custo monitorado", "Audit log completo"],
    },
    {
      icon: <Ico.Phone />, title: "Softphone SIP",
      desc: "Receba e faça chamadas direto do navegador, integrado ao seu MagnusBilling. Sem app extra.",
      bullets: ["WebRTC nativo", "CDR no histórico", "Click-to-call"],
    },
    {
      icon: <Ico.Shield />, title: "Secretária Ligo",
      desc: "Sua IA executiva. Responde KPIs por WhatsApp ou ChatGPT customizado, faz backup automático na nuvem.",
      bullets: ["28 ferramentas read-only", "Backup Drive diário", "Tool-use Claude"],
    },
  ];
  return (
    <section id="modulos" style={{ padding: "100px 28px", background: C.bgMuted }} className="sp-section">
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ maxWidth: 720, marginBottom: 56 }}>
          <span className="sp-pill" style={{ marginBottom: 16 }}>Módulos</span>
          <h2 className="sp-display sp-h2" style={{ fontSize: 48, lineHeight: 1.05, margin: "0 0 14px", letterSpacing: "-0.035em" }}>
            Tudo o que um provedor precisa.<br/>
            <span style={{ color: C.textSecondary }}>Em um sistema só.</span>
          </h2>
          <p style={{ fontSize: 17, color: C.textSecondary, lineHeight: 1.55, margin: 0 }}>
            Construído por gente que conhece ISP. Sem patchworks de planilha, sem 5 sistemas pra abrir.
          </p>
        </div>
        <div className="sp-features-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
          {modules.map((m, i) => (
            <div key={m.title} className="sp-bento sp-fade-up" data-testid={`module-${i}`} style={{ animationDelay: `${i * 60}ms` }}>
              <div className="sp-feature-icon" style={{ marginBottom: 16 }}>{m.icon}</div>
              <h3 className="sp-display" style={{ fontSize: 20, fontWeight: 600, margin: "0 0 10px", letterSpacing: "-0.02em" }}>{m.title}</h3>
              <p style={{ fontSize: 14, color: C.textSecondary, lineHeight: 1.55, margin: "0 0 16px" }}>{m.desc}</p>
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                {m.bullets.map((b) => (
                  <li key={b} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: C.text }}>
                    <span style={{ color: C.brand }}><Ico.Check /></span>{b}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    { num: "01", title: "Importe seu provedor", desc: "Conecte Atlaz, SmartOLT, MagnusBilling — em minutos seus 1.700 clientes aparecem automaticamente." },
    { num: "02", title: "Configure os agentes IA", desc: "Ative Triagem, Co-Pilot, Sentinela e Secretária Ligo. Defina budget e kill-switch por agente." },
    { num: "03", title: "Opere com inteligência", desc: "Veja em tempo real: técnicos no campo, atendimentos por IA, panes detectadas, churn previsto." },
  ];
  return (
    <section id="produto" style={{ padding: "100px 28px" }} className="sp-section">
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "0.8fr 1.2fr", gap: 60, alignItems: "start" }} className="sp-hero-grid">
          <div>
            <span className="sp-pill" style={{ marginBottom: 16 }}>Como funciona</span>
            <h2 className="sp-display sp-h2" style={{ fontSize: 48, lineHeight: 1.05, margin: "0 0 18px", letterSpacing: "-0.035em" }}>
              Do importer<br/>ao operacional<br/>
              <span style={{ color: C.brand }}>em 24h.</span>
            </h2>
            <p style={{ fontSize: 16, color: C.textSecondary, lineHeight: 1.55 }}>
              A maioria dos clientes está com a operação rodando dentro de 1 dia. Sem onboarding meses, sem TI dedicada.
            </p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            {steps.map((s, i) => (
              <div key={s.num} className="sp-fade-up" style={{ display: "flex", gap: 24, padding: "24px 0", borderBottom: i < 2 ? `1px solid ${C.border}` : "none", animationDelay: `${i * 100}ms` }}>
                <div className="sp-mono" style={{ fontSize: 13, color: C.brand, fontWeight: 700, letterSpacing: ".1em", flexShrink: 0, paddingTop: 4 }}>{s.num}</div>
                <div>
                  <h3 className="sp-display" style={{ fontSize: 22, fontWeight: 600, margin: "0 0 8px", letterSpacing: "-0.02em" }}>{s.title}</h3>
                  <p style={{ fontSize: 15, color: C.textSecondary, lineHeight: 1.55, margin: 0 }}>{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Pricing({ onSignup }) {
  const plans = [
    {
      name: "Starter", price: "R$ 297", period: "/mês",
      desc: "Até 500 clientes ativos. Ideal para começar.",
      bullets: ["Até 500 assinantes", "Lousa + WhatsApp", "1 OLT integrada", "Suporte por chat"],
      cta: "Começar grátis",
      featured: false,
    },
    {
      name: "Pro", price: "R$ 697", period: "/mês",
      desc: "O queridinho dos provedores em crescimento.",
      bullets: ["Até 2.500 assinantes", "Motor IA + Co-Pilot", "OLTs ilimitadas", "Secretária Ligo + Drive", "Softphone SIP", "Suporte prioritário"],
      cta: "Começar 14 dias",
      featured: true,
    },
    {
      name: "Enterprise", price: "Custom", period: "",
      desc: "Para operações grandes, multi-cidade.",
      bullets: ["Assinantes ilimitados", "Multi-tenant", "SLA garantido", "API dedicada", "Onboarding presencial", "Customer Success"],
      cta: "Falar com vendas",
      featured: false,
    },
  ];
  return (
    <section id="precos" style={{ padding: "100px 28px", background: C.bgMuted }} className="sp-section">
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ textAlign: "center", maxWidth: 600, margin: "0 auto 56px" }}>
          <span className="sp-pill" style={{ marginBottom: 16 }}>Preços</span>
          <h2 className="sp-display sp-h2" style={{ fontSize: 48, lineHeight: 1.05, margin: "0 0 14px", letterSpacing: "-0.035em" }}>
            Simples. Justo. Honesto.
          </h2>
          <p style={{ fontSize: 17, color: C.textSecondary, lineHeight: 1.55 }}>
            Sem taxa de setup. Sem fidelidade. Sem letrinha miúda.
          </p>
        </div>
        <div className="sp-bento-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18, alignItems: "stretch" }}>
          {plans.map((p, i) => (
            <div key={p.name} className={`sp-bento ${p.featured ? "sp-bento-dark" : ""} sp-fade-up`}
                  data-testid={`plan-${p.name.toLowerCase()}`}
                  style={{
                    padding: 32,
                    animationDelay: `${i * 100}ms`,
                    position: "relative",
                  }}>
              {p.featured && (
                <span style={{
                  position: "absolute", top: -12, right: 32,
                  background: C.brand, color: "white",
                  padding: "4px 12px", borderRadius: 999, fontSize: 11, fontWeight: 700, letterSpacing: ".04em",
                }}>RECOMENDADO</span>
              )}
              <div className="sp-display" style={{ fontSize: 22, fontWeight: 600, marginBottom: 8 }}>{p.name}</div>
              <div style={{ marginBottom: 18 }}>
                <span className="sp-display" style={{ fontSize: 44, fontWeight: 700, letterSpacing: "-0.04em" }}>{p.price}</span>
                <span style={{ fontSize: 15, color: p.featured ? "rgba(255,255,255,.6)" : C.textSecondary, marginLeft: 4 }}>{p.period}</span>
              </div>
              <p style={{ fontSize: 14, color: p.featured ? "rgba(255,255,255,.7)" : C.textSecondary, lineHeight: 1.55, marginBottom: 24 }}>{p.desc}</p>
              <button
                onClick={() => onSignup({ plan: p.name.toLowerCase() })}
                data-testid={`plan-cta-${p.name.toLowerCase()}`}
                style={{
                  width: "100%", padding: "13px 0", borderRadius: 8, fontSize: 14.5, fontWeight: 600, cursor: "pointer",
                  background: p.featured ? C.brand : C.ink,
                  color: "white", border: `1px solid ${p.featured ? C.brand : C.ink}`,
                  marginBottom: 24,
                  transition: "all .2s",
                }}
                onMouseEnter={(e) => e.currentTarget.style.transform = "translateY(-1px)"}
                onMouseLeave={(e) => e.currentTarget.style.transform = "translateY(0)"}
              >{p.cta}</button>
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
                {p.bullets.map((b) => (
                  <li key={b} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13.5, color: p.featured ? "rgba(255,255,255,.85)" : C.text }}>
                    <span style={{ color: p.featured ? C.accent : C.brand }}><Ico.Check /></span>{b}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CtaFinal({ onSignup }) {
  return (
    <section id="contato" style={{ padding: "100px 28px" }} className="sp-section">
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        <div className="sp-bento sp-bento-dark" style={{ padding: "64px 56px", textAlign: "center", borderRadius: 24, position: "relative", overflow: "hidden" }}>
          <div className="sp-grid-bg" style={{ position: "absolute", inset: 0, opacity: 0.15 }} />
          <div style={{ position: "relative" }}>
            <h2 className="sp-display" style={{ fontSize: 48, lineHeight: 1.05, margin: "0 0 18px", fontWeight: 600, letterSpacing: "-0.035em", color: "white" }}>
              Pronto pra operar<br/>com inteligência?
            </h2>
            <p style={{ fontSize: 17, color: "rgba(255,255,255,.7)", lineHeight: 1.55, margin: "0 0 32px", maxWidth: 540, marginLeft: "auto", marginRight: "auto" }}>
              14 dias grátis. Sem cartão. Você ativa, importa seu provedor, e em 24h está rodando.
            </p>
            <div style={{ display: "inline-flex", gap: 12, alignItems: "center", flexWrap: "wrap", justifyContent: "center" }}>
              <button
                onClick={() => onSignup({ plan: "trial" })}
                data-testid="cta-final-signup"
                style={{
                  background: "white", color: C.ink, border: 0,
                  padding: "14px 28px", borderRadius: 8, fontSize: 15, fontWeight: 700,
                  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 8,
                  transition: "all .2s",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = C.accent; e.currentTarget.style.transform = "translateY(-1px)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "white"; e.currentTarget.style.transform = "translateY(0)"; }}
              >Começar agora <Ico.ArrowRight /></button>
              <a href="mailto:contato@smartprov.com.br" style={{ color: "rgba(255,255,255,.85)", textDecoration: "none", fontSize: 14, fontWeight: 600, padding: "14px 20px" }}>
                Falar com vendas →
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer style={{ borderTop: `1px solid ${C.border}`, padding: "48px 28px 32px", background: C.bg }}>
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr", gap: 40, marginBottom: 32 }} className="sp-bento-grid">
          <div>
            <Logo />
            <p style={{ fontSize: 13.5, color: C.textSecondary, lineHeight: 1.55, marginTop: 14, maxWidth: 280 }}>
              A plataforma de gestão pra provedores de internet construída pra escalar.
            </p>
          </div>
          {[
            { title: "Produto", links: ["Módulos", "Preços", "Roadmap", "Changelog"] },
            { title: "Empresa", links: ["Sobre", "Blog", "Carreiras", "Contato"] },
            { title: "Recursos", links: ["Documentação", "API", "Status", "Comunidade"] },
          ].map((col) => (
            <div key={col.title}>
              <div className="sp-mono" style={{ fontSize: 11, color: C.text, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 14 }}>{col.title}</div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
                {col.links.map((l) => (
                  <li key={l}><a className="sp-link" href="#" style={{ fontSize: 14 }}>{l}</a></li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <hr className="sp-divider" />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 24, fontSize: 13, color: C.textMuted, flexWrap: "wrap", gap: 10 }}>
          <span>© {new Date().getFullYear()} SmartProv. Construído no Brasil.</span>
          <div style={{ display: "flex", gap: 22 }}>
            <a className="sp-link" href="#" style={{ fontSize: 13 }}>Privacidade</a>
            <a className="sp-link" href="#" style={{ fontSize: 13 }}>Termos</a>
            <a className="sp-link" href="#" style={{ fontSize: 13 }}>Segurança</a>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ============================================================
// Landing page
// ============================================================
export default function LandingPage({ onLogin, onSignup }) {
  useEffect(() => {
    if (!document.getElementById("smartprov-landing-css")) {
      const s = document.createElement("style");
      s.id = "smartprov-landing-css";
      s.textContent = css;
      document.head.appendChild(s);
    }
    document.title = "SmartProv — A plataforma do seu provedor";
  }, []);

  return (
    <div className="sp-page" data-testid="landing-page">
      <Nav onLogin={onLogin} onSignup={onSignup} />
      <Hero onSignup={onSignup} />
      <LogoStrip />
      <StatsSection />
      <ModulesSection />
      <HowItWorks />
      <Pricing onSignup={onSignup} />
      <CtaFinal onSignup={onSignup} />
      <Footer />
    </div>
  );
}
