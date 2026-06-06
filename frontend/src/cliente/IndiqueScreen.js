/* IndiqueScreen — tela completa do programa Indique e Ganhe.
 *
 * Estrutura (scroll vertical):
 *   1. HeaderHero "OLÁ, Maria " + "Bem-vindo ao Indique & Ganhe da Ligo"
 *   2. ProfileSheet (avatar + nome + CPF + plano + filial)
 *   3. Hero card "● PROGRAMA INDIQUE E GANHE" com headline gigante +
 *      info box + 3 steps INDICA → INSTALA → PIX
 *   4. Invite Link card (URL + Copiar + WhatsApp + QR toggle)
 *   5. KPIs (4 stats)
 *   6. Tier Progress + chips Bronze/Prata/Ouro/Diamante
 *   7. Projeção 30d
 *   8. Leaderboard anônimo (top 5 + sua posição)
 *   9. Lista de indicações
 *  10. PIX + payout request
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { QRCodeSVG } from "qrcode.react";
import { ArrowRight, Check, Copy, MessageCircle, QrCode, Send } from "lucide-react";

import { COLORS, FONT_DISPLAY, pill, titleCase } from "@/cliente/ligo-theme";
import {
  Shell, HeaderHero, ProfileSheet, GlassCard, WhiteCard,
  OrangeCTA, PillBadge,
} from "@/cliente/components";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const http = (tk) => axios.create({
  baseURL: API,
  headers: tk ? { Authorization: `Bearer ${tk}` } : {},
});

export default function IndiqueScreen({ token, me, setMe, onBack, onLogout }) {
  const [stats, setStats] = useState(null);
  const [refs, setRefs] = useState([]);
  const [board, setBoard] = useState(null);

  const refresh = async () => {
    const c = http(token);
    const [s, r, b] = await Promise.all([
      c.get("/customer/stats").then((x) => x.data).catch(() => null),
      c.get("/customer/referrals").then((x) => x.data.items).catch(() => []),
      c.get("/customer/leaderboard").then((x) => x.data).catch(() => null),
    ]);
    setStats(s); setRefs(r); setBoard(b);
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [token]);

  const firstName = titleCase((me?.name || "").split(" ")[0] || "Amigo(a)");
  const inviteUrl = `${window.location.origin}/r/${me.referral_code}`;

  return (
    <Shell testid="indique-screen">
      <HeaderHero
        greeting="Olá,"
        greetingName={firstName}
        greetingEmoji=""
        subtitle={<>Bem-vindo ao{" "}
          <span style={{ color: "#FFB070", fontWeight: 900 }}>
            Indique & Ganhe
          </span>{" "}da Ligo </>}
        onBack={onBack}
        onLogout={onLogout}
        height={290}
      />

      <ProfileSheet me={me} marginTop={-66} />

      {/* Hero card — Programa Indique e Ganhe */}
      <div style={{ padding: "22px 16px 0" }}>
        <ProgramHeroCard />
      </div>

      {/* KPIs */}
      {stats && (
        <div style={{ padding: "14px 16px 0" }}>
          <KpisStrip stats={stats} />
        </div>
      )}

      {/* Invite Link */}
      <div style={{ padding: "14px 16px 0" }}>
        <InviteLinkCard inviteUrl={inviteUrl} code={me.referral_code} />
      </div>

      {/* Tier Progress */}
      {stats && (
        <div style={{ padding: "14px 16px 0" }}>
          <TierProgressCard stats={stats} />
        </div>
      )}

      {/* Projection */}
      {stats?.projection && (
        <div style={{ padding: "14px 16px 0" }}>
          <ProjectionCard p={stats.projection} />
        </div>
      )}

      {/* Leaderboard */}
      {board?.leaderboard?.length > 0 && (
        <div style={{ padding: "14px 16px 0" }}>
          <LeaderboardCard board={board} />
        </div>
      )}

      {/* Referrals */}
      <div style={{ padding: "14px 16px 0" }}>
        <ReferralsListCard items={refs} />
      </div>

      {/* PIX & Payout */}
      <div style={{ padding: "14px 16px 0" }}>
        <PixPayoutCard token={token} me={me} setMe={setMe}
          stats={stats} onAfter={refresh} />
      </div>
    </Shell>
  );
}

/* ──────────────────── ProgramHeroCard ──────────────────── */
function ProgramHeroCard() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 26 }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: .55, ease: [0.22, 1, 0.36, 1] }}
      data-testid="indique-program-hero"
      style={{
        position: "relative", overflow: "hidden",
        padding: "26px 24px 26px",
        background: `linear-gradient(140deg, #7c3aed 0%, #5b21b6 55%, #3a0f8a 100%)`,
        borderRadius: 28, color: "white",
        boxShadow: "0 28px 64px rgba(58,15,138,.42)",
        fontFamily: FONT_DISPLAY,
      }}>
      {/* Decor circles à direita (imitando screenshot #4) */}
      <span aria-hidden style={{
        position: "absolute", top: -10, right: -30, width: 140, height: 140,
        borderRadius: "50%",
        border: "1.5px solid rgba(255,255,255,.18)",
      }} />
      <span aria-hidden style={{
        position: "absolute", top: 20, right: 8, width: 70, height: 70,
        borderRadius: "50%",
        background: "radial-gradient(circle at 35% 35%, #ff6a1a, #b13800 70%)",
        boxShadow: "0 12px 30px rgba(255,106,26,.45)",
      }} />

      <span style={pill("rgba(255,255,255,.12)", "#FFE6D2")}>
        <span style={{ width: 7, height: 7, borderRadius: "50%",
          background: "#FF6A1A", boxShadow: "0 0 10px #FF6A1A" }} />
        Programa Indique e Ganhe
      </span>

      <h2 data-testid="indique-headline" style={{
        marginTop: 18,
        fontSize: "clamp(34px, 8vw, 46px)", fontWeight: 900,
        letterSpacing: "-.025em", lineHeight: 1.04,
        color: "white",
        maxWidth: 540,
        textShadow: "0 4px 20px rgba(0,0,0,.2)",
      }}>
        Indique um amigo<br />
        e <span style={{
          color: "#FF6A1A",
          background: "linear-gradient(180deg, #ff8a3b, #ff6a1a)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}>ganhe R$ 50 no PIX.</span>
      </h2>

      {/* Info box */}
      <div style={{
        marginTop: 18, padding: "14px 16px",
        background: "rgba(255,255,255,.1)",
        border: "1px solid rgba(255,255,255,.18)",
        borderRadius: 18, fontSize: 14, lineHeight: 1.5,
        color: "rgba(255,255,255,.95)", fontWeight: 500,
      }}>
        <span style={{ fontSize: 16 }}>️</span>{" "}
        Compartilhe seu link agora e ganhe seu{" "}
        <b style={{ color: "#FFB070" }}>primeiro R$ 50</b>{" "}
        quando um amigo instalar.
      </div>

      {/* 3 steps */}
      <div style={{
        marginTop: 18, display: "grid",
        gridTemplateColumns: "1fr 22px 1fr 22px 1fr",
        gap: 0, alignItems: "stretch",
      }}>
        <StepTile emoji="" label="INDICA" />
        <Arrow />
        <StepTile emoji="" label="INSTALA" />
        <Arrow />
        <StepTile emoji="" label="PIX" highlight />
      </div>
    </motion.div>
  );
}

function StepTile({ emoji, label, highlight }) {
  return (
    <div style={{
      padding: "14px 6px 12px",
      borderRadius: 16,
      background: highlight
        ? "linear-gradient(135deg, #FF6A1A, #ff8a3b)"
        : "rgba(255,255,255,.08)",
      border: highlight
        ? "1px solid rgba(255,255,255,.35)"
        : "1px solid rgba(255,255,255,.14)",
      textAlign: "center",
      boxShadow: highlight ? "0 14px 30px rgba(255,106,26,.45)" : "none",
    }}>
      <div style={{ fontSize: 30, lineHeight: 1 }}>{emoji}</div>
      <div style={{
        marginTop: 6, fontSize: 12, fontWeight: 900, letterSpacing: 1.5,
        color: highlight ? "#1a0840" : "white",
      }}>{label}</div>
    </div>
  );
}
const Arrow = () => (
  <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
    opacity: .6, color: "white" }}>
    <ArrowRight size={16} strokeWidth={2.5} />
  </div>
);

/* ──────────────────── KpisStrip ──────────────────── */
function KpisStrip({ stats }) {
  const items = [
    { k: "Indicados", v: stats.total_indicated, color: "#a5b4fc" },
    { k: "Instalados", v: stats.installed, color: "#86efac" },
    { k: "Saldo", v: `R$ ${(stats.available_brl || 0).toFixed(2)}`,
      color: "#FFB070" },
    { k: "Total ganho", v: `R$ ${(stats.earned_total_brl || 0).toFixed(0)}`,
      color: "#fde68a" },
  ];
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      data-testid="indique-kpis"
      style={{
        display: "grid", gap: 8,
        gridTemplateColumns: "1fr 1fr 1fr 1fr",
      }}>
      {items.map((i) => (
        <div key={i.k} style={{
          padding: "14px 8px", borderRadius: 16, textAlign: "center",
          background: "white", border: "1px solid #ede5ff",
          boxShadow: "0 8px 20px rgba(20,8,60,.06)",
        }}>
          <div style={{
            fontSize: "clamp(18px, 4.2vw, 22px)", fontWeight: 900,
            color: COLORS.slate900, letterSpacing: "-.02em",
            fontFamily: FONT_DISPLAY,
          }}>{i.v}</div>
          <div style={{ fontSize: 10.5, fontWeight: 700,
            color: COLORS.slate500, marginTop: 4,
            letterSpacing: .8, textTransform: "uppercase" }}>
            {i.k}
          </div>
          <div style={{ height: 3, width: 26, margin: "8px auto 0",
            background: i.color, borderRadius: 999 }} />
        </div>
      ))}
    </motion.div>
  );
}

/* ──────────────────── InviteLinkCard ──────────────────── */
function InviteLinkCard({ inviteUrl, code }) {
  const [copied, setCopied] = useState(false);
  const [showQR, setShowQR] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  };

  const msg = `Oi! Tô usando a Ligo Fibra e indicando pra você. `
    + `Internet rápida, estável, atendimento de verdade. `
    + `Cadastra teus dados aqui que a equipe te chama: ${inviteUrl}`;
  const wa = `https://wa.me/?text=${encodeURIComponent(msg)}`;

  return (
    <WhiteCard testid="indique-invite-card">
      <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
        textTransform: "uppercase", color: COLORS.orange,
        marginBottom: 10 }}>
        Seu link de indicação
      </div>

      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "12px 14px", borderRadius: 14,
        background: "#F4F1FF", border: "1px dashed #C4B0FF",
      }}>
        <code data-testid="indique-invite-url" style={{
          flex: 1, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap", fontSize: 13, fontWeight: 700,
          color: COLORS.purpleBase,
        }}>{inviteUrl}</code>
        <button onClick={copy} className="ligo-tap"
          data-testid="indique-copy-link"
          style={{
            padding: "8px 12px", borderRadius: 10, border: "none",
            background: copied ? COLORS.green : COLORS.purpleBase,
            color: "white", fontSize: 12, fontWeight: 800, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 4,
          }}>
          {copied ? <><Check size={14} /> Copiado</> : <><Copy size={14} /> Copiar</>}
        </button>
      </div>

      <div style={{ marginTop: 10, display: "grid", gap: 8,
        gridTemplateColumns: "1fr 1fr" }}>
        <a href={wa} target="_blank" rel="noreferrer"
          className="ligo-tap"
          data-testid="indique-share-whatsapp"
          style={{
            padding: "14px 14px", borderRadius: 14, textAlign: "center",
            background: "linear-gradient(135deg, #25D366, #128C7E)",
            color: "white", fontWeight: 900, fontSize: 14,
            textDecoration: "none", display: "inline-flex",
            alignItems: "center", justifyContent: "center", gap: 8,
            boxShadow: "0 12px 26px rgba(37,211,102,.4)",
          }}><MessageCircle size={18} /> WhatsApp</a>
        <button onClick={() => setShowQR((x) => !x)}
          className="ligo-tap"
          data-testid="indique-qr-toggle"
          style={{
            padding: "14px 14px", borderRadius: 14, border: "none",
            background: "white",
            border: `1.5px solid ${COLORS.purpleBase}`,
            color: COLORS.purpleBase, fontWeight: 900, fontSize: 14,
            cursor: "pointer",
            display: "inline-flex", alignItems: "center",
            justifyContent: "center", gap: 8,
          }}><QrCode size={18} /> {showQR ? "Ocultar QR" : "Mostrar QR"}</button>
      </div>

      {showQR && (
        <motion.div
          initial={{ opacity: 0, y: 8, scale: .96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: .35 }}
          data-testid="indique-qr-box" style={{
            marginTop: 12, padding: 18, borderRadius: 18,
            background: "#F4F1FF", border: "1px solid #DCCFFF",
            display: "flex", justifyContent: "center",
          }}>
          <div style={{ background: "white", padding: 12, borderRadius: 14 }}>
            <QRCodeSVG value={inviteUrl} size={200}
              fgColor={COLORS.purpleDeep} bgColor="#ffffff" level="M" />
          </div>
        </motion.div>
      )}

      <p style={{ marginTop: 12, fontSize: 12, color: COLORS.slate500,
        lineHeight: 1.5 }}>
        Código:{" "}
        <code style={{
          color: COLORS.orange, fontWeight: 900,
          background: "#FFF1E5", padding: "2px 8px", borderRadius: 6,
        }}>{code}</code>{" "}
        · Cada amigo que instalar a Ligo te dá{" "}
        <b style={{ color: COLORS.orange }}>R$ 50 no PIX</b>.
      </p>
    </WhiteCard>
  );
}

/* ──────────────────── TierProgressCard ──────────────────── */
function TierProgressCard({ stats }) {
  const { current_tier, next_tier, installed, missing_for_next, tiers } = stats;
  const target = next_tier?.min_installs || (current_tier?.min_installs || 5);
  const base = current_tier?.min_installs || 0;
  const pct = next_tier
    ? Math.min(100, Math.max(4, ((installed - base) / (target - base)) * 100))
    : 100;

  return (
    <WhiteCard testid="indique-tier-card">
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
          textTransform: "uppercase", color: COLORS.orange,
          display: "inline-flex", alignItems: "center", gap: 8 }}>
          <Medal level={current_tier?.label || "Bronze"} size={20} />
          Sua jornada
        </div>
        <div style={{ fontSize: 12, color: COLORS.slate500, fontWeight: 700 }}>
          {current_tier ? `Nível ${current_tier.label}` : "Sem nível ainda"}
        </div>
      </div>

      <div style={{
        height: 14, borderRadius: 999, overflow: "hidden",
        background: "#F4F1FF", border: "1px solid #DCCFFF",
        position: "relative",
      }}>
        <motion.div
          initial={{ width: 0 }} animate={{ width: `${pct}%` }}
          transition={{ duration: 1, ease: "easeOut" }}
          style={{
            height: "100%",
            background: "linear-gradient(90deg, #FF6A1A, #ff8a3b, #ffb070)",
            backgroundSize: "200% 100%",
            animation: "shimmer 3s linear infinite",
          }} />
      </div>

      {next_tier ? (
        <div style={{ marginTop: 12, fontSize: 14, lineHeight: 1.5,
          color: COLORS.slate700 }}>
          Faltam{" "}
          <b style={{ color: COLORS.orange }}>
            {missing_for_next} instalação(ões)
          </b>{" "}
          pro nível <b>{next_tier.label}</b>.<br />
          <span style={{ color: COLORS.slate500, fontSize: 12.5 }}>
            Recompensa: {next_tier.prize}
          </span>
        </div>
      ) : (
        <div style={{ marginTop: 12, fontSize: 14,
          display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Medal level="Diamante" size={22} /> Nível máximo! Cada nova
          indicação ainda te dá R$ 50.
        </div>
      )}

      <div style={{
        marginTop: 18,
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8,
      }}>
        {tiers.map((t) => {
          const reached = installed >= t.min_installs;
          const isCurrent = current_tier?.label === t.label;
          return (
            <motion.div
              key={t.level}
              whileHover={{ y: -3 }}
              animate={isCurrent ? { scale: [1, 1.04, 1] } : { scale: 1 }}
              transition={isCurrent
                ? { duration: 2, repeat: Infinity, ease: "easeInOut" }
                : { duration: .25 }}
              style={{
                padding: "12px 6px 10px", borderRadius: 14, textAlign: "center",
                background: isCurrent
                  ? "linear-gradient(180deg, #FFF7ED, #FFE6D2)"
                  : reached ? "#F0FDF4" : "#F8FAFC",
                border: `1.5px solid ${isCurrent
                  ? COLORS.orange
                  : reached ? "#86efac" : "#E2E8F0"}`,
                boxShadow: isCurrent
                  ? "0 10px 22px rgba(255,106,26,.18)"
                  : "none",
                opacity: reached || isCurrent ? 1 : 0.55,
                filter: (reached || isCurrent) ? "none" : "grayscale(.4)",
              }}>
              <div style={{ display: "flex", justifyContent: "center",
                marginBottom: 4 }}>
                <Medal level={t.label} size={42} dim={!reached && !isCurrent} />
              </div>
              <div style={{
                fontSize: 11, fontWeight: 900, letterSpacing: .4,
                color: isCurrent ? "#9a3412"
                  : reached ? "#065f46" : COLORS.slate500,
              }}>{t.label}</div>
              <div style={{ fontSize: 10, color: COLORS.slate500,
                fontWeight: 700, marginTop: 1 }}>
                {t.min_installs}+
              </div>
            </motion.div>
          );
        })}
      </div>
    </WhiteCard>
  );
}

/* ──────────────────── Medal (SVG inline) ──────────────────── */
/** Renderiza medalha vetorial por nível.
 *  Usa gradient próprio de cada metal (Bronze, Prata, Ouro, Diamante).
 *  Quando `dim`, fica em escala de cinza pra indicar nível ainda não atingido.
 */
function Medal({ level, size = 40, dim = false }) {
  const id = React.useId();
  const palette = {
    Bronze: { a: "#FFD7A8", b: "#C97B3C", c: "#7B3F18", ribbon: "#8C2F2F" },
    Prata: { a: "#F8FAFC", b: "#C0C7CF", c: "#6B7280", ribbon: "#1E3A8A" },
    Ouro: { a: "#FFF3B0", b: "#F5C842", c: "#A66B00", ribbon: "#9A0030" },
    Diamante: { a: "#E0F2FE", b: "#7DD3FC", c: "#0284C7", ribbon: "#1E40AF" },
  }[level] || { a: "#FFD7A8", b: "#C97B3C", c: "#7B3F18", ribbon: "#8C2F2F" };

  return (
    <svg width={size} height={size * 1.25} viewBox="0 0 64 80"
      style={{ filter: dim ? "grayscale(.85) opacity(.65)" : "none" }}
      aria-label={`Medalha ${level}`}>
      <defs>
        <radialGradient id={`g-${id}`} cx="35%" cy="32%" r="68%">
          <stop offset="0%" stopColor={palette.a} />
          <stop offset="55%" stopColor={palette.b} />
          <stop offset="100%" stopColor={palette.c} />
        </radialGradient>
        <linearGradient id={`r-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={palette.ribbon} stopOpacity=".95" />
          <stop offset="100%" stopColor={palette.ribbon} stopOpacity=".7" />
        </linearGradient>
      </defs>
      {/* Fitas */}
      <path d="M18 4 L24 30 L20 48 L14 26 Z" fill={`url(#r-${id})`} />
      <path d="M46 4 L40 30 L44 48 L50 26 Z" fill={`url(#r-${id})`} />
      {/* Disco */}
      <circle cx="32" cy="46" r="22" fill={`url(#g-${id})`}
        stroke={palette.c} strokeWidth="1.5" />
      <circle cx="32" cy="46" r="16" fill="none"
        stroke={palette.a} strokeOpacity=".7" strokeWidth="1" />
      {/* Estrela central */}
      {level === "Diamante" ? (
        <path d="M32 36 L36 44 L44 46 L36 48 L32 56 L28 48 L20 46 L28 44 Z"
          fill="white" opacity=".9" />
      ) : (
        <path d="M32 36 L34.5 43 L42 43 L36 47.5 L38.5 54.5 L32 50 L25.5 54.5 L28 47.5 L22 43 L29.5 43 Z"
          fill="white" opacity=".82" />
      )}
      {/* Brilho diagonal */}
      <ellipse cx="26" cy="40" rx="6" ry="3" fill="white" opacity=".4"
        transform="rotate(-25 26 40)" />
    </svg>
  );
}

/* ──────────────────── ProjectionCard ──────────────────── */
function ProjectionCard({ p }) {
  if (!p || !p.projected_total_brl) return null;
  return (
    <WhiteCard testid="indique-projection-card">
      <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
        textTransform: "uppercase", color: COLORS.orange,
        marginBottom: 6 }}>
        Projeção 30 dias
      </div>
      <div style={{
        fontSize: 36, fontWeight: 900, letterSpacing: "-.02em",
        color: COLORS.slate900, fontFamily: FONT_DISPLAY,
      }}>R$ {p.projected_total_brl.toFixed(2)}</div>
      <div style={{ fontSize: 12.5, color: COLORS.slate500,
        marginTop: 4, fontWeight: 600 }}>
        ≈ {p.projected_installs_30d} instalação(ões) ·
        {" "}{p.conversion_pct}% conversão
      </div>
    </WhiteCard>
  );
}

/* ──────────────────── LeaderboardCard ──────────────────── */
function LeaderboardCard({ board }) {
  return (
    <WhiteCard testid="indique-leaderboard-card">
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
          textTransform: "uppercase", color: COLORS.orange }}>
          Ranking do mês
        </div>
        {board.my_rank && (
          <span style={{ fontSize: 11.5, color: COLORS.orange,
            fontWeight: 800 }}>Você: #{board.my_rank}</span>
        )}
      </div>
      {board.leaderboard.map((row) => (
        <div key={row.rank} style={{
          display: "flex", alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 12px", borderRadius: 12, marginBottom: 6,
          background: row.is_you ? "#FFF1E5" : "#FAFAFA",
          border: row.is_you
            ? "1px solid rgba(255,106,26,.4)"
            : "1px solid #f0f0f0",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{
              width: 28, height: 28, borderRadius: "50%",
              display: "inline-flex", alignItems: "center",
              justifyContent: "center",
              background: row.rank === 1 ? "#fde68a"
                : row.rank === 2 ? "#cbd5e1"
                : row.rank === 3 ? "#fdba74"
                : "#F4F1FF",
              color: row.rank <= 3 ? "#1a0840" : COLORS.slate700,
              fontSize: 12, fontWeight: 900,
            }}>{row.rank}</span>
            <span style={{ fontSize: 13.5, fontWeight: 800,
              color: COLORS.slate900 }}>
              {row.is_you ? "Você" : row.name_masked}
            </span>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 14, fontWeight: 900, color: COLORS.orange,
              fontFamily: FONT_DISPLAY }}>
              R$ {row.total_brl.toFixed(0)}
            </div>
            <div style={{ fontSize: 10.5, color: COLORS.slate500,
              fontWeight: 600 }}>
              {row.installs} instal.
            </div>
          </div>
        </div>
      ))}
    </WhiteCard>
  );
}

/* ──────────────────── ReferralsListCard ──────────────────── */
const STATUS_LABEL = {
  pending: { label: "Pendente", color: "#f59e0b", bg: "#FEF3C7" },
  contacted: { label: "Em contato", color: "#3b82f6", bg: "#DBEAFE" },
  converting: { label: "Negociando", color: "#8b5cf6", bg: "#EDE9FE" },
  contracted: { label: "Contrato", color: "#10b981", bg: "#D1FAE5" },
  installed: { label: "Instalado", color: "#059669", bg: "#A7F3D0" },
  lost: { label: "Não fechou", color: "#dc2626", bg: "#FEE2E2" },
};

function ReferralsListCard({ items }) {
  if (!items?.length) {
    return (
      <WhiteCard testid="indique-refs-empty">
        <div style={{ textAlign: "center", padding: "16px 4px" }}>
          <div style={{ fontSize: 40, marginBottom: 6 }}></div>
          <div style={{ fontWeight: 900, fontSize: 17,
            color: COLORS.slate900, fontFamily: FONT_DISPLAY }}>
            Você ainda não indicou ninguém
          </div>
          <p style={{ color: COLORS.slate500, fontSize: 13,
            marginTop: 6, lineHeight: 1.5 }}>
            Clica em <b>WhatsApp</b> ali em cima e manda pra quem você acha
            que vai gostar. A gente faz o resto.
          </p>
        </div>
      </WhiteCard>
    );
  }

  return (
    <WhiteCard testid="indique-refs-list">
      <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
        textTransform: "uppercase", color: COLORS.orange,
        marginBottom: 12 }}>
        Suas indicações ({items.length})
      </div>
      {items.map((r, idx) => {
        const s = STATUS_LABEL[r.status] || {
          label: r.status, color: COLORS.slate500, bg: "#F1F5F9" };
        return (
          <div key={r.id || idx} style={{
            display: "flex", justifyContent: "space-between",
            alignItems: "flex-start",
            padding: "12px 14px", borderRadius: 12, marginBottom: 8,
            background: "#FAFAFA", border: "1px solid #f0f0f0",
          }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: 800, fontSize: 14,
                color: COLORS.slate900 }}>
                {r.friend_name || "Amigo sem nome"}
              </div>
              <div style={{ fontSize: 12, color: COLORS.slate500,
                marginTop: 2 }}>
                {r.friend_phone || "—"}
                {r.friend_neighborhood ? ` · ${r.friend_neighborhood}` : ""}
              </div>
              {r.status === "installed" && (
                <div style={{ marginTop: 6, fontSize: 12.5,
                  color: "#059669", fontWeight: 700 }}>
                  ✓ R$ 50 creditado no seu saldo
                </div>
              )}
            </div>
            <span style={{
              padding: "5px 10px", borderRadius: 999, fontSize: 11,
              fontWeight: 800, color: s.color, background: s.bg,
              flexShrink: 0,
            }}>{s.label}</span>
          </div>
        );
      })}
    </WhiteCard>
  );
}

/* ──────────────────── PixPayoutCard ──────────────────── */
function PixPayoutCard({ token, me, setMe, stats, onAfter }) {
  const [pixKey, setPixKey] = useState(me.pix_key || "");
  const [pixType, setPixType] = useState(me.pix_key_type || "cpf");
  const [savingPix, setSavingPix] = useState(false);
  const [pixMsg, setPixMsg] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("pix");
  const [requesting, setRequesting] = useState(false);
  const [payMsg, setPayMsg] = useState("");

  const available = stats?.available_brl || 0;

  const savePix = async () => {
    setSavingPix(true); setPixMsg("");
    try {
      await http(token).put("/customer/pix-key",
        { pix_key: pixKey, pix_key_type: pixType });
      setMe({ ...me, pix_key: pixKey, pix_key_type: pixType });
      setPixMsg("Chave PIX salva!");
    } catch (e) {
      setPixMsg(e?.response?.data?.detail || "Erro ao salvar.");
    } finally { setSavingPix(false); }
  };

  const requestPayout = async () => {
    const a = parseFloat(amount);
    if (!a || a <= 0) { setPayMsg("Informe um valor maior que zero."); return; }
    setRequesting(true); setPayMsg("");
    try {
      await http(token).post("/customer/payout-request",
        { method, amount: a });
      setPayMsg("Pedido enviado! Você será notificado quando aprovado.");
      setAmount("");
      onAfter && onAfter();
    } catch (e) {
      setPayMsg(e?.response?.data?.detail || "Erro ao solicitar.");
    } finally { setRequesting(false); }
  };

  return (
    <>
      {/* PIX key */}
      <WhiteCard testid="indique-pix-card" style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
          textTransform: "uppercase", color: COLORS.orange,
          marginBottom: 10 }}>
          Sua chave PIX
        </div>
        <div style={{ display: "grid",
          gridTemplateColumns: "130px 1fr", gap: 8 }}>
          <select value={pixType} onChange={(e) => setPixType(e.target.value)}
            data-testid="indique-pix-type" style={inp()}>
            <option value="cpf">CPF</option>
            <option value="cnpj">CNPJ</option>
            <option value="email">E-mail</option>
            <option value="phone">Telefone</option>
            <option value="aleatoria">Aleatória</option>
          </select>
          <input value={pixKey} onChange={(e) => setPixKey(e.target.value)}
            data-testid="indique-pix-key-input"
            placeholder="Sua chave PIX" style={inp()} />
        </div>
        <div style={{ marginTop: 12 }}>
          <OrangeCTA testid="indique-pix-save"
            onClick={savePix}
            disabled={savingPix || pixKey.length < 4}>
            {savingPix ? "Salvando…" : "Salvar chave PIX"}
          </OrangeCTA>
        </div>
        {pixMsg && <Msg text={pixMsg} />}
      </WhiteCard>

      {/* Solicitar saque */}
      <WhiteCard testid="indique-payout-card">
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
          textTransform: "uppercase", color: COLORS.orange,
          marginBottom: 10 }}>
          Solicitar saque
        </div>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", padding: "12px 14px",
          background: "linear-gradient(135deg, #FFF1E5, #FFE6D2)",
          border: "1px solid #FFCEAA",
          borderRadius: 14, marginBottom: 12,
        }}>
          <span style={{ fontSize: 12, color: COLORS.slate700,
            fontWeight: 700, letterSpacing: .6,
            textTransform: "uppercase" }}>
            Saldo disponível
          </span>
          <span data-testid="indique-balance" style={{
            fontSize: 26, fontWeight: 900, color: COLORS.orange,
            fontFamily: FONT_DISPLAY, letterSpacing: "-.02em",
          }}>R$ {available.toFixed(2)}</span>
        </div>

        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr",
          gap: 8, marginBottom: 10,
        }}>
          <button onClick={() => setMethod("pix")}
            data-testid="indique-method-pix"
            style={methodBtn(method === "pix")}>PIX</button>
          <button onClick={() => setMethod("invoice_discount")}
            data-testid="indique-method-invoice"
            style={methodBtn(method === "invoice_discount")}>
            Desconto fatura
          </button>
        </div>

        <input type="number" min="1" step="0.01"
          placeholder="Valor (R$)" value={amount}
          onChange={(e) => setAmount(e.target.value)}
          data-testid="indique-amount-input" style={inp()} />
        <div style={{ marginTop: 12 }}>
          <OrangeCTA testid="indique-pix-submit-btn"
            onClick={requestPayout}
            disabled={requesting || !amount || parseFloat(amount) <= 0
              || parseFloat(amount) > available}>
            {requesting
              ? "Enviando…"
              : <><Send size={16} /> Solicitar agora</>}
          </OrangeCTA>
        </div>
        {payMsg && <Msg text={payMsg} />}
        {stats && (
          <div style={{
            marginTop: 14, fontSize: 12, color: COLORS.slate500,
            lineHeight: 1.5,
          }}>
            Total ganho: R$ {stats.earned_total_brl.toFixed(2)}{" "}
            · Aguardando aprovação: R$ {stats.pending_brl.toFixed(2)}{" "}
            · Já pago: R$ {stats.paid_out_brl.toFixed(2)}
          </div>
        )}
      </WhiteCard>
    </>
  );
}

function Msg({ text }) {
  if (!text) return null;
  const ok = /salv|enviad/i.test(text) && !/erro|inválid|fal/i.test(text);
  return (
    <div data-testid="indique-msg" style={{
      marginTop: 10, padding: "10px 12px", borderRadius: 12,
      fontSize: 13, fontWeight: 700,
      background: ok ? "#D1FAE5" : "#FEE2E2",
      color: ok ? "#065f46" : "#991b1b",
      border: `1px solid ${ok ? "#86efac" : "#fca5a5"}`,
    }}>{text}</div>
  );
}

const inp = () => ({
  width: "100%", boxSizing: "border-box",
  background: "white",
  border: `1.5px solid ${COLORS.slate200}`,
  borderRadius: 12, color: COLORS.slate900,
  fontSize: 14, padding: "12px 14px",
  outline: "none", fontWeight: 600,
});

const methodBtn = (active) => ({
  padding: "12px", borderRadius: 12, cursor: "pointer",
  fontWeight: 800, fontSize: 13.5,
  background: active
    ? "linear-gradient(135deg, #FFF1E5, #FFE6D2)"
    : "white",
  color: active ? COLORS.purpleBase : COLORS.slate500,
  border: `1.5px solid ${active ? COLORS.orange : COLORS.slate200}`,
});
