import React, { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/api";
import { Button, Icon } from "@/ui";
import EditTicketModal from "./lousa/EditTicketModal";
import CreateTicketModal from "./lousa/CreateTicketModal";
import RescheduleModal from "./lousa/RescheduleModal";
import LousaHistoryModal from "./lousa/LousaHistoryModal";
import BulkActionsBar from "./lousa/BulkActionsBar";
import useEventStream from "@/useEventStream";
import { isAlertsEnabled, setAlertsEnabled, maybeFireOverdueAlerts } from "./slaAlerts";

const TYPE_LABELS = {
  reparo: "🔧 Reparo",
  instalacao: "📡 Instalação",
  retirada: "📦 Retirada",
  prioridade: "🚨 Prioridade",
  preventiva: "🛡️ Preventiva",
  venda: "💼 Venda",
};

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

export default function LousaAdminPanel({ systemStatus = { offline: false, drift_blocked: false } }) {
  const [grid, setGrid] = useState({ columns: [], sla_blink_when_overdue: true, sla_warning_pct: 80 });
  const [collabs, setCollabs] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editingTicket, setEditingTicket] = useState(null);
  const [reschedTicket, setReschedTicket] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draggingId, setDraggingId] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);
  const [logs, setLogs] = useState([]);
  const [tick, setTick] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFlash, setRefreshFlash] = useState(false);
  const [alertsOn, setAlertsOnState] = useState(() => isAlertsEnabled());
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [selectedDate, setSelectedDate] = useState(() => todayLocalISO());
  const [atlazTenantDomain, setAtlazTenantDomain] = useState("");
  const prevOverdueRef = useRef(0);
  const isLocked = systemStatus.offline || systemStatus.drift_blocked;
  const isToday = selectedDate === todayLocalISO();

  function shiftDay(delta) {
    const d = new Date(selectedDate + "T12:00:00");
    d.setDate(d.getDate() + delta);
    setSelectedDate(d.toISOString().slice(0, 10));
  }
  function goToday() { setSelectedDate(todayLocalISO()); }

  function toggleAlerts() {
    const next = !alertsOn;
    setAlertsEnabled(next);
    setAlertsOnState(next);
  }

  function toggleSelectMode() {
    setSelectMode((prev) => {
      if (prev) setSelectedIds([]);
      return !prev;
    });
  }
  function toggleTicketSelected(id) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  }
  function clearSelection() {
    setSelectedIds([]);
  }
  function selectAllOverdue() {
    const overdueIds = [];
    for (const col of grid.columns || []) {
      for (const t of col.tickets || []) {
        if (t.sla?.status === "overdue" && ["pendente", "aberta", "aguardando_atendimento"].includes(t.status)) {
          overdueIds.push(t.id);
        }
      }
    }
    setSelectedIds(overdueIds);
  }
  function exitSelectMode() {
    setSelectedIds([]);
    setSelectMode(false);
  }

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const params = {};
      if (selectedDate !== todayLocalISO()) {
        params.date_from = selectedDate;
        params.date_to = selectedDate;
      }
      const [g, cs, lg] = await Promise.all([
        api.lousaGrid(params),
        api.listCollaborators(),
        api.lousaLogs({ limit: 50 }),
      ]);
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
  }, [selectedDate]);

  useEffect(() => {
    refresh();
    const t1 = setInterval(refresh, 30000);  // refresh dados
    const t2 = setInterval(() => setTick((x) => x + 1), 5000);  // re-render p/ animação SLA
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [refresh]);

  // SSE: refresh imediato quando o worker Atlaz cria novas bolhas
  const [atlazFlash, setAtlazFlash] = useState("");
  useEventStream({
    onEvent: (name, data) => {
      if (name === "atlaz_bubbles_synced" && data?.created > 0) {
        setAtlazFlash(`🔗 ${data.created} nova(s) bolha(s) sincronizada(s) do Atlaz`);
        refresh();
        setTimeout(() => setAtlazFlash(""), 6000);
      }
    },
  });

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
    if (isLocked) { alert("Sistema bloqueado: dispositivo offline ou horário dessincronizado."); return; }
    setBusy(true);
    try {
      await api.lousaAdminClose(ticketId, { action, notes: notes || "" });
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleAdminOpen(ticketId) {
    if (isLocked) { alert("Sistema bloqueado: dispositivo offline ou horário dessincronizado."); return; }
    if (!window.confirm("Abrir esta nota em nome do colaborador?")) return;
    setBusy(true);
    try {
      await api.lousaAdminOpen(ticketId);
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleEditTicket(ticketId, payload) {
    if (isLocked) { alert("Sistema bloqueado."); return; }
    setBusy(true);
    try {
      await api.lousaEditTicket(ticketId, payload);
      await refresh();
      setEditingTicket(null);
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleReschedule({ new_date, new_time, notes }) {
    if (!reschedTicket || isLocked) return;
    setBusy(true);
    try {
      await api.lousaAdminClose(reschedTicket.id, {
        action: "reagendar", new_date, new_time, notes,
      });
      setReschedTicket(null);
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  const totalTickets = grid.columns.reduce((sum, c) => sum + (c.tickets?.length || 0), 0);
  const overdueCount = grid.columns.flatMap((c) => c.tickets || []).filter((t) => t.sla?.status === "overdue").length;

  // Detecta se data selecionada é passada/futura (para mostrar banner)
  const dateMode = (() => {
    const today = todayLocalISO();
    if (selectedDate === today) return "today";
    return selectedDate < today ? "past" : "future";
  })();

  // Dispara beep + notification se overdueCount aumentou (e usuário ativou)
  useEffect(() => {
    prevOverdueRef.current = maybeFireOverdueAlerts(prevOverdueRef.current, overdueCount);
  }, [overdueCount]);

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
            {grid.columns.length} técnico(s) · {totalTickets} serviço(s) ativos — arraste para transferir entre técnicos · <span style={{ color: "#475569" }}>duplo-clique abre serviço pendente</span>
            {overdueCount > 0 && (
              <span data-testid="overdue-counter" style={{ marginLeft: 10, padding: "2px 10px", background: "#dc2626", color: "white", borderRadius: 999, fontWeight: 800 }}>
                ⚠ {overdueCount} ATRASADA(S)
              </span>
            )}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <DateNavigator
            selectedDate={selectedDate}
            isToday={isToday}
            onPrev={() => shiftDay(-1)}
            onNext={() => shiftDay(1)}
            onToday={goToday}
            onChange={setSelectedDate}
          />
          <Button
            variant="soft"
            onClick={toggleSelectMode}
            data-testid="lousa-select-mode-toggle"
            title={selectMode ? "Sair do modo seleção" : "Selecionar várias bolhas para ação coletiva"}
            style={{
              background: selectMode ? "#e0e7ff" : "#f1f5f9",
              color: selectMode ? "#3730a3" : "#475569",
              border: `1px solid ${selectMode ? "#a5b4fc" : "#cbd5e1"}`,
            }}
          >
            {selectMode ? "✕ Sair seleção" : "🔲 Selecionar"}
          </Button>
          {selectMode && (
            <Button
              variant="soft"
              onClick={selectAllOverdue}
              data-testid="lousa-select-overdue-btn"
              title="Selecionar todas as bolhas atrasadas (SLA estourado)"
              style={{
                background: "#fee2e2", color: "#7f1d1d",
                border: "1px solid #fca5a5", fontWeight: 700,
              }}
              disabled={overdueCount === 0}
            >
              ⚠ Atrasadas ({overdueCount})
            </Button>
          )}
          <Button
            variant="soft"
            onClick={() => setShowHistory(true)}
            data-testid="lousa-history-btn"
            title="Histórico completo de notas (dia/mês/ano/período)"
          >
            📚 Histórico
          </Button>
          <Button
            variant="soft"
            onClick={toggleAlerts}
            data-testid="lousa-sla-alerts-toggle"
            title={alertsOn ? "Alertas sonoros ativos — clique para desligar" : "Ativar alertas sonoros para serviços atrasados"}
            style={{
              background: alertsOn ? "#dcfce7" : "#f1f5f9",
              color: alertsOn ? "#166534" : "#475569",
              border: `1px solid ${alertsOn ? "#86efac" : "#cbd5e1"}`,
            }}
          >
            {alertsOn ? "🔔 Alertas ON" : "🔕 Alertas OFF"}
          </Button>
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

      {isLocked && (
        <div data-testid="lousa-locked-banner" style={{
          background: "#fee2e2", border: "2px solid #dc2626", borderRadius: 12,
          padding: 14, marginBottom: 14, textAlign: "center", color: "#7f1d1d", fontWeight: 700,
        }}>
          🔒 LOUSA TRANCADA — {systemStatus.offline ? "dispositivo offline" : "horário dessincronizado"}.
          Todas as ações estão bloqueadas até a normalização.
        </div>
      )}

      {atlazFlash && (
        <div data-testid="lousa-atlaz-flash" style={{
          background: "linear-gradient(135deg,#ecfdf5,#d1fae5)",
          border: "1px solid #6ee7b7", borderRadius: 12,
          padding: "10px 14px", marginBottom: 14,
          color: "#064e3b", fontWeight: 700, fontSize: 13,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span>{atlazFlash}</span>
          <span style={{ fontSize: 11, opacity: 0.7 }}>atualizado em tempo real</span>
        </div>
      )}

      {dateMode !== "today" && (
        <div data-testid="lousa-date-banner" style={{
          background: dateMode === "past"
            ? "linear-gradient(90deg,#fef3c7,#fde68a)"
            : "linear-gradient(90deg,#dbeafe,#bfdbfe)",
          border: `1px solid ${dateMode === "past" ? "#fcd34d" : "#93c5fd"}`,
          borderRadius: 12, padding: "10px 16px", marginBottom: 14,
          display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10,
        }}>
          <div style={{ color: dateMode === "past" ? "#78350f" : "#1e40af", fontSize: 13, fontWeight: 600 }}>
            {dateMode === "past" ? "🕐 Visualizando dia passado" : "📅 Visualizando dia futuro"}
            {" — "}
            <strong>{formatBR(selectedDate)}</strong>
            {" · "}<span style={{ opacity: 0.8 }}>{totalTickets} serviço(s) neste dia</span>
            {" · "}<em style={{ opacity: 0.7 }}>modo somente leitura</em>
          </div>
          <Button variant="soft" onClick={goToday} data-testid="lousa-back-today-btn"
            style={{ background: "white", border: "1px solid #cbd5e1", fontWeight: 700 }}>
            ← Voltar para hoje
          </Button>
        </div>
      )}

      {/* Grade horizontal — coluna por técnico */}
      <div style={{
        display: "flex", gap: 14, overflowX: "auto", paddingBottom: 16, minHeight: 540,
        opacity: isLocked || !isToday ? 0.92 : 1, pointerEvents: isLocked ? "none" : "auto",
      }} data-testid="lousa-grid">
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
            onAdminOpen={handleAdminOpen}
            onEdit={(t) => setEditingTicket(t)}
            onReschedule={(t) => setReschedTicket(t)}
            busy={busy}
            selectMode={selectMode}
            selectedIds={selectedIds}
            onToggleSelect={toggleTicketSelected}
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
      {editingTicket && (
        <EditTicketModal
          ticket={editingTicket}
          onClose={() => setEditingTicket(null)}
          onSave={(payload) => handleEditTicket(editingTicket.id, payload)}
          busy={busy}
        />
      )}
      {reschedTicket && (
        <RescheduleModal
          ticket={reschedTicket}
          onClose={() => setReschedTicket(null)}
          onConfirm={handleReschedule}
          busy={busy}
        />
      )}
      {showHistory && <LousaHistoryModal onClose={() => setShowHistory(false)} />}
      {selectMode && (
        <BulkActionsBar
          selectedIds={selectedIds}
          onClear={clearSelection}
          onDone={() => { exitSelectMode(); refresh(); }}
        />
      )}
    </div>
  );
}

function TechColumn({ column, isDropTarget, blinkOverdue, onDragOver, onDragLeave, onDrop, onDragStart, onDragEnd, draggingId, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, maxPerSlot, onSlotDrop, selectMode, selectedIds, onToggleSelect }) {
  const c = column.collaborator;
  const state = column.clock_state;
  const slots = column.slots || [];
  const unscheduled = column.unscheduled || [];
  const recentResolved = column.recent_resolved || [];
  const totalTickets = column.tickets?.length || 0;
  const isOnline = state.is_online === true || (state.is_online === undefined && state.has_entrada && !state.ended_day && !state.in_intervalo);

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
        <div data-testid={`tech-avatar-${c.id}`} title={isOnline ? "Dispositivo online" : "Dispositivo offline"} style={{
          width: 42, height: 42, borderRadius: "50%",
          background: c.avatar ? `url(${c.avatar}) center/cover` : "linear-gradient(135deg,#0ea5e9,#0284c7)",
          display: "grid", placeItems: "center", color: "white", fontWeight: 800, fontSize: 16,
          border: `3px solid ${isOnline ? "#10b981" : "#f59e0b"}`,
          boxShadow: `0 0 0 2px ${isOnline ? "rgba(16,185,129,.18)" : "rgba(245,158,11,.18)"}`,
          position: "relative", flexShrink: 0,
        }}>
          {!c.avatar && (c.name?.[0] || "?").toUpperCase()}
          <span data-testid={`tech-online-dot-${c.id}`} style={{
            position: "absolute", bottom: -2, right: -2,
            width: 14, height: 14, borderRadius: "50%",
            background: isOnline ? "#10b981" : "#f59e0b",
            border: "2px solid white",
          }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 800, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {c.name}
            {c.is_test_mode && <span style={{ marginLeft: 6, fontSize: 9, background: "#a855f7", color: "white", padding: "1px 5px", borderRadius: 6 }}>🧪 TESTE</span>}
            {c.praca_id === "NOTA" && <span title="Praça Nota: bate ponto no endereço do serviço aberto" style={{ marginLeft: 4, fontSize: 9, background: "#0ea5e9", color: "white", padding: "1px 5px", borderRadius: 6 }}>📍 NOTA</span>}
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>
            {totalTickets} serviço(s) · {c.praca || "—"}
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

      {/* Serviços encerrados nas últimas 24h — texto simples para conferência (gap entre serviços) */}
      {recentResolved.length > 0 && (
        <div data-testid={`recent-resolved-${c.id}`} style={{
          marginTop: 10, padding: "6px 8px", background: "#f8fafc", border: "1px dashed #cbd5e1",
          borderRadius: 8, fontSize: 10, color: "#475569",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4, color: "#0f172a" }}>📒 Encerrados (24h)</div>
          {recentResolved.map((t) => (
            <div key={t.id} style={{ marginBottom: 4 }}>
              {t.gap_minutes_to_prev != null && (
                <div style={{ fontStyle: "italic", color: "#94a3b8", padding: "2px 0" }}>
                  ⏱ {fmtGap(t.gap_minutes_to_prev)} entre o serviço anterior e este
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                <span><strong>{TYPE_LABELS[t.type] || t.type}</strong> · {t.client_snapshot?.name}</span>
                <span style={{ color: "#0f172a", fontWeight: 700 }}>
                  {t.duration_minutes != null ? `🕐 ${fmtDuration(t.duration_minutes)}` : ""}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

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
            onAdminOpen={onAdminOpen}
            onEdit={onEdit}
            onReschedule={onReschedule}
            busy={busy}
            selectMode={selectMode}
            selectedIds={selectedIds}
            onToggleSelect={onToggleSelect}
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
                onAdminOpen={onAdminOpen}
                onEdit={onEdit}
                onReschedule={onReschedule}
                busy={busy}
                selectMode={selectMode}
                isSelected={selectedIds?.includes(t.id)}
                onToggleSelect={onToggleSelect}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SlotRow({ slot, techId, maxPerSlot, onSlotDrop, draggingId, onDragStart, onDragEnd, blinkOverdue, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, selectMode, selectedIds, onToggleSelect }) {
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
      {slot.tickets.map((t, idx) => (
        <React.Fragment key={t.id}>
          {idx > 0 && t.gap_minutes_to_prev != null && (
            <div data-testid={`gap-${t.id}`} style={{
              fontSize: 9, fontStyle: "italic", color: "#94a3b8",
              textAlign: "center", padding: "2px 0",
            }}>
              ⏱ {fmtGap(t.gap_minutes_to_prev)} de intervalo
            </div>
          )}
          <BubbleCard
            ticket={t}
            blinkOverdue={blinkOverdue}
            isDragging={draggingId === t.id}
            onDragStart={() => onDragStart(t.id)}
            onDragEnd={onDragEnd}
            onAdminClose={onAdminClose}
            onAdminOpen={onAdminOpen}
            onEdit={onEdit}
            onReschedule={onReschedule}
            busy={busy}
            selectMode={selectMode}
            isSelected={selectedIds?.includes(t.id)}
            onToggleSelect={onToggleSelect}
          />
        </React.Fragment>
      ))}
    </div>
  );
}

function BubbleCard({ ticket, blinkOverdue, isDragging, onDragStart, onDragEnd, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, selectMode, isSelected, onToggleSelect }) {
  const c = PRIORITY_COLORS[ticket.priority] || PRIORITY_COLORS.normal;
  const st = STATUS_LABEL[ticket.status] || { label: ticket.status, color: "#64748b" };
  const sla = ticket.sla || {};
  const ai = ticket.ai_score || {};
  const slaColor = sla.status === "overdue" ? "#dc2626" : sla.status === "warning" ? "#f59e0b" : "#10b981";
  const isOverdue = sla.status === "overdue";
  const [showActions, setShowActions] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiDetail, setAiDetail] = useState(null);
  const [aiBusy, setAiBusy] = useState(false);
  const isSelectable = selectMode && ["pendente", "aberta", "aguardando_atendimento"].includes(ticket.status);

  async function runAiAnalysis() {
    setAiBusy(true);
    try {
      const r = await api.lousaAiEvaluate(ticket.id);
      setAiDetail(r);
      setAiOpen(true);
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
    setAiBusy(false);
  }

  function handleDoubleClick(e) {
    e.stopPropagation();
    if (selectMode) return;
    if (onEdit) onEdit(ticket);
  }

  function handleClick(e) {
    if (selectMode) {
      e.stopPropagation();
      if (isSelectable && onToggleSelect) onToggleSelect(ticket.id);
      return;
    }
    setShowActions(!showActions);
  }

  return (
    <div
      draggable={!ticket.in_execution && !selectMode}
      onDragStart={(e) => {
        if (ticket.in_execution || selectMode) { e.preventDefault(); return; }
        e.dataTransfer.effectAllowed = "move"; onDragStart();
      }}
      onDragEnd={onDragEnd}
      onClick={handleClick}
      onMouseEnter={() => { if (!selectMode) setShowActions(true); }}
      onMouseLeave={() => { if (!selectMode) setShowActions(false); }}
      onDoubleClick={handleDoubleClick}
      data-testid={`bubble-card-${ticket.id}`}
      data-selected={isSelected ? "true" : "false"}
      title={selectMode
        ? (isSelectable ? (isSelected ? "Clique para desmarcar" : "Clique para selecionar") : "Não selecionável neste status")
        : ticket.in_execution
          ? "Em execução pelo técnico — bloqueado para mover/excluir · Duplo-clique para editar"
          : "Passe o mouse para ver ações · Duplo-clique para editar"}
      className={isOverdue && blinkOverdue ? "sla-overdue" : ""}
      style={{
        background: c.bg,
        border: `2px solid ${isSelected ? "#3b82f6" : isOverdue ? "#dc2626" : c.border}`,
        borderRadius: 14, padding: 10, marginBottom: 6,
        cursor: selectMode ? (isSelectable ? "pointer" : "not-allowed") : "grab",
        opacity: isDragging ? 0.4 : (selectMode && !isSelectable ? 0.55 : 1),
        position: "relative",
        boxShadow: isSelected
          ? "0 0 0 3px rgba(59,130,246,.25), 0 4px 12px rgba(59,130,246,.18)"
          : isDragging ? "none" : "0 2px 6px rgba(15,23,42,.08)",
        transition: "box-shadow .15s, border-color .15s",
      }}
    >
      {selectMode && (
        <div data-testid={`bubble-checkbox-${ticket.id}`} style={{
          position: "absolute", top: 6, left: 6,
          width: 22, height: 22, borderRadius: 6,
          background: isSelected ? "#3b82f6" : "rgba(255,255,255,.92)",
          border: `2px solid ${isSelected ? "#1d4ed8" : "#94a3b8"}`,
          display: "grid", placeItems: "center",
          color: "white", fontWeight: 900, fontSize: 14, zIndex: 2,
          pointerEvents: "none",
        }}>
          {isSelected ? "✓" : ""}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", gap: 4, alignItems: "start" }}>
        {c.label && (
          <span style={{ fontSize: 9, fontWeight: 900, color: c.text }}>{c.label}{ticket.scheduled_time ? ` · ${ticket.scheduled_time.substr(11, 5)}` : ""}</span>
        )}
        <span style={{ fontSize: 9, fontWeight: 800, color: st.color, background: "rgba(255,255,255,.7)", padding: "1px 6px", borderRadius: 6 }}>
          {st.label}
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 800, marginTop: 4, color: c.text }}>{ticket.client_snapshot.name}</div>
      <div style={{ fontSize: 11, color: "#64748b" }}>{TYPE_LABELS[ticket.type] || ticket.type} · {ticket.client_snapshot.neighborhood}</div>
      <div style={{ fontSize: 11, color: "#475569", marginTop: 4 }}>
        {ticket.client_snapshot.relato?.substring(0, 70)}{ticket.client_snapshot.relato?.length > 70 ? "..." : ""}
      </div>

      {/* SLA badge + AI score badge */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
        {ticket.status === "aberta" && sla.elapsed_minutes != null && (
          <div data-testid={`sla-${ticket.id}`} style={{
            fontSize: 10, fontWeight: 800, color: slaColor,
            display: "flex", alignItems: "center", gap: 4,
          }}>
            ⏱ {Math.floor(sla.elapsed_minutes)}min / {sla.sla_minutes}min ({sla.pct?.toFixed(0)}%)
            {sla.status === "overdue" && <span style={{ background: "#dc2626", color: "white", padding: "1px 6px", borderRadius: 6 }}>ATRASADO</span>}
            {sla.status === "warning" && <span style={{ background: "#f59e0b", color: "white", padding: "1px 6px", borderRadius: 6 }}>ATENÇÃO</span>}
          </div>
        )}
        {ai.score != null && (
          <span
            data-testid={`ai-score-${ticket.id}`}
            title={`Score heurístico: ${ai.label}\n` + (ai.signals || []).map((s) => `• ${s.msg}`).join("\n")}
            style={{
              fontSize: 10, fontWeight: 900, padding: "2px 8px", borderRadius: 999,
              background: aiScoreColor(ai.score), color: "white",
              display: "inline-flex", alignItems: "center", gap: 4,
            }}
          >
            🤖 {ai.score.toFixed(1)}/10
          </span>
        )}
      </div>

      {/* Duração no canto inf-direito */}
      {ticket.duration_minutes != null && (
        <div data-testid={`duration-${ticket.id}`} style={{
          position: "absolute", right: 10, bottom: 6,
          fontSize: 10, fontWeight: 800, color: "#0f172a",
          background: "rgba(255,255,255,.85)", padding: "1px 6px",
          borderRadius: 6, border: "1px solid #e2e8f0",
        }}>
          🕐 {fmtDuration(ticket.duration_minutes)}
        </div>
      )}

      {ticket.in_execution && (
        <div data-testid={`in-execution-${ticket.id}`} style={{
          position: "absolute", top: 6, left: selectMode ? 34 : 6,
          fontSize: 9, fontWeight: 900, color: "white",
          background: "linear-gradient(90deg,#10b981,#059669)",
          padding: "2px 7px", borderRadius: 999,
          textTransform: "uppercase", letterSpacing: 0.5,
          boxShadow: "0 0 0 2px rgba(16,185,129,.2)",
          animation: "pulse 1.6s ease-in-out infinite",
        }}>
          ▶ Em execução
        </div>
      )}
      {ticket.locked && (
        <span style={{ position: "absolute", top: 6, right: 6, fontSize: 14 }}>🔒</span>
      )}
      {ticket.atlaz_external_id && (
        <span data-testid={`atlaz-badge-${ticket.id}`}
          title={`Sincronizada do Atlaz · ID externo: ${ticket.atlaz_external_id}${ticket.atlaz_filial ? ` · Filial: ${ticket.atlaz_filial}` : ""}`}
          style={{
            position: "absolute", bottom: 6, left: 8,
            fontSize: 9, fontWeight: 800, color: "#1e40af",
            background: "rgba(219,234,254,.95)", border: "1px solid #93c5fd",
            padding: "1px 6px", borderRadius: 6,
          }}>
          🔗 Atlaz
        </span>
      )}
      {!selectMode && showActions && ["pendente", "aberta", "aguardando_atendimento"].includes(ticket.status) && (
        <div onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}>
          {ticket.status === "pendente" && onAdminOpen && (
            <button data-testid={`admin-open-${ticket.id}`} disabled={busy}
              onClick={() => onAdminOpen(ticket.id)} style={btnSm("#10b981")}>▶ Abrir</button>
          )}
          {onEdit && (
            <button data-testid={`admin-edit-${ticket.id}`} disabled={busy}
              onClick={() => onEdit(ticket)} style={btnSm("#0ea5e9")}>✎ Editar</button>
          )}
          <button data-testid={`ai-evaluate-${ticket.id}`} disabled={aiBusy}
            onClick={runAiAnalysis} style={btnSm("#a855f7")}>🤖 IA {aiBusy ? "..." : ""}</button>
          <button data-testid={`admin-close-${ticket.id}`} disabled={busy}
            onClick={() => { const n = window.prompt("Notas:"); if (n !== null) onAdminClose(ticket.id, "encerrar", n); }} style={btnSm("#64748b")}>✓ Encerrar</button>
          <button data-testid={`admin-reschedule-${ticket.id}`} disabled={busy}
            onClick={(e) => { e.stopPropagation(); if (onReschedule) onReschedule(ticket); }} style={btnSm("#3b82f6")}>📅 Reagendar</button>
          <button disabled={busy}
            onClick={() => { const n = window.prompt("Motivo do cancelamento:"); if (n) onAdminClose(ticket.id, "cancelar", n); }} style={btnSm("#dc2626")}>✗ Cancelar</button>
        </div>
      )}
      {aiOpen && aiDetail && (
        <AiDetailModal detail={aiDetail} onClose={() => setAiOpen(false)} />
      )}
    </div>
  );
}

function AiDetailModal({ detail, onClose }) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 110, display: "grid", placeItems: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="ai-detail-modal"
           style={{ background: "white", borderRadius: 18, padding: 22, maxWidth: 540, width: "100%", maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>🤖 Avaliação IA do Serviço</h2>
          <span style={{ background: aiScoreColor(detail.ai_score), color: "white", padding: "4px 12px", borderRadius: 999, fontWeight: 900, fontSize: 14 }}>
            {detail.ai_score?.toFixed(1)}/10
          </span>
        </div>
        <div style={{ fontSize: 13, color: "#475569", marginBottom: 8 }}>
          <strong>Veredito:</strong> {detail.verdict} · <span style={{ color: "#94a3b8", fontSize: 11 }}>({detail.method})</span>
        </div>
        <p style={{ background: "#f8fafc", padding: 10, borderRadius: 8, fontSize: 13, color: "#0f172a", margin: "8px 0" }}>
          {detail.summary}
        </p>
        {detail.recommendations?.length > 0 && (
          <>
            <h4 style={{ fontSize: 13, margin: "10px 0 4px" }}>Recomendações</h4>
            <ul style={{ paddingLeft: 18, margin: 0, fontSize: 12, color: "#334155" }}>
              {detail.recommendations.map((r, i) => <li key={i} style={{ marginBottom: 4 }}>{r}</li>)}
            </ul>
          </>
        )}
        {detail.heuristic?.signals?.length > 0 && (
          <>
            <h4 style={{ fontSize: 13, margin: "12px 0 4px" }}>Sinais (heurística)</h4>
            <div style={{ fontSize: 11 }}>
              {detail.heuristic.signals.map((s, i) => (
                <div key={i} style={{
                  padding: "4px 8px", marginBottom: 3, borderRadius: 6,
                  background: s.level === "critical" ? "#fee2e2" : s.level === "warning" ? "#fef3c7" : "#dcfce7",
                  color: s.level === "critical" ? "#7f1d1d" : s.level === "warning" ? "#78350f" : "#166534",
                }}>
                  {s.level === "critical" ? "🔴" : s.level === "warning" ? "🟡" : "🟢"} {s.msg}
                </div>
              ))}
            </div>
          </>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
          <Button variant="soft" onClick={onClose}>Fechar</Button>
        </div>
      </div>
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

function fmtDuration(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h${String(m).padStart(2, "0")}` : `${m}min`;
}

function fmtGap(min) {
  if (min == null) return "—";
  if (min < 60) return `${Math.round(min)}min`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return `${h}h${String(m).padStart(2, "0")}`;
}

function aiScoreColor(score) {
  if (score == null) return "#94a3b8";
  if (score >= 8.5) return "#10b981";
  if (score >= 7.0) return "#3b82f6";
  if (score >= 5.0) return "#f59e0b";
  return "#dc2626";
}

function todayLocalISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatBR(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function DateNavigator({ selectedDate, isToday, onPrev, onNext, onToday, onChange }) {
  const dateObj = new Date(selectedDate + "T12:00:00");
  const weekday = dateObj.toLocaleDateString("pt-BR", { weekday: "short" });
  return (
    <div data-testid="lousa-date-navigator" style={{
      display: "flex", alignItems: "center", gap: 6,
      background: isToday ? "#f0f9ff" : "#fef3c7",
      border: `1px solid ${isToday ? "#bae6fd" : "#fcd34d"}`,
      borderRadius: 999, padding: "4px 8px",
    }}>
      <button
        data-testid="lousa-date-prev"
        onClick={onPrev}
        title="Dia anterior"
        style={navBtnStyle}
      >◀</button>
      <input
        type="date"
        data-testid="lousa-date-input"
        value={selectedDate}
        onChange={(e) => onChange(e.target.value)}
        style={{
          border: "none", outline: "none", background: "transparent",
          fontSize: 13, fontWeight: 700, color: "#0f172a",
          fontFamily: "inherit", cursor: "pointer", padding: "2px 4px",
        }}
      />
      <span style={{ fontSize: 11, color: "#64748b", textTransform: "capitalize", marginRight: 4 }}>
        {weekday.replace(".", "")}
      </span>
      <button
        data-testid="lousa-date-next"
        onClick={onNext}
        title="Próximo dia"
        style={navBtnStyle}
      >▶</button>
      {!isToday && (
        <button
          data-testid="lousa-date-today"
          onClick={onToday}
          title="Voltar para hoje"
          style={{
            ...navBtnStyle, background: "#0ea5e9", color: "white",
            padding: "3px 10px", fontWeight: 700, fontSize: 11,
          }}
        >Hoje</button>
      )}
    </div>
  );
}

const navBtnStyle = {
  border: 0, background: "white", borderRadius: 999,
  width: 26, height: 26, display: "grid", placeItems: "center",
  cursor: "pointer", fontSize: 12, color: "#475569",
  boxShadow: "0 1px 2px rgba(15,23,42,.08)",
};
