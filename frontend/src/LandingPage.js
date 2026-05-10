import React, { useEffect, useState } from "react";

const ACCENT = "#10b981"; // verde-vivo (associa "ponto válido")
const BG_DARK = "#0a1322";
const BG_DARKER = "#050b16";

const css = `
  @keyframes pi-fadeUp { from { opacity: 0; transform: translateY(24px); } to { opacity: 1; transform: translateY(0); } }
  @keyframes pi-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,.55); } 50% { box-shadow: 0 0 0 18px rgba(16,185,129,0); } }
  @keyframes pi-shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
  .pi-fadeUp { opacity: 0; animation: pi-fadeUp .9s cubic-bezier(.2,.8,.2,1) forwards; }
  .pi-grain {
    background-image: radial-gradient(rgba(255,255,255,.03) 1px, transparent 1px);
    background-size: 3px 3px;
  }
  .pi-card-hover { transition: transform .35s cubic-bezier(.2,.8,.2,1), border-color .35s; }
  .pi-card-hover:hover { transform: translateY(-6px); border-color: rgba(16,185,129,.45); }
  .pi-cta { transition: transform .25s, box-shadow .25s, background .25s; }
  .pi-cta:hover { transform: translateY(-2px); box-shadow: 0 18px 40px rgba(16,185,129,.35); }
  .pi-link { transition: color .2s; }
  .pi-link:hover { color: #10b981; }
  .pi-shine {
    background: linear-gradient(90deg, transparent, rgba(255,255,255,.08), transparent);
    background-size: 200% 100%;
    animation: pi-shimmer 2.5s linear infinite;
  }
  @media (max-width: 720px) {
    .pi-h1 { font-size: 38px !important; line-height: 1.05 !important; }
    .pi-hero-grid { grid-template-columns: 1fr !important; gap: 24px !important; }
    .pi-features-grid { grid-template-columns: 1fr !important; }
    .pi-nav-actions { display: none !important; }
  }
`;

function PIcon({ name }) {
  const map = {
    selfie: "📸",
    map: "📍",
    bolt: "⚡",
    shield: "🛡️",
    chart: "📊",
    bell: "🔔",
    cloud: "☁️",
    sparkle: "✨",
    check: "✓",
  };
  return <span aria-hidden style={{ fontSize: "inherit" }}>{map[name] || "•"}</span>;
}

function FeatureCard({ icon, title, desc, delay = 0 }) {
  return (
    <div
      className="pi-card-hover pi-fadeUp"
      style={{
        background: "rgba(255,255,255,.03)",
        border: "1px solid rgba(255,255,255,.08)",
        borderRadius: 18,
        padding: "26px 22px",
        backdropFilter: "blur(8px)",
        animationDelay: `${delay}ms`,
      }}
    >
      <div style={{
        width: 46, height: 46, borderRadius: 12,
        background: "linear-gradient(135deg, rgba(16,185,129,.18), rgba(16,185,129,.06))",
        border: "1px solid rgba(16,185,129,.25)",
        display: "grid", placeItems: "center", fontSize: 22, marginBottom: 14,
      }}><PIcon name={icon} /></div>
      <h3 style={{ margin: "0 0 8px", color: "#f1f5f9", fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em" }}>{title}</h3>
      <p style={{ margin: 0, color: "#94a3b8", fontSize: 13.5, lineHeight: 1.6 }}>{desc}</p>
    </div>
  );
}

function StepCard({ n, title, desc, delay = 0 }) {
  return (
    <div className="pi-fadeUp" style={{ display: "flex", gap: 18, alignItems: "flex-start", animationDelay: `${delay}ms` }}>
      <div style={{
        flexShrink: 0, width: 44, height: 44, borderRadius: 12,
        background: "linear-gradient(135deg,#10b981,#059669)",
        color: "white", fontWeight: 900, display: "grid", placeItems: "center",
        fontSize: 17, boxShadow: "0 10px 24px rgba(16,185,129,.3)",
      }}>{n}</div>
      <div>
        <h4 style={{ margin: "4px 0 6px", color: "#f1f5f9", fontSize: 15.5, fontWeight: 700 }}>{title}</h4>
        <p style={{ margin: 0, color: "#94a3b8", fontSize: 13.5, lineHeight: 1.6 }}>{desc}</p>
      </div>
    </div>
  );
}

function PriceCheck({ children }) {
  return (
    <li style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0", color: "#cbd5e1", fontSize: 14 }}>
      <span style={{
        flexShrink: 0, width: 20, height: 20, borderRadius: "50%",
        background: "rgba(16,185,129,.15)", color: ACCENT,
        display: "grid", placeItems: "center", fontSize: 12, fontWeight: 900,
        marginTop: 1,
      }}>✓</span>
      <span>{children}</span>
    </li>
  );
}

export default function LandingPage({ onSignup, onLogin }) {
  // smooth scroll para a âncora #pricing etc.
  useEffect(() => {
    const handler = (e) => {
      const a = e.target.closest("a[href^='#']");
      if (a) {
        const id = a.getAttribute("href").slice(1);
        const el = document.getElementById(id);
        if (el) {
          e.preventDefault();
          el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }
    };
    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, []);

  return (
    <div data-testid="landing-page" style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse 80% 60% at 50% -20%, rgba(16,185,129,.15) 0%, ${BG_DARK} 55%, ${BG_DARKER} 100%)`,
      color: "#e2e8f0",
      fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
      letterSpacing: "-0.01em",
    }}>
      <style>{css}</style>
      <div className="pi-grain" style={{ position: "fixed", inset: 0, pointerEvents: "none", opacity: 0.4 }} />

      {/* Nav */}
      <nav style={{
        position: "sticky", top: 0, zIndex: 50,
        background: "rgba(10,19,34,.7)", backdropFilter: "blur(14px)",
        borderBottom: "1px solid rgba(255,255,255,.06)",
        padding: "14px 28px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }} data-testid="brand-logo">
          <div style={{
            width: 34, height: 34, borderRadius: 10,
            background: "linear-gradient(135deg,#10b981,#059669)",
            display: "grid", placeItems: "center", fontSize: 18,
            boxShadow: "0 8px 18px rgba(16,185,129,.3)",
          }}>📍</div>
          <strong style={{ color: "white", fontSize: 18, letterSpacing: "-0.02em" }}>PontoIA</strong>
        </div>
        <div className="pi-nav-actions" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <a href="#features" className="pi-link" style={{ color: "#cbd5e1", textDecoration: "none", fontSize: 14, padding: "8px 14px" }}>Recursos</a>
          <a href="#how" className="pi-link" style={{ color: "#cbd5e1", textDecoration: "none", fontSize: 14, padding: "8px 14px" }}>Como funciona</a>
          <a href="#pricing" className="pi-link" style={{ color: "#cbd5e1", textDecoration: "none", fontSize: 14, padding: "8px 14px" }}>Preço</a>
          <button
            onClick={onLogin}
            data-testid="nav-login-btn"
            style={{
              background: "transparent", border: "1px solid rgba(255,255,255,.15)",
              color: "white", padding: "8px 18px", borderRadius: 999, fontSize: 13.5,
              fontWeight: 600, cursor: "pointer",
            }}
          >Entrar</button>
          <button
            onClick={() => onSignup({ plan: "trial" })}
            data-testid="nav-signup-btn"
            className="pi-cta"
            style={{
              background: ACCENT, color: BG_DARKER, border: 0,
              padding: "9px 20px", borderRadius: 999, fontSize: 13.5,
              fontWeight: 800, cursor: "pointer",
            }}
          >Começar grátis</button>
        </div>
      </nav>

      {/* Hero */}
      <section style={{ padding: "80px 28px 60px", maxWidth: 1240, margin: "0 auto" }}>
        <div className="pi-hero-grid" style={{ display: "grid", gridTemplateColumns: "1.15fr 0.85fr", gap: 60, alignItems: "center" }}>
          <div className="pi-fadeUp">
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "6px 14px", borderRadius: 999,
              background: "rgba(16,185,129,.1)", border: "1px solid rgba(16,185,129,.25)",
              color: "#34d399", fontSize: 12, fontWeight: 700, marginBottom: 24,
            }} data-testid="hero-badge">
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: ACCENT, animation: "pi-pulse 2s infinite" }}></span>
              Trial de 14 dias · Sem cartão de crédito
            </div>
            <h1 className="pi-h1" data-testid="hero-title" style={{
              margin: 0, fontSize: 64, lineHeight: 1.02, letterSpacing: "-0.04em",
              fontWeight: 850, color: "white",
            }}>
              Ponto eletrônico<br />
              com <span style={{
                background: "linear-gradient(135deg,#10b981 30%,#34d399 70%)",
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
              }}>IA de validação facial</span>.
            </h1>
            <p style={{ marginTop: 24, color: "#94a3b8", fontSize: 18, lineHeight: 1.55, maxWidth: 540 }}>
              Selfie automática, cerca virtual por GPS, espelho mensal pronto para o RH. Zero fraude.
              Para equipes de campo que precisam de <strong style={{ color: "#cbd5e1" }}>controle real</strong> sem complicação.
            </p>
            <div style={{ marginTop: 36, display: "flex", gap: 14, flexWrap: "wrap" }}>
              <button
                onClick={() => onSignup({ plan: "trial" })}
                data-testid="hero-cta-signup"
                className="pi-cta"
                style={{
                  background: ACCENT, color: BG_DARKER, border: 0,
                  padding: "16px 28px", borderRadius: 14, fontSize: 15,
                  fontWeight: 800, cursor: "pointer",
                  boxShadow: "0 14px 30px rgba(16,185,129,.35)",
                }}
              >Começar trial grátis →</button>
              <a
                href="#how"
                data-testid="hero-cta-demo"
                style={{
                  background: "rgba(255,255,255,.06)",
                  color: "white", padding: "16px 24px", borderRadius: 14,
                  fontSize: 15, fontWeight: 600, textDecoration: "none",
                  border: "1px solid rgba(255,255,255,.12)",
                }}
              >Ver como funciona</a>
            </div>
            <div style={{ marginTop: 38, display: "flex", gap: 28, color: "#64748b", fontSize: 13, flexWrap: "wrap" }}>
              <span><PIcon name="check" /> Setup em 5 minutos</span>
              <span><PIcon name="check" /> 14 dias para testar</span>
              <span><PIcon name="check" /> Cancele a qualquer momento</span>
            </div>
          </div>

          {/* Mock visual do app */}
          <div className="pi-fadeUp" style={{ animationDelay: "200ms", position: "relative" }}>
            <div style={{
              position: "relative", margin: "0 auto",
              width: 290, padding: 14, borderRadius: 38,
              background: "linear-gradient(135deg,#1e293b,#0f172a)",
              border: "1px solid rgba(255,255,255,.1)",
              boxShadow: "0 30px 80px rgba(0,0,0,.6), inset 0 0 0 1px rgba(16,185,129,.1)",
            }}>
              <div style={{ background: "#020617", borderRadius: 26, padding: 18, color: "white" }}>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>Olá</div>
                <strong style={{ fontSize: 17 }}>Maria Silva</strong>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>Coordenadora de campo</div>

                <div style={{
                  marginTop: 18, padding: 16, borderRadius: 18,
                  background: "linear-gradient(135deg,#0f172a,#1e293b)",
                  border: "1px solid rgba(16,185,129,.15)",
                }}>
                  <div style={{ fontSize: 10, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em" }}>Próximo</div>
                  <div style={{ fontSize: 26, fontWeight: 900, marginTop: 4 }}>Entrada</div>
                  <div style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>2 registros hoje · Praça SP/SP</div>
                </div>

                <button style={{
                  width: "100%", marginTop: 14, height: 56, borderRadius: 28,
                  background: ACCENT, color: BG_DARKER, border: 0,
                  fontSize: 15, fontWeight: 900, animation: "pi-pulse 2.4s infinite",
                  cursor: "default",
                }}>📸 Bater Ponto</button>

                <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                  {["Entrada 08:02", "Saída"].map((s, i) => (
                    <div key={i} style={{
                      flex: 1, padding: "8px 10px", borderRadius: 10,
                      background: i === 0 ? "rgba(16,185,129,.1)" : "rgba(255,255,255,.04)",
                      fontSize: 10, color: i === 0 ? "#34d399" : "#64748b",
                    }}>{s}</div>
                  ))}
                </div>
              </div>
            </div>

            {/* Floating chips */}
            <div className="pi-fadeUp" style={{
              position: "absolute", top: 30, right: -20, animationDelay: "600ms",
              background: "rgba(255,255,255,.06)", backdropFilter: "blur(12px)",
              border: "1px solid rgba(255,255,255,.1)", borderRadius: 14,
              padding: "10px 14px", fontSize: 12, color: "white",
              boxShadow: "0 12px 30px rgba(0,0,0,.3)",
            }}>
              <span style={{ color: "#34d399", fontSize: 14, marginRight: 6 }}>✓</span>
              Rosto validado
            </div>
            <div className="pi-fadeUp" style={{
              position: "absolute", bottom: 80, left: -28, animationDelay: "800ms",
              background: "rgba(255,255,255,.06)", backdropFilter: "blur(12px)",
              border: "1px solid rgba(255,255,255,.1)", borderRadius: 14,
              padding: "10px 14px", fontSize: 12, color: "white",
              boxShadow: "0 12px 30px rgba(0,0,0,.3)",
            }}>
              📍 Dentro da cerca
            </div>
          </div>
        </div>
      </section>

      {/* Trust bar */}
      <section style={{ padding: "20px 28px 60px", maxWidth: 1100, margin: "0 auto", textAlign: "center" }}>
        <div style={{ color: "#475569", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.18em", marginBottom: 16 }}>
          Construído com tecnologia que você já usa
        </div>
        <div style={{ display: "flex", gap: 32, justifyContent: "center", flexWrap: "wrap", color: "#64748b", fontSize: 13, fontWeight: 600 }}>
          <span>OpenAI Vision</span>
          <span>·</span>
          <span>Resend</span>
          <span>·</span>
          <span>Stripe</span>
          <span>·</span>
          <span>OpenStreetMap</span>
          <span>·</span>
          <span>BrasilAPI</span>
        </div>
      </section>

      {/* Features */}
      <section id="features" style={{ padding: "60px 28px", maxWidth: 1240, margin: "0 auto" }}>
        <div style={{ textAlign: "center", maxWidth: 680, margin: "0 auto 50px" }}>
          <h2 style={{ margin: 0, color: "white", fontSize: 38, fontWeight: 800, letterSpacing: "-0.02em" }}>
            Tudo que o RH precisa.<br />Nada que o gestor não use.
          </h2>
          <p style={{ marginTop: 14, color: "#94a3b8", fontSize: 16 }}>
            Pensado para operações de campo: motorista, técnico, vendedor, agente. Funciona offline, valida com IA e sincroniza ao reconectar.
          </p>
        </div>
        <div className="pi-features-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
          <FeatureCard icon="selfie" title="Selfie automática + IA" desc="GPT-4o Vision verifica que o rosto está visível e compara com a foto de cadastro. Anti-fraude em tempo real." delay={0} />
          <FeatureCard icon="map" title="Cerca virtual por colaborador" desc="Defina um raio (15m padrão) ao redor de uma rota ou ponto de operação. Fora da cerca = bloqueado." delay={100} />
          <FeatureCard icon="bolt" title="Funciona offline" desc="Sem sinal? Bate ponto mesmo assim. Sincroniza automaticamente quando o 4G voltar." delay={200} />
          <FeatureCard icon="shield" title="Auditoria e impersonation" desc="Log imutável de cada ação. Auditor pode visualizar como gestor para investigar fraudes." delay={300} />
          <FeatureCard icon="chart" title="Painel executivo" desc="Horas extras, banco de horas, custo projetado em R$, tendência mensal e heatmap de permanência." delay={400} />
          <FeatureCard icon="bell" title="Push em tempo real" desc="Alerta o gestor quando alguém para 30+ min em local errado ou sai da cerca durante expediente." delay={500} />
          <FeatureCard icon="cloud" title="Espelho mensal automático" desc="Todo último dia do mês: PDF gerado, email para o RH e colaborador. Sem clique manual." delay={600} />
          <FeatureCard icon="sparkle" title="IA para feriados" desc="Cadastrou uma cidade nova? A IA descobre os feriados estaduais e municipais para você revisar." delay={700} />
          <FeatureCard icon="map" title="Mapa ao vivo" desc="Veja a posição atual da equipe em campo. Trajeto das últimas 24h. Análise de permanência com IA." delay={800} />
        </div>
      </section>

      {/* How it works */}
      <section id="how" style={{ padding: "100px 28px", background: "rgba(0,0,0,.25)", borderTop: "1px solid rgba(255,255,255,.05)", borderBottom: "1px solid rgba(255,255,255,.05)" }}>
        <div style={{ maxWidth: 980, margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: 56 }}>
            <h2 style={{ margin: 0, color: "white", fontSize: 36, fontWeight: 800, letterSpacing: "-0.02em" }}>Em 5 minutos sua equipe está marcando ponto.</h2>
          </div>
          <div style={{ display: "grid", gap: 32 }}>
            <StepCard n="1" title="Crie sua conta" desc="Trial de 14 dias, sem cartão. Você vira o gestor da sua empresa em 30 segundos." delay={0} />
            <StepCard n="2" title="Cadastre os colaboradores" desc="Nome, CPF, foto de cadastro e o endereço da cerca virtual. A IA descobre os feriados da cidade." delay={150} />
            <StepCard n="3" title="Compartilhe o link do PWA" desc="Cada colaborador acessa pelo celular (iOS/Android). Login Google na 1ª vez vincula o aparelho." delay={300} />
            <StepCard n="4" title="A equipe bate ponto" desc="Selfie automática + GPS + IA validando rosto vs cadastro. Tudo em 8 segundos." delay={450} />
            <StepCard n="5" title="Você só revisa" desc="Painel mostra HE, banco de horas, alertas. Espelho mensal vai por email no último dia." delay={600} />
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" style={{ padding: "100px 28px", maxWidth: 1100, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 50 }}>
          <h2 style={{ margin: 0, color: "white", fontSize: 38, fontWeight: 800, letterSpacing: "-0.02em" }}>Comece grátis. Cresça quando quiser.</h2>
          <p style={{ marginTop: 12, color: "#94a3b8", fontSize: 16 }}>Free pra sempre até 3 colaboradores. Pro com trial de 14 dias.</p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22, maxWidth: 880, margin: "0 auto" }} className="pi-features-grid">
          {/* FREE */}
          <div className="pi-fadeUp" data-testid="pricing-card-free" style={{
            position: "relative",
            background: "rgba(255,255,255,.04)",
            border: "1px solid rgba(255,255,255,.1)",
            borderRadius: 24, padding: "32px 28px",
          }}>
            <div style={{ color: "#cbd5e1", fontSize: 13, fontWeight: 700, letterSpacing: "0.04em" }}>PONTOIA FREE</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 12 }}>
              <span style={{ color: "white", fontSize: 48, fontWeight: 900, letterSpacing: "-0.04em" }}>R$ 0</span>
              <span style={{ color: "#94a3b8", fontSize: 15 }}>/ para sempre</span>
            </div>
            <div style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>Sem cartão · sem expiração</div>
            <ul style={{ listStyle: "none", padding: 0, margin: "26px 0 0" }}>
              <PriceCheck>Até <strong style={{ color: "white" }}>3 colaboradores</strong></PriceCheck>
              <PriceCheck>Selfie + IA de validação facial</PriceCheck>
              <PriceCheck>Cercas virtuais</PriceCheck>
              <PriceCheck>App PWA mobile</PriceCheck>
              <PriceCheck>Painel básico</PriceCheck>
              <PriceCheck>Faça upgrade pra Pro a qualquer momento</PriceCheck>
            </ul>
            <button
              onClick={() => onSignup({ plan: "free" })}
              data-testid="pricing-cta-free"
              className="pi-cta"
              style={{
                width: "100%", marginTop: 28,
                background: "transparent", color: "white",
                border: "1px solid rgba(255,255,255,.25)",
                padding: "14px 18px", borderRadius: 14,
                fontSize: 14, fontWeight: 800, cursor: "pointer",
              }}
            >Começar grátis →</button>
          </div>

          {/* PRO */}
          <div className="pi-fadeUp" data-testid="pricing-card-pro" style={{
            position: "relative",
            background: "linear-gradient(135deg, rgba(16,185,129,.1), rgba(16,185,129,.02))",
            border: "1px solid rgba(16,185,129,.4)",
            borderRadius: 24, padding: "32px 28px",
            boxShadow: "0 30px 80px rgba(16,185,129,.18)",
          }}>
            <div className="pi-shine" style={{ position: "absolute", inset: 0, borderRadius: 24, pointerEvents: "none" }} />
            <div style={{ position: "absolute", top: -14, left: "50%", transform: "translateX(-50%)" }}>
              <span style={{
                background: ACCENT, color: BG_DARKER,
                padding: "5px 14px", borderRadius: 999,
                fontSize: 11, fontWeight: 900, letterSpacing: "0.04em",
                boxShadow: "0 8px 18px rgba(16,185,129,.4)",
              }}>RECOMENDADO</span>
            </div>
            <div style={{ color: "#34d399", fontSize: 13, fontWeight: 700, letterSpacing: "0.04em" }}>PONTOIA PRO</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 12 }}>
              <span style={{ color: "white", fontSize: 48, fontWeight: 900, letterSpacing: "-0.04em" }}>R$ 99</span>
              <span style={{ color: "#94a3b8", fontSize: 15 }}>/ mês</span>
            </div>
            <div style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>14 dias grátis · sem cartão · cancele quando quiser</div>
            <ul style={{ listStyle: "none", padding: 0, margin: "26px 0 0" }}>
              <PriceCheck><strong style={{ color: "white" }}>25 colaboradores</strong> ativos</PriceCheck>
              <PriceCheck>Tudo do Free +</PriceCheck>
              <PriceCheck>Mapa ao vivo + IA de permanência</PriceCheck>
              <PriceCheck>Espelho mensal automático em PDF</PriceCheck>
              <PriceCheck>Push em tempo real + alertas inteligentes</PriceCheck>
              <PriceCheck>Painel executivo + heatmap</PriceCheck>
              <PriceCheck>Auditoria + impersonation</PriceCheck>
            </ul>
            <button
              onClick={() => onSignup({ plan: "trial" })}
              data-testid="pricing-cta-signup"
              className="pi-cta"
              style={{
                width: "100%", marginTop: 28,
                background: ACCENT, color: BG_DARKER, border: 0,
                padding: "14px 18px", borderRadius: 14,
                fontSize: 14, fontWeight: 800, cursor: "pointer",
                boxShadow: "0 14px 30px rgba(16,185,129,.35)",
              }}
            >Iniciar trial de 14 dias →</button>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section style={{
        padding: "80px 28px",
        background: "linear-gradient(135deg, rgba(16,185,129,.1), transparent)",
        borderTop: "1px solid rgba(255,255,255,.05)",
      }}>
        <div style={{ maxWidth: 720, margin: "0 auto", textAlign: "center" }}>
          <h2 style={{ margin: 0, color: "white", fontSize: 36, fontWeight: 800, letterSpacing: "-0.02em" }}>Pronto pra parar de perseguir comprovantes de WhatsApp? </h2>
          <p style={{ marginTop: 16, color: "#94a3b8", fontSize: 16 }}>
            Crie sua conta agora. Em 5 minutos sua equipe pode bater o primeiro ponto.
          </p>
          <button
            onClick={() => onSignup({ plan: "trial" })}
            data-testid="final-cta-signup"
            className="pi-cta"
            style={{
              marginTop: 30,
              background: ACCENT, color: BG_DARKER, border: 0,
              padding: "18px 36px", borderRadius: 14,
              fontSize: 16, fontWeight: 800, cursor: "pointer",
              boxShadow: "0 14px 30px rgba(16,185,129,.35)",
            }}
          >Criar conta grátis →</button>
        </div>
      </section>

      {/* Footer */}
      <footer style={{
        padding: "40px 28px", borderTop: "1px solid rgba(255,255,255,.05)",
        color: "#64748b", fontSize: 13, textAlign: "center",
      }}>
        © {new Date().getFullYear()} PontoIA — Construído para equipes de campo no Brasil.
      </footer>
    </div>
  );
}
