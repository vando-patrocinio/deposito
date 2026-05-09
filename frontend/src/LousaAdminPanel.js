import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Button, Card, Icon } from "@/ui";

const PRIORITY_COLORS = {
  prioridade: { bg: "#fee2e2", border: "#dc2626", text: "#7f1d1d", label: "🚨 PRIORIDADE" },
  horario: { bg: "#fef3c7", border: "#f59e0b", text: "#78350f", label: "⏰ HORÁRIO" },
  normal: { bg: "white", border: "#cbd5e1", text: "#0f172a", label: "📋 NORMAL" },
};

const STATUS_LABEL = {
  pendente: { label: "Pendente", color: "#64748b" },
  aberta: { label: "Em campo", color: "#10b981" },
  aguardando_atendimento: { label: "Aguarda gestor", color: "#f59e0b" },
  finalizada: { label: "Finalizada ✓", color: "#10b981" },
  encerrada: { label: "Encerrada", color: "#94a3b8" },
  reagendada: { label: "Reagendada", color: "#3b82f6" },
  cancelada: { label: "Cancelada", color: "#dc2626" },
};

export default function LousaAdminPanel() {
  const [tickets, setTickets] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [filterStatus, setFilterStatus] = useState("all");
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [tk, cs] = await Promise.all([api.lousaAll(), api.listCollaborators()]);
    setTickets(tk.tickets || []);
    setCollabs(cs);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const filtered = tickets.filter((t) => {
    if (filterStatus === "all") return true;
    if (filterStatus === "active") return ["pendente", "aberta", "aguardando_atendimento"].includes(t.status);
    if (filterStatus === "resolved") return ["finalizada", "encerrada", "reagendada", "cancelada"].includes(t.status);
    return t.status === filterStatus;
  });

  async function handleAdminClose(ticket, action, notes) {
    setBusy(true);
    try {
      await api.lousaAdminClose(ticket.id, { action, notes: notes || "" });
      await refresh();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  async function handleDelete(ticket) {
    if (!window.confirm("Excluir esta nota?")) return;
    setBusy(true);
    try {
      await api.lousaDeleteTicket(ticket.id);
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  return (
    <div data-testid="lousa-admin-panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0 }}>📋 Lousa de Serviços</h2>
          <p style={{ color: "#64748b", fontSize: 13, margin: "4px 0 0" }}>
            {tickets.length} bolhas no total · {filtered.length} exibidas
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)} data-testid="lousa-create-btn">
          <Icon name="plus" /> Nova nota
        </Button>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {[
          ["all", "Todas"],
          ["active", "Ativas"],
          ["aberta", "Em campo"],
          ["aguardando_atendimento", "Aguarda gestor"],
          ["resolved", "Resolvidas"],
        ].map(([k, l]) => (
          <Button
            key={k}
            variant={filterStatus === k ? "primary" : "secondary"}
            onClick={() => setFilterStatus(k)}
            data-testid={`lousa-filter-${k}`}
          >
            {l}
          </Button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
        {filtered.length === 0 && (
          <div style={{ background: "white", padding: 20, borderRadius: 16, color: "#94a3b8", textAlign: "center", gridColumn: "1/-1" }}>
            Nenhuma nota nesse filtro.
          </div>
        )}
        {filtered.map((t) => {
          const c = PRIORITY_COLORS[t.priority] || PRIORITY_COLORS.normal;
          const collab = collabs.find((x) => x.id === t.assigned_collaborator_id);
          const st = STATUS_LABEL[t.status] || { label: t.status, color: "#64748b" };
          return (
            <div key={t.id} data-testid={`lousa-card-${t.id}`} style={{
              background: c.bg, border: `2px solid ${c.border}`, borderRadius: 18, padding: 14,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                <span style={{ fontSize: 10, fontWeight: 900, color: c.text }}>
                  {c.label}{t.scheduled_time ? ` · ${t.scheduled_time.substr(11, 5)}` : ""}
                </span>
                <span style={{ fontSize: 10, fontWeight: 800, color: st.color, background: "rgba(255,255,255,.7)", padding: "2px 8px", borderRadius: 8 }}>
                  {st.label}
                </span>
              </div>
              <div style={{ fontSize: 16, fontWeight: 800, marginTop: 6, color: c.text }}>{t.client_snapshot.name}</div>
              <div style={{ fontSize: 12, color: "#64748b" }}>{t.client_snapshot.address}</div>
              <div style={{ fontSize: 12, color: "#475569", marginTop: 6 }}>
                Técnico: <strong>{collab?.name || "—"}</strong>
              </div>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 4, fontStyle: "italic" }}>
                "{t.client_snapshot.relato?.substring(0, 100)}{t.client_snapshot.relato?.length > 100 ? "..." : ""}"
              </div>
              {t.admin_notes && (
                <div style={{ marginTop: 8, fontSize: 11, background: "rgba(220, 38, 38, 0.08)", padding: 6, borderRadius: 8, color: "#7f1d1d" }}>
                  <strong>{t.admin_action}:</strong> {t.admin_notes}
                </div>
              )}

              {/* Actions */}
              {["pendente", "aberta", "aguardando_atendimento"].includes(t.status) && (
                <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      const notes = window.prompt("Notas (opcional):");
                      if (notes !== null) handleAdminClose(t, "encerrar", notes);
                    }}
                    data-testid={`admin-close-${t.id}`}
                    style={{ fontSize: 11, padding: "4px 10px" }}
                  >
                    ✓ Encerrar
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      const notes = window.prompt("Motivo do reagendamento:");
                      if (notes) handleAdminClose(t, "reagendar", notes);
                    }}
                    style={{ fontSize: 11, padding: "4px 10px" }}
                  >
                    📅 Reagendar
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      const notes = window.prompt("Motivo do cancelamento:");
                      if (notes) handleAdminClose(t, "cancelar", notes);
                    }}
                    style={{ fontSize: 11, padding: "4px 10px" }}
                  >
                    ✗ Cancelar
                  </Button>
                </div>
              )}
              {t.status === "pendente" && (
                <Button variant="soft" onClick={() => handleDelete(t)} style={{ fontSize: 11, padding: "2px 8px", marginTop: 4 }}>
                  🗑 Excluir
                </Button>
              )}
            </div>
          );
        })}
      </div>

      {showCreate && (
        <CreateTicketModal
          collabs={collabs}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); refresh(); }}
        />
      )}
    </div>
  );
}

function CreateTicketModal({ collabs, onClose, onCreated }) {
  const [form, setForm] = useState({
    client_name: "", address: "", neighborhood: "", phone: "",
    relato: "", type: "reparo", priority: "normal",
    scheduled_time: "", assigned_collaborator_id: collabs[0]?.id || "",
  });
  const [saving, setSaving] = useState(false);

  async function submit(e) {
    e?.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form };
      if (!payload.scheduled_time) delete payload.scheduled_time;
      await api.lousaCreateTicket(payload);
      onCreated();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
    setSaving(false);
  }

  const css = {
    width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1",
    borderRadius: 10, fontSize: 13, marginBottom: 8,
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 100,
      display: "grid", placeItems: "center", padding: 20,
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 18, padding: 22, maxWidth: 480, width: "100%",
        maxHeight: "92vh", overflowY: "auto",
      }} data-testid="lousa-create-modal">
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
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>Prioridade</label>
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} style={css} data-testid="ticket-priority">
              <option value="normal">Normal</option>
              <option value="horario">Horário marcado</option>
              <option value="prioridade">🚨 Prioridade</option>
            </select>
          </div>
        </div>
        {form.priority === "horario" && (
          <>
            <label style={{ fontSize: 12, color: "#64748b" }}>Horário agendado</label>
            <input type="datetime-local" value={form.scheduled_time} onChange={(e) => setForm({ ...form, scheduled_time: e.target.value })} style={css} />
          </>
        )}
        <label style={{ fontSize: 12, color: "#64748b" }}>Técnico responsável *</label>
        <select required value={form.assigned_collaborator_id} onChange={(e) => setForm({ ...form, assigned_collaborator_id: e.target.value })} style={css} data-testid="ticket-collab">
          {collabs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>

        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <Button variant="soft" type="button" onClick={onClose} style={{ flex: 1 }}>Cancelar</Button>
          <Button type="submit" disabled={saving} style={{ flex: 1 }} data-testid="ticket-submit">
            {saving ? "Salvando..." : "Criar nota"}
          </Button>
        </div>
      </form>
    </div>
  );
}
