import React, { useState, useEffect } from "react";
import { api } from "@/api";
import VehicleCameraOverlay from "@/fleet/VehicleCameraOverlay";

/**
 * WeeklyInspectionFlow — fluxo mobile da vistoria semanal de veículo.
 *
 * Fluxo: KM (com input) → frente → traseira → lat_dir → lat_esq → submit.
 * Após submit, dispara IA review (resultado em ~1-2 min).
 * Soft block (escolha 2c): apenas avisa, não trava operação.
 */
const POSITIONS = [
  { key: "km", label: "Odômetro (KM)", icon: "📊", needsKm: true },
  { key: "frente", label: "Frente", icon: "🚗" },
  { key: "traseira", label: "Traseira", icon: "🔙" },
  { key: "lat_dir", label: "Lateral direita", icon: "➡️" },
  { key: "lat_esq", label: "Lateral esquerda", icon: "⬅️" },
];

export default function WeeklyInspectionFlow({ onClose, onDefer }) {
  const [inspection, setInspection] = useState(null);
  const [activePosition, setActivePosition] = useState(null);
  const [kmValue, setKmValue] = useState("");
  const [uploadingPos, setUploadingPos] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [submittedOk, setSubmittedOk] = useState(false);

  useEffect(() => { start(); /* eslint-disable-line */ }, []);

  async function start() {
    setBusy(true); setErr("");
    try {
      const r = await api.fleetInspectionStart();
      setInspection(r.inspection);
      if (r.inspection?.km_informado) setKmValue(String(r.inspection.km_informado));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleCapture(dataUrl) {
    if (!inspection) return;
    const pos = activePosition;
    setActivePosition(null);
    setUploadingPos(pos);
    try {
      const body = { position: pos, data_url: dataUrl };
      if (pos === "km") {
        const km = parseInt(kmValue, 10);
        if (!km || km < 0) { setErr("Informe o KM atual."); setUploadingPos(null); return; }
        body.km_value = km;
      }
      await api.fleetInspectionUpload(inspection.id, body);
      // refetch atualiza photos object
      const fresh = await api.fleetInspectionGet(inspection.id);
      setInspection(fresh);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setUploadingPos(null);
  }

  async function submitAll() {
    setBusy(true); setErr("");
    try {
      await api.fleetInspectionSubmit(inspection.id);
      setSubmittedOk(true);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  const photos = inspection?.photos || {};
  const allDone = POSITIONS.every((p) => photos[p.key]);

  if (activePosition) {
    return (
      <VehicleCameraOverlay
        position={activePosition}
        onCapture={handleCapture}
        onCancel={() => setActivePosition(null)}
      />
    );
  }

  if (submittedOk) {
    return (
      <div data-testid="inspection-success" style={{
        padding: 28, textAlign: "center",
      }}>
        <div style={{ fontSize: 56 }}>✅</div>
        <h2 style={{ fontSize: 22, fontWeight: 700, margin: "12px 0 8px" }}>
          Vistoria enviada!
        </h2>
        <p style={{ color: "#475569", fontSize: 14, lineHeight: 1.5 }}>
          A IA está revisando suas fotos. Você poderá ver o resultado em alguns
          minutos. Boa rota! 🚗
        </p>
        <button
          data-testid="inspection-done-btn"
          onClick={onClose}
          style={{
            marginTop: 20, padding: "12px 28px",
            background: "#0ea5e9", color: "white", border: "none",
            borderRadius: 10, fontWeight: 700, fontSize: 15,
          }}>
          Voltar para Lousa
        </button>
      </div>
    );
  }

  return (
    <div data-testid="weekly-inspection-flow" style={{
      padding: 16, maxWidth: 540, margin: "0 auto",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 16, gap: 10,
      }}>
        <h2 style={{ fontSize: 19, fontWeight: 700, margin: 0,
                       color: "#0f172a", flex: 1 }}>
          🚗 Vistoria semanal do veículo
        </h2>
        {onDefer && (
          <button
            data-testid="inspection-defer-btn"
            onClick={onDefer}
            style={{
              padding: "8px 12px", background: "#f1f5f9",
              color: "#64748b", border: "1px solid #e2e8f0",
              borderRadius: 8, fontSize: 12, fontWeight: 600,
            }}>
            Adiar hoje
          </button>
        )}
      </div>

      <div style={{
        background: "#fef3c7", border: "1px solid #fcd34d",
        padding: 12, borderRadius: 10, marginBottom: 16,
        fontSize: 13, color: "#92400e", lineHeight: 1.4,
      }}>
        Tire <strong>5 fotos do veículo</strong> nesta ordem. A IA vai comparar
        com a semana anterior. Demora ~3 minutos.
      </div>

      {err && (
        <div style={{
          background: "#fee2e2", color: "#991b1b", padding: 10,
          borderRadius: 8, marginBottom: 12, fontSize: 13,
        }}>{err}</div>
      )}

      {busy && !inspection && (
        <div style={{ textAlign: "center", color: "#64748b", padding: 24 }}>
          Carregando vistoria…
        </div>
      )}

      {inspection && (
        <>
          {/* KM input */}
          <div style={{
            background: "white", border: "1px solid #e2e8f0",
            borderRadius: 12, padding: 14, marginBottom: 12,
          }}>
            <label style={{ fontSize: 13, color: "#475569", fontWeight: 600 }}>
              KM atual do odômetro
            </label>
            <input
              data-testid="inp-km"
              type="number"
              value={kmValue}
              onChange={(e) => setKmValue(e.target.value)}
              placeholder="Ex: 45230"
              style={{
                width: "100%", padding: "10px 12px", marginTop: 6,
                border: "1px solid #cbd5e1", borderRadius: 8,
                fontSize: 16, fontFamily: "monospace",
              }} />
          </div>

          {POSITIONS.map((p) => {
            const done = !!photos[p.key];
            return (
              <div key={p.key}
                data-testid={`insp-row-${p.key}`}
                style={{
                  background: done ? "#ecfdf5" : "white",
                  border: `1px solid ${done ? "#86efac" : "#e2e8f0"}`,
                  borderRadius: 12, padding: 12, marginBottom: 10,
                  display: "flex", alignItems: "center", gap: 12,
                }}>
                <div style={{ fontSize: 28 }}>{p.icon}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, color: "#0f172a", fontSize: 14 }}>
                    {p.label}
                  </div>
                  <div style={{ fontSize: 12, color: done ? "#047857" : "#64748b" }}>
                    {done ? "✓ Foto enviada" : "Toque para tirar foto"}
                  </div>
                </div>
                <button
                  data-testid={`btn-take-${p.key}`}
                  disabled={uploadingPos === p.key}
                  onClick={() => {
                    if (p.needsKm && !kmValue) { setErr("Informe o KM antes."); return; }
                    setErr("");
                    setActivePosition(p.key);
                  }}
                  style={{
                    padding: "9px 14px",
                    background: done ? "#fff" : "#0ea5e9",
                    color: done ? "#047857" : "white",
                    border: done ? "1px solid #86efac" : "none",
                    borderRadius: 8, fontWeight: 600, fontSize: 13,
                    cursor: "pointer",
                  }}>
                  {uploadingPos === p.key ? "Enviando…" : done ? "Refazer" : "Câmera"}
                </button>
              </div>
            );
          })}

          <button
            data-testid="inspection-submit-btn"
            disabled={!allDone || busy}
            onClick={submitAll}
            style={{
              width: "100%", marginTop: 14, padding: "14px",
              background: allDone ? "#10b981" : "#cbd5e1",
              color: "white", border: "none", borderRadius: 12,
              fontSize: 16, fontWeight: 700,
              cursor: allDone ? "pointer" : "not-allowed",
            }}>
            {busy ? "Enviando…" : allDone ? "✅ Concluir vistoria" : `Fotos pendentes: ${POSITIONS.filter(p => !photos[p.key]).length}`}
          </button>
        </>
      )}
    </div>
  );
}
