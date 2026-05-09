import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Button, Icon } from "@/ui";
import QRScannerModal from "@/QRScannerModal";

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

  // --- Reorder helpers (modo "Reordenar") ---
  function isLockedTicket(t) {
    return t.locked || t.priority !== "normal" || ["aberta", "aguardando_atendimento", "finalizada"].includes(t.status);
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

  async function handleFinalize(ticket, completionData) {
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
      });
      setOpenTicket(null);
      await refresh();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  if (!data) {
    return (
      <div data-testid="lousa-loading" style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
        Carregando lousa...
      </div>
    );
  }

  if (openTicket) {
    return (
      <TicketDetail
        ticket={openTicket}
        onClose={() => setOpenTicket(null)}
        onFinalize={(cd) => handleFinalize(openTicket, cd)}
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

      {!state.has_entrada && (
        <Banner color="#fef3c7" border="#f59e0b" icon="⚠️" text="Bata o ponto de Entrada para liberar a lousa." />
      )}
      {state.in_intervalo && (
        <Banner color="#dbeafe" border="#3b82f6" icon="🍽️" text="Você está em intervalo de almoço. A lousa abrirá após Fim intervalo." />
      )}
      {state.ended_day && (
        <Banner color="#e0e7ff" border="#6366f1" icon="🏁" text="Você já bateu Saída. Boa noite!" />
      )}
      {lastEvent && state.has_entrada && !reorderMode && (
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
        border: `1px solid ${isOpen ? "#10b981" : c.border}`,
        marginBottom: 10,
        cursor: ticket.locked || isResolved ? "not-allowed" : "pointer",
        opacity, color: c.text, position: "relative",
        boxShadow: isOpen
          ? "0 6px 18px rgba(16,185,129,.20)"
          : "0 1px 3px rgba(15,23,42,.06), 0 2px 6px rgba(15,23,42,.04)",
        transition: "transform .15s, box-shadow .2s",
        overflow: "hidden",
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

function TicketDetail({ ticket, onClose, onFinalize, busy, err, onRefresh }) {
  const [form, setForm] = useState({
    sinal: -25, qtd_drop: 1, esticadores: 1, conectores_fast: 2,
    cabo_rede: 10, conectores_rede: 2, ont: "", observacoes: "",
  });
  const [stock, setStock] = useState(null);
  const [macStatus, setMacStatus] = useState(null); // null|loading|ok|warn|error
  const [macInfo, setMacInfo] = useState(null);
  const [showQR, setShowQR] = useState(false);

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

  function submit() {
    if (needsMac && !form.ont) {
      alert(isWithdraw ? "MAC da ONT retirada é obrigatório" : "MAC da ONT é obrigatório para instalação/troca");
      return;
    }
    if (needsMac && macStatus === "error") {
      if (!window.confirm("MAC não encontrado no SmartOLT. Continuar mesmo assim? (Será marcado como erro_estoque para o gestor revisar)")) return;
    }
    // Saldo
    const consMap = Object.fromEntries((stock?.consumables || []).map((c) => [c.id, c.qty]));
    const checks = [
      ["drop", form.qtd_drop], ["esticador", form.esticadores],
      ["conector_fast", form.conectores_fast], ["cabo_rede", form.cabo_rede],
      ["conector_rede", form.conectores_rede],
    ];
    for (const [k, v] of checks) {
      const used = Number(v) || 0;
      if (used > (consMap[k] ?? Infinity)) {
        if (!window.confirm(`Saldo insuficiente de ${k} (disponível ${consMap[k]}, gastando ${used}). Continuar? Vai ficar erro_estoque pra revisão.`)) return;
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
      fotos: [],
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
          <div style={{ fontSize: 11, fontFamily: "monospace", color: "#a5b4fc", marginBottom: 4 }}>
            🔑 {ticket.client_snapshot.pppoe_user}
          </div>
        )}
        {ticket.live_signal && (
          <div style={{ marginTop: 8, padding: "6px 10px", background: "rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}>
            📶 <strong>{ticket.live_signal.rx_dbm?.toFixed(1)} dBm</strong> · {ticket.live_signal.status} · {ticket.live_signal.olt_name}
          </div>
        )}
      </div>

      <div style={{
        background: "#f1f5f9", padding: 12, borderRadius: 12, marginTop: 12,
        fontSize: 13, lineHeight: 1.5, borderLeft: "3px solid #6366f1",
      }}>
        <strong>📝 Relato:</strong> {ticket.client_snapshot.relato}
      </div>

      <h3 style={{ marginTop: 18, marginBottom: 10, fontSize: 16, fontWeight: 800, color: "#0f172a" }}>📋 Finalizar serviço</h3>

      {/* SINAL */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>📶 Sinal medido (dBm)</label>
        <input data-testid="finalize-sinal" type="number" step="0.1" value={form.sinal}
          onChange={(e) => setForm({ ...form, sinal: e.target.value })}
          style={{ width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 14, marginTop: 4, boxSizing: "border-box" }} />
      </div>

      {/* MAC ONT */}
      {needsMac && (
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

      {/* INSUMOS */}
      <div style={{
        padding: "12px 14px", background: "white", border: "1px solid #e2e8f0",
        borderRadius: 14, marginBottom: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: "#0f172a", marginBottom: 10 }}>
          🧰 Materiais utilizados
          {stock && <span style={{ fontSize: 11, color: "#64748b", fontWeight: 500, marginLeft: 6 }}>· estoque: {stock.collaborator_name}</span>}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <ConsumableField label="Drop (m)" fieldKey="qtd_drop" consumableId="drop" consMap={consMap} form={form} setForm={setForm} />
          <ConsumableField label="Esticador (un)" fieldKey="esticadores" consumableId="esticador" consMap={consMap} form={form} setForm={setForm} />
          <ConsumableField label="Conector fast (un)" fieldKey="conectores_fast" consumableId="conector_fast" consMap={consMap} form={form} setForm={setForm} />
          <ConsumableField label="Cabo rede (m)" fieldKey="cabo_rede" consumableId="cabo_rede" step="0.5" consMap={consMap} form={form} setForm={setForm} />
          <ConsumableField label="Conector rede (un)" fieldKey="conectores_rede" consumableId="conector_rede" consMap={consMap} form={form} setForm={setForm} />
        </div>
      </div>

      <label style={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>📝 Observações</label>
      <textarea
        data-testid="finalize-obs" value={form.observacoes}
        onChange={(e) => setForm({ ...form, observacoes: e.target.value })} rows={3}
        placeholder="Detalhes do serviço, materiais especiais, etc."
        style={{
          width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1",
          borderRadius: 10, fontSize: 14, marginTop: 4, marginBottom: 12,
          resize: "vertical", boxSizing: "border-box", fontFamily: "inherit",
        }}
      />

      {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}

      <Button onClick={submit} disabled={busy} style={{ width: "100%", marginTop: 6, height: 52, fontSize: 15 }} data-testid="finalize-btn">
        <Icon name="check" /> {busy ? "Finalizando..." : "Finalizar nota"}
      </Button>

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
