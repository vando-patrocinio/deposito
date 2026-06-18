/**
 * EscalateToRedeModal — modal de escalonamento para a Célula REDE (Tier 2).
 *
 * Fluxo (best-practice ITSM/FTTH):
 *   1. Carrega sugestão IA (POST /api/lousa/tickets/{id}/rede/ai-suggest)
 *   2. Mostra: sinal atual + top 3 causas com %, ação por tier
 *   3. Checklist obrigatório (limpou conector ✓ · reiniciou ONU ✓)
 *   4. Botões:
 *      - "✓ IA me ajudou, NÃO vou escalar" (POST .../ai-avoided)
 *      - "↑ ESCALAR para REDE" (POST .../escalate)
 */
import React, { useState, useEffect } from "react";
import { api } from "./api";

export default function EscalateToRedeModal({ ticket, onClose, onEscalated }) {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [aiData, setAiData] = useState(null);
  const [error, setError] = useState(null);

  const [checklist, setChecklist] = useState({
    limpou_conector: false,
    reiniciou_onu: false,
    inspecionou_drop: false,
  });
  const [cause, setCause] = useState("");
  const [observations, setObservations] = useState("");

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const r = await api._client.post(
          `/lousa/tickets/${ticket.id}/rede/ai-suggest`);
        if (cancel) return;
        setAiData(r.data);
        const top = (r.data?.suggestions || [])[0];
        if (top?.cause) setCause(top.cause);
      } catch (e) {
        if (!cancel) setError(e?.response?.data?.detail || e.message);
      } finally {
        if (!cancel) setLoading(false);
      }
    }
    load();
    return () => { cancel = true; };
  }, [ticket.id]);

  const allChecklistDone = Object.values(checklist).every(Boolean);

  async function escalate() {
    if (!allChecklistDone) {
      await window.alert("Marque todos os checks do campo antes de escalar.");
      return;
    }
    setBusy(true);
    try {
      await api._client.post(
        `/lousa/tickets/${ticket.id}/rede/escalate`, {
          cause: cause || "sinal_critico",
          signal_dbm: aiData?.signal_dbm,
          observations,
          checklist,
          ai_suggestion_id: aiData?._sug_id || null,
        });
      onEscalated();
    } catch (e) {
      await window.alert("Erro ao escalar: " + (e?.response?.data?.detail || e.message));
      setBusy(false);
    }
  }

  async function aiAvoided() {
    setBusy(true);
    try {
      await api._client.post(
        `/lousa/tickets/${ticket.id}/rede/ai-avoided`, {
          ai_suggestion_id: aiData?._sug_id,
          chosen_action: (aiData?.suggestions || [])[0]?.action,
          notes: observations,
        });
      onClose();
    } catch (e) {
      // Sugestão não foi gravada ainda? Tenta sem ID.
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
      setBusy(false);
    }
  }

  return (
    <div data-testid="rede-modal-root"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.65)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 9999, padding: 20,
      }}>
      <div style={{
        background: "white", borderRadius: 14, padding: 22,
        maxWidth: 560, width: "100%", maxHeight: "90vh", overflowY: "auto",
        boxShadow: "0 20px 50px rgba(0,0,0,0.4)",
      }}>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 12,
        }}>
          <div>
            <div style={{
              fontSize: 11, fontWeight: 700, color: "#0891b2",
              letterSpacing: 1.5, fontFamily: "monospace",
            }}>
              ESCALAR PARA CÉLULA REDE · TIER 2
            </div>
            <div style={{ fontSize: 17, fontWeight: 700, color: "#0f172a" }}>
              {ticket.client_snapshot?.name || "Cliente"} · {ticket.type}
            </div>
          </div>
          <button data-testid="rede-modal-close" onClick={onClose}
            style={{
              background: "none", border: "none", fontSize: 22,
              cursor: "pointer", color: "#94a3b8",
            }}>×</button>
        </div>

        {loading && (
          <div data-testid="rede-modal-loading"
            style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
            🧠 IA analisando o caso…
          </div>
        )}

        {error && (
          <div style={{
            padding: 12, background: "#fef2f2", color: "#dc2626",
            borderRadius: 8, fontSize: 13,
          }}>
            Não consegui consultar a IA: {error}. Você ainda pode escalar manualmente.
          </div>
        )}

        {aiData && (
          <>
            {/* SINAL + ADVICE */}
            <div data-testid="rede-modal-signal" style={{
              background: aiData.signal_dbm !== null && aiData.signal_dbm <= -27
                ? "#fef2f2" : "#f0f9ff",
              border: `1.5px solid ${aiData.signal_dbm <= -27 ? "#fca5a5" : "#7dd3fc"}`,
              borderRadius: 10, padding: 12, marginBottom: 12,
            }}>
              <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <div>
                  <div style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase", letterSpacing: 1 }}>
                    Sinal RX
                  </div>
                  <div data-testid="rede-modal-signal-value" style={{
                    fontSize: 26, fontWeight: 800, fontFamily: "monospace",
                    color: aiData.signal_dbm !== null && aiData.signal_dbm <= -27 ? "#dc2626" : "#0284c7",
                  }}>
                    {aiData.signal_dbm !== null ? `${aiData.signal_dbm} dBm` : "—"}
                  </div>
                  <div style={{ fontSize: 10, color: "#64748b" }}>
                    limiar GPON crítico: -27 dBm
                  </div>
                </div>
                <div style={{ flex: 1, fontSize: 12, color: "#334155", lineHeight: 1.4 }}>
                  <b>💡 IA:</b> {aiData.advice_text}
                </div>
              </div>
            </div>

            {/* TOP CAUSAS IA */}
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
              Causas prováveis (IA · {aiData.used_model})
            </div>
            <div data-testid="rede-modal-suggestions">
              {(aiData.suggestions || []).map((s, i) => (
                <label key={i} data-testid={`rede-suggestion-${i}`}
                  style={{
                    display: "flex", alignItems: "flex-start", gap: 10,
                    padding: "8px 10px", border: `1.5px solid ${cause === s.cause ? "#06b6d4" : "#e2e8f0"}`,
                    borderRadius: 9, marginBottom: 6, cursor: "pointer",
                    background: cause === s.cause ? "#ecfeff" : "white",
                  }}>
                  <input type="radio" name="rede-cause" value={s.cause}
                    checked={cause === s.cause}
                    onChange={() => setCause(s.cause)} style={{ marginTop: 3 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ fontWeight: 600, fontSize: 13, color: "#0f172a" }}>
                        {s.cause}
                      </span>
                      <span style={{
                        fontSize: 11, fontWeight: 700,
                        padding: "1px 7px", borderRadius: 8,
                        background: s.tier === "rede" ? "#cffafe" : "#dcfce7",
                        color: s.tier === "rede" ? "#0e7490" : "#15803d",
                      }}>
                        {s.probability_pct}% · {s.tier?.toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: "#475569", marginTop: 2 }}>
                      → {s.action}
                    </div>
                  </div>
                </label>
              ))}
            </div>

            {/* CHECKLIST OBRIGATÓRIO */}
            <div style={{
              marginTop: 14, padding: 11, background: "#fffbeb",
              border: "1.5px solid #fde68a", borderRadius: 9,
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
                Confirmação do campo (obrigatório)
              </div>
              {[
                ["limpou_conector", "Limpei conectores ONT + drop"],
                ["reiniciou_onu", "Reiniciei a ONT (power cycle)"],
                ["inspecionou_drop", "Inspecionei o drop (sem dobras/cortes visíveis)"],
              ].map(([k, label]) => (
                <label key={k}
                  data-testid={`rede-check-${k}`}
                  style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "4px 0", cursor: "pointer", fontSize: 13,
                  }}>
                  <input type="checkbox" checked={!!checklist[k]}
                    onChange={(e) => setChecklist(c => ({ ...c, [k]: e.target.checked }))} />
                  <span>{label}</span>
                </label>
              ))}
            </div>

            {/* OBSERVAÇÕES */}
            <textarea data-testid="rede-modal-obs"
              value={observations}
              onChange={(e) => setObservations(e.target.value)}
              placeholder="Observações (opcional) — o que tentou, o que viu…"
              style={{
                width: "100%", marginTop: 12, padding: 9, fontSize: 12,
                border: "1.5px solid #e2e8f0", borderRadius: 8,
                fontFamily: "inherit", resize: "vertical", minHeight: 60,
              }} />

            {/* AÇÕES */}
            <div style={{
              display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap",
            }}>
              {aiData.can_avoid_escalation && (
                <button data-testid="rede-modal-avoid"
                  onClick={aiAvoided} disabled={busy}
                  style={{
                    flex: 1, padding: "10px 14px", border: "none",
                    borderRadius: 8, background: "#10b981", color: "white",
                    fontWeight: 700, fontSize: 13, cursor: "pointer",
                    minWidth: 200,
                  }}>
                  ✓ IA me ajudou · resolvo no campo
                </button>
              )}
              <button data-testid="rede-modal-escalate"
                onClick={escalate}
                disabled={busy || !allChecklistDone}
                title={allChecklistDone ? "" : "Marque o checklist primeiro"}
                style={{
                  flex: 1, padding: "10px 14px", border: "none",
                  borderRadius: 8,
                  background: allChecklistDone ? "#dc2626" : "#cbd5e1",
                  color: "white", fontWeight: 700, fontSize: 13,
                  cursor: allChecklistDone ? "pointer" : "not-allowed",
                  minWidth: 200,
                }}>
                ↑ ESCALAR PARA REDE
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
