/*
photoStamp.js — Utilitário de selo (overlay) em fotos de campo (iter211y)

Desenha no canto inferior direito da imagem um quadro semi-transparente
contendo data/hora, endereço completo (via geocoding reverso GPS) e
identificação do dispositivo. Usado em fotos de CTO e CE para auditoria
e prova de localização real do técnico no momento da captura.

API:
  await stampFieldPhoto(dataUrl, { lat, lng, address?, label? })
    → retorna nova dataUrl (image/jpeg ~0.78) com selo aplicado.

Se `address` não é informado e GPS está disponível, faz reverse-geocode
via Nominatim com timeout de 5s. Se falhar/timeout, mostra só lat,lng.
*/

const NOMINATIM_REV = "https://nominatim.openstreetmap.org/reverse";

async function reverseGeocodeShort(lat, lng) {
  if (lat == null || lng == null) return null;
  try {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 5000);
    const url = `${NOMINATIM_REV}?format=json&lat=${lat}&lon=${lng}&addressdetails=1&zoom=18&accept-language=pt-BR`;
    const r = await fetch(url, { signal: ctrl.signal });
    clearTimeout(tid);
    if (!r.ok) return null;
    const j = await r.json();
    const a = j.address || {};
    // Monta endereço curto BR: rua, nº — bairro, cidade/UF
    const rua = a.road || a.pedestrian || a.footway || "";
    const num = a.house_number ? `, ${a.house_number}` : "";
    const bairro = a.suburb || a.neighbourhood || a.village || "";
    const cidade = a.city || a.town || a.municipality || "";
    const uf = a.state_code || (a.state ? a.state.slice(0, 2).toUpperCase() : "");
    const linhas = [];
    if (rua) linhas.push(`${rua}${num}`);
    const l2 = [bairro, cidade && uf ? `${cidade}/${uf}` : (cidade || uf)]
      .filter(Boolean).join(" — ");
    if (l2) linhas.push(l2);
    return linhas.length ? linhas.join("\n") : (j.display_name || null);
  } catch {
    return null;
  }
}

function detectDevice() {
  const ua = (navigator.userAgent || "").trim();
  // Tenta extrair modelo Android: "Linux; Android 14; SM-G990B"
  const mAndroid = ua.match(/Android\s+\d+(?:\.\d+)?\s*;\s*([^;)]+?)\s*(?:Build|\))/i);
  if (mAndroid) return mAndroid[1].trim();
  // iPhone/iPad genérico
  if (/iPhone/i.test(ua)) return "iPhone";
  if (/iPad/i.test(ua)) return "iPad";
  // Windows/Mac fallback
  if (/Windows/i.test(ua)) return "Windows";
  if (/Macintosh/i.test(ua)) return "Mac";
  return navigator.platform || "Dispositivo";
}

function pad(n) { return String(n).padStart(2, "0"); }
function fmtNow() {
  const d = new Date();
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Desenha o selo no canto inferior direito de um canvas já contendo a imagem.
 * Internamente quebra as linhas pra caber em até 65% da largura do canvas.
 */
function drawStamp(ctx, canvasW, canvasH, lines) {
  const padding = Math.round(Math.max(8, canvasW * 0.012));
  const fontSize = Math.round(Math.max(11, canvasW * 0.018));
  const lineH = Math.round(fontSize * 1.32);
  const family = "system-ui, -apple-system, Roboto, sans-serif";

  ctx.save();
  ctx.font = `600 ${fontSize}px ${family}`;
  ctx.textBaseline = "top";

  // Quebra linhas longas: cada `line` pode ter \n internos OU pode ser
  // longa demais e precisar de wrap.
  const maxLineWidth = Math.round(canvasW * 0.55);
  const wrapped = [];
  lines.forEach((raw) => {
    String(raw).split("\n").forEach((part) => {
      if (!part) return;
      let cur = "";
      part.split(/\s+/).forEach((word) => {
        const test = cur ? `${cur} ${word}` : word;
        if (ctx.measureText(test).width > maxLineWidth && cur) {
          wrapped.push(cur);
          cur = word;
        } else {
          cur = test;
        }
      });
      if (cur) wrapped.push(cur);
    });
  });

  const boxW = Math.max(
    180,
    ...wrapped.map((l) => Math.ceil(ctx.measureText(l).width)),
  ) + padding * 2;
  const boxH = padding * 2 + wrapped.length * lineH;

  const x = canvasW - boxW - Math.round(canvasW * 0.012);
  const y = canvasH - boxH - Math.round(canvasH * 0.012);

  // Fundo preto semi-transparente arredondado
  const r = 6;
  ctx.fillStyle = "rgba(0, 0, 0, 0.62)";
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + boxW - r, y);
  ctx.quadraticCurveTo(x + boxW, y, x + boxW, y + r);
  ctx.lineTo(x + boxW, y + boxH - r);
  ctx.quadraticCurveTo(x + boxW, y + boxH, x + boxW - r, y + boxH);
  ctx.lineTo(x + r, y + boxH);
  ctx.quadraticCurveTo(x, y + boxH, x, y + boxH - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  ctx.fill();

  // Borda fina
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(255,255,255,0.18)";
  ctx.stroke();

  // Texto branco com sombra leve pra legibilidade
  ctx.shadowColor = "rgba(0,0,0,0.7)";
  ctx.shadowBlur = 2;
  ctx.fillStyle = "#ffffff";
  let cy = y + padding;
  wrapped.forEach((line) => {
    ctx.fillText(line, x + padding, cy);
    cy += lineH;
  });
  ctx.restore();
}

/**
 * Aplica selo de campo a uma dataUrl. Retorna nova dataUrl JPEG.
 *
 * @param {string} dataUrl - dataUrl original (já comprimida pela wizard).
 * @param {object} opts
 * @param {number|null} opts.lat - latitude do GPS no momento da captura.
 * @param {number|null} opts.lng - longitude.
 * @param {string=} opts.address - endereço pronto (pula reverse-geocode).
 * @param {string=} opts.label - rótulo opcional acima dos demais (ex: "📦 FOTO CTO").
 * @param {string=} opts.collaborator - nome do técnico que tirou a foto.
 * @param {string=} opts.element - nomenclatura do elemento de rede
 *                                  (ex: "CTO_301_0027", "CABO_LINHA_PRINCIPAL").
 *                                  iter211az
 * @returns {Promise<string>} - dataUrl com selo aplicado.
 */
export async function stampFieldPhoto(dataUrl, opts = {}) {
  if (!dataUrl) return dataUrl;
  const { lat, lng } = opts;
  let address = opts.address;
  if (!address && lat != null && lng != null) {
    address = await reverseGeocodeShort(lat, lng);
  }
  if (!address && lat != null && lng != null) {
    address = `Lat ${Number(lat).toFixed(5)}, Lng ${Number(lng).toFixed(5)}`;
  }
  const dev = detectDevice();
  const lines = [];
  if (opts.label) lines.push(opts.label);
  // iter211az — elemento de rede (CTO_301_0027 / CABO_X) e colaborador
  // ficam nas duas primeiras linhas pra leitura imediata na auditoria.
  if (opts.element) lines.push(`🔖 ${opts.element}`);
  if (opts.collaborator) lines.push(`👷 ${opts.collaborator}`);
  lines.push(`📅 ${fmtNow()}`);
  if (lat != null && lng != null) {
    lines.push(`📍 ${Number(lat).toFixed(5)}, ${Number(lng).toFixed(5)}`);
  }
  if (address) lines.push(`🏠 ${address}`);
  lines.push(`📱 ${dev}`);

  return new Promise((resolve) => {
    let settled = false;
    const safeResolve = (url) => {
      if (settled) return;
      settled = true;
      resolve(url);
    };
    // Hard timeout: nunca trava o caller, mesmo se onload/onerror nunca disparar.
    setTimeout(() => safeResolve(dataUrl), 6500);
    try {
      const img = new Image();
      img.onload = () => {
        try {
          const canvas = document.createElement("canvas");
          canvas.width = img.width;
          canvas.height = img.height;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0);
          try { drawStamp(ctx, canvas.width, canvas.height, lines); }
          catch (_e) { /* falha do stamp não derruba upload */ }
          safeResolve(canvas.toDataURL("image/jpeg", 0.82));
        } catch (_e) { safeResolve(dataUrl); }
      };
      img.onerror = () => safeResolve(dataUrl);
      img.src = dataUrl;
    } catch (_e) {
      safeResolve(dataUrl);
    }
  });
}
