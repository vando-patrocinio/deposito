/* NeoChatFab.js — Floating chat NEO acessível em qualquer tela do admin.
 *
 * UX:
 *  - FAB no canto inferior direito (z-index alto)
 *  - Clicar abre janela 380x540 com chat
 *  - Salva session_id em sessionStorage (mantém conversa enquanto a aba estiver aberta)
 *  - Histórico carregado ao abrir
 *  - Suporte a markdown leve (negrito **x**)
 *
 * Como usar:
 *   import NeoChatFab from "@/NeoChatFab";
 *   <NeoChatFab />     // só renderiza para gestor/admin/auditor
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Bot, X, Send, Sparkles, MessageCircle, Loader2,
  ChevronDown, RefreshCw,
} from "lucide-react";
import { api } from "@/api";

const SESSION_KEY = "neo_chat_session_id";

const SUGGESTIONS = [
  "KPIs da Isabella últimos 7 dias",
  "Quantos tickets o Álvaro resolveu hoje?",
  "Quanto a Pâmela cobrou este mês?",
  "Top intents da Secretaria semana",
  "Últimos relatórios gerados",
  "Agendamentos ativos",
];

function renderMarkdown(text) {
  if (!text) return null;
  // **bold** → <strong>; quebras de linha → <br/>
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (/^\*\*[^*]+\*\*$/.test(p)) {
      return <strong key={i}>{p.slice(2, -2)}</strong>;
    }
    return p.split("\n").flatMap((line, j, arr) => [
      <React.Fragment key={`${i}-${j}`}>{line}</React.Fragment>,
      j < arr.length - 1 ? <br key={`${i}-${j}-br`} /> : null,
    ]);
  });
}

function MessageBubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div data-testid={`neo-msg-${msg.role}`} style={{
      display: "flex", flexDirection: isUser ? "row-reverse" : "row",
      gap: 8, marginBottom: 10, alignItems: "flex-start",
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%",
        background: isUser ? "#3b82f6" : "linear-gradient(135deg, #0d9488, #06b6d4)",
        color: "#fff", display: "grid", placeItems: "center", flexShrink: 0,
      }}>
        {isUser ? <span style={{ fontSize: 12, fontWeight: 700 }}>EU</span> : <Bot size={14} />}
      </div>
      <div style={{
        background: isUser ? "#dbeafe" : "#f1f5f9",
        color: "#0f172a",
        padding: "8px 12px", borderRadius: 12, maxWidth: 270,
        fontSize: 13, lineHeight: 1.5,
        borderTopLeftRadius: isUser ? 12 : 4,
        borderTopRightRadius: isUser ? 4 : 12,
      }}>
        {renderMarkdown(msg.text)}
        {msg.tool && msg.tool !== "freeform" && (
          <div style={{
            marginTop: 6, paddingTop: 6, borderTop: "1px solid rgba(0,0,0,0.06)",
            fontSize: 10, color: "#64748b", display: "flex", alignItems: "center", gap: 4,
          }}>
            <Sparkles size={9} /> via <code style={{ fontFamily: "monospace" }}>{msg.tool}</code>
          </div>
        )}
      </div>
    </div>
  );
}

export default function NeoChatFab({ initiallyOpen = false }) {
  const [open, setOpen] = useState(initiallyOpen);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => {
    try { return window.sessionStorage.getItem(SESSION_KEY) || null; } catch { return null; }
  });
  const scrollRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }, 40);
  }, []);

  // Carrega histórico ao abrir
  useEffect(() => {
    if (!open || !sessionId) return;
    api.neoChatHistory(sessionId, 50).then((r) => {
      setMessages(r?.items || []);
      scrollToBottom();
    }).catch(() => {});
  }, [open, sessionId, scrollToBottom]);

  const send = async (text) => {
    const q = (text || input).trim();
    if (!q) return;
    setInput("");
    const userMsg = { role: "user", text: q, at: new Date().toISOString() };
    setMessages((p) => [...p, userMsg]);
    setLoading(true);
    scrollToBottom();
    try {
      const r = await api.neoChatAsk({ question: q, session_id: sessionId });
      if (r?.session_id && r.session_id !== sessionId) {
        setSessionId(r.session_id);
        try { window.sessionStorage.setItem(SESSION_KEY, r.session_id); } catch {}
      }
      setMessages((p) => [...p, {
        role: "assistant", text: r?.answer || "(sem resposta)",
        tool: r?.tool, at: new Date().toISOString(),
      }]);
    } catch (e) {
      setMessages((p) => [...p, {
        role: "assistant",
        text: `Erro: ${e?.response?.data?.detail || e.message || "falha ao chamar NEO"}`,
        at: new Date().toISOString(),
      }]);
    } finally {
      setLoading(false);
      scrollToBottom();
    }
  };

  const clearSession = () => {
    try { window.sessionStorage.removeItem(SESSION_KEY); } catch {}
    setSessionId(null);
    setMessages([]);
  };

  return (
    <>
      {/* FAB Button */}
      {!open && (
        <button
          data-testid="neo-fab-open"
          onClick={() => setOpen(true)}
          title="Abrir NEO"
          style={{
            position: "fixed", bottom: 24, right: 24, zIndex: 9999,
            width: 56, height: 56, borderRadius: "50%",
            background: "linear-gradient(135deg, #0d9488, #06b6d4)",
            color: "#fff", border: 0, cursor: "pointer",
            boxShadow: "0 8px 24px rgba(13,148,136,.45)",
            display: "grid", placeItems: "center",
            transition: "transform .2s, box-shadow .2s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = "scale(1.08)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
        >
          <Bot size={26} strokeWidth={2} />
          <span style={{
            position: "absolute", top: 4, right: 4,
            width: 10, height: 10, borderRadius: "50%",
            background: "#22c55e", border: "2px solid white",
          }} />
        </button>
      )}

      {/* Chat Window */}
      {open && (
        <div data-testid="neo-chat-window" style={{
          position: "fixed", bottom: 20, right: 20, zIndex: 9999,
          width: 380, height: 540, borderRadius: 16,
          background: "var(--bg-surface, #ffffff)",
          border: "1px solid var(--border-default, #e2e8f0)",
          boxShadow: "0 20px 50px rgba(15,23,42,.25)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}>
          {/* Header */}
          <div style={{
            padding: "12px 14px",
            background: "linear-gradient(135deg, #0d9488, #06b6d4)",
            color: "#fff", display: "flex", alignItems: "center", gap: 10,
          }}>
            <div style={{
              width: 32, height: 32, borderRadius: 10,
              background: "rgba(255,255,255,.18)",
              display: "grid", placeItems: "center",
            }}>
              <Bot size={18} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 800, fontSize: 14 }}>NEO</div>
              <div style={{ fontSize: 10, opacity: 0.9 }}>
                Orquestrador IA · Conectado a todas as IAs
              </div>
            </div>
            <button data-testid="neo-fab-refresh" onClick={clearSession}
                    style={{ background: "transparent", border: 0, color: "#fff",
                      cursor: "pointer", padding: 6 }} title="Nova conversa">
              <RefreshCw size={14} />
            </button>
            <button data-testid="neo-fab-close" onClick={() => setOpen(false)}
                    style={{ background: "transparent", border: 0, color: "#fff",
                      cursor: "pointer", padding: 6 }} title="Fechar">
              <X size={16} />
            </button>
          </div>

          {/* Messages */}
          <div ref={scrollRef} data-testid="neo-messages" style={{
            flex: 1, overflowY: "auto", padding: "12px 14px",
            background: "var(--bg-surface-2, #fafbfc)",
          }}>
            {messages.length === 0 && (
              <div style={{ textAlign: "center", padding: 16, color: "#64748b", fontSize: 12 }}>
                <Bot size={36} style={{ opacity: 0.4, marginBottom: 8 }} />
                <div style={{ fontWeight: 700, marginBottom: 6, fontSize: 13, color: "#0f172a" }}>
                  Oi! Sou o NEO.
                </div>
                <div style={{ marginBottom: 12 }}>
                  Pergunte sobre Isabella, Álvaro, Pâmela ou Secretaria.
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {SUGGESTIONS.slice(0, 4).map((s, i) => (
                    <button key={i} data-testid={`neo-suggestion-${i}`}
                            onClick={() => send(s)}
                            style={{
                              fontSize: 11, padding: "6px 10px",
                              background: "white", border: "1px solid #e2e8f0",
                              borderRadius: 8, cursor: "pointer", textAlign: "left",
                              color: "#0f172a", fontWeight: 600,
                            }}>
                      <MessageCircle size={10} style={{ display: "inline", marginRight: 4 }} />
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => <MessageBubble key={i} msg={m} />)}
            {loading && (
              <div data-testid="neo-loading" style={{
                display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
                color: "#0d9488", fontSize: 12,
              }}>
                <Loader2 size={14} className="animate-spin" />
                NEO está pensando…
              </div>
            )}
          </div>

          {/* Input */}
          <form onSubmit={(e) => { e.preventDefault(); send(); }} style={{
            padding: 10, borderTop: "1px solid var(--border-default, #e2e8f0)",
            display: "flex", gap: 6, background: "var(--bg-surface, #fff)",
          }}>
            <input
              data-testid="neo-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Pergunte ao NEO…"
              disabled={loading}
              style={{
                flex: 1, padding: "10px 12px", borderRadius: 8,
                border: "1px solid var(--border-default, #e2e8f0)",
                background: "var(--bg-surface, #fff)", color: "var(--text-primary, #0f172a)",
                fontSize: 13, outline: "none",
              }}
            />
            <button data-testid="neo-send" type="submit" disabled={loading || !input.trim()}
                    style={{
                      padding: "10px 12px", borderRadius: 8, border: 0,
                      background: loading ? "#94a3b8" : "linear-gradient(135deg, #0d9488, #06b6d4)",
                      color: "#fff", cursor: loading ? "wait" : "pointer",
                      display: "grid", placeItems: "center",
                    }}>
              <Send size={14} />
            </button>
          </form>
        </div>
      )}
    </>
  );
}
