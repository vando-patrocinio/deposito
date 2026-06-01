// iter189 — Bolha de odômetro semanal (Lousa Mobile)
// - Aparece como primeira bolha do dia (segunda) ou última bolha (sábado)
// - Quando clicada, abre modal full-screen para foto do velocímetro
// - Tira a foto com câmera traseira, mostra moldura guia padronizada
// - Claude Sonnet 4.5 Vision lê o km automaticamente
import React, { useRef, useState } from "react";
import { api } from "@/api";

export function OdometerBubble({ odom, onClick }) {
  const done = !!odom?.already_done_today;
  const isStart = odom?.kind === "start";
  return (
    <button data-testid="odom-bubble" onClick={onClick}
      style={{
        width: "100%", padding: 14, borderRadius: 18,
        background: done ? "#ecfdf5" : (isStart ? "#fffbeb" : "#fef2f2"),
        border: `2px solid ${done ? "#10b981" : (isStart ? "#f59e0b" : "#ef4444")}`,
        cursor: "pointer", textAlign: "left",
        display: "flex", gap: 10, alignItems: "center",
        boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
      }}>
      <div style={{
        width: 56, height: 56, borderRadius: "50%",
        background: done ? "#10b981" : (isStart ? "#f59e0b" : "#ef4444"),
        color: "#fff", fontSize: 28, fontWeight: 800,
        display: "grid", placeItems: "center", flexShrink: 0,
      }}>{done ? "✓" : "🚗"}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: "#0f172a" }}>
          {done ? (
            <>
              Odômetro registrado
              {odom?.current_reading?.km_final && (
                <> — <strong>{odom.current_reading.km_final.toLocaleString("pt-BR")} km</strong></>
              )}
            </>
          ) : (
            <>
              {isStart ? "🌅 Foto do velocímetro — INÍCIO da semana"
                       : "🌙 Foto do velocímetro — FIM da semana"}
            </>
          )}
        </div>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 3 }}>
          {odom?.vehicle_plate ? `${odom.vehicle_plate} · ` : ""}
          {odom?.vehicle_model || "Veículo"}
          {!done && " · Toque para tirar a foto"}
        </div>
      </div>
    </button>
  );
}

export function OdometerCaptureModal({
  collaboratorId, odom, onClose, onSaved,
}) {
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const [ai, setAi] = useState(null);
  const [manualKm, setManualKm] = useState("");
  const [err, setErr] = useState("");
  const inputRef = useRef(null);

  const onPickFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = (ev) => setPhoto(ev.target.result);
    reader.readAsDataURL(f);
    setAi(null); setErr("");
  };

  const submit = async () => {
    if (!photo) { setErr("Tire a foto antes."); return; }
    setBusy(true); setErr("");
    try {
      const r = await api.fleetOdomSubmitPublic(collaboratorId, {
        kind: odom?.kind || "start",
        photo_data_url: photo,
        vehicle_plate: odom?.vehicle_plate,
        manual_km: manualKm ? Number(manualKm) : null,
      });
      setAi(r);
      // Espera 800ms pro usuário ver o resultado
      setTimeout(() => onSaved?.(r), 800);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)",
      display: "flex", flexDirection: "column", zIndex: 2000,
    }}>
      {/* Header */}
      <div style={{
        padding: 14, color: "#fff", display: "flex",
        justifyContent: "space-between", alignItems: "center",
      }}>
        <div>
          <div style={{ fontSize: 12, opacity: 0.7, fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
            {odom?.kind === "start" ? "🌅 Início da semana"
                                     : "🌙 Fim da semana"}
          </div>
          <div style={{ fontSize: 17, fontWeight: 800, marginTop: 2 }}>
            Foto do velocímetro
          </div>
        </div>
        <button onClick={onClose} data-testid="odom-modal-close" style={{
          background: "rgba(255,255,255,0.15)", border: 0, color: "#fff",
          padding: 10, borderRadius: 8, fontSize: 18, fontWeight: 800,
          cursor: "pointer",
        }}>✕</button>
      </div>

      {/* Área da foto com moldura guia */}
      <div style={{ flex: 1, display: "flex", alignItems: "center",
                       justifyContent: "center", padding: 16,
                       position: "relative" }}>
        {!photo && (
          <div style={{
            position: "relative", width: "100%", maxWidth: 380,
            aspectRatio: "4/3", borderRadius: 16,
            background: "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",
            display: "grid", placeItems: "center",
          }}>
            {/* Moldura guia padronizada — retângulo no centro p/ enquadrar
                a área do hodômetro */}
            <div style={{
              position: "absolute",
              top: "30%", left: "20%", right: "20%", bottom: "30%",
              border: "3px dashed #fbbf24", borderRadius: 12,
              boxShadow: "0 0 0 9999px rgba(0,0,0,0.4)",
              pointerEvents: "none",
            }}>
              <div style={{
                position: "absolute", top: -32, left: "50%",
                transform: "translateX(-50%)",
                background: "#fbbf24", color: "#0f172a",
                padding: "4px 10px", borderRadius: 6,
                fontSize: 11, fontWeight: 800, whiteSpace: "nowrap",
              }}>📍 ENQUADRE O HODÔMETRO AQUI</div>
            </div>
            <div style={{ color: "#94a3b8", fontSize: 13, textAlign: "center",
                              padding: "0 20px" }}>
              Toque no botão abaixo para abrir a câmera
              <br />e enquadrar os números do hodômetro
            </div>
          </div>
        )}
        {photo && (
          <div style={{ position: "relative", maxWidth: 420,
                            maxHeight: "60vh", borderRadius: 12,
                            overflow: "hidden" }}>
            <img src={photo} alt="velocímetro" style={{
              maxWidth: "100%", maxHeight: "60vh", display: "block",
            }} />
            {ai && (
              <div style={{
                position: "absolute", left: 8, right: 8, bottom: 8,
                background: "rgba(15,23,42,0.92)", color: "#fff",
                padding: 10, borderRadius: 10,
              }}>
                <div style={{ fontSize: 11, color: "#67e8f9",
                                      fontWeight: 700, marginBottom: 3 }}>
                  ✨ IA leu (confiança {ai.ai_confidence}%)
                </div>
                <div style={{ fontSize: 22, fontWeight: 900 }}>
                  {ai.km_final ? `${ai.km_final.toLocaleString("pt-BR")} km` : "—"}
                </div>
                {ai.ai_reasoning && (
                  <div style={{ fontSize: 10, color: "#94a3b8",
                                       marginTop: 4, lineHeight: 1.4 }}>
                    {ai.ai_reasoning}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer com ações */}
      <div style={{ padding: 14, background: "#0f172a" }}>
        {err && (
          <div style={{ background: "#fee2e2", color: "#991b1b",
                            padding: 10, borderRadius: 8, marginBottom: 8,
                            fontSize: 12 }}>{err}</div>
        )}
        {photo && !ai && (
          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 11, color: "#94a3b8",
                                fontWeight: 700, marginBottom: 4,
                                display: "block" }}>
              KM (fallback manual, se IA falhar):
            </label>
            <input type="number" inputMode="numeric"
              value={manualKm}
              onChange={(e) => setManualKm(e.target.value)}
              data-testid="odom-manual-km"
              placeholder="Ex: 45230"
              style={{
                width: "100%", padding: "10px 12px", borderRadius: 8,
                fontSize: 14, border: 0, boxSizing: "border-box",
              }} />
          </div>
        )}
        <input ref={inputRef} type="file" accept="image/*"
          capture="environment" onChange={onPickFile}
          style={{ display: "none" }}
          data-testid="odom-file-input" />
        <div style={{ display: "flex", gap: 8 }}>
          {!photo && (
            <button onClick={() => inputRef.current?.click()}
              data-testid="odom-take-photo"
              style={{
                flex: 1, padding: "14px 12px", borderRadius: 10,
                background: "#0d9488", color: "#fff", border: 0,
                fontSize: 15, fontWeight: 800, cursor: "pointer",
              }}>
              📸 Abrir câmera
            </button>
          )}
          {photo && !ai && (
            <>
              <button onClick={() => { setPhoto(null); setAi(null); }}
                style={{
                  padding: "14px 16px", borderRadius: 10,
                  background: "#475569", color: "#fff", border: 0,
                  fontSize: 14, fontWeight: 700, cursor: "pointer",
                }}>Refazer</button>
              <button onClick={submit} disabled={busy}
                data-testid="odom-submit"
                style={{
                  flex: 1, padding: "14px 12px", borderRadius: 10,
                  background: "#10b981", color: "#fff", border: 0,
                  fontSize: 15, fontWeight: 800, cursor: "pointer",
                  opacity: busy ? 0.6 : 1,
                }}>
                {busy ? "Analisando..." : "✓ Confirmar foto"}
              </button>
            </>
          )}
          {ai && (
            <div style={{ flex: 1, padding: "14px 12px",
                              borderRadius: 10, background: "#10b981",
                              color: "#fff", textAlign: "center",
                              fontWeight: 800 }}>
              ✓ Salvo!
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
