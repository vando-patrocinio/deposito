/**
 * LifecycleTimeline — Componente visual do histórico de transições de OS
 * ----------------------------------------------------------------------
 * Mostra timeline vertical com cada estado, ator, motivo e timestamp.
 * Inclui badge de SLA atual (% usado, breach/warning/ok).
 *
 * CTO P1 — 12/06/2026.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const STATE_COLORS = {
  draft: "#94a3b8",
  ready_for_dispatch: "#0ea5e9",
  assigned: "#6366f1",
  accepted: "#8b5cf6",
  en_route: "#a855f7",
  in_progress: "#0d9488",
  pending: "#f59e0b",
  completed: "#16a34a",
  closed_incomplete: "#dc2626",
  canceled: "#64748b",
};

const STATE_LABELS = {
  draft: "Rascunho",
  ready_for_dispatch: "Pronta",
  assigned: "Atribuída",
  accepted: "Aceita",
  en_route: "A caminho",
  in_progress: "Em execução",
  pending: "Em espera",
  completed: "Concluída",
  closed_incomplete: "Encerrada s/ êxito",
  canceled: "Cancelada",
};

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { hour12: false });
}

function fmtAge(min) {
  if (!min) return "—";
  if (min < 60) return `${min}min`;
  if (min < 1440) return `${(min / 60).toFixed(1)}h`;
  return `${(min / 1440).toFixed(1)}d`;
}

export default function LifecycleTimeline({ ticketId, compact = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!ticketId) return;
    let mounted = true;
    api.osLifecycleTimeline(ticketId)
      .then((r) => { if (mounted) setData(r); })
      .catch((e) => { if (mounted) setError(e?.response?.data?.detail || e.message); });
    return () => { mounted = false; };
  }, [ticketId]);

  if (error) return (
    <div style={{ padding: 8, fontSize: 12, color: "#dc2626" }} data-testid="lt-error">
      Timeline indisponível: {error}
    </div>
  );
  if (!data) return (
    <div style={{ padding: 8, fontSize: 12, color: "#94a3b8" }} data-testid="lt-loading">
      Carregando timeline…
    </div>
  );

  const t = data.ticket;
  const history = data.history || [];
  const sla = data.sla || {};
  const currentState = t.lifecycle_state;

  return (
    <div data-testid={`lifecycle-timeline-${ticketId}`} style={{
      background: "#fafbfc", border: "1px solid #e2e8f0", borderRadius: 10,
      padding: compact ? 10 : 14,
    }}>
      {/* Header: estado atual + SLA */}
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 10, color: "#94a3b8", fontWeight: 800,
                          letterSpacing: ".08em", textTransform: "uppercase" }}>
            Estado atual
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
            <span style={{
              padding: "3px 10px", borderRadius: 999,
              background: STATE_COLORS[currentState] || "#64748b",
              color: "white", fontSize: 11, fontWeight: 700,
            }}>{STATE_LABELS[currentState] || currentState}</span>
            {t.lifecycle_reason_code && (
              <span style={{ fontSize: 11, color: "#64748b",
                              fontStyle: "italic" }}>
                · {t.lifecycle_reason_code}
              </span>
            )}
          </div>
        </div>
        {sla.sla_minutes && (
          <div style={{
            textAlign: "right",
            padding: "6px 12px", borderRadius: 8,
            background: sla.breach ? "#fef2f2" : sla.warning ? "#fffbeb" : "#f0fdf4",
            border: `1px solid ${sla.breach ? "#fecaca" : sla.warning ? "#fde68a" : "#bbf7d0"}`,
          }}>
            <div style={{ fontSize: 10, fontWeight: 800,
                            color: sla.breach ? "#991b1b" : sla.warning ? "#92400e" : "#166534",
                            letterSpacing: ".05em", textTransform: "uppercase" }}>
              {sla.breach ? "🔴 SLA estourado" : sla.warning ? "⚠ SLA alerta" : "✓ SLA OK"}
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a", marginTop: 2 }}>
              {fmtAge(sla.consumed_minutes)} / {fmtAge(sla.sla_minutes)}
              <span style={{ marginLeft: 6, fontSize: 11, color: "#64748b" }}>
                ({sla.percent_used}%)
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Timeline */}
      {history.length === 0 ? (
        <div style={{ fontSize: 12, color: "#94a3b8", textAlign: "center",
                        padding: 12, fontStyle: "italic" }}>
          Sem transições registradas ainda
        </div>
      ) : (
        <div style={{ position: "relative", paddingLeft: 24 }}>
          {/* Linha vertical */}
          <div style={{
            position: "absolute", left: 7, top: 6, bottom: 6,
            width: 2, background: "#e2e8f0",
          }} />
          {history.map((h, i) => {
            const color = STATE_COLORS[h.to_state] || "#64748b";
            return (
              <div key={i} style={{ position: "relative", marginBottom: 12 }}>
                {/* Bolinha */}
                <div style={{
                  position: "absolute", left: -22, top: 2,
                  width: 14, height: 14, borderRadius: "50%",
                  background: color, border: "3px solid white",
                  boxShadow: `0 0 0 2px ${color}55`,
                }} />
                <div style={{ display: "flex", alignItems: "baseline",
                                gap: 6, flexWrap: "wrap" }}>
                  <span style={{
                    fontSize: 11, fontWeight: 700,
                    color, padding: "1px 7px",
                    background: color + "15", borderRadius: 4,
                  }}>{STATE_LABELS[h.to_state] || h.to_state}</span>
                  {h.from_state && (
                    <span style={{ fontSize: 10, color: "#94a3b8" }}>
                      (de {STATE_LABELS[h.from_state] || h.from_state})
                    </span>
                  )}
                  {h.reason_code && (
                    <span style={{
                      fontSize: 10, color: "#64748b", fontStyle: "italic",
                    }}>· {h.reason_code}</span>
                  )}
                  {h.forced && (
                    <span style={{
                      fontSize: 9, color: "#dc2626", fontWeight: 800,
                      letterSpacing: ".05em",
                    }}>FORÇADO</span>
                  )}
                </div>
                <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
                  {fmtTime(h.at)}
                  {h.actor_name && <> · por <strong>{h.actor_name}</strong></>}
                </div>
                {h.notes && (
                  <div style={{
                    fontSize: 11, color: "#475569", marginTop: 4,
                    padding: "4px 8px", background: "white",
                    borderRadius: 4, border: "1px solid #f1f5f9",
                  }}>{h.notes}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
