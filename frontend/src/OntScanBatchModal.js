/* OntScanBatchModal.js — Scan IA em LOTE: várias ONTs em sequência.
 *
 * Uso (técnico em retirada em massa):
 *   <OntScanBatchModal open onSaved={(items) => ...} onClose={...} />
 *
 * UX:
 *  - Tela 1: câmera com viewfinder + contador "Foto N de N"
 *  - Capturar → IA lê em background → adiciona à lista
 *  - Tela 2: lista das ONTs lidas com botão "Editar" individual e "Salvar todas"
 *  - Cada ONT já vai com prova (foto base64) no payload de save
 *
 * Resultado: chama onSaved(items[]) com cada {mac, sn, confidence, image_base64}
 */
import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  Camera, CheckCircle2, X, RefreshCw, Loader2, Layers,
  Plus, Edit2, Trash2, Save, ChevronRight,
} from "lucide-react";
import { api } from "@/api";

export default function OntScanBatchModal({ open, onSaved, onClose, hint }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [view, setView] = useState("camera"); // camera | list
  const [items, setItems] = useState([]);   // [{id, mac, sn, confidence, image_base64, status: 'ok'|'reading'|'failed'}]
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState(null); // index | null
  const [saving, setSaving] = useState(false);

  const startCamera = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" },
                  width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setErr("");
    } catch (e) {
      setErr("Não consegui acessar a câmera.");
    }
  }, []);

  const stopCamera = () => {
    try { streamRef.current?.getTracks().forEach((t) => t.stop()); } catch {}
    streamRef.current = null;
  };

  useEffect(() => {
    if (!open) return;
    setView("camera"); setItems([]); setErr(""); setEditing(null);
    startCamera();
    return stopCamera;
  }, [open, startCamera]);

  // Captura uma foto, adiciona à lista com status='reading', dispara IA em background
  const captureAndQueue = async () => {
    if (!videoRef.current) return;
    const v = videoRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth || 1280;
    canvas.height = v.videoHeight || 720;
    canvas.getContext("2d").drawImage(v, 0, 0, canvas.width, canvas.height);
    const b64 = canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
    const newItem = {
      id: Math.random().toString(36).slice(2, 10),
      mac: "", sn: "", confidence: 0, image_base64: b64, status: "reading",
    };
    setItems((prev) => [...prev, newItem]);
    // Roda IA em background — não bloqueia próxima foto
    api.scanOntLabel({ image_base64: b64, hint })
      .then((r) => {
        setItems((prev) => prev.map((it) => it.id === newItem.id
          ? { ...it, mac: r.mac || "", sn: r.sn || "",
              confidence: r.confidence || 0,
              status: (r.mac || r.sn) ? "ok" : "failed" }
          : it));
      })
      .catch(() => {
        setItems((prev) => prev.map((it) => it.id === newItem.id
          ? { ...it, status: "failed" } : it));
      });
  };

  const goToList = () => {
    stopCamera();
    setView("list");
  };

  const removeItem = (id) => {
    setItems((prev) => prev.filter((it) => it.id !== id));
  };

  const updateItem = (id, patch) => {
    setItems((prev) => prev.map((it) => it.id === id ? { ...it, ...patch } : it));
  };

  const backToCamera = () => {
    setView("camera");
    startCamera();
  };

  const saveAll = async () => {
    const valid = items.filter((it) => it.status === "ok" && (it.mac || it.sn));
    if (valid.length === 0) {
      window.alert("Nenhuma ONT válida pra salvar. Tire pelo menos 1 foto que a IA leia com sucesso.");
      return;
    }
    setSaving(true);
    try {
      await onSaved?.(valid);
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const okCount = items.filter((it) => it.status === "ok").length;
  const readingCount = items.filter((it) => it.status === "reading").length;
  const failedCount = items.filter((it) => it.status === "failed").length;

  return (
    <div data-testid="ont-batch-modal" style={{
      position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,.9)",
      display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 14px", color: "#fff",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Layers size={22} />
          <div>
            <div style={{ fontWeight: 800, fontSize: 14 }}>
              Scan em Lote · ONTs
            </div>
            <div style={{ fontSize: 11, opacity: 0.8 }}>
              {items.length === 0
                ? "Tire fotos seguidas — IA lê todas"
                : `${okCount} OK · ${readingCount} lendo · ${failedCount} falhou`}
            </div>
          </div>
        </div>
        <button data-testid="ont-batch-close" onClick={onClose}
                style={{ background: "transparent", border: 0, color: "#fff", cursor: "pointer" }}>
          <X size={24} />
        </button>
      </div>

      {/* CAMERA VIEW */}
      {view === "camera" && (
        <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
          <video ref={videoRef} autoPlay playsInline muted
                  style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          {/* Viewfinder */}
          <div style={{
            position: "absolute", inset: 0, pointerEvents: "none",
            display: "grid", placeItems: "center",
          }}>
            <div data-testid="ont-batch-viewfinder" style={{
              width: "82%", maxWidth: 480, aspectRatio: "3 / 2",
              border: "3px solid #06b6d4", borderRadius: 12,
              boxShadow: "0 0 0 9999px rgba(0,0,0,.5)",
              position: "relative",
            }}>
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
                Encaixe a etiqueta da ONT aqui · foto {items.length + 1}
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
          {/* Thumbnails strip (bottom-left) */}
          {items.length > 0 && (
            <div style={{
              position: "absolute", bottom: 24, left: 14,
              display: "flex", gap: 6, alignItems: "center",
              maxWidth: "calc(50% - 20px)", overflow: "hidden",
            }}>
              {items.slice(-3).map((it) => (
                <div key={it.id} style={{
                  width: 44, height: 44, borderRadius: 8, overflow: "hidden",
                  border: `2px solid ${it.status === "ok" ? "#22c55e"
                                          : it.status === "failed" ? "#ef4444"
                                          : "#06b6d4"}`,
                  position: "relative",
                }}>
                  <img src={`data:image/jpeg;base64,${it.image_base64}`}
                        alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  {it.status === "reading" && (
                    <div style={{
                      position: "absolute", inset: 0, background: "rgba(0,0,0,.5)",
                      display: "grid", placeItems: "center",
                    }}>
                      <Loader2 size={16} color="#06b6d4" className="animate-spin" />
                    </div>
                  )}
                </div>
              ))}
              {items.length > 3 && (
                <div style={{
                  width: 44, height: 44, borderRadius: 8,
                  background: "rgba(255,255,255,.15)",
                  display: "grid", placeItems: "center",
                  color: "#fff", fontSize: 11, fontWeight: 800,
                }}>+{items.length - 3}</div>
              )}
            </div>
          )}
          {/* Capture button center bottom */}
          <div style={{
            position: "absolute", bottom: 22, left: 0, right: 0,
            display: "flex", justifyContent: "center", alignItems: "center", gap: 24,
          }}>
            <button data-testid="ont-batch-capture" onClick={captureAndQueue}
                    style={{
                      width: 72, height: 72, borderRadius: "50%",
                      background: "white", border: "5px solid #06b6d4",
                      cursor: "pointer", boxShadow: "0 4px 16px rgba(0,0,0,.6)",
                      display: "grid", placeItems: "center",
                    }}>
              <Plus size={28} color="#0e7490" />
            </button>
          </div>
          {/* Done button (top-right) */}
          {items.length > 0 && (
            <button data-testid="ont-batch-done" onClick={goToList}
                    style={{
                      position: "absolute", bottom: 36, right: 14,
                      padding: "10px 16px", borderRadius: 999,
                      background: "linear-gradient(135deg,#10b981,#059669)",
                      color: "#fff", border: 0, fontWeight: 800, fontSize: 13,
                      cursor: "pointer", boxShadow: "0 4px 12px rgba(0,0,0,.5)",
                      display: "flex", alignItems: "center", gap: 6,
                    }}>
              Revisar ({items.length}) <ChevronRight size={16} />
            </button>
          )}
        </div>
      )}

      {/* LIST/REVIEW VIEW */}
      {view === "list" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "10px 12px" }}>
          <div style={{
            background: "rgba(255,255,255,.06)", borderRadius: 10,
            padding: 12, marginBottom: 12, color: "#fff",
          }}>
            <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 4 }}>
              {items.length} foto(s) capturada(s)
            </div>
            <div style={{ fontSize: 11, opacity: 0.8, display: "flex", gap: 12, flexWrap: "wrap" }}>
              <span>✓ {okCount} lidas com sucesso</span>
              {readingCount > 0 && <span>⏳ {readingCount} processando</span>}
              {failedCount > 0 && <span>✗ {failedCount} falharam</span>}
            </div>
          </div>

          {items.map((it) => (
            <div key={it.id} data-testid={`ont-batch-item-${it.id}`}
                  style={{
                    background: "rgba(255,255,255,.08)", borderRadius: 10,
                    padding: 10, marginBottom: 8, color: "#fff",
                    display: "flex", gap: 10, alignItems: "center",
                  }}>
              <img src={`data:image/jpeg;base64,${it.image_base64}`}
                    alt="" style={{
                      width: 64, height: 64, borderRadius: 8, objectFit: "cover",
                      border: `2px solid ${it.status === "ok" ? "#22c55e"
                                              : it.status === "failed" ? "#ef4444"
                                              : "#06b6d4"}`,
                    }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                {it.status === "reading" && (
                  <div style={{ fontSize: 12, opacity: 0.8 }}>
                    <Loader2 size={12} className="animate-spin" style={{
                      display: "inline", marginRight: 6, verticalAlign: -2 }} />
                    IA lendo…
                  </div>
                )}
                {editing === it.id ? (
                  <>
                    {/* iter197 — SN é o identificador principal (input primeiro/destacado) */}
                    <input value={it.sn}
                            onChange={(e) => updateItem(it.id, { sn: e.target.value.toUpperCase() })}
                            placeholder="SN (principal)"
                            style={{
                              width: "100%", padding: "4px 8px", marginBottom: 4,
                              fontFamily: "monospace", fontSize: 14, fontWeight: 800,
                              border: "2px solid #22c55e", borderRadius: 6,
                              background: "rgba(255,255,255,.95)", color: "#0f172a",
                            }} />
                    <input value={it.mac}
                            onChange={(e) => updateItem(it.id, { mac: e.target.value.toUpperCase() })}
                            placeholder="MAC (opcional)"
                            style={{
                              width: "100%", padding: "4px 8px",
                              fontFamily: "monospace", fontSize: 11, fontWeight: 600,
                              border: "1px solid #06b6d4", borderRadius: 6,
                              background: "rgba(255,255,255,.85)", color: "#0f172a",
                            }} />
                  </>
                ) : (
                  <>
                    {/* iter197 — SN prevalente */}
                    <div style={{ fontSize: 14, fontFamily: "monospace", fontWeight: 900 }}>
                      SN: {it.sn || <span style={{ color: "#fca5a5" }}>—</span>}
                    </div>
                    <div style={{ fontSize: 10, fontFamily: "monospace", opacity: 0.7 }}>
                      MAC: {it.mac || <span style={{ color: "#fca5a5" }}>—</span>}
                    </div>
                    {it.status === "ok" && (
                      <div style={{ fontSize: 10, opacity: 0.7, marginTop: 2 }}>
                        Confiança: {Math.round((it.confidence || 0) * 100)}%
                      </div>
                    )}
                    {it.status === "failed" && (
                      <div style={{ fontSize: 10, color: "#fecaca", marginTop: 2 }}>
                        IA não leu — edite manualmente
                      </div>
                    )}
                  </>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <button data-testid={`ont-batch-edit-${it.id}`}
                        onClick={() => setEditing(editing === it.id ? null : it.id)}
                        title={editing === it.id ? "Salvar edição" : "Editar"}
                        style={{
                          padding: 6, borderRadius: 6, border: 0,
                          background: editing === it.id
                            ? "linear-gradient(135deg,#22c55e,#16a34a)"
                            : "rgba(255,255,255,.18)",
                          color: "#fff", cursor: "pointer",
                        }}>
                  {editing === it.id ? <Save size={14} /> : <Edit2 size={14} />}
                </button>
                <button data-testid={`ont-batch-remove-${it.id}`}
                        onClick={() => removeItem(it.id)}
                        title="Remover"
                        style={{
                          padding: 6, borderRadius: 6, border: 0,
                          background: "rgba(239,68,68,.3)",
                          color: "#fee2e2", cursor: "pointer",
                        }}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}

          {/* Actions */}
          <div style={{ display: "flex", gap: 10, marginTop: 16,
                          position: "sticky", bottom: 0, paddingBottom: 14,
                          background: "linear-gradient(to top, rgba(0,0,0,1) 70%, transparent)" }}>
            <button data-testid="ont-batch-back" onClick={backToCamera}
                    style={{
                      flex: 1, padding: "12px 14px", borderRadius: 8,
                      border: "1px solid #06b6d4", background: "transparent",
                      color: "#06b6d4", fontWeight: 700, fontSize: 13, cursor: "pointer",
                    }}>
              <Camera size={14} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
              Tirar mais
            </button>
            <button data-testid="ont-batch-save"
                    onClick={saveAll}
                    disabled={saving || okCount === 0}
                    style={{
                      flex: 2, padding: "12px 14px", borderRadius: 8, border: 0,
                      background: (saving || okCount === 0)
                        ? "#475569"
                        : "linear-gradient(135deg,#10b981,#059669)",
                      color: "#fff", fontWeight: 800, fontSize: 14,
                      cursor: (saving || okCount === 0) ? "not-allowed" : "pointer",
                    }}>
              {saving ? (
                <><Loader2 size={14} className="animate-spin" style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
                  Salvando…</>
              ) : (
                <><CheckCircle2 size={14} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
                  Salvar {okCount} ONT{okCount !== 1 ? "s" : ""} no estoque</>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
