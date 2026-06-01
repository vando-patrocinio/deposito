/* OsClientChat — iter183.2
 *
 * Chat rápido do técnico (PWA) com o cliente da OS via WhatsApp interno
 * (sidecar Baileys). SEM carregamento de histórico: só mostra as
 * mensagens que rolarem A PARTIR do momento em que o técnico abriu o
 * chat — pra tirar dúvidas pontuais do serviço atual.
 *
 * - Não puxa thread antiga
 * - Polling 6s SÓ pra capturar respostas novas do cliente
 * - Mensagens enviadas aparecem imediatamente
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Send, X, MessageSquare, Loader2 } from "lucide-react";
import { api } from "@/api";
import { toast } from "sonner";

function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("pt-BR",
                                  { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function fmtPhonePretty(p) {
  const d = String(p || "").replace(/\D/g, "");
  if (d.length === 13) {
    return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 5)} ${d.slice(5, 9)}-${d.slice(9)}`;
  }
  if (d.length === 12) {
    return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 8)}-${d.slice(8)}`;
  }
  return p;
}

export default function OsClientChat({
  open, onClose, collabId, collabName, phone, clientName,
}) {
  // Mensagens da sessão atual (não inclui histórico)
  const [messages, setMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const [text, setText] = useState("");
  // Presença do cliente: "available" | "composing" | "recording" | ...
  const [presence, setPresence] = useState("unknown");
  const scrollRef = useRef(null);
  // Marca o instante em que o chat foi aberto para filtrar respostas novas
  const openedAtRef = useRef(null);
  // IDs já adicionados localmente (evita duplicar quando o polling traz a msg outbound)
  const seenIdsRef = useRef(new Set());

  // Limpa estado ao fechar/reabrir
  useEffect(() => {
    if (open) {
      openedAtRef.current = new Date().toISOString();
      setMessages([]);
      seenIdsRef.current = new Set();
      setPresence("unknown");
    }
  }, [open]);

  // Polling de presença (escrevendo/gravando) a cada 4s
  const pollPresence = useCallback(async () => {
    if (!collabId || !phone) return;
    try {
      const r = await api.waBaileysPublicPresence(collabId, phone);
      setPresence(r?.presence || "unknown");
    } catch {
      // silencia
    }
  }, [collabId, phone]);

  useEffect(() => {
    if (!open) return;
    pollPresence();
    const t = setInterval(pollPresence, 4000);
    return () => clearInterval(t);
  }, [open, pollPresence]);

  const pollInbound = useCallback(async () => {
    if (!collabId || !phone || !openedAtRef.current) return;
    try {
      // Pega últimas 20 mensagens (limit baixo — só pra detectar novas)
      const r = await api.waBaileysPublicMessages(collabId, phone, 20);
      const items = r.items || [];
      const cutoff = openedAtRef.current;
      const fresh = items.filter((m) => {
        if (!m.created_at) return false;
        if (m.created_at < cutoff) return false;
        if (seenIdsRef.current.has(m.id)) return false;
        return true;
      });
      if (fresh.length) {
        fresh.forEach((m) => seenIdsRef.current.add(m.id));
        setMessages((prev) => [...prev, ...fresh]);
      }
    } catch {
      // silencia — chat continua funcional pra envio
    }
  }, [collabId, phone]);

  // Polling 6s pra capturar respostas
  useEffect(() => {
    if (!open) return;
    const t = setInterval(pollInbound, 6000);
    return () => clearInterval(t);
  }, [open, pollInbound]);

  // Auto-scroll pro fim
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length]);

  async function send() {
    const t = (text || "").trim();
    if (!t || sending) return;
    setSending(true);
    // Adiciona localmente imediatamente (UX otimista)
    const localId = `local-${Date.now()}`;
    setMessages((prev) => [...prev, {
      id: localId,
      direction: "outbound",
      text: t,
      created_at: new Date().toISOString(),
      delivery_status: "sending",
    }]);
    setText("");
    try {
      await api.waBaileysPublicSend(collabId, phone, t);
      // Marca como entregue
      setMessages((prev) => prev.map((m) =>
        m.id === localId ? { ...m, delivery_status: "sent" } : m,
      ));
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message
                    || "Falha ao enviar mensagem";
      toast.error(msg);
      // Marca como falhou
      setMessages((prev) => prev.map((m) =>
        m.id === localId ? { ...m, delivery_status: "failed" } : m,
      ));
    } finally {
      setSending(false);
    }
  }

  if (!open) return null;

  return (
    <div data-testid="os-chat-overlay"
         style={{
           position: "fixed", inset: 0, zIndex: 9999,
           background: "rgba(15,23,42,0.55)",
           display: "flex", flexDirection: "column",
         }}>
      <div style={{
        background: "white", flex: 1, display: "flex",
        flexDirection: "column", margin: "max(env(safe-area-inset-top), 8px) 0 0 0",
        borderTopLeftRadius: 16, borderTopRightRadius: 16,
        overflow: "hidden", boxShadow: "0 -10px 30px rgba(0,0,0,0.25)",
      }}>
        {/* Header */}
        <div style={{
          padding: "12px 14px",
          background: "#065f46", color: "white",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <MessageSquare size={18} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 800,
                            whiteSpace: "nowrap", overflow: "hidden",
                            textOverflow: "ellipsis" }}>
              {clientName || "Cliente"}
            </div>
            <div data-testid="os-chat-presence"
                 style={{ fontSize: 11, opacity: 0.9,
                            display: "flex", alignItems: "center", gap: 4,
                            minHeight: 14 }}>
              {presence === "composing" && (
                <>
                  <span style={{ color: "#fbbf24" }}>✏️</span>
                  <span style={{ fontStyle: "italic" }}>
                    escrevendo…
                  </span>
                </>
              )}
              {presence === "recording" && (
                <>
                  <span style={{ color: "#fbbf24" }}>🎙</span>
                  <span style={{ fontStyle: "italic" }}>
                    gravando áudio…
                  </span>
                </>
              )}
              {presence !== "composing" && presence !== "recording" && (
                <>conversa do momento</>
              )}
            </div>
            {collabName && (
              <div style={{ fontSize: 10, opacity: 0.75, marginTop: 2 }}>
                atendendo como <strong>{collabName}</strong>
              </div>
            )}
          </div>
          <button data-testid="os-chat-close"
            onClick={onClose}
            style={{
              background: "rgba(255,255,255,0.15)",
              border: 0, color: "white", padding: 8,
              borderRadius: 8, cursor: "pointer",
              display: "grid", placeItems: "center",
            }}>
            <X size={18} />
          </button>
        </div>

        {/* Messages */}
        <div ref={scrollRef}
             data-testid="os-chat-messages"
             style={{
               flex: 1, overflowY: "auto", padding: "14px 12px",
               background: "#ece5dd", display: "flex",
               flexDirection: "column", gap: 8,
             }}>
          {messages.length === 0 && (
            <div style={{ textAlign: "center", color: "#64748b",
                            padding: 40, fontSize: 13,
                            maxWidth: 280, alignSelf: "center" }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>💬</div>
              Envie uma mensagem pra tirar dúvidas com o cliente.
              <br />
              <span style={{ fontSize: 11, opacity: 0.7 }}>
                Histórico anterior fica no painel do gestor.
              </span>
            </div>
          )}
          {(() => {
            // Heurística "lida": quando há QUALQUER inbound após um outbound,
            // marcamos todos os outbounds anteriores ao último inbound como lidos.
            const lastInboundAt = (() => {
              for (let i = messages.length - 1; i >= 0; i--) {
                if (messages[i].direction === "inbound") {
                  return messages[i].created_at;
                }
              }
              return null;
            })();
            return messages.map((m, idx) => {
              const isOut = m.direction === "outbound";
              const isRead = isOut && lastInboundAt
                              && m.created_at && m.created_at <= lastInboundAt
                              && m.delivery_status !== "failed"
                              && m.delivery_status !== "sending";
              return (
                <div key={m.id || idx}
                     data-testid={`os-chat-msg-${idx}`}
                     style={{
                       alignSelf: isOut ? "flex-end" : "flex-start",
                       maxWidth: "82%",
                       padding: "8px 12px",
                       background: isOut ? "#dcf8c6" : "white",
                       borderRadius: 10,
                       boxShadow: "0 1px 1px rgba(0,0,0,0.08)",
                       fontSize: 14, lineHeight: 1.4,
                       wordBreak: "break-word",
                       whiteSpace: "pre-wrap",
                       opacity: m.delivery_status === "sending" ? 0.65 : 1,
                     }}>
                  {m.text || m.body || ""}
                  <div style={{
                    fontSize: 10, color: "#64748b",
                    textAlign: "right", marginTop: 4,
                    display: "flex", alignItems: "center",
                    justifyContent: "flex-end", gap: 4,
                  }}>
                    <span>{fmtTime(m.created_at)}</span>
                    {isOut && m.delivery_status === "sending" && (
                      <span>· enviando…</span>
                    )}
                    {isOut && m.delivery_status === "failed" && (
                      <span style={{ color: "#dc2626" }}>· falhou</span>
                    )}
                    {isOut && isRead && (
                      <span data-testid={`os-chat-read-${idx}`}
                            style={{ color: "#0ea5e9", fontWeight: 700,
                                       letterSpacing: -1 }}
                            title="Lida pelo cliente">
                        ✓✓
                      </span>
                    )}
                    {isOut && !isRead && m.delivery_status === "sent" && (
                      <span style={{ color: "#94a3b8", letterSpacing: -1 }}
                            title="Enviada">
                        ✓
                      </span>
                    )}
                  </div>
                </div>
              );
            });
          })()}
        </div>

        {/* Composer */}
        <div style={{
          padding: "10px 12px",
          background: "#f0f2f5",
          borderTop: "1px solid #e2e8f0",
          display: "flex", alignItems: "flex-end", gap: 8,
          paddingBottom: "max(env(safe-area-inset-bottom, 0), 10px)",
        }}>
          <textarea
            data-testid="os-chat-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Digite sua mensagem…"
            rows={1}
            style={{
              flex: 1, resize: "none", maxHeight: 120,
              padding: "10px 12px", fontSize: 15,
              border: "1px solid #cbd5e1", borderRadius: 20,
              background: "white", outline: "none",
              fontFamily: "inherit",
            }} />
          <button
            data-testid="os-chat-send"
            onClick={send}
            disabled={sending || !text.trim()}
            style={{
              background: sending || !text.trim() ? "#94a3b8" : "#0d9488",
              color: "white", border: 0, borderRadius: "50%",
              width: 44, height: 44, display: "grid",
              placeItems: "center", cursor: "pointer",
              opacity: sending || !text.trim() ? 0.7 : 1,
              transition: "background 0.15s",
            }}>
            {sending ? <Loader2 size={18} className="animate-spin" />
                      : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  );
}
