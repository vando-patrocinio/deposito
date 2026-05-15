/**
 * WaWallpaper — papel de parede estilo WhatsApp com doodles tile-able.
 *
 * Light: fundo #efeae2 (bege-creme clássico) com doodles #d9d2c8.
 * Empty state: oval branca centralizada com mini-mascote (SVG inline).
 *
 * Uso:
 *   <WaWallpaper />                  → só o fundo tileado (cobre flex parent)
 *   <WaWallpaper empty />             → fundo + mascote oval no centro
 *
 * O SVG do tile é embutido como data-URL p/ não ter request HTTP extra.
 */
import React from "react";

/* Tile 300×300 com ~30 doodles distribuídos. Strokes simples, cor única
 * via currentColor pra trocar tema. Inspirado no wallpaper original do
 * WhatsApp Web (não é cópia byte-a-byte, mas dá a mesma vibe). */
const DOODLE_SVG = encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
<g fill="none" stroke="#d9d2c8" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" opacity="0.85">
<!-- balão de chat -->
<path d="M20 30 q0 -12 12 -12 h24 q12 0 12 12 v12 q0 12 -12 12 h-18 l-10 8 v-8 q-8 0 -8 -12 z"/>
<!-- coração -->
<path d="M82 28 q-6 -8 -14 0 q-8 8 0 18 l14 14 l14 -14 q8 -10 0 -18 q-8 -8 -14 0 z"/>
<!-- telefone -->
<rect x="118" y="14" width="20" height="36" rx="3"/>
<circle cx="128" cy="44" r="1.2" fill="#d9d2c8"/>
<!-- música -->
<path d="M160 50 l0 -28 l16 -4 l0 24"/>
<circle cx="160" cy="50" r="3"/>
<circle cx="176" cy="46" r="3"/>
<!-- câmera -->
<rect x="200" y="22" width="32" height="22" rx="2"/>
<circle cx="216" cy="33" r="6"/>
<path d="M208 22 l3 -4 h10 l3 4"/>
<!-- sol -->
<circle cx="258" cy="32" r="6"/>
<path d="M258 18 v4 M258 42 v4 M244 32 h4 M268 32 h4 M250 24 l3 3 M263 24 l-3 3 M250 40 l3 -3 M263 40 l-3 -3"/>
<!-- envelope -->
<rect x="20" y="80" width="32" height="20" rx="1"/>
<path d="M20 82 l16 12 l16 -12"/>
<!-- fone de ouvido -->
<path d="M70 100 v-4 q0 -14 14 -14 q14 0 14 14 v4"/>
<rect x="66" y="98" width="8" height="14" rx="2"/>
<rect x="94" y="98" width="8" height="14" rx="2"/>
<!-- relógio -->
<circle cx="130" cy="92" r="11"/>
<path d="M130 86 v6 l4 3"/>
<!-- lâmpada -->
<path d="M170 80 q-9 0 -9 9 q0 4 3 7 v4 h12 v-4 q3 -3 3 -7 q0 -9 -9 -9 z"/>
<path d="M167 104 h6"/>
<!-- estrela -->
<path d="M210 80 l3 8 h8 l-6 6 l2 9 l-7 -5 l-7 5 l2 -9 l-6 -6 h8 z"/>
<!-- pizza/triângulo -->
<path d="M250 80 l16 22 h-32 z"/>
<circle cx="250" cy="92" r="1.5" fill="#d9d2c8"/>
<circle cx="244" cy="98" r="1.5" fill="#d9d2c8"/>
<circle cx="256" cy="98" r="1.5" fill="#d9d2c8"/>
<!-- planeta -->
<circle cx="28" cy="150" r="8"/>
<ellipse cx="28" cy="150" rx="14" ry="4"/>
<!-- foguete -->
<path d="M72 140 q4 -10 8 -10 q4 0 8 10 v18 h-16 z"/>
<path d="M72 150 l-4 6 l4 0 M88 150 l4 6 l-4 0"/>
<circle cx="80" cy="148" r="2"/>
<!-- nuvem -->
<path d="M118 152 q-6 0 -6 -6 q0 -7 8 -7 q2 -7 10 -7 q9 0 11 8 q6 0 6 7 q0 5 -6 5 z"/>
<!-- presente -->
<rect x="170" y="138" width="20" height="20" rx="1"/>
<path d="M170 146 h20 M180 138 v20 M176 138 q-4 -6 4 -6 q8 0 4 6 M184 138 q4 -6 -4 -6 q-8 0 -4 6"/>
<!-- pipa -->
<path d="M214 138 l8 8 l-8 8 l-8 -8 z"/>
<path d="M214 154 v8 M210 158 l4 -2 l4 2"/>
<!-- microfone -->
<rect x="250" y="138" width="10" height="14" rx="5"/>
<path d="M246 150 q0 8 9 8 q9 0 9 -8 M255 158 v4 M250 162 h10"/>
<!-- compass / bússola -->
<circle cx="30" cy="210" r="11"/>
<path d="M30 202 l3 6 l-3 6 l-3 -6 z" fill="#d9d2c8"/>
<!-- xícara -->
<path d="M70 200 h20 v12 q0 6 -6 6 h-8 q-6 0 -6 -6 z"/>
<path d="M90 204 q6 0 6 6 q0 6 -6 6"/>
<path d="M74 196 q0 -4 2 -4 M80 196 q0 -4 2 -4 M86 196 q0 -4 2 -4"/>
<!-- livro -->
<path d="M114 202 q8 -4 16 0 v16 q-8 -4 -16 0 z"/>
<path d="M130 202 q8 -4 16 0 v16 q-8 -4 -16 0"/>
<!-- chave -->
<circle cx="166" cy="206" r="5"/>
<path d="M171 206 l14 0 M179 206 v4 M183 206 v4"/>
<!-- bicicleta -->
<circle cx="210" cy="216" r="6"/>
<circle cx="226" cy="216" r="6"/>
<path d="M210 216 l8 -10 l8 10 M218 206 l3 -4 h5"/>
<!-- guarda-chuva -->
<path d="M260 202 q-12 0 -12 10 h24 q0 -10 -12 -10 z"/>
<path d="M260 212 v8 q0 4 4 4"/>
<!-- avião -->
<path d="M18 268 l24 -6 l4 -4 l4 4 l-4 8 l-22 4 z"/>
<!-- balde de tinta -->
<path d="M70 260 h16 v14 h-16 z"/>
<path d="M78 274 l-2 4 q-2 3 -5 3"/>
<!-- chave inglesa -->
<path d="M110 268 q0 -6 6 -6 q6 0 6 6 l-3 3 l8 8 l4 -4 l-8 -8 l3 -3 q0 -6 -6 -6 q-9 0 -10 10 z"/>
<!-- caderno -->
<rect x="158" y="258" width="18" height="22" rx="1"/>
<path d="M162 264 h10 M162 268 h10 M162 272 h10"/>
<!-- pincel -->
<path d="M200 258 l8 8 l-12 12 l-8 -8 z"/>
<path d="M188 270 l-4 8 l8 -4"/>
<!-- termômetro -->
<path d="M240 256 v18 q-3 1 -3 4 q0 4 4 4 q4 0 4 -4 q0 -3 -3 -4 v-18 q0 -3 -2 -3 q-2 0 -2 3 z"/>
<circle cx="241" cy="278" r="3"/>
<!-- cifrão -->
<path d="M278 262 q-6 0 -6 4 q0 4 6 4 q6 0 6 4 q0 4 -6 4 M278 256 v22"/>
</g>
</svg>
`);

const TILE_URL = `url("data:image/svg+xml;utf8,${DOODLE_SVG}")`;

export function WaWallpaper({ empty = false, children = null }) {
  return (
    <div data-testid="wa-wallpaper" style={{
      flex: 1, minHeight: 0,
      position: "relative",
      backgroundColor: "#efeae2",
      backgroundImage: TILE_URL,
      backgroundRepeat: "repeat",
      backgroundSize: "300px 300px",
      overflow: "hidden",
    }}>
      {empty && (
        <div style={{
          position: "absolute", inset: 0,
          display: "grid", placeItems: "center",
        }}>
          <div data-testid="wa-empty-mascot" style={{
            width: 112, height: 112, borderRadius: "50%",
            background: "rgba(255,255,255,0.9)",
            boxShadow: "0 4px 16px rgba(15,23,42,0.08)",
            display: "grid", placeItems: "center",
            backdropFilter: "blur(4px)",
          }}>
            <Mascot />
          </div>
        </div>
      )}
      {children}
    </div>
  );
}

/* Pequeno astronauta-mascote inline (mesma vibe da imagem do usuário). */
function Mascot() {
  return (
    <svg width="72" height="72" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* corpo do astronauta */}
      <ellipse cx="36" cy="40" rx="20" ry="22" fill="#a78bfa"/>
      <ellipse cx="36" cy="38" rx="16" ry="17" fill="#1e293b"/>
      {/* visor */}
      <ellipse cx="36" cy="36" rx="11" ry="12" fill="#22d3ee" opacity="0.9"/>
      {/* olho */}
      <circle cx="33" cy="34" r="3" fill="#0f172a"/>
      <circle cx="34" cy="33" r="1" fill="#ffffff"/>
      {/* sorriso */}
      <path d="M30 40 q3 3 8 0" stroke="#0f172a" strokeWidth="1.6" strokeLinecap="round" fill="none"/>
      {/* braço com celular */}
      <rect x="48" y="22" width="10" height="14" rx="2" fill="#1e293b"/>
      <rect x="50" y="24" width="6" height="9" rx="1" fill="#22d3ee"/>
      {/* outro braço */}
      <ellipse cx="14" cy="44" rx="4" ry="6" fill="#a78bfa"/>
    </svg>
  );
}

export default WaWallpaper;
