import React, { useEffect, useRef, useState } from "react";
import { Button, Icon } from "@/ui";

export default function SelfieCamera({ onCapture, onCancel, eventType }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const [status, setStatus] = useState("starting");
  const [errorMsg, setErrorMsg] = useState("");
  const [countdown, setCountdown] = useState(3);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("Câmera não suportada neste navegador.");
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "user" }, width: { ideal: 720 }, height: { ideal: 960 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        setStatus("ready");
      } catch (e) {
        setErrorMsg(e?.message || "Não foi possível acessar a câmera frontal.");
        setStatus("error");
      }
    }
    start();
    return () => {
      cancelled = true;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (status !== "ready") return;
    setCountdown(3);
    const t1 = setTimeout(() => setCountdown(2), 1000);
    const t2 = setTimeout(() => setCountdown(1), 2000);
    const t3 = setTimeout(() => capture(), 3000);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  function capture() {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c) return;
    setStatus("capturing");
    const w = v.videoWidth || 720;
    const h = v.videoHeight || 960;
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d");
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(v, 0, 0, w, h);
    const dataUrl = c.toDataURL("image/jpeg", 0.82);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    onCapture(dataUrl);
  }

  return (
    <div data-testid="screen-camera">
      <Button variant="soft" onClick={onCancel} data-testid="cancel-camera-btn">← Cancelar</Button>
      <h2 style={{ margin: "14px 0 4px", fontSize: 22 }}>Selfie automática</h2>
      <p style={{ margin: "0 0 12px", color: "#64748b", fontSize: 13 }}>
        Confirmando {eventType}. Posicione o rosto no centro — a captura é automática.
      </p>

      <div style={{ position: "relative", borderRadius: 26, overflow: "hidden", background: "#020617", aspectRatio: "3/4", border: "1px solid #0f172a", boxShadow: "0 14px 30px rgba(2,6,23,.35)" }}>
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          data-testid="selfie-video"
          style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)", display: status === "error" ? "none" : "block" }}
        />
        <canvas ref={canvasRef} style={{ display: "none" }} />

        {status !== "error" && (
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none", display: "grid", placeItems: "center" }}>
            <div style={{ width: "62%", height: "74%", borderRadius: "50%", border: "3px dashed rgba(255,255,255,.75)", boxShadow: "0 0 0 9999px rgba(2,6,23,.35) inset" }} />
          </div>
        )}

        <div style={{ position: "absolute", top: 10, left: 10, right: 10, display: "flex", justifyContent: "space-between", gap: 8 }}>
          <span style={{ background: "rgba(2,6,23,.55)", color: "white", padding: "6px 10px", borderRadius: 999, fontSize: 12, fontWeight: 800 }}>
            <Icon name="camera" /> Câmera frontal
          </span>
          {status === "ready" && (
            <span data-testid="countdown" style={{ background: "#0f172a", color: "white", padding: "6px 12px", borderRadius: 999, fontSize: 12, fontWeight: 900 }}>
              Capturando em {countdown}s…
            </span>
          )}
          {status === "starting" && (
            <span style={{ background: "rgba(2,6,23,.55)", color: "white", padding: "6px 10px", borderRadius: 999, fontSize: 12, fontWeight: 800 }}>
              Abrindo câmera…
            </span>
          )}
          {status === "capturing" && (
            <span style={{ background: "#16a34a", color: "white", padding: "6px 10px", borderRadius: 999, fontSize: 12, fontWeight: 900 }}>
              <Icon name="check" /> Capturada
            </span>
          )}
        </div>

        {status === "error" && (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", padding: 18, textAlign: "center", color: "white" }}>
            <div>
              <div style={{ fontSize: 54 }}><Icon name="alert" /></div>
              <strong style={{ display: "block", fontSize: 16, marginTop: 8 }}>Câmera indisponível</strong>
              <p style={{ color: "#cbd5e1", fontSize: 13, marginTop: 8 }}>{errorMsg}</p>
              <p style={{ color: "#94a3b8", fontSize: 12 }}>Permita o acesso à câmera nas configurações do navegador.</p>
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 14 }}>
        <Button variant="secondary" onClick={onCancel} data-testid="camera-back-btn">Voltar</Button>
        <Button onClick={capture} disabled={status !== "ready"} data-testid="capture-now-btn">Capturar agora</Button>
      </div>
    </div>
  );
}
