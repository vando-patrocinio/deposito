// iter189 — OdometerConfigCard
// Card que aparece na edição de colaborador (admin) pra configurar:
//   - On/Off da feature
//   - Dia(s) da semana de leitura "início" (default segunda)
//   - Dia(s) da semana de leitura "fim" (default sábado)
//   - Placa e modelo do veículo
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const WEEKDAYS = [
  { v: 0, label: "Seg" },
  { v: 1, label: "Ter" },
  { v: 2, label: "Qua" },
  { v: 3, label: "Qui" },
  { v: 4, label: "Sex" },
  { v: 5, label: "Sáb" },
  { v: 6, label: "Dom" },
];

const inputStyle = {
  width: "100%", padding: "8px 10px", borderRadius: 8,
  border: "1px solid #cbd5e1", fontSize: 14, boxSizing: "border-box",
};

function DayChips({ value, onChange, testidPrefix }) {
  return (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
      {WEEKDAYS.map((d) => {
        const on = (value || []).includes(d.v);
        return (
          <button key={d.v} type="button"
            data-testid={`${testidPrefix}-${d.label.toLowerCase()}`}
            onClick={() => {
              if (on) onChange((value || []).filter((x) => x !== d.v));
              else onChange([...(value || []), d.v].sort());
            }}
            style={{
              padding: "6px 10px", borderRadius: 8, fontSize: 12,
              border: on ? "2px solid #0d9488" : "1px solid #cbd5e1",
              background: on ? "#ccfbf1" : "#fff",
              color: on ? "#0d9488" : "#475569",
              fontWeight: 700, cursor: "pointer",
            }}>{d.label}</button>
        );
      })}
    </div>
  );
}

export default function OdometerConfigCard({ collabId }) {
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!collabId || collabId === "new") return;
    setLoading(true);
    api.fleetOdomConfigGet(collabId)
      .then((r) => setCfg(r))
      .catch(() => setCfg({
        enabled: false, weekdays_start: [0], weekdays_end: [5],
        vehicle_plate: "", vehicle_model: "",
      }))
      .finally(() => setLoading(false));
  }, [collabId]);

  const save = async () => {
    setSaving(true); setMsg("");
    try {
      await api.fleetOdomConfigSet(collabId, cfg);
      setMsg("✓ Salvo");
      setTimeout(() => setMsg(""), 2000);
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setSaving(false); }
  };

  if (loading) return null;
  if (!cfg) return null;

  return (
    <div data-testid="odometer-config-card" style={{
      marginTop: 16, padding: 14, borderRadius: 12,
      background: "#f0fdfa", border: "1px solid #99f6e4",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", gap: 8, flexWrap: "wrap",
                       marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#0d9488" }}>
            🚗 Odômetro Semanal
          </div>
          <div style={{ fontSize: 11, color: "#0f766e", marginTop: 2 }}>
            Bolha automática na Lousa do colaborador para fotografar o
            velocímetro nos dias configurados.
          </div>
        </div>
        <label style={{ display: "inline-flex", alignItems: "center",
                          gap: 6, fontSize: 13, fontWeight: 700,
                          color: "#0f766e", cursor: "pointer" }}>
          <input type="checkbox" data-testid="odom-enabled"
            checked={!!cfg.enabled}
            onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
            style={{ width: 18, height: 18 }} />
          Ativo
        </label>
      </div>

      <div style={{ display: "grid", gap: 10,
                          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                              marginBottom: 4 }}>
            Dias de INÍCIO (primeira bolha do dia)
          </div>
          <DayChips
            value={cfg.weekdays_start}
            onChange={(v) => setCfg({ ...cfg, weekdays_start: v })}
            testidPrefix="odom-start" />
        </div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                              marginBottom: 4 }}>
            Dias de FIM (última bolha do dia)
          </div>
          <DayChips
            value={cfg.weekdays_end}
            onChange={(v) => setCfg({ ...cfg, weekdays_end: v })}
            testidPrefix="odom-end" />
        </div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                              marginBottom: 4 }}>Placa do veículo</div>
          <input data-testid="odom-plate" style={inputStyle}
            value={cfg.vehicle_plate || ""}
            onChange={(e) => setCfg({ ...cfg,
              vehicle_plate: e.target.value.toUpperCase() })}
            placeholder="ABC1A23" maxLength={8} />
        </div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                              marginBottom: 4 }}>Modelo</div>
          <input data-testid="odom-model" style={inputStyle}
            value={cfg.vehicle_model || ""}
            onChange={(e) => setCfg({ ...cfg, vehicle_model: e.target.value })}
            placeholder="Renault Kwid 2020" />
        </div>
      </div>

      <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end",
                          alignItems: "center", gap: 10 }}>
        {msg && (
          <span style={{ fontSize: 12,
            color: msg.startsWith("✓") ? "#0d9488" : "#dc2626" }}>{msg}</span>
        )}
        <button data-testid="odom-save" onClick={save} disabled={saving}
          style={{ padding: "8px 14px", borderRadius: 8,
                       background: "#0d9488", color: "#fff", border: 0,
                       fontWeight: 700, cursor: "pointer" }}>
          {saving ? "Salvando..." : "Salvar Odômetro"}
        </button>
      </div>
    </div>
  );
}
