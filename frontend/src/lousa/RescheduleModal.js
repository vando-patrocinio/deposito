import React, { useState } from "react";
import { Button } from "@/ui";

const css = { width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13, marginBottom: 8 };

export default function RescheduleModal({ ticket, onClose, onConfirm, busy }) {
  // Sugere o próximo dia útil às 09:00 como default
  function defaultDate() {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  }
  const [date, setDate] = useState(defaultDate());
  const [time, setTime] = useState("09:00");
  const [reason, setReason] = useState("");

  function submit(e) {
    e?.preventDefault();
    if (!date || !time || !reason.trim()) {
      alert("Preencha data, horário e motivo do reagendamento.");
      return;
    }
    onConfirm({ new_date: date, new_time: time, notes: reason.trim() });
  }

  const clientName = ticket.client_snapshot?.name || ticket.client_name || "Cliente";

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 100,
      display: "grid", placeItems: "center", padding: 20,
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} data-testid="reschedule-modal" style={{
        background: "white", borderRadius: 18, padding: 22, maxWidth: 440, width: "100%",
        maxHeight: "92vh", overflowY: "auto",
      }}>
        <h2 style={{ margin: "0 0 4px", fontSize: 18 }}>📅 Reagendar serviço</h2>
        <p style={{ color: "#64748b", fontSize: 12, margin: "0 0 14px" }}>
          Cliente: <strong>{clientName}</strong>
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={{ fontSize: 12, color: "#64748b", fontWeight: 700 }}>Nova data *</label>
            <input data-testid="reschedule-date" type="date" required min={new Date().toISOString().slice(0, 10)}
              value={date} onChange={(e) => setDate(e.target.value)} style={css} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#64748b", fontWeight: 700 }}>Novo horário *</label>
            <input data-testid="reschedule-time" type="time" required
              value={time} onChange={(e) => setTime(e.target.value)} style={css} />
          </div>
        </div>

        <label style={{ fontSize: 12, color: "#64748b", fontWeight: 700 }}>Motivo do reagendamento *</label>
        <textarea data-testid="reschedule-reason" required rows={3}
          placeholder="Ex.: cliente solicitou mudança de horário; trânsito; equipamento indisponível..."
          value={reason} onChange={(e) => setReason(e.target.value)} style={{ ...css, resize: "vertical" }} />

        <div style={{ background: "#fef3c7", padding: 10, borderRadius: 10, fontSize: 12, color: "#78350f", marginBottom: 12 }}>
          ℹ️ O técnico será notificado automaticamente sobre o reagendamento.
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="soft" type="button" onClick={onClose} style={{ flex: 1 }}>Cancelar</Button>
          <Button type="submit" disabled={busy} data-testid="reschedule-confirm" style={{ flex: 1 }}>
            {busy ? "Reagendando..." : "Confirmar reagendamento"}
          </Button>
        </div>
      </form>
    </div>
  );
}
