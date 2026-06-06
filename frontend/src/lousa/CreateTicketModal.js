import React, { useState } from "react";
import { api } from "@/api";
import { Button } from "@/ui";

const css = { width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13, marginBottom: 8 };

// Grade da Lousa: 09:00 ATÉ 18:00 (inclusivo). Validação client-side
// pra avisar o atendente no ato de criar a OS (iter215).
const GRID_START_HOUR = 9;
const GRID_END_HOUR = 18;

function validateScheduledTime(dtLocal) {
  if (!dtLocal) return null;
  // formato "YYYY-MM-DDTHH:MM"
  const m = /T(\d{2}):(\d{2})/.exec(dtLocal);
  if (!m) return null;
  const h = parseInt(m[1], 10);
  const min = parseInt(m[2], 10);
  if (h < GRID_START_HOUR) {
    return `Horário ${m[1]}:${m[2]} antes da grade. Use entre ${String(GRID_START_HOUR).padStart(2,"0")}:00 e ${String(GRID_END_HOUR).padStart(2,"0")}:00.`;
  }
  if (h > GRID_END_HOUR || (h === GRID_END_HOUR && min > 0)) {
    return `Horário ${m[1]}:${m[2]} após a grade. Use entre ${String(GRID_START_HOUR).padStart(2,"0")}:00 e ${String(GRID_END_HOUR).padStart(2,"0")}:00.`;
  }
  return null;
}

export default function CreateTicketModal({ collabs, onClose, onCreated, defaults }) {
  const [form, setForm] = useState({
    client_name: "", address: "", neighborhood: "", phone: "",
    relato: "", type: "reparo",
    priority: defaults?.scheduled_time ? "horario" : "normal",
    scheduled_time: defaults?.scheduled_time || "",
    assigned_collaborator_id: defaults?.assigned_collaborator_id || collabs[0]?.id || "",
  });
  const [saving, setSaving] = useState(false);
  const scheduleError = form.priority === "horario"
    ? validateScheduledTime(form.scheduled_time) : null;

  async function submit(e) {
    e?.preventDefault();
    if (scheduleError) {
      await window.alert("️ " + scheduleError);
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      if (!payload.scheduled_time) delete payload.scheduled_time;
      await api.lousaCreateTicket(payload);
      onCreated();
    } catch (err) {
      await window.alert("Erro: " + (err?.response?.data?.detail || err.message));
    }
    setSaving(false);
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 100, display: "grid", placeItems: "center", padding: 20 }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{ background: "white", borderRadius: 18, padding: 22, maxWidth: 480, width: "100%", maxHeight: "92vh", overflowY: "auto" }} data-testid="lousa-create-modal">
        <h2 style={{ marginTop: 0 }}>Nova nota de serviço</h2>
        <label style={{ fontSize: 12, color: "#64748b" }}>Nome do cliente *</label>
        <input required value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} style={css} data-testid="ticket-client-name" />
        <label style={{ fontSize: 12, color: "#64748b" }}>Endereço completo *</label>
        <input required value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} style={css} data-testid="ticket-address" />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Bairro</label>
            <input value={form.neighborhood} onChange={(e) => setForm({ ...form, neighborhood: e.target.value })} style={css} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Telefone</label>
            <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} style={css} />
          </div>
        </div>
        <label style={{ fontSize: 12, color: "#64748b" }}>Relato do cliente</label>
        <textarea value={form.relato} onChange={(e) => setForm({ ...form, relato: e.target.value })} rows={3} style={{ ...css, resize: "vertical" }} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Tipo</label>
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={css} data-testid="ticket-type">
              <option value="reparo">Reparo</option>
              <option value="instalacao">Instalação</option>
              <option value="retirada">Retirada</option>
              <option value="prioridade">Prioridade</option>
              <option value="preventiva">️ Preventiva</option>
              <option value="venda">Venda</option>
              <option value="rompimento">Rompimento</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Prioridade</label>
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} style={css} data-testid="ticket-priority">
              <option value="normal">Normal</option>
              <option value="horario">Horário marcado</option>
              <option value="prioridade">Prioridade</option>
            </select>
          </div>
        </div>
        {form.priority === "horario" && (
          <>
            <label style={{ fontSize: 12, color: "#64748b" }}>
              Horário agendado <span style={{ color: "#94a3b8", fontWeight: 400 }}>
                (grade: {String(GRID_START_HOUR).padStart(2,"0")}:00–{String(GRID_END_HOUR).padStart(2,"0")}:00)
              </span>
            </label>
            <input
              data-testid="ticket-scheduled-time"
              type="datetime-local"
              value={form.scheduled_time}
              onChange={(e) => setForm({ ...form, scheduled_time: e.target.value })}
              style={{
                ...css,
                borderColor: scheduleError ? "#dc2626" : "#cbd5e1",
                borderWidth: scheduleError ? 2 : 1,
              }}
            />
            {scheduleError && (
              <div data-testid="ticket-schedule-error"
                    style={{
                      marginTop: -4, marginBottom: 8,
                      background: "#fee2e2", color: "#991b1b",
                      border: "1px solid #fca5a5",
                      borderRadius: 8, padding: "6px 10px", fontSize: 11,
                      lineHeight: 1.4,
                    }}>
                ️ {scheduleError}
              </div>
            )}
          </>
        )}
        <label style={{ fontSize: 12, color: "#64748b" }}>Técnico responsável *</label>
        <select required value={form.assigned_collaborator_id} onChange={(e) => setForm({ ...form, assigned_collaborator_id: e.target.value })} style={css} data-testid="ticket-collab">
          {collabs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <Button variant="soft" type="button" onClick={onClose} style={{ flex: 1 }}>Cancelar</Button>
          <Button type="submit" disabled={saving || !!scheduleError} style={{ flex: 1 }} data-testid="ticket-submit">
            {saving ? "Salvando..." : "Criar nota"}
          </Button>
        </div>
      </form>
    </div>
  );
}
