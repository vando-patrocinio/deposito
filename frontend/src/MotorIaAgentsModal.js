import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { X, Power, Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";

/**
 * MotorIaAgentsModal — Painel de Kill-Switch por agente.
 * Permite ao admin pausar uma IA específica sem afetar as outras.
 * Mudanças têm efeito imediato (próxima chamada do agente desligado falha
 * com AgentDisabledError, mas o caller já trata silenciosamente).
 *
 * Props:
 *  - onClose(): fecha modal
 */
export default function MotorIaAgentsModal({ onClose }) {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pendingId, setPendingId] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.motorIaAgentsList();
      setAgents(r.agents || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (a) => {
    setPendingId(a.id); setErr("");
    try {
      await api.motorIaAgentToggle(a.id, !a.enabled);
      // Atualiza local sem refetch (otimista)
      setAgents((prev) => prev.map((x) =>
        x.id === a.id ? { ...x, enabled: !x.enabled, updated_at: new Date().toISOString() } : x
      ));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setPendingId(null);
    }
  };

  const enabledCount = agents.filter((a) => a.enabled).length;
  const disabledCount = agents.length - enabledCount;

  return (
    <div
      onClick={onClose}
      data-testid="motor-ia-agents-modal-backdrop"
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)",
        zIndex: 9000, display: "grid", placeItems: "center", padding: 20,
        backdropFilter: "blur(4px)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        data-testid="motor-ia-agents-modal"
        style={{
          background: "var(--bg-surface, #fff)",
          color: "var(--text-primary, #0f172a)",
          borderRadius: 16, width: "100%", maxWidth: 720,
          maxHeight: "85vh", overflow: "hidden",
          display: "flex", flexDirection: "column",
          boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
          border: "1px solid var(--border-default, #e2e8f0)",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "18px 22px",
          borderBottom: "1px solid var(--border-default, #e2e8f0)",
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12,
            background: "#0f172a", color: "#fbbf24",
            display: "grid", placeItems: "center", flexShrink: 0,
          }}>
            <Power size={22} strokeWidth={2} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "-0.02em" }}>
              Painel de Agentes IA
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted, #64748b)", marginTop: 2 }}>
              Kill-switch global por agente. Desligue uma IA específica sem afetar as outras.
            </div>
          </div>
          <button
            onClick={onClose} data-testid="modal-close-btn"
            style={{
              padding: 8, border: 0, borderRadius: 8,
              background: "transparent", cursor: "pointer",
              color: "var(--text-muted, #64748b)",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Resumo */}
        <div style={{
          padding: "10px 22px",
          background: "var(--surface-2, #f8fafc)",
          borderBottom: "1px solid var(--border-default, #e2e8f0)",
          display: "flex", gap: 22, fontSize: 12,
        }}>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <CheckCircle2 size={14} color="#16a34a" />
            <strong>{enabledCount}</strong> ativos
          </span>
          {disabledCount > 0 && (
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <AlertTriangle size={14} color="#dc2626" />
              <strong>{disabledCount}</strong> pausados
            </span>
          )}
          <span style={{ color: "var(--text-muted, #64748b)" }}>
            Total: {agents.length}
          </span>
        </div>

        {/* Lista */}
        <div style={{ overflow: "auto", flex: 1, padding: "8px 0" }}>
          {err && (
            <div style={{ margin: "10px 22px", padding: 10,
                            background: "#fef2f2", color: "#be123c",
                            borderRadius: 8, fontSize: 12 }}>
              {err}
            </div>
          )}
          {loading ? (
            <div style={{ padding: 30, display: "flex", justifyContent: "center",
                            color: "var(--text-muted, #64748b)", fontSize: 13, gap: 8,
                            alignItems: "center" }}>
              <Loader2 size={14} className="animate-spin" /> Carregando agentes...
            </div>
          ) : (
            agents.map((a) => (
              <div key={a.id}
                   data-testid={`agent-row-${a.id}`}
                   style={{
                     padding: "12px 22px",
                     display: "flex", alignItems: "center", gap: 14,
                     borderBottom: "1px solid var(--border-default, #f1f5f9)",
                     opacity: a.enabled ? 1 : 0.65,
                     transition: "opacity 0.2s",
                   }}>
                <div style={{
                  width: 10, height: 10, borderRadius: "50%",
                  background: a.enabled ? "#16a34a" : "#94a3b8",
                  boxShadow: a.enabled ? "0 0 0 3px rgba(22,163,74,0.15)" : "none",
                  flexShrink: 0,
                }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700,
                                  color: "var(--text-primary, #0f172a)" }}>
                    {a.label}
                    {!a.enabled && (
                      <span style={{
                        marginLeft: 8, fontSize: 10, fontWeight: 700,
                        padding: "2px 7px", borderRadius: 999,
                        background: "#fef2f2", color: "#be123c",
                      }}>PAUSADO</span>
                    )}
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--text-muted, #64748b)",
                                  marginTop: 2, lineHeight: 1.4 }}>
                    {a.description}
                  </div>
                  {a.updated_at && (
                    <div style={{ fontSize: 10, color: "var(--text-muted, #94a3b8)",
                                    marginTop: 3 }}>
                      Última alteração: {new Date(a.updated_at).toLocaleString("pt-BR")}
                      {a.updated_by && ` · por ${a.updated_by}`}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => toggle(a)}
                  disabled={pendingId === a.id}
                  data-testid={`agent-toggle-${a.id}`}
                  style={{
                    position: "relative", width: 46, height: 24,
                    borderRadius: 999, border: 0, cursor: pendingId ? "wait" : "pointer",
                    background: a.enabled ? "#16a34a" : "#cbd5e1",
                    transition: "background 0.2s", flexShrink: 0,
                  }}
                >
                  <div style={{
                    position: "absolute", top: 2,
                    left: a.enabled ? 24 : 2,
                    width: 20, height: 20, borderRadius: "50%",
                    background: "#fff", transition: "left 0.2s",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                    display: "grid", placeItems: "center",
                  }}>
                    {pendingId === a.id && <Loader2 size={11} className="animate-spin" color="#64748b" />}
                  </div>
                </button>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: "12px 22px",
          borderTop: "1px solid var(--border-default, #e2e8f0)",
          background: "var(--surface-2, #f8fafc)",
          fontSize: 11, color: "var(--text-muted, #64748b)",
          lineHeight: 1.5,
        }}>
          <strong>Importante:</strong> ao pausar um agente, todas as chamadas LLM dele
          serão bloqueadas até reativação. Workers em background continuam rodando, mas
          sem analisar (silent skip). Reativar aplica imediatamente.
        </div>
      </div>
    </div>
  );
}
