import React, { useRef, useState, useEffect } from "react";

/**
 * VehicleCameraOverlay — câmera com silhuetas SVG sobrepostas.
 * Position guides:
 *  - frente, traseira, lat_dir, lat_esq → silhueta do carro
 *  - km → silhueta do odômetro (retângulo)
 */
const SILHOUETTES = {
  frente: (
    <svg viewBox="0 0 200 120" style={{ width: "100%", height: "100%", opacity: 0.55 }}>
      <path d="M30 90 Q30 50 60 40 L140 40 Q170 50 170 90 L160 90 L160 100 L150 100 L150 90 L50 90 L50 100 L40 100 L40 90 Z"
        fill="none" stroke="#fde68a" strokeWidth="2.5" strokeDasharray="4 3" />
      <circle cx="55" cy="92" r="9" fill="none" stroke="#fde68a" strokeWidth="2" />
      <circle cx="145" cy="92" r="9" fill="none" stroke="#fde68a" strokeWidth="2" />
      <rect x="78" y="58" width="44" height="20" rx="3" fill="none"
        stroke="#fde68a" strokeWidth="2" />
      <rect x="84" y="92" width="32" height="10" rx="2" fill="none"
        stroke="#fde68a" strokeWidth="2" />
      <text x="100" y="115" textAnchor="middle" fill="#fde68a" fontSize="9"
        fontFamily="system-ui" fontWeight="600">FRENTE</text>
    </svg>
  ),
  traseira: (
    <svg viewBox="0 0 200 120" style={{ width: "100%", height: "100%", opacity: 0.55 }}>
      <path d="M30 90 Q30 45 55 38 L145 38 Q170 45 170 90 L160 90 L160 100 L150 100 L150 90 L50 90 L50 100 L40 100 L40 90 Z"
        fill="none" stroke="#fde68a" strokeWidth="2.5" strokeDasharray="4 3" />
      <circle cx="55" cy="92" r="9" fill="none" stroke="#fde68a" strokeWidth="2" />
      <circle cx="145" cy="92" r="9" fill="none" stroke="#fde68a" strokeWidth="2" />
      <rect x="84" y="92" width="32" height="10" rx="2" fill="none"
        stroke="#fde68a" strokeWidth="2" />
      <rect x="40" y="55" width="14" height="8" rx="1" fill="#fde68a" opacity="0.4" />
      <rect x="146" y="55" width="14" height="8" rx="1" fill="#fde68a" opacity="0.4" />
      <text x="100" y="115" textAnchor="middle" fill="#fde68a" fontSize="9"
        fontFamily="system-ui" fontWeight="600">TRASEIRA</text>
    </svg>
  ),
  lat_dir: (
    <svg viewBox="0 0 220 100" style={{ width: "100%", height: "100%", opacity: 0.55 }}>
      <path d="M15 75 Q15 60 30 55 L60 35 L150 35 L175 55 L205 60 Q205 75 200 80 L185 80 Q185 70 175 70 Q165 70 165 80 L65 80 Q65 70 55 70 Q45 70 45 80 L25 80 Q15 80 15 75 Z"
        fill="none" stroke="#fde68a" strokeWidth="2.5" strokeDasharray="4 3" />
      <circle cx="55" cy="80" r="8" fill="none" stroke="#fde68a" strokeWidth="2" />
      <circle cx="175" cy="80" r="8" fill="none" stroke="#fde68a" strokeWidth="2" />
      <text x="110" y="98" textAnchor="middle" fill="#fde68a" fontSize="9"
        fontFamily="system-ui" fontWeight="600">LATERAL DIREITA →</text>
    </svg>
  ),
  lat_esq: (
    <svg viewBox="0 0 220 100" style={{ width: "100%", height: "100%", opacity: 0.55 }}>
      <path d="M205 75 Q205 60 190 55 L160 35 L70 35 L45 55 L15 60 Q15 75 20 80 L35 80 Q35 70 45 70 Q55 70 55 80 L155 80 Q155 70 165 70 Q175 70 175 80 L195 80 Q205 80 205 75 Z"
        fill="none" stroke="#fde68a" strokeWidth="2.5" strokeDasharray="4 3" />
      <circle cx="45" cy="80" r="8" fill="none" stroke="#fde68a" strokeWidth="2" />
      <circle cx="165" cy="80" r="8" fill="none" stroke="#fde68a" strokeWidth="2" />
      <text x="110" y="98" textAnchor="middle" fill="#fde68a" fontSize="9"
        fontFamily="system-ui" fontWeight="600">← LATERAL ESQUERDA</text>
    </svg>
  ),
  km: (
    <svg viewBox="0 0 200 120" style={{ width: "100%", height: "100%", opacity: 0.55 }}>
      <rect x="40" y="30" width="120" height="60" rx="6" fill="none"
        stroke="#fde68a" strokeWidth="2.5" strokeDasharray="4 3" />
      <text x="100" y="65" textAnchor="middle" fill="#fde68a" fontSize="13"
        fontFamily="monospace" fontWeight="700">0 0 0 0 0 0</text>
      <text x="100" y="110" textAnchor="middle" fill="#fde68a" fontSize="9"
        fontFamily="system-ui" fontWeight="600">ODÔMETRO / PAINEL</text>
    </svg>
  ),
};

const LABELS = {
  km: "Odômetro / Painel",
  frente: "Frente do veículo",
  traseira: "Traseira do veículo",
  lat_dir: "Lateral direita",
  lat_esq: "Lateral esquerda",
};

export default function VehicleCameraOverlay({ position, onCapture, onCancel }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [stream, setStream] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
          audio: false,
        });
        if (!active) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        setStream(s);
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          videoRef.current.onloadedmetadata = () => {
            videoRef.current.play();
            setStreaming(true);
          };
        }
      } catch (e) {
        setError("Não foi possível acessar a câmera: " + (e.message || e));
      }
    })();
    return () => {
      active = false;
      if (stream) stream.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line
  }, []);

  function capture() {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c) return;
    const w = v.videoWidth || 1280;
    const h = v.videoHeight || 720;
    c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    ctx.drawImage(v, 0, 0, w, h);
    const dataUrl = c.toDataURL("image/jpeg", 0.82);
    if (stream) stream.getTracks().forEach((t) => t.stop());
    onCapture(dataUrl);
  }

  return (
    <div data-testid="vehicle-camera-overlay"
      style={{
        position: "fixed", inset: 0, background: "#000", zIndex: 9999,
        display: "flex", flexDirection: "column",
      }}>
      <div style={{
        padding: "14px 16px", background: "rgba(0,0,0,0.7)",
        color: "white", display: "flex", alignItems: "center",
        justifyContent: "space-between",
      }}>
        <button
          data-testid="cam-cancel-btn"
          onClick={() => { if (stream) stream.getTracks().forEach((t) => t.stop()); onCancel(); }}
          style={{ background: "transparent", color: "white", border: "1px solid #fff5",
                    padding: "6px 12px", borderRadius: 8, fontWeight: 600 }}>
          ← Cancelar
        </button>
        <strong data-testid="cam-position-label" style={{ fontSize: 15 }}>
          {LABELS[position] || position}
        </strong>
        <span style={{ width: 80 }} />
      </div>

      <div style={{ position: "relative", flex: 1, overflow: "hidden" }}>
        <video ref={videoRef} playsInline
          style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000" }} />
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: 24,
        }}>
          <div style={{ width: "90%", maxWidth: 480 }}>
            {SILHOUETTES[position] || SILHOUETTES.frente}
          </div>
        </div>
        {error && (
          <div style={{
            position: "absolute", bottom: 0, left: 0, right: 0, padding: 16,
            background: "#dc2626", color: "white", textAlign: "center", fontSize: 13,
          }}>{error}</div>
        )}
      </div>

      <div style={{
        padding: "20px 16px 30px", background: "rgba(0,0,0,0.85)",
        display: "flex", justifyContent: "center", alignItems: "center", gap: 16,
      }}>
        <button
          data-testid="cam-capture-btn"
          disabled={!streaming}
          onClick={capture}
          style={{
            width: 72, height: 72, borderRadius: "50%",
            background: streaming ? "white" : "#666",
            border: "4px solid #fde68a", cursor: streaming ? "pointer" : "not-allowed",
            boxShadow: "0 4px 20px rgba(0,0,0,0.6)",
          }} />
      </div>
      <canvas ref={canvasRef} style={{ display: "none" }} />
    </div>
  );
}
