import React, { useEffect, useState, useCallback } from "react";
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

const ACTION_LABEL = {
  criada: { icon: "➕", color: "#3b82f6", label: "Criada" },
  aberta: { icon: "▶", color: "#10b981", label: "Iniciada" },
  finalizada: { icon: "✓", color: "#10b981", label: "Finalizada" },
  encerrar: { icon: "✕", color: "#94a3b8", label: "Encerrada (gestor)" },
  reagendar: { icon: "📅", color: "#3b82f6", label: "Reagendada" },
  cancelar: { icon: "🚫", color: "#dc2626", label: "Cancelada" },
  transferida: { icon: "↔", color: "#a855f7", label: "Transferida" },
};

export default function LousaAdminPanel() {
  const [grid, setGrid] = useState({ columns: [], sla_blink_when_overdue: true, sla_warning_pct: 80 });
  const [collabs, setCollabs] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draggingId, setDraggingId] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);
  const [logs, setLogs] = useState([]);
  const [tick, setTick] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFlash, setRefreshFlash] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [g, cs, lg] = await Promise.all([api.lousaGrid(), api.listCollaborators(), api.lousaLogs({ limit: 50 })]);
      setGrid(g);
      setCollabs(cs);
      setLogs(lg.items || []);
      setRefreshFlash(true);
      setTimeout(() => setRefreshFlash(false), 1200);
    } catch (e) {
      console.error("Erro lousa", e);
      alert("Erro ao atualizar: " + (e?.message || e));
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t1 = setInterval(refresh, 30000);  // refresh dados
    const t2 = setInterval(() => setTick((x) => x + 1), 5000);  // re-render p/ animação SLA
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [refresh]);

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

  async function handleSlotDrop(targetCollabId, slotLabel) {
    if (!draggingId) return;
    setBusy(true);
    try {
      await api.lousaTransferTicket(draggingId, {
        new_collaborator_id: targetCollabId,
        new_grid_slot: slotLabel,
      });
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
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
  const overdueCount = grid.columns.flatMap((c) => c.tickets || []).filter((t) => t.sla?.status === "overdue").length;

  return (
    <div data-testid="lousa-admin-panel">
      {/* Animação CSS do piscar */}
      <style>{`
        @keyframes pulseRed {
          0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.7); border-color: #dc2626; }
          50% { box-shadow: 0 0 0 12px rgba(220, 38, 38, 0); border-color: #b91c1c; }
        }
        .sla-overdue { animation: pulseRed 1.4s ease-in-out infinite; }
      `}</style>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
        <div>
          <h2 style={{ margin: 0 }}>📋 Lousa de Serviços</h2>
          <p style={{ color: "#64748b", fontSize: 13, margin: "4px 0 0" }}>
            {grid.columns.length} técnico(s) · {totalTickets} bolha(s) ativas — arraste para transferir entre técnicos
            {overdueCount > 0 && (
              <span data-testid="overdue-counter" style={{ marginLeft: 10, padding: "2px 10px", background: "#dc2626", color: "white", borderRadius: 999, fontWeight: 800 }}>
                ⚠ {overdueCount} ATRASADA(S)
              </span>
            )}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            variant="soft"
            onClick={refresh}
            disabled={refreshing}
            data-testid="lousa-refresh-btn"
            style={{
              background: refreshFlash ? "#dcfce7" : refreshing ? "#fef9c3" : "#dbeafe",
              color: refreshFlash ? "#166534" : refreshing ? "#92400e" : "#1e40af",
              border: `1px solid ${refreshFlash ? "#86efac" : refreshing ? "#fde68a" : "#93c5fd"}`,
              transition: "background-color .25s, color .25s",
            }}
          >
            {refreshing ? "⏳ Atualizando..." : refreshFlash ? "✓ Atualizado" : "🔄 Atualizar"}
          </Button>
          <Button onClick={() => setShowCreate(true)} data-testid="lousa-create-btn">
            <Icon name="plus" /> Nova nota
          </Button>
        </div>
      </div>

      {/* Grade horizontal — coluna por técnico */}
      <div style={{ display: "flex", gap: 14, overflowX: "auto", paddingBottom: 16, minHeight: 540 }} data-testid="lousa-grid">
        {grid.columns.length === 0 && (
          <div style={{ background: "white", padding: 30, borderRadius: 14, color: "#94a3b8", flex: 1, textAlign: "center" }}>
            Nenhum técnico cadastrado.
          </div>
        )}
        {grid.columns.map((col) => (
          <TechColumn
            key={col.collaborator.id + tick}
            column={col}
            isDropTarget={dragOverCol === col.collaborator.id}
            blinkOverdue={grid.sla_blink_when_overdue}
            maxPerSlot={grid.grid?.max_per_slot || 2}
            onSlotDrop={handleSlotDrop}
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

      {/* Logs de auditoria */}
      <LogsPanel logs={logs} collabs={collabs} />

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

function TechColumn({ column, isDropTarget, blinkOverdue, onDragOver, onDragLeave, onDrop, onDragStart, onDragEnd, draggingId, onAdminClose, busy, maxPerSlot, onSlotDrop }) {
  const c = column.collaborator;
  const state = column.clock_state;
  const slots = column.slots || [];
  const unscheduled = column.unscheduled || [];
  const totalTickets = column.tickets?.length || 0;
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
      <div style={{ display: "flex", gap: 10, alignItems: "center", paddingBottom: 10, borderBottom: "1px solid #cbd5e1" }}>
        <div style={{
          width: 42, height: 42, borderRadius: "50%",
          background: c.avatar ? `url(${c.avatar}) center/cover` : "linear-gradient(135deg,#0ea5e9,#0284c7)",
          display: "grid", placeItems: "center", color: "white", fontWeight: 800, fontSize: 16,
          border: `3px solid ${isOnline ? "#10b981" : "#94a3b8"}`, position: "relative", flexShrink: 0,
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
            {c.praca_id === "NOTA" && <span title="Praça Nota: bate ponto no endereço da bolha aberta" style={{ marginLeft: 4, fontSize: 9, background: "#0ea5e9", color: "white", padding: "1px 5px", borderRadius: 6 }}>📍 NOTA</span>}
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>
            {totalTickets} bolha(s) · {c.praca || "—"}
          </div>
        </div>
      </div>

      <div data-testid={`schedule-${c.id}`} style={{
        marginTop: 10, padding: "6px 8px", background: "white", borderRadius: 10,
        border: "1px solid #e2e8f0", fontSize: 10, display: "flex", flexWrap: "wrap", gap: 4,
      }}>
        {state.records?.length === 0 && <span style={{ color: "#94a3b8" }}>Sem ponto hoje</span>}
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

      {/* Grade FIXA de slots */}
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, minHeight: 200 }}>
        {slots.map((s) => (
          <SlotRow
            key={s.slot}
            slot={s}
            techId={c.id}
            maxPerSlot={maxPerSlot}
            onSlotDrop={onSlotDrop}
            draggingId={draggingId}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            blinkOverdue={blinkOverdue}
            onAdminClose={onAdminClose}
            busy={busy}
          />
        ))}
        {unscheduled.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <div style={{
              fontSize: 10, fontWeight: 800, color: "#64748b", padding: "3px 8px",
              background: "#e2e8f0", borderRadius: 6, marginBottom: 4,
            }}>📋 Sem horário ({unscheduled.length})</div>
            {unscheduled.map((t) => (
              <BubbleCard
                key={t.id}
                ticket={t}
                blinkOverdue={blinkOverdue}
                isDragging={draggingId === t.id}
                onDragStart={() => onDragStart(t.id)}
                onDragEnd={onDragEnd}
                onAdminClose={onAdminClose}
                busy={busy}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SlotRow({ slot, techId, maxPerSlot, onSlotDrop, draggingId, onDragStart, onDragEnd, blinkOverdue, onAdminClose, busy }) {
  const [over, setOver] = useState(false);
  const isFull = slot.full;
  const isEmpty = slot.tickets.length === 0;

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); if (!isFull) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setOver(false);
        if (!isFull) onSlotDrop(techId, slot.slot);
      }}
      data-testid={`slot-${techId}-${slot.slot}`}
      style={{
        background: over ? "#bfdbfe" : isFull ? "#fef3c7" : isEmpty ? "white" : "#f8fafc",
        border: `${over ? "2px dashed #3b82f6" : "1px solid #e2e8f0"}`,
        borderRadius: 8, padding: 6, minHeight: 38,
        transition: "all .15s",
      }}
    >
      <div style={{
        fontSize: 10, fontWeight: 800, color: isFull ? "#92400e" : "#475569",
        marginBottom: isEmpty ? 0 : 4, display: "flex", justifyContent: "space-between",
      }}>
        <span>🕐 {slot.slot}</span>
        <span style={{ fontSize: 9 }}>
          {slot.tickets.length}/{maxPerSlot}{isFull && " 🔒 cheio"}
        </span>
      </div>
      {isEmpty && (
        <div style={{ fontSize: 10, color: "#cbd5e1", textAlign: "center", padding: 2, fontStyle: "italic" }}>
          {over ? "↓ Solte aqui ↓" : "vazio"}
        </div>
      )}
      {slot.tickets.map((t) => (
        <BubbleCard
          key={t.id}
          ticket={t}
          blinkOverdue={blinkOverdue}
          isDragging={draggingId === t.id}
          onDragStart={() => onDragStart(t.id)}
          onDragEnd={onDragEnd}
          onAdminClose={onAdminClose}
          busy={busy}
        />
      ))}
    </div>
  );
}

function BubbleCard({ ticket, blinkOverdue, isDragging, onDragStart, onDragEnd, onAdminClose, busy }) {
  const c = PRIORITY_COLORS[ticket.priority] || PRIORITY_COLORS.normal;
  const st = STATUS_LABEL[ticket.status] || { label: ticket.status, color: "#64748b" };
  const sla = ticket.sla || {};
  const slaColor = sla.status === "overdue" ? "#dc2626" : sla.status === "warning" ? "#f59e0b" : "#10b981";
  const isOverdue = sla.status === "overdue";
  const [showActions, setShowActions] = useState(false);

  return (
    <div
      draggable
      onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; onDragStart(); }}
      onDragEnd={onDragEnd}
      onClick={() => setShowActions(!showActions)}
      data-testid={`bubble-card-${ticket.id}`}
      className={isOverdue && blinkOverdue ? "sla-overdue" : ""}
      style={{
        background: c.bg, border: `2px solid ${isOverdue ? "#dc2626" : c.border}`,
        borderRadius: 14, padding: 10, marginBottom: 6,
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

      {/* SLA badge */}
      {ticket.status === "aberta" && sla.elapsed_minutes != null && (
        <div data-testid={`sla-${ticket.id}`} style={{
          marginTop: 6, fontSize: 10, fontWeight: 800,
          color: slaColor,
          display: "flex", alignItems: "center", gap: 4,
        }}>
          ⏱ {Math.floor(sla.elapsed_minutes)}min / {sla.sla_minutes}min ({sla.pct?.toFixed(0)}%)
          {sla.status === "overdue" && <span style={{ background: "#dc2626", color: "white", padding: "1px 6px", borderRadius: 6 }}>ATRASADA</span>}
          {sla.status === "warning" && <span style={{ background: "#f59e0b", color: "white", padding: "1px 6px", borderRadius: 6 }}>ATENÇÃO</span>}
        </div>
      )}

      {ticket.locked && (
        <span style={{ position: "absolute", top: 6, right: 6, fontSize: 14 }}>🔒</span>
      )}
      {showActions && ["pendente", "aberta", "aguardando_atendimento"].includes(ticket.status) && (
        <div onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}>
          <button data-testid={`admin-close-${ticket.id}`} disabled={busy}
            onClick={() => { const n = window.prompt("Notas:"); if (n !== null) onAdminClose(ticket.id, "encerrar", n); }} style={btnSm("#10b981")}>✓ Encerrar</button>
          <button disabled={busy}
            onClick={() => { const n = window.prompt("Motivo do reagendamento:"); if (n) onAdminClose(ticket.id, "reagendar", n); }} style={btnSm("#3b82f6")}>📅 Reagendar</button>
          <button disabled={busy}
            onClick={() => { const n = window.prompt("Motivo do cancelamento:"); if (n) onAdminClose(ticket.id, "cancelar", n); }} style={btnSm("#dc2626")}>✗ Cancelar</button>
        </div>
      )}
    </div>
  );
}

function LogsPanel({ logs, collabs }) {
  const [filter, setFilter] = useState("all");
  const filtered = logs.filter((l) => filter === "all" ? true : l.actor_role === filter);

  return (
    <div data-testid="lousa-logs-panel" style={{
      marginTop: 18, background: "white", border: "1px solid #e2e8f0",
      borderRadius: 14, padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>📜 Histórico de Ações ({logs.length})</h3>
        <div style={{ display: "flex", gap: 6 }}>
          {[
            ["all", "Todos"],
            ["colaborador", "Técnicos"],
            ["gestor", "Gestor"],
            ["administrador", "Admin"],
          ].map(([k, l]) => (
            <button
              key={k}
              data-testid={`logs-filter-${k}`}
              onClick={() => setFilter(k)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 700,
                border: filter === k ? "2px solid #3b82f6" : "1px solid #cbd5e1",
                background: filter === k ? "#dbeafe" : "white", borderRadius: 8,
                cursor: "pointer", color: filter === k ? "#1e40af" : "#475569",
              }}
            >{l}</button>
          ))}
        </div>
      </div>
      <div style={{ maxHeight: 280, overflowY: "auto" }}>
        {filtered.length === 0 && (
          <div style={{ color: "#94a3b8", textAlign: "center", padding: 20, fontSize: 13 }}>
            Sem ações ainda.
          </div>
        )}
        {filtered.map((l) => {
          const a = ACTION_LABEL[l.action] || { icon: "•", color: "#64748b", label: l.action };
          return (
            <div key={l.id} data-testid={`log-${l.id}`} style={{
              padding: "8px 10px", borderLeft: `3px solid ${a.color}`,
              background: "#f8fafc", borderRadius: 6, marginBottom: 4,
              display: "flex", gap: 10, alignItems: "center",
            }}>
              <span style={{ fontSize: 16, flexShrink: 0 }}>{a.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: a.color }}>
                  {a.label}
                  <span style={{ marginLeft: 8, fontSize: 10, color: "#94a3b8", fontWeight: 500 }}>
                    {l.actor_role} · {l.actor_name}
                  </span>
                </div>
                {l.details && <div style={{ fontSize: 11, color: "#475569", marginTop: 1 }}>{l.details}</div>}
              </div>
              <span style={{ fontSize: 10, color: "#94a3b8", flexShrink: 0 }}>
                {new Date(l.at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function btnSm(color) {
  return { fontSize: 10, padding: "3px 7px", border: 0, borderRadius: 6, background: color, color: "white", fontWeight: 800, cursor: "pointer" };
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
