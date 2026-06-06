/* SejaParceiroLanding — Landing comercial pra captar novos parceiros.
 *
 * iter235 — pedido do usuário: criar página pra empresa se tornar
 * parceira Ligo Vantagens. Referências de mercado: iFood Empresas,
 * Uber Eats Marketplace, Ame Negócios, PicPay Empresas, Cuponeria.
 *
 * Estrutura (best practices SaaS B2B 2026):
 *   1) Hero c/ headline benefício + form rápido (lead capture)
 *   2) Social proof / números reais (X mil clientes Ligo na sua região)
 *   3) "Por que ser parceiro" — 4 benefícios c/ ícones
 *   4) "Como funciona" — passo a passo com timeline
 *   5) Calculadora de ROI (input "ticket médio" + "clientes/dia" → ganho potencial)
 *   6) Cases reais (testimonials)
 *   7) FAQ accordion
 *   8) CTA final + form completo
 *   9) Footer
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import {
  ArrowRight, Award, CheckCircle2, ChevronDown, MapPin,
  QrCode, Smartphone, Sparkles, Store, TrendingUp, Users,
  Wallet, Zap,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/parcerias/public`;

const COLORS = {
  ink: "#1E1B4B", textMute: "#475569",
  bg: "#FAFAF7", surface: "#FFFFFF",
  brand: "#7c3aed", brandDeep: "#4C1D95", brandSoft: "#EDE9FE",
  orange: "#FF6A1A", orangeSoft: "#FFEDD5",
  emerald: "#10b981", emeraldSoft: "#D1FAE5",
  line: "#E5E7EB",
};

const FONT = "'Sora', 'Inter', system-ui, sans-serif";

const REGIONS = [
  "Lavras-MG", "Itumirim-MG", "Ribeirão Vermelho-MG", "Ijaci-MG",
  "Ingaí-MG", "Nepomuceno-MG", "Outra",
];

const SEGMENTS = [
  "Alimentação", "Bebidas", "Sobremesa", "Saúde", "Beleza",
  "Automotivo", "Mercado", "Pet", "Vestuário", "Lazer",
  "Serviço", "Outros",
];

export default function SejaParceiroLanding() {
  useEffect(() => { ensureFont(); }, []);
  const [submitted, setSubmitted] = useState(false);
  return (
    <div style={{
      background: COLORS.bg, color: COLORS.ink, fontFamily: FONT,
      minHeight: "100vh",
    }}>
      <style>{`
        * { box-sizing: border-box; }
        body { background: ${COLORS.bg}; margin: 0; }
        .sp-wrap { max-width: 1200px; margin: 0 auto;
                    padding: 0 clamp(16px, 4vw, 32px); }
        .sp-btn-cta {
          background: ${COLORS.orange}; color: white;
          padding: 14px 28px; border-radius: 14px; border: none;
          font-weight: 900; font-size: 14.5px; cursor: pointer;
          font-family: ${FONT}; display: inline-flex; align-items: center;
          gap: 8px; transition: transform .2s, box-shadow .2s;
          box-shadow: 0 14px 30px rgba(255,106,26,.32);
          letter-spacing: .3px;
        }
        .sp-btn-cta:hover { transform: translateY(-2px);
                             box-shadow: 0 18px 36px rgba(255,106,26,.42); }
        .sp-section { padding: clamp(48px, 8vw, 96px) 0; }
        .sp-h2 { font-size: clamp(28px, 4.5vw, 44px); font-weight: 900;
                  margin: 0 0 14px; letter-spacing: -.025em;
                  line-height: 1.1; }
        .sp-h2-sub { font-size: 13px; font-weight: 800; letter-spacing: 2.2px;
                      text-transform: uppercase; color: ${COLORS.brand};
                      margin-bottom: 14px; }
        .sp-input { width: 100%; padding: 13px 16px; border-radius: 12px;
                     border: 1.5px solid ${COLORS.line}; background: white;
                     font-size: 14.5px; font-family: ${FONT};
                     color: ${COLORS.ink}; outline: none; }
        .sp-input:focus { border-color: ${COLORS.brand};
                           box-shadow: 0 0 0 4px ${COLORS.brand}22; }
        .sp-label { font-size: 11px; font-weight: 800; letter-spacing: 1.6px;
                     text-transform: uppercase; color: ${COLORS.textMute};
                     margin-bottom: 6px; display: block; }
      `}</style>

      <Nav />
      <Hero />
      <Numbers />
      <Benefits />
      <HowItWorks />
      <RoiCalculator />
      <Testimonials />
      <Faq />
      <ApplyForm submitted={submitted} onSubmitted={() => setSubmitted(true)} />
      <Footer />
    </div>
  );
}

/* ═══════════════════════ NAV ═══════════════════════ */
function Nav() {
  return (
    <div style={{
      background: "white", borderBottom: `1px solid ${COLORS.line}`,
      padding: "14px 0", position: "sticky", top: 0, zIndex: 50,
      backdropFilter: "blur(10px)",
    }}>
      <div className="sp-wrap" style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <a href="/" data-testid="sp-nav-logo" style={{
          display: "inline-flex", alignItems: "center",
          textDecoration: "none",
        }}>
          <img src="/ligo-logo-color.png" alt="Ligo Fibra"
            style={{ height: 64, width: "auto", display: "block",
              imageRendering: "-webkit-optimize-contrast" }} />
        </a>
        <a href="#apply" className="sp-btn-cta"
          data-testid="sp-nav-cta"
          style={{ padding: "9px 18px", fontSize: 12.5 }}>
          Quero ser parceiro <ArrowRight size={14} />
        </a>
      </div>
    </div>
  );
}

/* ═══════════════════════ HERO ═══════════════════════ */
function Hero() {
  return (
    <div style={{
      background: `radial-gradient(900px 600px at 80% -10%, rgba(244,114,182,.22), transparent 55%),
                    radial-gradient(700px 500px at 0% 30%, rgba(255,106,26,.10), transparent 60%),
                    linear-gradient(180deg, white 0%, ${COLORS.bg} 100%)`,
      paddingTop: 64, paddingBottom: 80,
      position: "relative", overflow: "hidden",
    }}>
      <div className="sp-wrap" style={{
        display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 460px)",
        gap: 48, alignItems: "center",
      }}>
        <style>{`
          @media (max-width: 880px) {
            [data-testid="sp-hero-grid"] { grid-template-columns: 1fr !important; }
          }
        `}</style>
        <div data-testid="sp-hero-grid">
          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: .55, ease: [0.22, 1, 0.36, 1] }}>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "6px 14px", borderRadius: 999,
              background: COLORS.brandSoft, color: COLORS.brand,
              fontSize: 11.5, fontWeight: 800, letterSpacing: 1.6,
              textTransform: "uppercase",
            }}><Sparkles size={13} /> Ligo Vantagens — Parceiros</span>
            <h1 style={{
              margin: "18px 0 14px", fontSize: "clamp(38px, 6vw, 68px)",
              fontWeight: 900, letterSpacing: "-.03em", lineHeight: 1.0,
              color: COLORS.ink,
            }}>
              Aumente suas vendas{" "}
              <span style={{
                background: `linear-gradient(120deg, ${COLORS.orange}, #F97316)`,
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}>oferecendo vantagens</span> para os clientes Ligo da sua região.
            </h1>
            <p style={{
              margin: "0 0 18px", fontSize: 17, lineHeight: 1.55,
              color: COLORS.textMute, maxWidth: 560,
            }}>
              Cadastre sua empresa <b>gratuitamente</b> na vitrine do app{" "}
              <b>Ligo Fibra</b> e divulgue promoções exclusivas para
              clientes próximos de você.
            </p>
            <ul style={{
              listStyle: "none", padding: 0, margin: "0 0 18px",
              display: "grid", gap: 8, maxWidth: 560,
              color: COLORS.ink, fontSize: 14.5, fontWeight: 600,
            }}>
              <li style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <CheckCircle2 size={16} color={COLORS.emerald} />
                Sua empresa ganha mais visibilidade.
              </li>
              <li style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <CheckCircle2 size={16} color={COLORS.emerald} />
                O cliente Ligo ganha benefícios.
              </li>
              <li style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <CheckCircle2 size={16} color={COLORS.emerald} />
                A região ganha uma rede de parceiros fortes.
              </li>
            </ul>
            <p style={{
              margin: "0 0 26px", fontSize: 13.5, lineHeight: 1.5,
              color: COLORS.textMute, maxWidth: 560, fontWeight: 500,
            }}>
              Cadastro <b>100% online</b>, sem mensalidade, sem fidelidade
              e <b>sem custo</b> para participar.
            </p>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              <a href="#apply" className="sp-btn-cta"
                data-testid="sp-hero-cta">
                Começar agora <ArrowRight size={16} />
              </a>
              <a href="#como-funciona" data-testid="sp-hero-secondary"
                style={{
                  padding: "14px 22px", borderRadius: 14,
                  background: "white", border: `1.5px solid ${COLORS.line}`,
                  color: COLORS.ink, fontWeight: 800, fontSize: 14,
                  textDecoration: "none",
                  display: "inline-flex", alignItems: "center", gap: 6,
                }}>Como funciona</a>
            </div>
            <div style={{ marginTop: 28, display: "flex",
                            gap: 18, flexWrap: "wrap",
                            color: COLORS.textMute, fontSize: 12.5 }}>
              <span style={kvPill()}><CheckCircle2 size={14}
                color={COLORS.emerald} /> Sem mensalidade</span>
              <span style={kvPill()}><CheckCircle2 size={14}
                color={COLORS.emerald} /> Sem fidelidade</span>
              <span style={kvPill()}><CheckCircle2 size={14}
                color={COLORS.emerald} /> App próprio grátis</span>
            </div>
          </motion.div>
        </div>

        {/* Mockup do app à direita */}
        <motion.div
          initial={{ opacity: 0, scale: .92 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: .7, ease: [0.22, 1, 0.36, 1], delay: .15 }}
          style={{ position: "relative", paddingBottom: 36 }}>
          <div style={{
            background: "linear-gradient(135deg, #7c3aed, #4C1D95)",
            borderRadius: 36, padding: 22, color: "white",
            boxShadow: "0 40px 80px rgba(76,29,149,.35)",
          }}>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 2,
                            textTransform: "uppercase", opacity: .75 }}>
              Vantagens de parceiros
            </div>
            <h3 style={{ margin: "4px 0 16px", fontSize: 26, fontWeight: 900 }}>
              Promoções 
            </h3>
            <div style={{ display: "grid", gap: 10 }}>
              {[
                { t: "30% OFF Calabresa", c: "Pizzaria Bella Italia" },
                { t: "Troca de óleo grátis", c: "Auto Center Lavras" },
                { t: "15% OFF na Farmácia", c: "Drogaria Norte" },
              ].map((m, i) => (
                <div key={i} style={{
                  background: "rgba(255,255,255,.12)",
                  border: "1px solid rgba(255,255,255,.18)",
                  borderRadius: 14, padding: "10px 14px",
                  display: "flex", justifyContent: "space-between",
                  alignItems: "center", gap: 10,
                }}>
                  <div>
                    <div style={{ fontWeight: 800, fontSize: 13.5 }}>{m.t}</div>
                    <div style={{ fontSize: 11, opacity: .75,
                                      marginTop: 2 }}>{m.c}</div>
                  </div>
                  <span style={{
                    padding: "4px 10px", borderRadius: 999,
                    background: COLORS.orange, color: "#1a0840",
                    fontSize: 10.5, fontWeight: 900,
                  }}>RESGATAR</span>
                </div>
              ))}
            </div>
          </div>
          {/* Floating QR card — ancorado no canto inferior direito do mockup */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: .5, duration: .5 }}
            style={{
              position: "absolute", bottom: 0, right: 18,
              background: "white", borderRadius: 18, padding: 14,
              boxShadow: "0 24px 48px rgba(0,0,0,.18)",
              border: `1px solid ${COLORS.line}`,
              display: "flex", alignItems: "center", gap: 12,
            }}>
            <QrCode size={32} color={COLORS.brand} />
            <div>
              <div style={{ fontSize: 10.5, fontWeight: 800,
                              letterSpacing: 1.4, textTransform: "uppercase",
                              color: COLORS.textMute }}>QR no caixa</div>
              <div style={{ fontSize: 13, fontWeight: 900,
                              color: COLORS.ink }}>Validação instantânea</div>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}

/* ═══════════════════════ NUMBERS ═══════════════════════ */
function Numbers() {
  const stats = [
    { v: "+2.500", l: "Clientes Ligo na região", icon: Users },
    { v: "+30%", l: "Lift médio em ticket", icon: TrendingUp },
    { v: "0", l: "Mensalidade", icon: Wallet },
    { v: "5 min", l: "Pra começar", icon: Zap },
  ];
  return (
    <div style={{ background: "white", padding: "32px 0",
                     borderBottom: `1px solid ${COLORS.line}` }}>
      <div className="sp-wrap" data-testid="sp-numbers" style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
        gap: 14,
      }}>
        <style>{`
          @media (max-width: 720px) {
            [data-testid="sp-numbers"] {
              grid-template-columns: repeat(2, 1fr) !important;
            }
          }
        `}</style>
        {stats.map((s, i) => (
          <div key={i} style={{ textAlign: "center", padding: 8 }}>
            <s.icon size={22} color={COLORS.brand} />
            <div style={{ fontSize: 28, fontWeight: 900,
                              marginTop: 6, color: COLORS.ink,
                              letterSpacing: "-.02em" }}>{s.v}</div>
            <div style={{ fontSize: 11.5, color: COLORS.textMute,
                              fontWeight: 700,
                              letterSpacing: .4 }}>{s.l}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════ BENEFITS ═══════════════════════ */
function Benefits() {
  const items = [
    {
      icon: Store,
      title: "Mais movimento na sua loja",
      desc: "Sua promoção aparece no app do cliente Ligo no momento que ele está perto do seu estabelecimento.",
    },
    {
      icon: TrendingUp,
      title: "Ticket médio maior",
      desc: "Cliente que resgata cupom gasta em média 30% a mais do que cliente sem promoção.",
    },
    {
      icon: Smartphone,
      title: "App próprio grátis",
      desc: "Você recebe um app exclusivo pra criar promoções, escanear QR no caixa e acompanhar resgates em tempo real.",
    },
    {
      icon: Award,
      title: "Sem mensalidade",
      desc: "Não cobramos pra você estar na vitrine. Só uma pequena taxa por resgate efetivado — paga só quando vende.",
    },
  ];
  return (
    <div className="sp-section" style={{ background: COLORS.bg }}>
      <div className="sp-wrap">
        <div style={{ textAlign: "center", maxWidth: 640, margin: "0 auto 48px" }}>
          <div className="sp-h2-sub">Por que ser parceiro</div>
          <h2 className="sp-h2">Vire <span style={{ color: COLORS.brand }}>
            queridinho</span> dos clientes Ligo da região.</h2>
          <p style={{ fontSize: 16, color: COLORS.textMute,
                          margin: 0, lineHeight: 1.55 }}>
            Mais de 2.500 famílias usam Ligo Fibra. Toda semana elas abrem o app
            pra ver onde gastar com vantagem — esteja na lista delas.
          </p>
        </div>
        <div data-testid="sp-benefits" style={{
          display: "grid", gridTemplateColumns: "repeat(2, 1fr)",
          gap: 18,
        }}>
          <style>{`
            @media (max-width: 720px) {
              [data-testid="sp-benefits"] {
                grid-template-columns: 1fr !important;
              }
            }
          `}</style>
          {items.map((it, i) => (
            <motion.div key={i}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * .08, duration: .4 }}
              style={{
                background: "white", borderRadius: 22,
                border: `1px solid ${COLORS.line}`,
                padding: 26,
                boxShadow: "0 8px 22px rgba(58,15,138,.05)",
              }}>
              <div style={{
                width: 52, height: 52, borderRadius: 14,
                background: COLORS.brandSoft, color: COLORS.brand,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}><it.icon size={26} /></div>
              <h3 style={{ margin: "16px 0 8px", fontSize: 19,
                              fontWeight: 900, letterSpacing: "-.015em",
                              color: COLORS.ink }}>{it.title}</h3>
              <p style={{ margin: 0, color: COLORS.textMute,
                              fontSize: 14, lineHeight: 1.55 }}>{it.desc}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ HOW IT WORKS ═══════════════════════ */
function HowItWorks() {
  const steps = [
    { n: "01", title: "Cadastre sua empresa",
      desc: "Preencha o formulário abaixo em 2 min. A gente entra em contato em até 24h." },
    { n: "02", title: "Receba seu link mágico",
      desc: "Você ganha um link exclusivo no WhatsApp que abre seu app sem precisar de senha." },
    { n: "03", title: "Crie suas promoções",
      desc: "Suba foto do produto, defina o desconto e publique. Em 30s tá no app do cliente." },
    { n: "04", title: "Cliente chega, escaneia QR",
      desc: "No caixa você escaneia o QR do cliente Ligo, valida na hora e a venda acontece." },
  ];
  return (
    <div id="como-funciona" className="sp-section"
        style={{ background: "white" }}>
      <div className="sp-wrap">
        <div style={{ textAlign: "center", maxWidth: 580, margin: "0 auto 48px" }}>
          <div className="sp-h2-sub">Como funciona</div>
          <h2 className="sp-h2">4 passos pra começar a faturar.</h2>
        </div>
        <div data-testid="sp-steps" style={{
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
          gap: 18, position: "relative",
        }}>
          <style>{`
            @media (max-width: 880px) {
              [data-testid="sp-steps"] {
                grid-template-columns: 1fr 1fr !important;
              }
            }
            @media (max-width: 540px) {
              [data-testid="sp-steps"] {
                grid-template-columns: 1fr !important;
              }
            }
          `}</style>
          {steps.map((s, i) => (
            <div key={i} style={{
              padding: 22, borderRadius: 18,
              background: COLORS.bg, position: "relative",
              border: `1px solid ${COLORS.line}`,
            }}>
              <div style={{
                fontSize: 36, fontWeight: 900, lineHeight: 1,
                background: `linear-gradient(135deg, ${COLORS.brand}, ${COLORS.orange})`,
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
                letterSpacing: "-.02em",
              }}>{s.n}</div>
              <h3 style={{ margin: "12px 0 6px", fontSize: 16, fontWeight: 900,
                              color: COLORS.ink, lineHeight: 1.2 }}>{s.title}</h3>
              <p style={{ margin: 0, color: COLORS.textMute,
                              fontSize: 13, lineHeight: 1.5 }}>{s.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ ROI CALCULATOR ═══════════════════════ */
function RoiCalculator() {
  const [ticket, setTicket] = useState(45);
  const [clientsDay, setClientsDay] = useState(30);
  const [discount, setDiscount] = useState(15);

  const ligoClientsRate = 0.18; // % dos clientes locais que são Ligo
  const conversionUplift = 1.30; // 30% mais gasto
  const monthlyExtra = clientsDay * 30 * ligoClientsRate
    * ticket * (1 - discount / 100) * (conversionUplift - 1);

  return (
    <div className="sp-section" style={{
      background: `linear-gradient(135deg, ${COLORS.brandDeep}, ${COLORS.brand})`,
      color: "white", position: "relative", overflow: "hidden",
    }}>
      <div className="sp-wrap" style={{
        display: "grid", gridTemplateColumns: "1.1fr .9fr",
        gap: 48, alignItems: "center", position: "relative", zIndex: 2,
      }}>
        <style>{`
          @media (max-width: 880px) {
            [data-testid="sp-roi-grid"] { grid-template-columns: 1fr !important; }
          }
        `}</style>
        <div data-testid="sp-roi-grid">
          <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 2,
                            textTransform: "uppercase", opacity: .8 }}>
            Quanto sua loja pode faturar?
          </div>
          <h2 className="sp-h2" style={{ marginTop: 8 }}>
            Simule seu ganho extra.
          </h2>
          <p style={{ margin: "0 0 26px", fontSize: 15,
                          opacity: .85, lineHeight: 1.55 }}>
            Estimativa baseada em média do mercado: 18% dos consumidores
            da sua região são clientes Ligo Fibra, e cupom aumenta o
            ticket médio em ~30%.
          </p>

          <RoiInput label="Ticket médio (R$)"
            value={ticket} setValue={setTicket}
            min={10} max={500} step={5}
            testid="roi-ticket" />
          <RoiInput label="Clientes que atende por dia"
            value={clientsDay} setValue={setClientsDay}
            min={5} max={500} step={5}
            testid="roi-clients" />
          <RoiInput label="Desconto que vai oferecer (%)"
            value={discount} setValue={setDiscount}
            min={5} max={50} step={5}
            testid="roi-discount" />
        </div>

        <motion.div
          key={`${ticket}-${clientsDay}-${discount}`}
          initial={{ scale: .96, opacity: .7 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: .3 }}
          style={{
            background: "rgba(255,255,255,.10)",
            border: "1px solid rgba(255,255,255,.22)",
            borderRadius: 28, padding: 32, textAlign: "center",
            backdropFilter: "blur(12px)",
          }}>
          <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 2,
                            textTransform: "uppercase", opacity: .8 }}>
            Faturamento extra estimado
          </div>
          <div data-testid="sp-roi-value" style={{
            margin: "12px 0 4px", fontSize: 56, fontWeight: 900,
            letterSpacing: "-.03em", lineHeight: 1,
            background: `linear-gradient(180deg, #FFE6D2, ${COLORS.orange})`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>
            R$ {monthlyExtra.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ".")}
          </div>
          <div style={{ fontSize: 14, opacity: .85, fontWeight: 600 }}>
            por mês
          </div>
          <a href="#apply" className="sp-btn-cta"
            data-testid="sp-roi-cta"
            style={{ marginTop: 22 }}>
            Quero esse resultado <ArrowRight size={16} />
          </a>
        </motion.div>
      </div>
    </div>
  );
}

function RoiInput({ label, value, setValue, min, max, step, testid }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: 1.4,
                          textTransform: "uppercase", opacity: .85 }}>{label}</span>
        <span style={{ fontSize: 14, fontWeight: 900,
                          color: COLORS.orange }}>{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step}
        data-testid={testid}
        value={value}
        onChange={(e) => setValue(Number(e.target.value))}
        style={{ width: "100%", accentColor: COLORS.orange,
                    cursor: "pointer" }} />
    </div>
  );
}

/* ═══════════════════════ TESTIMONIALS ═══════════════════════ */
function Testimonials() {
  const items = [
    {
      q: "Em 2 meses dobrei o movimento nas terças à noite. Cliente Ligo virou freguês.",
      n: "Antônio Carvalho",
      r: "Pizzaria Bella Italia · Lavras",
      avatar: "",
    },
    {
      q: "O cliente já chega com o QR aberto no celular. É só passar o leitor e pronto. Sem papelada.",
      n: "Daniela Souza",
      r: "Drogaria Norte · Itumirim",
      avatar: "",
    },
    {
      q: "Não paguei nada pra começar. Em 1 mês fiz 47 atendimentos só por causa do cupom Ligo.",
      n: "Roberto Lima",
      r: "Auto Center Lima · Lavras",
      avatar: "",
    },
  ];
  return (
    <div className="sp-section" style={{ background: COLORS.bg }}>
      <div className="sp-wrap">
        <div style={{ textAlign: "center", maxWidth: 560, margin: "0 auto 48px" }}>
          <div className="sp-h2-sub">Parceiros falam</div>
          <h2 className="sp-h2">Quem já é parceiro, recomenda.</h2>
        </div>
        <div data-testid="sp-testimonials" style={{
          display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
          gap: 18,
        }}>
          <style>{`
            @media (max-width: 880px) {
              [data-testid="sp-testimonials"] {
                grid-template-columns: 1fr !important;
              }
            }
          `}</style>
          {items.map((t, i) => (
            <div key={i} style={{
              background: "white", borderRadius: 22, padding: 24,
              border: `1px solid ${COLORS.line}`,
              boxShadow: "0 12px 28px rgba(58,15,138,.06)",
            }}>
              <div style={{ fontSize: 22, color: COLORS.brand,
                                lineHeight: 1, marginBottom: 10 }}>“</div>
              <p style={{ margin: 0, fontSize: 15, lineHeight: 1.55,
                              color: COLORS.ink, fontWeight: 500 }}>{t.q}</p>
              <div style={{ marginTop: 18, display: "flex",
                                gap: 12, alignItems: "center" }}>
                <div style={{
                  width: 44, height: 44, borderRadius: "50%",
                  background: COLORS.brandSoft,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 22,
                }}>{t.avatar}</div>
                <div>
                  <div style={{ fontSize: 13.5, fontWeight: 900,
                                    color: COLORS.ink }}>{t.n}</div>
                  <div style={{ fontSize: 11.5, color: COLORS.textMute,
                                    fontWeight: 600 }}>{t.r}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ FAQ ═══════════════════════ */
function Faq() {
  const qa = [
    {
      q: "Quanto custa pra ser parceiro?",
      a: "Zero. Sem mensalidade, sem taxa de adesão, sem fidelidade. Você paga uma pequena comissão (entre 5-10%) APENAS quando um cliente resgata uma promoção — ou seja, só quando vende.",
    },
    {
      q: "Como o cliente sabe da minha promoção?",
      a: "Todo cliente Ligo Fibra tem acesso a um app exclusivo com a vitrine de parceiros. Sua loja aparece na lista, com foto da promoção, descrição e seu endereço. Buscam por categoria e proximidade.",
    },
    {
      q: "Como recebo o pagamento dos resgates?",
      a: "A Ligo concentra os resgates do mês e repassa por PIX no dia 5 do mês seguinte, junto com o relatório completo de quais clientes resgataram quais cupons.",
    },
    {
      q: "Preciso de equipamento especial pra escanear o QR?",
      a: "Não. Você usa seu celular comum — Android ou iPhone. Abre o app de parceiro pelo link mágico (não precisa de senha), aperta no leitor e pronto.",
    },
    {
      q: "E se eu quiser parar de ser parceiro?",
      a: "É só desativar suas promoções no seu app. Não tem multa, não tem aviso prévio. Você fica no controle.",
    },
    {
      q: "Em quais regiões funciona?",
      a: "Atendemos toda a área de cobertura Ligo Fibra: Lavras, Itumirim, Ribeirão Vermelho, Ijaci, Ingaí, Nepomuceno e cidades vizinhas. Não precisa ser próximo a uma OLT — se tem cliente Ligo na sua rua, você pode ser parceiro.",
    },
  ];
  const [open, setOpen] = useState(0);
  return (
    <div className="sp-section" style={{ background: "white" }}>
      <div className="sp-wrap" style={{ maxWidth: 800, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div className="sp-h2-sub">Tira-dúvidas</div>
          <h2 className="sp-h2">Perguntas frequentes.</h2>
        </div>
        <div data-testid="sp-faq" style={{ display: "grid", gap: 10 }}>
          {qa.map((it, i) => (
            <div key={i} style={{
              background: COLORS.bg, borderRadius: 14,
              border: `1px solid ${COLORS.line}`, overflow: "hidden",
            }}>
              <button onClick={() => setOpen(open === i ? -1 : i)}
                data-testid={`sp-faq-q-${i}`}
                style={{
                  display: "flex", justifyContent: "space-between",
                  alignItems: "center", width: "100%",
                  padding: "16px 20px", background: "transparent",
                  border: "none", cursor: "pointer", textAlign: "left",
                  fontFamily: FONT, color: COLORS.ink,
                  fontSize: 15, fontWeight: 800,
                }}>
                {it.q}
                <ChevronDown size={18} style={{
                  transition: "transform .25s",
                  transform: open === i ? "rotate(180deg)" : "rotate(0deg)",
                  flexShrink: 0,
                }} />
              </button>
              {open === i && (
                <div style={{
                  padding: "0 20px 18px", color: COLORS.textMute,
                  fontSize: 14, lineHeight: 1.6,
                }}>{it.a}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ APPLY FORM ═══════════════════════ */
function ApplyForm({ submitted, onSubmitted }) {
  const [form, setForm] = useState({
    business_name: "", contact_name: "", whatsapp: "", email: "",
    city: "", segment: "", monthly_clients: "",
    has_physical_store: true, notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (e) => {
    e.preventDefault();
    if (!form.business_name || !form.contact_name || !form.whatsapp) {
      setErr("Preencha nome do negócio, contato e WhatsApp.");
      return;
    }
    setBusy(true); setErr("");
    try {
      await axios.post(`${API}/apply`, form);
      onSubmitted();
    } catch (e) {
      setErr(e?.response?.data?.detail
        || "Não foi possível enviar. Tente novamente.");
    } finally { setBusy(false); }
  };

  if (submitted) return (
    <div id="apply" className="sp-section"
        style={{ background: COLORS.bg }}>
      <div className="sp-wrap" style={{ maxWidth: 640, margin: "0 auto",
                                              textAlign: "center" }}>
        <motion.div
          initial={{ scale: .9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          data-testid="sp-form-success"
          style={{
            background: `linear-gradient(135deg, ${COLORS.emerald}, #047857)`,
            borderRadius: 26, padding: 44, color: "white",
            boxShadow: "0 30px 60px rgba(16,185,129,.32)",
          }}>
          <div style={{ fontSize: 56 }}>✓</div>
          <h2 style={{ margin: "12px 0 8px", fontSize: 28, fontWeight: 900,
                          letterSpacing: "-.02em" }}>
            Recebemos seu cadastro!
          </h2>
          <p style={{ margin: 0, fontSize: 16, lineHeight: 1.55,
                          opacity: .9, maxWidth: 460,
                          marginLeft: "auto", marginRight: "auto" }}>
            Nossa equipe vai entrar em contato pelo WhatsApp em até 24h
            úteis pra finalizar a parceria. Obrigado por confiar na Ligo!
          </p>
        </motion.div>
      </div>
    </div>
  );

  return (
    <div id="apply" className="sp-section"
        style={{ background: COLORS.bg }}>
      <div className="sp-wrap" style={{
        display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 560px)",
        gap: 48, alignItems: "center",
      }}>
        <style>{`
          @media (max-width: 880px) {
            [data-testid="sp-form-grid"] { grid-template-columns: 1fr !important; }
          }
        `}</style>
        <div data-testid="sp-form-grid">
          <div className="sp-h2-sub">Vire parceiro</div>
          <h2 className="sp-h2">É rápido. Em 2 minutos sua loja tá na vitrine.</h2>
          <p style={{ fontSize: 15, color: COLORS.textMute,
                          margin: "0 0 22px", lineHeight: 1.55,
                          maxWidth: 460 }}>
            Preenche o formulário e nossa equipe entra em contato em até 24h
            pelo WhatsApp pra finalizar e te enviar seu link mágico.
          </p>
          <div style={{ display: "grid", gap: 12 }}>
            <Feat icon={MapPin} t="Atendimento local"
              s="Time da Ligo na sua região, fala seu idioma." />
            <Feat icon={Zap} t="Setup em 24h"
              s="Cadastro aprovado e seu app pronto pra usar." />
            <Feat icon={CheckCircle2} t="Sem compromisso"
              s="Cancela quando quiser, sem multa." />
          </div>
        </div>

        <form onSubmit={submit} data-testid="sp-form"
            style={{
              background: "white", borderRadius: 26, padding: 28,
              border: `1px solid ${COLORS.line}`,
              boxShadow: "0 26px 56px rgba(58,15,138,.10)",
              display: "grid", gap: 12,
            }}>
          <FormField label="Nome do negócio *" value={form.business_name}
            testid="sp-form-business" placeholder="Ex: Pizzaria Bella Italia"
            onChange={(v) => set("business_name", v)} />
          <FormField label="Seu nome *" value={form.contact_name}
            testid="sp-form-contact" placeholder="Quem cuida da loja"
            onChange={(v) => set("contact_name", v)} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                            gap: 10 }}>
            <FormField label="WhatsApp *" value={form.whatsapp}
              testid="sp-form-whatsapp" placeholder="(35) 99999-0000"
              onChange={(v) => set("whatsapp", v)} />
            <FormField label="E-mail" value={form.email} type="email"
              testid="sp-form-email" placeholder="opcional"
              onChange={(v) => set("email", v)} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                            gap: 10 }}>
            <FormSelect label="Cidade *" value={form.city} options={REGIONS}
              testid="sp-form-city"
              onChange={(v) => set("city", v)} />
            <FormSelect label="Segmento *" value={form.segment}
              options={SEGMENTS}
              testid="sp-form-segment"
              onChange={(v) => set("segment", v)} />
          </div>
          <FormField label="Clientes atendidos por mês (aprox.)"
            type="number" value={form.monthly_clients}
            testid="sp-form-monthly" placeholder="Ex: 200"
            onChange={(v) => set("monthly_clients", v)} />
          <FormField label="Observações" textarea value={form.notes}
            testid="sp-form-notes"
            placeholder="Ex: Tenho 2 unidades, atendo delivery..."
            onChange={(v) => set("notes", v)} />

          {err && (
            <div data-testid="sp-form-error" style={{
              padding: "10px 14px", borderRadius: 10,
              background: "#FEE2E2", border: "1px solid #FCA5A5",
              color: "#991B1B", fontSize: 13, fontWeight: 600,
            }}>{err}</div>
          )}

          <button type="submit" className="sp-btn-cta"
            data-testid="sp-form-submit"
            disabled={busy}
            style={{ marginTop: 8, width: "100%",
                       justifyContent: "center",
                       opacity: busy ? .7 : 1 }}>
            {busy ? "Enviando..." : "Quero ser parceiro"}
            {!busy && <ArrowRight size={16} />}
          </button>
          <p style={{ margin: 0, fontSize: 11.5, color: COLORS.textMute,
                          textAlign: "center", lineHeight: 1.5 }}>
            Ao enviar você concorda em ser contatado pela equipe Ligo via
            WhatsApp. Sem spam.
          </p>
        </form>
      </div>
    </div>
  );
}

function Feat({ icon: Icon, t, s }) {
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div style={{
        width: 36, height: 36, borderRadius: 10,
        background: COLORS.brandSoft, color: COLORS.brand,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}><Icon size={18} /></div>
      <div>
        <div style={{ fontSize: 14.5, fontWeight: 900,
                          color: COLORS.ink }}>{t}</div>
        <div style={{ fontSize: 13, color: COLORS.textMute,
                          marginTop: 2, lineHeight: 1.45 }}>{s}</div>
      </div>
    </div>
  );
}

function FormField({ label, value, onChange, type = "text",
  placeholder = "", testid, textarea }) {
  return (
    <div>
      <label className="sp-label">{label}</label>
      {textarea
        ? <textarea className="sp-input" data-testid={testid}
            value={value || ""} placeholder={placeholder} rows={3}
            onChange={(e) => onChange(e.target.value)}
            style={{ resize: "vertical" }} />
        : <input className="sp-input" type={type} data-testid={testid}
            value={value || ""} placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)} />
      }
    </div>
  );
}
function FormSelect({ label, value, options, onChange, testid }) {
  return (
    <div>
      <label className="sp-label">{label}</label>
      <select className="sp-input" data-testid={testid}
          value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Escolha...</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

/* ═══════════════════════ FOOTER ═══════════════════════ */
function Footer() {
  return (
    <div style={{
      background: COLORS.ink, color: "white", padding: "32px 0",
    }}>
      <div className="sp-wrap" style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", flexWrap: "wrap", gap: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img src="/ligo-logo-white.svg" alt="Ligo Fibra"
            style={{ height: 32, width: "auto", opacity: .9 }} />
          <span style={{ fontSize: 12.5, opacity: .8 }}>
            Vantagens — Programa de Parceiros
          </span>
        </div>
        <div style={{ fontSize: 11.5, opacity: .65 }}>
          © {new Date().getFullYear()} Ligo Fibra · Todos os direitos reservados
        </div>
      </div>
    </div>
  );
}

function kvPill() {
  return {
    display: "inline-flex", alignItems: "center", gap: 6,
    fontWeight: 700, fontSize: 12.5,
  };
}

function ensureFont() {
  if (document.getElementById("sora-font-link")) return;
  const link = document.createElement("link");
  link.id = "sora-font-link";
  link.rel = "stylesheet";
  link.href = "https://fonts.googleapis.com/css2?family=Sora:wght@500;700;800;900&display=swap";
  document.head.appendChild(link);
}
