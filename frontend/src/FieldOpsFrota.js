import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Row } from "@/ui";
import { appCard, darkBtn, fieldInput, readPhotoFile, sectionLabel, softBtn } from "@/FieldOps";

/* =============================================================
   Frota IA — vistoria semanal do veículo (KM + 4 fotos).
   Conectada ao SmartProv: /api/field/vehicle/*
============================================================= */

const SIDES = [
  { key: "front", label: "Frente" },
  { key: "rear", label: "Traseira" },
  { key: "left", label: "Lateral esquerda" },
  { key: "right", label: "Lateral direita" },
];

export default function FieldOpsFrota({ collabId, readOnly }) {
  const [status, setStatus] = useState(null);
  const [form, setForm] = useState({ plate: "", km: "", notes: "" });
  const [photos, setPhotos] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const s = await api.fieldVehicleStatus(collabId);
      setStatus(s);
      if (s.last_inspection?.plate) setForm((f) => ({ ...f, plate: f.plate || s.last_inspection.plate }));
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  }, [collabId]);
  useEffect(() => { load(); }, [load]);

  const allPhotos = SIDES.every((s) => photos[s.key]);
  const canSubmit = !readOnly && form.plate.length >= 4 && form.km !== "" && allPhotos && !busy;

  const submit = async () => {
    setBusy(true); setMsg(null); setErr(null);
    try {
      await api.fieldVehicleInspection({
        plate: form.plate.trim().toUpperCase(),
        km: parseFloat(form.km),
        photo_front: photos.front, photo_rear: photos.rear,
        photo_left: photos.left, photo_right: photos.right,
        notes: form.notes || null,
      });
      setMsg("Vistoria registrada no SmartProv");
      setPhotos({});
      setForm((f) => ({ ...f, km: "", notes: "" }));
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "object" ? d.message : (d || e.message));
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="field-frota-screen">
      <div style={{ ...appCard, padding: 14 }}>
        <div style={{ ...sectionLabel, marginBottom: 8 }}>Frota IA — vistoria semanal</div>
        {status && (
          <>
            <Row label="Obrigatória" value={status.required ? `Sim (a cada ${status.max_age_days} dias)` : "Não (toggle desligado)"} />
            <Row label="Situação" value={status.pending ? "PENDENTE" : "Em dia"} />
            <Row label="Última vistoria" value={status.last_inspection ? new Date(status.last_inspection.created_at).toLocaleDateString("pt-BR") : "Nunca"} />
            {status.last_inspection && <Row label="KM registrado" value={String(status.last_inspection.km ?? "—")} />}
          </>
        )}
        {status?.pending && status?.required && (
          <div data-testid="frota-pending-banner" style={{ marginTop: 10, background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b", padding: "8px 12px", borderRadius: 10, fontSize: 11, fontWeight: 700 }}>
            Vistoria pendente — abertura de OS bloqueada até concluir.
          </div>
        )}
      </div>

      {msg && <div data-testid="frota-ok" style={{ background: "#ecfdf5", color: "#065f46", border: "1px solid #86efac", padding: "10px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{msg}</div>}
      {err && <div data-testid="frota-err" style={{ background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca", padding: "10px 12px", borderRadius: 10, fontSize: 12, marginBottom: 10 }}>{String(err)}</div>}

      {!readOnly && (
        <div style={{ ...appCard, padding: 14 }}>
          <div style={{ ...sectionLabel, marginBottom: 10 }}>Nova vistoria</div>
          <input data-testid="frota-plate" placeholder="Placa (ABC1D23)" value={form.plate}
            onChange={(e) => setForm({ ...form, plate: e.target.value.toUpperCase() })}
            style={{ ...fieldInput, marginBottom: 8 }} />
          <input data-testid="frota-km" type="number" min="0" placeholder="KM atual do veículo" value={form.km}
            onChange={(e) => setForm({ ...form, km: e.target.value })}
            style={{ ...fieldInput, marginBottom: 10 }} />

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
            {SIDES.map((s) => (
              <label key={s.key} data-testid={`frota-photo-${s.key}`}
                style={{ ...softBtn, height: 64, flexDirection: "column", gap: 2, fontSize: 12,
                  background: photos[s.key] ? "#ecfdf5" : "white",
                  borderColor: photos[s.key] ? "#86efac" : "#e2e8f0",
                  color: photos[s.key] ? "#065f46" : "#475569" }}>
                {photos[s.key] ? "✓ " : ""}{s.label}
                <span style={{ fontSize: 9, color: "#94a3b8" }}>{photos[s.key] ? "foto ok" : "tirar foto"}</span>
                <input type="file" accept="image/*" capture="environment" style={{ display: "none" }}
                  onChange={async (ev) => {
                    const f = ev.target.files?.[0];
                    ev.target.value = "";
                    if (!f) return;
                    try {
                      const dataUrl = await readPhotoFile(f, 1024);
                      setPhotos((p) => ({ ...p, [s.key]: dataUrl }));
                    } catch { /* */ }
                  }} />
              </label>
            ))}
          </div>

          <textarea data-testid="frota-notes" placeholder="Observações (avarias, pneus, etc.) — opcional" value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            style={{ ...fieldInput, minHeight: 60, marginBottom: 10 }} />

          <button data-testid="frota-submit" disabled={!canSubmit} onClick={submit}
            style={{ ...darkBtn, opacity: canSubmit ? 1 : 0.5 }}>
            {busy ? "Enviando..." : "Concluir vistoria"}
          </button>
          <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 8 }}>
            Exigidas as 4 fotos (frente, traseira e laterais) + KM. Histórico fica no SmartProv para análise da IA.
          </div>
        </div>
      )}
    </div>
  );
}
