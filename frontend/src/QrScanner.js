/* =============================================================
   QrScanner — leitor de QR Code via câmera para o app do técnico
   Usa getUserMedia (câmera traseira) + jsQR para decodificar.
   Apenas tokens com prefixo "SPCTO|v1|..." são aceitos (validação
   HMAC ocorre no backend via /api/rede-ia/qrcode/scan).
============================================================= */
import React, { useEffect, useRef, useState } from "react";
import jsQR from "jsqr";
import { api } from "@/api";

export default function QrScanner({ onClose, onScan }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const rafRef = useRef(null);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        tick();
      } catch (e) {
        setError("Permissão de câmera negada ou indisponível.");
      }
    }

    function tick() {
      if (cancelled) return;
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (video && video.readyState === video.HAVE_ENOUGH_DATA && canvas) {
        const w = video.videoWidth;
        const h = video.videoHeight;
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(video, 0, 0, w, h);
        const img = ctx.getImageData(0, 0, w, h);
        const code = jsQR(img.data, w, h, { inversionAttempts: "dontInvert" });
        if (code?.data) {
          handleDetected(code.data);
          return;
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    }

    start();
    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function handleDetected(payload) {
    if (!scanning || busy) return;
    // Validação preliminar: precisa começar com SPCTO|
    if (!payload.startsWith("SPCTO|")) {
      setError("QR não é da rede SmartProv. Apenas QRs gerados pelo painel admin são aceitos.");
      return;
    }
    setScanning(false);
    setBusy(true);
    setError("");
    try {
      const r = await api.redeIaQrScan(payload);
      setResult(r);
    } catch (e) {
      const detail = e?.response?.data?.detail || "QR inválido ou expirado.";
      setError(detail);
      setScanning(true);
    } finally {
      setBusy(false);
    }
  }

  function useThisCto() {
    onScan?.(result);
  }

  function tryAgain() {
    setResult(null);
    setError("");
    setScanning(true);
  }

  return (
    <div data-testid="qr-scanner" style={{
      position: "fixed", inset: 0, background: "#000", zIndex: 9999,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        background: "rgba(0,0,0,0.7)", color: "#fff", padding: "14px 16px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <button data-testid="qr-close-btn" onClick={onClose}
                style={{ background: "transparent", border: 0, color: "#fff",
                          fontSize: 22, cursor: "pointer", padding: 4 }}>
          ✕
        </button>
        <span style={{ fontWeight: 700, fontSize: 15 }}>Ler QR Code da CTO</span>
        <span style={{ width: 28 }} />
      </div>

      {/* Camera area */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden",
                     display: "grid", placeItems: "center" }}>
        <video ref={videoRef} playsInline muted
          style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <canvas ref={canvasRef} style={{ display: "none" }} />

        {/* Overlay quadrado de foco */}
        {scanning && !result && (
          <div style={{
            position: "absolute", width: 260, height: 260,
            border: "3px solid #fff", borderRadius: 18,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.4)",
            pointerEvents: "none",
          }} />
        )}

        {busy && (
          <div style={{
            position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)",
            color: "#fff", display: "grid", placeItems: "center", fontSize: 16,
          }}>Validando QR…</div>
        )}
      </div>

      {/* Bottom panel */}
      <div style={{
        background: "#fff", padding: 18,
        boxShadow: "0 -4px 12px rgba(0,0,0,0.2)",
      }}>
        {error && (
          <div data-testid="qr-error" style={{
            background: "#fef2f2", color: "#991b1b", padding: 10,
            borderRadius: 8, fontSize: 13, marginBottom: 12,
            border: "1px solid #fecaca",
          }}>{error}</div>
        )}

        {result ? (
          <div data-testid="qr-result">
            <div style={{ fontSize: 12, color: "#64748b", fontWeight: 600,
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 4 }}>
              CTO identificada
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#5b21b6" }}>
              {result.cto?.name}
            </div>
            <div style={{ fontSize: 13, color: "#475569", marginTop: 6 }}>
              {result.cto?.address?.rua}, {result.cto?.address?.numero} ·
              {" "}{result.cto?.address?.bairro}
            </div>
            <div style={{
              display: "flex", gap: 6, flexWrap: "wrap",
              marginTop: 10, fontSize: 12, color: "#0f172a",
            }}>
              <span style={pillStyle("#dcfce7", "#15803d")}>
                {result.free_ports?.length || 0} portas livres
              </span>
              <span style={pillStyle("#fef3c7", "#92400e")}>
                {result.used_ports_count || 0} ocupadas
              </span>
              <span style={pillStyle("#ede9fe", "#5b21b6")}>
                VLAN {result.cto?.vlan}
              </span>
              {result.cto?.splitter && (
                <span style={pillStyle("#fed7aa", "#7c2d12")}>
                  Splitter {result.cto.splitter}
                </span>
              )}
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
              <button onClick={tryAgain}
                      style={btnSecondary}>Ler outro</button>
              <button data-testid="qr-use-btn" onClick={useThisCto}
                      style={btnPrimary}>Usar esta CTO</button>
            </div>
          </div>
        ) : (
          <div style={{ textAlign: "center", color: "#64748b", fontSize: 13 }}>
            Aponte a câmera para o QR Code colado na CTO. Apenas QRs gerados
            pelo SmartProv são aceitos.
          </div>
        )}
      </div>
    </div>
  );
}

const pillStyle = (bg, fg) => ({
  padding: "3px 9px", borderRadius: 999, fontSize: 11, fontWeight: 700,
  background: bg, color: fg,
});
const btnPrimary = {
  flex: 1, padding: "14px 16px", borderRadius: 10,
  background: "#5b21b6", color: "#fff", border: 0,
  fontWeight: 700, fontSize: 14, cursor: "pointer",
};
const btnSecondary = {
  ...btnPrimary, background: "#fff", color: "#0f172a",
  border: "1.5px solid #e2e8f0",
};
