/* FleetVehicleForm.js — Cadastro/edição de veículo rastreado.
 * Campos principais: placa, IMEI, tracker model, password, etc. */
import React, { useState } from "react";
import { api } from "@/api";

export default function FleetVehicleForm({ initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    placa: initial?.placa || "",
    imei: initial?.imei || "",
    tracker_model: initial?.tracker_model || "TK103",
    tracker_password: initial?.tracker_password || "123456",
    sim_phone: initial?.sim_phone || "",
    modelo: initial?.modelo || "",
    marca: initial?.marca || "",
    cor: initial?.cor || "",
    ano: initial?.ano || "",
    driver_collaborator_id: initial?.driver_collaborator_id || "",
    fleet_tenant_id: initial?.fleet_tenant_id || "",
    speed_limit_kmh: initial?.speed_limit_kmh || 80,
    notes: initial?.notes || "",
    active: initial?.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    if (!form.placa || !form.imei) {
      setErr("Placa e IMEI são obrigatórios");
      return;
    }
    setBusy(true); setErr("");
    try {
      const body = { ...form,
        ano: form.ano ? Number(form.ano) : null,
        speed_limit_kmh: Number(form.speed_limit_kmh) || 80,
        driver_collaborator_id: form.driver_collaborator_id || null,
        fleet_tenant_id: form.fleet_tenant_id || null,
      };
      if (initial?.id) {
        await api._client.put(`/fleet-tracking/vehicles/${initial.id}`, body);
      } else {
        await api._client.post("/fleet-tracking/vehicles", body);
      }
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  const remove = async () => {
    if (!initial?.id) return;
    if (!window.confirm(`Excluir o veículo ${initial.placa}?`)) return;
    setBusy(true);
    try {
      await api._client.delete(`/fleet-tracking/vehicles/${initial.id}`);
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  return (
    <div style={overlay} data-testid="fleet-vehicle-form">
      <div style={modal}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>
            {initial?.id ? `Editar ${initial.placa}` : "Cadastrar Veículo"}
          </h2>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                       gap: 10 }}>
          {field("Placa *", form.placa, (v) => set("placa", v.toUpperCase()),
                  "fleet-vform-placa")}
          {field("IMEI do rastreador *", form.imei,
                  (v) => set("imei", v.replace(/\D/g, "")),
                  "fleet-vform-imei", "Ex: 1234567890")}
          {field("Modelo do rastreador", form.tracker_model,
                  (v) => set("tracker_model", v), "fleet-vform-tracker")}
          {field("Senha do rastreador", form.tracker_password,
                  (v) => set("tracker_password", v), "fleet-vform-pwd")}
          {field("Marca", form.marca, (v) => set("marca", v),
                  "fleet-vform-marca")}
          {field("Modelo", form.modelo, (v) => set("modelo", v),
                  "fleet-vform-modelo")}
          {field("Cor", form.cor, (v) => set("cor", v), "fleet-vform-cor")}
          {field("Ano", form.ano, (v) => set("ano", v), "fleet-vform-ano",
                  "", "number")}
          {field("Telefone do chip", form.sim_phone,
                  (v) => set("sim_phone", v), "fleet-vform-sim")}
          {field("Limite de velocidade (km/h)", form.speed_limit_kmh,
                  (v) => set("speed_limit_kmh", v), "fleet-vform-speed",
                  "", "number")}
          {field("ID do colaborador (motorista)",
                  form.driver_collaborator_id,
                  (v) => set("driver_collaborator_id", v),
                  "fleet-vform-driver")}
          {field("ID do cliente (white-label)", form.fleet_tenant_id,
                  (v) => set("fleet_tenant_id", v), "fleet-vform-tenant",
                  "Opcional — vazio = sua frota")}
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 6,
                          marginTop: 8, fontSize: 12 }}>
          <input type="checkbox" checked={form.active}
                  onChange={(e) => set("active", e.target.checked)}
                  data-testid="fleet-vform-active" />
          Ativo
        </label>
        <textarea value={form.notes}
                    onChange={(e) => set("notes", e.target.value)}
                    placeholder="Observações"
                    data-testid="fleet-vform-notes"
                    style={{ ...inp, marginTop: 8, minHeight: 60,
                              width: "100%", boxSizing: "border-box" }} />
        {err && <div style={{ color: "#dc2626", fontSize: 12, marginTop: 8 }}>
          {err}
        </div>}
        <div style={{ display: "flex", gap: 8, marginTop: 12,
                       justifyContent: "space-between" }}>
          <div>
            {initial?.id && (
              <button onClick={remove} disabled={busy} style={dangerBtn}
                       data-testid="fleet-vform-delete">
                Excluir
              </button>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onClose} disabled={busy} style={secBtn}>
              Cancelar
            </button>
            <button onClick={save} disabled={busy} style={primaryBtn}
                     data-testid="fleet-vform-save">
              {busy ? "Salvando…" : "Salvar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function field(label, value, onChange, testid, ph = "", type = "text") {
  return (
    <label style={{ display: "block", fontSize: 11, color: "#475569" }}>
      {label}
      <input type={type} value={value}
              placeholder={ph}
              onChange={(e) => onChange(e.target.value)}
              data-testid={testid}
              style={inp} />
    </label>
  );
}

const overlay = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
  display: "flex", alignItems: "center", justifyContent: "center",
  zIndex: 1000, padding: 20,
};
const modal = {
  background: "white", borderRadius: 12, padding: 20,
  maxWidth: 720, width: "100%", maxHeight: "90vh", overflow: "auto",
};
const closeBtn = {
  background: "transparent", border: 0, fontSize: 20, cursor: "pointer",
  color: "#94a3b8",
};
const inp = {
  width: "100%", padding: "6px 10px", borderRadius: 6,
  border: "1px solid #cbd5e1", fontSize: 13, marginTop: 4,
  boxSizing: "border-box",
};
const primaryBtn = {
  padding: "7px 16px", background: "#0f172a", color: "white",
  border: 0, borderRadius: 6, fontWeight: 700, fontSize: 13, cursor: "pointer",
};
const secBtn = { ...primaryBtn, background: "white", color: "#475569",
                  border: "1px solid #cbd5e1", fontWeight: 600 };
const dangerBtn = { ...primaryBtn, background: "#dc2626" };
