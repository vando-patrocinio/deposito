/* OntScanModal.js — Câmera + IA Claude lê MAC/SN da etiqueta da ONT.
 *
 * Uso (técnico ao finalizar retirada):
 *   <OntScanModal open onScanned={(data) => ...} onClose={...} />
 *
 * UX:
 *  - Abre câmera do dispositivo (preferência: traseira)
 *  - Viewfinder overlay: retângulo destacado onde a etiqueta deve ficar
 *  - Botão "Capturar" tira a foto, envia para /api/stok/retirada/scan-ont
 *  - Mostra resultado MAC/SN com confiança; usuário pode aceitar ou refazer
 *
 * Resultado: chama onScanned({mac, sn, confidence, image_base64})
 */
import React, { useEffect, useRef, useState } from "react";
import { Camera, CheckCircle2, X, RefreshCw, Loader2 } from "lucide-react";
import { api } from "@/api";

export default function OntScanModal({ open, onScanned, onClose, hint,
                                       isFullUnlock = false, expectedMac = "",
                                       usePublic = false }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const canvasRef = useRef(null);
  const [stage, setStage] = useState("camera"); // camera | preview | reading | result
  const [imgB64, setImgB64] = useState("");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  // Abre a câmera (traseira) quando o modal abre
  useEffect(() => {
    if (!open) return;
    let mounted = true;
    setStage("camera"); setImgB64(""); setResult(null); setErr("");
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (!mounted) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch (e) {
        setErr("Não consegui acessar a câmera. Permita o acesso e tente novamente.");
      }
    })();
    return () => {
      mounted = false;
      try { streamRef.current?.getTracks().forEach((t) => t.stop()); } catch {}
      streamRef.current = null;
    };
  }, [open]);

  const capture = () => {
    if (!videoRef.current) return;
    const v = videoRef.current;
    const canvas = canvasRef.current || document.createElement("canvas");
    canvasRef.current = canvas;
    const w = v.videoWidth || 1280;
    const h = v.videoHeight || 720;
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(v, 0, 0, w, h);
    const b64 = canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
    setImgB64(b64);
    setStage("preview");
    // Para a câmera para economizar bateria
    try { streamRef.current?.getTracks().forEach((t) => t.stop()); } catch {}
  };

  const retake = () => {
    setImgB64(""); setResult(null); setErr("");
    setStage("camera");
    // Re-abre câmera
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } }, audio: false,
        });
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
      } catch (e) {
        setErr("Não consegui acessar a câmera.");
      }
    })();
  };

  const readWithAI = async () => {
    setStage("reading"); setErr("");
    try {
      // iter221 — quando o modal está no PWA do colaborador (Google
      // session token, sem JWT), usa a rota pública /public/scan-ont —
      // senão devolveria 401 "Não autenticado" mesmo o usuário estando
      // logado no PWA. Mesma lógica do /api/lousa/public/ocr-sn.
      const r = await (usePublic
        ? api.scanOntLabelPublic({ image_base64: imgB64, hint })
        : api.scanOntLabel({ image_base64: imgB64, hint }));
      // Modo Teste (Vando/super_admin): se a IA falhou (sem MAC/SN), auto-preenche
      // com o MAC esperado (vindo do SmartOLT) ou um mock TEST-XXXX para liberar o fluxo.
      if (isFullUnlock && !r?.mac && !r?.sn) {
        const fallback = (expectedMac || "TESTMAC000001").toUpperCase();
        setResult({
          ok: true,
          mac: fallback,
          sn: fallback,
          confidence: 1,
          auto_filled_test: true,
        });
      } else {
        setResult(r);
      }
      setStage("result");
    } catch (e) {
      // Em Modo Teste, ainda assim libera com mock pra não travar o tester.
      if (isFullUnlock) {
        const fallback = (expectedMac || "TESTMAC000001").toUpperCase();
        setResult({
          ok: true,
          mac: fallback, sn: fallback,
          confidence: 1, auto_filled_test: true,
        });
        setStage("result");
        return;
      }
      setErr(e?.response?.data?.detail || e.message || "Erro na leitura IA");
      setStage("preview");
    }
  };

  const accept = () => {
    onScanned?.({
      mac: result?.mac || "",
      sn: result?.sn || "",
      confidence: result?.confidence || 0,
      image_base64: imgB64,
    });
  };

  if (!open) return null;

  return (
    <div data-testid="ont-scan-modal" style={{
      position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,.85)",
      display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 14px", color: "#fff",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Camera size={20} />
          <div>
            <div style={{ fontWeight: 800, fontSize: 14 }}>Scan da ONT/ONU</div>
            <div style={{ fontSize: 11, opacity: 0.8 }}>
              Foto da etiqueta — Claude 4.6 lê SN (e MAC quando visível)
            </div>
          </div>
        </div>
        <button data-testid="ont-scan-close"
                onClick={onClose}
                style={{ background: "transparent", border: 0, color: "#fff", cursor: "pointer" }}>
          <X size={24} />
        </button>
      </div>

      {/* Camera view */}
      {stage === "camera" && (
        <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
          <video ref={videoRef} autoPlay playsInline muted
                  style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          {/* Viewfinder overlay */}
          <div style={{
            position: "absolute", inset: 0, pointerEvents: "none",
            display: "grid", placeItems: "center",
          }}>
            <div data-testid="ont-scan-viewfinder" style={{
              width: "82%", maxWidth: 480, aspectRatio: "3 / 2",
              border: "3px solid #06b6d4",
              borderRadius: 12,
              boxShadow: "0 0 0 9999px rgba(0,0,0,.4)",
              position: "relative",
            }}>
              {/* Corners */}
              {["tl","tr","bl","br"].map((c) => {
                const pos = c === "tl" ? { top: -4, left: -4 } :
                              c === "tr" ? { top: -4, right: -4 } :
                              c === "bl" ? { bottom: -4, left: -4 } :
                                            { bottom: -4, right: -4 };
                return <div key={c} style={{
                  position: "absolute", ...pos, width: 24, height: 24,
                  borderColor: "#22d3ee", borderStyle: "solid",
                  borderTopWidth: c.startsWith("t") ? 4 : 0,
                  borderBottomWidth: c.startsWith("b") ? 4 : 0,
                  borderLeftWidth: c.endsWith("l") ? 4 : 0,
                  borderRightWidth: c.endsWith("r") ? 4 : 0,
                }} />;
              })}
              <div style={{
                position: "absolute", top: "100%", left: 0, right: 0,
                marginTop: 12, textAlign: "center", color: "#fff",
                fontSize: 13, fontWeight: 700, textShadow: "0 1px 3px rgba(0,0,0,.8)",
              }}>
                📍 Encaixe a etiqueta da ONT aqui
              </div>
            </div>
          </div>
          {err && (
            <div style={{
              position: "absolute", top: 14, left: 14, right: 14,
              background: "#fee2e2", color: "#991b1b", padding: 10,
              borderRadius: 8, fontSize: 13, textAlign: "center",
            }}>{err}</div>
          )}
          {/* Capture button */}
          <div style={{
            position: "absolute", bottom: 32, left: 0, right: 0,
            display: "flex", justifyContent: "center",
          }}>
            <button data-testid="ont-scan-capture" onClick={capture}
                    style={{
                      width: 72, height: 72, borderRadius: "50%",
                      background: "white", border: "5px solid #06b6d4",
                      cursor: "pointer", boxShadow: "0 4px 16px rgba(0,0,0,.5)",
                      display: "grid", placeItems: "center",
                    }}>
              <Camera size={26} color="#0e7490" />
            </button>
          </div>
        </div>
      )}

      {/* Preview da foto capturada */}
      {(stage === "preview" || stage === "reading") && imgB64 && (
        <div style={{
          flex: 1, padding: 16, display: "flex", flexDirection: "column",
          alignItems: "center", gap: 12, overflow: "auto",
        }}>
          <img data-testid="ont-scan-preview"
                src={`data:image/jpeg;base64,${imgB64}`}
                alt="Etiqueta capturada"
                style={{
                  maxWidth: "100%", maxHeight: "60vh",
                  borderRadius: 10, border: "2px solid #06b6d4",
                }} />
          {err && (
            <div style={{
              background: "#fee2e2", color: "#991b1b", padding: 10,
              borderRadius: 8, fontSize: 13, textAlign: "center", width: "100%",
            }}>{err}</div>
          )}
          <div style={{ display: "flex", gap: 10, marginTop: "auto" }}>
            <button data-testid="ont-scan-retake" onClick={retake}
                    disabled={stage === "reading"}
                    style={{
                      padding: "12px 18px", borderRadius: 8,
                      border: "1px solid white", background: "transparent",
                      color: "white", fontWeight: 700, fontSize: 14, cursor: "pointer",
                    }}>
              <RefreshCw size={14} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
              Refazer
            </button>
            <button data-testid="ont-scan-read" onClick={readWithAI}
                    disabled={stage === "reading"}
                    style={{
                      padding: "12px 22px", borderRadius: 8, border: 0,
                      background: stage === "reading"
                        ? "#94a3b8" : "linear-gradient(135deg,#0d9488,#06b6d4)",
                      color: "white", fontWeight: 800, fontSize: 14,
                      cursor: stage === "reading" ? "wait" : "pointer",
                    }}>
              {stage === "reading" ? (
                <><Loader2 size={14} className="animate-spin" style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
                  Lendo com IA…</>
              ) : (
                <>🤖 Ler MAC/SN com IA</>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Resultado */}
      {stage === "result" && result && (
        <div data-testid="ont-scan-result" style={{
          flex: 1, padding: 20, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", gap: 14,
        }}>
          {result.ok ? (
            <CheckCircle2 size={56} color="#22c55e" />
          ) : (
            <div style={{ fontSize: 48 }}>⚠️</div>
          )}
          <div style={{ color: "#fff", fontSize: 18, fontWeight: 800, textAlign: "center" }}>
            {result.ok ? "Leitura concluída" : "Não consegui ler com clareza"}
          </div>
          {result.auto_filled_test && (
            <div data-testid="ont-scan-auto-filled-badge" style={{
              background: "linear-gradient(135deg,#fbbf24,#f59e0b)",
              color: "#7c2d12", padding: "4px 10px", borderRadius: 999,
              fontSize: 10, fontWeight: 800, letterSpacing: 0.5,
              textTransform: "uppercase",
            }}>
              🔓 Modo Teste · auto-preenchido
            </div>
          )}
          <div style={{
            background: "rgba(255,255,255,.1)", color: "#fff",
            padding: 16, borderRadius: 12, width: "100%", maxWidth: 420,
            border: "1px solid rgba(255,255,255,.2)",
          }}>
            {/* iter197 — SN é o identificador PRINCIPAL (acima e maior) */}
            <div style={{ marginBottom: 14, paddingBottom: 12,
                            borderBottom: "1px solid rgba(255,255,255,.15)" }}>
              <div style={{ fontSize: 10, opacity: 0.7, fontWeight: 700,
                              letterSpacing: ".05em", color: "#22c55e" }}>
                SN · IDENTIFICADOR PRINCIPAL
              </div>
              <div data-testid="ont-scan-sn"
                    style={{ fontSize: 22, fontFamily: "monospace", fontWeight: 900,
                              color: result.sn ? "#fff" : "rgba(255,255,255,.4)" }}>
                {result.sn || "— não lido"}
              </div>
            </div>
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, opacity: 0.5, fontWeight: 700, letterSpacing: ".05em" }}>
                MAC (opcional)
              </div>
              <div data-testid="ont-scan-mac" style={{ fontSize: 14,
                            fontFamily: "monospace", fontWeight: 600,
                            opacity: 0.85 }}>
                {result.mac || "— não lido"}
              </div>
            </div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>
              Confiança: <strong>{Math.round((result.confidence || 0) * 100)}%</strong>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button data-testid="ont-scan-retake-result" onClick={retake}
                    style={{
                      padding: "10px 16px", borderRadius: 8,
                      border: "1px solid white", background: "transparent",
                      color: "white", fontWeight: 700, fontSize: 13, cursor: "pointer",
                    }}>
              <RefreshCw size={13} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
              Tirar outra
            </button>
            <button data-testid="ont-scan-accept"
                    onClick={accept}
                    disabled={!result.mac && !result.sn}
                    style={{
                      padding: "10px 18px", borderRadius: 8, border: 0,
                      background: (!result.mac && !result.sn) ? "#94a3b8"
                                  : "linear-gradient(135deg,#10b981,#059669)",
                      color: "white", fontWeight: 800, fontSize: 13,
                      cursor: (!result.mac && !result.sn) ? "not-allowed" : "pointer",
                    }}>
              <CheckCircle2 size={13} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
              Confirmar e usar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
