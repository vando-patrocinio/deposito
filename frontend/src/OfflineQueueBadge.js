/* OfflineQueueBadge — iter183
 *
 * Badge flutuante / linha de status mostrando cadastros pendentes de
 * sincronização. Usado na home do PWA do técnico.
 *
 * - Listener em onChange + online/offline do navegador
 * - Click → expande mostrando os itens + botão "Reenviar agora"
 * - Auto-sync ao voltar online (já tratado em offlineQueue.startAutoSync)
 */
import React, { useEffect, useState, useCallback } from "react";
import { CloudOff, RefreshCw, X, AlertTriangle, CheckCircle2 } from "lucide-react";
import outbox from "@/utils/offlineQueue";

const API_BASE = process.env.REACT_APP_BACKEND_URL || "";

function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return ""; }
}

export default function OfflineQueueBadge({ collabId, compact = false }) {
  const [items, setItems] = useState([]);
  const [online, setOnline] = useState(
    typeof navigator !== "undefined" ? navigator.onLine : true,
  );
  const [expanded, setExpanded] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const reload = useCallback(async () => {
    try {
      const pend = await outbox.listPending(collabId || null);
      setItems(pend);
    } catch { /* ignore */ }
  }, [collabId]);

  useEffect(() => {
    reload();
    const off = outbox.onChange(reload);
    const onOn = () => setOnline(true);
    const onOff = () => setOnline(false);
    if (typeof window !== "undefined") {
      window.addEventListener("online", onOn);
      window.addEventListener("offline", onOff);
    }
    return () => {
      off();
      if (typeof window !== "undefined") {
        window.removeEventListener("online", onOn);
        window.removeEventListener("offline", onOff);
      }
    };
  }, [reload]);

  // Filtra apenas os que não foram sincronizados
  const pending = items.filter((i) => i.status !== "synced");
  const failed = pending.filter((i) => i.status === "failed"
                                          || i.status === "conflict");

  async function handleSync() {
    if (!online) return;
    setSyncing(true);
    try {
      await outbox.syncAll(API_BASE);
      await reload();
    } finally {
      setSyncing(false);
    }
  }

  async function handleDiscard(id) {
    if (!window.confirm("Descartar este cadastro? Esta ação não pode ser desfeita.")) return;
    await outbox.remove(id);
    await reload();
  }

  if (pending.length === 0 && online) return null;

  // Modo compacto: só linha de status pequena (Header da home)
  if (compact && !expanded) {
    return (
      <button
        data-testid="offline-queue-pill"
        onClick={() => setExpanded(true)}
        style={{
          background: !online ? "#fef3c7" : pending.length ? "#dbeafe" : "white",
          border: `1px solid ${!online ? "#fde68a" : pending.length ? "#bfdbfe" : "#e2e8f0"}`,
          borderRadius: 999, padding: "4px 10px", fontSize: 11,
          fontWeight: 700, cursor: "pointer",
          color: !online ? "#92400e" : pending.length ? "#1e40af" : "#475569",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
        {!online && <CloudOff size={12} />}
        {!online && "Offline"}
        {!online && pending.length > 0 && (
          <span style={{ opacity: 0.5, margin: "0 2px" }}>·</span>
        )}
        {pending.length > 0 && (
          <>
            {online && <RefreshCw size={12} className={syncing ? "animate-spin" : ""} />}
            {pending.length} pendente{pending.length === 1 ? "" : "s"}
          </>
        )}
      </button>
    );
  }

  // Modo expandido: lista completa em overlay
  return (
    <div data-testid="offline-queue-panel"
         style={{
           position: "fixed", inset: 0, zIndex: 9990,
           background: "rgba(15,23,42,0.55)",
           display: "flex", justifyContent: "center", alignItems: "flex-end",
         }}
         onClick={(e) => {
           if (e.target === e.currentTarget) setExpanded(false);
         }}>
      <div style={{
        background: "white", width: "100%", maxWidth: 560,
        maxHeight: "80vh", overflowY: "auto",
        borderTopLeftRadius: 16, borderTopRightRadius: 16,
        padding: "16px 16px 20px",
        boxShadow: "0 -10px 30px rgba(0,0,0,0.25)",
      }}>
        <div style={{ display: "flex", alignItems: "center",
                        marginBottom: 12, gap: 10 }}>
          <CloudOff size={20} style={{ color: online ? "#0ea5e9" : "#dc2626" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
              Cadastros offline
            </div>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              {online
                ? "Conectado — toque em 'Sincronizar' pra enviar"
                : "Sem internet — enviam automaticamente ao voltar"}
            </div>
          </div>
          <button data-testid="offline-queue-close"
            onClick={() => setExpanded(false)}
            style={{
              background: "#f1f5f9", border: 0, padding: 8,
              borderRadius: 8, cursor: "pointer",
              display: "grid", placeItems: "center",
            }}>
            <X size={16} />
          </button>
        </div>

        {pending.length === 0 && (
          <div style={{ padding: 20, textAlign: "center",
                          color: "#64748b", fontSize: 13 }}>
            <CheckCircle2 size={28} style={{ color: "#16a34a", margin: "0 auto 8px",
                                                  display: "block" }} />
            Nada na fila. Todos os cadastros foram enviados.
          </div>
        )}

        {pending.map((item) => (
          <div key={item.id}
               data-testid={`offline-item-${item.id}`}
               style={{
                 padding: "12px",
                 background: item.status === "conflict" ? "#fef2f2"
                            : item.status === "failed" ? "#fef9c3"
                            : "#f8fafc",
                 border: `1px solid ${
                   item.status === "conflict" ? "#fecaca"
                   : item.status === "failed" ? "#fef08a"
                   : "#e2e8f0"
                 }`,
                 borderRadius: 10, marginBottom: 8,
                 display: "flex", gap: 10, alignItems: "flex-start",
               }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a",
                              textTransform: "uppercase", letterSpacing: 0.5,
                              marginBottom: 2 }}>
                {item.kind}
                {item.status === "sending" && (
                  <span style={{ color: "#0ea5e9", marginLeft: 6 }}>
                    enviando…
                  </span>
                )}
                {item.status === "conflict" && (
                  <span style={{ color: "#dc2626", marginLeft: 6 }}>
                    conflito
                  </span>
                )}
                {item.status === "failed" && (
                  <span style={{ color: "#a16207", marginLeft: 6 }}>
                    falhou ({item.attempts}x)
                  </span>
                )}
              </div>
              <div style={{ fontSize: 13, color: "#0f172a", marginBottom: 4 }}>
                {item.description || "Cadastro de rede"}
              </div>
              <div style={{ fontSize: 10, color: "#64748b" }}>
                {fmtTime(item.created_at)}
                {item.last_error && (
                  <span style={{ color: "#dc2626", marginLeft: 6 }}>
                    · {item.last_error.slice(0, 60)}
                  </span>
                )}
              </div>
            </div>
            <button onClick={() => handleDiscard(item.id)}
                    data-testid={`offline-discard-${item.id}`}
                    title="Descartar"
                    style={{ background: "transparent", border: 0,
                                color: "#64748b", padding: 4, cursor: "pointer" }}>
              <X size={14} />
            </button>
          </div>
        ))}

        {failed.length > 0 && online && (
          <div style={{ display: "flex", alignItems: "center",
                          gap: 8, padding: 10, marginTop: 6,
                          background: "#fef3c7", borderRadius: 8,
                          fontSize: 11, color: "#92400e" }}>
            <AlertTriangle size={14} />
            <span>
              {failed.length} item(s) com erro. Toque em “Sincronizar agora”
              para tentar novamente.
            </span>
          </div>
        )}

        <button
          data-testid="offline-queue-sync-btn"
          onClick={handleSync}
          disabled={!online || syncing || pending.length === 0}
          style={{
            width: "100%", padding: "12px",
            background: !online || syncing ? "#94a3b8" : "#0d9488",
            color: "white", border: 0, borderRadius: 10,
            fontSize: 14, fontWeight: 700, cursor: "pointer",
            opacity: !online || syncing || pending.length === 0 ? 0.6 : 1,
            display: "flex", alignItems: "center",
            justifyContent: "center", gap: 8,
            marginTop: 12,
          }}>
          <RefreshCw size={16} className={syncing ? "animate-spin" : ""} />
          {syncing ? "Sincronizando…"
                    : !online ? "Sem internet"
                    : `Sincronizar agora (${pending.length})`}
        </button>
      </div>
    </div>
  );
}
