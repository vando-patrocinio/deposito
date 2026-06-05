/* Design tokens compartilhados pelo app /cliente — visuais Ligo Premium.
 *
 * Referência fiel aos screenshots originais que o usuário enviou:
 * gradiente roxo radial (rosa quente em cima à direita) + acento laranja
 * + "sheet card" branco sobrepondo a curva inferior do header.
 */

export const COLORS = {
  /* Roxos Ligo (profundo → vibrante) */
  purpleDeep: "#2e0b70",
  purpleBase: "#3a0f8a",
  purpleMid: "#5b21b6",
  purpleLight: "#7c3aed",
  /* Acentos */
  orange: "#FF6A1A",
  orangeHover: "#e55d12",
  orangeSoft: "#ff8a3b",
  green: "#22c55e",
  /* Surfaces */
  white: "#ffffff",
  slate900: "#0f172a",
  slate700: "#334155",
  slate500: "#64748b",
  slate200: "#e2e8f0",
};

/** Gradiente roxo radial do hero — luz pink-coral no topo direito.
 *  iter219 — agora animado (aurora girando lentamente). */
export const HERO_GRADIENT = `
  radial-gradient(900px 600px at 90% -10%, rgba(244,114,182,.35) 0%, transparent 55%),
  radial-gradient(700px 500px at 0% 20%, rgba(255,106,26,.18) 0%, transparent 60%),
  linear-gradient(170deg, ${COLORS.purpleMid} 0%, ${COLORS.purpleBase} 45%, ${COLORS.purpleDeep} 100%)
`;

/** CSS keyframes/classe que adiciona a aurora animada por trás do
 *  HERO_GRADIENT. Aplica como background animado de 200% size pra dar
 *  sensação de movimento contínuo, somado a um conic blob girando.
 *  Injetado uma única vez via Shell. */
export const HERO_ANIMATED_CSS = `
@keyframes ligoHeroFlow {
  0%   { background-position: 0% 50%, 100% 50%, 0% 50%; }
  50%  { background-position: 100% 50%, 0% 50%, 50% 50%; }
  100% { background-position: 0% 50%, 100% 50%, 0% 50%; }
}
@keyframes ligoHeroOrbit {
  0%   { transform: rotate(0deg) scale(1.15); }
  50%  { transform: rotate(180deg) scale(1.32); }
  100% { transform: rotate(360deg) scale(1.15); }
}
.ligo-hero-bg {
  background:
    radial-gradient(900px 600px at 90% -10%, rgba(244,114,182,.45) 0%, transparent 55%),
    radial-gradient(700px 500px at 0% 20%, rgba(255,106,26,.22) 0%, transparent 60%),
    linear-gradient(135deg, ${COLORS.purpleMid} 0%, ${COLORS.purpleBase} 35%, ${COLORS.purpleDeep} 100%);
  background-size: 200% 200%, 200% 200%, 240% 240%;
  background-position: 0% 50%, 100% 50%, 0% 50%;
  animation: ligoHeroFlow 22s ease-in-out infinite;
  position: relative;
}
.ligo-hero-bg::before {
  content: "";
  position: absolute; inset: -30%;
  background: conic-gradient(from 0deg,
    rgba(255,106,26,.0) 0%,
    rgba(244,114,182,.18) 18%,
    rgba(124,58,237,.22) 38%,
    rgba(255,106,26,.16) 60%,
    rgba(244,114,182,.0) 100%);
  filter: blur(48px);
  animation: ligoHeroOrbit 28s linear infinite;
  z-index: 0;
  pointer-events: none;
  mix-blend-mode: screen;
}
.ligo-hero-bg > * { position: relative; z-index: 1; }
`;

/** Fundo full-screen do login. */
export const LOGIN_GRADIENT = `
  radial-gradient(1100px 700px at 85% -10%, rgba(244,114,182,.32) 0%, transparent 60%),
  radial-gradient(900px 600px at 0% 100%, rgba(255,106,26,.18) 0%, transparent 60%),
  linear-gradient(165deg, ${COLORS.purpleMid} 0%, ${COLORS.purpleBase} 40%, ${COLORS.purpleDeep} 130%)
`;

/** Texto noise sutil — overlay opcional em SVG data-uri. */
export const NOISE_OVERLAY = "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.05 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")";

/** Font-stack: display heavy + Inter pra corpo.
 *  Sora é injetado via <link> no Shell. */
export const FONT_DISPLAY = "'Sora', 'Inter', system-ui, sans-serif";
export const FONT_BODY = "'Inter', system-ui, sans-serif";

/* ──────────────────── Style factories ──────────────────── */
export const glass = (opacity = 0.08) => ({
  background: `rgba(255,255,255,${opacity})`,
  border: "1px solid rgba(255,255,255,.16)",
  backdropFilter: "blur(18px)",
  WebkitBackdropFilter: "blur(18px)",
});

export const sheet = () => ({
  background: COLORS.white,
  borderRadius: 28,
  boxShadow: "0 30px 80px rgba(20,8,60,.28), 0 8px 22px rgba(20,8,60,.12)",
});

export const pill = (bgRgba = "rgba(255,255,255,.1)", color = "#FFE6D2") => ({
  padding: "7px 13px",
  borderRadius: 999,
  background: bgRgba,
  border: "1px solid rgba(255,255,255,.18)",
  color,
  fontSize: 11,
  fontWeight: 800,
  letterSpacing: 1.7,
  textTransform: "uppercase",
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
});

/** Inicializa um <link> pra Sora no head, uma única vez. */
export function ensureSoraFont() {
  if (typeof document === "undefined") return;
  if (document.getElementById("ligo-sora-font")) return;
  const link = document.createElement("link");
  link.id = "ligo-sora-font";
  link.rel = "stylesheet";
  link.href = "https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800;900&family=Inter:wght@400;500;600;700;800;900&display=swap";
  document.head.appendChild(link);
}

/** Formata CPF: 00000000000 → 000.000.000-00. */
export const formatCPF = (raw) => {
  const d = String(raw || "").replace(/\D/g, "").slice(0, 11);
  if (d.length <= 3) return d;
  if (d.length <= 6) return `${d.slice(0, 3)}.${d.slice(3)}`;
  if (d.length <= 9) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6)}`;
  return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
};

/** Mascara CPF para exibição: 459.***.***-63 */
export const maskCPF = (raw) => {
  const d = String(raw || "").replace(/\D/g, "");
  if (d.length !== 11) return raw || "—";
  return `${d.slice(0, 3)}.***.***-${d.slice(9)}`;
};

/** Converte string em Title Case (Pamela Nery), respeitando preposições. */
export const titleCase = (s) => {
  if (!s) return s;
  const low = new Set(["de", "da", "do", "das", "dos", "e", "di"]);
  return String(s).toLowerCase().split(/\s+/)
    .map((w, i) => (i > 0 && low.has(w)) ? w
      : w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
};

/** Pega iniciais de um nome — "Maria José Silva" → "MJ". */
export const initialsOf = (name) => {
  if (!name) return "??";
  const parts = String(name).trim().split(/\s+/);
  const first = parts[0] || "";
  const last = parts.length > 1 ? parts[parts.length - 1] : "";
  return ((first[0] || "") + (last[0] || "")).toUpperCase() || "??";
};
