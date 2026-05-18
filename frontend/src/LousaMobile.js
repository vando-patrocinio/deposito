import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Button, Icon } from "@/ui";
import QRScannerModal from "@/QRScannerModal";
import UberGpsPicker from "@/UberGpsPicker";
import AchievementsCard from "@/AchievementsCard";

/**
 * LousaMobile — vista da Lousa (bolhas) no app do colaborador.
 * Regras visuais:
 * - Lousa fica TRAVADA se: não bateu Entrada, está em intervalo, ou já bateu Saída.
 * - Bolhas com priority='horario'/'prioridade' têm cadeado (não dá para reordenar — futuro).
 * - Banner com último ponto registrado entre as bolhas.
 */
export default function LousaMobile({ collaboratorId, onBack }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [openTicket, setOpenTicket] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFlash, setRefreshFlash] = useState(false);
  const [reorderMode, setReorderMode] = useState(false);
  const [orderedIds, setOrderedIds] = useState([]);   // ordem local em modo reorder
  const [dragId, setDragId] = useState(null);
  const [dragOverId, setDragOverId] = useState(null);
  const [perf, setPerf] = useState(null);
  const [dashCfg, setDashCfg] = useState({
    show_performance: true, show_achievements: true,
    show_smart_route: true, show_points: true,
    enable_geofence_alerts: true,
  });

  const refresh = useCallback(async () => {
    if (!collaboratorId) return;
    setRefreshing(true);
    try {
      const d = await api.lousaByCollaborator(collaboratorId);
      setData(d);
      // Quando recarrega fora do modo reorder, sincroniza orderedIds
      if (!reorderMode) {
        setOrderedIds((d.tickets || []).map((t) => t.id));
      }
      setRefreshFlash(true);
      setTimeout(() => setRefreshFlash(false), 1200);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setRefreshing(false);
    }
  }, [collaboratorId, reorderMode]);

  useEffect(() => { refresh(); }, [refresh]);

  // Modo Boss — detecta novos chamados urgentes e alerta com beep + vibração
  const [seenUrgentIds, setSeenUrgentIds] = useState(() => new Set());
  useEffect(() => {
    if (!data?.tickets) return;
    const urgentes = data.tickets.filter(
      (t) => t.priority === "urgente"
              && t.status !== "finalizada" && !t.admin_resolved,
    );
    if (urgentes.length === 0) return;
    const newOnes = urgentes.filter((t) => !seenUrgentIds.has(t.id));
    if (newOnes.length === 0) return;
    // 1ª render: marca como já vistas sem alertar (evita spam ao abrir o app)
    if (seenUrgentIds.size === 0) {
      setSeenUrgentIds(new Set(urgentes.map((t) => t.id)));
      return;
    }
    // Beep + vibração
    try {
      // eslint-disable-next-line no-undef
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        const ctx = new AudioCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = "square"; osc.frequency.value = 880;
        gain.gain.value = 0.18;
        osc.start();
        setTimeout(() => { osc.frequency.value = 660; }, 180);
        setTimeout(() => { osc.stop(); ctx.close(); }, 420);
      }
      if (navigator.vibrate) navigator.vibrate([180, 90, 180, 90, 280]);
    } catch { /* silent */ }
    setSeenUrgentIds(new Set(urgentes.map((t) => t.id)));
  }, [data?.tickets, seenUrgentIds]);

  // Performance KPIs do dia
  useEffect(() => {
    if (!collaboratorId) return undefined;
    let alive = true;
    const load = () => {
      api._client.get(`/lousa/public/tech-performance/${collaboratorId}`)
        .then((r) => { if (alive) setPerf(r.data); })
        .catch(() => {});
    };
    load();
    const t = setInterval(load, 60000); // refresh a cada 1min
    return () => { alive = false; clearInterval(t); };
  }, [collaboratorId]);

  // Dashboard config (toggles do admin)
  useEffect(() => {
    if (!collaboratorId) return undefined;
    let alive = true;
    api._client.get(`/lousa/public/dashboard-config/${collaboratorId}`)
      .then((r) => { if (alive) setDashCfg((c) => ({ ...c, ...r.data })); })
      .catch(() => {});
    return () => { alive = false; };
  }, [collaboratorId]);

  // Geofence ping — envia posição a cada 60s (se admin habilitou)
  useEffect(() => {
    if (!collaboratorId) return undefined;
    if (!dashCfg.enable_geofence_alerts) return undefined;
    if (!navigator.geolocation) return undefined;
    let alive = true;
    const ping = () => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (!alive) return;
          api._client.post("/lousa/public/geofence-ping", {
            collaborator_id: collaboratorId,
            lat: pos.coords.latitude, lng: pos.coords.longitude,
          }).catch(() => {});
        },
        () => {},
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 30000 },
      );
    };
    ping();
    const t = setInterval(ping, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [collaboratorId, dashCfg.enable_geofence_alerts]);

  // --- Reorder helpers (modo "Reordenar") ---
  function isLockedTicket(t) {
    return t.reorder_locked || t.locked || t.priority !== "normal" || ["aberta", "aguardando_atendimento", "finalizada"].includes(t.status);
  }
  function moveTicket(ticketId, delta) {
    setOrderedIds((prev) => {
      const idx = prev.indexOf(ticketId);
      if (idx < 0) return prev;
      const targetIdx = idx + delta;
      if (targetIdx < 0 || targetIdx >= prev.length) return prev;
      // Não atravessar bolhas travadas
      const tickets = data?.tickets || [];
      const targetTicket = tickets.find((t) => t.id === prev[targetIdx]);
      if (!targetTicket || isLockedTicket(targetTicket)) return prev;
      const next = [...prev];
      [next[idx], next[targetIdx]] = [next[targetIdx], next[idx]];
      return next;
    });
  }
  async function saveReorder() {
    if (!data || !orderedIds.length) return;
    setBusy(true); setErr("");
    try {
      const items = orderedIds.map((id, position) => ({ id, position }));
      await api.lousaPublicReorder(collaboratorId, items);
      setReorderMode(false);
      await refresh();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }
  function cancelReorder() {
    setReorderMode(false);
    setOrderedIds((data?.tickets || []).map((t) => t.id));
    setDragId(null); setDragOverId(null);
  }
  function enterReorder() {
    setOrderedIds((data?.tickets || []).map((t) => t.id));
    setReorderMode(true);
  }

  // --- Touch/Mouse drag handlers (HTML5 DnD) ---
  function handleDragStart(id) {
    if (!reorderMode) return;
    const t = (data?.tickets || []).find((x) => x.id === id);
    if (!t || isLockedTicket(t)) return;
    setDragId(id);
  }
  function handleDragOver(e, overId) {
    if (!reorderMode || !dragId || dragId === overId) return;
    e.preventDefault();
    setDragOverId(overId);
  }
  function handleDrop(overId) {
    if (!reorderMode || !dragId) return;
    setOrderedIds((prev) => {
      const fromIdx = prev.indexOf(dragId);
      const toIdx = prev.indexOf(overId);
      if (fromIdx < 0 || toIdx < 0) return prev;
      const targetTicket = (data?.tickets || []).find((t) => t.id === overId);
      if (!targetTicket || isLockedTicket(targetTicket)) return prev;
      const next = [...prev];
      const [moved] = next.splice(fromIdx, 1);
      next.splice(toIdx, 0, moved);
      return next;
    });
    setDragId(null); setDragOverId(null);
  }

  async function handleOpen(ticket) {
    if (ticket.locked) return;
    if (ticket.status === "aberta" || ticket.status === "aguardando_atendimento") {
      setOpenTicket(ticket);
      return;
    }
    setBusy(true); setErr("");
    try {
      await api.lousaPublicOpen(ticket.id, collaboratorId);
      await refresh();
      const fresh = await api.lousaTicket(ticket.id);
      setOpenTicket(fresh);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function handleFinalize(ticket, completionData, opts = {}) {
    setBusy(true); setErr("");
    try {
      const lat = await new Promise((res) => navigator.geolocation
        ? navigator.geolocation.getCurrentPosition(
            (p) => res({ lat: p.coords.latitude, lng: p.coords.longitude }),
            () => res({ lat: 0, lng: 0 }),
          )
        : res({ lat: 0, lng: 0 }));
      await api.lousaPublicFinalize(ticket.id, {
        collaborator_id: collaboratorId,
        completion_data: completionData,
        latitude: lat.lat, longitude: lat.lng,
        outcome: "sucesso",
        bad_signal_auth_id: opts.bad_signal_auth_id || null,
      });
      setOpenTicket(null);
      setBadSignalAuth(null);
      await refresh();
    } catch (e) {
      // Backend 403 com needs_bad_signal_auth → abre modal de espera
      const detail = e?.response?.data?.detail;
      if (e?.response?.status === 403
            && detail?.code === "needs_bad_signal_auth") {
        setBadSignalAuth({
          request_id: detail.request_id,
          threshold: detail.threshold,
          sinal: detail.sinal,
          ticket,
          completionData,
          status: "pending",
        });
        setErr("");
      } else {
        setErr(typeof detail === "string"
                ? detail
                : (detail?.message || e.message));
      }
    }
    setBusy(false);
  }

  // Threshold do bad-signal warning — busca da config CENTRAL_ONT
  // (admin pode ter mudado pra -25/-30 etc). Best-effort: -27 default.
  const [badSignalThreshold, setBadSignalThreshold] = useState(-27);
  useEffect(() => {
    let alive = true;
    api._client.get("/lousa/central-ont/settings")
      .then((r) => alive && setBadSignalThreshold(
        Number(r.data?.bad_signal_threshold ?? -27)))
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Estado: aguardando autorização do gestor pra fechar com sinal ruim
  const [badSignalAuth, setBadSignalAuth] = useState(null);
  // Poll: a cada 4s checa status da request
  useEffect(() => {
    if (!badSignalAuth?.request_id) return undefined;
    const t = setInterval(async () => {
      try {
        const r = await api._client.get(
          `/lousa/public/bad-signal-auth/${badSignalAuth.request_id}`,
        ).then((x) => x.data);
        if (r.status === "approved") {
          clearInterval(t);
          // Re-tenta o finalize com o auth id
          await handleFinalize(
            badSignalAuth.ticket,
            badSignalAuth.completionData,
            { bad_signal_auth_id: badSignalAuth.request_id },
          );
        } else if (r.status === "rejected" || r.status === "expired") {
          clearInterval(t);
          setBadSignalAuth((b) => b ? { ...b, status: r.status } : b);
        }
      } catch { /* silent */ }
    }, 4000);
    return () => clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [badSignalAuth?.request_id]);

  if (!data) {
    return (
      <div data-testid="lousa-loading" style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
        Carregando lousa...
      </div>
    );
  }

  if (openTicket) {
    return (
      <>
      <TicketDetail
        ticket={openTicket}
        onClose={() => setOpenTicket(null)}
        onFinalize={(cd) => handleFinalize(openTicket, cd)}
        badSignalThreshold={badSignalThreshold}
        onRefresh={async () => {
          try {
            const fresh = await api.lousaTicket(openTicket.id);
            setOpenTicket(fresh);
            await refresh();
          } catch (e) { setErr(e?.response?.data?.detail || e.message); }
        }}
        busy={busy}
        err={err}
      />
      {badSignalAuth && (
        <BadSignalAuthWaitModal
          state={badSignalAuth}
          onClose={() => setBadSignalAuth(null)}
        />
      )}
      </>
    );
  }

  const state = data.clock_state;
  const unlocked = data.lousa_unlocked;
  const records = state.records || [];
  const lastEvent = records.length ? records[records.length - 1] : null;

  // Bolhas só aparecem após bater Entrada (identificação no sistema)
  if (data.needs_clock_in) {
    return (
      <div data-testid="lousa-mobile-needs-clockin">
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button variant="soft" onClick={onBack} data-testid="lousa-back-btn">← Voltar</Button>
          <Button
            variant="soft"
            onClick={refresh}
            disabled={refreshing}
            data-testid="lousa-refresh-btn"
            style={{
              background: refreshFlash ? "#dcfce7" : refreshing ? "#fef9c3" : "#dbeafe",
              color: refreshFlash ? "#166534" : refreshing ? "#92400e" : "#1e40af",
              border: `1px solid ${refreshFlash ? "#86efac" : refreshing ? "#fde68a" : "#93c5fd"}`,
              transition: "background-color .25s",
            }}
          >
            {refreshing ? "⏳ Atualizando..." : refreshFlash ? "✓ Atualizado" : "🔄 Atualizar"}
          </Button>
        </div>
        <h2 style={{ marginTop: 14, marginBottom: 4 }}>📋 Lousa de Serviços</h2>
        <div style={{
          marginTop: 24, padding: 30, textAlign: "center",
          background: "linear-gradient(135deg, #fef3c7, #fde68a)",
          border: "2px dashed #f59e0b", borderRadius: 22,
        }}>
          <div style={{ fontSize: 60 }}>🔒</div>
          <h3 style={{ margin: "12px 0 4px", color: "#78350f" }}>Bata o ponto de Entrada</h3>
          <p style={{ color: "#92400e", fontSize: 13, lineHeight: 1.5 }}>
            Suas notas de serviço só serão liberadas após você se identificar no sistema com o ponto de Entrada.
          </p>
          <Button onClick={onBack} style={{ marginTop: 12 }} data-testid="go-clock-btn">
            Ir para Bater Ponto
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="lousa-mobile">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button variant="soft" onClick={onBack} data-testid="lousa-back-btn">← Voltar</Button>
        <Button
          variant="soft"
          onClick={refresh}
          disabled={busy || refreshing || reorderMode}
          data-testid="lousa-refresh-btn"
          style={{
            background: refreshFlash ? "#dcfce7" : refreshing ? "#fef9c3" : "#dbeafe",
            color: refreshFlash ? "#166534" : refreshing ? "#92400e" : "#1e40af",
            border: `1px solid ${refreshFlash ? "#86efac" : refreshing ? "#fde68a" : "#93c5fd"}`,
            transition: "background-color .25s",
          }}
        >
          {refreshing ? "⏳ Atualizando..." : refreshFlash ? "✓ Atualizado" : "🔄 Atualizar"}
        </Button>
        {!reorderMode && data.tickets.length > 1 && unlocked && (
          <Button
            variant="soft"
            onClick={enterReorder}
            disabled={busy}
            data-testid="lousa-reorder-toggle"
            style={{ background: "#ede9fe", color: "#5b21b6", border: "1px solid #c4b5fd", fontWeight: 700 }}
          >
            ↕ Reordenar
          </Button>
        )}
      </div>
      <h2 style={{ marginTop: 14, marginBottom: 4 }}>📋 Lousa de Serviços</h2>
      <p style={{ color: "#64748b", fontSize: 12, margin: 0 }}>
        {data.tickets.length} serviço(s) — {unlocked ? "🔓 lousa liberada" : "🔒 lousa travada"}
        {reorderMode && <span style={{ marginLeft: 8, color: "#5b21b6", fontWeight: 700 }}>· ↕ modo reordenar</span>}
      </p>

      {dashCfg.show_performance && <PerformanceCard perf={perf}
                                                          showPoints={dashCfg.show_points} />}
      {dashCfg.show_achievements && <AchievementsCard collaboratorId={collaboratorId} compact />}
      {dashCfg.show_smart_route && (
        <SmartRouteCard collaboratorId={collaboratorId} onApplied={refresh}
                         enabled={data.tickets.some((t) => t.priority === "normal")} />
      )}

      {reorderMode && (
        <div data-testid="lousa-reorder-bar" style={{
          marginTop: 12, padding: "10px 14px",
          background: "linear-gradient(90deg, #ede9fe, #ddd6fe)",
          border: "1px solid #c4b5fd", borderRadius: 14,
          display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap",
        }}>
          <div style={{ fontSize: 12, color: "#4c1d95", fontWeight: 600 }}>
            Use ↑/↓ ou arraste para reordenar. 🔒 indica bolhas travadas.
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <Button
              variant="soft"
              onClick={cancelReorder}
              disabled={busy}
              data-testid="lousa-reorder-cancel"
              style={{ background: "white", color: "#475569", border: "1px solid #cbd5e1" }}
            >Cancelar</Button>
            <Button
              onClick={saveReorder}
              disabled={busy}
              data-testid="lousa-reorder-save"
              style={{ background: "#7c3aed", color: "white", fontWeight: 700 }}
            >{busy ? "Salvando..." : "✓ Salvar"}</Button>
          </div>
        </div>
      )}

      {!state.has_entrada && data.clock_in_enabled !== false && (
        <Banner color="#fef3c7" border="#f59e0b" icon="⚠️" text="Bata o ponto de Entrada para liberar a lousa." />
      )}
      {state.in_intervalo && data.clock_in_enabled !== false && (
        <Banner color="#dbeafe" border="#3b82f6" icon="🍽️" text="Você está em intervalo de almoço. A lousa abrirá após Fim intervalo." />
      )}
      {state.ended_day && data.clock_in_enabled !== false && (
        <Banner color="#e0e7ff" border="#6366f1" icon="🏁" text="Você já bateu Saída. Boa noite!" />
      )}
      {lastEvent && state.has_entrada && !reorderMode && data.clock_in_enabled !== false && (
        <Banner color="#dcfce7" border="#10b981" icon="✓" text={`Último ponto: ${lastEvent.type} às ${lastEvent.time}`} />
      )}

      {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}

      <div style={{ marginTop: 14 }}>
        {data.tickets.length === 0 && (
          <div style={{ background: "white", border: "1px dashed #cbd5e1", borderRadius: 16, padding: 20, textAlign: "center", color: "#94a3b8" }}>
            Nenhuma nota atribuída ainda.
          </div>
        )}
        {(reorderMode
          ? orderedIds.map((id) => data.tickets.find((t) => t.id === id)).filter(Boolean)
          : data.tickets
        ).map((t, idx, arr) => (
          <React.Fragment key={t.id}>
            {idx > 0 && lastEvent && idx === Math.floor(arr.length / 2) && !reorderMode && (
              <BetweenBubblesInfo records={records} />
            )}
            <Bubble
              ticket={t}
              onClick={() => handleOpen(t)}
              disabled={busy}
              reorderMode={reorderMode}
              isFirst={idx === 0}
              isLast={idx === arr.length - 1}
              locked={isLockedTicket(t)}
              onMoveUp={() => moveTicket(t.id, -1)}
              onMoveDown={() => moveTicket(t.id, 1)}
              isDragging={dragId === t.id}
              isDragOver={dragOverId === t.id}
              onDragStart={() => handleDragStart(t.id)}
              onDragOver={(e) => handleDragOver(e, t.id)}
              onDrop={() => handleDrop(t.id)}
              onDragEnd={() => { setDragId(null); setDragOverId(null); }}
            />
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

function Banner({ color, border, icon, text }) {
  return (
    <div style={{
      background: color, border: `1px solid ${border}`, borderRadius: 14,
      padding: "10px 14px", marginTop: 12, display: "flex", gap: 10, alignItems: "center",
      fontSize: 13, fontWeight: 600,
    }}>
      <span style={{ fontSize: 18 }}>{icon}</span>
      <span>{text}</span>
    </div>
  );
}

function BetweenBubblesInfo({ records }) {
  return (
    <div data-testid="lousa-records-strip" style={{
      margin: "8px 0", padding: "8px 12px",
      background: "linear-gradient(90deg, #f1f5f9, #e2e8f0)",
      borderRadius: 12, fontSize: 11, color: "#475569",
      display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center",
    }}>
      {records.map((r, i) => (
        <span key={i} style={{ background: "white", padding: "2px 8px", borderRadius: 8, border: "1px solid #cbd5e1" }}>
          {r.type === "Entrada" ? "🚪" : r.type === "Início intervalo" ? "🍽️" : r.type === "Fim intervalo" ? "🔄" : "🏁"} {r.time}
        </span>
      ))}
    </div>
  );
}

const TYPE_ICONS_M = {
  instalacao: "🔧", retirada: "📦", visita_tecnica: "🛠️", manutencao: "🔩",
  upgrade: "⬆️", downgrade: "⬇️", troca_endereco: "🏠",
  troca_titularidade: "👤", cancelamento: "🚫", outros: "📋", venda: "💼",
};

function Bubble({ ticket, onClick, disabled, reorderMode, isFirst, isLast, locked,
                 onMoveUp, onMoveDown, isDragging, isDragOver,
                 onDragStart, onDragOver, onDrop, onDragEnd }) {
  const isResolved = ticket.admin_resolved || ticket.status === "finalizada";
  const isOpen = ticket.status === "aberta" || ticket.status === "aguardando_atendimento";
  const priorityColors = {
    urgente: {
      bg: "linear-gradient(135deg,#fee2e2,#fecaca)",
      accent: "#dc2626", border: "#dc2626", text: "#7f1d1d",
      label: "URGENTE · BOSS", icon: "🚨",
    },
    prioridade: {
      bg: "linear-gradient(135deg,#fff5f5,#ffe4e6)",
      accent: "#e11d48", border: "#fecdd3", text: "#9f1239",
      label: "PRIORIDADE", icon: "🚨",
    },
    horario: {
      bg: "linear-gradient(135deg,#fffbeb,#fef3c7)",
      accent: "#d97706", border: "#fde68a", text: "#78350f",
      label: "HORÁRIO", icon: "⏰",
    },
    normal: {
      bg: "white", accent: "#0ea5e9", border: "#e2e8f0",
      text: "#0f172a", label: "", icon: "",
    },
  };
  const c = priorityColors[ticket.priority] || priorityColors.normal;
  const opacity = ticket.locked || disabled ? 0.55 : 1;
  const typeIcon = TYPE_ICONS_M[ticket.type] || "📋";
  const typeLabel = (ticket.type || "").replace(/_/g, " ");
  const tooltipText = [
    `${typeLabel.toUpperCase()}`,
    `Cliente: ${ticket.client_snapshot.name}`,
    ticket.client_snapshot.phone ? `Tel: ${ticket.client_snapshot.phone}` : null,
    ticket.client_snapshot.address ? `End.: ${ticket.client_snapshot.address}` : null,
    ticket.client_snapshot.neighborhood ? `Bairro: ${ticket.client_snapshot.neighborhood}` : null,
    ticket.scheduled_time ? `Horário: ${ticket.scheduled_time.substr(11, 5)}` : null,
    ticket.client_snapshot.relato ? `\nRelato:\n${ticket.client_snapshot.relato}` : null,
  ].filter(Boolean).join("\n");

  // Em modo reorder, a bolha vira um container drag-handle (não clica para abrir)
  if (reorderMode) {
    const draggableHere = !locked;
    return (
      <div
        data-testid={`bubble-reorder-${ticket.id}`}
        draggable={draggableHere}
        onDragStart={draggableHere ? onDragStart : undefined}
        onDragOver={onDragOver}
        onDrop={onDrop}
        onDragEnd={onDragEnd}
        style={{
          width: "100%", padding: 12, borderRadius: 22,
          background: isDragOver ? "#ede9fe" : (isOpen ? "#dcfce7" : c.bg),
          border: `2px ${isDragging ? "dashed" : "solid"} ${isDragOver ? "#7c3aed" : (isOpen ? "#10b981" : c.border)}`,
          marginBottom: 10,
          cursor: draggableHere ? "grab" : "not-allowed",
          opacity: isDragging ? 0.55 : opacity,
          color: c.text, position: "relative",
          boxShadow: isDragOver ? "0 8px 22px rgba(124,58,237,.25)" : "0 4px 10px rgba(15,23,42,.05)",
          touchAction: "none",
          display: "flex", gap: 10, alignItems: "center",
          transition: "all 0.18s",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4, flexShrink: 0 }}>
          <button
            data-testid={`bubble-up-${ticket.id}`}
            onClick={onMoveUp}
            disabled={isFirst || locked}
            title="Mover para cima"
            style={reorderBtnStyle(isFirst || locked)}
          >▲</button>
          <button
            data-testid={`bubble-down-${ticket.id}`}
            onClick={onMoveDown}
            disabled={isLast || locked}
            title="Mover para baixo"
            style={reorderBtnStyle(isLast || locked)}
          >▼</button>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {locked ? (
            <span style={{ position: "absolute", top: 8, right: 10, fontSize: 16 }} title="Bolha travada — não pode ser movida">🔒</span>
          ) : (
            <span style={{ position: "absolute", top: 8, right: 10, fontSize: 14, color: "#94a3b8" }} title="Arraste para reordenar">⋮⋮</span>
          )}
          {c.label && (
            <div style={{
              fontSize: 9, fontWeight: 900, letterSpacing: 0.5, marginBottom: 4,
              padding: "2px 7px", borderRadius: 999, background: c.accent, color: "white",
              display: "inline-block",
            }}>{c.icon} {c.label}</div>
          )}
          <div style={{ fontSize: 14, fontWeight: 800 }}>{ticket.client_snapshot.name}</div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            {ticket.type.toUpperCase()} · {ticket.client_snapshot.neighborhood}
          </div>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={onClick}
      disabled={ticket.locked || disabled || isResolved}
      data-testid={`bubble-${ticket.id}`}
      title={tooltipText}
      style={{
        width: "100%", textAlign: "left",
        padding: "12px 14px 12px 16px",
        borderRadius: 18,
        background: isOpen ? "linear-gradient(135deg,#ecfdf5,#d1fae5)" : c.bg,
        border: `${ticket.priority === "urgente" ? 2 : 1}px solid ${isOpen ? "#10b981" : c.border}`,
        marginBottom: 10,
        cursor: ticket.locked || isResolved ? "not-allowed" : "pointer",
        opacity, color: c.text, position: "relative",
        boxShadow: isOpen
          ? "0 6px 18px rgba(16,185,129,.20)"
          : (ticket.priority === "urgente"
              ? "0 0 0 4px rgba(220,38,38,0.18), 0 8px 22px rgba(220,38,38,.30)"
              : "0 1px 3px rgba(15,23,42,.06), 0 2px 6px rgba(15,23,42,.04)"),
        transition: "transform .15s, box-shadow .2s",
        overflow: "hidden",
        animation: (ticket.priority === "urgente" && !isResolved)
          ? "boss-mode-pulse 1.6s ease-in-out infinite" : "none",
      }}
    >
      {/* Faixa lateral colorida */}
      {ticket.priority !== "normal" && (
        <span aria-hidden style={{
          position: "absolute", left: 0, top: 0, bottom: 0,
          width: 5, background: c.accent, borderRadius: "18px 0 0 18px",
        }} />
      )}

      {ticket.locked && !isOpen && (
        <span style={{ position: "absolute", top: 10, right: 12, fontSize: 18 }}>🔒</span>
      )}

      {/* Header: badge + horário */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
        {c.label && (
          <span style={{
            fontSize: 9, fontWeight: 900, letterSpacing: 0.5,
            padding: "2px 8px", borderRadius: 999,
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

      {/* Body: ícone tipo + cliente + meta */}
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <div aria-hidden style={{
          width: 40, height: 40, borderRadius: 12,
          background: ticket.priority === "normal" ? "#f1f5f9" : "rgba(255,255,255,.85)",
          border: `1px solid ${c.border}`,
          display: "grid", placeItems: "center",
          fontSize: 20, flexShrink: 0,
        }}>{typeIcon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 14.5, fontWeight: 800, lineHeight: 1.2,
            color: c.text, letterSpacing: -0.1,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>{ticket.client_snapshot.name}</div>
          <div style={{
            fontSize: 11, color: "#64748b", marginTop: 2,
            textTransform: "uppercase", letterSpacing: 0.4,
            fontWeight: 700,
          }}>{typeLabel}</div>
          {ticket.client_snapshot.neighborhood && (
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 1 }}>
              📍 {ticket.client_snapshot.neighborhood}
            </div>
          )}
        </div>
      </div>

      {/* SINAL SMARTOLT (pill compacto) */}
      {ticket.live_signal && (
        <div
          data-testid={`signal-pill-mobile-${ticket.id}`}
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            marginTop: 6, padding: "3px 9px", borderRadius: 999,
            fontSize: 11, fontWeight: 800, fontFamily: "monospace",
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
          {ticket.live_signal.status === "Online" ? "🟢" : ticket.live_signal.status ? "🔴" : ""}
        </div>
      )}

      {/* Relato em footer separado */}
      {ticket.client_snapshot.relato && (
        <div style={{
          fontSize: 11.5, color: "#475569", marginTop: 8,
          paddingTop: 6, borderTop: "1px dashed rgba(15,23,42,.08)",
          lineHeight: 1.4,
        }}>
          {ticket.client_snapshot.relato.substring(0, 90)}
          {ticket.client_snapshot.relato.length > 90 ? "…" : ""}
        </div>
      )}

      {isResolved && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#16a34a", fontWeight: 700 }}>
          ✓ {ticket.status === "finalizada" ? "Finalizada" : ticket.admin_action || "Encerrada"}
        </div>
      )}
      {isOpen && (
        <div style={{
          marginTop: 8, fontSize: 11, color: "#065f46", fontWeight: 800,
          letterSpacing: 0.4, textTransform: "uppercase",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: "50%", background: "#10b981",
            boxShadow: "0 0 0 3px rgba(16,185,129,.25)",
            animation: "pulse 1.6s ease-in-out infinite",
          }} />
          Em andamento — toque para detalhes
        </div>
      )}
    </button>
  );
}


function SmartRouteCard({ collaboratorId, enabled, onApplied }) {
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");

  async function fetchOptimized(apply) {
    if (!enabled || !collaboratorId) return;
    setError("");
    setBusy(true);
    try {
      const pos = await new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
          reject(new Error("Geolocalização não disponível neste dispositivo."));
          return;
        }
        navigator.geolocation.getCurrentPosition(
          (p) => resolve(p),
          (e) => reject(new Error(e.message || "Permissão negada")),
          { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
        );
      });
      const { latitude, longitude } = pos.coords;
      const r = await api._client.post(
        "/lousa/public/optimize-route",
        {
          collaborator_id: collaboratorId,
          current_lat: latitude, current_lng: longitude,
          apply: !!apply,
        },
      ).then((x) => x.data);
      setPreview(r);
      if (apply && r.applied && onApplied) onApplied();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="smart-route-card" style={{
      marginTop: 12, padding: "10px 12px", borderRadius: 12,
      background: preview?.ok
        ? "#ecfeff"
        : (enabled ? "#fff7ed" : "#f1f5f9"),
      border: "1px dashed " + (preview?.ok ? "#06b6d4"
                                : (enabled ? "#fb923c" : "#cbd5e1")),
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 22 }}>🗺️</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 800,
                          color: preview?.ok ? "#0e7490" : "#9a3412" }}>
            {preview?.ok
              ? `Rota otimizada: ${preview.total_km}km · ${preview.stops} paradas`
              : "Otimizar rota com IA"}
          </div>
          <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>
            {preview?.ok
              ? `≈ ${preview.estimated_minutes}min total · ${preview.applied ? "✓ aplicada" : "pré-visualização"}`
              : (preview && preview.ok === false
                  ? preview.reason
                  : (enabled
                      ? "Calcula menor trajeto entre suas bolhas normais"
                      : "Sem bolhas reordenáveis no momento"))}
          </div>
        </div>
        {!preview?.ok && (
          <Button onClick={() => fetchOptimized(false)}
                   disabled={busy || !enabled}
                   data-testid="smart-route-preview-btn"
                   variant="primary"
                   style={{ padding: "6px 10px", fontSize: 12,
                              flexShrink: 0 }}>
            {busy ? "..." : "Calcular"}
          </Button>
        )}
        {preview?.ok && !preview.applied && (
          <Button onClick={() => fetchOptimized(true)}
                   disabled={busy}
                   data-testid="smart-route-apply-btn"
                   style={{ padding: "6px 10px", fontSize: 12,
                              flexShrink: 0,
                              background: "#06b6d4", color: "white" }}>
            {busy ? "..." : "Aplicar"}
          </Button>
        )}
      </div>
      {error && (
        <div data-testid="smart-route-error"
              style={{ marginTop: 6, fontSize: 11, color: "#b91c1c" }}>
          {error}
        </div>
      )}
      {preview?.ok && preview.optimized?.length > 0 && (
        <ol data-testid="smart-route-list" style={{
          marginTop: 8, marginBottom: 0, paddingLeft: 22,
          fontSize: 11, color: "#0f172a", lineHeight: 1.5,
        }}>
          {preview.optimized.map((stop, i) => (
            <li key={stop.id}>
              <strong>{stop.name || "Sem nome"}</strong>{" "}
              <span style={{ color: "#64748b" }}>
                · {stop.neighborhood || "—"} · {stop.distance_km}km
                {i === 0 ? " (próxima)" : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}


function PerformanceCard({ perf, showPoints = true }) {
  if (!perf) return null;
  const {
    closed_today, points_today, success_rate,
    avg_minutes, rank, total_techs, streak, badge,
  } = perf;

  // Cor do card por desempenho
  let cardBg = "linear-gradient(135deg,#0ea5e9 0%,#0284c7 100%)";
  if (rank === 1 && total_techs > 1) {
    cardBg = "linear-gradient(135deg,#f59e0b 0%,#d97706 100%)"; // ouro
  } else if (closed_today === 0) {
    cardBg = "linear-gradient(135deg,#64748b 0%,#475569 100%)"; // cinza
  } else if (success_rate === 100 && closed_today >= 3) {
    cardBg = "linear-gradient(135deg,#10b981 0%,#059669 100%)"; // verde
  }

  const Stat = ({ label, value, sub }) => (
    <div style={{ flex: 1, textAlign: "center", padding: "6px 4px" }}>
      <div style={{ fontSize: 22, fontWeight: 800, lineHeight: 1,
                      color: "white" }}>{value}</div>
      <div style={{ fontSize: 9, color: "rgba(255,255,255,0.85)",
                      textTransform: "uppercase", letterSpacing: 0.6,
                      fontWeight: 700, marginTop: 4 }}>{label}</div>
      {sub && (
        <div style={{ fontSize: 9, color: "rgba(255,255,255,0.65)",
                        marginTop: 2 }}>{sub}</div>
      )}
    </div>
  );

  return (
    <div data-testid="tech-performance-card" style={{
      marginTop: 12, padding: "12px 14px", borderRadius: 14,
      background: cardBg, color: "white",
      boxShadow: "0 6px 16px -8px rgba(15,23,42,.35)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5,
                        textTransform: "uppercase",
                        color: "rgba(255,255,255,0.85)" }}>
          📊 Seu desempenho hoje
        </div>
        <div data-testid="tech-perf-badge" style={{
          fontSize: 10, fontWeight: 800, padding: "3px 8px",
          borderRadius: 999, background: "rgba(255,255,255,0.2)",
          border: "1px solid rgba(255,255,255,0.3)",
        }}>{badge}</div>
      </div>
      <div style={{ display: "flex", gap: 4 }}>
        <Stat label="Fechadas" value={closed_today} />
        {showPoints && (
          <Stat label="Pontos" value={points_today ?? 0} />
        )}
        <Stat label="% sucesso" value={`${success_rate}%`} />
        <Stat label="Tempo médio"
               value={avg_minutes ? `${avg_minutes}min` : "—"} />
        <Stat
          label="Ranking"
          value={rank ? `${rank}º` : "—"}
          sub={total_techs ? `de ${total_techs}` : null}
        />
      </div>
      {streak >= 2 && (
        <div style={{
          marginTop: 8, padding: "4px 10px", borderRadius: 999,
          background: "rgba(255,255,255,0.18)", fontSize: 10,
          fontWeight: 700, display: "inline-block",
        }}>🔥 {streak} dia(s) consecutivos com fechamento</div>
      )}
    </div>
  );
}



function ConsumableField({ label, fieldKey, consumableId, step, consMap, form, setForm }) {
  const cur = consMap[consumableId];
  const used = Number(form[fieldKey]) || 0;
  const after = cur ? cur.qty - used : null;
  const insufficient = cur && used > cur.qty;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>{label}</label>
        {cur && (
          <span style={{ fontSize: 11, color: insufficient ? "#dc2626" : "#64748b", fontWeight: 600 }} data-testid={`bal-${consumableId}`}>
            📦 {cur.qty} {cur.unit}
            {used > 0 && (
              <span style={{ color: insufficient ? "#dc2626" : "#16a34a", marginLeft: 6 }}>
                → <strong>{after} {cur.unit}</strong>
              </span>
            )}
          </span>
        )}
      </div>
      <input
        data-testid={`finalize-${fieldKey}`}
        type="number" step={step || "1"} min="0"
        value={form[fieldKey]} onChange={(e) => setForm({ ...form, [fieldKey]: e.target.value })}
        style={{
          width: "100%", padding: "10px 12px",
          border: `1px solid ${insufficient ? "#fca5a5" : "#cbd5e1"}`,
          background: insufficient ? "#fef2f2" : "white",
          borderRadius: 10, fontSize: 14, boxSizing: "border-box",
        }}
      />
    </div>
  );
}

function TicketDetail({ ticket, onClose, onFinalize, busy, err, onRefresh,
                          badSignalThreshold = -27 }) {
  const [step, setStep] = useState(1); // 1: Sinal+ONT+Fotos · 2: Insumos+Obs
  // Default do sinal: pega do SmartOLT (live_signal.rx_dbm) se disponível,
  // senão usa -25 dBm (média típica de instalação saudável)
  const initialSinal = ticket?.live_signal?.rx_dbm != null
    ? Number(ticket.live_signal.rx_dbm.toFixed(1))
    : -25;
  const [form, setForm] = useState({
    sinal: initialSinal, qtd_drop: 1, esticadores: 1, conectores_fast: 2,
    cabo_rede: 10, conectores_rede: 2, ont: "", observacoes: "",
    fotos: [],          // [{kind:'equipamento'|'sn', dataUrl}]
  });
  // Marca se o valor atual ainda é o auto-preenchido do SmartOLT (mostra badge
  // "do SmartOLT"). Quando o usuário edita o input, vira false.
  const [sinalFromOlt, setSinalFromOlt] = useState(
    ticket?.live_signal?.rx_dbm != null,
  );

  // Sincroniza se o ticket atualizar (poll) e o usuário ainda não digitou
  React.useEffect(() => {
    if (sinalFromOlt && ticket?.live_signal?.rx_dbm != null) {
      setForm((f) => ({
        ...f,
        sinal: Number(ticket.live_signal.rx_dbm.toFixed(1)),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticket?.live_signal?.rx_dbm]);
  const [stock, setStock] = useState(null);
  const [macStatus, setMacStatus] = useState(null);
  const [macInfo, setMacInfo] = useState(null);
  const [showQR, setShowQR] = useState(false);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [ocrResult, setOcrResult] = useState(null);
  const [showPhotoWarn, setShowPhotoWarn] = useState(false);
  const [suggestBusy, setSuggestBusy] = useState(false);
  const [suggestResult, setSuggestResult] = useState(null);

  async function suggestSupplies() {
    try {
      setSuggestBusy(true);
      const r = await api._client.post(
        "/lousa/public/suggest-supplies",
        {
          ticket_id: ticket.id,
          type: ticket.type,
          neighborhood: ticket.client_snapshot?.neighborhood || null,
          company_id: ticket.company_id || null,
        },
      ).then((x) => x.data);
      setSuggestResult(r);
      setForm((f) => ({
        ...f,
        qtd_drop: r.qtd_drop,
        esticadores: r.esticadores,
        conectores_fast: r.conectores_fast,
        cabo_rede: r.cabo_rede,
        conectores_rede: r.conectores_rede,
      }));
    } catch (e) {
      alert("Sugestão falhou: " + (e?.response?.data?.detail || e.message));
    } finally {
      setSuggestBusy(false);
    }
  }

  const cid = ticket.assigned_collaborator_id;
  const isInstall = ticket.type === "instalacao" || ticket.type === "troca_endereco";
  const isWithdraw = ticket.type === "retirada";
  const needsMac = isInstall || isWithdraw;

  // Carrega estoque do técnico
  useEffect(() => {
    if (!cid) return;
    let alive = true;
    api.publicTechStock(cid).then((s) => { if (alive) setStock(s); }).catch(() => {});
    return () => { alive = false; };
  }, [cid]);

  // Validação MAC contra SmartOLT (debounce)
  useEffect(() => {
    if (!form.ont || form.ont.length < 6) {
      setMacStatus(null); setMacInfo(null); return;
    }
    setMacStatus("loading");
    const handle = setTimeout(async () => {
      try {
        const r = await api.publicValidateMac(form.ont, cid);
        setMacInfo(r);
        if (!r.found_smartolt) {
          setMacStatus("error"); // não existe na SmartOLT
        } else if (isInstall && !r.in_tech_stock) {
          setMacStatus("warn"); // existe mas não está no técnico → bloqueia auto-baixa
        } else if (isWithdraw && !r.in_client) {
          setMacStatus("warn"); // retirada precisa estar no cliente
        } else {
          setMacStatus("ok");
        }
      } catch {
        setMacStatus("error");
      }
    }, 600);
    return () => clearTimeout(handle);
  }, [form.ont, cid, isInstall, isWithdraw]);

  // ============ HELPERS Foto + OCR ============
  const requireEquipPhoto = isInstall || isWithdraw;
  const hasEquipPhoto = form.fotos.some((p) => p.kind === "equipamento");

  async function readFileAsDataURL(file) {
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = (e) => res(e.target.result);
      r.onerror = rej;
      r.readAsDataURL(file);
    });
  }

  async function addEquipPhoto(file) {
    try {
      const dataUrl = await readFileAsDataURL(file);
      setForm((f) => ({
        ...f,
        fotos: [
          ...f.fotos.filter((p) => p.kind !== "equipamento"),
          { kind: "equipamento", dataUrl },
        ],
      }));
    } catch (e) {
      alert("Falha ao ler foto: " + e.message);
    }
  }

  async function captureSnPhoto(file) {
    try {
      setOcrBusy(true);
      setOcrResult(null);
      const dataUrl = await readFileAsDataURL(file);
      // Salva foto também (kind=sn)
      setForm((f) => ({
        ...f,
        fotos: [...f.fotos.filter((p) => p.kind !== "sn"),
                 { kind: "sn", dataUrl }],
      }));
      const r = await api._client.post(
        "/lousa/public/ocr-sn",
        { image_base64: dataUrl, hint: "SN/MAC de ONT" },
      ).then((x) => x.data);
      setOcrResult(r);
      const detected = r.sn || r.mac || r.best;
      if (detected) {
        setForm((f) => ({ ...f, ont: detected.toUpperCase() }));
      }
    } catch (e) {
      alert("OCR falhou: " + (e?.response?.data?.detail || e.message));
    } finally {
      setOcrBusy(false);
    }
  }

  function goToStep2() {
    // Validação básica do step 1
    // INSTALAÇÃO: SN não é mais obrigatório aqui — provisionamento via Rede IA.
    if (isWithdraw && !form.ont) {
      alert("MAC da ONT retirada é obrigatório.");
      return;
    }
    if (requireEquipPhoto && !hasEquipPhoto) {
      setShowPhotoWarn(true);
      return;
    }
    setStep(2);
  }

  function submit() {
    if (needsMac && macStatus === "error") {
      if (!window.confirm("MAC não encontrado no SmartOLT. Continuar mesmo "
                            + "assim? (Marca erro_estoque pra revisão)")) return;
    }
    // Saldo
    const consMap = Object.fromEntries(
      (stock?.consumables || []).map((c) => [c.id, c.qty]));
    const checks = [
      ["drop", form.qtd_drop], ["esticador", form.esticadores],
      ["conector_fast", form.conectores_fast], ["cabo_rede", form.cabo_rede],
      ["conector_rede", form.conectores_rede],
    ];
    for (const [k, v] of checks) {
      const used = Number(v) || 0;
      if (used > (consMap[k] ?? Infinity)) {
        if (!window.confirm(`Saldo insuficiente de ${k} (disp ${consMap[k]}, `
                              + `gasto ${used}). Continuar? Vai ficar erro_estoque.`)) return;
        break;
      }
    }
    onFinalize({
      sinal: Number(form.sinal),
      qtd_drop: Number(form.qtd_drop),
      esticadores: Number(form.esticadores),
      conectores_fast: Number(form.conectores_fast),
      cabo_rede: Number(form.cabo_rede),
      conectores_rede: Number(form.conectores_rede),
      ont: form.ont || null,
      fotos: form.fotos.map((p) => p.dataUrl),
      observacoes: form.observacoes || null,
    });
  }

  const consMap = Object.fromEntries((stock?.consumables || []).map((c) => [c.id, c]));

  const macColors = {
    loading: { bg: "#dbeafe", color: "#1e40af", border: "#93c5fd", icon: "🔍", txt: "Validando…" },
    ok: { bg: "#dcfce7", color: "#166534", border: "#86efac", icon: "✓", txt: "Equipamento validado" },
    warn: { bg: "#fef3c7", color: "#92400e", border: "#fde68a", icon: "⚠", txt: "Não está no estoque correto" },
    error: { bg: "#fee2e2", color: "#991b1b", border: "#fca5a5", icon: "✕", txt: "MAC não encontrado no SmartOLT" },
  };
  const macStyle = macStatus ? macColors[macStatus] : null;

  return (
    <div data-testid="ticket-detail">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button variant="soft" onClick={onClose} data-testid="ticket-close-btn">← Voltar</Button>
        {onRefresh && (
          <Button variant="soft" onClick={onRefresh} data-testid="ticket-refresh-btn"
            style={{ background: "#dbeafe", color: "#1e40af", border: "1px solid #93c5fd" }}>🔄 Atualizar</Button>
        )}
      </div>

      {/* HEADER da nota */}
      <div style={{
        background: "linear-gradient(135deg,#0f172a 0%,#1e293b 100%)", color: "white",
        padding: 16, borderRadius: 14, marginTop: 14,
      }}>
        <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700, marginBottom: 4 }}>
          {ticket.type.toUpperCase()} · {ticket.priority}
        </div>
        <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>{ticket.client_snapshot.name}</div>
        <div style={{ fontSize: 12, color: "#cbd5e1", marginBottom: 8 }}>
          📍 {ticket.client_snapshot.address}{ticket.client_snapshot.neighborhood ? ` · ${ticket.client_snapshot.neighborhood}` : ""}
        </div>
        {ticket.client_snapshot.pppoe_user && (
          <PppoeChip pppoe={ticket.client_snapshot.pppoe_user} />
        )}
        {ticket.live_signal && (
          <>
            <div style={{ marginTop: 8, padding: "6px 10px", background: "rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}>
              📶 <strong>{ticket.live_signal.rx_dbm?.toFixed(1)} dBm</strong> · {ticket.live_signal.status} · {ticket.live_signal.olt_name}
            </div>
            {/* Bloco SmartOLT — porta OLT, VLAN, CTO, SN (pulled from SmartOLT) */}
            <SmartOltDetailBlock ls={ticket.live_signal} />
          </>
        )}
      </div>

      <div style={{
        background: "#f1f5f9", padding: 12, borderRadius: 12, marginTop: 12,
        fontSize: 13, lineHeight: 1.5, borderLeft: "3px solid #6366f1",
      }}>
        <strong>📝 Relato:</strong> {ticket.client_snapshot.relato}
      </div>

      <h3 style={{ marginTop: 18, marginBottom: 10, fontSize: 16, fontWeight: 800, color: "#0f172a" }}>📋 Finalizar serviço</h3>

      {/* Indicador de passos */}
      <div data-testid="finalize-steps"
            style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {[1, 2].map((n) => (
          <div key={n} style={{
            flex: 1, height: 6, borderRadius: 999,
            background: step >= n ? "#0ea5e9" : "#e2e8f0",
            transition: "background 200ms",
          }} />
        ))}
        <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                       letterSpacing: 0.5, textTransform: "uppercase",
                       marginLeft: 8, alignSelf: "center" }}>
          Etapa {step}/2
        </div>
      </div>

      {/* SINAL — step 1 */}
      {step === 1 && (
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 12, color: "#475569", fontWeight: 700,
                         display: "flex", alignItems: "center", gap: 6 }}>
          📶 Sinal medido (dBm)
          {sinalFromOlt && (
            <span data-testid="finalize-sinal-from-olt"
                   style={{
                     padding: "1px 7px", borderRadius: 999,
                     background: "linear-gradient(90deg,#0ea5e9,#06b6d4)",
                     color: "#fff", fontSize: 9, fontWeight: 700,
                     textTransform: "uppercase", letterSpacing: 0.4,
                   }}>SmartOLT</span>
          )}
        </label>
        <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
          <input data-testid="finalize-sinal" type="number" step="0.1" value={form.sinal}
            onChange={(e) => {
              setForm({ ...form, sinal: e.target.value });
              if (sinalFromOlt) setSinalFromOlt(false);
            }}
            style={{ flex: 1, padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 14, boxSizing: "border-box" }} />
          {ticket?.live_signal?.rx_dbm != null && !sinalFromOlt && (
            <button type="button"
                      onClick={() => {
                        setForm({ ...form,
                          sinal: Number(ticket.live_signal.rx_dbm.toFixed(1)) });
                        setSinalFromOlt(true);
                      }}
                      data-testid="finalize-sinal-refresh"
                      title="Usar sinal atual do SmartOLT"
                      style={{
                        padding: "10px 12px", border: "1px solid #06b6d4",
                        background: "#ecfeff", color: "#0e7490",
                        borderRadius: 10, fontSize: 11, fontWeight: 700,
                        cursor: "pointer", whiteSpace: "nowrap",
                      }}>
              ⟳ OLT
            </button>
          )}
        </div>
        {form.sinal !== "" && Number(form.sinal) < badSignalThreshold && (
          <div data-testid="finalize-bad-signal-warning"
                style={{
                  marginTop: 6, padding: "8px 10px", borderRadius: 8,
                  background: "#fef3c7", border: "1px solid #fde68a",
                  color: "#78350f", fontSize: 12, lineHeight: 1.4,
                  fontWeight: 600,
                }}>
            ⚠ Sinal abaixo de {badSignalThreshold} dBm. Se a Central proibir
            fechamento ruim, o gestor receberá um pedido de autorização ao você
            finalizar.
          </div>
        )}
        {ticket.live_signal?.sn && form.ont
            && form.ont.toUpperCase().replace(/:/g, "")
              !== ticket.live_signal.sn.toUpperCase().replace(/:/g, "") && (
          <div data-testid="finalize-sn-mismatch-warning"
                style={{
                  marginTop: 6, padding: "8px 10px", borderRadius: 8,
                  background: "#fef3c7", border: "1px solid #fde68a",
                  color: "#78350f", fontSize: 12, lineHeight: 1.4,
                  fontWeight: 600,
                }}>
            ⚠ O SN/MAC registrado na SmartOLT é
            <code style={{ background: "white", padding: "1px 4px",
                            borderRadius: 4, marginLeft: 4 }}>
              {ticket.live_signal.sn}
            </code>
            <br/>
            Você digitou <code style={{ background: "white",
                                            padding: "1px 4px",
                                            borderRadius: 4 }}>{form.ont}</code>.
            Confirma que trocou a ONT?
          </div>
        )}
      </div>
      )}

      {/* MAC ONT — step 1
          ATENÇÃO: para INSTALAÇÃO o cadastro de ONU agora é feito pela
          Rede IA → clicar na CTO no mapa → aba "Cadastrar novo cliente".
          Aqui só pedimos MAC pra RETIRADA (registrar qual ONT saiu do cliente). */}
      {step === 1 && isInstall && (
        <div data-testid="lousa-install-redirect"
              style={{
                marginBottom: 14, padding: 12,
                background: "linear-gradient(90deg,#eef2ff,#ede9fe)",
                border: "1px solid #c4b5fd", borderRadius: 10,
                color: "#5b21b6", fontSize: 12.5, lineHeight: 1.5,
              }}>
          <strong>🆕 Mudança de fluxo:</strong> o cadastro de ONU no SmartOLT
          agora é feito pelo gestor de rede direto na <strong>Rede IA →
          Mapa Interativo</strong>: clica na CTO e usa a aba "Cadastrar
          novo cliente". Aqui só registre a foto do equipamento e os
          insumos consumidos.
        </div>
      )}
      {step === 1 && isWithdraw && (
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
            📡 MAC/SN da ONT {isWithdraw ? "(retirada do cliente)" : "(do estoque do técnico)"} *
          </label>
          <div style={{ display: "flex", gap: 6, marginTop: 4, marginBottom: 6 }}>
            <input
              data-testid="finalize-ont"
              value={form.ont} onChange={(e) => setForm({ ...form, ont: e.target.value.trim().toUpperCase() })}
              placeholder="Ex.: ALCLFC090E99 ou AA:BB:CC:DD:EE:FF"
              style={{
                flex: 1, padding: "10px 12px",
                border: `1px solid ${macStyle?.border || "#cbd5e1"}`,
                borderRadius: 10, fontSize: 14,
                fontFamily: "monospace", textTransform: "uppercase", boxSizing: "border-box",
              }}
            />
            {/* Câmera OCR — foto da etiqueta preenche o MAC/SN */}
            <label data-testid="ocr-sn-btn"
                    title="Tirar foto da etiqueta (preenche o MAC/SN)"
                    style={{
                      padding: "10px 14px", border: "none", borderRadius: 10,
                      background: ocrBusy
                        ? "linear-gradient(135deg,#94a3b8,#64748b)"
                        : "linear-gradient(135deg,#10b981,#059669)",
                      color: "white", fontWeight: 800, fontSize: 16,
                      cursor: ocrBusy ? "wait" : "pointer", flexShrink: 0,
                      display: "inline-flex", alignItems: "center", gap: 3,
                    }}>
              {ocrBusy ? "⏳" : "📸"}
              <input type="file" accept="image/*" capture="environment"
                      style={{ display: "none" }}
                      disabled={ocrBusy}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) captureSnPhoto(f);
                        e.target.value = "";
                      }} />
            </label>
            <button
              type="button"
              data-testid="qr-open-btn"
              onClick={() => setShowQR(true)}
              title="Escanear código de barras/QR"
              style={{
                padding: "10px 14px", border: "none", borderRadius: 10,
                background: "linear-gradient(135deg,#0ea5e9,#2563eb)", color: "white",
                fontWeight: 800, fontSize: 16, cursor: "pointer", flexShrink: 0,
              }}
            >
              📷
            </button>
          </div>
          {ocrResult && (
            <div data-testid="ocr-result"
                  style={{
                    padding: "6px 10px", borderRadius: 8, marginBottom: 6,
                    background: ocrResult.best ? "#dcfce7" : "#fee2e2",
                    color: ocrResult.best ? "#166534" : "#991b1b",
                    fontSize: 11, lineHeight: 1.4, fontWeight: 600,
                  }}>
              {ocrResult.best
                ? `✓ Detectado: ${ocrResult.best} (confiança: ${ocrResult.confidence})`
                : "⚠ Nada legível na foto. Tente novamente com melhor luz."}
            </div>
          )}
          {macStyle && (
            <div data-testid="mac-validation" style={{
              padding: "8px 12px", borderRadius: 10, fontSize: 12,
              background: macStyle.bg, color: macStyle.color, fontWeight: 600,
              display: "flex", flexDirection: "column", gap: 4,
            }}>
              <div><strong>{macStyle.icon} {macStyle.txt}</strong></div>
              {macInfo?.smartolt && (
                <div style={{ fontSize: 11, fontFamily: "monospace" }}>
                  {macInfo.smartolt.name} · {macInfo.smartolt.olt_name} · sinal {macInfo.smartolt.signal_1490} dBm · {macInfo.smartolt.status}
                </div>
              )}
              {macInfo?.ont_record && (
                <div style={{ fontSize: 11 }}>
                  🏷 Estoque: {macInfo.ont_record.location_type === "tecnico" ? "no técnico" : macInfo.ont_record.location_type === "cliente" ? `cliente ${macInfo.ont_record.client_name || ""}` : macInfo.ont_record.location_type}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* FOTO DO EQUIPAMENTO — step 1, obrigatória em instalação/retirada */}
      {step === 1 && requireEquipPhoto && (
        <div data-testid="equip-photo-section" style={{
          padding: 12, borderRadius: 12,
          background: hasEquipPhoto ? "#dcfce7" : "#fef9c3",
          border: "1px solid " + (hasEquipPhoto ? "#16a34a" : "#fde68a"),
          marginBottom: 14,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginBottom: 8 }}>
            <strong style={{ fontSize: 13, color: hasEquipPhoto ? "#166534" : "#78350f" }}>
              📸 Foto do equipamento {hasEquipPhoto ? "✓" : "*"}
            </strong>
            <label style={{
              padding: "6px 12px", borderRadius: 8, fontSize: 11, fontWeight: 700,
              background: hasEquipPhoto ? "white" : "#0ea5e9",
              color: hasEquipPhoto ? "#0ea5e9" : "white",
              border: hasEquipPhoto ? "1px solid #0ea5e9" : "none",
              cursor: "pointer",
            }}>
              {hasEquipPhoto ? "Refazer" : "Tirar foto"}
              <input type="file" accept="image/*" capture="environment"
                      data-testid="equip-photo-input"
                      style={{ display: "none" }}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) addEquipPhoto(f);
                        e.target.value = "";
                      }} />
            </label>
          </div>
          <p style={{ margin: 0, fontSize: 11,
                       color: hasEquipPhoto ? "#15803d" : "#92400e",
                       lineHeight: 1.4 }}>
            {hasEquipPhoto
              ? "Foto registrada. Pode refazer se precisar."
              : (isWithdraw
                  ? "Tire uma foto do equipamento retirado antes de prosseguir."
                  : "Tire uma foto do equipamento instalado antes de prosseguir.")}
          </p>
          {hasEquipPhoto && (
            <img alt="Equipamento"
                  src={form.fotos.find((p) => p.kind === "equipamento")?.dataUrl}
                  style={{ marginTop: 8, width: 96, height: 96,
                             objectFit: "cover", borderRadius: 8,
                             border: "1px solid #16a34a" }} />
          )}
        </div>
      )}

      {/* Step 1 → botão Próximo */}
      {step === 1 && (
        <Button onClick={goToStep2}
                 data-testid="finalize-next-btn"
                 style={{ width: "100%", marginTop: 6, height: 52, fontSize: 15 }}>
          Próximo: Materiais e Observações →
        </Button>
      )}

      {/* ============ STEP 2 ============ */}
      {step === 2 && (
        <>
          {/* SUGESTÃO IA — insumos baseados em histórico */}
          <div data-testid="suggest-supplies-card" style={{
            padding: "10px 12px", borderRadius: 12, marginBottom: 12,
            background: suggestResult ? "#ecfdf5" : "#eff6ff",
            border: "1px dashed " + (suggestResult ? "#10b981" : "#3b82f6"),
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <span style={{ fontSize: 22 }}>📦</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 800,
                              color: suggestResult ? "#065f46" : "#1e40af" }}>
                {suggestResult ? "Insumos sugeridos aplicados" : "Sugerir insumos com IA"}
              </div>
              <div style={{ fontSize: 10, color: "#475569", marginTop: 2,
                              lineHeight: 1.3 }}>
                {suggestResult
                  ? suggestResult.rationale
                  : "Pré-preenche baseado em chamados similares do bairro."}
              </div>
            </div>
            <Button onClick={suggestSupplies} disabled={suggestBusy}
                     data-testid="suggest-supplies-btn"
                     variant={suggestResult ? "soft" : "primary"}
                     style={{ padding: "8px 12px", fontSize: 12,
                                flexShrink: 0 }}>
              {suggestBusy ? "..." : (suggestResult ? "Refazer" : "Sugerir")}
            </Button>
          </div>

          {/* INSUMOS FTTH */}
          <div style={{
            padding: "12px 14px", background: "white",
            border: "1px solid #fde68a", borderRadius: 14, marginBottom: 12,
          }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: "#ca8a04",
                            marginBottom: 8, letterSpacing: 0.5,
                            textTransform: "uppercase" }}>
              🌐 Insumo FTTH
              {stock && (
                <span style={{ fontSize: 10, color: "#64748b",
                                 fontWeight: 500, marginLeft: 6,
                                 textTransform: "none", letterSpacing: 0 }}>
                  · estoque: {stock.collaborator_name}
                </span>
              )}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <ConsumableField label="Drop (m)" fieldKey="qtd_drop"
                                consumableId="drop" consMap={consMap}
                                form={form} setForm={setForm} />
              <ConsumableField label="Esticador (un)" fieldKey="esticadores"
                                consumableId="esticador" consMap={consMap}
                                form={form} setForm={setForm} />
              <ConsumableField label="Conector fast (un)" fieldKey="conectores_fast"
                                consumableId="conector_fast" consMap={consMap}
                                form={form} setForm={setForm} />
            </div>
          </div>

          {/* INSUMOS REDE */}
          <div style={{
            padding: "12px 14px", background: "white",
            border: "1px solid #bfdbfe", borderRadius: 14, marginBottom: 12,
          }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: "#1d4ed8",
                            marginBottom: 8, letterSpacing: 0.5,
                            textTransform: "uppercase" }}>
              🖧 Rede
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <ConsumableField label="Cabo rede (m)" fieldKey="cabo_rede"
                                consumableId="cabo_rede" step="0.5"
                                consMap={consMap}
                                form={form} setForm={setForm} />
              <ConsumableField label="Conector rede (un)" fieldKey="conectores_rede"
                                consumableId="conector_rede" consMap={consMap}
                                form={form} setForm={setForm} />
            </div>
          </div>

          <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
            📝 Observações
          </label>
          <textarea
            data-testid="finalize-obs" value={form.observacoes}
            onChange={(e) => setForm({ ...form, observacoes: e.target.value })}
            rows={3}
            placeholder="Detalhes do serviço, materiais especiais, etc."
            style={{
              width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1",
              borderRadius: 10, fontSize: 14, marginTop: 4, marginBottom: 12,
              resize: "vertical", boxSizing: "border-box", fontFamily: "inherit",
            }}
          />

          {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}

          <div style={{ display: "flex", gap: 8 }}>
            <Button onClick={() => setStep(1)} variant="soft"
                     data-testid="finalize-back-btn"
                     style={{ flex: 1, height: 52, fontSize: 14 }}>
              ← Voltar
            </Button>
            <Button onClick={submit} disabled={busy}
                     data-testid="finalize-btn"
                     style={{ flex: 2, height: 52, fontSize: 15 }}>
              <Icon name="check" /> {busy ? "Finalizando..." : "Finalizar nota"}
            </Button>
          </div>
        </>
      )}

      {/* POPUP — força a tirar foto do equipamento antes de avançar */}
      {showPhotoWarn && (
        <div onClick={() => setShowPhotoWarn(false)}
              data-testid="photo-required-modal"
              style={{
                position: "fixed", inset: 0, zIndex: 1400,
                background: "rgba(2,6,23,0.7)",
                display: "grid", placeItems: "center", padding: 18,
              }}>
          <div onClick={(e) => e.stopPropagation()}
                style={{
                  background: "white", borderRadius: 14, padding: 22,
                  maxWidth: 360, width: "100%", textAlign: "center",
                  boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
                }}>
            <div style={{ fontSize: 38, marginBottom: 8 }}>📸</div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700,
                          color: "#0f172a" }}>
              Tire uma foto do equipamento
            </h3>
            <p style={{ margin: "8px 0 16px", fontSize: 12, color: "#475569",
                         lineHeight: 1.5 }}>
              É obrigatório registrar o equipamento antes de continuar.
              Use a câmera traseira do celular pra capturar.
            </p>
            <label style={{
              display: "inline-block", padding: "12px 22px", borderRadius: 10,
              background: "#0ea5e9", color: "white", fontWeight: 800,
              fontSize: 14, cursor: "pointer",
            }}>
              📷 Abrir câmera agora
              <input type="file" accept="image/*" capture="environment"
                      data-testid="photo-required-input"
                      style={{ display: "none" }}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) {
                          addEquipPhoto(f);
                          setShowPhotoWarn(false);
                        }
                        e.target.value = "";
                      }} />
            </label>
          </div>
        </div>
      )}

      {showQR && (
        <QRScannerModal
          onClose={() => setShowQR(false)}
          onScan={(text) => {
            // Normaliza: maiúsculas + remove espaços, mantém alfanum + ":"
            const cleaned = (text || "").trim().toUpperCase().replace(/[^A-Z0-9:]/g, "");
            setForm((f) => ({ ...f, ont: cleaned }));
            setShowQR(false);
          }}
        />
      )}
    </div>
  );
}

function reorderBtnStyle(disabled) {
  return {
    width: 32, height: 28, border: "1px solid #c4b5fd",
    background: disabled ? "#f1f5f9" : "white",
    color: disabled ? "#cbd5e1" : "#5b21b6",
    borderRadius: 8, fontSize: 12, fontWeight: 700,
    cursor: disabled ? "not-allowed" : "pointer",
    display: "grid", placeItems: "center",
    boxShadow: "0 1px 2px rgba(15,23,42,.05)",
  };
}

/* Modal: técnico aguardando autorização do gestor pra fechar com sinal ruim */
function BadSignalAuthWaitModal({ state, onClose }) {
  const isPending = state.status === "pending";
  const isRejected = state.status === "rejected";
  const isExpired = state.status === "expired";
  return (
    <div data-testid="bad-signal-auth-wait-modal"
          style={{
            position: "fixed", inset: 0, zIndex: 1500,
            background: "rgba(2,6,23,0.85)",
            display: "grid", placeItems: "center", padding: 18,
          }}>
      <div style={{
        background: "white", borderRadius: 14, padding: 22,
        maxWidth: 380, width: "100%", textAlign: "center",
        boxShadow: "0 25px 60px rgba(0,0,0,0.4)",
      }}>
        <div style={{
          width: 64, height: 64, borderRadius: "50%", margin: "0 auto 14px",
          background: isPending ? "#fef9c3" : isRejected ? "#fee2e2" : "#fef3c7",
          color: isPending ? "#ca8a04" : isRejected ? "#dc2626" : "#92400e",
          display: "grid", placeItems: "center",
          fontSize: 30,
          animation: isPending ? "wa-pulse 2s ease infinite" : "none",
        }}>
          {isPending ? "⏳" : isRejected ? "✗" : "⌛"}
        </div>
        <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700,
                      color: "#0f172a" }}>
          {isPending && "Aguardando autorização"}
          {isRejected && "Pedido rejeitado"}
          {isExpired && "Pedido expirou"}
        </h3>
        <p style={{ margin: "8px 0 16px", fontSize: 13, color: "#475569",
                     lineHeight: 1.5 }}>
          {isPending && (
            <>Você está fechando com <strong style={{ color: "#dc2626" }}>
              {state.sinal?.toFixed(1)} dBm</strong> (limite {state.threshold}).
              <br/>O gestor foi notificado — aguarde a aprovação.</>
          )}
          {isRejected && (
            <>O gestor negou o fechamento com este sinal.<br/>
            Melhore o sinal e tente novamente.</>
          )}
          {isExpired && (
            <>O pedido passou de 30 minutos sem decisão.<br/>
            Faça uma nova tentativa.</>
          )}
        </p>
        <button onClick={onClose}
                 data-testid="bad-signal-auth-close-btn"
                 style={{
                   padding: "10px 24px", borderRadius: 8,
                   border: "1.5px solid #cbd5e1", background: "white",
                   color: "#475569", fontWeight: 700, fontSize: 13,
                   cursor: "pointer",
                 }}>
          Fechar
        </button>
      </div>
      <style>{`
        @keyframes wa-pulse {
          0%,100% { transform: scale(1); }
          50% { transform: scale(1.08); }
        }
      `}</style>
    </div>
  );
}

/* PPPoE chip — clique copia pro clipboard com flash verde "✓ copiado" */
function PppoeChip({ pppoe }) {
  const [copied, setCopied] = React.useState(false);
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(pppoe);
    } catch {
      // fallback: createElement textarea + execCommand (já obsoleto mas funciona em http)
      const ta = document.createElement("textarea");
      ta.value = pppoe; document.body.appendChild(ta);
      ta.select(); try { document.execCommand("copy"); } catch {}
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };
  return (
    <button onClick={onClick} data-testid="lousa-pppoe-copy"
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              border: "none", cursor: "pointer", padding: "4px 10px",
              borderRadius: 999, fontSize: 11, fontFamily: "monospace",
              fontWeight: 700, marginBottom: 4,
              background: copied ? "#16a34a" : "rgba(165,180,252,0.15)",
              color: copied ? "white" : "#a5b4fc",
              transition: "background 180ms, color 180ms",
            }}
            title="Toque pra copiar">
      {copied ? "✓ Copiado!" : <>🔑 {pppoe}</>}
    </button>
  );
}

/* Bloco com dados puxados da SmartOLT — Porta OLT, VLAN, CTO, SN.
   Cada item só renderiza se houver dado. Cor azul-acinzentada pra
   diferenciar das infos do cliente (azul-índigo do PPPoE). */
function SmartOltDetailBlock({ ls }) {
  const [showGpsPicker, setShowGpsPicker] = React.useState(false);
  const [savingGps, setSavingGps] = React.useState(false);
  const [gpsMsg, setGpsMsg] = React.useState(null);
  const [pushBusy, setPushBusy] = React.useState(false);

  if (!ls) return null;
  const items = [
    { label: "PORTA OLT", value: ls.olt_port, hint: `ONU #${ls.onu || "?"}` },
    { label: "VLAN", value: ls.vlan },
    { label: "CTO", value: ls.cto_box },
    { label: "PORTA CTO", value: ls.cto_port },
    { label: "ONLINE HÁ", value: ls.uptime_human, mono: false },
    { label: "SN", value: ls.sn, mono: true },
  ].filter((i) => i.value);
  if (items.length === 0) return null;

  // Tenta achar o `cto_id` via ls.cto_id ou ls.cto_box (alguns sidecars
  // só retornam o nome). Se vier só nome, busca lazy no clique.
  const ctoId = ls.cto_id;
  const ctoBox = ls.cto_box;
  const initialGps = ls.cto_gps || ls.gps || null;

  const saveLocation = async ({ lat, lng, address }) => {
    setSavingGps(true); setGpsMsg(null);
    try {
      let resolvedId = ctoId;
      if (!resolvedId && ctoBox) {
        // Resolve por nome
        try {
          const r = await api._client.get(
            `/rede-ia/ctos?bairro=&q=${encodeURIComponent(ctoBox)}`,
          ).then((x) => x.data);
          const items = r.items || [];
          const hit = items.find((c) => c.name === ctoBox)
            || items[0];
          resolvedId = hit?.id;
        } catch { /* ignore */ }
      }
      if (!resolvedId) {
        setGpsMsg({ kind: "err", text: "CTO não encontrada no cadastro." });
        return;
      }
      const addrPayload = address ? {
        rua: address.rua, numero: address.numero,
        bairro: address.bairro, cidade: address.cidade,
        estado: address.estado, cep: address.cep,
      } : null;
      await api.redeIaCtoLocationUpdate(resolvedId, {
        lat, lng, address: addrPayload,
      });
      setGpsMsg({ kind: "ok", text: "Localização atualizada!" });
      setShowGpsPicker(false);
    } catch (e) {
      setGpsMsg({
        kind: "err",
        text: e?.response?.data?.detail || e.message,
      });
    } finally { setSavingGps(false); }
  };

  return (
    <div data-testid="lousa-smartolt-block"
          style={{
            marginTop: 8, padding: "8px 10px", borderRadius: 8,
            background: "rgba(14,165,233,0.08)",
            border: "1px solid rgba(14,165,233,0.18)",
          }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(85px, 1fr))",
        gap: 6,
      }}>
        {items.map((i) => (
          <div key={i.label}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#67e8f9",
                            textTransform: "uppercase", letterSpacing: 0.5 }}>
              {i.label}
            </div>
            <div style={{
              fontSize: 11.5, color: "#e0f2fe", fontWeight: 600,
              fontFamily: i.mono ? "monospace" : "inherit",
              wordBreak: "break-all",
            }}>{i.value}</div>
            {i.hint && (
              <div style={{ fontSize: 9, color: "#7dd3fc",
                              opacity: 0.7 }}>{i.hint}</div>
            )}
          </div>
        ))}
      </div>
      {ctoBox && (
        <div style={{
          marginTop: 8, display: "grid",
          gridTemplateColumns: "1fr 1fr", gap: 6,
        }}>
          <button
            onClick={() => setShowGpsPicker(true)}
            disabled={savingGps}
            data-testid="lousa-cto-gps-btn"
            style={{
              padding: "7px 8px", border: 0,
              background: "linear-gradient(135deg,#8b5cf6,#6366f1)",
              color: "#fff", borderRadius: 8, fontSize: 11, fontWeight: 600,
              cursor: savingGps ? "wait" : "pointer",
              display: "inline-flex", justifyContent: "center", alignItems: "center", gap: 4,
            }}>
            📍 {savingGps ? "Salvando..." : "GPS"}
          </button>
          <button
            onClick={async () => {
              if (!ls?.sn) return alert("ONU sem SN cadastrado");
              if (!confirm(`Enviar PUSH (reiniciar ONU ${ls.sn})?\n\nO cliente vai ficar offline por ~30s.`)) return;
              setPushBusy(true); setGpsMsg(null);
              try {
                await api._client.post(`/rede-ia/onu/${encodeURIComponent(ls.sn)}/push`,
                  { action: "reboot" });
                setGpsMsg({ kind: "ok", text: "Push enviado! Aguarde ~30s." });
              } catch (e) {
                setGpsMsg({
                  kind: "err",
                  text: e?.response?.data?.detail || e.message,
                });
              } finally { setPushBusy(false); }
            }}
            disabled={pushBusy || !ls?.sn}
            data-testid="lousa-cto-push-btn"
            style={{
              padding: "7px 8px", border: 0,
              background: pushBusy
                ? "#94a3b8"
                : "linear-gradient(135deg,#f43f5e,#ec4899)",
              color: "#fff", borderRadius: 8, fontSize: 11, fontWeight: 600,
              cursor: pushBusy ? "wait" : "pointer",
              display: "inline-flex", justifyContent: "center", alignItems: "center", gap: 4,
            }}>
            ⚡ {pushBusy ? "Enviando..." : "Push ONU"}
          </button>
        </div>
      )}
      {gpsMsg && (
        <div data-testid={`lousa-cto-gps-${gpsMsg.kind}`}
              style={{
                marginTop: 6, padding: 7, borderRadius: 6, fontSize: 11,
                background: gpsMsg.kind === "ok" ? "#dcfce7" : "#fee2e2",
                color: gpsMsg.kind === "ok" ? "#166534" : "#991b1b",
              }}>
          {gpsMsg.text}
        </div>
      )}
      {showGpsPicker && (
        <UberGpsPicker
          title={`CTO ${ctoBox} — Ajustar GPS`}
          initialLat={initialGps?.lat}
          initialLng={initialGps?.lng}
          onClose={() => setShowGpsPicker(false)}
          onConfirm={saveLocation}
        />
      )}
    </div>
  );
}
