import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot, User, Users, Search, Send, X, Loader2, Check, CheckCheck,
  PhoneCall, Filter, MessageSquare, Clock, MoonStar, Hand, UserCheck,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   FocusChat-style 3-column WhatsApp UI
   col 1: bucket sidebar (Automático/Aguardando/Fora de hora/Manual/Grupo)
   col 2: lista de conversas do bucket selecionado
   col 3: thread aberta + envio + atribuição
============================================================= */

const BUCKETS = [
  { id: "automatico",  label: "Automático",   icon: Bot,       color: "#0d9488" },
  { id: "aguardando",  label: "Aguardando",   icon: Clock,     color: "#f59e0b" },
  { id: "fora_de_hora",label: "Fora de hora", icon: MoonStar,  color: "#6366f1" },
  { id: "manual",      label: "Manual",       icon: Hand,      color: "#0ea5e9" },
  { id: "grupo",       label: "Grupo",        icon: Users,     color: "#94a3b8" },
];

function avatarColor(name) {
  let h = 0;
  for (const c of (name || "")) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 55%, 55%)`;
}

function Avatar({ name, src, size = 38, isAi = false, ring = false }) {
  const initials = (name || "?").split(/\s+/)
    .filter(Boolean).slice(0, 2)
    .map((p) => p[0]).join("").toUpperCase() || "?";
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: src ? `url(${src}) center/cover` : avatarColor(name),
      color: "#fff",
      display: "grid", placeItems: "center",
      fontSize: size * 0.36, fontWeight: 700,
      flexShrink: 0,
      border: ring ? "2px solid #16a34a" : "none",
      position: "relative",
    }}>
      {!src && initials}
      {isAi && (
        <span style={{
          position: "absolute", bottom: -2, right: -2,
          background: "#0d9488", color: "#fff",
          width: size * 0.45, height: size * 0.45, borderRadius: "50%",
          display: "grid", placeItems: "center",
          border: "2px solid var(--bg-surface)",
        }}>
          <Bot size={size * 0.22} strokeWidth={2.5} />
        </span>
      )}
    </div>
  );
}

export default function WhatsAppChatLayout() {
  const [bucket, setBucket] = useState("automatico");
  const [conversations, setConversations] = useState([]);
  const [buckets, setBuckets] = useState({});
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [search, setSearch] = useState("");
  const [attendants, setAttendants] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadConversations = useCallback(async () => {
    try {
      const r = await api.waBaileysConversations();
      setConversations(r.items || []);
      setBuckets(r.buckets || {});
      setLoading(false);
    } catch (e) {
      console.error(e); setLoading(false);
    }
  }, []);

  const loadAttendants = useCallback(async () => {
    try {
      const r = await api.waBaileysAttendants();
      setAttendants(r.items || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadConversations();
    loadAttendants();
    const id = setInterval(loadConversations, 6000);
    return () => clearInterval(id);
  }, [loadConversations, loadAttendants]);

  const filteredConvs = useMemo(() => {
    const inBucket = conversations.filter((c) => c.bucket === bucket);
    if (!search.trim()) return inBucket;
    const q = search.toLowerCase();
    return inBucket.filter((c) =>
      (c.phone || "").includes(q) ||
      (c.subscriber_name || "").toLowerCase().includes(q) ||
      (c.push_name || "").toLowerCase().includes(q) ||
      (c.last_text || "").toLowerCase().includes(q)
    );
  }, [conversations, bucket, search]);

  const selectedConv = useMemo(
    () => conversations.find((c) => c.phone === selectedPhone) || null,
    [conversations, selectedPhone]
  );

  return (
    <div data-testid="wa-chat-layout" style={{
      display: "grid",
      gridTemplateColumns: "220px 360px 1fr",
      gap: 0, height: "calc(100vh - 220px)", minHeight: 560,
      border: "1px solid var(--border-default)", borderRadius: 14,
      overflow: "hidden", background: "var(--bg-surface)",
    }}>
      {/* COLUNA 1 — Buckets */}
      <BucketSidebar bucket={bucket} setBucket={setBucket} counts={buckets} />

      {/* COLUNA 2 — Lista de conversas */}
      <ConversationList
        bucket={bucket} convs={filteredConvs} selectedPhone={selectedPhone}
        setSelectedPhone={setSelectedPhone} search={search} setSearch={setSearch}
        loading={loading} totalInBucket={buckets[bucket] || 0}
      />

      {/* COLUNA 3 — Thread aberta */}
      <ChatThread
        conv={selectedConv} attendants={attendants}
        onChange={loadConversations}
      />
    </div>
  );
}

/* ============================================================= */
function BucketSidebar({ bucket, setBucket, counts }) {
  return (
    <div data-testid="wa-buckets-sidebar" style={{
      background: "var(--bg-surface-2)",
      borderRight: "1px solid var(--border-default)",
      padding: "14px 8px", display: "flex", flexDirection: "column", gap: 4,
    }}>
      <div style={{
        fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.6, padding: "6px 10px 10px",
      }}>
        Atendimentos
      </div>
      {BUCKETS.map((b) => {
        const Ico = b.icon;
        const active = bucket === b.id;
        const n = counts[b.id] || 0;
        return (
          <button key={b.id}
                  onClick={() => setBucket(b.id)}
                  data-testid={`wa-bucket-${b.id}`}
                  style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "10px 12px", borderRadius: 10,
            background: active ? `${b.color}1F` : "transparent",
            border: active ? `1px solid ${b.color}55` : "1px solid transparent",
            color: active ? b.color : "var(--text-primary)",
            cursor: "pointer", textAlign: "left", fontSize: 13,
            fontWeight: active ? 700 : 500,
            transition: "all .15s",
          }}>
            <Ico size={16} strokeWidth={active ? 2.2 : 1.75}
                  style={{ color: active ? b.color : "var(--text-muted)" }} />
            <span style={{ flex: 1 }}>{b.label}</span>
            <span style={{
              padding: "2px 9px", borderRadius: 999,
              background: active ? b.color : "var(--bg-surface)",
              color: active ? "#fff" : "var(--text-secondary)",
              fontSize: 11, fontWeight: 800, minWidth: 24, textAlign: "center",
            }}>{n}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ============================================================= */
function ConversationList({ bucket, convs, selectedPhone, setSelectedPhone,
                              search, setSearch, loading, totalInBucket }) {
  const bucketLabel = BUCKETS.find((b) => b.id === bucket)?.label || bucket;
  return (
    <div data-testid="wa-conversation-list" style={{
      borderRight: "1px solid var(--border-default)",
      display: "flex", flexDirection: "column",
      background: "var(--bg-surface)",
    }}>
      <div style={{
        padding: "12px 14px", borderBottom: "1px solid var(--border-default)",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <Search size={14} strokeWidth={2} style={{ color: "var(--text-muted)" }} />
        <input value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder={`Buscar em ${bucketLabel.toLowerCase()}...`}
               data-testid="wa-search-input"
               style={{
                 flex: 1, border: "none", outline: "none", background: "transparent",
                 fontSize: 13, color: "var(--text-primary)",
               }} />
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading ? (
          <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
            <Loader2 size={20} style={{ animation: "wa-spin 1s linear infinite" }} />
            <div style={{ fontSize: 11, marginTop: 6 }}>Carregando...</div>
          </div>
        ) : convs.length === 0 ? (
          <div style={{ padding: "40px 20px", textAlign: "center", color: "var(--text-muted)" }}>
            <MessageSquare size={28} strokeWidth={1.5} style={{ opacity: 0.5 }} />
            <div style={{ fontSize: 12, marginTop: 8 }}>
              {totalInBucket === 0
                ? `Sem conversas em "${bucketLabel}"`
                : "Nenhuma conversa bate com a busca"}
            </div>
          </div>
        ) : convs.map((c) => (
          <ConvRow key={c.phone} conv={c}
                    selected={selectedPhone === c.phone}
                    onClick={() => setSelectedPhone(c.phone)} />
        ))}
      </div>
    </div>
  );
}

function ConvRow({ conv, selected, onClick }) {
  const name = conv.subscriber_name || conv.push_name || `+${conv.phone}`;
  const time = conv.last_message_at
    ? new Date(conv.last_message_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : "";
  const isAi = conv.assignee_role === "ai";
  return (
    <button onClick={onClick}
            data-testid={`wa-conv-${conv.phone}`}
            style={{
              width: "100%", padding: "12px 14px",
              border: "none", borderBottom: "1px solid var(--border-default)",
              background: selected ? "var(--accent-soft)" : "transparent",
              borderLeft: selected ? "3px solid var(--accent)" : "3px solid transparent",
              cursor: "pointer", textAlign: "left",
              display: "flex", gap: 11, alignItems: "flex-start",
            }}>
      <Avatar name={conv.subscriber_name || conv.push_name}
              src={conv.assignee_avatar} isAi={false} size={42} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <strong style={{
            fontSize: 13, color: "var(--text-primary)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            flex: 1, minWidth: 0,
          }}>{name}</strong>
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{time}</span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)",
                       marginTop: 1, fontFamily: "ui-monospace, monospace" }}>
          +{conv.phone}
        </div>
        <div style={{
          fontSize: 12, color: "var(--text-secondary)",
          marginTop: 5,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          maxWidth: 250,
        }}>
          {conv.last_direction === "outbound" ? "→ " : ""}{conv.last_text}
        </div>
        {conv.assignee_name && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            marginTop: 6, padding: "2px 8px", borderRadius: 999,
            background: isAi ? "rgba(13,148,136,.15)" : "rgba(14,165,233,.15)",
            color: isAi ? "#0d9488" : "#0284c7",
            fontSize: 10, fontWeight: 800, letterSpacing: 0.3,
          }}>
            {isAi ? <Bot size={9} strokeWidth={2.5} /> : <User size={9} strokeWidth={2.5} />}
            {conv.assignee_name}
          </span>
        )}
      </div>
    </button>
  );
}

/* ============================================================= */
function ChatThread({ conv, attendants, onChange }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showAssign, setShowAssign] = useState(false);
  const scrollRef = useRef(null);

  const loadMessages = useCallback(async () => {
    if (!conv) return;
    try {
      const r = await api.waBaileysConversationMessages(conv.phone);
      setMessages(r.items || []);
    } catch { /* ignore */ }
  }, [conv]);

  useEffect(() => {
    loadMessages();
    if (!conv) return undefined;
    const id = setInterval(loadMessages, 4500);
    return () => clearInterval(id);
  }, [loadMessages, conv]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!conv || !text.trim()) return;
    setSending(true);
    try {
      await api.waBaileysSend(conv.phone, text.trim());
      setText("");
      await loadMessages();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setSending(false); }
  };

  const assignTo = async (userId) => {
    setBusy(true);
    try {
      await api.waBaileysAssignConversation(conv.phone, {
        assignee_user_id: userId, assignee_role: "human",
      });
      setShowAssign(false);
      onChange();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const giveBackToAi = async () => {
    setBusy(true);
    try {
      await api.waBaileysAssignConversation(conv.phone, {
        assignee_user_id: null, assignee_role: "ai",
      });
      onChange();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const finalize = async () => {
    if (!window.confirm("Finalizar essa conversa? Vai sair da fila de atendimento.")) return;
    setBusy(true);
    try {
      await api.waBaileysFinalizeConversation(conv.phone);
      onChange();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  if (!conv) {
    return (
      <div style={{
        display: "grid", placeItems: "center",
        color: "var(--text-muted)", padding: 40, textAlign: "center",
      }}>
        <div>
          <MessageSquare size={48} strokeWidth={1.25} style={{ opacity: 0.4 }} />
          <p style={{ marginTop: 14, fontSize: 13 }}>
            Selecione uma conversa para começar
          </p>
        </div>
      </div>
    );
  }

  const name = conv.subscriber_name || conv.push_name || `+${conv.phone}`;
  const isAi = conv.assignee_role === "ai";

  return (
    <div data-testid="wa-chat-thread" style={{
      display: "flex", flexDirection: "column",
      background: "var(--bg-surface-2)",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--border-default)",
        background: "var(--bg-surface)",
        display: "flex", alignItems: "center", gap: 12,
      }}>
        <Avatar name={name} size={42} />
        <div style={{ flex: 1 }}>
          <strong style={{ fontSize: 14 }}>{name}</strong>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            <span className="mono">+{conv.phone}</span>
            {conv.subscriber_name && conv.subscriber_id && (
              <> · <span style={{ color: "var(--accent)" }}>cadastrado</span></>
            )}
          </div>
        </div>
        {/* Atribuição badge + actions */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {conv.assignee_name && (
            <span data-testid="wa-thread-assignee-badge" style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "5px 11px", borderRadius: 999,
              background: isAi ? "rgba(13,148,136,.15)" : "rgba(14,165,233,.15)",
              color: isAi ? "#0d9488" : "#0284c7",
              fontSize: 11, fontWeight: 800,
            }}>
              {isAi ? <Bot size={11} strokeWidth={2.5} /> : <User size={11} strokeWidth={2.5} />}
              {conv.assignee_name}
            </span>
          )}
          {isAi ? (
            <button onClick={() => setShowAssign(true)} disabled={busy}
                    className="btn btn-primary btn-sm"
                    data-testid="wa-take-over-btn">
              <Hand size={12} /> Assumir
            </button>
          ) : (
            <button onClick={giveBackToAi} disabled={busy}
                    className="btn btn-ghost btn-sm"
                    data-testid="wa-give-back-ai-btn">
              <Bot size={12} /> Devolver IA
            </button>
          )}
          <button onClick={finalize} disabled={busy}
                  className="btn btn-ghost btn-sm"
                  data-testid="wa-finalize-btn"
                  style={{ color: "var(--danger)" }}>
            <CheckCircle2 size={12} /> Finalizar
          </button>
        </div>
      </div>

      {/* Modal de atribuição */}
      {showAssign && (
        <AssignModal attendants={attendants}
                      onPick={assignTo}
                      onClose={() => setShowAssign(false)} />
      )}

      {/* Mensagens */}
      <div ref={scrollRef} style={{
        flex: 1, overflowY: "auto", padding: "16px 18px",
        background: "var(--bg-surface-2)",
        backgroundImage: "radial-gradient(circle, rgba(0,0,0,0.025) 1px, transparent 1px)",
        backgroundSize: "20px 20px",
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {messages.map((m) => <MsgBubble key={m.id} msg={m} />)}
          {messages.length === 0 && (
            <div style={{ textAlign: "center", color: "var(--text-muted)",
                           fontSize: 12, padding: 30 }}>
              Sem mensagens nesta conversa ainda.
            </div>
          )}
        </div>
      </div>

      {/* Composer */}
      <div style={{
        padding: 12, borderTop: "1px solid var(--border-default)",
        background: "var(--bg-surface)",
        display: "flex", gap: 8,
      }}>
        <input className="input" placeholder={isAi
          ? "Assuma a conversa para responder manualmente..."
          : "Digite sua mensagem..."}
          value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !sending && send()}
          disabled={isAi}
          data-testid="wa-composer-input"
          style={{ flex: 1 }} />
        <button onClick={send} disabled={sending || !text.trim() || isAi}
                className="btn btn-primary btn-sm"
                data-testid="wa-composer-send">
          <Send size={13} /> {sending ? "..." : "Enviar"}
        </button>
      </div>
    </div>
  );
}

function MsgBubble({ msg }) {
  const out = msg.direction === "outbound";
  const isAi = !!msg.auto_reply;
  const time = msg.created_at
    ? new Date(msg.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : "";
  return (
    <div style={{
      display: "flex", justifyContent: out ? "flex-end" : "flex-start",
    }}>
      <div style={{
        maxWidth: "70%",
        padding: "8px 12px", borderRadius: out ? "12px 12px 4px 12px" : "12px 12px 12px 4px",
        background: out ? (isAi ? "#bae6fd" : "#dcfce7") : "#fff",
        color: "#0f172a",
        border: "1px solid rgba(0,0,0,.05)",
        fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap",
        boxShadow: "0 1px 2px rgba(0,0,0,.05)",
      }}>
        {out && isAi && (
          <div style={{ fontSize: 9, fontWeight: 800, color: "#0369a1",
                         marginBottom: 3, textTransform: "uppercase",
                         letterSpacing: 0.5 }}>
            Isabella IA
          </div>
        )}
        <div>{msg.text}</div>
        <div style={{
          fontSize: 9, color: "#64748b", marginTop: 3,
          display: "flex", alignItems: "center", gap: 3, justifyContent: "flex-end",
        }}>
          <span>{time}</span>
          {out && (msg.delivery_status === "sent"
            ? <CheckCheck size={11} style={{ color: "#0ea5e9" }} />
            : msg.delivery_status === "failed"
              ? <span style={{ color: "#dc2626", fontSize: 9 }}>!</span>
              : <Check size={11} />)}
        </div>
      </div>
    </div>
  );
}

function AssignModal({ attendants, onPick, onClose }) {
  const [search, setSearch] = useState("");
  const filtered = attendants.filter((a) =>
    !a.is_ai_agent && a.email !== "isabella@ia.local" &&
    ((a.name || "").toLowerCase().includes(search.toLowerCase()) ||
     (a.email || "").toLowerCase().includes(search.toLowerCase()))
  );
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.5)",
      display: "grid", placeItems: "center", zIndex: 1000,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg-surface)",
        padding: 18, borderRadius: 14, width: 420,
        maxHeight: "80vh", overflow: "auto",
        boxShadow: "0 10px 30px rgba(0,0,0,.3)",
      }} data-testid="wa-assign-modal">
        <div style={{ display: "flex", alignItems: "center",
                       justifyContent: "space-between", marginBottom: 10 }}>
          <strong style={{ fontSize: 15 }}>Atribuir conversa</strong>
          <button onClick={onClose} className="btn btn-ghost btn-sm">
            <X size={14} />
          </button>
        </div>
        <input className="input" placeholder="Buscar atendente..." autoFocus
               value={search} onChange={(e) => setSearch(e.target.value)}
               style={{ marginBottom: 10 }} />
        <div style={{ display: "grid", gap: 4 }}>
          {filtered.map((a) => (
            <button key={a.id} onClick={() => onPick(a.id)}
                    data-testid={`wa-assign-pick-${a.id}`}
                    style={{
                      display: "flex", alignItems: "center", gap: 10,
                      padding: "10px 12px", borderRadius: 10,
                      border: "1px solid var(--border-default)",
                      background: "var(--bg-surface-2)",
                      cursor: "pointer", textAlign: "left",
                    }}>
              <Avatar name={a.name} src={a.avatar_url || a.google_picture} size={32} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>{a.name}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  {a.email}
                </div>
              </div>
              <UserCheck size={14} style={{ color: "var(--accent)" }} />
            </button>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: 20, textAlign: "center",
                           color: "var(--text-muted)", fontSize: 12 }}>
              Nenhum atendente encontrado.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
