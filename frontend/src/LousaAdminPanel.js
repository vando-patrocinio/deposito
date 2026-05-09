import React, { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/api";
import { Button, Icon } from "@/ui";

const PRIORITY_COLORS = {
  prioridade: { bg: "#fee2e2", border: "#dc2626", text: "#7f1d1d", label: "🚨 PRIORIDADE" },
  horario: { bg: "#fef3c7", border: "#f59e0b", text: "#78350f", label: "⏰ HORÁRIO" },
  normal: { bg: "white", border: "#cbd5e1", text: "#0f172a", label: "" },
};

const STATUS_LABEL = {
  pendente: { label: "Pendente", color: "#64748b" },
  aberta: { label: "▶ Em campo", color: "#10b981" },
  aguardando_atendimento: { label: "⚠ Aguarda gestor", color: "#f59e0b" },
  finalizada: { label: "✓ Finalizada", color: "#10b981" },
  encerrada: { label: "Encerrada", color: "#94a3b8" },
  reagendada: { label: "Reagendada", color: "#3b82f6" },
  cancelada: { label: "Cancelada", color: "#dc2626" },
};

export default function LousaAdminPanel() {
  const [grid, setGrid] = useState({ columns: [] });
  const [collabs, setCollabs] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draggingId, setDraggingId] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [g, cs] = await Promise.all([api.lousaGrid(), api.listCollaborators()]);
      setGrid(g);
      setCollabs(cs);
    } catch (e) {
      console.error("Erro ao carregar lousa", e);
    }
  }, []);

  useEffect(() => { refresh(); const i = setInterval(refresh, 30000); return () => clearInterval(i); }, [refresh]);

  async function handleDrop(targetCollabId) {
    if (!draggingId) return;
    setBusy(true);
    try {
      await api.lousaTransferTicket(draggingId, { new_collaborator_id: targetCollabId });
      await refresh();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
    setDraggingId(null);
    setDragOverCol(null);
  }

  async function handleAdminClose(ticketId, action, notes) {
    setBusy(true);
    try {
      await api.lousaAdminClose(ticketId, { action, notes: notes || "" });
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  const totalTickets = grid.columns.reduce((sum, c) => sum + (c.tickets?.length || 0), 0);

  return (
    <div data-testid="lousa-admin-panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
        <div>
          <h2 style={{ margin: 0 }}>📋 Lousa de Serviços</h2>
          <p style={{ color: "#64748b", fontSize: 13, margin: "4px 0 0" }}>
            {grid.columns.length} técnico(s) · {totalTickets} bolha(s) ativas — arraste para transferir entre técnicos
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)} data-testid="lousa-create-btn">
          <Icon name="plus" /> Nova nota
        </Button>
      </div>

      {/* Grade horizontal — coluna por técnico */}
      <div style={{
        display: "flex", gap: 14, overflowX: "auto", paddingBottom: 16,
        minHeight: 540,
      }} data-testid="lousa-grid">
        {grid.columns.length === 0 && (
          <div style={{ background: "white", padding: 30, borderRadius: 14, color: "#94a3b8", flex: 1, textAlign: "center" }}>
            Nenhum técnico cadastrado.
          </div>
        )}
        {grid.columns.map((col) => (
          <TechColumn
            key={col.collaborator.id}
            column={col}
            isDropTarget={dragOverCol === col.collaborator.id}
            onDragOver={(e) => { e.preventDefault(); setDragOverCol(col.collaborator.id); }}
            onDragLeave={() => setDragOverCol((c) => c === col.collaborator.id ? null : c)}
            onDrop={() => handleDrop(col.collaborator.id)}
            onDragStart={(tid) => setDraggingId(tid)}
            onDragEnd={() => { setDraggingId(null); setDragOverCol(null); }}
            draggingId={draggingId}
            onAdminClose={handleAdminClose}
            busy={busy}
          />
        ))}
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

function TechColumn({ column, isDropTarget, onDragOver, onDragLeave, onDrop, onDragStart, onDragEnd, draggingId, onAdminClose, busy }) {
  const c = column.collaborator;
  const state = column.clock_state;
  const tickets = column.tickets || [];
  const isOnline = state.has_entrada && !state.ended_day && !state.in_intervalo;

  return (
    <div
      data-testid={`tech-column-${c.id}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        flex: "0 0 320px", maxWidth: 320,
        background: isDropTarget ? "#dbeafe" : "#f1f5f9",
        border: `2px ${isDropTarget ? "dashed" : "solid"} ${isDropTarget ? "#3b82f6" : "#e2e8f0"}`,
        borderRadius: 16, padding: 12, transition: "all .15s",
      }}
    >
      {/* Header do técnico */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", paddingBottom: 10, borderBottom: "1px solid #cbd5e1" }}>
        <div style={{
          width: 42, height: 42, borderRadius: "50%",
          background: c.avatar ? `url(${c.avatar}) center/cover` : "linear-gradient(135deg,#0ea5e9,#0284c7)",
          display: "grid", placeItems: "center", color: "white", fontWeight: 800, fontSize: 16,
          border: `3px solid ${isOnline ? "#10b981" : "#94a3b8"}`, position: "relative",
        }}>
          {!c.avatar && (c.name?.[0] || "?").toUpperCase()}
          <span style={{
            position: "absolute", bottom: -2, right: -2,
            width: 14, height: 14, borderRadius: "50%",
            background: isOnline ? "#10b981" : state.ended_day ? "#94a3b8" : "#f59e0b",
            border: "2px solid white",
          }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 800, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {c.name}
            {c.is_test_mode && <span style={{ marginLeft: 6, fontSize: 9, background: "#a855f7", color: "white", padding: "1px 5px", borderRadius: 6 }}>🧪 TESTE</span>}
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>
            {c.praca || "—"} · {tickets.length} bolha(s)
          </div>
        </div>
      </div>

      {/* Faixa de horários do dia */}
      <div data-testid={`schedule-${c.id}`} style={{
        marginTop: 10, padding: "6px 8px",
        background: "white", borderRadius: 10, border: "1px solid #e2e8f0",
        fontSize: 10, display: "flex", flexWrap: "wrap", gap: 4,
      }}>
        {state.records?.length === 0 && (
          <span style={{ color: "#94a3b8" }}>Sem ponto hoje</span>
        )}
        {state.records?.map((r, i) => (
          <span key={i} style={{
            padding: "1px 6px", borderRadius: 6, fontWeight: 700,
            background: r.type === "Entrada" ? "#dcfce7" : r.type === "Saída" ? "#fee2e2" : "#fef3c7",
            color: r.type === "Entrada" ? "#166534" : r.type === "Saída" ? "#7f1d1d" : "#78350f",
          }}>
            {r.type === "Entrada" ? "🚪" : r.type === "Início intervalo" ? "🍽️" : r.type === "Fim intervalo" ? "🔄" : "🏁"} {r.time}
          </span>
        ))}
      </div>

      {/* Bolhas */}
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8, minHeight: 200 }}>
        {tickets.length === 0 && (
          <div style={{
            padding: 16, textAlign: "center", color: "#94a3b8", fontSize: 12,
            border: "2px dashed #cbd5e1", borderRadius: 10,
          }}>
            {isDropTarget ? "↓ Solte aqui ↓" : "Nenhuma bolha"}
          </div>
        )}
        {tickets.map((t) => (
          <BubbleCard
            key={t.id}
            ticket={t}
            isDragging={draggingId === t.id}
            onDragStart={() => onDragStart(t.id)}
            onDragEnd={onDragEnd}
            onAdminClose={onAdminClose}
            busy={busy}
          />
        ))}
      </div>
    </div>
  );
}

function BubbleCard({ ticket, isDragging, onDragStart, onDragEnd, onAdminClose, busy }) {
  const c = PRIORITY_COLORS[ticket.priority] || PRIORITY_COLORS.normal;
  const st = STATUS_LABEL[ticket.status] || { label: ticket.status, color: "#64748b" };
  const [showActions, setShowActions] = useState(false);

  return (
    <div
      draggable
      onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; onDragStart(); }}
      onDragEnd={onDragEnd}
      onClick={() => setShowActions(!showActions)}
      data-testid={`bubble-card-${ticket.id}`}
      style={{
        background: c.bg, border: `2px solid ${c.border}`, borderRadius: 14, padding: 10,
        cursor: "grab", opacity: isDragging ? 0.4 : 1, position: "relative",
        boxShadow: isDragging ? "none" : "0 2px 6px rgba(15,23,42,.08)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 4, alignItems: "start" }}>
        {c.label && (
          <span style={{ fontSize: 9, fontWeight: 900, color: c.text }}>{c.label}{ticket.scheduled_time ? ` · ${ticket.scheduled_time.substr(11, 5)}` : ""}</span>
        )}
        <span style={{ fontSize: 9, fontWeight: 800, color: st.color, background: "rgba(255,255,255,.7)", padding: "1px 6px", borderRadius: 6 }}>
          {st.label}
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 800, marginTop: 4, color: c.text }}>{ticket.client_snapshot.name}</div>
      <div style={{ fontSize: 11, color: "#64748b" }}>{ticket.type} · {ticket.client_snapshot.neighborhood}</div>
      <div style={{ fontSize: 11, color: "#475569", marginTop: 4 }}>
        {ticket.client_snapshot.relato?.substring(0, 70)}{ticket.client_snapshot.relato?.length > 70 ? "..." : ""}
      </div>
      {ticket.locked && (
        <span style={{ position: "absolute", top: 6, right: 6, fontSize: 14 }}>🔒</span>
      )}
      {showActions && ["pendente", "aberta", "aguardando_atendimento"].includes(ticket.status) && (
        <div onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}>
          <button
            data-testid={`admin-close-${ticket.id}`}
            disabled={busy}
            onClick={() => { const n = window.prompt("Notas:"); if (n !== null) onAdminClose(ticket.id, "encerrar", n); }}
            style={btnSm("#10b981")}
          >✓ Encerrar</button>
          <button
            disabled={busy}
            onClick={() => { const n = window.prompt("Motivo do reagendamento:"); if (n) onAdminClose(ticket.id, "reagendar", n); }}
            style={btnSm("#3b82f6")}
          >📅 Reagendar</button>
          <button
            disabled={busy}
            onClick={() => { const n = window.prompt("Motivo do cancelamento:"); if (n) onAdminClose(ticket.id, "cancelar", n); }}
            style={btnSm("#dc2626")}
          >✗ Cancelar</button>
        </div>
      )}
    </div>
  );
}

function btnSm(color) {
  return {
    fontSize: 10, padding: "3px 7px", border: 0, borderRadius: 6,
    background: color, color: "white", fontWeight: 800, cursor: "pointer",
  };
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

  const css = { width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13, marginBottom: 8 };

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
