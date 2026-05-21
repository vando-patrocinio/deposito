import React, { useEffect, useMemo, useState, useCallback, useRef } from "react";
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

export default function LousaAdminPanel({ systemStatus = { offline: false, drift_blocked: false }, currentUser = null }) {
  const isAuditor = !!currentUser
    && (currentUser.is_super_admin
        || (currentUser.role || "").toLowerCase() === "auditor"
        || (currentUser.role || "").toLowerCase() === "administrador");
  const [autoReschedCfg, setAutoReschedCfg] = useState(null);
  const [showAutoReschedModal, setShowAutoReschedModal] = useState(false);
  useEffect(() => {
    if (!isAuditor) return;
    api.lousaAutoReschedGet().then(setAutoReschedCfg).catch(() => {});
  }, [isAuditor]);
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
  // Focus mode: filtra a Lousa pra mostrar APENAS a grade de UM técnico
  // (visão "estação de trabalho"). Persiste em localStorage por gestor.
  const [focusTechId, setFocusTechId] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem("lousa_focus_tech") || "";
  });
  // Multi-seleção de técnicos visíveis na Lousa (array de IDs).
  // Quando vazio, a Lousa mostra TODOS os técnicos (comportamento padrão).
  // Quando tem 1+ IDs, mostra apenas esses (mesmo padrão visual, sem "focus mode").
  const [visibleTechIds, setVisibleTechIds] = useState(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem("lousa_visible_techs");
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch { return []; }
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (visibleTechIds.length > 0) {
      window.localStorage.setItem("lousa_visible_techs",
                                    JSON.stringify(visibleTechIds));
    } else {
      window.localStorage.removeItem("lousa_visible_techs");
    }
  }, [visibleTechIds]);
  const [techMenuOpen, setTechMenuOpen] = useState(false);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [showPdfPopover, setShowPdfPopover] = useState(false);
  // Visualização dentro do focus mode: "grid" (coluna vertical clássica)
  // ou "timeline" (slots horizontais estilo Google Calendar / Asana).
  const [focusView, setFocusView] = useState(() => {
    if (typeof window === "undefined") return "grid";
    return window.localStorage.getItem("lousa_focus_view") || "grid";
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("lousa_focus_view", focusView);
  }, [focusView]);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (focusTechId) window.localStorage.setItem("lousa_focus_tech", focusTechId);
    else window.localStorage.removeItem("lousa_focus_tech");
  }, [focusTechId]);
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

  async function handleAdminClose(ticketId, action, notes, completionData = null) {
    if (isLocked) { await window.alert("Sistema bloqueado: dispositivo offline ou horário dessincronizado."); return; }
    setBusy(true);
    try {
      const payload = { action, notes: notes || "" };
      if (completionData) payload.completion_data = completionData;
      await api.lousaAdminClose(ticketId, payload);
      await refresh();
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  // Modal de fechamento admin (mesmas regras do técnico)
  const [adminFinalizeTicket, setAdminFinalizeTicket] = useState(null);

  // Callback unificado: "encerrar" abre modal completo (com completion_data),
  // "cancelar" e outros vão direto pro handleAdminClose simples.
  const handleAdminCloseAction = useCallback((ticketOrId, action, notes) => {
    const ticket = typeof ticketOrId === "object" ? ticketOrId : null;
    const id = ticket?.id || ticketOrId;
    if (action === "encerrar" && ticket) {
      setAdminFinalizeTicket(ticket);
      return;
    }
    return handleAdminClose(id, action, notes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
            {focusTechId ? (
              <>
                Visão focada · 1 técnico de {grid.columns.length} · arraste para reordenar slots ·
                <button
                  onClick={() => setFocusTechId("")}
                  data-testid="lousa-clear-focus"
                  style={{
                    marginLeft: 6, padding: "1px 8px", borderRadius: 999,
                    background: "#e0e7ff", color: "#3730a3",
                    border: "1px solid #c7d2fe", fontSize: 11,
                    fontWeight: 700, cursor: "pointer",
                  }}
                >
                  ✕ Mostrar todos
                </button>
              </>
            ) : (
              <>{grid.columns.length} técnico(s) · {totalTickets} serviço(s) ativos — arraste para transferir entre técnicos · duplo-clique abre serviço pendente</>
            )}
            {overdueCount > 0 && (
              <span data-testid="overdue-counter" className="pill pill--danger" style={{ marginLeft: 10, fontWeight: 700 }}>
                {overdueCount} atrasada(s)
              </span>
            )}
          </p>
        </div>
        <div data-testid="lousa-toolbar" style={{
          display: "flex", gap: 6, alignItems: "stretch", flexWrap: "wrap",
          background: "#f8fafc",
          padding: 4, borderRadius: 12,
          border: "1px solid #e2e8f0",
        }}>
          {/* ─── Grupo 1: Sentinela + Data ─── */}
          <ToolbarGroup>
            <ToolbarBtn
              onClick={() => setShowSentinela(true)}
              data-testid="open-sentinela-btn"
              title="Alertas da Sentinela Lousa AI"
              accent={sentinelaCount > 0 ? "danger" : "success"}
            >
              <span style={{ fontSize: 13 }}>🛡</span>
              <span>Sentinela</span>
              {sentinelaCount > 0 && (
                <span data-testid="sentinela-badge" style={{
                  marginLeft: 2, padding: "1px 6px", borderRadius: 999,
                  background: "#dc2626", color: "#fff",
                  fontSize: 10, fontWeight: 800,
                  fontFamily: "ui-monospace, monospace",
                }}>{sentinelaCount}</span>
              )}
            </ToolbarBtn>
            <div style={{ display: "flex", alignItems: "center" }}>
              <DateNavigator
                selectedDate={selectedDate}
                isToday={isToday}
                onPrev={() => shiftDay(-1)}
                onNext={() => shiftDay(1)}
                onToday={goToday}
                onChange={setSelectedDate}
              />
            </div>
          </ToolbarGroup>

          {/* ─── Grupo 2: Filtro técnico + Visualização ─── */}
          <ToolbarGroup>
            <div style={{ position: "relative" }}>
              <ToolbarBtn
                onClick={() => setTechMenuOpen((v) => !v)}
                data-testid="lousa-tech-filter-btn"
                title="Focar em apenas 1 técnico (visão estação de trabalho)"
                accent={focusTechId ? "primary" : "neutral"}
                style={{ minWidth: 168 }}
              >
                {(() => {
                  const focused = focusTechId
                    ? grid.columns.find((c) => c.collaborator.id === focusTechId)?.collaborator
                    : null;
                  if (focused) {
                    return (
                      <>
                        <span style={{
                          width: 18, height: 18, borderRadius: "50%",
                          background: focused.avatar ? `url(${focused.avatar}) center/cover` : "linear-gradient(135deg,#0d9488,#0f766e)",
                          color: "white", fontSize: 9, fontWeight: 800,
                          display: "grid", placeItems: "center", flexShrink: 0,
                        }}>
                          {!focused.avatar && (focused.name?.[0] || "?").toUpperCase()}
                        </span>
                        <span style={{ flex: 1, textAlign: "left", overflow: "hidden",
                                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {focused.name}
                        </span>
                      </>
                    );
                  }
                  if (visibleTechIds.length > 0) {
                    return (
                      <>
                        <span style={{ fontSize: 13 }}>✓</span>
                        <span style={{ flex: 1, textAlign: "left" }}>
                          {visibleTechIds.length} técnico{visibleTechIds.length > 1 ? "s" : ""}
                        </span>
                      </>
                    );
                  }
                  return (
                    <>
                      <span style={{ fontSize: 13 }}>👥</span>
                      <span style={{ flex: 1, textAlign: "left" }}>Todos os técnicos</span>
                    </>
                  );
                })()}
                <span style={{ fontSize: 9, opacity: 0.6 }}>▾</span>
              </ToolbarBtn>
              {techMenuOpen && (
                <TechFilterMenu
                  columns={grid.columns}
                  focusTechId={focusTechId}
                  visibleTechIds={visibleTechIds}
                  onSelectFocus={(id) => { setFocusTechId(id); setTechMenuOpen(false); }}
                  onToggleVisible={(id) => {
                    setFocusTechId(""); // sai do focus mode
                    setVisibleTechIds((arr) =>
                      arr.includes(id) ? arr.filter((x) => x !== id)
                                          : [...arr, id]);
                  }}
                  onClearVisible={() => setVisibleTechIds([])}
                  onSelectAllVisible={() => {
                    setFocusTechId("");
                    setVisibleTechIds(grid.columns.map((c) => c.collaborator.id));
                  }}
                  onClose={() => setTechMenuOpen(false)}
                />
              )}
            </div>
            {focusTechId && (
              <div data-testid="lousa-focus-view-toggle" style={{
                display: "inline-flex", padding: 2, gap: 2,
                background: "white", borderRadius: 8,
                border: "1px solid #e2e8f0",
              }}>
                <button
                  onClick={() => setFocusView("grid")}
                  data-testid="lousa-focus-view-grid"
                  title="Visão em grade vertical (clássica)"
                  style={{
                    padding: "5px 9px", borderRadius: 6, border: "none",
                    background: focusView === "grid" ? "#0f172a" : "transparent",
                    color: focusView === "grid" ? "white" : "#64748b",
                    fontSize: 11.5, fontWeight: 600, cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }}
                >
                  <span style={{ fontSize: 12 }}>▦</span> Grade
                </button>
                <button
                  onClick={() => setFocusView("timeline")}
                  data-testid="lousa-focus-view-timeline"
                  title="Visão timeline horizontal (estilo Google Calendar)"
                  style={{
                    padding: "5px 9px", borderRadius: 6, border: "none",
                    background: focusView === "timeline" ? "#0f172a" : "transparent",
                    color: focusView === "timeline" ? "white" : "#64748b",
                    fontSize: 11.5, fontWeight: 600, cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }}
                >
                  <span style={{ fontSize: 12 }}>⟷</span> Timeline
                </button>
              </div>
            )}
            <ToolbarBtn
              onClick={toggleSelectMode}
              data-testid="lousa-select-mode-toggle"
              title={selectMode ? "Sair do modo seleção" : "Selecionar várias bolhas para ação coletiva"}
              accent={selectMode ? "primary" : "neutral"}
            >
              <span style={{ fontSize: 13 }}>{selectMode ? "✕" : "☐"}</span>
              <span>{selectMode ? "Sair seleção" : "Selecionar"}</span>
            </ToolbarBtn>
            {selectMode && (
              <ToolbarBtn
                onClick={selectAllOverdue}
                data-testid="lousa-select-overdue-btn"
                title="Selecionar todas as bolhas atrasadas (SLA estourado)"
                accent="danger"
                disabled={overdueCount === 0}
              >
                <span style={{ fontSize: 13 }}>⚠</span>
                <span>Atrasadas · {overdueCount}</span>
              </ToolbarBtn>
            )}
            <ToolbarBtn
              onClick={() => setShowHistory(true)}
              data-testid="lousa-history-btn"
              title="Histórico completo de notas (dia/mês/ano/período)"
              accent="neutral"
            >
              <span style={{ fontSize: 13 }}>📚</span>
              <span>Histórico</span>
            </ToolbarBtn>
          </ToolbarGroup>

          {/* ─── Grupo 3: Operação ─── */}
          <ToolbarGroup>
            <ToolbarBtn
              onClick={toggleAlerts}
              data-testid="lousa-sla-alerts-toggle"
              title={alertsOn ? "Alertas sonoros ativos — clique para desligar" : "Ativar alertas sonoros para serviços atrasados"}
              accent={alertsOn ? "success" : "neutral"}
            >
              <span style={{ fontSize: 13 }}>{alertsOn ? "🔔" : "🔕"}</span>
              <span>{alertsOn ? "Alertas" : "Mudo"}</span>
            </ToolbarBtn>
            <ToolbarBtn
              onClick={refresh}
              disabled={refreshing}
              data-testid="lousa-refresh-btn"
              accent={refreshFlash ? "success" : "neutral"}
              style={{ transition: "background-color .25s, color .25s" }}
            >
              <span style={{ fontSize: 13 }}>{refreshing ? "⏳" : refreshFlash ? "✓" : "🔄"}</span>
              <span>{refreshing ? "Atualizando" : refreshFlash ? "Atualizado" : "Atualizar"}</span>
            </ToolbarBtn>
            <ToolbarBtn
              onClick={() => setShowReleaseStuck(true)}
              data-testid="lousa-release-stuck-btn"
              title="EMERGÊNCIA — libera bolha presa do técnico (ação auditada)"
              accent="danger"
            >
              <span style={{ fontSize: 13 }}>🚨</span>
              <span>Liberar bolha</span>
            </ToolbarBtn>
            {isAuditor && (
              <ToolbarBtn
                onClick={() => setShowAutoReschedModal(true)}
                data-testid="lousa-auto-resched-toggle"
                title={autoReschedCfg?.enabled
                  ? "Auto-reagendar OS com sinal degradado: LIGADO (clique para configurar)"
                  : "Auto-reagendar OS com sinal degradado: DESLIGADO (clique para ligar)"}
                accent={autoReschedCfg?.enabled ? "success" : "neutral"}
              >
                <span style={{ fontSize: 13 }}>
                  {autoReschedCfg?.enabled ? "🟢" : "⚪"}
                </span>
                <span>
                  Auto-rede {autoReschedCfg?.enabled ? "ON" : "OFF"}
                </span>
              </ToolbarBtn>
            )}
            <ToolbarBtn
              onClick={() => setShowPdfPopover((v) => !v)}
              data-testid="lousa-pdf-btn"
              title="Gerar PDF de notas finalizadas (hoje/ontem/7 dias/período)"
              accent="neutral"
              style={{ position: "relative" }}
            >
              <span style={{ fontSize: 13 }}>📄</span>
              <span>Relatório PDF</span>
            </ToolbarBtn>
            {showPdfPopover && (
              <ClosedNotesPdfPopover onClose={() => setShowPdfPopover(false)} />
            )}
          </ToolbarGroup>

          {/* ─── Grupo 4: CTA + Overflow ─── */}
          <ToolbarGroup last>
            <button
              onClick={openCreateTicket}
              data-testid="lousa-create-btn"
              title={atlazTenantDomain ? `Abre o painel Atlaz (${atlazTenantDomain}) em nova aba` : "Cria uma nova nota local"}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "8px 14px", borderRadius: 8,
                background: "#0f172a", color: "white",
                border: "1px solid #0f172a",
                fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                transition: "transform .12s, box-shadow .12s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(15,23,42,.18)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
            >
              <span style={{ fontSize: 14, lineHeight: 0 }}>+</span>
              <span>Nova nota{atlazTenantDomain ? " 🔗" : ""}</span>
            </button>
            {user?.role === "auditor" && (
              <div style={{ position: "relative" }}>
                <ToolbarBtn
                  onClick={() => setOverflowOpen((v) => !v)}
                  data-testid="lousa-overflow-btn"
                  title="Mais ações (auditor)"
                  accent="neutral"
                  style={{ padding: "8px 10px" }}
                >
                  <span style={{ fontSize: 16, lineHeight: 0.5, letterSpacing: 1 }}>⋯</span>
                </ToolbarBtn>
                {overflowOpen && (
                  <OverflowMenu onClose={() => setOverflowOpen(false)}>
                    <button
                      onClick={async () => {
                        setOverflowOpen(false);
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
                      style={overflowItemStyle("#dc2626")}
                    >
                      <span style={{ fontSize: 14 }}>🗑</span>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 12.5 }}>Apagar todas as bolhas</div>
                        <div style={{ fontSize: 10.5, opacity: 0.7 }}>Ação irreversível · auditor only</div>
                      </div>
                    </button>
                  </OverflowMenu>
                )}
              </div>
            )}
          </ToolbarGroup>
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
        {(focusTechId
          ? grid.columns.filter((c) => c.collaborator.id === focusTechId)
          : (visibleTechIds.length > 0
              ? grid.columns.filter((c) => visibleTechIds.includes(c.collaborator.id))
              : grid.columns)
        ).map((col) => (
          focusTechId && focusView === "timeline" ? (
            <TechTimeline
              key={col.collaborator.id + tick}
              column={col}
              isDropTarget={dragOverCol === col.collaborator.id}
              blinkOverdue={grid.sla_blink_when_overdue}
              maxPerSlot={grid.grid?.max_per_slot || 2}
              onSlotDrop={handleSlotDrop}
              onDragStart={(tid) => setDraggingId(tid)}
              onDragEnd={() => { setDraggingId(null); setDragOverCol(null); }}
              draggingId={draggingId}
              onAdminClose={handleAdminCloseAction}
              onAdminOpen={handleAdminOpen}
              onEdit={(t) => setEditingTicket(t)}
              onReschedule={(t) => setReschedTicket(t)}
              busy={busy}
              selectMode={selectMode}
              selectedIds={selectedIds}
              onToggleSelect={toggleTicketSelected}
            />
          ) : (
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
            onAdminClose={handleAdminCloseAction}
            onAdminOpen={handleAdminOpen}
            onEdit={(t) => setEditingTicket(t)}
            onReschedule={(t) => setReschedTicket(t)}
            busy={busy}
            selectMode={selectMode}
            selectedIds={selectedIds}
            onToggleSelect={toggleTicketSelected}
            wide={!!focusTechId}
          />
          )
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
      {showAutoReschedModal && (
        <AutoReschedConfigModal
          initial={autoReschedCfg}
          onClose={() => setShowAutoReschedModal(false)}
          onSaved={(cfg) => { setAutoReschedCfg(cfg); setShowAutoReschedModal(false); }}
        />
      )}
      {adminFinalizeTicket && (
        <AdminFinalizeModal
          ticket={adminFinalizeTicket}
          onClose={() => setAdminFinalizeTicket(null)}
          onSubmit={async (cd, notes) => {
            await handleAdminClose(adminFinalizeTicket.id, "encerrar", notes, cd);
            setAdminFinalizeTicket(null);
          }}
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


function TechColumn({ column, isDropTarget, blinkOverdue, onDragOver, onDragLeave, onDrop, onDragStart, onDragEnd, draggingId, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, maxPerSlot, onSlotDrop, selectMode, selectedIds, onToggleSelect, wide }) {
  const c = column.collaborator;
  const state = column.clock_state;
  const slots = column.slots || [];
  const unscheduled = column.unscheduled || [];
  const recentResolved = column.recent_resolved || [];
  const totalTickets = column.tickets?.length || 0;
  const isOnline = state.is_online === true || (state.is_online === undefined && state.has_entrada && !state.ended_day && !state.in_intervalo);
  const [closedDetailTicket, setClosedDetailTicket] = useState(null);

  return (
    <div
      data-testid={`tech-column-${c.id}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        flex: wide ? "1 1 auto" : "0 0 320px",
        maxWidth: wide ? "100%" : 320,
        minWidth: wide ? 480 : undefined,
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
            <div key={t.id}
                  data-testid={`recent-closed-row-${t.id}`}
                  onDoubleClick={() => setClosedDetailTicket(t)}
                  title="Duplo-clique para abrir os detalhes da finalização"
                  style={{ marginBottom: 4, cursor: "pointer",
                            borderRadius: 5, padding: "2px 4px" }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "#eef2f7"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
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

      {closedDetailTicket && (
        <ClosedTicketDetailModal
          ticket={closedDetailTicket}
          onClose={() => setClosedDetailTicket(null)}
        />
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
            <div data-testid={`unscheduled-bubbles-${c.id}`}
                 style={{ display: "flex", gap: 6, alignItems: "stretch", width: "100%" }}>
              {unscheduled.map((t) => (
                <div key={t.id} style={{ flex: "1 1 0", minWidth: 0, display: "flex" }}>
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
          </div>
        )}
      </div>
    </div>
  );
}

function SlotRow({ slot, techId, maxPerSlot, onSlotDrop, draggingId, onDragStart, onDragEnd, blinkOverdue, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, selectMode, selectedIds, onToggleSelect }) {
  const [over, setOver] = useState(false);
  const isFull = slot.full;
  const tickets = slot.tickets || [];
  const isEmpty = tickets.length === 0;
  // A célula da grade se ajusta automaticamente ao conteúdo (min-height).
  // Quando há N bolhas no mesmo slot, elas dividem a largura igualmente
  // (1 = 100%, 2 = 50/50, 3 = 33% cada, etc.) usando flex.
  const SLOT_MIN_HEIGHT = 64;

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
        minHeight: SLOT_MIN_HEIGHT,
        position: "relative",
        transition: "background .2s ease",
      }}
    >
      <div style={{
        fontSize: 10, fontWeight: 800, color: isFull ? "#92400e" : "#475569",
        marginBottom: isEmpty ? 0 : 4, display: "flex", justifyContent: "space-between",
      }}>
        <span>🕐 {slot.slot}</span>
        <span style={{ fontSize: 9 }}>
          {tickets.length}/{maxPerSlot}{isFull && " 🔒 cheio"}
        </span>
      </div>
      {isEmpty && (
        <div style={{ fontSize: 10, color: "#cbd5e1", textAlign: "center", padding: 2, fontStyle: "italic" }}>
          {over ? "↓ Solte aqui ↓" : "vazio"}
        </div>
      )}
      {/* Tickets — distribuídos lado a lado em flex (1 = 100%, 2 = 50/50, 3 = 33% cada) */}
      {tickets.length > 0 && (
        <div data-testid={`slot-bubbles-${techId}-${slot.slot}`}
             style={{ display: "flex", gap: 6, alignItems: "stretch", width: "100%" }}>
          {tickets.map((t, idx) => (
            <div key={t.id} data-testid={`bubble-slot-${idx}-${t.id}`}
                 style={{
                   flex: "1 1 0",      // todas as bolhas dividem espaço igualmente
                   minWidth: 0,        // permite encolher abaixo do conteúdo
                   display: "flex",
                 }}>
              <BubbleCard
                ticket={t}
                slotHour={slot.slot}
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

function BubbleCard({ ticket, slotHour, blinkOverdue, isDragging, onDragStart, onDragEnd, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, selectMode, isSelected, onToggleSelect }) {
  const c = PRIORITY_COLORS[ticket.priority] || PRIORITY_COLORS.normal;
  const st = STATUS_LABEL[ticket.status] || { label: ticket.status, color: "#64748b" };
  const sla = ticket.sla || {};
  const ai = ticket.ai_score || {};
  const slaColor = sla.status === "overdue" ? "#dc2626" : sla.status === "warning" ? "#f59e0b" : "#10b981";
  const isOverdue = sla.status === "overdue";
  const [showActions, setShowActions] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
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
    // Duplo-clique abre o modal de DETALHES (visualização read-only).
    // Pra editar, o admin clica 1x → hover → botão "✎ Editar".
    setShowDetails(true);
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
        borderRadius: 14, padding: "6px 10px 6px 12px",
        marginBottom: 0, position: "relative",
        width: "100%", minWidth: 0, boxSizing: "border-box",
        cursor: selectMode ? (isSelectable ? "pointer" : "not-allowed") : "grab",
        opacity: isDragging ? 0.4 : (selectMode && !isSelectable ? 0.55 : 1),
        // Compact mode: altura máxima quando NÃO hovered; expande no hover
        // para mostrar todo o conteúdo sem cortar.
        maxHeight: showActions ? "none" : 42,
        overflow: showActions ? "visible" : "hidden",
        zIndex: showActions ? 999 : "auto",
        boxShadow: isSelected
          ? "0 0 0 3px rgba(59,130,246,.25), 0 4px 12px rgba(59,130,246,.18)"
          : isDragging ? "none"
          : showActions ? "0 8px 24px rgba(15,23,42,.25)"
          : isOverdue ? "0 4px 14px rgba(220,38,38,.18)"
          : "0 1px 3px rgba(15,23,42,.06), 0 2px 6px rgba(15,23,42,.04)",
        transition: "max-height .25s, box-shadow .2s, border-color .2s, transform .15s",
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
          {/* Horário da grade (slotHour) — refere-se à célula onde a bolha
              está, não ao scheduled_time original. Se houver discrepância
              (ticket reagendado p/ outro horário), mostra ambos. */}
          {slotHour && (
            <span style={{
              fontSize: 10, fontWeight: 800, color: "#0f172a",
              background: "#fef3c7", padding: "2px 7px", borderRadius: 999,
              border: "1px solid #fcd34d",
            }} title={ticket.scheduled_time
              ? `Slot ${slotHour} · Agendado p/ ${ticket.scheduled_time.substr(11,5)}`
              : `Slot ${slotHour}`}>
              🕐 {slotHour}
            </span>
          )}
          {!slotHour && ticket.scheduled_time && (
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
          <button data-testid={`admin-details-${ticket.id}`}
            onClick={() => setShowDetails(true)}
            style={btnSm("#8b5cf6")}>👁 Detalhes</button>
          <button data-testid={`ai-evaluate-${ticket.id}`} disabled={aiBusy}
            onClick={runAiAnalysis} style={btnSm("#0d9488")}>IA {aiBusy ? "..." : ""}</button>
          <button data-testid={`admin-close-${ticket.id}`} disabled={busy}
            onClick={() => onAdminClose(ticket, "encerrar")}
            style={btnSm("#64748b")}>✓ Encerrar</button>
          <button data-testid={`admin-reschedule-${ticket.id}`} disabled={busy}
            onClick={(e) => { e.stopPropagation(); if (onReschedule) onReschedule(ticket); }} style={btnSm("#3b82f6")}>📅 Reagendar</button>
          <button disabled={busy}
            onClick={async () => { const n = await window.prompt("Motivo do cancelamento:"); if (n) onAdminClose(ticket.id, "cancelar", n); }} style={btnSm("#dc2626")}>✗ Cancelar</button>
        </div>
      )}
      {aiOpen && aiDetail && (
        <AiDetailModal detail={aiDetail} onClose={() => setAiOpen(false)} />
      )}
      {showDetails && (
        <ClosedTicketDetailModal
          ticket={ticket}
          onClose={() => setShowDetails(false)}
        />
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




// ============================================================
// Toolbar primitives — usados pelo header compacto da Lousa
// ============================================================

function ToolbarGroup({ children, last }) {
  return (
    <div style={{
      display: "inline-flex", gap: 3, alignItems: "stretch",
      padding: "2px 6px 2px 0",
      borderRight: last ? "none" : "1px solid #e2e8f0",
      marginRight: last ? 0 : 3,
    }}>
      {children}
    </div>
  );
}

const _accentMap = {
  neutral: { bg: "transparent", color: "#475569", hover: "#e2e8f0", border: "transparent" },
  primary: { bg: "#0f172a", color: "white", hover: "#1e293b", border: "#0f172a" },
  success: { bg: "#ecfdf5", color: "#047857", hover: "#d1fae5", border: "#a7f3d0" },
  danger:  { bg: "#fef2f2", color: "#b91c1c", hover: "#fee2e2", border: "#fecaca" },
};

function ToolbarBtn({ children, accent = "neutral", disabled, style, ...rest }) {
  const a = _accentMap[accent] || _accentMap.neutral;
  return (
    <button
      {...rest}
      disabled={disabled}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "8px 12px", borderRadius: 8,
        background: a.bg, color: a.color,
        border: `1px solid ${a.border}`,
        fontSize: 12.5, fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: "background-color .12s, color .12s",
        whiteSpace: "nowrap",
        lineHeight: 1.1,
        ...(style || {}),
      }}
      onMouseEnter={(e) => { if (!disabled) e.currentTarget.style.background = a.hover; }}
      onMouseLeave={(e) => { if (!disabled) e.currentTarget.style.background = a.bg; }}
    >
      {children}
    </button>
  );
}

function TechFilterMenu({ columns, focusTechId, visibleTechIds = [],
                            onSelectFocus, onToggleVisible,
                            onClearVisible, onSelectAllVisible, onClose }) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return columns;
    return columns.filter((c) => (c.collaborator.name || "").toLowerCase().includes(q));
  }, [columns, search]);

  // Fecha ao clicar fora
  useEffect(() => {
    const onDoc = (e) => {
      if (!e.target.closest?.("[data-tech-menu]")) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);

  const allTechIds = columns.map((c) => c.collaborator.id);
  const allSelected = visibleTechIds.length > 0
    && visibleTechIds.length === allTechIds.length
    && allTechIds.every((id) => visibleTechIds.includes(id));

  return (
    <div data-tech-menu data-testid="lousa-tech-filter-menu" style={{
      position: "absolute", top: "calc(100% + 6px)", left: 0,
      width: 320, maxHeight: 440, overflowY: "auto",
      background: "white",
      border: "1px solid #e2e8f0",
      borderRadius: 10,
      boxShadow: "0 12px 32px rgba(15,23,42,.16)",
      zIndex: 1500,
      padding: 6,
    }}>
      <div style={{ padding: "6px 8px" }}>
        <input
          autoFocus
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar técnico…"
          data-testid="lousa-tech-filter-search"
          style={{
            width: "100%", padding: "6px 10px",
            border: "1px solid #e2e8f0", borderRadius: 7,
            fontSize: 12, outline: "none",
          }}
        />
      </div>

      {/* Ações em massa */}
      <div style={{ display: "flex", gap: 6, padding: "0 4px 6px" }}>
        <button
          data-testid="lousa-tech-filter-select-all"
          onClick={() => allSelected ? onClearVisible() : onSelectAllVisible()}
          style={{
            flex: 1, padding: "6px 8px", border: "1px solid #cbd5e1",
            borderRadius: 6, background: "#f8fafc", color: "#0f172a",
            fontSize: 11, fontWeight: 700, cursor: "pointer",
          }}>
          {allSelected ? "☐ Desmarcar todos" : "☑ Marcar todos"}
        </button>
        {visibleTechIds.length > 0 && (
          <button
            data-testid="lousa-tech-filter-clear"
            onClick={onClearVisible}
            style={{
              padding: "6px 10px", border: "1px solid #fecaca",
              borderRadius: 6, background: "#fef2f2", color: "#991b1b",
              fontSize: 11, fontWeight: 700, cursor: "pointer",
            }}>
            ✕ Limpar
          </button>
        )}
      </div>

      {/* "Todos" — desliga filtros (foco e multi) */}
      <button
        onClick={() => { onSelectFocus(""); onClearVisible(); }}
        data-testid="lousa-tech-filter-all"
        style={{
          display: "flex", alignItems: "center", gap: 9, width: "100%",
          padding: "8px 10px", border: "none",
          background: (!focusTechId && visibleTechIds.length === 0) ? "#f1f5f9" : "transparent",
          borderRadius: 7, cursor: "pointer", textAlign: "left",
          color: "#0f172a", fontSize: 12.5, fontWeight: 700,
          marginBottom: 4,
        }}
      >
        <span style={{
          width: 24, height: 24, borderRadius: "50%",
          background: "#e2e8f0", color: "#475569",
          display: "grid", placeItems: "center", fontSize: 11, flexShrink: 0,
        }}>👥</span>
        <span style={{ flex: 1 }}>Todos os técnicos</span>
        <span style={{ fontSize: 10, color: "#94a3b8", fontWeight: 600 }}>
          {columns.length}
        </span>
        {(!focusTechId && visibleTechIds.length === 0)
          && <span style={{ color: "#22c55e", fontSize: 13 }}>✓</span>}
      </button>

      <div style={{ height: 1, background: "#f1f5f9", margin: "2px 4px 6px" }} />

      <div style={{ fontSize: 9, color: "#94a3b8", fontWeight: 700,
                      textTransform: "uppercase", letterSpacing: 0.5,
                      padding: "4px 10px 2px" }}>
        Marque ✓ para escolher quem aparece — clique no nome para focar
      </div>

      {filtered.length === 0 && (
        <div style={{ padding: "16px 10px", textAlign: "center",
                        color: "#94a3b8", fontSize: 12 }}>
          Nenhum técnico bate com "{search}"
        </div>
      )}
      {filtered.map((col) => {
        const c = col.collaborator;
        const isFocused = focusTechId === c.id;
        const isChecked = visibleTechIds.includes(c.id);
        const total = col.tickets?.length || 0;
        const overdue = (col.tickets || []).filter((t) => t.sla?.status === "overdue").length;
        return (
          <div
            key={c.id}
            data-testid={`lousa-tech-filter-row-${c.id}`}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "6px 8px",
              background: isFocused ? "#e0f2fe" : isChecked ? "#f0fdf4" : "transparent",
              borderRadius: 7, marginBottom: 2,
            }}
          >
            {/* Checkbox (multi-seleção) */}
            <button
              type="button"
              data-testid={`lousa-tech-filter-check-${c.id}`}
              onClick={(e) => { e.stopPropagation(); onToggleVisible(c.id); }}
              title={isChecked ? "Remover da Lousa" : "Adicionar à Lousa"}
              style={{
                width: 20, height: 20, borderRadius: 5,
                border: `1.5px solid ${isChecked ? "#16a34a" : "#cbd5e1"}`,
                background: isChecked ? "#16a34a" : "#fff",
                color: "#fff", display: "grid", placeItems: "center",
                cursor: "pointer", flexShrink: 0, padding: 0,
                fontSize: 12, fontWeight: 800,
              }}
            >
              {isChecked && "✓"}
            </button>

            {/* Nome + ações */}
            <button
              onClick={() => onSelectFocus(c.id)}
              data-testid={`lousa-tech-filter-${c.id}`}
              style={{
                display: "flex", alignItems: "center", gap: 9, flex: 1,
                padding: "4px 4px", border: "none",
                background: "transparent",
                borderRadius: 5, cursor: "pointer", textAlign: "left",
                color: "#0f172a", fontSize: 12.5, fontWeight: 500,
                minWidth: 0,
              }}
            >
              <span style={{
                width: 24, height: 24, borderRadius: "50%",
                background: c.avatar ? `url(${c.avatar}) center/cover` : "linear-gradient(135deg,#0d9488,#0f766e)",
                color: "white", fontSize: 10, fontWeight: 700,
                display: "grid", placeItems: "center", flexShrink: 0,
              }}>
                {!c.avatar && (c.name?.[0] || "?").toUpperCase()}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.name}
                </div>
                <div style={{ fontSize: 10.5, color: "#64748b", marginTop: 1 }}>
                  {total} ativo{total === 1 ? "" : "s"}
                  {overdue > 0 && (
                    <span style={{ marginLeft: 5, color: "#dc2626", fontWeight: 700 }}>
                      · {overdue} atrasada{overdue === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
              </div>
              {isFocused && <span style={{ color: "#0284c7", fontSize: 11,
                                              fontWeight: 700 }}>FOCO</span>}
            </button>
          </div>
        );
      })}
    </div>
  );
}

function ClosedTicketDetailModal({ ticket, onClose }) {
  const [full, setFull] = useState(ticket);
  const [loading, setLoading] = useState(false);

  // Recarrega o ticket completo (lousa público pode ter completion_data)
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!ticket?.id) return;
      try {
        setLoading(true);
        const r = await api._client.get(`/lousa/tickets/${ticket.id}`);
        if (alive && r.data) setFull({ ...ticket, ...r.data });
      } catch { /* ignore — usa ticket inicial */ }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [ticket]);

  const cd = full?.completion_data || {};
  const cs = full?.client_snapshot || {};
  const fmt = (iso) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("pt-BR",
        { dateStyle: "short", timeStyle: "short" });
    } catch { return iso; }
  };

  const fotos = (cd.fotos || []).filter(Boolean);
  const fotosObjs = fotos.map((f) => {
    if (typeof f === "string") return { dataUrl: f, kind: "geral" };
    return { dataUrl: f.dataUrl || f.data_url, kind: f.kind || "geral" };
  }).filter((f) => f.dataUrl);

  return (
    <div onClick={onClose}
          data-testid="closed-ticket-detail-modal"
          style={{ position: "fixed", inset: 0, zIndex: 9999,
                    background: "rgba(15,23,42,0.7)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "#fff", borderRadius: 12,
                      width: "min(95vw, 720px)", maxHeight: "92vh",
                      display: "flex", flexDirection: "column",
                      overflow: "hidden",
                      boxShadow: "0 20px 60px rgba(0,0,0,0.35)" }}>
        {/* Header */}
        <div style={{ padding: 16, borderBottom: "1px solid #e2e8f0",
                        display: "flex", justifyContent: "space-between",
                        alignItems: "flex-start", gap: 12 }}>
          <div>
            {(() => {
              const isClosed = ["finalizada", "encerrada"].includes(full?.status);
              return (
                <>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b",
                                  textTransform: "uppercase", letterSpacing: 0.5 }}>
                    {isClosed ? "✓ Nota finalizada" : "🟡 Nota em andamento"} ·{" "}
                    {TYPE_LABELS[full.type] || full.type}
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a",
                                  marginTop: 2 }}>
                    {cs.name || "—"}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 4,
                                  lineHeight: 1.4 }}>
                    {isClosed
                      ? <>Fechada em <strong>{fmt(full.closed_at || full.finalized_at)}</strong></>
                      : <>Status: <strong>{full.status}</strong> · Aberta em <strong>{fmt(full.created_at)}</strong></>}
                    {full.outcome && <> · Resultado: <strong>{full.outcome}</strong></>}
                    {full.scheduled_date && (
                      <> · Agendada: <strong>{full.scheduled_date}
                        {full.scheduled_time ? ` ${full.scheduled_time}` : ""}</strong></>
                    )}
                    {full.admin_action === "encerrar" && (
                      <span style={{ marginLeft: 6, padding: "2px 7px",
                                      background: "#fef3c7", color: "#92400e",
                                      borderRadius: 999, fontSize: 9, fontWeight: 800 }}>
                        🛡 Fechado pelo gestor
                      </span>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
          <button onClick={onClose}
                  data-testid="closed-detail-close"
                  style={{ background: "transparent", border: 0, fontSize: 22,
                            cursor: "pointer", color: "#64748b" }}>×</button>
        </div>

        {/* Body */}
        <div style={{ padding: 16, overflowY: "auto", flex: 1, fontSize: 13,
                        color: "#0f172a" }}>
          {loading && (
            <div style={{ color: "#94a3b8", fontSize: 12 }}>Carregando…</div>
          )}

          {/* Endereço */}
          {cs.address && (
            <Section label="📍 Endereço">{cs.address}</Section>
          )}
          {cs.phone && (
            <Section label="📞 Telefone">
              <a href={`tel:${cs.phone}`} style={{ color: "#0891b2",
                          textDecoration: "none", fontWeight: 700 }}>
                {cs.phone}
              </a>
            </Section>
          )}
          {(cs.relato || full.notes) && (
            <Section label="📋 Relato / Notas">
              <div style={{ whiteSpace: "pre-wrap" }}>
                {cs.relato || full.notes}
              </div>
            </Section>
          )}

          {/* Sinal */}
          {cd.sinal != null && (
            <Section label="📡 Sinal medido">
              <strong>{Number(cd.sinal).toFixed(1)} dBm</strong>
            </Section>
          )}
          {cd.ont && <Section label="🔌 ONT">{cd.ont}</Section>}

          {/* CTO + porta + splitter + VLAN */}
          {(cd.cto_name || cd.cto_port_number) && (
            <Section label="🗺 Vínculo na Rede IA">
              {cd.cto_name}
              {cd.cto_port_number && ` · Porta ${cd.cto_port_number}`}
              {cd.cto_splitter && ` · Splitter ${cd.cto_splitter}`}
              {cd.cto_vlan && ` · VLAN ${cd.cto_vlan}`}
              {cd.cto_network_type && ` · Rede ${cd.cto_network_type}`}
            </Section>
          )}

          {/* Insumos */}
          {(cd.drop || cd.backbone || cd.esticador || cd.conectores) && (
            <Section label="🧰 Insumos utilizados">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {cd.drop && <li>Drop: <strong>{cd.drop}m</strong></li>}
                {cd.backbone && <li>Backbone: <strong>{cd.backbone}m</strong></li>}
                {cd.esticador && <li>Esticador: <strong>{cd.esticador}</strong></li>}
                {cd.conectores && <li>Conectores: <strong>{cd.conectores}</strong></li>}
              </ul>
            </Section>
          )}

          {/* Ping */}
          {cd.ping_summary && (
            <Section label="📶 Teste de Ping">
              <pre style={{ background: "#f8fafc",
                              padding: 10, borderRadius: 6, fontSize: 11,
                              whiteSpace: "pre-wrap" }}>{cd.ping_summary}</pre>
            </Section>
          )}

          {/* Observações */}
          {cd.observacoes && (
            <Section label="📝 Observações do técnico">
              <div style={{ whiteSpace: "pre-wrap" }}>{cd.observacoes}</div>
            </Section>
          )}

          {/* Fotos */}
          {fotosObjs.length > 0 && (
            <Section label={`📷 Fotos (${fotosObjs.length})`}>
              <div style={{ display: "grid",
                              gridTemplateColumns:
                                "repeat(auto-fill, minmax(120px, 1fr))",
                              gap: 8 }}>
                {fotosObjs.map((f, i) => (
                  <a key={i} href={f.dataUrl} target="_blank"
                      rel="noopener noreferrer">
                    <img src={f.dataUrl} alt={f.kind || ""}
                          style={{ width: "100%", aspectRatio: "1/1",
                                    objectFit: "cover", borderRadius: 8,
                                    border: "1px solid #e2e8f0",
                                    cursor: "zoom-in" }} />
                  </a>
                ))}
              </div>
            </Section>
          )}

          {/* fallback se nada estiver preenchido */}
          {!loading && !cd.sinal && !cd.ont && !cd.cto_name && !cd.drop
            && !cd.observacoes && fotosObjs.length === 0
            && !cs.relato && !full.notes && !cs.phone && !cs.address && (
            <div style={{ padding: 20, textAlign: "center",
                            color: "#94a3b8", fontSize: 12 }}>
              Nenhum dado registrado ainda.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ label, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b",
                      textTransform: "uppercase", letterSpacing: 0.5,
                      marginBottom: 4 }}>{label}</div>
      <div>{children}</div>
    </div>
  );
}

function ClosedNotesPdfPopover({ onClose }) {
  const [period, setPeriod] = useState("today");
  const [mode, setMode] = useState("closed"); // "closed" | "open"
  const [start, setStart] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  });
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [previewUrl, setPreviewUrl] = useState(null);

  useEffect(() => {
    const onDoc = (e) => {
      if (previewUrl) return;
      if (!e.target.closest?.("[data-pdf-pop]")) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose, previewUrl]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const generate = async () => {
    setErr(""); setBusy(true);
    try {
      const params = new URLSearchParams({ period, mode });
      if (period === "custom") {
        params.set("start", start);
        params.set("end", end);
      }
      const r = await api._client.get(
        `/lousa/tickets/closed/pdf?${params.toString()}`,
        { responseType: "blob" },
      );
      const blob = new Blob([r.data], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      setPreviewUrl(url);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao gerar PDF");
    } finally { setBusy(false); }
  };

  const downloadFromPreview = () => {
    if (!previewUrl) return;
    const a = document.createElement("a");
    a.href = previewUrl;
    a.download = `${mode === "open" ? "bolhas_abertas" : "fechamento_notas"}_${period}_${new Date()
        .toISOString().slice(0, 10)}.pdf`;
    document.body.appendChild(a);
    a.click(); a.remove();
  };

  const openInNewTab = () => {
    if (!previewUrl) return;
    window.open(previewUrl, "_blank", "noopener,noreferrer");
  };

  // ===== Modal de preview com iframe =====
  if (previewUrl) {
    return (
      <div data-testid="lousa-pdf-preview-modal"
            style={{
              position: "fixed", inset: 0, zIndex: 9999,
              background: "rgba(15,23,42,0.7)",
              display: "flex", alignItems: "center", justifyContent: "center",
              padding: 20,
            }}>
        <div style={{
          background: "#fff", borderRadius: 12,
          width: "min(95vw, 1100px)", height: "min(92vh, 800px)",
          display: "flex", flexDirection: "column", overflow: "hidden",
          boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
        }}>
          <div style={{ display: "flex", alignItems: "center",
                          justifyContent: "space-between", padding: 14,
                          borderBottom: "1px solid #e2e8f0" }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
                {mode === "open"
                  ? "🟡 Bolhas Abertas — Pré-visualização"
                  : "📄 Notas Finalizadas — Pré-visualização"}
              </div>
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                {mode === "open" ? "Todas as OS pendentes/em execução" : (
                  "Período: " + {
                    today: "Hoje", yesterday: "Ontem", week: "Últimos 7 dias",
                    custom: `${start} → ${end}`,
                  }[period]
                )}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button data-testid="lousa-pdf-preview-open-tab"
                      onClick={openInNewTab}
                      title="Abrir em nova aba (alternativa se a pré-visualização ficar branca)"
                      style={{ padding: "8px 14px", borderRadius: 8,
                                background: "#fff", border: "1px solid #cbd5e1",
                                color: "#0f172a", fontSize: 12, fontWeight: 700,
                                cursor: "pointer" }}>
                ↗ Abrir em nova aba
              </button>
              <button data-testid="lousa-pdf-preview-download"
                      onClick={downloadFromPreview}
                      style={{ padding: "8px 14px", borderRadius: 8,
                                background: "linear-gradient(135deg,#0f766e,#0891b2)",
                                color: "#fff", border: 0, fontSize: 12,
                                fontWeight: 700, cursor: "pointer",
                                display: "inline-flex", alignItems: "center",
                                gap: 6 }}>
                ⬇ Baixar PDF
              </button>
              <button data-testid="lousa-pdf-preview-close"
                      onClick={() => { setPreviewUrl(null); onClose(); }}
                      style={{ padding: "8px 14px", borderRadius: 8,
                                background: "#fff", border: "1px solid #cbd5e1",
                                color: "#475569", fontSize: 12, fontWeight: 700,
                                cursor: "pointer" }}>
                ✕ Fechar
              </button>
            </div>
          </div>
          <object
            data-testid="lousa-pdf-preview-object"
            data={previewUrl}
            type="application/pdf"
            style={{ flex: 1, width: "100%", border: 0 }}
          >
            <div style={{ padding: 40, textAlign: "center" }}>
              <p style={{ fontSize: 14, color: "#475569", marginBottom: 12 }}>
                Seu navegador bloqueou a pré-visualização inline.
              </p>
              <button onClick={openInNewTab}
                      style={{ padding: "10px 18px", borderRadius: 8,
                                background: "#0891b2", color: "#fff",
                                border: 0, fontWeight: 700, cursor: "pointer" }}>
                ↗ Abrir PDF em nova aba
              </button>
            </div>
          </object>
        </div>
      </div>
    );
  }

  // ===== Popover de configuração =====
  return (
    <div data-pdf-pop data-testid="lousa-pdf-popover"
          style={{
            position: "absolute", top: "calc(100% + 6px)", right: 0,
            width: 320, background: "white",
            border: "1px solid #e2e8f0", borderRadius: 10,
            boxShadow: "0 12px 32px rgba(15,23,42,.16)",
            zIndex: 1500, padding: 14,
          }}>
      <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a",
                      marginBottom: 8 }}>
        📄 Relatório PDF
      </div>
      {/* Seletor Modo: Finalizadas vs Abertas */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 6, marginBottom: 10 }}>
        <button data-testid="lousa-pdf-mode-closed"
                onClick={() => setMode("closed")}
                style={{ padding: "10px 8px", borderRadius: 8,
                          border: `1.5px solid ${mode === "closed" ? "#0f766e" : "#e2e8f0"}`,
                          background: mode === "closed" ? "#ecfdf5" : "#fff",
                          color: mode === "closed" ? "#065f46" : "#0f172a",
                          fontSize: 12, fontWeight: 700, cursor: "pointer",
                          textAlign: "center" }}>
          ✓ Notas FINALIZADAS
        </button>
        <button data-testid="lousa-pdf-mode-open"
                onClick={() => setMode("open")}
                style={{ padding: "10px 8px", borderRadius: 8,
                          border: `1.5px solid ${mode === "open" ? "#ea580c" : "#e2e8f0"}`,
                          background: mode === "open" ? "#fff7ed" : "#fff",
                          color: mode === "open" ? "#9a3412" : "#0f172a",
                          fontSize: 12, fontWeight: 700, cursor: "pointer",
                          textAlign: "center" }}>
          🟡 Bolhas ABERTAS
        </button>
      </div>
      {mode === "open" && (
        <div style={{ fontSize: 10, color: "#9a3412",
                        background: "#fff7ed",
                        border: "1px solid #fed7aa",
                        borderRadius: 6, padding: 8, marginBottom: 8,
                        lineHeight: 1.4 }}>
          Mostra OS pendentes/em execução agrupadas por técnico (ignora o
          período).
        </div>
      )}
      {mode === "closed" && (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 6, marginBottom: 8 }}>
        {[
          { id: "today", label: "Hoje" },
          { id: "yesterday", label: "Ontem" },
          { id: "week", label: "7 dias" },
          { id: "custom", label: "Período…" },
        ].map((p) => (
          <button key={p.id}
                  data-testid={`lousa-pdf-period-${p.id}`}
                  onClick={() => setPeriod(p.id)}
                  style={{
                    padding: "8px 10px", borderRadius: 8,
                    border: `1.5px solid ${period === p.id ? "#0f172a" : "#e2e8f0"}`,
                    background: period === p.id ? "#0f172a" : "#fff",
                    color: period === p.id ? "#fff" : "#0f172a",
                    fontSize: 12, fontWeight: 700, cursor: "pointer",
                  }}>
            {p.label}
          </button>
        ))}
      </div>
      )}
      {period === "custom" && mode === "closed" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 6, marginBottom: 8 }}>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)}
                  data-testid="lousa-pdf-start"
                  style={{ padding: "6px 8px", border: "1px solid #e2e8f0",
                            borderRadius: 7, fontSize: 12 }} />
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)}
                  data-testid="lousa-pdf-end"
                  style={{ padding: "6px 8px", border: "1px solid #e2e8f0",
                            borderRadius: 7, fontSize: 12 }} />
        </div>
      )}
      {err && (
        <div data-testid="lousa-pdf-err"
              style={{ marginBottom: 8, padding: 8, borderRadius: 6,
                        background: "#fef2f2", color: "#991b1b", fontSize: 11 }}>
          ⚠ {err}
        </div>
      )}
      <button data-testid="lousa-pdf-generate"
              onClick={generate} disabled={busy}
              style={{ width: "100%", padding: "10px 12px", borderRadius: 8,
                        background: busy ? "#94a3b8"
                            : "linear-gradient(135deg,#0f766e,#0891b2)",
                        color: "#fff", border: 0, fontSize: 13, fontWeight: 700,
                        cursor: busy ? "wait" : "pointer" }}>
        {busy ? "Gerando…" : (mode === "open"
            ? "👁 Visualizar Bolhas Abertas"
            : "👁 Visualizar Finalizadas")}
      </button>
    </div>
  );
}


function OverflowMenu({ children, onClose }) {
  useEffect(() => {
    const onDoc = (e) => {
      if (!e.target.closest?.("[data-overflow-menu]")) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);
  return (
    <div data-overflow-menu data-testid="lousa-overflow-menu" style={{
      position: "absolute", top: "calc(100% + 6px)", right: 0,
      width: 240,
      background: "white",
      border: "1px solid #e2e8f0",
      borderRadius: 10,
      boxShadow: "0 12px 32px rgba(15,23,42,.16)",
      zIndex: 1500,
      padding: 4,
    }}>
      {children}
    </div>
  );
}

function overflowItemStyle(color) {
  return {
    display: "flex", alignItems: "center", gap: 10,
    padding: "9px 10px", width: "100%",
    border: "none", background: "transparent",
    borderRadius: 7, cursor: "pointer", textAlign: "left",
    color: color || "#0f172a",
  };
}


// ============================================================
// TechTimeline — visão horizontal estilo Google Calendar
// Exibida quando o gestor entra no "focus mode" (1 técnico) e
// escolhe a aba Timeline. Cada slot vira coluna no eixo X.
// ============================================================

function TechTimeline({ column, blinkOverdue, maxPerSlot, onSlotDrop, draggingId,
  onDragStart, onDragEnd, onAdminClose, onAdminOpen, onEdit, onReschedule,
  busy, selectMode, selectedIds, onToggleSelect }) {
  const c = column.collaborator;
  const state = column.clock_state;
  const slots = column.slots || [];
  const unscheduled = column.unscheduled || [];
  const recentResolved = column.recent_resolved || [];
  const totalTickets = column.tickets?.length || 0;
  const isOnline = state.is_online === true || (state.is_online === undefined && state.has_entrada && !state.ended_day && !state.in_intervalo);
  const [closedDetailTicket, setClosedDetailTicket] = useState(null);

  // Hora atual pra desenhar a linha "agora" no timeline
  const now = new Date();
  const nowLabel = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;

  return (
    <div data-testid={`tech-timeline-${c.id}`} style={{
      flex: "1 1 auto", minWidth: 800,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderRadius: 12, padding: 14,
      boxShadow: "var(--shadow-xs)",
    }}>
      {/* Header — mesma identidade do TechColumn */}
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                       paddingBottom: 12, borderBottom: "1px solid var(--border-default)" }}>
        <div style={{
          width: 44, height: 44, borderRadius: "50%",
          background: c.avatar ? `url(${c.avatar}) center/cover` : "linear-gradient(135deg,#0d9488,#0f766e)",
          display: "grid", placeItems: "center", color: "white", fontWeight: 700, fontSize: 16,
          border: `2px solid ${isOnline ? "#16a34a" : "#d97706"}`,
          position: "relative", flexShrink: 0,
        }}>
          {!c.avatar && (c.name?.[0] || "?").toUpperCase()}
          <span style={{
            position: "absolute", bottom: -2, right: -2,
            width: 14, height: 14, borderRadius: "50%",
            background: isOnline ? "#10b981" : "#f59e0b",
            border: "2px solid white",
          }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
            {c.name}
          </div>
          <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 2 }}>
            Timeline · {totalTickets} serviço(s) · {c.praca || "—"}
            {state.records?.length > 0 && (
              <span style={{ marginLeft: 8 }}>
                {state.records.map((r, i) => (
                  <span key={i} style={{
                    marginLeft: 4, padding: "1px 6px", borderRadius: 6, fontWeight: 700,
                    fontSize: 10,
                    background: r.type === "Entrada" ? "#dcfce7" : r.type === "Saída" ? "#fee2e2" : "#fef3c7",
                    color: r.type === "Entrada" ? "#166534" : r.type === "Saída" ? "#7f1d1d" : "#78350f",
                  }}>
                    {r.type === "Entrada" ? "🚪" : r.type === "Início intervalo" ? "🍽️" : r.type === "Fim intervalo" ? "🔄" : "🏁"} {r.time}
                  </span>
                ))}
              </span>
            )}
          </div>
        </div>
        <OptimizeRouteButton collaboratorId={c.id} />
      </div>

      {/* Faixa horizontal de slots */}
      <div style={{ marginTop: 12, overflowX: "auto", paddingBottom: 6 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "stretch", minHeight: 220 }}>
          {slots.map((s) => (
            <TimelineSlot
              key={s.slot}
              slot={s}
              isCurrentHour={nowLabel.slice(0, 2) === s.slot.slice(0, 2)}
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

          {/* Coluna "Sem horário" sticky no fim — drop target especial */}
          {unscheduled.length > 0 && (
            <div data-testid={`timeline-unscheduled-${c.id}`} style={{
              flex: "0 0 200px",
              background: "#fef3c7",
              border: "1.5px dashed #f59e0b",
              borderRadius: 10, padding: 8,
              alignSelf: "stretch",
            }}>
              <div style={{ fontSize: 10.5, fontWeight: 800, color: "#92400e",
                              marginBottom: 6, textAlign: "center",
                              textTransform: "uppercase", letterSpacing: ".05em" }}>
                📋 Sem horário ({unscheduled.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
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
            </div>
          )}
        </div>
      </div>

      {/* Encerrados nas últimas 24h — rodapé compacto */}
      {recentResolved.length > 0 && (
        <div data-testid={`timeline-recent-${c.id}`} style={{
          marginTop: 12, padding: "8px 10px",
          background: "#f8fafc", border: "1px dashed #cbd5e1",
          borderRadius: 8, fontSize: 10.5, color: "#475569",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4, color: "#0f172a" }}>
            📒 Encerrados (24h)
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {recentResolved.map((t) => (
              <div key={t.id}
                    data-testid={`recent-closed-chip-${t.id}`}
                    onDoubleClick={() => setClosedDetailTicket(t)}
                    title="Duplo-clique para ver os detalhes do fechamento"
                    style={{
                padding: "4px 8px", background: "white",
                border: "1px solid #e2e8f0", borderRadius: 6,
                fontSize: 10.5, cursor: "pointer",
                transition: "background 120ms",
              }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "#f1f5f9"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "white"; }}>
                <strong>{TYPE_LABELS[t.type] || t.type}</strong>
                {" · "}{t.client_snapshot?.name}
                {t.duration_minutes != null && (
                  <span style={{ marginLeft: 5, color: "#0f172a", fontWeight: 700 }}>
                    · 🕐 {fmtDuration(t.duration_minutes)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {closedDetailTicket && (
        <ClosedTicketDetailModal
          ticket={closedDetailTicket}
          onClose={() => setClosedDetailTicket(null)}
        />
      )}
    </div>
  );
}

function TimelineSlot({ slot, isCurrentHour, techId, maxPerSlot, onSlotDrop, draggingId,
  onDragStart, onDragEnd, blinkOverdue, onAdminClose, onAdminOpen, onEdit, onReschedule,
  busy, selectMode, selectedIds, onToggleSelect }) {
  const [over, setOver] = useState(false);
  const isFull = slot.full;
  const tickets = slot.tickets || [];
  const isEmpty = tickets.length === 0;

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); if (!isFull) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); e.stopPropagation();
        setOver(false);
        if (!isFull) onSlotDrop(techId, slot.slot);
      }}
      data-testid={`timeline-slot-${techId}-${slot.slot}`}
      style={{
        flex: "0 0 160px",
        background: over ? "#bfdbfe" : isFull ? "#fef3c7" : isEmpty ? "#fafbfc" : "#f8fafc",
        border: over ? "2px dashed #3b82f6"
              : isCurrentHour ? "2px solid #22c55e"
              : "1px solid #e2e8f0",
        borderRadius: 10, padding: 6,
        position: "relative",
        transition: "background-color .15s, border-color .15s",
        display: "flex", flexDirection: "column", gap: 4,
      }}
    >
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "2px 4px 4px", borderBottom: "1px solid #e2e8f0",
      }}>
        <span style={{
          fontSize: 11.5, fontWeight: 800,
          color: isCurrentHour ? "#15803d" : isFull ? "#92400e" : "#0f172a",
          letterSpacing: ".02em",
        }}>
          {slot.slot}{isCurrentHour && " ●"}
        </span>
        <span style={{
          fontSize: 9.5, fontWeight: 600,
          color: isFull ? "#92400e" : "#94a3b8",
        }}>
          {tickets.length}/{maxPerSlot}{isFull && " 🔒"}
        </span>
      </div>
      {isEmpty ? (
        <div style={{
          fontSize: 10, color: "#cbd5e1", textAlign: "center",
          padding: "12px 4px", fontStyle: "italic",
        }}>
          {over ? "↓ Solte aqui ↓" : "vazio"}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {tickets.map((t) => (
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
  );
}


/* ============================================================
 * Auto-Reschedule on Degraded Signal — Modal de configuração
 * ============================================================ */
function AutoReschedConfigModal({ initial, onClose, onSaved }) {
  const [cfg, setCfg] = useState(initial || {
    enabled: false, delay_hours: 24,
    target_collaborator_id: null, rede_candidates: [],
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) setCfg(initial);
  }, [initial]);

  const save = async () => {
    setSaving(true);
    try {
      const next = await api.lousaAutoReschedSet({
        enabled: cfg.enabled,
        delay_hours: cfg.delay_hours,
        target_collaborator_id: cfg.target_collaborator_id || null,
      });
      onSaved(next);
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  };

  const candidates = cfg.rede_candidates || [];

  return (
    <div onClick={onClose} data-testid="auto-resched-modal"
          style={{ position: "fixed", inset: 0, zIndex: 1100,
                    background: "rgba(0,0,0,.55)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "var(--bg-canvas)", padding: 24,
                      borderRadius: 12, maxWidth: 520, width: "100%",
                      border: "2px solid #0f766e",
                      boxShadow: "0 20px 50px rgba(0,0,0,.3)" }}>
        <h3 style={{ margin: "0 0 6px", fontSize: 17, fontWeight: 800,
                        color: "#0f172a" }}>
          🟢 Auto-reagendar OS com sinal degradado
        </h3>
        <p style={{ fontSize: 12, color: "var(--text-muted)",
                      marginBottom: 16 }}>
          Quando um técnico finaliza uma OS e o sinal piora
          (<strong>|sinal fechamento| &gt; |sinal abertura|</strong>),
          o sistema cria automaticamente uma nova OS de reinspeção
          atribuída a um técnico de rede.
        </p>

        {/* Toggle */}
        <label data-testid="auto-resched-enable-label"
                style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", padding: "10px 12px",
                          background: cfg.enabled ? "#ecfdf5" : "#f1f5f9",
                          border: `1px solid ${cfg.enabled ? "#6ee7b7" : "#cbd5e1"}`,
                          borderRadius: 8, marginBottom: 14,
                          cursor: "pointer" }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13,
                              color: cfg.enabled ? "#065f46" : "#475569" }}>
              {cfg.enabled ? "🟢 Ligado" : "⚪ Desligado"}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
              {cfg.enabled
                ? "Próximas OS com sinal degradado serão reagendadas automaticamente."
                : "Nenhuma ação automática enquanto desligado."}
            </div>
          </div>
          <input type="checkbox"
                    data-testid="auto-resched-toggle-input"
                    checked={!!cfg.enabled}
                    onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
                    style={{ width: 36, height: 20, cursor: "pointer" }} />
        </label>

        {/* Delay */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", fontSize: 11,
                            fontWeight: 700, color: "var(--text-secondary)",
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 6 }}>
            Reagendar para daqui a quantas horas
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            {[12, 24, 48, 72].map((h) => (
              <button key={h} type="button"
                        data-testid={`auto-resched-delay-${h}`}
                        onClick={() => setCfg({ ...cfg, delay_hours: h })}
                        style={{ flex: 1, padding: "8px 0", borderRadius: 6,
                                  border: `1px solid ${cfg.delay_hours === h ? "#0f766e" : "#cbd5e1"}`,
                                  background: cfg.delay_hours === h ? "#0f766e" : "white",
                                  color: cfg.delay_hours === h ? "white" : "#0f172a",
                                  fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
                {h}h
              </button>
            ))}
          </div>
        </div>

        {/* Target */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: "block", fontSize: 11,
                            fontWeight: 700, color: "var(--text-secondary)",
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 6 }}>
            Técnico de rede que receberá a OS
          </label>
          <select value={cfg.target_collaborator_id || ""}
                    data-testid="auto-resched-target-select"
                    onChange={(e) => setCfg({
                      ...cfg,
                      target_collaborator_id: e.target.value || null,
                    })}
                    style={{ width: "100%", padding: "8px 10px",
                              borderRadius: 6, border: "1px solid #cbd5e1",
                              fontSize: 13 }}>
            <option value="">Automático (primeiro disponível)</option>
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          {candidates.length === 0 && (
            <div style={{ fontSize: 10, color: "#92400e",
                            background: "#fffbeb", padding: "5px 8px",
                            borderRadius: 4, marginTop: 6, border: "1px solid #fcd34d" }}>
              ⚠ Nenhum colaborador com cargo/role contendo &quot;rede&quot;.
              Cadastre técnicos de rede no painel de Colaboradores.
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}
                    style={{ padding: "8px 18px", background: "white",
                              border: "1px solid #cbd5e1", borderRadius: 6,
                              fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
            Cancelar
          </button>
          <button onClick={save}
                    data-testid="auto-resched-save"
                    disabled={saving}
                    style={{ padding: "8px 18px", background: "#0f766e",
                              color: "white", border: "none",
                              borderRadius: 6, fontWeight: 700, fontSize: 12,
                              cursor: saving ? "wait" : "pointer",
                              opacity: saving ? 0.7 : 1 }}>
            {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}



/* ============================================================
 * AdminFinalizeModal — gestor finaliza OS no lugar do técnico,
 * com mesmas regras (drop, esticadores, sinal, observações).
 * Aplica os mesmos hooks no backend (signal snapshot, auto-resched).
 * ============================================================ */
function AdminFinalizeModal({ ticket, onClose, onSubmit }) {
  const [form, setForm] = useState({ sinal: "", observacoes: "" });
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const setF = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const cname = ticket?.client_snapshot?.name || ticket?.id;

  const submit = async () => {
    if (form.sinal === "" || Number.isNaN(Number(form.sinal))) {
      window.alert("Informe o sinal óptico final (dBm).");
      return;
    }
    setBusy(true);
    try {
      // Fechamento interno (gestor/auditor): NÃO consome insumos nem ONT.
      // Apenas registra sinal final do cliente + observações + justificativa.
      const cd = {
        sinal: Number(form.sinal),
        qtd_drop: 0,
        esticadores: 0,
        conectores_fast: 0,
        cabo_rede: 0,
        conectores_rede: 0,
        ont: null,
        observacoes: form.observacoes || null,
        closed_by_admin: true,
        internal_close: true,
      };
      await onSubmit(cd, notes);
    } catch (e) {
      window.alert(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose} data-testid="admin-finalize-modal"
          style={{ position: "fixed", inset: 0, zIndex: 1200,
                    background: "rgba(0,0,0,.55)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 16,
                    overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "var(--bg-canvas, white)", padding: 22,
                      borderRadius: 12, maxWidth: 560, width: "100%",
                      border: "2px solid #0f766e",
                      boxShadow: "0 20px 50px rgba(0,0,0,.3)",
                      maxHeight: "90vh", overflowY: "auto" }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 17, fontWeight: 800,
                        color: "#0f172a" }}>
          🏁 Finalizar OS no lugar do técnico
        </h3>
        <p style={{ fontSize: 11, color: "#64748b", marginBottom: 12 }}>
          Cliente: <strong>{cname}</strong>
          {ticket.assigned_collaborator_id && (
            <span> · técnico: {ticket.collaborator_name || ticket.assigned_collaborator_id}</span>
          )}
          <br/>Fechamento <strong>interno</strong>: registra apenas o sinal
          final do cliente e a descrição. <strong>Não consome insumos nem
          ONT</strong> (técnico não esteve no local).
        </p>

        <div style={{ marginBottom: 10 }}>
          <FieldNum label="Sinal final (dBm) *" testid="adm-fin-sinal"
                      step="0.1" value={form.sinal}
                      onChange={(v) => setF("sinal", v)} required />
        </div>

        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "#475569", textTransform: "uppercase",
                          letterSpacing: 0.5, marginBottom: 4 }}>
          Observações do serviço
        </label>
        <textarea data-testid="adm-fin-obs"
                    value={form.observacoes}
                    onChange={(e) => setF("observacoes", e.target.value)}
                    placeholder="Ex: substituído drop, ajustada emenda no CTO, etc."
                    style={{ width: "100%", padding: 8, fontSize: 12,
                              minHeight: 60, borderRadius: 6,
                              border: "1px solid #cbd5e1", marginBottom: 10,
                              fontFamily: "inherit" }} />

        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "#7c2d12", textTransform: "uppercase",
                          letterSpacing: 0.5, marginBottom: 4 }}>
          Justificativa (auditoria — por que o gestor está fechando)
        </label>
        <textarea data-testid="adm-fin-notes"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Ex: técnico não conseguiu finalizar via app, registrei manualmente."
                    style={{ width: "100%", padding: 8, fontSize: 12,
                              minHeight: 50, borderRadius: 6,
                              border: "1px solid #fcd34d",
                              background: "#fffbeb",
                              marginBottom: 16, fontFamily: "inherit" }} />

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}
                    style={{ padding: "8px 18px", background: "white",
                              border: "1px solid #cbd5e1", borderRadius: 6,
                              fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
            Cancelar
          </button>
          <button onClick={submit}
                    data-testid="adm-fin-submit"
                    disabled={busy}
                    style={{ padding: "8px 18px", background: "#0f766e",
                              color: "white", border: "none",
                              borderRadius: 6, fontWeight: 700, fontSize: 12,
                              cursor: busy ? "wait" : "pointer",
                              opacity: busy ? 0.7 : 1 }}>
            {busy ? "Finalizando..." : "✓ Finalizar OS"}
          </button>
        </div>
      </div>
    </div>
  );
}

function FieldNum({ label, value, onChange, step = "1", required, testid }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#475569",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       marginBottom: 3 }}>
        {label}{required && <span style={{ color: "#dc2626" }}> *</span>}
      </div>
      <input type="number" step={step} value={value}
                data-testid={testid}
                onChange={(e) => onChange(e.target.value)}
                style={{ width: "100%", padding: "6px 8px",
                          border: "1px solid #cbd5e1", borderRadius: 6,
                          fontSize: 13, fontWeight: 600 }} />
    </label>
  );
}
// (FieldText removido — fechamento interno não usa campos de texto livre)


