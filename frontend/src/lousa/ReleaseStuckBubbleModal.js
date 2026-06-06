/* =============================================================
   ReleaseStuckBubbleModal — botão vermelho de emergência.
   Quando uma "bolha" (ticket aberta) trava no app do técnico
   e ele não consegue finalizar, o admin libera manualmente.
   - Lista colaboradores com bolha presa
   - Confirma seleção + motivo (opcional)
   - Avisa: ação é registrada e notifica os demais admins
   - Só libera 1 por clique (se houver outra, repete a ação)
============================================================= */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { AlertTriangle, Unlock, Loader2, X } from "lucide-react";

export default function ReleaseStuckBubbleModal({ onClose, onReleased }) {
  const [loading, setLoading] = useState(true);
  const [stuck, setStuck] = useState([]);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api._client.get("/lousa/admin/stuck-tickets")
                            .then((x) => x.data);
      setStuck(r.items || []);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const doRelease = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await api._client.post(
        "/lousa/admin/release-stuck",
        {
          collaborator_id: selected.collaborator_id,
          reason: reason.trim() || null,
        },
      ).then((x) => x.data);
      await window.alert(`✓ Bolha de ${r.collaborator_name} foi liberada.\n\n`
            + "Ela voltou ao status 'pendente'. Todos os admins serão notificados.\n\n"
            + (stuck.length > 1
                ? "Há outras bolhas presas — clique no botão novamente."
                : ""));
      onReleased?.();
      onClose();
    } catch (e) {
      await window.alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div onClick={!busy ? onClose : undefined}
          data-testid="release-stuck-modal"
          style={{
            position: "fixed", inset: 0, zIndex: 1100,
            background: "rgba(2,6,23,0.7)",
            display: "grid", placeItems: "center", padding: 16,
          }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{
              background: "white", borderRadius: 14, padding: 22,
              maxWidth: 560, width: "100%", maxHeight: "88vh",
              overflowY: "auto",
              boxShadow: "0 25px 60px rgba(0,0,0,0.35)",
            }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", marginBottom: 14 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <div style={{
              width: 44, height: 44, borderRadius: 10,
              background: "#fee2e2", color: "#dc2626",
              display: "grid", placeItems: "center",
            }}>
              <AlertTriangle size={22} strokeWidth={2.2} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700,
                            color: "#0f172a" }}>
                Liberar bolha presa
              </h3>
              <p style={{ margin: "2px 0 0", fontSize: 11,
                           color: "#64748b" }}>
                Use apenas se o técnico não consegue finalizar a bolha.
              </p>
            </div>
          </div>
          {!busy && (
            <button onClick={onClose} aria-label="Fechar"
                     style={{
                       border: "none", background: "transparent",
                       cursor: "pointer", fontSize: 22, color: "#64748b",
                     }}>×</button>
          )}
        </div>

        {/* Aviso */}
        <div style={{
          padding: 12, borderRadius: 8, background: "#fff7ed",
          border: "1px solid #fed7aa", color: "#9a3412",
          fontSize: 12, marginBottom: 14, lineHeight: 1.5,
        }}>
          Esta ação será <strong>registrada nos logs</strong> e enviará uma
          <strong> notificação a todos os administradores</strong>. A bolha
          voltará ao status <em>pendente</em> e poderá ser reaberta pelo
          técnico. <strong>Libera apenas 1 bolha por clique</strong> — se houver
          outras presas, clique no botão novamente.
        </div>

        {/* Lista de bolhas presas */}
        {loading ? (
          <div style={{ padding: 30, textAlign: "center", color: "#94a3b8" }}>
            <Loader2 size={24} className="wa-spin" />
            <div style={{ marginTop: 8, fontSize: 12 }}>
              Buscando bolhas presas...
            </div>
          </div>
        ) : error ? (
          <div style={{ padding: 12, borderRadius: 8, background: "#fee2e2",
                         color: "#991b1b", fontSize: 12 }}>
            {error}
          </div>
        ) : stuck.length === 0 ? (
          <div style={{ padding: 30, textAlign: "center", color: "#16a34a",
                         fontSize: 13 }}>
            ✓ Nenhuma bolha presa no momento.
          </div>
        ) : (
          <>
            <label style={{
              display: "block", fontSize: 11, fontWeight: 700, color: "#64748b",
              textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6,
            }}>
              Selecione o colaborador com bolha presa
            </label>
            <div style={{
              display: "grid", gap: 6,
              maxHeight: 260, overflowY: "auto", marginBottom: 14,
            }}>
              {stuck.map((s) => {
                const active = selected?.collaborator_id === s.collaborator_id;
                return (
                  <button
                    key={s.collaborator_id}
                    onClick={() => setSelected(s)}
                    data-testid={`stuck-coll-${s.collaborator_id}`}
                    style={{
                      textAlign: "left", padding: 12,
                      borderRadius: 8, cursor: "pointer",
                      background: active ? "#fee2e2" : "white",
                      border: "2px solid " + (active ? "#dc2626" : "#e2e8f0"),
                      transition: "all 120ms",
                    }}>
                    <div style={{ display: "flex", justifyContent: "space-between",
                                    alignItems: "center", marginBottom: 4 }}>
                      <strong style={{ fontSize: 13, color: "#0f172a" }}>
                        {s.collaborator_name}
                      </strong>
                      <span style={{
                        fontSize: 10, padding: "2px 8px", borderRadius: 999,
                        background: (s.minutes_stuck || 0) > 60 ? "#dc2626" : "#f59e0b",
                        color: "white", fontWeight: 700,
                      }}>
                        presa há {fmtMinutes(s.minutes_stuck)}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: "#64748b" }}>
                      Cliente: <strong>{s.client_name}</strong>
                      {s.client_address && <> · {s.client_address}</>}
                    </div>
                    <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>
                      {s.type} · prioridade {s.priority}
                    </div>
                  </button>
                );
              })}
            </div>

            {selected && (
              <>
                <label style={{
                  display: "block", fontSize: 11, fontWeight: 700,
                  color: "#64748b", textTransform: "uppercase",
                  letterSpacing: 0.5, marginBottom: 6,
                }}>
                  Motivo (opcional, mas recomendado)
                </label>
                <input
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Ex: técnico perdeu sinal; app travou; cliente cancelou..."
                  data-testid="stuck-reason-input"
                  disabled={busy}
                  style={{
                    width: "100%", padding: 10, borderRadius: 8,
                    border: "1px solid #cbd5e1", fontSize: 13,
                    marginBottom: 14,
                  }}
                />

                {!confirming ? (
                  <button
                    onClick={() => setConfirming(true)}
                    data-testid="stuck-trigger-confirm"
                    style={{
                      width: "100%", padding: "12px 16px", borderRadius: 10,
                      border: "none", background: "#dc2626", color: "white",
                      fontSize: 14, fontWeight: 800, cursor: "pointer",
                      display: "inline-flex", alignItems: "center",
                      justifyContent: "center", gap: 8,
                      letterSpacing: 0.3,
                    }}>
                    <Unlock size={16} /> Liberar bolha de {selected.collaborator_name}
                  </button>
                ) : (
                  <div style={{
                    padding: 14, borderRadius: 10,
                    background: "#fef2f2", border: "2px solid #dc2626",
                  }}>
                    <p style={{ margin: "0 0 12px", fontSize: 13,
                                 color: "#7f1d1d", fontWeight: 600,
                                 lineHeight: 1.5 }}>
                      Confirma a liberação da bolha de
                      <strong> {selected.client_name}</strong> do técnico
                      <strong> {selected.collaborator_name}</strong>?
                      <br/>
                      <span style={{ fontSize: 11, color: "#991b1b",
                                       fontWeight: 500 }}>
                        Esta ação será registrada no seu nome e
                        notificará os outros administradores.
                      </span>
                    </p>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        onClick={() => setConfirming(false)}
                        disabled={busy}
                        data-testid="stuck-cancel-btn"
                        style={{
                          flex: 1, padding: "9px 14px", borderRadius: 8,
                          border: "1.5px solid #cbd5e1", background: "white",
                          color: "#475569", fontWeight: 700, fontSize: 13,
                          cursor: busy ? "wait" : "pointer",
                        }}>NÃO</button>
                      <button
                        onClick={doRelease}
                        disabled={busy}
                        data-testid="stuck-confirm-btn"
                        style={{
                          flex: 1, padding: "9px 14px", borderRadius: 8,
                          border: "none", background: "#dc2626", color: "white",
                          fontWeight: 800, fontSize: 13,
                          cursor: busy ? "wait" : "pointer",
                          display: "inline-flex", alignItems: "center",
                          justifyContent: "center", gap: 6,
                        }}>
                        {busy
                          ? <><Loader2 size={14} className="wa-spin" /> Liberando…</>
                          : <>SIM, LIBERAR</>}
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}

        <style>{`
          .wa-spin { animation: wa-spin 1s linear infinite; }
          @keyframes wa-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
        `}</style>
      </div>
    </div>
  );
}

function fmtMinutes(min) {
  if (min == null) return "—";
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  if (h < 24) return `${h}h${m ? ` ${m}m` : ""}`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}
