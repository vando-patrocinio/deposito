/**
 * Recorta um avatar quadrado centralizado no rosto a partir de uma selfie.
 * Usa a FaceDetector API nativa (Chrome/Edge mobile) quando disponível.
 * Fallback: recorte quadrado centralizado no terço superior (onde fica o rosto
 * em selfies frontais).
 *
 * Retorna sempre um dataURL JPEG quadrado (default 320×320) — pronto pra ser
 * salvo como avatar_data_url / foto_id do colaborador.
 */
export async function cropAvatarFromSelfie(dataUrl, size = 320) {
  if (!dataUrl || typeof dataUrl !== "string") return null;
  try {
    const img = await _loadImage(dataUrl);
    const box = await _detectFace(img);

    // Define a área quadrada a recortar
    let { sx, sy, sSize } = _squareCropFromBox(img, box);

    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) return dataUrl;
    ctx.drawImage(img, sx, sy, sSize, sSize, 0, 0, size, size);
    return canvas.toDataURL("image/jpeg", 0.88);
  } catch (e) {
    // Falha silenciosa — devolve o original
    return dataUrl;
  }
}

function _loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

async function _detectFace(img) {
  // FaceDetector API (Chrome/Edge mobile)
  if (typeof window !== "undefined" && "FaceDetector" in window) {
    try {
      const det = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 });
      const faces = await det.detect(img);
      if (faces && faces.length > 0 && faces[0].boundingBox) {
        return faces[0].boundingBox; // {x,y,width,height}
      }
    } catch { /* ignora — vai pro fallback */ }
  }
  return null;
}

function _squareCropFromBox(img, box) {
  const W = img.naturalWidth || img.width;
  const H = img.naturalHeight || img.height;

  if (box) {
    // Expande a bounding box pra incluir mais cabeça/ombros (margem 60%)
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    const margin = 1.6;
    let sSize = Math.max(box.width, box.height) * margin;
    // Não ultrapassa as dimensões da imagem
    sSize = Math.min(sSize, W, H);
    let sx = Math.round(cx - sSize / 2);
    let sy = Math.round(cy - sSize / 2);
    // Clamp aos limites
    sx = Math.max(0, Math.min(sx, W - sSize));
    sy = Math.max(0, Math.min(sy, H - sSize));
    return { sx, sy, sSize: Math.round(sSize) };
  }

  // Fallback: recorte quadrado biased pro topo (rosto fica em ~28% da altura)
  const sSize = Math.min(W, H);
  const sx = Math.round((W - sSize) / 2);
  // Em selfies verticais (H > W), puxa pro topo
  const sy = H > W ? Math.round((H - sSize) * 0.18) : Math.round((H - sSize) / 2);
  return { sx, sy, sSize };
}
