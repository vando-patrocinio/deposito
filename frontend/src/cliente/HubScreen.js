/* HubScreen — Após login.
 *
 * iter229 — Layout pedido pelo usuário:
 *   1) Header roxo gradient com "OLÁ, [Nome] "
 *   2) Sheet branco PROMOÇÕES (substitui o ProfileSheet) — vitrine de
 *      parceiros + 3 pontinhos no canto direito que abrem o QR modal
 *      com infos do cliente (nome/CPF/plano/status).
 *   3) Cards "Indique e Ganhe" e "Minha Ligo" abaixo (gradient).
 */
import React, { useState } from "react";
import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";

import { COLORS, FONT_DISPLAY, titleCase } from "@/cliente/ligo-theme";
import {
  Shell, HeaderHero,
} from "@/cliente/components";
import ClientQRModal from "@/cliente/ClientQRModal";
import PromocoesSheet from "@/cliente/PromocoesSheet";

export default function HubScreen({ me, onOpenIndique, onOpenMinhaLigo,
  onOpenPromocoes, onLogout }) {
  const firstName = titleCase((me?.name || "").split(" ")[0] || "Amigo(a)");
  const [qrOpen, setQrOpen] = useState(false);
  return (
    <Shell testid="cliente-hub-screen">
      <HeaderHero
        greeting="Olá,"
        greetingName={firstName}
        greetingEmoji=""
        subtitle={<>O que você quer fazer{" "}
          <span style={{ color: "#FFB070", fontWeight: 800 }}>hoje?</span>
        </>}
        onLogout={onLogout}
        height={300}
      />

      {/* iter229 — Sheet branco PROMOÇÕES substitui o ProfileSheet.
          Os 3 pontinhos no canto direito abrem o modal QR Code com as
          infos do cliente (antes mostradas no ProfileSheet). */}
      <PromocoesSheet marginTop={-66}
        onShowQR={() => setQrOpen(true)}
        onViewAll={onOpenPromocoes} />

      <ClientQRModal open={qrOpen} me={me}
        onClose={() => setQrOpen(false)} />

      <motion.div
        initial="hidden" animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: .12 } } }}
        style={{
          margin: "26px 16px 0",
          display: "grid", gap: 14,
          gridTemplateColumns: "1fr",
        }}
        // 2 colunas em ≥600px via inline media — usamos classe utilitária:
      >
        <style>{`
          @media (min-width: 600px) {
            [data-testid="cliente-hub-grid"] { grid-template-columns: 1fr 1fr; }
          }
          /* iter218 — Gradiente animado dos cards do Hub: o conic
             gradient gira lentamente atrás do conteúdo, criando um
             "aurora" sutil que o usuário pediu como referência. */
          @keyframes hubAurora { to { transform: rotate(360deg); } }
          .hub-card-aurora::before {
            content: "";
            position: absolute; inset: -55%;
            background: conic-gradient(from 0deg,
              var(--aurora-a), var(--aurora-b),
              var(--aurora-c), var(--aurora-a));
            animation: hubAurora 18s linear infinite;
            opacity: .55;
            filter: blur(34px);
            z-index: 0;
            pointer-events: none;
          }
          .hub-card-aurora::after {
            content: "";
            position: absolute; inset: 0;
            background: var(--aurora-veil);
            z-index: 1;
            pointer-events: none;
          }
        `}</style>
        <div data-testid="cliente-hub-grid" style={{
          display: "grid", gap: 14, gridTemplateColumns: "1fr",
        }}>
          <HubCard
            testid="hub-card-indique"
            pillLabel="● PROGRAMA INDIQUE E GANHE"
            title="Indique e Ganhe"
            subtagline="Ganhe R$ 50 a cada amigo que instalar"
            tagline={<>Convide amigos<br/>e <span style={{color:"#FF8A3B"}}>ganhe PIX</span> </>}
            accent={COLORS.orange}
            // gradiente "aurora" mais quente — laranja + rosa girando sobre roxo escuro
            auroraA="rgba(255,138,59,.55)"
            auroraB="rgba(244,114,182,.55)"
            auroraC="rgba(124,58,237,.40)"
            auroraVeil="linear-gradient(165deg, rgba(58,15,138,.10) 0%, rgba(26,8,64,.55) 100%)"
            baseBg="linear-gradient(135deg, #4C1D95 0%, #2e0b70 70%, #1a0840 100%)"
            decorIcon="indique"
            onClick={onOpenIndique}
          />
          <HubCard
            testid="hub-card-minha-ligo"
            pillLabel="● SUA ÁREA PRIVADA"
            title="Minha Ligo"
            subtagline="Acompanhe seu plano, baixe boletos, peça desbloqueio e veja seu histórico."
            tagline={<><span style={{fontSize:"1.45em"}}>2ª via</span>
              <span style={{display: "block",fontSize:"0.5em",opacity:.85,
                marginTop:6,fontWeight:600}}>rápida e segura</span></>}
            accent="#C4B5FD"
            // gradiente roxo claro tipo o screenshot de referência
            auroraA="rgba(167,139,250,.55)"
            auroraB="rgba(139,92,246,.50)"
            auroraC="rgba(91,33,182,.45)"
            auroraVeil="linear-gradient(165deg, rgba(124,58,237,.05) 0%, rgba(58,15,138,.35) 100%)"
            baseBg="linear-gradient(135deg, #8B5CF6 0%, #7C3AED 55%, #5B21B6 100%)"
            decorIcon="check"
            onClick={onOpenMinhaLigo}
          />
        </div>
      </motion.div>

      <p style={{
        margin: "28px 22px 0", textAlign: "center",
        fontSize: 12, fontWeight: 600, color: COLORS.slate500,
      }}>
        Toque em um card pra continuar.
      </p>
    </Shell>
  );
}

/* ───────────────────────── HubCard ───────────────────────── */
function HubCard({ testid, pillLabel, title, tagline, subtagline, accent,
  auroraA, auroraB, auroraC, auroraVeil, baseBg, decorIcon, onClick }) {
  return (
    <motion.button
      onClick={onClick}
      data-testid={testid}
      className="hub-card-aurora"
      variants={{
        hidden: { opacity: 0, y: 24 },
        show: { opacity: 1, y: 0,
          transition: { duration: .5, ease: [0.22, 1, 0.36, 1] } },
      }}
      whileHover={{ y: -4 }}
      whileTap={{ scale: .98 }}
      style={{
        position: "relative", overflow: "hidden",
        textAlign: "left", border: "none", cursor: "pointer",
        padding: 24, borderRadius: 28,
        background: baseBg, color: "white",
        boxShadow: "0 26px 60px rgba(20,8,60,.45), 0 8px 22px rgba(20,8,60,.25)",
        minHeight: 240, fontFamily: FONT_DISPLAY,
        // CSS vars consumidos pelo ::before/::after definidos no Hub style block
        "--aurora-a": auroraA,
        "--aurora-b": auroraB,
        "--aurora-c": auroraC,
        "--aurora-veil": auroraVeil,
      }}>
      {/* Ícone decorativo grande no canto direito (✓ shield ou ) */}
      {decorIcon === "check" && (
        <svg aria-hidden viewBox="0 0 100 110" style={{
          position: "absolute", top: 18, right: -14,
          width: 130, height: 145, zIndex: 2,
          opacity: .35, pointerEvents: "none",
        }}>
          <path d="M50 4 L92 22 V58 C92 80 72 100 50 106 C28 100 8 80 8 58 V22 Z"
            fill="rgba(255,255,255,.18)"
            stroke="rgba(255,255,255,.35)" strokeWidth="2"/>
          <path d="M28 56 L44 72 L74 38"
            stroke="white" strokeWidth="7"
            strokeLinecap="round" strokeLinejoin="round" fill="none"/>
        </svg>
      )}
      {decorIcon === "indique" && (
        <span aria-hidden style={{
          position: "absolute", top: 16, right: 18,
          fontSize: 56, zIndex: 2,
          opacity: .45, pointerEvents: "none",
          filter: "drop-shadow(0 8px 18px rgba(255,106,26,.55))",
        }}></span>
      )}
      {decorIcon === "promo" && (
        <span aria-hidden style={{
          position: "absolute", top: 16, right: 18,
          fontSize: 56, zIndex: 2,
          opacity: .55, pointerEvents: "none",
          filter: "drop-shadow(0 8px 18px rgba(252,211,77,.55))",
        }}></span>
      )}

      <div style={{
        position: "relative", zIndex: 3,
        height: "100%", display: "flex", flexDirection: "column",
        justifyContent: "space-between", gap: 16,
      }}>
        {pillLabel && (
          <span style={{
            display: "inline-flex", alignSelf: "flex-start",
            padding: "6px 12px", borderRadius: 999,
            background: "rgba(255,255,255,.16)",
            border: "1px solid rgba(255,255,255,.25)",
            fontSize: 10.5, fontWeight: 800, letterSpacing: 1.8,
            color: "rgba(255,255,255,.92)",
            textTransform: "uppercase",
            backdropFilter: "blur(6px)",
          }}>{pillLabel}</span>
        )}

        <div>
          <div style={{
            fontSize: 13, fontWeight: 700, letterSpacing: 2.4,
            textTransform: "uppercase", opacity: .8,
            marginBottom: 6,
          }}>{title}</div>
          <div style={{
            fontSize: "clamp(34px, 7vw, 46px)", fontWeight: 900,
            letterSpacing: "-.025em", lineHeight: 1.0,
            color: "white",
            textShadow: "0 6px 20px rgba(0,0,0,.25)",
          }}>{tagline}</div>
          <div style={{
            marginTop: 14, fontSize: 13.5,
            color: "rgba(255,255,255,.82)",
            fontWeight: 500, lineHeight: 1.45, maxWidth: 320,
          }}>{subtagline}</div>

          <div style={{
            marginTop: 18, display: "inline-flex", alignItems: "center",
            gap: 6, padding: "9px 16px", borderRadius: 999,
            background: accent, color: "#1a0840",
            fontWeight: 900, fontSize: 13, letterSpacing: .4,
            boxShadow: "0 12px 28px rgba(20,8,60,.35)",
          }}>Abrir <ChevronRight size={16} strokeWidth={3} /></div>
        </div>
      </div>
    </motion.button>
  );
}
