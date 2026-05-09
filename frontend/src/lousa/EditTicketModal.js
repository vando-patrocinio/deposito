import React, { useState } from "react";
import { Button } from "@/ui";

const css = { width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13, marginBottom: 8 };

export default function EditTicketModal({ ticket, onClose, onSave, busy }) {
  const [form, setForm] = useState({
    client_name: ticket.client_snapshot?.name || "",
    address: ticket.client_snapshot?.address || "",
    neighborhood: ticket.client_snapshot?.neighborhood || "",
    phone: ticket.client_snapshot?.phone || "",
    relato: ticket.client_snapshot?.relato || "",
    type: ticket.type || "reparo",
    priority: ticket.priority || "normal",
    scheduled_time: ticket.scheduled_time || "",
  });

  function submit(e) {
    e?.preventDefault();
    const payload = { ...form };
    if (!payload.scheduled_time) delete payload.scheduled_time;
    onSave(payload);
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 100, display: "grid", placeItems: "center", padding: 20 }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{ background: "white", borderRadius: 18, padding: 22, maxWidth: 480, width: "100%", maxHeight: "92vh", overflowY: "auto" }} data-testid="lousa-edit-modal">
        <h2 style={{ marginTop: 0 }}>✎ Editar nota</h2>
        <p style={{ color: "#64748b", fontSize: 12, margin: "0 0 12px" }}>
          Status: <strong>{ticket.status}</strong> · ID: <code>{ticket.id}</code>
        </p>
        <label style={{ fontSize: 12, color: "#64748b" }}>Nome do cliente</label>
        <input value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} style={css} data-testid="edit-client-name" />
        <label style={{ fontSize: 12, color: "#64748b" }}>Endereço</label>
        <input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} style={css} />
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
        <label style={{ fontSize: 12, color: "#64748b" }}>Relato</label>
        <textarea value={form.relato} onChange={(e) => setForm({ ...form, relato: e.target.value })} rows={3} style={{ ...css, resize: "vertical" }} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Tipo</label>
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={css} data-testid="edit-type">
              <option value="reparo">🔧 Reparo</option>
              <option value="instalacao">📡 Instalação</option>
              <option value="retirada">📦 Retirada</option>
              <option value="prioridade">🚨 Prioridade</option>
              <option value="preventiva">🛡️ Preventiva</option>
              <option value="venda">💼 Venda</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Prioridade</label>
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} style={css}>
              <option value="normal">Normal</option>
              <option value="horario">Horário marcado</option>
              <option value="prioridade">🚨 Prioridade</option>
            </select>
          </div>
        </div>
        {form.priority === "horario" && (
          <>
            <label style={{ fontSize: 12, color: "#64748b" }}>Horário agendado</label>
            <input type="datetime-local" value={form.scheduled_time?.substring(0, 16) || ""} onChange={(e) => setForm({ ...form, scheduled_time: e.target.value })} style={css} />
          </>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <Button variant="soft" type="button" onClick={onClose} style={{ flex: 1 }}>Cancelar</Button>
          <Button type="submit" disabled={busy} style={{ flex: 1 }} data-testid="edit-submit">
            {busy ? "Salvando..." : "Salvar alterações"}
          </Button>
        </div>
      </form>
    </div>
  );
}
