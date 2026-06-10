import React, { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { api } from "@/api";
import { fmtAddress, fmtPhone, fmtName, fmtRelato, safeText } from "@/utils/format";
import { Button, Icon } from "@/ui";
import { useAuth } from "@/AuthContext";
import EditTicketModal from "./lousa/EditTicketModal";
import CreateTicketModal from "./lousa/CreateTicketModal";
import LousaTvLinkModal from "./lousa/LousaTvLinkModal";
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
import LousaServicesMap from "./LousaServicesMap";
import { styleForQuality } from "@/signalQuality";
import ManagerCallbacksPanel from "./ManagerCallbacksPanel";
import {
  AiDetailModal,
  ClosedTicketDetailModal,
  AutoReschedConfigModal,
  AdminFinalizeModal,
} from "./lousa-admin/modals";
import { ClosedNotesPdfPopover } from "./lousa-admin/report";

const TYPE_LABELS = {
  reparo: "Reparo",
  instalacao: "Instalação",
  retirada: "Retirada",
  prioridade: "Prioridade",
  preventiva: "️ Preventiva",
  venda: "Venda",
  rompimento: "Rompimento",
  alerta_geofence: "️ ALERTA GEOFENCE",
};

const TYPE_ICONS = {
  instalacao: "",
  retirada: "",
  visita_tecnica: "️",
  manutencao: "",
  upgrade: "⬆️",
  downgrade: "⬇️",
  troca_endereco: "",
  troca_titularidade: "",
  cancelamento: "",
  outros: "",
  venda: "",
};

// ─────────── Áudio de alerta na SmarTV (iter237) ───────────
// Beep via Web Audio API — não precisa de asset mp3.
// IMPORTANTE: browsers exigem 1ª interação do usuário antes de tocar.
// Ligamos via click no toggle "Som ligado" no header da Lousa.
let _lousaAudio = null;
function _ensureLousaAudio() {
  if (typeof window === "undefined") return null;
  if (_lousaAudio) return _lousaAudio;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    _lousaAudio = new Ctx();
  } catch { _lousaAudio = null; }
  return _lousaAudio;
}
function _tone(freq, startOffset, durMs, vol = 0.22) {
  const ctx = _ensureLousaAudio();
  if (!ctx) return;
  try {
    const t0 = ctx.currentTime + startOffset / 1000;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine"; osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.001, t0);
    gain.gain.exponentialRampToValueAtTime(vol, t0 + 0.02);
    gain.gain.setValueAtTime(vol, t0 + (durMs - 50) / 1000);
    gain.gain.exponentialRampToValueAtTime(0.001, t0 + durMs / 1000);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + durMs / 1000);
  } catch { /* */ }
}
// Som PRETA — SLA overdue do técnico em campo: 5 toques graves
// alternados ao longo de 5s (lembra "tic-tac-tic-tac" de cronômetro).
function playBlackAlert() {
  for (let i = 0; i < 5; i++) {
    _tone(i % 2 === 0 ? 220 : 180, i * 1000, 400, 0.24);
  }
}
// Som VERMELHA — alerta de cerca/frota: sirene aguda urgente
// (intercala 880↔660Hz por 5s, igual sirene de ambulância).
function playRedAlert() {
  for (let i = 0; i < 10; i++) {
    _tone(i % 2 === 0 ? 880 : 660, i * 500, 450, 0.20);
  }
}

// TTS (Text-to-Speech) em PT-BR — anuncia o cliente da bolha.
// Roda DEPOIS do beep (delay de 1s pra não sobrepor o som).
function speakAnnouncement(text) {
  try {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "pt-BR";
    u.rate = 0.95;
    u.pitch = 1.0;
    u.volume = 0.9;
    // Tenta pegar uma voz brasileira (se disponível)
    const voices = window.speechSynthesis.getVoices();
    const ptBr = voices.find((v) => v.lang === "pt-BR")
                    || voices.find((v) => v.lang.startsWith("pt"));
    if (ptBr) u.voice = ptBr;
    setTimeout(() => window.speechSynthesis.speak(u), 1000);
  } catch { /* */ }
}
// Constrói o texto do anúncio a partir da bolha
function buildAnnouncement(ticket, kind) {
  const cs = ticket.client_snapshot || {};
  const name = (cs.client_name || cs.name || ticket.client_name
                  || ticket.title || "cliente").split(/\s+/).slice(0, 2).join(" ");
  const hora = ticket.scheduled_time
    ? (ticket.scheduled_time + "").substring(0, 5).replace(":", " e ")
    : "";
  if (kind === "red") {
    if (ticket.type === "alerta_geofence") {
      return `Atenção! Alerta de cerca. ${name} está fora da área autorizada.`;
    }
    if (ticket.type === "frota_alerta") {
      return `Atenção! Alerta de frota. ${name}.`;
    }
    return `Atenção! Alerta urgente. ${name}.`;
  }
  // Preta = SLA estourado em OS aberta
  return `Atenção! Ordem de serviço atrasada. Cliente ${name}${hora ? ", agendada para " + hora + " horas" : ""}.`;
}

const PRIORITY_COLORS = {
  prioridade: {
    bg: "#fff7f7",
    accent: "#dc2626", border: "#fecaca", text: "#991b1b",    label: "PRIORIDADE", icon: "",
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
  aguardando_atendimento: { label: "Aguarda gestor", color: "#f59e0b" },
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
  reagendar: { icon: "", color: "#3b82f6", label: "Reagendada" },
  cancelar: { icon: "", color: "#dc2626", label: "Cancelada" },
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

  // Atualiza badge de transferências pendentes a cada 30s
  useEffect(() => {
    let mounted = true;
    const fetchPending = () => {
      api.stokPendingTransfers("pending").then((r) => {
        if (mounted) setPendingTransfersCount(r?.items?.length || 0);
      }).catch(() => {});
    };
    fetchPending();
    const id = setInterval(fetchPending, 30000);
    return () => { mounted = false; clearInterval(id); };
  }, []);
  const { user } = useAuth();
  const [grid, setGrid] = useState({ columns: [], sla_blink_when_overdue: true, sla_warning_pct: 80 });
  const [collabs, setCollabs] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [createDefaults, setCreateDefaults] = useState(null);
  const [editingTicket, setEditingTicket] = useState(null);
  const [reschedTicket, setReschedTicket] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showSentinela, setShowSentinela] = useState(false);
  const [showReleaseStuck, setShowReleaseStuck] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState("board"); // board | central_ont
  const [sentinelaCount, setSentinelaCount] = useState(0);
  const [pendingCallbacksCount, setPendingCallbacksCount] = useState(0);
  const [pendingTransfersCount, setPendingTransfersCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [draggingId, setDraggingId] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);
  const [logs, setLogs] = useState([]);
  // iter237 — Filtro por agente IA (Isabella/Álvaro/Camila/Gestor/Sistema)
  const [agentFilter, setAgentFilter] = useState("all");
  // iter237 — Áudio de alerta na TV (modo SmarTV).
  // Toca 5s quando uma bolha começa a pulsar:
  //   • PRETA (SLA overdue + status "aberta") → som grave alternado
  //   • VERMELHA (alerta_geofence) → sirene aguda urgente
  const [soundEnabled, setSoundEnabled] = useState(() => {
    try { return localStorage.getItem("lousa_tv_sound") !== "off"; }
    catch { return true; }
  });
  const lastAlertRef = useRef(new Set()); // ticket_ids que já tocaram
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
  const [showServicesMap, setShowServicesMap] = useState(false);
  const [showTvLink, setShowTvLink] = useState(false);
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
  const [onlyFleetAlerts, setOnlyFleetAlerts] = useState(false);  // filtro frota_alerta
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
    // iter237 — Sincronização Lousa Admin ↔ Lousa Mobile:
    // baixamos o intervalo de refresh de 30s → 8s pra que, quando um técnico
    // abrir/fechar uma bolha no celular, o admin veja a mudança ("▶ Em campo"
    // verde, ou movida pra "Encerrados (24h)") em até 8 segundos. A SSE
    // logo abaixo já força refresh imediato em eventos do worker Atlaz.
    const t1 = setInterval(refresh, 8000);  // refresh dados (sync c/ mobile)
    const t2 = setInterval(() => setTick((x) => x + 1), 5000);  // re-render p/ animação SLA
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [refresh]);

  // iter237 — SmarTV alert sound: detecta bolhas que ACABARAM de começar
  // a pulsar e toca o som correspondente (preta vs vermelha).
  // Roda toda vez que `grid` muda (a cada refresh de 8s).
  useEffect(() => {
    if (!soundEnabled) return;
    const tickets = [];
    for (const col of grid.columns || []) {
      for (const t of col.tickets || []) tickets.push(t);
    }
    const seen = lastAlertRef.current;
    let blackTriggered = false;
    let redTriggered = false;
    const stillAlive = new Set();
    for (const t of tickets) {
      const id = t.id;
      const isBlack = (t.sla?.status === "overdue"
        && t.status === "aberta"
        && t.priority !== "horario");
      const isRed = (t.type === "alerta_geofence"
        || t.type === "frota_alerta");
      if (isBlack || isRed) {
        stillAlive.add(id);
        if (!seen.has(id)) {
          if (isRed && !redTriggered) {
            playRedAlert();
            speakAnnouncement(buildAnnouncement(t, "red"));
            redTriggered = true;
          } else if (isBlack && !blackTriggered) {
            playBlackAlert();
            speakAnnouncement(buildAnnouncement(t, "black"));
            blackTriggered = true;
          }
          seen.add(id);
        }
      }
    }
    // Remove tickets que pararam de pulsar (foram resolvidos)
    for (const id of seen) {
      if (!stillAlive.has(id)) seen.delete(id);
    }
  }, [grid, soundEnabled]);

  // SSE: refresh imediato quando o worker Atlaz cria novas bolhas
  const [atlazFlash, setAtlazFlash] = useState("");
  useEventStream({
    onEvent: (name, data) => {
      if (name === "atlaz_bubbles_synced" && data?.created > 0) {
        setAtlazFlash(`${data.created} nova(s) bolha(s) sincronizada(s) do Atlaz`);
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

  // Polling do contador de callbacks pendentes (técnico→gestor)
  useEffect(() => {
    let alive = true;
    const fetchCount = () => {
      api.lousaManagerCallbacks("pending", 200)
        .then((r) => { if (alive) setPendingCallbacksCount(r?.count || 0); })
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
  const fleetAlertCount = grid.columns.flatMap((c) => c.tickets || [])
    .filter((t) => t.type === "frota_alerta" && t.status !== "finalizada").length;

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
      {/* Animação CSS do piscar — agora preto */}
      <style>{`
        @keyframes pulseBlack {
          0%, 100% { box-shadow: 0 0 0 0 rgba(15, 23, 42, 0.6); border-color: #0f172a; }
          50% { box-shadow: 0 0 0 12px rgba(15, 23, 42, 0); border-color: #1f2937; }
        }
        .sla-overdue { animation: pulseBlack 1.4s ease-in-out infinite; }
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
              <span style={{ fontSize: 13 }}></span>
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
            {/* Pendentes de transferência ONT */}
            {pendingTransfersCount > 0 && (
              <ToolbarBtn
                onClick={() => {
                  // Tenta navegar para Estoque > Transferências
                  if (typeof window !== "undefined") {
                    window.dispatchEvent(new CustomEvent("ponto:navigate",
                      { detail: { view: "estoque", sub: "transfers" } }));
                  }
                }}
                data-testid="open-pending-transfers-btn"
                title="Transferências ONT aguardando aprovação"
                accent="danger"
              >
                <span style={{ fontSize: 13 }}></span>
                <span>Transferências</span>
                <span data-testid="pending-transfers-badge" style={{
                  marginLeft: 2, padding: "1px 6px", borderRadius: 999,
                  background: "#dc2626", color: "#fff",
                  fontSize: 10, fontWeight: 800,
                  fontFamily: "ui-monospace, monospace",
                }}>{pendingTransfersCount}</span>
              </ToolbarBtn>
            )}
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
                      <span style={{ fontSize: 13 }}></span>
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
              <span style={{ fontSize: 13 }}>{selectMode ? "✕" : ""}</span>
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
                <span style={{ fontSize: 13 }}></span>
                <span>Atrasadas · {overdueCount}</span>
              </ToolbarBtn>
            )}
            {fleetAlertCount > 0 && (
              <ToolbarBtn
                onClick={() => setOnlyFleetAlerts(!onlyFleetAlerts)}
                data-testid="lousa-fleet-filter-btn"
                title="Mostrar apenas alertas de Frota (vistoria recusada pela IA)"
                accent={onlyFleetAlerts ? "warning" : "neutral"}
                style={{ minWidth: 110, justifyContent: "center" }}
              >
                <span style={{ fontSize: 13 }}></span>
                <span>{onlyFleetAlerts ? "Só Frota" : "Frota"} · {fleetAlertCount}</span>
              </ToolbarBtn>
            )}
            <ToolbarBtn
              onClick={() => setShowHistory(true)}
              data-testid="lousa-history-btn"
              title="Histórico completo de notas (dia/mês/ano/período)"
              accent="neutral"
            >
              <span style={{ fontSize: 13 }}></span>
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
              style={{ minWidth: 96, justifyContent: "center" }}
            >
              <span style={{ fontSize: 13 }}>{alertsOn ? "" : ""}</span>
              <span>{alertsOn ? "Alertas" : "Mudo"}</span>
            </ToolbarBtn>
            <ToolbarBtn
              onClick={refresh}
              disabled={refreshing}
              data-testid="lousa-refresh-btn"
              accent={refreshFlash ? "success" : "neutral"}
              style={{ minWidth: 130, justifyContent: "center",
                       transition: "background-color .25s, color .25s" }}
            >
              <span style={{ fontSize: 13 }}>{refreshing ? "⏳" : refreshFlash ? "✓" : ""}</span>
              <span>{refreshing ? "Atualizando" : refreshFlash ? "Atualizado" : "Atualizar"}</span>
            </ToolbarBtn>
            <ToolbarBtn
              onClick={async () => {
                if (!window.confirm("Distribuir bolhas pendentes na grade de horário?\n\n• HORÁRIO/PRIORIDADE/URGENTE mantêm seu slot.\n• Normais são alocadas no slot livre mais próximo do GPS do técnico.\n• Se faltar slot, permite 2 por horário."))
                  return;
                try {
                  const r = await api.lousaAutoDistribute({
                    slot_minutes: 60, work_start_hour: 8, work_end_hour: 18,
                    allow_double_per_slot: true,
                  });
                  const total = (r.details || []).reduce((acc, d) => acc + (d.moved || 0), 0);
                  alert(`✅ ${total} bolha(s) distribuída(s) em ${r.collaborators_processed} técnico(s).`);
                  await refresh();
                } catch (e) {
                  alert(`Erro ao otimizar: ${e?.response?.data?.detail || e.message}`);
                }
              }}
              data-testid="lousa-auto-distribute-btn"
              title="Distribuir bolhas pendentes na grade de horário automaticamente (logística por GPS)"
              accent="info"
            >
              <span style={{ fontSize: 13 }}></span>
              <span>Otimizar grade</span>
            </ToolbarBtn>
            <ToolbarBtn
              onClick={() => {
                // 1ª interação do usuário libera o AudioContext.
                _ensureLousaAudio()?.resume?.();
                // Pre-carrega vozes do TTS PT-BR (browsers carregam async)
                try { window.speechSynthesis?.getVoices(); } catch { /* */ }
                const next = !soundEnabled;
                setSoundEnabled(next);
                try { localStorage.setItem("lousa_tv_sound", next ? "on" : "off"); }
                catch { /* */ }
                if (next) {
                  // Beep + TTS curto pra confirmar que tudo funciona
                  _tone(660, 0, 200, 0.18);
                  speakAnnouncement("Som da Lousa ativado.");
                }
              }}
              data-testid="lousa-tv-sound-toggle"
              title={soundEnabled
                ? "Sons de alerta ligados (modo SmarTV). Clique para silenciar."
                : "Sons de alerta desligados. Clique para ativar (essencial pra usar na TV)."}
              accent={soundEnabled ? "success" : "neutral"}
            >
              <span style={{ fontSize: 13 }}>{soundEnabled ? "" : ""}</span>
              <span>{soundEnabled ? "Som TV" : "Som off"}</span>
            </ToolbarBtn>
            {/* Filtro rápido por agente IA */}
            <div data-testid="lousa-agent-filter" style={{
              display: "inline-flex", gap: 4, marginLeft: 6,
              padding: 2, background: "white", borderRadius: 8,
              border: "1px solid #e2e8f0",
            }}>
              {[
                { id: "all",      lbl: "Todos",    color: "#64748b" },
                { id: "isabella", lbl: "Isabella", color: "#a855f7" },
                { id: "alvaro",   lbl: "Álvaro",   color: "#0ea5e9" },
                { id: "camila",   lbl: "Camila",   color: "#10b981" },
                { id: "sistema",  lbl: "Sistema",  color: "#3b82f6" },
                { id: "gestor",   lbl: "Gestor",   color: "#475569" },
              ].map((f) => (
                <button key={f.id}
                  data-testid={`lousa-agent-filter-${f.id}`}
                  onClick={() => setAgentFilter(f.id)}
                  style={{
                    padding: "4px 10px", borderRadius: 6,
                    border: "none", cursor: "pointer",
                    fontSize: 11, fontWeight: 800, fontFamily: "inherit",
                    letterSpacing: 0.2,
                    background: agentFilter === f.id ? f.color : "transparent",
                    color: agentFilter === f.id ? "white" : f.color,
                    transition: "all .15s",
                  }}>{f.lbl}</button>
              ))}
            </div>
            <ToolbarBtn
              onClick={() => setShowReleaseStuck(true)}
              data-testid="lousa-release-stuck-btn"
              title="EMERGÊNCIA — libera bolha presa do técnico (ação auditada)"
              accent="danger"
            >
              <span style={{ fontSize: 13 }}></span>
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
                  {autoReschedCfg?.enabled ? "" : ""}
                </span>
                <span>
                  Auto-rede {autoReschedCfg?.enabled ? "ON" : "OFF"}
                </span>
              </ToolbarBtn>
            )}
            <div style={{ position: "relative", display: "inline-flex" }}>
              <ToolbarBtn
                onClick={() => setShowPdfPopover((v) => !v)}
                data-testid="lousa-pdf-btn"
                title="Gerar relatório de notas finalizadas/abertas (hoje/ontem/7 dias/período)"
                accent="neutral"
              >
                <span style={{ fontSize: 13 }}></span>
                <span>Relatório</span>
              </ToolbarBtn>
              {showPdfPopover && (
                <ClosedNotesPdfPopover onClose={() => setShowPdfPopover(false)} />
              )}
            </div>
            <ToolbarBtn
              onClick={() => setShowServicesMap(true)}
              data-testid="lousa-map-btn"
              title="Visualiza no mapa todas as bolhas com pinos coloridos por técnico"
              accent="neutral"
            >
              <span style={{ fontSize: 13 }}>️</span>
              <span>Mapa</span>
            </ToolbarBtn>
            <ToolbarBtn
              onClick={() => setShowTvLink(true)}
              data-testid="lousa-tv-link-btn"
              title="Abre o link público da Lousa para exibir em SmartTV (somente leitura)"
              accent="neutral"
            >
              <span style={{ fontSize: 13 }}></span>
              <span>TV</span>
            </ToolbarBtn>
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
              <span>Nova nota{atlazTenantDomain ? " " : ""}</span>
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
                          "ATENÇÃO: isto APAGA TODAS as bolhas da empresa, incluindo as em execução.\n" +
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
                      <span style={{ fontSize: 14 }}></span>
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
          LOUSA TRANCADA — {systemStatus.offline ? "dispositivo offline" : "horário dessincronizado"}.
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
            {dateMode === "past" ? "Visualizando dia passado" : "Visualizando dia futuro"}
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
          { id: "board", label: "Quadro" },
          { id: "insights", label: "PAINEL IA" },
          { id: "central_ont", label: "️ CENTRAL_ONT" },
          { id: "gestao_metas", label: "GESTÃO E METAS" },
          { id: "quality_notes", label: "NOTAS DE QUALIDADE" },
          { id: "callbacks", label: (
            <>
              AGUARDANDO CONTATO
              {pendingCallbacksCount > 0 && (
                <span data-testid="callbacks-badge" style={{
                  marginLeft: 6, background: "#dc2626", color: "#fff",
                  padding: "1px 7px", borderRadius: 99, fontSize: 10,
                  fontWeight: 800,
                }}>{pendingCallbacksCount}</span>
              )}
            </>
          ) },
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
        (activeSubTab === "callbacks" ? <ManagerCallbacksPanel /> :
        (activeSubTab === "insights"
          ? <InsightsPanel onJumpTicket={(t) => setEditingTicket(t)} />
          : <></>))))}
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
        ).map((origCol) => {
          // Filtro "Só Frota": esconde bolhas que não são frota_alerta
          let col = onlyFleetAlerts
            ? { ...origCol, tickets: (origCol.tickets || [])
                .filter((t) => t.type === "frota_alerta") }
            : origCol;
          // Filtro por agente IA (origin_source ou created_by)
          if (agentFilter !== "all") {
            const ISABELLA = new Set(["isabella_ai", "isabella_route_support",
              "isabella_viability", "isabella_vision"]);
            const ALVARO = new Set(["alvaro_diagnose", "alvaro_ai"]);
            const CAMILA = new Set(["camila_billing", "camila_ai", "camila_cobranca"]);
            const matchAgent = (t) => {
              const src = t.origin_source || t.created_by || "";
              if (agentFilter === "isabella") return ISABELLA.has(src);
              if (agentFilter === "alvaro") return ALVARO.has(src);
              if (agentFilter === "camila") return CAMILA.has(src);
              if (agentFilter === "gestor") {
                const ai = new Set([...ISABELLA, ...ALVARO, ...CAMILA]);
                return !ai.has(src) && !["alerta_geofence", "frota_alerta",
                  "alerta_ia", "signal_callback", "auto_retargeting"]
                  .includes(t.type);
              }
              if (agentFilter === "sistema") {
                return ["alerta_geofence", "frota_alerta", "alerta_ia",
                  "signal_callback", "auto_retargeting"].includes(t.type);
              }
              return true;
            };
            col = { ...col, tickets: (col.tickets || []).filter(matchAgent) };
          }
          return focusTechId && focusView === "timeline" ? (
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
              onEmptySlotDblClick={(techId, slotHour) => {
                const dt = `${selectedDate}T${slotHour}`;
                setCreateDefaults({ assigned_collaborator_id: techId, scheduled_time: dt });
                setShowCreate(true);
              }}
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
              onEmptySlotDblClick={(techId, slotHour) => {
                // Constrói datetime-local YYYY-MM-DDTHH:MM com base no
                // selectedDate (já no formato YYYY-MM-DD) e no slotHour HH:MM
                const dt = `${selectedDate}T${slotHour}`;
                setCreateDefaults({
                  assigned_collaborator_id: techId,
                  scheduled_time: dt,
                });
                setShowCreate(true);
              }}
              wide={!!focusTechId}
            />
          );
        })}
      </div>

      {/* Logs de auditoria */}
      <LogsPanel logs={logs} collabs={collabs} />
      </>}

      {showCreate && (
        <CreateTicketModal
          collabs={collabs}
          defaults={createDefaults}
          onClose={() => { setShowCreate(false); setCreateDefaults(null); }}
          onCreated={() => { setShowCreate(false); setCreateDefaults(null); refresh(); }}
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
      {showServicesMap && (
        <LousaServicesMap onClose={() => setShowServicesMap(false)} />
      )}
      {showTvLink && (
        <LousaTvLinkModal onClose={() => setShowTvLink(false)} />
      )}
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
    >{busy ? "..." : "️ Rota"}</button>
  );
}


function TechColumn({ column, isDropTarget, blinkOverdue, onDragOver, onDragLeave, onDrop, onDragStart, onDragEnd, draggingId, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, maxPerSlot, onSlotDrop, selectMode, selectedIds, onToggleSelect, onEmptySlotDblClick, wide }) {
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
            {r.type === "Entrada" ? "" : r.type === "Início intervalo" ? "️" : r.type === "Fim intervalo" ? "" : ""} {r.time}
          </span>
        ))}
      </div>

      {/* Serviços encerrados nas últimas 24h — texto simples para conferência (gap entre serviços) */}
      {recentResolved.length > 0 && (
        <div data-testid={`recent-resolved-${c.id}`} style={{
          marginTop: 10, padding: "6px 8px", background: "#f8fafc", border: "1px dashed #cbd5e1",
          borderRadius: 8, fontSize: 10, color: "#475569",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4, color: "#0f172a" }}>Encerrados (24h)</div>
          {recentResolved.map((t) => (
            <div key={t.id}
                  data-testid={`recent-closed-row-${t.id}`}
                  onClick={() => setClosedDetailTicket(
                    closedDetailTicket?.id === t.id ? null : t)}
                  title="Clique para abrir os detalhes — clique novamente ou fora pra fechar"
                  style={{ marginBottom: 4, cursor: "pointer",
                            borderRadius: 5, padding: "2px 4px",
                            background: closedDetailTicket?.id === t.id
                              ? "#eef2f7" : "transparent" }}
                  onMouseEnter={(e) => { if (closedDetailTicket?.id !== t.id) e.currentTarget.style.background = "#eef2f7"; }}
                  onMouseLeave={(e) => { if (closedDetailTicket?.id !== t.id) e.currentTarget.style.background = "transparent"; }}>
              {t.gap_minutes_to_prev != null && (
                <div style={{ fontStyle: "italic", color: "#94a3b8", padding: "2px 0" }}>
                  ⏱ {fmtGap(t.gap_minutes_to_prev)} entre o serviço anterior e este
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                <span><strong>{TYPE_LABELS[t.type] || t.type}</strong> · {t.client_snapshot?.name}</span>
                <span style={{ color: "#0f172a", fontWeight: 700 }}>
                  {t.duration_minutes != null ? `${fmtDuration(t.duration_minutes)}` : ""}
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
          onReopened={() => { setClosedDetailTicket(null); window.location.reload(); }}
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
            onEmptySlotDblClick={onEmptySlotDblClick}
          />
        ))}
        {/* "Sem horário" REMOVIDO (iter215): toda bolha agora cai num slot da
              grade (09:00–18:00) — clampada se horário fora do range. */}
      </div>
    </div>
  );
}

function SlotRow({ slot, techId, maxPerSlot, onSlotDrop, draggingId, onDragStart, onDragEnd, blinkOverdue, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, selectMode, selectedIds, onToggleSelect, onEmptySlotDblClick }) {
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
      onDoubleClick={(e) => {
        // Só dispara o "Nova OS" se o slot está VAZIO. Se já tem bolhas,
        // o duplo clique nelas é tratado pelo card (abrir detalhes).
        if (isEmpty && onEmptySlotDblClick) {
          e.stopPropagation();
          onEmptySlotDblClick(techId, slot.slot);
        }
      }}
      title={isEmpty ? "Duplo clique pra criar Nova OS neste horário" : undefined}
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
        <span>{slot.slot}</span>
        <span style={{ fontSize: 9 }}>
          {tickets.length}/{maxPerSlot}{isFull && " cheio"}
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
                forceExpanded={tickets.length === 1}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentBadge({ ticket }) {
  // Mapeia agente IA → { label, cor, tooltip } a partir do origin_source
  // ou created_by da bolha. Mostra um avatar circular 14px com a letra do
  // agente — pro gestor identificar rápido quem abriu a OS.
  const src = ticket.origin_source || ticket.created_by || "";
  const map = {
    isabella_ai:            { letter: "I", color: "#a855f7", title: "Isabella · IA do cliente (WhatsApp)" },
    isabella_route_support: { letter: "I", color: "#a855f7", title: "Isabella · roteado pra suporte" },
    isabella_viability:     { letter: "I", color: "#a855f7", title: "Isabella · viabilidade agendada" },
    isabella_vision:        { letter: "I", color: "#a855f7", title: "Isabella · análise de imagem" },
    alvaro_diagnose:        { letter: "A", color: "#0ea5e9", title: "Álvaro · diagnóstico técnico" },
    alvaro_ai:              { letter: "A", color: "#0ea5e9", title: "Álvaro · diagnóstico IA" },
    camila_billing:         { letter: "C", color: "#10b981", title: "Camila · cobrança IA" },
    camila_ai:              { letter: "C", color: "#10b981", title: "Camila · cobrança IA" },
    camila_cobranca:        { letter: "C", color: "#10b981", title: "Camila · cobrança IA" },
  };
  const cfg = map[src];
  if (!cfg) return null;
  return (
    <span title={cfg.title}
      data-testid={`bubble-agent-${ticket.id}`}
      style={{
        width: 16, height: 16, borderRadius: "50%",
        background: cfg.color, color: "white",
        display: "inline-grid", placeItems: "center",
        fontSize: 9, fontWeight: 900, letterSpacing: 0,
        flexShrink: 0, boxShadow: `0 1px 3px ${cfg.color}66`,
      }}>{cfg.letter}</span>
  );
}

function BubbleCard({ ticket, slotHour, blinkOverdue, isDragging, onDragStart, onDragEnd, onAdminClose, onAdminOpen, onEdit, onReschedule, busy, selectMode, isSelected, onToggleSelect, forceExpanded }) {
  const c = PRIORITY_COLORS[ticket.priority] || PRIORITY_COLORS.normal;
  const st = STATUS_LABEL[ticket.status] || { label: ticket.status, color: "#64748b" };
  const sla = ticket.sla || {};
  const ai = ticket.ai_score || {};
  const slaColor = sla.status === "overdue" ? "#dc2626" : sla.status === "warning" ? "#f59e0b" : "#10b981";
  const isOverdue = sla.status === "overdue";
  // iter237 — Regras solicitadas pelo Vando:
  //  • Pulse PRETO (não vermelho), e SOMENTE quando:
  //    – ticket.status === "aberta" (técnico iniciou e está demorando)
  //    – priority !== "horario" (HORÁRIO fixo nunca pulsa — só borda laranja)
  //    – SLA overdue + blinkOverdue ligado nas settings
  //  Bolhas PENDENTES atrasadas NÃO pulsam mais — só ficam com borda preta estática.
  const shouldPulse = isOverdue
    && blinkOverdue
    && ticket.status === "aberta"
    && ticket.priority !== "horario";

  // Origem da bolha (define cor da borda quando NÃO atrasada):
  //  • CLIENTE (verde): bolha foi gerada por um AGENTE DE IA que atende o
  //    cliente final — Isabella (WhatsApp), Álvaro (diagnóstico técnico),
  //    Camila (cobrança). Esses agentes representam a vontade do cliente
  //    pedindo abertura de chamado.
  //  • SISTEMA (azul): bolha foi gerada por um worker automático SEM
  //    interação direta com o cliente — alerta de cerca, frota_alerta,
  //    rede_ia outage, ai_preventive, etc.
  //  • GESTOR (padrão): operador humano abriu via painel admin.
  const CLIENT_AI_AGENTS = new Set([
    "isabella_ai", "isabella_route_support", "isabella_viability",
    "alvaro_diagnose", "alvaro_ai",
    "camila_billing", "camila_ai", "camila_cobranca",
  ]);
  const SYSTEM_TYPES = new Set([
    "alerta_geofence", "frota_alerta",
    "alerta_ia", "signal_callback", "auto_retargeting",
  ]);
  const isFromClient = ticket.origin === "cliente"
    || CLIENT_AI_AGENTS.has(ticket.origin_source)
    || CLIENT_AI_AGENTS.has(ticket.created_by)
    || ticket.opened_via === "client_whatsapp"
    || ticket.client_initiated === true;
  const isFromSystem = !isFromClient && (
    SYSTEM_TYPES.has(ticket.type)
    || ticket.origin === "sistema"
    || (ticket.origin_source
      && !["gestor", "manual", "operator"].includes(ticket.origin_source))
  );
  // Cor da borda (prioridade: pulse preto > selecionado azul > overdue preto >
  //                          horário laranja > sistema azul > cliente verde > padrão)
  let borderColor = c.border;
  if (ticket.type === "alerta_geofence") borderColor = "#0f172a";
  else if (ticket.type === "frota_alerta") borderColor = "#f59e0b";
  else if (isSelected) borderColor = "#3b82f6";
  else if (isOverdue && ticket.status === "aberta") borderColor = "#0f172a";
  else if (ticket.priority === "horario") borderColor = c.border; // laranja padrão
  else if (isFromSystem) borderColor = "#3b82f6";
  else if (isFromClient) borderColor = "#10b981";

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
        `Cliente: ${fmtName(ticket.client_snapshot.name)}`,
        ticket.client_snapshot.phone ? `Tel: ${fmtPhone(ticket.client_snapshot.phone)}` : null,
        ticket.client_snapshot.address ? `End.: ${fmtAddress(ticket.client_snapshot.address)}` : null,
        ticket.client_snapshot.neighborhood ? `Bairro: ${safeText(ticket.client_snapshot.neighborhood)}` : null,
        ticket.scheduled_time ? `Horário: ${ticket.scheduled_time.substr(11, 5)}` : null,
        ticket.atlaz_slot_original && ticket.scheduled_time
          && ticket.atlaz_slot_original !== ticket.scheduled_time
          ? `⏰ Atlaz original: ${ticket.atlaz_slot_original.substr(11, 5)} (slot cheio — movida)`
          : null,
        ticket.client_snapshot.relato ? `\nRelato:\n${fmtRelato(ticket.client_snapshot.relato)}` : null,
        ai.score != null ? `\nIA: ${ai.score.toFixed(1)}/10 (${ai.label || ""})` : null,
        ticket.in_execution ? "\n▶ Em execução pelo técnico" : null,
        ticket.atlaz_external_id ? `\nAtlaz #${ticket.atlaz_external_id}` : null,
        "\n— Duplo-clique para editar",
      ].filter(Boolean).join("\n");

  const typeIcon = TYPE_ICONS[ticket.type] || "";

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
        + (ticket.type === "frota_alerta" ? "lousa-fleet-glow " : "")
        + (shouldPulse ? "sla-overdue" : "")
      }
      style={{
        background: ticket.type === "alerta_geofence"
          ? "linear-gradient(135deg,#fee2e2,#fecaca)"
          : ticket.type === "frota_alerta"
          ? "linear-gradient(135deg,#fef3c7,#fde68a)"
          : c.bg,
        border: `${(ticket.type === "alerta_geofence" || ticket.type === "frota_alerta") ? 2 : (isFromSystem || isFromClient ? 2 : 1)}px solid ${borderColor}`,
        borderRadius: 14, padding: "6px 10px 6px 12px",
        marginBottom: 0, position: "relative",
        width: "100%", minWidth: 0, boxSizing: "border-box",
        cursor: selectMode ? (isSelectable ? "pointer" : "not-allowed") : "grab",
        opacity: isDragging ? 0.4 : (selectMode && !isSelectable ? 0.55 : 1),
        // Compact mode: altura máxima quando NÃO hovered; expande no hover
        // para mostrar todo o conteúdo sem cortar. Se forceExpanded (bolha
        // única no slot), abre completa por padrão.
        maxHeight: (showActions || forceExpanded) ? "none" : 42,
        overflow: (showActions || forceExpanded) ? "visible" : "hidden",
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

      {/* HEADER: badge prioridade · agente IA · status · horário */}
      <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", minWidth: 0 }}>
          {c.label && (
            <span style={{
              fontSize: 9, fontWeight: 900, letterSpacing: 0.5,
              padding: "2px 7px", borderRadius: 999,
              background: c.accent, color: "white",
            }}>{c.icon} {c.label}</span>
          )}
          <AgentBadge ticket={ticket} />
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
              {slotHour}
            </span>
          )}
          {!slotHour && ticket.scheduled_time && (
            <span style={{
              fontSize: 10, fontWeight: 800, color: "#475569",
              background: "#f1f5f9", padding: "2px 7px", borderRadius: 999,
              border: "1px solid #e2e8f0",
            }}>{ticket.scheduled_time.substr(11, 5)}</span>
          )}
          {/* iter211aa — Badge "movida" quando atlaz_slot_original difere
              do scheduled_time atual. Indica que essa bolha foi deslocada
              da hora real do Atlaz porque o slot estava cheio. */}
          {ticket.atlaz_slot_original
            && ticket.scheduled_time
            && ticket.atlaz_slot_original !== ticket.scheduled_time && (
            <span data-testid={`bubble-displaced-${ticket.id}`}
                  style={{
                    fontSize: 9, fontWeight: 800, color: "#9a3412",
                    background: "#fed7aa", padding: "2px 7px",
                    borderRadius: 999, border: "1px solid #fb923c",
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }} title={
              `Atlaz original: ${ticket.atlaz_slot_original.substr(11, 5)}`
              + ` (${ticket.atlaz_slot_original.substr(0, 10)})`
              + `\nMovida automaticamente para ${ticket.scheduled_time.substr(11, 5)} `
              + `porque o slot original estava cheio.`
            }>
              ⏰ era {ticket.atlaz_slot_original.substr(11, 5)}
            </span>
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
          }}>{fmtName(ticket.client_snapshot.name)}</div>
          <div style={{
            fontSize: 11, color: "#64748b", marginTop: 1,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {TYPE_LABELS[ticket.type]?.replace(/^\S+\s/, "") || ticket.type}
            {ticket.client_snapshot.neighborhood ? ` · ${safeText(ticket.client_snapshot.neighborhood)}` : ""}
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
            background: styleForQuality(ticket.live_signal.quality).bg,
            color: styleForQuality(ticket.live_signal.quality).fg,
            borderColor: styleForQuality(ticket.live_signal.quality).border,
          }}
        >
          {ticket.live_signal.rx_dbm != null ? `${ticket.live_signal.rx_dbm.toFixed(1)} dBm` : "—"}
          {ticket.live_signal.status === "Online" && <span style={{ fontSize: 8 }}></span>}
          {ticket.live_signal.status && ticket.live_signal.status !== "Online" && <span style={{ fontSize: 8 }}></span>}
        </div>
      )}

      {/* ISABELLA FIELD PRESIDENT (prioridade/risco/previsão na bolha) */}
      {ticket.isabella && (
        <div
          data-testid={`isabella-pill-${ticket.id}`}
          title={`Isabella · ${ticket.isabella.analysis || ""} · ${ticket.isabella.prediction || ""}`}
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            marginTop: 6, marginLeft: 4, padding: "2px 8px", borderRadius: 999,
            fontSize: 10, fontWeight: 800,
            border: "1px solid",
            background: ticket.isabella.risk === "alto" ? "#fef2f2"
              : ticket.isabella.risk === "medio" ? "#fffbeb" : "#f0fdf4",
            color: ticket.isabella.risk === "alto" ? "#b91c1c"
              : ticket.isabella.risk === "medio" ? "#b45309" : "#065f46",
            borderColor: ticket.isabella.risk === "alto" ? "#fecaca"
              : ticket.isabella.risk === "medio" ? "#fcd34d" : "#86efac",
          }}
        >
          ISA #{ticket.isabella.priority_rank} · {ticket.isabella.risk}
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
            >{ai.score.toFixed(1)}</span>
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
          {fmtDuration(ticket.duration_minutes)}
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
        <span style={{ position: "absolute", top: 8, right: 8, fontSize: 14, zIndex: 2 }}></span>
      )}
      {ticket.atlaz_external_id && (
        <span data-testid={`atlaz-badge-${ticket.id}`}
          style={{
            position: "absolute", bottom: 6, left: ticket.priority !== "normal" ? 12 : 8,
            fontSize: 9, fontWeight: 800, color: "#1e40af",
            background: "rgba(219,234,254,.95)", border: "1px solid #93c5fd",
            padding: "1px 6px", borderRadius: 999,
          }}>
          Atlaz
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
            style={btnSm("#8b5cf6")}>Detalhes</button>
          <button data-testid={`ai-evaluate-${ticket.id}`} disabled={aiBusy}
            onClick={runAiAnalysis} style={btnSm("#0d9488")}>IA {aiBusy ? "..." : ""}</button>
          <button data-testid={`admin-close-${ticket.id}`} disabled={busy}
            onClick={() => onAdminClose(ticket, "encerrar")}
            style={btnSm("#64748b")}>✓ Encerrar</button>
          <button data-testid={`admin-reschedule-${ticket.id}`} disabled={busy}
            onClick={(e) => { e.stopPropagation(); if (onReschedule) onReschedule(ticket); }} style={btnSm("#3b82f6")}>Reagendar</button>
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
          onReopened={() => { setShowDetails(false); window.location.reload(); }}
        />
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
              Qualidade do atendimento — Teste de Ping
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
                  ️ {tech.without_ping} sem ping
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
            Coaching automático — Ping skip
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
          {saving ? "Salvando..." : "Salvar"}
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
              Nenhum alerta nos últimos 30 dias 
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
              Qualidade dos fechamentos — IA
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
            {analyzing ? "Analisando..." : `Analisar (${data.totals.pending})`}
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
            Fechamentos suspeitos (score &lt; 50)
          </div>
          {(!data.low_score_tickets || data.low_score_tickets.length === 0) && (
            <div style={{ fontSize: 12, color: "#64748b" }}>
              Nada suspeito. Clique em “Analisar” se houver pendentes.
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
          Painel IA — Qualidade de Atendimento
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
  warning: { bg: "#fffbeb", color: "#92400e", hover: "#fef3c7", border: "#fcd34d" },
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
          {allSelected ? "Desmarcar todos" : "Marcar todos"}
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
        }}></span>
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
          Nenhum técnico bate com “{search}”
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
  busy, selectMode, selectedIds, onToggleSelect, onEmptySlotDblClick }) {
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
                    {r.type === "Entrada" ? "" : r.type === "Início intervalo" ? "️" : r.type === "Fim intervalo" ? "" : ""} {r.time}
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
              onEmptySlotDblClick={onEmptySlotDblClick}
            />
          ))}

          {/* "Sem horário" REMOVIDO (iter215): toda bolha cai num slot da grade. */}
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
            Encerrados (24h)
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {recentResolved.map((t) => (
              <div key={t.id}
                    data-testid={`recent-closed-chip-${t.id}`}
                    onClick={() => setClosedDetailTicket(
                      closedDetailTicket?.id === t.id ? null : t)}
                    title="Clique para ver os detalhes do fechamento — clique novamente ou fora pra fechar"
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
                    · {fmtDuration(t.duration_minutes)}
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
          onReopened={() => { setClosedDetailTicket(null); window.location.reload(); }}
        />
      )}
    </div>
  );
}

function TimelineSlot({ slot, isCurrentHour, techId, maxPerSlot, onSlotDrop, draggingId,
  onDragStart, onDragEnd, blinkOverdue, onAdminClose, onAdminOpen, onEdit, onReschedule,
  busy, selectMode, selectedIds, onToggleSelect, onEmptySlotDblClick }) {
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
      onDoubleClick={(e) => {
        if (isEmpty && onEmptySlotDblClick) {
          e.stopPropagation();
          onEmptySlotDblClick(techId, slot.slot);
        }
      }}
      title={isEmpty ? "Duplo clique pra criar Nova OS neste horário" : undefined}
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
          {tickets.length}/{maxPerSlot}{isFull && " "}
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



