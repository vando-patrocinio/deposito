/* Componentes compartilhados pelas telas do app /cliente.
 *
 * - Shell: container full-screen mobile-first, instala a fonte Sora,
 *   renderiza o gradient base e o noise.
 * - HeaderHero: gradient + pill + título grande + botões Voltar/Sair.
 * - ProfileSheet: card branco que sobrepõe o header (avatar + nome + CPF
 *   + plano + filial). Replica fielmente os screenshots #2/#3 do usuário.
 * - GlassCard, OrangeCTA, PillBadge: pedaços reutilizáveis.
 */
import React from "react";
import { motion } from "framer-motion";
import { ChevronLeft, LogOut } from "lucide-react";

import {
  COLORS, NOISE_OVERLAY,
  HERO_ANIMATED_CSS,
  FONT_DISPLAY, FONT_BODY, ensureSoraFont,
  glass, sheet, pill, maskCPF, initialsOf, titleCase,
} from "@/cliente/ligo-theme";

/* ───────────────────────────── Shell ───────────────────────────── */
export function Shell({ children, testid = "cliente-shell" }) {
  React.useEffect(() => { ensureSoraFont(); }, []);
  return (
    <div data-testid={testid} style={{
      minHeight: "100vh", background: "#F7F4FF",
      fontFamily: FONT_BODY, color: COLORS.slate900,
      overflowX: "hidden",
    }}>
      <style>{`
        @keyframes shimmer { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
        @keyframes ligo-name-shimmer {
          0%{background-position:0% 50%}
          50%{background-position:100% 50%}
          100%{background-position:0% 50%}
        }
        @keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
        .ligo-name-shimmer-text {
          background-image: linear-gradient(110deg,
            #FFE6D2 0%, #FFB070 18%, #FF6A1A 36%, #ffffff 50%,
            #FFB070 64%, #FF6A1A 82%, #FFE6D2 100%);
          background-size: 300% 100%;
          -webkit-background-clip: text;
          background-clip: text;
          -webkit-text-fill-color: transparent;
          color: transparent;
          animation: ligo-name-shimmer 6s linear infinite;
          filter: drop-shadow(0 6px 28px rgba(255,106,26,.35));
        }
        .ligo-tap:active { transform: scale(.97); transition: transform .1s; }
        .ligo-orange-cta:hover { filter: brightness(1.05); }
        button { font-family: inherit; }
        input { font-family: inherit; }
        input::placeholder { color: rgba(255,255,255,.5); }
        .hide-scrollbar::-webkit-scrollbar { display: none; }
        .hide-scrollbar { scrollbar-width: none; }
        ${HERO_ANIMATED_CSS}
      `}</style>
      <div style={{
        maxWidth: 760, margin: "0 auto", position: "relative",
        paddingBottom: 60,
      }}>{children}</div>
    </div>
  );
}

/* ───────────────────────────── HeaderHero ───────────────────────────── */
/**
 * Topo roxo gradient com curva inferior. Aceita props:
 *  - pillLabel: ex. "● PROGRAMA INDIQUE E GANHE"
 *  - greeting: "OLÁ,"  greetingName: "Maria 👋"
 *  - subtitle: JSX livre (pode ter <span> laranja)
 *  - onBack, onLogout: handlers (botões só aparecem se passados)
 */
export function HeaderHero({
  pillLabel, greeting, greetingName, greetingEmoji, subtitle,
  onBack, onLogout, height = 360,
}) {
  return (
    <div data-testid="cliente-header-hero" className="ligo-hero-bg" style={{
      position: "relative", overflow: "hidden",
      paddingTop: 24, paddingBottom: 90,
      minHeight: height,
      borderBottomLeftRadius: "40% 12%",
      borderBottomRightRadius: "40% 12%",
      color: "white",
    }}>
      {/* Noise overlay sutil */}
      <div aria-hidden style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage: NOISE_OVERLAY,
        opacity: .25, mixBlendMode: "soft-light",
      }} />

      {/* Top bar — logo na esquerda, botões na direita */}
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", padding: "0 22px",
        position: "relative", zIndex: 3,
      }}>
        <img src="/ligo-logo-white.svg" alt="Ligo Fibra"
          onError={(e) => { e.target.src = "/ligo-logo-white.png"; }}
          style={{ height: 100, width: "auto" }} />
        <div style={{ display: "flex", gap: 8 }}>
          {onBack && (
            <button onClick={onBack} className="ligo-tap"
              data-testid="header-back-btn"
              style={iconBtnStyle()}>
              <ChevronLeft size={16} /> Voltar
            </button>
          )}
          {onLogout && (
            <button onClick={onLogout} className="ligo-tap"
              data-testid="header-logout-btn"
              style={iconBtnStyle()}>
              <LogOut size={14} /> Sair
            </button>
          )}
        </div>
      </div>

      {/* Pill + greeting — espaço reduzido pra logo ficar "um pouco acima" do greeting */}
      <div style={{ padding: "14px 26px 0", position: "relative", zIndex: 2 }}>
        {pillLabel && (
          <motion.span
            data-testid="header-pill"
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: .35 }}
            style={pill("rgba(255,255,255,.12)", "#FFE6D2")}>
            <span style={{ width: 7, height: 7, borderRadius: "50%",
              background: COLORS.orange,
              boxShadow: `0 0 10px ${COLORS.orange}` }} />
            {pillLabel}
          </motion.span>
        )}

        {greeting && (
          <motion.div
            initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: .45, delay: .05 }}
            style={{ marginTop: 14, fontFamily: FONT_DISPLAY }}>
            <div style={{
              fontSize: 13, fontWeight: 700, letterSpacing: 3,
              textTransform: "uppercase", opacity: .85,
            }}>{greeting}</div>
            <div data-testid="header-greeting-name" style={{
              fontSize: "clamp(40px, 9vw, 64px)",
              fontWeight: 900, lineHeight: 1.02,
              letterSpacing: "-.03em",
              marginTop: 2,
              display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
            }}>
              <span className="ligo-name-shimmer-text">{greetingName}</span>
              {greetingEmoji && (
                <span style={{
                  display: "inline-block",
                  animation: "float 3.2s ease-in-out infinite",
                  textShadow: "0 6px 18px rgba(0,0,0,.25)",
                }}>{greetingEmoji}</span>
              )}
            </div>
          </motion.div>
        )}

        {subtitle && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            transition={{ duration: .45, delay: .15 }}
            style={{
              marginTop: 12, fontSize: "clamp(16px, 4vw, 20px)",
              fontWeight: 600, color: "rgba(255,255,255,.92)",
              lineHeight: 1.4, maxWidth: 540,
            }}>
            {subtitle}
          </motion.div>
        )}
      </div>
    </div>
  );
}

const iconBtnStyle = () => ({
  ...glass(.14), color: "white", fontSize: 13, fontWeight: 700,
  padding: "8px 14px", borderRadius: 999, cursor: "pointer",
  display: "inline-flex", alignItems: "center", gap: 6,
});

/* ──────────────────────────── ProfileSheet ──────────────────────────── */
/** Card branco que sobrepõe o header (margem negativa).
 *  Avatar + Nome + CPF mascarado + Plano + Filial. */
export function ProfileSheet({ me, marginTop = -60, onShowQR }) {
  const [menuOpen, setMenuOpen] = React.useState(false);
  if (!me) return null;
  const cpfFromDoc = me.cpf || me.document || me.cpf_cnpj || "";
  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: .55, ease: [0.22, 1, 0.36, 1] }}
      data-testid="cliente-profile-sheet"
      style={{
        ...sheet(),
        margin: `${marginTop}px 16px 0`,
        padding: 22,
        position: "relative", zIndex: 4,
      }}>
      {/* iter228 — 3 pontinhos no canto superior direito */}
      <button type="button" data-testid="cliente-profile-menu-btn"
        onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
        aria-label="Mais opções"
        style={{
          position: "absolute", top: 14, right: 14,
          width: 38, height: 38, borderRadius: "50%",
          background: "rgba(124,58,237,.08)",
          border: "1px solid rgba(124,58,237,.18)",
          color: COLORS.purpleBase, cursor: "pointer", padding: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 20, fontWeight: 900, lineHeight: 1, letterSpacing: 1.5,
        }}>⋮</button>
      {menuOpen && (
        <>
          <div onClick={() => setMenuOpen(false)} style={{
            position: "fixed", inset: 0, zIndex: 9,
          }} />
          <div data-testid="cliente-profile-menu" style={{
            position: "absolute", top: 56, right: 14, zIndex: 10,
            background: "white",
            border: "1px solid #E0D5FF",
            borderRadius: 14, boxShadow: "0 18px 40px rgba(58,15,138,.22)",
            minWidth: 200, overflow: "hidden",
          }}>
            <button type="button" data-testid="cliente-menu-qr"
              onClick={() => { setMenuOpen(false); onShowQR && onShowQR(); }}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                width: "100%", padding: "12px 14px",
                background: "white", border: "none", cursor: "pointer",
                fontSize: 13.5, fontWeight: 700, color: COLORS.slate900,
                textAlign: "left", fontFamily: "inherit",
              }}>
              <span style={{ fontSize: 18 }}>📱</span>
              Meu QR Code de cliente
            </button>
          </div>
        </>
      )}

      {/* Header do sheet: avatar + nome + CPF */}
      <div style={{ display: "flex", alignItems: "center", gap: 14,
                       paddingRight: 44 }}>
        <div data-testid="cliente-avatar" style={{
          width: 64, height: 64, borderRadius: "50%",
          background: `linear-gradient(135deg, ${COLORS.purpleMid}, ${COLORS.purpleBase})`,
          color: "white", fontWeight: 900, fontSize: 22, letterSpacing: .5,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 12px 24px rgba(58,15,138,.28)",
          flexShrink: 0,
        }}>
          {initialsOf(me.name)}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div data-testid="cliente-profile-name" style={{
            fontSize: "clamp(20px, 5vw, 24px)", fontWeight: 800,
            letterSpacing: "-.01em", color: COLORS.slate900,
            lineHeight: 1.15, whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis",
          }}>{titleCase(me.name) || "Cliente Ligo"}</div>
          <div data-testid="cliente-profile-cpf" style={{
            display: "inline-block", marginTop: 6,
            fontSize: 13, fontWeight: 700, color: COLORS.slate700,
            background: "#F1ECFF", border: "1px solid #E0D5FF",
            padding: "4px 10px", borderRadius: 999,
            letterSpacing: .8,
          }}>{maskCPF(cpfFromDoc)}</div>
        </div>
      </div>

      {/* Plano contratado */}
      {me.plan_name && (
        <div data-testid="cliente-plan-row" style={{
          marginTop: 18, padding: "14px 14px",
          background: "linear-gradient(135deg, #F4F1FF, #ECE4FF)",
          border: "1px solid #DCCFFF", borderRadius: 16,
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <div style={{
            width: 50, height: 50, borderRadius: 12,
            background: "linear-gradient(135deg, #5AA9FF, #2D7EFF)",
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
            boxShadow: "0 8px 18px rgba(45,126,255,.35)",
          }}>
            <span style={{ fontSize: 26 }}>📊</span>
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{
              fontSize: 11, fontWeight: 800, letterSpacing: 1.8,
              textTransform: "uppercase", color: "#2D7EFF",
            }}>Plano contratado</div>
            <div style={{
              fontSize: 20, fontWeight: 900, letterSpacing: "-.01em",
              color: COLORS.slate900, marginTop: 2, lineHeight: 1.1,
            }}>{me.plan_name}</div>
            {me.plan_price_brl && (
              <div style={{
                fontSize: 13, color: COLORS.slate500, fontWeight: 600,
                marginTop: 2,
              }}>R$ {Number(me.plan_price_brl).toFixed(2).replace(".", ",")}/mês</div>
            )}
          </div>
        </div>
      )}

      {/* Filial */}
      {me.filial_name && (
        <div data-testid="cliente-filial-row" style={{
          marginTop: 12, display: "flex", alignItems: "center", gap: 8,
          fontSize: 13, color: COLORS.slate500, fontWeight: 600,
        }}>
          <span style={{ fontSize: 16 }}>📁</span>
          <span style={{ fontWeight: 700, color: COLORS.slate700,
            letterSpacing: 1.2, textTransform: "uppercase", fontSize: 11 }}>
            Filial
          </span>
          <span style={{ fontWeight: 800, color: COLORS.slate900,
            letterSpacing: .3 }}>
            {me.filial_name}
          </span>
        </div>
      )}
    </motion.div>
  );
}

/* ──────────────────────────── GlassCard ──────────────────────────── */
export function GlassCard({ children, style, testid, delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: .5, delay, ease: [0.22, 1, 0.36, 1] }}
      data-testid={testid}
      style={{
        ...glass(.08),
        borderRadius: 24,
        padding: 22,
        color: "white",
        ...style,
      }}>{children}</motion.div>
  );
}

/* ──────────────────────────── WhiteCard ──────────────────────────── */
export function WhiteCard({ children, style, testid, delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: .5, delay, ease: [0.22, 1, 0.36, 1] }}
      data-testid={testid}
      style={{
        background: "white",
        borderRadius: 24,
        padding: 20,
        boxShadow: "0 18px 50px rgba(20,8,60,.10)",
        border: "1px solid rgba(20,8,60,.06)",
        ...style,
      }}>{children}</motion.div>
  );
}

/* ──────────────────────────── OrangeCTA ──────────────────────────── */
export function OrangeCTA({ children, onClick, disabled, style, testid,
  type = "button" }) {
  return (
    <button
      type={type} onClick={onClick} disabled={disabled}
      className="ligo-tap ligo-orange-cta"
      data-testid={testid}
      style={{
        width: "100%",
        padding: "16px 22px",
        borderRadius: 999, border: "none",
        cursor: disabled ? "not-allowed" : "pointer",
        background: disabled
          ? "rgba(0,0,0,.08)"
          : `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeSoft})`,
        color: disabled ? COLORS.slate500 : "white",
        fontWeight: 900, fontSize: 16, letterSpacing: .3,
        boxShadow: disabled ? "none" : "0 18px 40px rgba(255,106,26,.45)",
        transition: "filter .15s, transform .1s",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        gap: 8,
        ...style,
      }}>{children}</button>
  );
}

/* ──────────────────────────── PillBadge ──────────────────────────── */
/** Pílula com bolinha colorida — usado pros badges Ativo / Programa etc. */
export function PillBadge({ children, color = COLORS.orange,
  bg = "rgba(255,255,255,.12)", textColor = "#FFE6D2", style }) {
  return (
    <span style={{ ...pill(bg, textColor), ...style }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%",
        background: color, boxShadow: `0 0 10px ${color}` }} />
      {children}
    </span>
  );
}
