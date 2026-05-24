import React, { useRef, useState, useEffect } from "react";

/**
 * SignatureCanvas — canvas de assinatura digital (touch + mouse).
 * Retorna dataUrl ao confirmar.
 */
export default function SignatureCanvas({ onConfirm, onCancel, title = "Assine aqui" }) {
  const canvasRef = useRef(null);
  const [drawing, setDrawing] = useState(false);
  const [hasInk, setHasInk] = useState(false);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = c.getBoundingClientRect();
    c.width = rect.width * ratio;
    c.height = rect.height * ratio;
    const ctx = c.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = 2.2;
    ctx.strokeStyle = "#0f172a";
    // fill background white
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, rect.width, rect.height);
  }, []);

  function pointer(evt) {
    const c = canvasRef.current;
    const rect = c.getBoundingClientRect();
    const t = evt.touches?.[0];
    const cx = (t ? t.clientX : evt.clientX) - rect.left;
    const cy = (t ? t.clientY : evt.clientY) - rect.top;
    return { x: cx, y: cy };
  }

  function start(evt) {
    evt.preventDefault();
    setDrawing(true);
    const { x, y } = pointer(evt);
    const ctx = canvasRef.current.getContext("2d");
    ctx.beginPath();
    ctx.moveTo(x, y);
  }
  function move(evt) {
    if (!drawing) return;
    evt.preventDefault();
    const { x, y } = pointer(evt);
    const ctx = canvasRef.current.getContext("2d");
    ctx.lineTo(x, y);
    ctx.stroke();
    if (!hasInk) setHasInk(true);
  }
  function end() { setDrawing(false); }

  function clear() {
    const c = canvasRef.current;
    const ctx = c.getContext("2d");
    const rect = c.getBoundingClientRect();
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, rect.width, rect.height);
    setHasInk(false);
  }

  function confirm() {
    if (!hasInk) return;
    const c = canvasRef.current;
    const dataUrl = c.toDataURL("image/png");
    onConfirm(dataUrl);
  }

  return (
    <div data-testid="signature-canvas-wrap" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.85)",
      zIndex: 9998, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 16,
    }}>
      <div style={{
        background: "white", borderRadius: 16, padding: 18,
        width: "100%", maxWidth: 520,
      }}>
        <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700,
                     color: "#0f172a" }}>{title}</h3>
        <p style={{ margin: "6px 0 12px", fontSize: 12, color: "#64748b" }}>
          Use o dedo (mobile) ou o mouse para desenhar a assinatura.
        </p>
        <div style={{
          border: "2px dashed #cbd5e1", borderRadius: 10,
          overflow: "hidden", touchAction: "none",
        }}>
          <canvas
            ref={canvasRef}
            data-testid="signature-canvas"
            style={{ width: "100%", height: 220, display: "block",
                       cursor: "crosshair" }}
            onMouseDown={start} onMouseMove={move} onMouseUp={end}
            onMouseLeave={end}
            onTouchStart={start} onTouchMove={move} onTouchEnd={end}
          />
        </div>
        <div style={{
          marginTop: 14, display: "flex", gap: 8, justifyContent: "space-between",
        }}>
          <button
            data-testid="sig-clear-btn"
            onClick={clear}
            style={{ padding: "10px 14px", background: "#f1f5f9",
                       border: "1px solid #e2e8f0", borderRadius: 8,
                       fontWeight: 600, color: "#475569" }}>
            Limpar
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              data-testid="sig-cancel-btn"
              onClick={onCancel}
              style={{ padding: "10px 16px", background: "#fff",
                         border: "1px solid #e2e8f0", borderRadius: 8,
                         fontWeight: 600, color: "#475569" }}>
              Cancelar
            </button>
            <button
              data-testid="sig-confirm-btn"
              disabled={!hasInk}
              onClick={confirm}
              style={{ padding: "10px 18px", background: hasInk ? "#10b981" : "#94a3b8",
                         color: "white", border: "none", borderRadius: 8,
                         fontWeight: 700, cursor: hasInk ? "pointer" : "not-allowed" }}>
              Confirmar assinatura
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
