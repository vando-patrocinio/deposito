import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Button, Icon } from "@/ui";

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
  const [openTicket, setOpenTicket] = useState(null); // ticket clicked

  const refresh = useCallback(async () => {
    if (!collaboratorId) return;
    try {
      const d = await api.lousaByCollaborator(collaboratorId);
      setData(d);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, [collaboratorId]);

  useEffect(() => { refresh(); }, [refresh]);

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
            data-testid="lousa-refresh-btn"
            style={{ background: "#dbeafe", color: "#1e40af", border: "1px solid #93c5fd" }}
          >
            🔄 Atualizar
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
          disabled={busy}
          data-testid="lousa-refresh-btn"
          style={{ background: "#dbeafe", color: "#1e40af", border: "1px solid #93c5fd" }}
        >
          🔄 Atualizar
        </Button>
      </div>
      <h2 style={{ marginTop: 14, marginBottom: 4 }}>📋 Lousa de Serviços</h2>
      <p style={{ color: "#64748b", fontSize: 12, margin: 0 }}>
        {data.tickets.length} bolhas — {unlocked ? "🔓 lousa liberada" : "🔒 lousa travada"}
      </p>

      {!state.has_entrada && (
        <Banner color="#fef3c7" border="#f59e0b" icon="⚠️" text="Bata o ponto de Entrada para liberar a lousa." />
      )}
      {state.in_intervalo && (
        <Banner color="#dbeafe" border="#3b82f6" icon="🍽️" text="Você está em intervalo de almoço. A lousa abrirá após Fim intervalo." />
      )}
      {state.ended_day && (
        <Banner color="#e0e7ff" border="#6366f1" icon="🏁" text="Você já bateu Saída. Boa noite!" />
      )}
      {lastEvent && state.has_entrada && (
        <Banner color="#dcfce7" border="#10b981" icon="✓" text={`Último ponto: ${lastEvent.type} às ${lastEvent.time}`} />
      )}

      {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}

      <div style={{ marginTop: 14 }}>
        {data.tickets.length === 0 && (
          <div style={{ background: "white", border: "1px dashed #cbd5e1", borderRadius: 16, padding: 20, textAlign: "center", color: "#94a3b8" }}>
            Nenhuma nota atribuída ainda.
          </div>
        )}
        {data.tickets.map((t, idx) => (
          <React.Fragment key={t.id}>
            {idx > 0 && lastEvent && idx === Math.floor(data.tickets.length / 2) && (
              <BetweenBubblesInfo records={records} />
            )}
            <Bubble ticket={t} onClick={() => handleOpen(t)} disabled={busy} />
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

function Bubble({ ticket, onClick, disabled }) {
  const isResolved = ticket.admin_resolved || ticket.status === "finalizada";
  const isOpen = ticket.status === "aberta" || ticket.status === "aguardando_atendimento";
  const priorityColors = {
    prioridade: { bg: "#fee2e2", border: "#dc2626", text: "#7f1d1d", label: "🚨 PRIORIDADE" },
    horario: { bg: "#fef3c7", border: "#f59e0b", text: "#78350f", label: "⏰ HORÁRIO" },
    normal: { bg: "white", border: "#e2e8f0", text: "#0f172a", label: "" },
  };
  const c = priorityColors[ticket.priority] || priorityColors.normal;
  const opacity = ticket.locked || disabled ? 0.55 : 1;

  return (
    <button
      onClick={onClick}
      disabled={ticket.locked || disabled || isResolved}
      data-testid={`bubble-${ticket.id}`}
      style={{
        width: "100%", textAlign: "left", padding: 14, borderRadius: 22,
        background: isOpen ? "#dcfce7" : c.bg,
        border: `2px solid ${isOpen ? "#10b981" : c.border}`,
        marginBottom: 10, cursor: ticket.locked || isResolved ? "not-allowed" : "pointer",
        opacity, color: c.text, position: "relative",
        boxShadow: isOpen ? "0 8px 22px rgba(16,185,129,.25)" : "0 4px 10px rgba(15,23,42,.05)",
        transition: "all 0.2s",
      }}
    >
      {ticket.locked && !isOpen && (
        <span style={{ position: "absolute", top: 8, right: 10, fontSize: 18 }}>🔒</span>
      )}
      {c.label && (
        <div style={{ fontSize: 10, fontWeight: 900, letterSpacing: 0.5, marginBottom: 4 }}>
          {c.label}{ticket.scheduled_time ? ` · ${ticket.scheduled_time.substr(11, 5)}` : ""}
        </div>
      )}
      <div style={{ fontSize: 14, fontWeight: 800 }}>{ticket.client_snapshot.name}</div>
      <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
        {ticket.type.toUpperCase()} · {ticket.client_snapshot.neighborhood}
      </div>
      <div style={{ fontSize: 12, color: "#475569", marginTop: 6 }}>
        {ticket.client_snapshot.relato?.substring(0, 80)}{ticket.client_snapshot.relato?.length > 80 ? "..." : ""}
      </div>
      {isResolved && (
        <div style={{ marginTop: 6, fontSize: 11, color: "#16a34a", fontWeight: 700 }}>
          ✓ {ticket.status === "finalizada" ? "Finalizada" : ticket.admin_action || "Encerrada"}
        </div>
      )}
      {isOpen && (
        <div style={{ marginTop: 6, fontSize: 11, color: "#16a34a", fontWeight: 800 }}>
          ▶ EM ANDAMENTO — toque para ver detalhes
        </div>
      )}
    </button>
  );
}

function TicketDetail({ ticket, onClose, onFinalize, busy, err, onRefresh }) {
  const [form, setForm] = useState({
    sinal: -25, qtd_drop: 1, esticadores: 1, conectores_fast: 2,
    cabo_rede: 10, conectores_rede: 2, ont: "", observacoes: "",
  });

  function submit() {
    if (ticket.type === "instalacao" && !form.ont) {
      alert("ONT é obrigatório para instalação");
      return;
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

  const inputCss = {
    width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1",
    borderRadius: 10, fontSize: 14, marginBottom: 10,
  };

  return (
    <div data-testid="ticket-detail">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button variant="soft" onClick={onClose} data-testid="ticket-close-btn">← Voltar à lousa</Button>
        {onRefresh && (
          <Button
            variant="soft"
            onClick={onRefresh}
            data-testid="ticket-refresh-btn"
            style={{ background: "#dbeafe", color: "#1e40af", border: "1px solid #93c5fd" }}
          >
            🔄 Atualizar
          </Button>
        )}
      </div>
      <h2 style={{ marginTop: 14, marginBottom: 4 }}>{ticket.client_snapshot.name}</h2>
      <p style={{ color: "#64748b", fontSize: 12, margin: 0 }}>
        {ticket.type.toUpperCase()} · {ticket.client_snapshot.address}
      </p>
      <div style={{
        background: "#f1f5f9", padding: 12, borderRadius: 12, marginTop: 12,
        fontSize: 13, lineHeight: 1.5,
      }}>
        <strong>Relato:</strong> {ticket.client_snapshot.relato}
      </div>

      <h3 style={{ marginTop: 18, marginBottom: 8, fontSize: 15 }}>📋 Finalizar serviço</h3>
      <label style={{ fontSize: 12, color: "#64748b" }}>Sinal (dBm)</label>
      <input data-testid="finalize-sinal" type="number" step="0.1" value={form.sinal} onChange={(e) => setForm({ ...form, sinal: e.target.value })} style={inputCss} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>Qtd. drop</label>
          <input data-testid="finalize-drop" type="number" value={form.qtd_drop} onChange={(e) => setForm({ ...form, qtd_drop: e.target.value })} style={inputCss} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>Esticadores</label>
          <input type="number" value={form.esticadores} onChange={(e) => setForm({ ...form, esticadores: e.target.value })} style={inputCss} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>Conectores fast</label>
          <input type="number" value={form.conectores_fast} onChange={(e) => setForm({ ...form, conectores_fast: e.target.value })} style={inputCss} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>Cabo rede (m)</label>
          <input type="number" step="0.1" value={form.cabo_rede} onChange={(e) => setForm({ ...form, cabo_rede: e.target.value })} style={inputCss} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>Conectores rede</label>
          <input type="number" value={form.conectores_rede} onChange={(e) => setForm({ ...form, conectores_rede: e.target.value })} style={inputCss} />
        </div>
        {ticket.type === "instalacao" && (
          <div>
            <label style={{ fontSize: 12, color: "#64748b" }}>ONT *</label>
            <input data-testid="finalize-ont" value={form.ont} onChange={(e) => setForm({ ...form, ont: e.target.value })} style={inputCss} />
          </div>
        )}
      </div>
      <label style={{ fontSize: 12, color: "#64748b" }}>Observações</label>
      <textarea data-testid="finalize-obs" value={form.observacoes} onChange={(e) => setForm({ ...form, observacoes: e.target.value })} rows={3} style={{ ...inputCss, resize: "vertical" }} />

      {err && <Banner color="#fee2e2" border="#dc2626" icon="!" text={err} />}

      <Button onClick={submit} disabled={busy} style={{ width: "100%", marginTop: 8, height: 50 }} data-testid="finalize-btn">
        <Icon name="check" /> {busy ? "Finalizando..." : "Finalizar nota"}
      </Button>
    </div>
  );
}
