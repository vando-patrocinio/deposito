/* iter215an — AtendimentoDutyGate
 * Wrapper que controla o acesso ao chat de Atendimento IA conforme o
 * estado do PONTO do colaborador (regra global de batimento de ponto).
 *
 * Quando off_duty=true:
 *  • filtro grayscale + pointer-events:none no children
 *  • banner sólido no topo explicando o motivo
 *  • CTA "Ir para Ponto"
 */
import React, { useEffect, useRef, useState } from "react";
import { Lock, Clock, AlertTriangle, MessageSquare } from "lucide-react";

import { api } from "@/api";

const POLL_MS = 30000; // 30s

export default function AtendimentoDutyGate({ children, onPontoClick }) {
  const [status, setStatus] = useState({
    on_duty: true, reason: "loading", role: null,
    other_attendants_online: [], last_event: null,
  });
  const [loading, setLoading] = useState(true);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    let timer = null;
    const fetchStatus = async () => {
      try {
        const r = await api._client.get(
          "/whatsapp-baileys/atendimento/duty-status");
        if (mountedRef.current) setStatus(r.data || {});
      } catch {
        if (mountedRef.current) {
          setStatus((s) => ({ ...s, on_duty: true,
                                reason: "fallback_open" }));
        }
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    };
    fetchStatus();
    timer = setInterval(fetchStatus, POLL_MS);
    return () => {
      mountedRef.current = false;
      if (timer) clearInterval(timer);
    };
  }, []);

  if (loading) {
    return (
      <div data-testid="duty-gate-loading"
            style={{ padding: 32, textAlign: "center", color: "#64748b",
                      fontSize: 13, fontFamily: "Inter, sans-serif" }}>
        Verificando ponto…
      </div>
    );
  }

  const blocked = status.on_duty === false;

  const formatSince = (sec) => {
    if (sec == null) return "—";
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    if (m < 60) return `${m}min`;
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return rm ? `${h}h ${rm}min` : `${h}h`;
  };

  return (
    <div data-testid="atendimento-duty-gate"
          style={{ position: "relative",
                    fontFamily: "Inter, sans-serif" }}>
      {!blocked && (
        <div data-testid="duty-kpi-strip"
              style={{ display: "flex", gap: 10, alignItems: "center",
                        padding: "8px 12px", marginBottom: 10,
                        borderRadius: 10,
                        background: "linear-gradient(135deg,#f5f3ff,#ede9fe)",
                        border: "1px solid #ddd6fe",
                        fontSize: 12, color: "#4c1d95",
                        fontWeight: 700, flexWrap: "wrap" }}>
          <span style={{ display: "inline-flex", alignItems: "center",
                          gap: 6 }}>
            <MessageSquare size={13} />
            <span data-testid="duty-kpi-open" style={{ fontWeight: 800 }}>
              {status.my_open_conversations ?? 0}
            </span>
            <span style={{ opacity: 0.75, fontWeight: 600 }}>
              conversa(s) atribuída(s) a mim
            </span>
          </span>
          <span style={{ color: "#a78bfa", fontWeight: 400 }}>·</span>
          <span style={{ display: "inline-flex", alignItems: "center",
                          gap: 6 }}>
            <Clock size={13} />
            <span data-testid="duty-kpi-since" style={{ fontWeight: 800 }}>
              {formatSince(status.seconds_since_last_onduty)}
            </span>
            <span style={{ opacity: 0.75, fontWeight: 600 }}>
              desde {status.last_onduty_event === "Fim intervalo"
                ? "fim do intervalo" : "Entrada"}
            </span>
          </span>
        </div>
      )}      {blocked && (
        <div data-testid="duty-gate-banner"
              style={{
          display: "flex", gap: 14, alignItems: "center",
          padding: "14px 18px", marginBottom: 14, borderRadius: 14,
          background: "linear-gradient(135deg,#fef2f2,#fee2e2)",
          border: "2px solid #fca5a5",
          boxShadow: "0 4px 12px rgba(220,38,38,.08)",
        }}>
          <div style={{ width: 44, height: 44, borderRadius: 12,
                          background: "var(--danger, #b42318)",
                          color: "white", display: "flex",
                          alignItems: "center", justifyContent: "center",
                          flexShrink: 0 }}>
            <Lock size={22} strokeWidth={2.2} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 800,
                            color: "#7f1d1d", letterSpacing: -0.2,
                            marginBottom: 2,
                            display: "flex", alignItems: "center", gap: 8 }}>
              <AlertTriangle size={14} />
              Atendimento BLOQUEADO pelo seu ponto
            </div>
            <div style={{ fontSize: 12.5, color: "#7f1d1d",
                            lineHeight: 1.5 }}>
              {status.reason || (
                "Bata o ponto de Entrada para liberar o chat de atendimento."
              )}
            </div>
            {status.other_attendants_online?.length > 0 && (
              <div style={{ marginTop: 6, fontSize: 11,
                              color: "#7f1d1d", opacity: 0.85 }}>
                <Clock size={11} style={{ marginRight: 4,
                                              verticalAlign: -1 }} />
                Atendentes online no momento: {status.other_attendants_online
                  .map((a) => a.name || a.role).join(", ")}
              </div>
            )}
          </div>
          {onPontoClick && (
            <button data-testid="duty-gate-go-to-ponto"
                     onClick={onPontoClick}
                     style={{ padding: "10px 16px", border: "none",
                                borderRadius: 10,
                                background: "var(--primary, #4b1d7a)",
                                color: "white", fontWeight: 800,
                                fontSize: 12.5, cursor: "pointer",
                                fontFamily: "inherit",
                                whiteSpace: "nowrap" }}>
              Ir para Ponto
            </button>
          )}
        </div>
      )}
      <div data-testid="duty-gate-content"
            style={{
        filter: blocked ? "grayscale(0.85) opacity(0.55)" : "none",
        pointerEvents: blocked ? "none" : "auto",
        userSelect: blocked ? "none" : "auto",
        transition: "filter 220ms ease",
      }}
            aria-disabled={blocked}>
        {children}
      </div>
    </div>
  );
}
