/* =============================================================
   QrScanner — leitor de QR Code via câmera para o app do técnico
   Usa getUserMedia (câmera traseira) + jsQR para decodificar.
   Após validação, oferece o fluxo de vínculo cliente↔porta com
   geração automática de Ordem de Serviço (OS).
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
  // Bind step
  const [bindStep, setBindStep] = useState(false);
  const [bindForm, setBindForm] = useState({
    port_number: null,
    subscriber_name: "",
    pppoe: "",
    subscriber_phone: "",
    service_type: "instalacao",
    notes: "",
  });
  const [bindResult, setBindResult] = useState(null);

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

  // Para a câmera quando entramos no fluxo de bind/result
  useEffect(() => {
    if (bindStep || bindResult) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
    }
  }, [bindStep, bindResult]);

  function useThisCto() {
    // Abre fluxo de vínculo cliente↔porta
    setBindStep(true);
    setError("");
  }

  function tryAgain() {
    setResult(null);
    setBindResult(null);
    setBindStep(false);
    setError("");
    setScanning(true);
  }

  async function submitBind() {
    if (!bindForm.port_number) {
      setError("Selecione uma porta livre.");
      return;
    }
    if (!bindForm.subscriber_name.trim()) {
      setError("Informe o nome do cliente.");
      return;
    }
    setBusy(true); setError("");
    try {
      const r = await api.redeIaQrBindPort({
        cto_id: result.cto.id,
        port_number: bindForm.port_number,
        subscriber_name: bindForm.subscriber_name.trim(),
        pppoe: bindForm.pppoe.trim() || null,
        subscriber_phone: bindForm.subscriber_phone.trim() || null,
        service_type: bindForm.service_type,
        notes: bindForm.notes.trim() || null,
      });
      setBindResult(r);
      setBindStep(false);
    } catch (e) {
      setError(e?.response?.data?.detail || "Falha ao vincular cliente.");
    } finally {
      setBusy(false);
    }
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
                     display: "grid", placeItems: "center",
                     background: bindStep || bindResult ? "#f8fafc" : "#000" }}>
        {!bindStep && !bindResult && (
          <>
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
          </>
        )}

        {/* === Bind form === */}
        {bindStep && result && (
          <div data-testid="qr-bind-form" style={{
            padding: 18, width: "100%", height: "100%",
            overflowY: "auto", boxSizing: "border-box",
          }}>
            <div style={{ fontSize: 12, color: "#64748b", fontWeight: 600,
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
              CTO
            </div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "#5b21b6",
                            marginBottom: 16 }}>
              {result.cto?.name}
            </div>

            <label style={lbl}>Selecione a porta livre</label>
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8,
              marginBottom: 14,
            }}>
              {(result.free_ports || []).map((p) => (
                <button key={p} data-testid={`bind-port-${p}`}
                        onClick={() => setBindForm({ ...bindForm, port_number: p })}
                        style={{
                          padding: "14px 0", borderRadius: 10,
                          border: `2px solid ${bindForm.port_number === p ? "#5b21b6" : "#e2e8f0"}`,
                          background: bindForm.port_number === p ? "#5b21b6" : "#fff",
                          color: bindForm.port_number === p ? "#fff" : "#0f172a",
                          fontSize: 16, fontWeight: 700, cursor: "pointer",
                        }}>
                  {String(p).padStart(2, "0")}
                </button>
              ))}
              {(result.free_ports || []).length === 0 && (
                <div style={{ gridColumn: "1 / -1", padding: 12,
                                background: "#fef2f2", color: "#991b1b",
                                borderRadius: 8, fontSize: 12, textAlign: "center" }}>
                  Nenhuma porta livre nesta CTO.
                </div>
              )}
            </div>

            <label style={lbl}>Nome do cliente *</label>
            <input data-testid="bind-name" value={bindForm.subscriber_name}
              onChange={(e) => setBindForm({ ...bindForm, subscriber_name: e.target.value })}
              style={inp} placeholder="João da Silva" />

            <label style={lbl}>PPPoE / login (opcional)</label>
            <input data-testid="bind-pppoe" value={bindForm.pppoe}
              onChange={(e) => setBindForm({ ...bindForm, pppoe: e.target.value })}
              style={inp} placeholder="joao.silva" />

            <label style={lbl}>Telefone (opcional)</label>
            <input data-testid="bind-phone" value={bindForm.subscriber_phone}
              onChange={(e) => setBindForm({ ...bindForm, subscriber_phone: e.target.value })}
              style={inp} placeholder="21 91234-5678" />

            <label style={lbl}>Tipo de serviço</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                             gap: 6, marginBottom: 14 }}>
              {[
                { v: "instalacao", l: "Instalação" },
                { v: "manutencao", l: "Manutenção" },
                { v: "troca_porta", l: "Troca de porta" },
              ].map((opt) => (
                <button key={opt.v} data-testid={`bind-svc-${opt.v}`}
                        onClick={() => setBindForm({ ...bindForm, service_type: opt.v })}
                        style={{
                          padding: "10px 4px", borderRadius: 8,
                          border: `1.5px solid ${bindForm.service_type === opt.v ? "#5b21b6" : "#e2e8f0"}`,
                          background: bindForm.service_type === opt.v ? "#ede9fe" : "#fff",
                          fontSize: 12, fontWeight: 700, color: "#0f172a",
                          cursor: "pointer",
                        }}>
                  {opt.l}
                </button>
              ))}
            </div>

            <label style={lbl}>Observações</label>
            <textarea data-testid="bind-notes" value={bindForm.notes}
              onChange={(e) => setBindForm({ ...bindForm, notes: e.target.value })}
              rows={2} style={{ ...inp, resize: "vertical", fontFamily: "inherit" }}
              placeholder="Detalhes opcionais..." />

            <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
              <button onClick={() => { setBindStep(false); }}
                      style={btnSecondary}>Voltar</button>
              <button data-testid="bind-submit" onClick={submitBind}
                      disabled={busy} style={btnPrimary}>
                {busy ? "Enviando..." : "Vincular e abrir OS"}
              </button>
            </div>
          </div>
        )}

        {/* === Success === */}
        {bindResult && (
          <div data-testid="qr-bind-success" style={{
            padding: 30, textAlign: "center", width: "100%",
          }}>
            <div style={{
              width: 72, height: 72, borderRadius: "50%",
              background: "#dcfce7", display: "grid", placeItems: "center",
              margin: "0 auto 16px", fontSize: 36,
            }}>✓</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a",
                            marginBottom: 8 }}>
              Cliente vinculado!
            </div>
            <div style={{ fontSize: 13, color: "#64748b", lineHeight: 1.5,
                            marginBottom: 16 }}>
              <strong>{bindResult.subscriber_name}</strong> ligado na
              porta <strong>{bindResult.port_number}</strong>.
              <br />Ordem de serviço <code>{bindResult.ticket_id}</code> criada na sua fila.
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button onClick={tryAgain} style={btnSecondary}>Ler outro QR</button>
              <button onClick={() => onScan?.(bindResult)} style={btnPrimary}>
                Concluir
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Bottom panel — só na fase inicial do scan */}
      {!bindStep && !bindResult && (
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
                      style={btnPrimary}>Vincular cliente</button>
            </div>
          </div>
        ) : (
          <div style={{ textAlign: "center", color: "#64748b", fontSize: 13 }}>
            Aponte a câmera para o QR Code colado na CTO. Apenas QRs gerados
            pelo SmartProv são aceitos.
          </div>
        )}
      </div>
      )}
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
const lbl = {
  fontSize: 11, fontWeight: 600, color: "#475569",
  textTransform: "uppercase", letterSpacing: 0.4,
  display: "block", marginTop: 10, marginBottom: 6,
};
const inp = {
  width: "100%", padding: "11px 12px", borderRadius: 10,
  border: "1.5px solid #e2e8f0", fontSize: 14,
  boxSizing: "border-box", color: "#0f172a", background: "#fff",
  outline: "none",
};
