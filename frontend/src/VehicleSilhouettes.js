/* Silhuetas SVG simplificadas mas reconhecíveis para o checklist veicular.
   ViewBox padronizado em 0 0 200 110 — coordenadas dos marks são percentuais
   relativas ao viewBox, então funcionam para qualquer escala (modal e PDF). */
import React from "react";

const STROKE = "#0b1220";
const FILL = "#f1f5f9";

// Side view (lateral) — hatch profile
function SideCar({ flip = false }) {
  return (
    <g transform={flip ? "scale(-1,1) translate(-200,0)" : ""}>
      {/* corpo principal */}
      <path d="M 10 70 L 30 50 L 65 38 L 130 38 L 165 52 L 190 60 L 190 80 L 10 80 Z"
            fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      {/* coluna entre janelas */}
      <line x1="98" y1="38" x2="98" y2="60" stroke={STROKE} strokeWidth="1" />
      {/* janela dianteira */}
      <path d="M 38 52 L 65 42 L 95 42 L 95 52 Z"
            fill="#dbeafe" stroke={STROKE} strokeWidth="1" />
      {/* janela traseira */}
      <path d="M 102 42 L 130 42 L 162 52 L 102 52 Z"
            fill="#dbeafe" stroke={STROKE} strokeWidth="1" />
      {/* maçanetas */}
      <line x1="55" y1="62" x2="65" y2="62" stroke={STROKE} strokeWidth="1.2" />
      <line x1="115" y1="62" x2="125" y2="62" stroke={STROKE} strokeWidth="1.2" />
      {/* rodas */}
      <circle cx="50" cy="80" r="11" fill="#0b1220" stroke={STROKE} strokeWidth="1" />
      <circle cx="50" cy="80" r="6" fill="#94a3b8" />
      <circle cx="155" cy="80" r="11" fill="#0b1220" stroke={STROKE} strokeWidth="1" />
      <circle cx="155" cy="80" r="6" fill="#94a3b8" />
      {/* faróis */}
      <ellipse cx="14" cy="68" rx="4" ry="2.5" fill="#fde68a" stroke={STROKE} strokeWidth="0.6" />
      <ellipse cx="186" cy="68" rx="3" ry="2" fill="#fecaca" stroke={STROKE} strokeWidth="0.6" />
    </g>
  );
}

// Front view
function FrontCar() {
  return (
    <>
      {/* corpo */}
      <path d="M 30 90 L 30 50 Q 30 30 60 28 L 140 28 Q 170 30 170 50 L 170 90 Z"
            fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      {/* parabrisa */}
      <path d="M 50 50 L 60 32 L 140 32 L 150 50 Z"
            fill="#dbeafe" stroke={STROKE} strokeWidth="1" />
      {/* grade */}
      <rect x="68" y="62" width="64" height="14" fill="#0b1220" stroke={STROKE} strokeWidth="0.8" rx="2" />
      <line x1="72" y1="66" x2="128" y2="66" stroke="#475569" strokeWidth="0.8" />
      <line x1="72" y1="70" x2="128" y2="70" stroke="#475569" strokeWidth="0.8" />
      {/* faróis */}
      <rect x="34" y="55" width="22" height="10" rx="3" fill="#fde68a" stroke={STROKE} strokeWidth="0.8" />
      <rect x="144" y="55" width="22" height="10" rx="3" fill="#fde68a" stroke={STROKE} strokeWidth="0.8" />
      {/* placa */}
      <rect x="84" y="80" width="32" height="8" fill="#fff" stroke={STROKE} strokeWidth="0.6" />
      {/* retrovisores */}
      <rect x="22" y="48" width="8" height="6" fill={FILL} stroke={STROKE} strokeWidth="0.8" rx="2" />
      <rect x="170" y="48" width="8" height="6" fill={FILL} stroke={STROKE} strokeWidth="0.8" rx="2" />
      {/* roda visível */}
      <ellipse cx="44" cy="92" rx="14" ry="3" fill="#0b1220" />
      <ellipse cx="156" cy="92" rx="14" ry="3" fill="#0b1220" />
    </>
  );
}

// Rear view
function RearCar() {
  return (
    <>
      <path d="M 30 90 L 30 50 Q 30 32 60 30 L 140 30 Q 170 32 170 50 L 170 90 Z"
            fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      {/* vidro traseiro */}
      <rect x="50" y="38" width="100" height="20" rx="3" fill="#dbeafe" stroke={STROKE} strokeWidth="1" />
      {/* lanternas */}
      <rect x="34" y="62" width="26" height="12" rx="2" fill="#dc2626" stroke={STROKE} strokeWidth="0.8" />
      <rect x="140" y="62" width="26" height="12" rx="2" fill="#dc2626" stroke={STROKE} strokeWidth="0.8" />
      <line x1="35" y1="68" x2="59" y2="68" stroke="#fef2f2" strokeWidth="0.6" />
      <line x1="141" y1="68" x2="165" y2="68" stroke="#fef2f2" strokeWidth="0.6" />
      {/* placa */}
      <rect x="74" y="78" width="52" height="10" rx="1" fill="#fff" stroke={STROKE} strokeWidth="0.6" />
      {/* maçaneta porta-malas */}
      <rect x="92" y="68" width="16" height="3" rx="1" fill="#94a3b8" stroke={STROKE} strokeWidth="0.5" />
      {/* rodas */}
      <ellipse cx="44" cy="92" rx="14" ry="3" fill="#0b1220" />
      <ellipse cx="156" cy="92" rx="14" ry="3" fill="#0b1220" />
    </>
  );
}

// Top view
function TopCar() {
  return (
    <>
      <rect x="40" y="14" width="120" height="82" rx="20" ry="14"
            fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      {/* parabrisas dianteiro */}
      <path d="M 56 30 L 144 30 L 138 44 L 62 44 Z"
            fill="#dbeafe" stroke={STROKE} strokeWidth="1" />
      {/* teto */}
      <rect x="62" y="44" width="76" height="26" fill="#e2e8f0" stroke={STROKE} strokeWidth="0.6" />
      {/* parabrisas traseiro */}
      <path d="M 62 70 L 138 70 L 144 84 L 56 84 Z"
            fill="#dbeafe" stroke={STROKE} strokeWidth="1" />
      {/* divisão portas */}
      <line x1="100" y1="44" x2="100" y2="70" stroke={STROKE} strokeWidth="0.6" strokeDasharray="2 2" />
      {/* retrovisores externos */}
      <rect x="34" y="40" width="6" height="10" fill={FILL} stroke={STROKE} strokeWidth="0.8" rx="1" />
      <rect x="160" y="40" width="6" height="10" fill={FILL} stroke={STROKE} strokeWidth="0.8" rx="1" />
    </>
  );
}

const VIEWS = {
  front:  { label: "Frente",            render: <FrontCar /> },
  rear:   { label: "Traseira",          render: <RearCar /> },
  left:   { label: "Lateral esquerda",  render: <SideCar /> },
  right:  { label: "Lateral direita",   render: <SideCar flip /> },
  top:    { label: "Vista superior",    render: <TopCar /> },
};

export const VIEW_KEYS = Object.keys(VIEWS);
export const VIEW_LABELS = Object.fromEntries(
  Object.entries(VIEWS).map(([k, v]) => [k, v.label])
);

export const DAMAGE_TYPES = {
  D: { label: "Amassado",  color: "#dc2626" },
  S: { label: "Risco",     color: "#d97706" },
  R: { label: "Oxidação",  color: "#7c2d12" },
  F: { label: "Quebrado",  color: "#b91c1c" },
  V: { label: "Vidro",     color: "#0369a1" },
  P: { label: "Pintura",   color: "#475569" },
};

export default function VehicleSilhouette({ view, marks = [], onAddMark, readOnly = false, height = 130 }) {
  const conf = VIEWS[view];
  if (!conf) return null;

  const handleClick = (e) => {
    if (readOnly || !onAddMark) return;
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 200;
    const y = ((e.clientY - rect.top) / rect.height) * 110;
    onAddMark({ x: +x.toFixed(1), y: +y.toFixed(1), view });
  };

  return (
    <svg
      viewBox="0 0 200 110"
      width="100%"
      height={height}
      onClick={handleClick}
      style={{
        background: "#fff",
        border: "1px solid var(--border-default)",
        borderRadius: 8,
        cursor: readOnly ? "default" : "crosshair",
        userSelect: "none",
      }}
      data-testid={`vehicle-silhouette-${view}`}
    >
      {conf.render}
      {marks.filter((m) => m.view === view).map((m, i) => {
        const ord = m.ord ?? (i + 1);
        const color = DAMAGE_TYPES[m.code]?.color || "#dc2626";
        return (
          <g key={`${view}-${i}`} pointerEvents="none">
            <circle cx={m.x} cy={m.y} r="6" fill={color} stroke="#fff" strokeWidth="1.5" />
            <text x={m.x} y={m.y + 2.5} fill="#fff" fontSize="7" textAnchor="middle" fontWeight="700">{ord}</text>
          </g>
        );
      })}
    </svg>
  );
}
