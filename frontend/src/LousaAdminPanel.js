import React, { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/api";
import { Button, Icon } from "@/ui";
import { useAuth } from "@/AuthContext";
import EditTicketModal from "./lousa/EditTicketModal";
import CreateTicketModal from "./lousa/CreateTicketModal";
import RescheduleModal from "./lousa/RescheduleModal";
import LousaHistoryModal from "./lousa/LousaHistoryModal";
import BulkActionsBar from "./lousa/BulkActionsBar";
import useEventStream from "@/useEventStream";
import { isAlertsEnabled, setAlertsEnabled, maybeFireOverdueAlerts } from "./slaAlerts";
import SentinelaLousaCard from "./SentinelaLousaCard";
import ReleaseStuckBubbleModal from "./lousa/ReleaseStuckBubbleModal";
import CentralOntPanel from "./lousa/CentralOntPanel";
import GestaoMetasPanel from "./lousa/GestaoMetasPanel";
import LousaQualityNotesPanel from "./LousaQualityNotesPanel";

const TYPE_LABELS = {
  reparo: "🔧 Reparo",
  instalacao: "📡 Instalação",
  retirada: "📦 Retirada",
  prioridade: "🚨 Prioridade",
  preventiva: "🛡️ Preventiva",
  venda: "💼 Venda",
  alerta_geofence: "⚠️ ALERTA GEOFENCE",
};

const TYPE_ICONS = {
  instalacao: "🔧",
  retirada: "📦",
  visita_tecnica: "🛠️",
  manutencao: "🔩",
  upgrade: "⬆️",
  downgrade: "⬇️",
  troca_endereco: "🏠",
  troca_titularidade: "👤",
  cancelamento: "🚫",
  outros: "📋",
  venda: "💼",
};

const PRIORITY_COLORS = {
  prioridade: {
    bg: "#fff7f7",
    accent: "#dc2626", border: "#fecaca", text: "#991b1b",
    label: "PRIORIDADE", icon: "",
  },
  horario: {
    bg: "#fffbeb",
    accent: "#d97706", border: "#fde68a", text: "#78350f",
    label: "HORÁRIO", icon: "",
  },
  normal: {
    bg: "#ffffff",
    accent: "#0d9488", border: "#e6e8ee", text: "#0b1220",
    label: "", icon: "",
  },
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
  transferida: { icon: "↔", color: "#0d9488", label: "Transferida" },
};

export default function LousaAdminPanel({ systemStatus = { offline: false, drift_blocked: false } }) {
  const { user } = useAuth();
  const [grid, setGrid] = useState({ columns: [], sla_blink_when_overdue: true, sla_warning_pct: 80 });
  const [collabs, setCollabs] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editingTicket, setEditingTicket] = useState(null);
  const [reschedTicket, setReschedTicket] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showSentinela, setShowSentinela] = useState(false);
  const [showReleaseStuck, setShowReleaseStuck] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState("board"); // board | central_ont
  const [sentinelaCount, setSentinelaCount] = useState(0);
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
      await window.alert("Erro ao atualizar: " + (e?.message || e));
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

  // Carrega domínio Atlaz uma vez (para o botão "+ Nova nota" abrir o painel externo)
  useEffect(() => {
    let mounted = true;
    api.atlazGetSettings()
      .then((cfg) => { if (mounted) setAtlazTenantDomain((cfg?.tenant_domain || "").replace(/\/$/, "")); })
      .catch(() => {});
    return () => { mounted = false; };
  }, []);

  // Polling do contador da Sentinela Lousa AI
  useEffect(() => {
    let alive = true;
    const fetchCount = () => {
      api.sentinelaSummary()
        .then((s) => { if (alive) setSentinelaCount(s?.active || 0); })
        .catch(() => {});
    };
    fetchCount();
    const t = setInterval(fetchCount, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  function openCreateTicket() {
    // Se houver domínio Atlaz configurado, abre o painel externo (criação no Atlaz).
    // Caso contrário, fallback para o modal local de criação de bolha.
    if (atlazTenantDomain) {
      const url = `${atlazTenantDomain}/admin/tickets/list?new=1`;
      window.open(url, "_blank", "noopener,noreferrer");
    } else {
      setShowCreate(true);
    }
  }

  async function handleDrop(targetCollabId) {
    if (!draggingId) return;
    setBusy(true);
    try {
      await api.lousaTransferTicket(draggingId, { new_collaborator_id: targetCollabId });
      await refresh();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
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
      await window.alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
    setDraggingId(null);
    setDragOverCol(null);
  }

  async function handleAdminClose(ticketId, action, notes) {
    if (isLocked) { await window.alert("Sistema bloqueado: dispositivo offline ou horário dessincronizado."); return; }
    setBusy(true);
    try {
      await api.lousaAdminClose(ticketId, { action, notes: notes || "" });
      await refresh();
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleAdminOpen(ticketId) {
    if (isLocked) { await window.alert("Sistema bloqueado: dispositivo offline ou horário dessincronizado."); return; }
    if (!await window.confirm("Abrir esta nota em nome do colaborador?")) return;
    setBusy(true);
    try {
      await api.lousaAdminOpen(ticketId);
      await refresh();
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleEditTicket(ticketId, payload) {
    if (isLocked) { await window.alert("Sistema bloqueado."); return; }
    setBusy(true);
    try {
      await api.lousaEditTicket(ticketId, payload);
      await refresh();
      setEditingTicket(null);
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
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
      await window.alert(e?.response?.data?.detail || e.message);
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

      <div className="page-header" style={{ marginTop: 0, paddingTop: 0 }}>
        <div>
          <h1 className="page-title" style={{ fontSize: 22 }}>Lousa de Serviços</h1>
          <p className="page-subtitle">
            {grid.columns.length} técnico(s) · {totalTickets} serviço(s) ativos — arraste para transferir entre técnicos · duplo-clique abre serviço pendente
            {overdueCount > 0 && (
              <span data-testid="overdue-counter" className="pill pill--danger" style={{ marginLeft: 10, fontWeight: 700 }}>
                {overdueCount} atrasada(s)
              </span>
            )}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Button
            variant="soft"
            onClick={() => setShowSentinela(true)}
            data-testid="open-sentinela-btn"
            title="Alertas da Sentinela Lousa AI"
            style={{
              position: "relative",
              background: sentinelaCount > 0 ? "#fef2f2" : "#f0fdf4",
              color: sentinelaCount > 0 ? "#991b1b" : "#15803d",
              border: `1px solid ${sentinelaCount > 0 ? "#fecaca" : "#bbf7d0"}`,
              fontWeight: 700,
            }}
          >
            🛡 Sentinela
            {sentinelaCount > 0 && (
              <span data-testid="sentinela-badge" style={{
                marginLeft: 6, padding: "1px 7px", borderRadius: 999,
                background: "#dc2626", color: "#fff",
                fontSize: 11, fontWeight: 800,
                fontFamily: "ui-monospace, monospace",
              }}>{sentinelaCount}</span>
            )}
          </Button>
          <DateNavigator
            selectedDate={selectedDate}
            isToday={isToday}
            onPrev={() => shiftDay(-1)}
            onNext={() => shiftDay(1)}
            onToday={goToday}
            onChange={setSelectedDate}
          />
          {user?.role === "auditor" && (
            <Button
              variant="soft"
              onClick={async () => {
                const phrase = await window.prompt(
                  "⚠ ATENÇÃO: isto APAGA TODAS as bolhas da empresa, incluindo as em execução.\n" +
                  "Ação irreversível e auditada (logs).\n\n" +
                  "Digite APAGAR TUDO para confirmar:");
                if (phrase !== "APAGAR TUDO") return;
                try {
                  const res = await api.lousaWipeAll();
                  await window.alert(`✓ ${res.deleted_count} bolha(s) apagadas.`);
                  refresh();
                } catch (e) {
                  await window.alert("Falha: " + (e?.response?.data?.detail || e.message));
                }
              }}
              data-testid="lousa-wipe-all-btn"
              title="AUDITOR — Apaga todas as bolhas. Ação irreversível e logada."
              style={{
                background: "#fee2e2", color: "#7f1d1d",
                border: "1px solid #f87171", fontWeight: 700,
              }}
            >
              🗑 Apagar todas
            </Button>
          )}
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
            onClick={() => setShowReleaseStuck(true)}
            data-testid="lousa-release-stuck-btn"
            title="EMERGÊNCIA — libera bolha presa do técnico (ação auditada)"
            style={{
              background: "#fee2e2", color: "#991b1b",
              border: "1.5px solid #dc2626", fontWeight: 800,
            }}
          >
            🚨 Liberar bolha
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
          <Button onClick={openCreateTicket} data-testid="lousa-create-btn"
            title={atlazTenantDomain ? `Abre o painel Atlaz (${atlazTenantDomain}) em nova aba` : "Cria uma nova nota local"}>
            <Icon name="plus" /> Nova nota{atlazTenantDomain ? " 🔗" : ""}
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
          background: "var(--accent-soft)",
          border: "1px solid #99f6e4", borderRadius: 8,
          padding: "10px 14px", marginBottom: 14,
          color: "var(--accent-soft-fg)", fontWeight: 600, fontSize: 13,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span>{atlazFlash}</span>
          <span style={{ fontSize: 11, opacity: 0.7 }}>atualizado em tempo real</span>
        </div>
      )}

      {dateMode !== "today" && (
        <div data-testid="lousa-date-banner" style={{
          background: dateMode === "past" ? "var(--warning-soft)" : "var(--info-soft)",
          border: `1px solid ${dateMode === "past" ? "#fcd34d" : "#93c5fd"}`,
          borderRadius: 8, padding: "10px 16px", marginBottom: 14,
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

      {/* SUB-TABS — Quadro / CENTRAL_ONT / GESTÃO E METAS */}
      <div style={{ display: "flex", gap: 4,
                      borderBottom: "1px solid #e2e8f0", marginBottom: 14 }}>
        {[
          { id: "board", label: "📋 Quadro" },
          { id: "insights", label: "🧠 PAINEL IA" },
          { id: "central_ont", label: "🛰️ CENTRAL_ONT" },
          { id: "gestao_metas", label: "📊 GESTÃO E METAS" },
          { id: "quality_notes", label: "📶 NOTAS DE QUALIDADE" },
        ].map((t) => (
          <button key={t.id} onClick={() => setActiveSubTab(t.id)}
                   data-testid={`lousa-subtab-${t.id}`}
                   style={{
                     padding: "10px 16px", border: "none",
                     background: "transparent", cursor: "pointer",
                     fontSize: 13, fontWeight: activeSubTab === t.id ? 700 : 500,
                     color: activeSubTab === t.id ? "#0ea5e9" : "#64748b",
                     borderBottom: "2px solid "
                        + (activeSubTab === t.id ? "#0ea5e9" : "transparent"),
                     marginBottom: -1, transition: "color 150ms",
                   }}>{t.label}</button>
        ))}
      </div>

      {activeSubTab === "gestao_metas" ? <GestaoMetasPanel /> :
        (activeSubTab === "central_ont" ? <CentralOntPanel /> :
        (activeSubTab === "quality_notes" ? <LousaQualityNotesPanel /> :
        (activeSubTab === "insights"
          ? <InsightsPanel onJumpTicket={(t) => setEditingTicket(t)} />
          : <></>)))}
      {activeSubTab === "board" && <>
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
      </>}

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
      {showReleaseStuck && (
        <ReleaseStuckBubbleModal
          onClose={() => setShowReleaseStuck(false)}
          onReleased={refresh}
        />
      )}
      {showSentinela && (
        <div data-testid="sentinela-drawer"
              onClick={() => setShowSentinela(false)}
              style={{
                position: "fixed", inset: 0, zIndex: 1000,
                background: "rgba(0,0,0,.5)",
                display: "flex", justifyContent: "flex-end",
              }}>
          <div onClick={(e) => e.stopPropagation()}
                style={{
                  width: "min(720px, 95vw)", height: "100%",
                  background: "var(--bg-canvas)",
                  overflowY: "auto",
                  padding: 22,
                  boxShadow: "-12px 0 30px rgba(0,0,0,.2)",
                }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "center", marginBottom: 14 }}>
              <strong style={{ fontSize: 13, color: "var(--text-muted)",
                                  textTransform: "uppercase",
                                  letterSpacing: 0.6 }}>
                Sentinela Lousa AI
              </strong>
              <button onClick={() => setShowSentinela(false)}
                        data-testid="close-sentinela-btn"
                        style={{
                          padding: "5px 10px", fontSize: 11, fontWeight: 700,
                          border: "1px solid var(--border-default)",
                          background: "var(--bg-surface)",
                          color: "var(--text-secondary)",
                          borderRadius: 5, cursor: "pointer",
                        }}>Fechar ✕</button>
            </div>
            <SentinelaLousaCard />
          </div>
        </div>
      )}
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


function OptimizeRouteButton({ collaboratorId }) {
  const [busy, setBusy] = React.useState(false);
  async function go() {
    if (!await window.confirm("Otimizar a rota deste técnico usando a posição GPS dele?\nA ordem das bolhas será reescrita.")) return;
    setBusy(true);
    try {
      const r = await api._client.post("/lousa/admin/optimize-route", {
        collaborator_id: collaboratorId, apply: true,
      }).then((x) => x.data);
      if (!r.ok) {
        await window.alert("Nada pra otimizar: " + (r.reason || "—"));
      } else {
        await window.alert(`✓ Rota otimizada\n${r.stops} paradas · ${r.total_km}km · ${r.estimated_minutes}min`);
        window.location.reload();
      }
    } catch (e) {
      await window.alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  }
  return (
    <button
      data-testid={`optimize-route-${collaboratorId}`}
      onClick={go} disabled={busy} title="Otimizar rota por GPS"
      style={{
        background: "linear-gradient(135deg,#06b6d4,#0e7490)",
        color: "white", border: "none", borderRadius: 8,
        padding: "4px 8px", fontSize: 10, fontWeight: 700,
        cursor: busy ? "wait" : "pointer", flexShrink: 0,
      }}
    >{busy ? "..." : "🗺️ Rota"}</button>
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
        background: isDropTarget ? "var(--accent-soft)" : "var(--bg-surface)",
        border: `1px ${isDropTarget ? "dashed" : "solid"} ${isDropTarget ? "var(--accent)" : "var(--border-default)"}`,
        borderRadius: 12, padding: 12, transition: "all .15s",
        boxShadow: "var(--shadow-xs)",
      }}
    >
      <div style={{ display: "flex", gap: 10, alignItems: "center", paddingBottom: 10, borderBottom: "1px solid var(--border-default)" }}>
        <div data-testid={`tech-avatar-${c.id}`} title={isOnline ? "Dispositivo online" : "Dispositivo offline"} style={{
          width: 38, height: 38, borderRadius: "50%",
          background: c.avatar ? `url(${c.avatar}) center/cover` : "linear-gradient(135deg,#0d9488,#0f766e)",
          display: "grid", placeItems: "center", color: "white", fontWeight: 700, fontSize: 14,
          border: `2px solid ${isOnline ? "#16a34a" : "#d97706"}`,
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
            {c.is_test_mode && <span style={{ marginLeft: 6, fontSize: 9, background: "var(--bg-surface-3)", color: "var(--text-secondary)", padding: "1px 6px", borderRadius: 6, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase" }}>teste</span>}
            {c.praca_id === "NOTA" && <span title="Praça Nota: bate ponto no endereço do serviço aberto" style={{ marginLeft: 4, fontSize: 9, background: "var(--accent-soft)", color: "var(--accent-soft-fg)", padding: "1px 6px", borderRadius: 6, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase" }}>nota</span>}
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>
            {totalTickets} serviço(s) · {c.praca || "—"}
          </div>
        </div>
        <OptimizeRouteButton collaboratorId={c.id} />
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
  const [expanded, setExpanded] = useState(false);
  const isFull = slot.full;
  const tickets = slot.tickets || [];
  const isEmpty = tickets.length === 0;
  // Altura fixa do slot (regra do horário): independente da quantidade de bolhas.
  // Bolhas extras ficam interpostas (offset vertical de 6px). Hover/click "expande" pra ver todas.
  const SLOT_BASE_HEIGHT = 64;          // altura fixa = 1 bolha
  const STACK_OFFSET = 6;               // deslocamento vertical entre bolhas empilhadas

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
        borderRadius: 8, padding: 6,
        height: SLOT_BASE_HEIGHT,         // ALTURA FIXA — não cresce com mais bolhas
        position: "relative",
        transition: "all .15s",
      }}
    >
      <div style={{
        fontSize: 10, fontWeight: 800, color: isFull ? "#92400e" : "#475569",
        marginBottom: isEmpty ? 0 : 4, display: "flex", justifyContent: "space-between",
      }}>
        <span>🕐 {slot.slot}</span>
        <span style={{ fontSize: 9 }}>
          {tickets.length}/{maxPerSlot}{isFull && " 🔒 cheio"}
          {tickets.length > 1 && (
            <button onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
                    data-testid={`slot-expand-${techId}-${slot.slot}`}
                    style={{ marginLeft: 4, padding: "0 4px", fontSize: 9, border: "1px solid #cbd5e1",
                             background: "white", borderRadius: 4, cursor: "pointer" }}>
              {expanded ? "↑ recolher" : `+${tickets.length - 1} 👁`}
            </button>
          )}
        </span>
      </div>
      {isEmpty && (
        <div style={{ fontSize: 10, color: "#cbd5e1", textAlign: "center", padding: 2, fontStyle: "italic" }}>
          {over ? "↓ Solte aqui ↓" : "vazio"}
        </div>
      )}
      {/* Tickets — em stack absoluto quando há mais de 1, pra preservar altura fixa */}
      {tickets.length > 0 && (
        <div style={{ position: "relative", height: SLOT_BASE_HEIGHT - 22 }}>
          {tickets.map((t, idx) => (
            <div key={t.id} data-testid={`stacked-${idx}-${t.id}`}
                 style={{
                   position: "absolute",
                   top: expanded ? `${idx * (SLOT_BASE_HEIGHT - 8)}px` : `${idx * STACK_OFFSET}px`,
                   left: 0, right: 0,
                   zIndex: 100 - idx,    // primeira bolha por cima
                   transition: "top .25s ease",
                   cursor: tickets.length > 1 ? "pointer" : "default",
                 }}
                 onClick={() => tickets.length > 1 && setExpanded((v) => !v)}
                 title={tickets.length > 1 ? `Slot com ${tickets.length} bolhas — clique pra expandir/recolher` : undefined}>
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
            </div>
          ))}
        </div>
      )}
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
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
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

  // Tooltip rico (nativo) — mostra quando passar mouse
  const tooltipText = selectMode
    ? (isSelectable ? (isSelected ? "Clique para desmarcar" : "Clique para selecionar") : "Não selecionável neste status")
    : [
        `${TYPE_LABELS[ticket.type] || ticket.type}`,
        `Cliente: ${ticket.client_snapshot.name}`,
        ticket.client_snapshot.phone ? `Tel: ${ticket.client_snapshot.phone}` : null,
        ticket.client_snapshot.address ? `End.: ${ticket.client_snapshot.address}` : null,
        ticket.client_snapshot.neighborhood ? `Bairro: ${ticket.client_snapshot.neighborhood}` : null,
        ticket.scheduled_time ? `Horário: ${ticket.scheduled_time.substr(11, 5)}` : null,
        ticket.client_snapshot.relato ? `\nRelato:\n${ticket.client_snapshot.relato}` : null,
        ai.score != null ? `\nIA: ${ai.score.toFixed(1)}/10 (${ai.label || ""})` : null,
        ticket.in_execution ? "\n▶ Em execução pelo técnico" : null,
        ticket.atlaz_external_id ? `\n🔗 Atlaz #${ticket.atlaz_external_id}` : null,
        "\n— Duplo-clique para editar",
      ].filter(Boolean).join("\n");

  const typeIcon = TYPE_ICONS[ticket.type] || "📋";

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
      title={tooltipText}
      className={
        (ticket.type === "alerta_geofence" ? "lousa-alert-blink " : "")
        + (isOverdue && blinkOverdue ? "sla-overdue" : "")
      }
      style={{
        background: ticket.type === "alerta_geofence"
          ? "linear-gradient(135deg,#fee2e2,#fecaca)"
          : c.bg,
        border: `${ticket.type === "alerta_geofence" ? 2 : 1}px solid ${
          ticket.type === "alerta_geofence" ? "#dc2626"
          : isSelected ? "#3b82f6"
          : isOverdue ? "#dc2626" : c.border}`,
        borderRadius: 14, padding: "10px 12px 10px 14px",
        marginBottom: 6, position: "relative",
        cursor: selectMode ? (isSelectable ? "pointer" : "not-allowed") : "grab",
        opacity: isDragging ? 0.4 : (selectMode && !isSelectable ? 0.55 : 1),
        boxShadow: isSelected
          ? "0 0 0 3px rgba(59,130,246,.25), 0 4px 12px rgba(59,130,246,.18)"
          : isDragging ? "none"
          : isOverdue ? "0 4px 14px rgba(220,38,38,.18)"
          : "0 1px 3px rgba(15,23,42,.06), 0 2px 6px rgba(15,23,42,.04)",
        transition: "box-shadow .2s, border-color .2s, transform .15s",
        overflow: "hidden",
      }}
    >
      {/* Faixa lateral colorida (priority accent) */}
      {ticket.priority !== "normal" && (
        <span aria-hidden style={{
          position: "absolute", left: 0, top: 0, bottom: 0,
          width: 4, background: c.accent, borderRadius: "14px 0 0 14px",
        }} />
      )}

      {selectMode && (
        <div data-testid={`bubble-checkbox-${ticket.id}`} style={{
          position: "absolute", top: 8, left: 8,
          width: 22, height: 22, borderRadius: 6,
          background: isSelected ? "#3b82f6" : "rgba(255,255,255,.95)",
          border: `2px solid ${isSelected ? "#1d4ed8" : "#94a3b8"}`,
          display: "grid", placeItems: "center",
          color: "white", fontWeight: 900, fontSize: 14, zIndex: 2,
          pointerEvents: "none",
        }}>
          {isSelected ? "✓" : ""}
        </div>
      )}

      {/* HEADER: badge prioridade · status · horário */}
      <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", minWidth: 0 }}>
          {c.label && (
            <span style={{
              fontSize: 9, fontWeight: 900, letterSpacing: 0.5,
              padding: "2px 7px", borderRadius: 999,
              background: c.accent, color: "white",
            }}>{c.icon} {c.label}</span>
          )}
          {ticket.scheduled_time && (
            <span style={{
              fontSize: 10, fontWeight: 800, color: "#475569",
              background: "#f1f5f9", padding: "2px 7px", borderRadius: 999,
              border: "1px solid #e2e8f0",
            }}>{ticket.scheduled_time.substr(11, 5)}</span>
          )}
        </div>
        <span style={{
          fontSize: 9, fontWeight: 800, letterSpacing: 0.3,
          color: st.color, padding: "2px 7px", borderRadius: 999,
          background: "rgba(255,255,255,.85)", border: `1px solid ${st.color}33`,
          flexShrink: 0,
        }}>{st.label}</span>
      </div>

      {/* BODY: ícone do tipo + cliente + tipo */}
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <div aria-hidden style={{
          width: 36, height: 36, borderRadius: 10,
          background: ticket.priority === "normal" ? "#f1f5f9" : "rgba(255,255,255,.85)",
          border: `1px solid ${c.border}`,
          display: "grid", placeItems: "center",
          fontSize: 18, flexShrink: 0,
        }}>{typeIcon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 13.5, fontWeight: 800, color: c.text,
            lineHeight: 1.25, letterSpacing: -0.1,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>{ticket.client_snapshot.name}</div>
          <div style={{
            fontSize: 11, color: "#64748b", marginTop: 1,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {TYPE_LABELS[ticket.type]?.replace(/^\S+\s/, "") || ticket.type}
            {ticket.client_snapshot.neighborhood ? ` · ${ticket.client_snapshot.neighborhood}` : ""}
          </div>
        </div>
      </div>

      {/* SINAL SMARTOLT (pill compacto — todas as bolhas que têm match) */}
      {ticket.live_signal && (
        <div
          data-testid={`signal-pill-${ticket.id}`}
          title={`SmartOLT · ${ticket.live_signal.name || ""} · ${ticket.live_signal.olt_name || ""} · status ${ticket.live_signal.status || "?"} · ${ticket.live_signal.signal_text || ""}`}
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            marginTop: 6, padding: "2px 8px", borderRadius: 999,
            fontSize: 10, fontWeight: 800, fontFamily: "monospace",
            border: "1px solid",
            background: ticket.live_signal.quality === "good" ? "#dcfce7"
              : ticket.live_signal.quality === "warn" ? "#fef3c7"
              : ticket.live_signal.quality === "bad" ? "#fee2e2" : "#f1f5f9",
            color: ticket.live_signal.quality === "good" ? "#15803d"
              : ticket.live_signal.quality === "warn" ? "#a16207"
              : ticket.live_signal.quality === "bad" ? "#b91c1c" : "#475569",
            borderColor: ticket.live_signal.quality === "good" ? "#86efac"
              : ticket.live_signal.quality === "warn" ? "#fde68a"
              : ticket.live_signal.quality === "bad" ? "#fca5a5" : "#cbd5e1",
          }}
        >
          📶 {ticket.live_signal.rx_dbm != null ? `${ticket.live_signal.rx_dbm.toFixed(1)} dBm` : "—"}
          {ticket.live_signal.status === "Online" && <span style={{ fontSize: 8 }}>🟢</span>}
          {ticket.live_signal.status && ticket.live_signal.status !== "Online" && <span style={{ fontSize: 8 }}>🔴</span>}
        </div>
      )}

      {/* FOOTER (SLA + IA) */}
      {(ticket.status === "aberta" || ai.score != null) && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6, marginTop: 8,
          flexWrap: "wrap", paddingTop: 6,
          borderTop: "1px dashed rgba(15,23,42,.08)",
        }}>
          {ticket.status === "aberta" && sla.elapsed_minutes != null && (
            <div data-testid={`sla-${ticket.id}`} style={{
              fontSize: 10, fontWeight: 800, color: slaColor,
              display: "flex", alignItems: "center", gap: 4,
            }}>
              ⏱ {Math.floor(sla.elapsed_minutes)}/{sla.sla_minutes}min
              {sla.status === "overdue" && <span style={{ background: "#dc2626", color: "white", padding: "1px 6px", borderRadius: 6, fontSize: 9, letterSpacing: 0.3 }}>ATRASADO</span>}
              {sla.status === "warning" && <span style={{ background: "#f59e0b", color: "white", padding: "1px 6px", borderRadius: 6, fontSize: 9, letterSpacing: 0.3 }}>ATENÇÃO</span>}
            </div>
          )}
          {ai.score != null && (
            <span
              data-testid={`ai-score-${ticket.id}`}
              style={{
                fontSize: 10, fontWeight: 900, padding: "2px 8px", borderRadius: 999,
                background: aiScoreColor(ai.score), color: "white",
                display: "inline-flex", alignItems: "center", gap: 4,
                marginLeft: "auto",
              }}
            >🤖 {ai.score.toFixed(1)}</span>
          )}
        </div>
      )}

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
          position: "absolute", top: 6, right: selectMode ? 6 : 6,
          fontSize: 9, fontWeight: 900, color: "white",
          background: "linear-gradient(90deg,#10b981,#059669)",
          padding: "2px 7px", borderRadius: 999,
          textTransform: "uppercase", letterSpacing: 0.5,
          boxShadow: "0 0 0 2px rgba(16,185,129,.2)",
          animation: "pulse 1.6s ease-in-out infinite",
          zIndex: 2,
        }}>
          ▶ Em execução
        </div>
      )}
      {ticket.locked && !ticket.in_execution && (
        <span style={{ position: "absolute", top: 8, right: 8, fontSize: 14, zIndex: 2 }}>🔒</span>
      )}
      {ticket.atlaz_external_id && (
        <span data-testid={`atlaz-badge-${ticket.id}`}
          style={{
            position: "absolute", bottom: 6, left: ticket.priority !== "normal" ? 12 : 8,
            fontSize: 9, fontWeight: 800, color: "#1e40af",
            background: "rgba(219,234,254,.95)", border: "1px solid #93c5fd",
            padding: "1px 6px", borderRadius: 999,
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
            onClick={runAiAnalysis} style={btnSm("#0d9488")}>IA {aiBusy ? "..." : ""}</button>
          <button data-testid={`admin-close-${ticket.id}`} disabled={busy}
            onClick={() => { const n = await window.prompt("Notas:"); if (n !== null) onAdminClose(ticket.id, "encerrar", n); }} style={btnSm("#64748b")}>✓ Encerrar</button>
          <button data-testid={`admin-reschedule-${ticket.id}`} disabled={busy}
            onClick={(e) => { e.stopPropagation(); if (onReschedule) onReschedule(ticket); }} style={btnSm("#3b82f6")}>📅 Reagendar</button>
          <button disabled={busy}
            onClick={() => { const n = await window.prompt("Motivo do cancelamento:"); if (n) onAdminClose(ticket.id, "cancelar", n); }} style={btnSm("#dc2626")}>✗ Cancelar</button>
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
          <h2 style={{ margin: 0, fontSize: 18 }}>Avaliação IA do Serviço</h2>
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
        <h3 style={{ margin: 0, fontSize: 16 }}>Histórico de Ações ({logs.length})</h3>
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


// ============================================================================
// ReturnedNotesCard — Notas que retornaram (bolhas esquecidas de dias
// anteriores). Bolhas que ficaram pendente/aberta/aguardando_atendimento e
// não foram reagendadas. Exibe contagem por técnico + lista expansível.
// Estado visual: cinza/desativado para indicar que não fazem mais parte
// do dia de hoje.
// ============================================================================
function ReturnedNotesCard({ onJump }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const r = await api.lousaReturnedNotes(30);
      setData(r);
    } catch (e) {
      console.warn("returned-notes fetch failed:", e?.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 60_000);
    return () => clearInterval(t);
  }, [fetchData]);

  if (loading || !data) return null;
  const total = data.total || 0;
  if (total === 0) return null;

  return (
    <div data-testid="returned-notes-card" style={{
      marginBottom: 14, padding: 14, borderRadius: 12,
      background: "linear-gradient(135deg, #f8fafc, #f1f5f9)",
      border: "1.5px solid #cbd5e1",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                     justifyContent: "space-between", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: "#64748b", display: "grid", placeItems: "center",
            color: "white", fontWeight: 800, fontSize: 14,
          }}>
            {total}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 13, color: "#0f172a",
                           letterSpacing: "-.01em" }}>
              Notas que retornaram
            </div>
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 1 }}>
              Bolhas esquecidas em dias anteriores (não reagendadas) ·
              últimos {data.days_back || 30} dias
            </div>
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          data-testid="returned-notes-toggle"
          style={{
            background: "transparent", color: "#475569",
            fontSize: 12, fontWeight: 700,
            padding: "6px 14px", borderRadius: 8,
            border: "1px solid #cbd5e1", cursor: "pointer",
          }}>
          {expanded ? "Ocultar" : `Ver todas (${total})`}
        </button>
      </div>

      {/* Resumo por técnico (cards horizontais) */}
      <div style={{
        marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap",
        overflowX: "auto",
      }}>
        {(data.by_technician || []).map((tech) => (
          <div key={tech.collaborator_id} style={{
            padding: "8px 12px", background: "white",
            borderRadius: 8, border: "1px solid #e2e8f0",
            minWidth: 130,
          }}>
            <div style={{ fontSize: 10, color: "#64748b",
                           textTransform: "uppercase", letterSpacing: ".05em" }}>
              {tech.name}
            </div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a",
                           marginTop: 2 }}>
              {tech.count}
            </div>
            {tech.oldest_date && (
              <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>
                desde {tech.oldest_date.slice(0, 10)}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Lista expandida (bolhas desativadas) */}
      {expanded && (
        <div data-testid="returned-notes-list" style={{
          marginTop: 14, display: "grid", gap: 6,
          maxHeight: 360, overflowY: "auto",
          padding: 8, background: "white", borderRadius: 8,
          border: "1px solid #e2e8f0",
        }}>
          {(data.items || []).map((t) => (
            <div key={t.id} onClick={() => onJump && onJump(t)}
                 style={{
              padding: "8px 10px", borderRadius: 6,
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              opacity: 0.7, cursor: onJump ? "pointer" : "default",
              display: "flex", justifyContent: "space-between", alignItems: "center",
              gap: 10, fontSize: 12,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontWeight: 600, color: "#475569",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  textDecoration: "line-through", textDecorationThickness: 1,
                  textDecorationColor: "#94a3b8",
                }}>
                  {t.cliente_nome || t.title || t.id}
                </div>
                <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>
                  {t.technician_name} · {t.returned_from_date?.slice(0, 10)}
                  {t.days_overdue ? ` · há ${t.days_overdue} dia(s)` : ""}
                  {t.status ? ` · ${t.status}` : ""}
                </div>
              </div>
              <span style={{
                background: "#fef3c7", color: "#92400e",
                padding: "2px 8px", borderRadius: 999,
                fontSize: 10, fontWeight: 700, whiteSpace: "nowrap",
              }}>
                ESQUECIDA
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}



// ============================================================================
// PingQualityCard — % de bolhas finalizadas com teste de ping feito, por técnico.
// KPI de qualidade: técnico que pula o ping vira métrica vermelha pro gestor.
// ============================================================================
function PingQualityCard() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const r = await api.lousaPingQualityReport(days);
      setData(r);
    } catch (e) {
      console.warn("ping-quality fetch failed:", e?.message);
    } finally { setLoading(false); }
  }, [days]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const t = setInterval(fetchData, 90_000);
    return () => clearInterval(t);
  }, [fetchData]);

  if (loading || !data) return null;
  const total = data.totals?.finalized || 0;
  if (total === 0) return null;

  const rate = data.totals?.rate_pct || 0;
  const accent = rate >= 80 ? "#16a34a" : rate >= 50 ? "#f59e0b" : "#dc2626";

  return (
    <div data-testid="ping-quality-card" style={{
      marginBottom: 14, padding: 14, borderRadius: 12,
      background: "linear-gradient(135deg, #ecfeff, #cffafe)",
      border: "1.5px solid #67e8f9",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                     justifyContent: "space-between", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 48, height: 48, borderRadius: 12, background: accent,
            display: "grid", placeItems: "center", color: "white",
            fontWeight: 800, fontSize: 16,
          }}>
            {rate.toFixed(0)}%
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 13, color: "#0c4a6e",
                           letterSpacing: "-.01em" }}>
              🛰 Qualidade do atendimento — Teste de Ping
            </div>
            <div style={{ fontSize: 11, color: "#0e7490", marginTop: 2 }}>
              {data.totals.with_ping} de {data.totals.finalized} bolhas finalizadas
              tiveram ping nos últimos {data.days_back} dias
            </div>
          </div>
        </div>
        <select value={days}
                 onChange={(e) => setDays(parseInt(e.target.value, 10))}
                 data-testid="ping-quality-days"
                 style={{
                   padding: "8px 12px", borderRadius: 8,
                   background: "white", border: "1px solid #67e8f9",
                   color: "#0c4a6e", fontSize: 12, fontWeight: 700,
                   cursor: "pointer",
                 }}>
          <option value="1">Hoje (1 dia)</option>
          <option value="7">7 dias</option>
          <option value="30">30 dias</option>
        </select>
      </div>

      <div style={{
        marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap",
        overflowX: "auto",
      }}>
        {(data.by_technician || []).map((tech) => {
          const techRate = tech.rate_pct || 0;
          const techAccent = techRate >= 80 ? "#16a34a"
                              : techRate >= 50 ? "#f59e0b" : "#dc2626";
          return (
            <div key={tech.collaborator_id} style={{
              padding: "8px 12px", background: "white",
              borderRadius: 8, border: "1px solid #e2e8f0",
              minWidth: 150,
            }}>
              <div style={{ fontSize: 10, color: "#64748b",
                             textTransform: "uppercase", letterSpacing: ".05em",
                             whiteSpace: "nowrap", overflow: "hidden",
                             textOverflow: "ellipsis" }}>
                {tech.name}
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 4,
                             marginTop: 2 }}>
                <span style={{ fontSize: 18, fontWeight: 800,
                                 color: techAccent }}>
                  {techRate.toFixed(0)}%
                </span>
                <span style={{ fontSize: 10, color: "#64748b" }}>
                  {tech.with_ping}/{tech.finalized}
                </span>
              </div>
              {tech.without_ping > 0 && (
                <div style={{ fontSize: 9, color: "#dc2626", marginTop: 2,
                                fontWeight: 700 }}>
                  ⚠️ {tech.without_ping} sem ping
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}



// ============================================================================
// CoachingConfigCard — alerta WhatsApp quando técnico fecha N bolhas seguidas
// sem teste de ping. Mensagem vai pro WhatsApp da Isabella (gestor configura
// o número que recebe).
// ============================================================================
function CoachingConfigCard() {
  const [cfg, setCfg] = useState({ enabled: false, manager_phone: "", threshold: 3 });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const [expanded, setExpanded] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [c, a] = await Promise.all([
        api.lousaCoachingConfigGet(),
        api.lousaCoachingAlerts(30),
      ]);
      setCfg({
        enabled: !!c.enabled,
        manager_phone: c.manager_phone || "",
        threshold: c.threshold || 3,
      });
      setAlerts(a.items || []);
    } catch (e) {
      console.warn("coaching cfg load:", e?.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.lousaCoachingConfigSave(cfg);
      setCfg({
        enabled: !!r.enabled,
        manager_phone: r.manager_phone || "",
        threshold: r.threshold || 3,
      });
    } catch (e) {
      await window.alert("Falha ao salvar: " + (e?.message || e));
    } finally { setSaving(false); }
  };

  if (loading) return null;

  return (
    <div data-testid="coaching-config-card" style={{
      marginBottom: 14, padding: 14, borderRadius: 12,
      background: "linear-gradient(135deg, #fef3c7, #fde68a)",
      border: "1.5px solid #f59e0b",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ fontWeight: 800, fontSize: 13, color: "#78350f",
                         letterSpacing: "-.01em" }}>
            🎯 Coaching automático — Ping skip
          </div>
          <div style={{ fontSize: 11, color: "#92400e", marginTop: 2 }}>
            Avisa no WhatsApp da Isabella quando alguém fecha {cfg.threshold} bolhas
            seguidas sem teste de ping.
          </div>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8,
                          cursor: "pointer" }}>
          <input type="checkbox" checked={cfg.enabled}
                 data-testid="coaching-enabled"
                 onChange={(e) => setCfg((c) => ({ ...c, enabled: e.target.checked }))} />
          <span style={{ fontSize: 12, fontWeight: 700, color: "#78350f" }}>
            {cfg.enabled ? "Ativo" : "Desligado"}
          </span>
        </label>
      </div>

      <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap",
                      alignItems: "flex-end" }}>
        <label style={{ flex: "1 1 220px", fontSize: 11, color: "#78350f",
                          fontWeight: 700 }}>
          WhatsApp do gestor (com DDI)
          <input type="text" placeholder="+55 21 99817-6526"
                 value={cfg.manager_phone}
                 data-testid="coaching-manager-phone"
                 onChange={(e) => setCfg((c) => ({ ...c, manager_phone: e.target.value }))}
                 style={{ width: "100%", marginTop: 4, padding: "8px 10px",
                            borderRadius: 8, border: "1px solid #f59e0b",
                            fontSize: 13, background: "white" }} />
        </label>
        <label style={{ width: 110, fontSize: 11, color: "#78350f",
                          fontWeight: 700 }}>
          Disparo em
          <select value={cfg.threshold}
                  data-testid="coaching-threshold"
                  onChange={(e) => setCfg((c) => ({ ...c, threshold: parseInt(e.target.value, 10) }))}
                  style={{ width: "100%", marginTop: 4, padding: "8px 10px",
                             borderRadius: 8, border: "1px solid #f59e0b",
                             fontSize: 13, background: "white", fontWeight: 700 }}>
            {[2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>{n} bolhas</option>
            ))}
          </select>
        </label>
        <Button onClick={save} disabled={saving}
                data-testid="coaching-save"
                style={{ height: 38 }}>
          {saving ? "Salvando..." : "💾 Salvar"}
        </Button>
        <Button onClick={() => setExpanded((e) => !e)}
                data-testid="coaching-history-toggle"
                style={{ height: 38, background: "white",
                           color: "#78350f", border: "1px solid #f59e0b" }}>
          {expanded ? "Esconder" : `Histórico (${alerts.length})`}
        </Button>
      </div>

      {expanded && (
        <div style={{ marginTop: 12, background: "white", borderRadius: 8,
                        padding: 10, maxHeight: 240, overflowY: "auto" }}>
          {alerts.length === 0 ? (
            <div style={{ fontSize: 12, color: "#78350f", textAlign: "center" }}>
              Nenhum alerta nos últimos 30 dias 🎉
            </div>
          ) : alerts.map((a) => (
            <div key={a.id} style={{ padding: "6px 0",
                                         borderBottom: "1px solid #fde68a",
                                         fontSize: 11 }}>
              <div style={{ fontWeight: 700, color: "#78350f" }}>
                {a.collaborator_name}
                <span style={{ marginLeft: 6, fontWeight: 500, color: "#92400e" }}>
                  {a.delivery_status === "sent" ? "✓ enviado" : "✗ falhou"}
                </span>
              </div>
              <div style={{ color: "#78350f" }}>
                {a.threshold} bolhas sem ping ·
                {" "}{new Date(a.created_at).toLocaleString("pt-BR")}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// ============================================================================
// ClosureQualityCard — IA correlaciona reclamação x solução do técnico e dá
// uma nota 0-100. Mostra os top motivos e os fechamentos suspeitos.
// ============================================================================
function ClosureQualityCard() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);

  const reload = useCallback(async () => {
    try {
      const r = await api.lousaClosureQualityReport(days);
      setData(r);
    } catch (e) {
      console.warn("closure-quality fetch:", e?.message);
    } finally { setLoading(false); }
  }, [days]);

  useEffect(() => {
    setLoading(true);
    reload();
  }, [reload]);

  const runAnalysis = async () => {
    setAnalyzing(true);
    try {
      const r = await api.lousaClosureQualityAnalyze({ daysBack: days, limit: 25 });
      await reload();
      if (r.processed === 0) {
        await window.alert(r.remaining_pending > 0
          ? `Nada novo processado (${r.remaining_pending} pendentes — tente outro período).`
          : "Todos os fechamentos do período já foram analisados.");
      }
    } catch (e) {
      await window.alert("Falha na análise IA: " + (e?.message || e));
    } finally { setAnalyzing(false); }
  };

  if (loading || !data) return null;
  const total = data.totals?.finalized || 0;
  if (total === 0) return null;

  const avg = data.totals?.avg_score;
  const accent = avg === null || avg === undefined ? "#64748b"
                 : avg >= 75 ? "#16a34a"
                 : avg >= 50 ? "#f59e0b" : "#dc2626";

  return (
    <div data-testid="closure-quality-card" style={{
      marginBottom: 14, padding: 14, borderRadius: 12,
      background: "linear-gradient(135deg, #ede9fe, #ddd6fe)",
      border: "1.5px solid #a78bfa",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 48, height: 48, borderRadius: 12, background: accent,
            display: "grid", placeItems: "center", color: "white",
            fontWeight: 800, fontSize: 16,
          }} data-testid="closure-quality-score">
            {avg !== null && avg !== undefined ? Math.round(avg) : "—"}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 13, color: "#4c1d95",
                            letterSpacing: "-.01em" }}>
              🧠 Qualidade dos fechamentos — IA
            </div>
            <div style={{ fontSize: 11, color: "#5b21b6", marginTop: 2 }}>
              {data.totals.analyzed}/{total} fechamentos analisados ·
              {" "}{data.totals.low_score_count} suspeitos
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={days}
                  data-testid="closure-quality-days"
                  onChange={(e) => setDays(parseInt(e.target.value, 10))}
                  style={{ padding: "8px 12px", borderRadius: 8,
                             background: "white", border: "1px solid #a78bfa",
                             color: "#4c1d95", fontSize: 12, fontWeight: 700,
                             cursor: "pointer" }}>
            <option value="1">Hoje</option>
            <option value="7">7 dias</option>
            <option value="30">30 dias</option>
          </select>
          <Button onClick={runAnalysis} disabled={analyzing}
                  data-testid="closure-quality-analyze"
                  style={{ height: 36 }}>
            {analyzing ? "Analisando..." : `🧪 Analisar (${data.totals.pending})`}
          </Button>
        </div>
      </div>

      <div style={{ marginTop: 12, display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {/* Top motivos */}
        <div style={{ background: "white", borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#4c1d95",
                          marginBottom: 8, textTransform: "uppercase",
                          letterSpacing: ".05em" }}>
            Top motivos de fechamento
          </div>
          {data.top_reasons?.length === 0 && (
            <div style={{ fontSize: 12, color: "#64748b" }}>—</div>
          )}
          {(data.top_reasons || []).map((r) => (
            <div key={r.reason} style={{ display: "flex",
                                              justifyContent: "space-between",
                                              padding: "4px 0",
                                              borderBottom: "1px solid #f1f5f9",
                                              fontSize: 12 }}
                 data-testid="closure-reason-row">
              <span style={{ color: "#4c1d95", flex: 1, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.reason}
              </span>
              <span style={{ color: "#7c3aed", fontWeight: 700, marginLeft: 8 }}>
                {r.count} ({r.pct}%)
              </span>
            </div>
          ))}
        </div>

        {/* Fechamentos suspeitos */}
        <div style={{ background: "white", borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#4c1d95",
                          marginBottom: 8, textTransform: "uppercase",
                          letterSpacing: ".05em" }}>
            🚩 Fechamentos suspeitos (score &lt; 50)
          </div>
          {(!data.low_score_tickets || data.low_score_tickets.length === 0) && (
            <div style={{ fontSize: 12, color: "#64748b" }}>
              Nada suspeito. Clique em "Analisar" se houver pendentes.
            </div>
          )}
          {(data.low_score_tickets || []).map((t) => (
            <div key={t.ticket_id} style={{ padding: "6px 0",
                                                borderBottom: "1px solid #f1f5f9" }}
                 data-testid="closure-low-score-row">
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#4c1d95",
                                 flex: 1, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t.client_name} — {t.title}
                </span>
                <span style={{ background: t.score < 25 ? "#dc2626" : "#f59e0b",
                                 color: "white", padding: "2px 6px",
                                 borderRadius: 6, fontSize: 11, fontWeight: 800 }}>
                  {t.score}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "#7c3aed", marginTop: 2 }}>
                <b>{t.verdict}</b> · {t.reasoning}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}


// ============================================================================
// InsightsPanel — sub-aba "Painel IA". Mostra os 4 cards (Notas que retornaram,
// Qualidade do Ping, Coaching, Qualidade dos fechamentos) todos abertos numa
// grade 2x2 com layout limpo. Header com resumo do que cada card faz.
// ============================================================================
function InsightsPanel({ onJumpTicket }) {
  return (
    <div data-testid="insights-panel">
      {/* Header explicativo */}
      <div style={{
        marginBottom: 16, padding: "16px 20px", borderRadius: 14,
        background: "linear-gradient(135deg, #0f172a, #1e293b)",
        color: "white",
      }}>
        <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-.02em" }}>
          🧠 Painel IA — Qualidade de Atendimento
        </div>
        <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
          Visão consolidada do que sua operação está deixando passar: bolhas
          esquecidas, técnicos pulando ping, e a IA auditando se a solução do
          técnico bate com a reclamação do cliente.
        </div>
      </div>

      {/* Grade 2x2 (em mobile vira 1 coluna) */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(440px, 1fr))",
        gap: 14, alignItems: "start",
      }}>
        <ReturnedNotesCard onJump={onJumpTicket} />
        <PingQualityCard />
        <CoachingConfigCard />
        <ClosureQualityCard />
      </div>
    </div>
  );
}


