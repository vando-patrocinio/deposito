import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot, User, Users, Search, Send, X, Loader2, Check, CheckCheck,
  Filter, MessageSquare, Clock, MoonStar, Hand, UserCheck,
  CheckCircle2, GraduationCap, ChevronDown, ChevronUp, Lightbulb,
  Wifi, WifiOff, Activity, Info, Signal, MapPin, Phone, CreditCard,
  AlertCircle, Sparkles, Lock,
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
  /* Avatar + presença do cliente vindo do WhatsApp (cache por phone). */
  const [contactProfiles, setContactProfiles] = useState({});
  const warmingRef = useRef(new Set());

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

  /* Warmer: para as conversas mais recentes do bucket atual,
     busca avatar/presença em background (com cache). */
  const warmContact = useCallback(async (phone) => {
    if (!phone || warmingRef.current.has(phone)) return;
    warmingRef.current.add(phone);
    try {
      const r = await api.waCustomerProfile(phone);
      setContactProfiles((m) => ({ ...m, [phone]: {
        avatar: r?.whatsapp?.avatar || null,
        presence: r?.whatsapp?.presence || "unknown",
        last_seen: r?.whatsapp?.last_seen || null,
        subscriber: r?.subscriber || null,
        olt_signal: r?.olt_signal || null,
        fetched_at: Date.now(),
      }}));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadConversations();
    loadAttendants();
    const id = setInterval(loadConversations, 6000);
    return () => clearInterval(id);
  }, [loadConversations, loadAttendants]);

  /* Quando as conversas atualizam, aquece avatares dos top 20 do bucket atual. */
  useEffect(() => {
    const top = conversations
      .filter((c) => c.bucket === bucket && !c.is_group)
      .slice(0, 20);
    top.forEach((c) => {
      const cached = contactProfiles[c.phone];
      // re-aquece se nunca foi buscado ou foi há mais de 2min (para presença)
      if (!cached || (Date.now() - cached.fetched_at) > 120000) {
        warmContact(c.phone);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations, bucket]);

  const filteredConvs = useMemo(() => {
    /* Se há busca, vasculha TODOS os buckets (não só o ativo). */
    const inBucket = search.trim()
      ? conversations
      : conversations.filter((c) => c.bucket === bucket);
    if (!search.trim()) return inBucket;
    const q = search.toLowerCase();
    return inBucket.filter((c) =>
      (c.phone || "").includes(q) ||
      (c.subscriber_name || "").toLowerCase().includes(q) ||
      (c.subscriber_external_code || "").toLowerCase().includes(q) ||
      (c.subscriber_branch || "").toLowerCase().includes(q) ||
      (c.push_name || "").toLowerCase().includes(q) ||
      (c.last_text || "").toLowerCase().includes(q) ||
      (c.assignee_name || "").toLowerCase().includes(q)
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
        contactProfiles={contactProfiles}
      />

      {/* COLUNA 3 — Thread aberta */}
      <ChatThread
        conv={selectedConv} attendants={attendants}
        contactProfile={selectedConv ? contactProfiles[selectedConv.phone] : null}
        onWarmContact={warmContact}
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
                              search, setSearch, loading, totalInBucket,
                              contactProfiles }) {
  const bucketLabel = BUCKETS.find((b) => b.id === bucket)?.label || bucket;
  return (
    <div data-testid="wa-conversation-list" style={{
      borderRight: "1px solid var(--border-default)",
      display: "flex", flexDirection: "column",
      background: "var(--bg-surface)",
      minHeight: 0,
    }}>
      <div style={{
        padding: "12px 14px", borderBottom: "1px solid var(--border-default)",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <Search size={14} strokeWidth={2} style={{ color: "var(--text-muted)" }} />
        <input value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder={search.trim()
                 ? "Buscar em todas as conversas..."
                 : `Buscar em ${bucketLabel.toLowerCase()}...`}
               data-testid="wa-search-input"
               style={{
                 flex: 1, border: "none", outline: "none", background: "transparent",
                 fontSize: 13, color: "var(--text-primary)",
               }} />
      </div>
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
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
                    profile={contactProfiles?.[c.phone]}
                    onClick={() => setSelectedPhone(c.phone)} />
        ))}
      </div>
    </div>
  );
}

function ConvRow({ conv, selected, onClick, profile }) {
  /* Card profissional inspirado no FocusChat: avatar grande + WA badge +
     status dot, nome do cliente em destaque, telefone abaixo, tag de filial,
     pílula do atendente e última msg com indicador de direção + unread. */
  // Prioriza: subscriber_name > push_name > phone
  const displayName = conv.subscriber_name || conv.push_name || `+${conv.phone}`;
  const isIdentified = !!conv.subscriber_name;
  const time = conv.last_message_at
    ? new Date(conv.last_message_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : "";
  const isAi = conv.assignee_role === "ai";
  // Avatar pode vir do backend (contact_avatar do bulk) OU do profile fetch (warming)
  const avatarSrc = conv.contact_avatar || profile?.avatar;
  const presence = profile?.presence;
  const online = presence === "available" || presence === "composing";
  const unread = conv.unread || 0;
  // Status do contato (dot bottom-right do avatar):
  // verde se online · laranja se aguardando atendente · azul se há unread · cinza default
  let statusColor = null;
  if (online) statusColor = "#22c55e";
  else if (conv.bucket === "aguardando") statusColor = "#f59e0b";
  else if (unread > 0) statusColor = "#0ea5e9";
  // Última msg: direção indica quem falou por último
  const dirIcon = conv.last_direction === "outbound" ? "▲" : "▼";
  const dirColor = conv.last_direction === "outbound" ? "#64748b" : "#0ea5e9";

  return (
    <button onClick={onClick}
            data-testid={`wa-conv-${conv.phone}`}
            style={{
              width: "100%", padding: "12px 14px",
              border: "none", borderBottom: "1px solid var(--border-default)",
              background: selected ? "var(--accent-soft)" : "transparent",
              borderLeft: selected ? "3px solid var(--accent)" : "3px solid transparent",
              cursor: "pointer", textAlign: "left",
              display: "flex", gap: 12, alignItems: "flex-start",
              transition: "background .15s",
            }}>
      {/* Avatar com WA badge bottom-left + status dot bottom-right */}
      <div style={{ position: "relative", flexShrink: 0, width: 46, height: 46 }}>
        <Avatar name={displayName} src={avatarSrc} isAi={false} size={46} />
        {/* WhatsApp badge */}
        <span title="WhatsApp" style={{
          position: "absolute", bottom: -1, left: -2,
          width: 16, height: 16, borderRadius: "50%",
          background: "#22c55e", color: "#fff",
          display: "grid", placeItems: "center",
          border: "2px solid var(--bg-surface)",
          boxShadow: "0 1px 2px rgba(0,0,0,.2)",
        }}>
          <svg width="9" height="9" viewBox="0 0 32 32" fill="currentColor">
            <path d="M16.001 0C7.165 0 .001 7.164.001 16c0 2.823.737 5.587 2.137 8.018L0 32l8.182-2.146A15.92 15.92 0 0 0 16 32c8.836 0 16-7.164 16-16S24.837 0 16.001 0Zm0 29.333c-2.45 0-4.84-.654-6.937-1.892l-.498-.295-5.151 1.35 1.376-5.016-.323-.515A13.282 13.282 0 0 1 2.668 16c0-7.353 5.98-13.333 13.333-13.333S29.334 8.647 29.334 16 23.354 29.333 16.001 29.333Zm7.292-9.984c-.4-.2-2.366-1.166-2.733-1.3-.367-.133-.633-.2-.9.2s-1.033 1.3-1.267 1.567c-.233.266-.466.3-.866.1-.4-.2-1.689-.622-3.217-1.984-1.189-1.06-1.992-2.368-2.225-2.768-.233-.4-.024-.617.176-.816.18-.18.4-.467.6-.7.2-.234.267-.4.4-.667.133-.266.067-.5-.033-.7-.1-.2-.9-2.167-1.233-2.967-.325-.778-.655-.672-.9-.685-.233-.011-.5-.013-.766-.013-.267 0-.7.1-1.067.5s-1.4 1.367-1.4 3.334 1.434 3.866 1.633 4.134c.2.267 2.817 4.3 6.834 6.034.955.412 1.7.659 2.281.844.958.305 1.83.262 2.52.158.769-.114 2.367-.967 2.7-1.9.333-.934.333-1.734.233-1.9-.1-.167-.367-.267-.767-.467Z"/>
          </svg>
        </span>
        {/* Status dot (online/aguardando/unread) */}
        {statusColor && (
          <span title={online ? "Online" : conv.bucket === "aguardando" ? "Aguardando" : "Não lidas"}
                style={{
                  position: "absolute", bottom: -1, right: -1,
                  width: 13, height: 13, borderRadius: "50%",
                  background: statusColor,
                  border: "2px solid var(--bg-surface)",
                }} />
        )}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Linha 1: nome + timestamp */}
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <strong style={{
            fontSize: 13.5, color: "var(--text-primary)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            flex: 1, minWidth: 0,
            fontWeight: unread > 0 ? 800 : 700,
          }}>{displayName}</strong>
          <span style={{ fontSize: 10, color: "var(--text-muted)",
                          flexShrink: 0, fontWeight: unread > 0 ? 700 : 400 }}>
            {time}
          </span>
        </div>

        {/* Linha 2: telefone (sempre) */}
        <div style={{ fontSize: 11, color: "var(--text-muted)",
                       marginTop: 1, fontFamily: "ui-monospace, monospace" }}>
          +{conv.phone}
          {conv.subscriber_external_code && (
            <span style={{ marginLeft: 6, color: "var(--text-muted)" }}>
              · cód <strong style={{ color: "var(--text-secondary)" }}>
                {conv.subscriber_external_code}
              </strong>
            </span>
          )}
        </div>

        {/* Linha 3: tag filial + assignee */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          marginTop: 6, flexWrap: "wrap",
        }}>
          {conv.subscriber_branch && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 3,
              padding: "2px 7px", borderRadius: 5,
              background: "rgba(100,116,139,.15)",
              color: "var(--text-secondary)",
              fontSize: 10, fontWeight: 700, letterSpacing: 0.3,
              textTransform: "uppercase",
            }}>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 22V8l9-6 9 6v14h-6v-7h-6v7H3Z"/>
              </svg>
              {conv.subscriber_branch}
            </span>
          )}
          {isIdentified && conv.subscriber_plan && (
            <span style={{
              padding: "2px 7px", borderRadius: 5,
              background: "rgba(13,148,136,.15)",
              color: "#0d9488",
              fontSize: 10, fontWeight: 700,
            }}>
              {conv.subscriber_plan}
            </span>
          )}
          {conv.assignee_name && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 3,
              marginLeft: "auto",
              padding: "3px 10px", borderRadius: 999,
              background: isAi
                ? "linear-gradient(135deg, #0d9488, #06b6d4)"
                : "linear-gradient(135deg, #0ea5e9, #0284c7)",
              color: "#fff",
              fontSize: 10, fontWeight: 800, letterSpacing: 0.3,
              maxWidth: 130,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {isAi ? <Bot size={9} strokeWidth={2.8} /> : <User size={9} strokeWidth={2.8} />}
              {conv.assignee_name}
            </span>
          )}
        </div>

        {/* Linha 4: última msg + direção + unread badge */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6, marginTop: 5,
        }}>
          <span style={{ color: dirColor, fontSize: 11, fontWeight: 800, flexShrink: 0 }}>
            {dirIcon}
          </span>
          <span style={{
            fontSize: 12,
            color: unread > 0 ? "var(--text-primary)" : "var(--text-secondary)",
            fontWeight: unread > 0 ? 600 : 400,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            flex: 1, minWidth: 0,
          }}>
            {conv.last_text}
          </span>
          {unread > 0 && (
            <span data-testid={`wa-unread-${conv.phone}`} style={{
              minWidth: 20, height: 20, padding: "0 6px",
              borderRadius: 999, background: "#22c55e",
              color: "#fff", fontSize: 10, fontWeight: 800,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
              boxShadow: "0 1px 3px rgba(34,197,94,.5)",
            }}>{unread > 99 ? "99+" : unread}</span>
          )}
        </div>

        {/* Indicador "Chat assumido por" — quando humano pegou */}
        {!isAi && conv.assignee_role === "human" && conv.last_direction === "outbound" && (
          <div style={{
            marginTop: 6, fontSize: 10,
            color: "var(--text-muted)",
            display: "flex", alignItems: "center", gap: 4,
            fontStyle: "italic",
          }}>
            <span style={{ color: "#f59e0b" }}>🔔</span>
            Chat assumido por: <strong>{conv.assignee_name}</strong>
          </div>
        )}
      </div>
    </button>
  );
}

/* ============================================================= */
function ChatThread({ conv, attendants, contactProfile, onWarmContact, onChange }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showAssign, setShowAssign] = useState(false);
  const [showCustomer, setShowCustomer] = useState(false);
  /* Coaching IA inline — buscado por (user, phone), aparece como bolhas
     internas no chat (somente o atendente logado vê). */
  const [coachings, setCoachings] = useState([]);
  const [coachingHidden, setCoachingHidden] = useState(false);
  const scrollRef = useRef(null);

  const loadMessages = useCallback(async () => {
    if (!conv) return;
    try {
      const r = await api.waBaileysConversationMessages(conv.phone);
      setMessages(r.items || []);
    } catch { /* ignore */ }
  }, [conv]);

  const loadCoachings = useCallback(async () => {
    if (!conv) return;
    try {
      const r = await api.centralIaCoachingForConversation(conv.phone);
      setCoachings(r.items || []);
    } catch { /* ignore */ }
  }, [conv]);

  useEffect(() => {
    loadMessages();
    loadCoachings();
    setCoachingHidden(false);
    if (!conv) return undefined;
    const id = setInterval(() => { loadMessages(); loadCoachings(); }, 4500);
    return () => clearInterval(id);
  }, [loadMessages, loadCoachings, conv]);

  /* Ao abrir uma conversa: assina presença + força refresh do perfil
     (avatar/online) a cada 25s + marca como visualizada (zera unread). */
  useEffect(() => {
    if (!conv) return undefined;
    let cancelled = false;
    const refresh = async () => {
      try {
        await api.waContactSubscribePresence(conv.phone).catch(() => {});
        if (!cancelled) await onWarmContact?.(conv.phone);
      } catch { /* ignore */ }
    };
    refresh();
    // Marca como visto imediatamente ao abrir
    api.waBaileysMarkSeen(conv.phone).catch(() => {});
    const id = setInterval(refresh, 25000);
    return () => { cancelled = true; clearInterval(id); };
  }, [conv, onWarmContact]);

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

  /* Timeline mesclada: mensagens reais (WhatsApp) + coaching INTERNO (só você vê),
     ordenado por created_at. Mantém este hook ANTES de qualquer early return
     pra atender a regra dos React Hooks. */
  const timeline = useMemo(() => {
    const items = [
      ...messages.map((m) => ({ _kind: "msg", _ts: m.created_at, ...m })),
      ...coachings.map((c) => ({
        _kind: "coaching", _ts: c.created_at || c.applied_at, ...c })),
    ];
    items.sort((a, b) => {
      const ta = a._ts || "";
      const tb = b._ts || "";
      return ta < tb ? -1 : ta > tb ? 1 : 0;
    });
    return items;
  }, [messages, coachings]);

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
  const presence = contactProfile?.presence;
  const online = presence === "available" || presence === "composing";
  const typing = presence === "composing";
  /* O subscriber vem do contactProfile (customer-profile endpoint) OU
     direto da conversa (lista bulk-enriched). Prefere o customer-profile
     porque ele tem o objeto completo (com pppoe_user, address). */
  const subscriber = contactProfile?.subscriber || (conv.subscriber_id ? {
    id: conv.subscriber_id,
    name: conv.subscriber_name,
    branch: conv.subscriber_branch,
    plan_name: conv.subscriber_plan,
    status: conv.subscriber_status,
    external_code: conv.subscriber_external_code,
    pppoe_user: conv.subscriber_pppoe,
  } : null);
  const oltSignal = contactProfile?.olt_signal;
  const lastSeen = contactProfile?.last_seen;
  /* Avatar: lista bulk-enrich vem em conv.contact_avatar; aqui pegamos da
     fresh-fetched customerProfile (que substitui a do bulk se mais novo). */
  const avatarSrc = contactProfile?.avatar || conv.contact_avatar;

  const unreadCoachings = coachings.filter((c) => !c.read).length;
  const totalCoachings = coachings.length;

  let presenceLabel = "—";
  let presenceColor = "var(--text-muted)";
  if (typing) { presenceLabel = "digitando…"; presenceColor = "#22c55e"; }
  else if (online) { presenceLabel = "online"; presenceColor = "#22c55e"; }
  else if (presence === "unavailable") {
    if (lastSeen) {
      try {
        const d = new Date(Number(lastSeen) * 1000);
        presenceLabel = "visto por último " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      } catch { presenceLabel = "offline"; }
    } else { presenceLabel = "offline"; }
  } else if (presence === "unknown") {
    presenceLabel = "presença desconhecida";
  }

  return (
    <div data-testid="wa-chat-thread" style={{
      display: "flex", flexDirection: "column",
      background: "var(--bg-surface-2)",
      minHeight: 0, // <- fix scroll: permite que o child com flex:1 encolha
      height: "100%",
    }}>
      {/* Header — clean, sóbrio, hierarquia clara */}
      <div style={{
        padding: "10px 18px",
        borderBottom: "1px solid var(--border-default)",
        background: "var(--bg-surface)",
        display: "flex", alignItems: "center", gap: 12,
        minHeight: 60,
      }}>
        {/* Avatar + status dot */}
        <div style={{ position: "relative", flexShrink: 0 }}>
          <Avatar name={name} src={avatarSrc} size={38} />
          {online && (
            <span style={{
              position: "absolute", bottom: 0, right: 0,
              width: 10, height: 10, borderRadius: "50%",
              background: "#22c55e", border: "2px solid var(--bg-surface)",
            }} />
          )}
        </div>

        {/* Identity block */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "nowrap" }}>
            <strong style={{
              fontSize: 14, fontWeight: 600, color: "var(--text-primary)",
              letterSpacing: "-0.01em",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              maxWidth: 220,
            }}>{name}</strong>
            <button onClick={() => setShowCustomer(true)}
                    data-testid="wa-customer-badge"
                    title={subscriber
                      ? "Ver informações completas do cliente (sinal, plano, débitos)"
                      : "Telefone não vinculado a nenhum cadastro — clique para verificar"}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      padding: "1px 8px", borderRadius: 4,
                      background: "transparent",
                      color: subscriber ? "var(--accent)" : "var(--text-muted)",
                      border: `1px solid ${subscriber ? "var(--accent)" : "var(--border-default)"}`,
                      fontSize: 10, fontWeight: 600, letterSpacing: 0.2,
                      cursor: "pointer",
                      lineHeight: 1.4,
                      whiteSpace: "nowrap",
                    }}>
              {subscriber
                ? (subscriber.plan_name ? `Cliente · ${subscriber.plan_name}` : "Cliente")
                : "Não vinculado"}
            </button>
          </div>
          <div style={{
            fontSize: 11, color: "var(--text-muted)",
            display: "flex", alignItems: "center", gap: 6, marginTop: 3,
          }}>
            <span className="mono">+{conv.phone}</span>
            <span style={{ opacity: 0.4 }}>·</span>
            <span style={{
              color: online ? "#16a34a" : "var(--text-muted)",
              fontWeight: online ? 600 : 400,
            }}>{presenceLabel}</span>
          </div>
        </div>

        {/* Assignee + actions — todos com a mesma altura e estilo sóbrio */}
        <div data-testid="wa-online-indicator" style={{ display: "none" }} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          {conv.assignee_name && (
            <span data-testid="wa-thread-assignee-badge" style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "6px 10px", height: 30, borderRadius: 6,
              background: "var(--bg-surface-2)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border-default)",
              fontSize: 11, fontWeight: 500,
              whiteSpace: "nowrap",
            }}>
              {isAi
                ? <Bot size={12} strokeWidth={2} style={{ color: "var(--accent)" }} />
                : <User size={12} strokeWidth={2} />}
              {conv.assignee_name}
            </span>
          )}
          {isAi ? (
            <button onClick={() => setShowAssign(true)} disabled={busy}
                    data-testid="wa-take-over-btn"
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 5,
                      padding: "6px 12px", height: 30, borderRadius: 6,
                      background: "var(--text-primary)",
                      color: "var(--bg-surface)",
                      border: "1px solid var(--text-primary)",
                      fontSize: 11, fontWeight: 600, cursor: busy ? "not-allowed" : "pointer",
                      opacity: busy ? 0.6 : 1,
                      whiteSpace: "nowrap",
                    }}>
              <Hand size={12} strokeWidth={2} /> Assumir
            </button>
          ) : (
            <button onClick={giveBackToAi} disabled={busy}
                    data-testid="wa-give-back-ai-btn"
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 5,
                      padding: "6px 12px", height: 30, borderRadius: 6,
                      background: "transparent",
                      color: "var(--text-secondary)",
                      border: "1px solid var(--border-default)",
                      fontSize: 11, fontWeight: 600, cursor: busy ? "not-allowed" : "pointer",
                      opacity: busy ? 0.6 : 1,
                      whiteSpace: "nowrap",
                    }}>
              <Bot size={12} strokeWidth={2} /> Devolver IA
            </button>
          )}
          <button onClick={finalize} disabled={busy}
                  data-testid="wa-finalize-btn"
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "6px 12px", height: 30, borderRadius: 6,
                    background: "transparent",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border-default)",
                    fontSize: 11, fontWeight: 600, cursor: busy ? "not-allowed" : "pointer",
                    opacity: busy ? 0.6 : 1,
                    whiteSpace: "nowrap",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = "var(--danger)";
                    e.currentTarget.style.borderColor = "var(--danger)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = "var(--text-secondary)";
                    e.currentTarget.style.borderColor = "var(--border-default)";
                  }}>
            <CheckCircle2 size={12} strokeWidth={2} /> Finalizar
          </button>
        </div>
      </div>

      {/* Modal de atribuição */}
      {showAssign && (
        <AssignModal attendants={attendants}
                      onPick={assignTo}
                      onClose={() => setShowAssign(false)} />
      )}

      {/* Modal informações do cliente */}
      {showCustomer && (
        <CustomerProfileModal
          phone={conv.phone}
          profile={contactProfile}
          onClose={() => setShowCustomer(false)}
        />
      )}

      {/* Mensagens */}
      <div ref={scrollRef}
           data-testid="wa-messages-scroll"
           style={{
             flex: 1, minHeight: 0,
             overflowY: "auto", padding: "16px 18px",
             background: "var(--bg-surface-2)",
             backgroundImage: "radial-gradient(circle, rgba(0,0,0,0.025) 1px, transparent 1px)",
             backgroundSize: "20px 20px",
           }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {timeline.map((it) => (
            it._kind === "coaching"
              ? <InternalCoachingBubble key={`c-${it.id}`} coach={it}
                  onAcknowledge={async () => {
                    try {
                      await api.centralIaCoachingAction(it.id, "acknowledged");
                      await loadCoachings();
                    } catch { /* ignore */ }
                  }}
                  onDismiss={async () => {
                    try {
                      await api.centralIaCoachingAction(it.id, "dismiss");
                      setCoachings((arr) => arr.filter((c) => c.id !== it.id));
                    } catch { /* ignore */ }
                  }}
                  onRead={async () => {
                    if (it.read) return;
                    try {
                      await api.centralIaCoachingAction(it.id, "read");
                      setCoachings((arr) => arr.map((c) =>
                        c.id === it.id ? { ...c, read: true } : c));
                    } catch { /* ignore */ }
                  }} />
              : <MsgBubble key={`m-${it.id}`} msg={it} />
          ))}
          {timeline.length === 0 && (
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
        display: "flex", gap: 8, alignItems: "center",
      }}>
        {/* Ícone Coaching IA à esquerda — só pra usuário humano (não-IA).
            Mostra contador de coachings pra essa conversa.
            Ao clicar: rola até o coaching não lido mais próximo OU mostra
            tooltip explicando que coaching é interno e nunca vai pro cliente. */}
        <button
          data-testid="wa-coaching-icon-btn"
          onClick={() => {
            const unread = coachings.find((c) => !c.read);
            const target = unread || coachings[coachings.length - 1];
            if (!target) {
              alert("Sem coaching ativo. Conversas com CSAT baixo geram dicas privadas automaticamente.");
              return;
            }
            const el = document.querySelector(`[data-coaching-id="${target.id}"]`);
            if (el) {
              el.scrollIntoView({ behavior: "smooth", block: "center" });
              el.style.outline = "2px solid #a855f7";
              setTimeout(() => { el.style.outline = ""; }, 1800);
            }
          }}
          title={totalCoachings === 0
            ? "Sem coaching para esta conversa"
            : `Coaching IA — ${totalCoachings} dica(s) interna(s) só pra você.\nNunca vai para o cliente.`}
          style={{
            position: "relative", flexShrink: 0,
            width: 38, height: 38, borderRadius: 10,
            border: "none", cursor: "pointer",
            display: "grid", placeItems: "center",
            background: totalCoachings > 0
              ? "linear-gradient(135deg, #a855f7, #7c3aed)"
              : "var(--bg-surface-2)",
            color: totalCoachings > 0 ? "#fff" : "var(--text-muted)",
            boxShadow: unreadCoachings > 0
              ? "0 0 0 3px rgba(168,85,247,.25)" : "none",
            transition: "all .2s",
          }}>
          <GraduationCap size={17} strokeWidth={2} />
          {unreadCoachings > 0 && (
            <span style={{
              position: "absolute", top: -4, right: -4,
              minWidth: 17, height: 17, padding: "0 4px",
              borderRadius: 999, background: "#dc2626", color: "#fff",
              fontSize: 9, fontWeight: 800,
              display: "grid", placeItems: "center",
              border: "2px solid var(--bg-surface)",
            }}>{unreadCoachings}</span>
          )}
        </button>
        <input className="input" placeholder={isAi
          ? "Assuma a conversa para responder manualmente..."
          : "Digite sua mensagem (vai pro cliente via WhatsApp)..."}
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

      <style>{`
        @keyframes wa-pulse { 0%,100% { transform:scale(1); opacity:1; }
          50% { transform:scale(1.25); opacity:.7; } }
        @keyframes wa-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

/* =============================================================
   InternalCoachingBubble — bolha INTERNA de coaching IA inline.
   • Aparece no meio do chat, com fundo roxo distintivo
   • Visível APENAS para o atendente logado (filtrado no backend por user_id)
   • Nunca vai pelo WhatsApp pro cliente
   • Label "🔒 SOMENTE VOCÊ VÊ" pra reforçar
============================================================= */
function InternalCoachingBubble({ coach, onRead, onAcknowledge, onDismiss }) {
  const [expanded, setExpanded] = useState(!coach.read);
  const [acting, setActing] = useState(false);
  const toneColor = coach.tone === "urgente" ? "#dc2626"
    : coach.tone === "positivo" ? "#16a34a" : "#a855f7";
  const time = coach.created_at
    ? new Date(coach.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : "";

  const handleExpand = () => {
    const willExpand = !expanded;
    setExpanded(willExpand);
    if (willExpand && !coach.read) onRead?.();
  };

  const wrap = async (fn) => {
    setActing(true);
    try { await fn(); } finally { setActing(false); }
  };

  return (
    <div data-testid={`wa-coaching-bubble-${coach.id}`}
         data-coaching-id={coach.id}
         style={{
           display: "flex", justifyContent: "center",
           padding: "4px 0",
         }}>
      <div style={{
        width: "85%", maxWidth: 560,
        borderRadius: 14,
        border: `1.5px dashed ${toneColor}`,
        background: `linear-gradient(135deg, ${toneColor}10, ${toneColor}05)`,
        overflow: "hidden",
        boxShadow: `0 1px 3px ${toneColor}20`,
        transition: "all .2s",
      }}>
        {/* Header — sempre visível */}
        <button onClick={handleExpand} style={{
          width: "100%", padding: "9px 13px", border: "none",
          background: "transparent", cursor: "pointer", textAlign: "left",
          display: "flex", alignItems: "center", gap: 9,
        }}>
          <div style={{
            width: 30, height: 30, borderRadius: 9,
            background: `linear-gradient(135deg, ${toneColor}, ${toneColor}cc)`,
            color: "#fff", display: "grid", placeItems: "center",
            flexShrink: 0,
            boxShadow: `0 2px 6px ${toneColor}40`,
          }}>
            <GraduationCap size={15} strokeWidth={2} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap",
            }}>
              <span style={{
                fontSize: 11, fontWeight: 800, color: toneColor,
                letterSpacing: 0.3, textTransform: "uppercase",
              }}>
                Coaching IA · {coach.tone || "construtivo"}
              </span>
              <span style={{
                padding: "1px 7px", borderRadius: 999,
                background: "rgba(0,0,0,.06)", color: "var(--text-muted)",
                fontSize: 9, fontWeight: 700, letterSpacing: 0.4,
                display: "inline-flex", alignItems: "center", gap: 3,
              }}>
                <Lock size={8} strokeWidth={2.5} /> SOMENTE VOCÊ VÊ · INTERNO
              </span>
              {!coach.read && (
                <span style={{
                  padding: "1px 7px", borderRadius: 999,
                  background: toneColor, color: "#fff",
                  fontSize: 9, fontWeight: 800, letterSpacing: 0.4,
                }}>NOVO</span>
              )}
            </div>
            <div style={{
              fontSize: 12.5, color: "var(--text-primary)", marginTop: 3,
              fontWeight: expanded ? 600 : 500,
            }}>
              {coach.summary_eval || coach.next_action
                || `CSAT ${coach.csat_at_time ?? "—"}/10 — clique para ver dicas`}
            </div>
          </div>
          <div style={{
            width: 24, height: 24, borderRadius: 999,
            background: toneColor, color: "#fff",
            display: "grid", placeItems: "center",
            fontSize: 10, fontWeight: 800, flexShrink: 0,
          }}>{coach.score?.toFixed?.(1) ?? coach.score}</div>
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>

        {/* Corpo expandido */}
        {expanded && (
          <div style={{
            padding: "10px 14px 12px",
            borderTop: `1px solid ${toneColor}30`,
            background: "rgba(255,255,255,.6)",
          }}>
            {coach.strengths?.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{
                  fontSize: 9, fontWeight: 800, color: "#16a34a",
                  textTransform: "uppercase", letterSpacing: 0.4,
                  marginBottom: 4,
                }}>✓ Você acertou em</div>
                {coach.strengths.map((s, i) => (
                  <div key={i} style={{
                    fontSize: 12, color: "var(--text-primary)",
                    paddingLeft: 12, marginBottom: 2,
                  }}>• {s}</div>
                ))}
              </div>
            )}
            {coach.improvements?.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{
                  fontSize: 9, fontWeight: 800, color: "#f59e0b",
                  textTransform: "uppercase", letterSpacing: 0.4,
                  marginBottom: 4,
                }}>→ Próxima vez, melhore em</div>
                {coach.improvements.map((s, i) => (
                  <div key={i} style={{
                    fontSize: 12, color: "var(--text-primary)",
                    paddingLeft: 12, marginBottom: 2,
                  }}>• {s}</div>
                ))}
              </div>
            )}
            {coach.next_action && (
              <div style={{
                padding: 9, borderRadius: 8,
                background: `${toneColor}15`,
                fontSize: 12, display: "flex", gap: 7,
                alignItems: "flex-start", marginBottom: 8,
              }}>
                <Lightbulb size={13} strokeWidth={1.75}
                            style={{ flexShrink: 0, marginTop: 1, color: toneColor }} />
                <div><strong>Próxima ação:</strong> {coach.next_action}</div>
              </div>
            )}
            <div style={{
              display: "flex", gap: 6, justifyContent: "flex-end",
              alignItems: "center",
              borderTop: "1px solid rgba(0,0,0,.05)",
              paddingTop: 8,
            }}>
              <span style={{ fontSize: 10, color: "var(--text-muted)",
                              marginRight: "auto" }}>
                {time && `${time} · `}Esta mensagem é privada, jamais vai pro cliente.
              </span>
              {!coach.acknowledged && (
                <button onClick={() => wrap(onAcknowledge)}
                        disabled={acting}
                        data-testid={`wa-coaching-ack-inline-${coach.id}`}
                        className="btn btn-primary btn-sm">
                  <Check size={11} /> Entendi
                </button>
              )}
              <button onClick={() => wrap(onDismiss)}
                      disabled={acting}
                      className="btn btn-ghost btn-sm">
                <X size={11} /> Dispensar
              </button>
              {coach.acknowledged && (
                <span style={{
                  fontSize: 10, color: "#16a34a", fontWeight: 700,
                  display: "flex", alignItems: "center", gap: 3,
                }}>
                  <Check size={11} /> Reconhecido
                </span>
              )}
            </div>
          </div>
        )}
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

/* =============================================================
   CustomerProfileModal — popup com 1-clique no badge "cliente"
   Mostra: nome, plano, status, débitos, endereço, sinal RX/TX SmartOLT
============================================================= */
function CustomerProfileModal({ phone, profile, onClose }) {
  const sub = profile?.subscriber;
  const signal = profile?.olt_signal;
  const wa = profile;
  const avatarSrc = profile?.avatar;
  const rx = signal?.rx_signal_dbm ?? signal?.rx ?? signal?.rx_power;
  const tx = signal?.tx_signal_dbm ?? signal?.tx ?? signal?.tx_power;
  const ontStatus = signal?.status || signal?.ont_status;

  const rxColor = (v) => {
    if (v == null) return "var(--text-muted)";
    const n = Number(v);
    if (Number.isNaN(n)) return "var(--text-muted)";
    if (n >= -25) return "#16a34a";
    if (n >= -27) return "#eab308";
    return "#dc2626";
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
      display: "grid", placeItems: "center", zIndex: 1100,
    }} data-testid="wa-customer-modal">
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg-surface)",
        padding: 0, borderRadius: 16, width: 540,
        maxHeight: "85vh", overflow: "auto",
        boxShadow: "0 20px 50px rgba(0,0,0,.4)",
      }}>
        {/* Header com avatar do WhatsApp */}
        <div style={{
          padding: "20px 22px",
          background: "linear-gradient(135deg, rgba(13,148,136,.10), rgba(6,182,212,.06))",
          borderBottom: "1px solid var(--border-default)",
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <Avatar name={sub?.name || `+${phone}`} src={avatarSrc} size={56} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 17, fontWeight: 800,
                           color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
              {sub?.name || "Cliente não identificado"}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2,
                           display: "flex", gap: 8, alignItems: "center",
                           fontFamily: "ui-monospace, monospace" }}>
              <Phone size={11} /> +{phone}
            </div>
            {sub?.external_code && (
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                Cód.: <span className="mono">{sub.external_code}</span>
              </div>
            )}
          </div>
          <button onClick={onClose} className="btn btn-ghost btn-sm">
            <X size={14} />
          </button>
        </div>

        <div style={{ padding: 18, display: "grid", gap: 14 }}>
          {!sub && (
            <div style={{
              padding: 14, borderRadius: 10,
              background: "rgba(245,158,11,.10)",
              border: "1px solid rgba(245,158,11,.30)",
              fontSize: 12, color: "var(--text-primary)",
              display: "flex", gap: 10, alignItems: "flex-start",
            }}>
              <AlertCircle size={14} strokeWidth={2} style={{ color: "#f59e0b", marginTop: 1 }} />
              <div>
                <strong>Telefone sem cadastro vinculado.</strong>
                <div style={{ color: "var(--text-muted)", marginTop: 3 }}>
                  Cadastre este cliente em Assinantes para que a IA puxe
                  automaticamente as informações nas próximas conversas.
                </div>
              </div>
            </div>
          )}

          {sub && (
            <>
              <Field icon={Info} label="Status">
                <span style={{
                  fontSize: 12, fontWeight: 700,
                  padding: "3px 10px", borderRadius: 999,
                  background: sub.status === "ativo" ? "rgba(34,197,94,.15)"
                    : sub.status === "bloqueado" ? "rgba(220,38,38,.15)"
                    : "rgba(148,163,184,.15)",
                  color: sub.status === "ativo" ? "#16a34a"
                    : sub.status === "bloqueado" ? "#dc2626"
                    : "#64748b",
                }}>{sub.status || "—"}</span>
              </Field>
              {sub.plan_name && (
                <Field icon={Sparkles} label="Plano">
                  <span style={{ fontSize: 13, fontWeight: 700 }}>{sub.plan_name}</span>
                </Field>
              )}
              {sub.branch && (
                <Field icon={Activity} label="Filial">
                  <span style={{ fontSize: 13 }}>{sub.branch}</span>
                </Field>
              )}
              {sub.address && (
                <Field icon={MapPin} label="Endereço">
                  <span style={{ fontSize: 13 }}>{sub.address}</span>
                </Field>
              )}
              {sub.pppoe_user && (
                <Field icon={User} label="Usuário PPPoE">
                  <span className="mono" style={{ fontSize: 12 }}>{sub.pppoe_user}</span>
                </Field>
              )}
              {(sub.debit_total != null || sub.debits) && (
                <Field icon={CreditCard} label="Débitos">
                  <span style={{
                    fontSize: 13, fontWeight: 700,
                    color: (sub.debit_total || 0) > 0 ? "#dc2626" : "#16a34a",
                  }}>
                    {sub.debit_total != null
                      ? new Intl.NumberFormat("pt-BR",
                            { style: "currency", currency: "BRL" }).format(sub.debit_total)
                      : (sub.debits || "—")}
                  </span>
                </Field>
              )}
            </>
          )}

          {/* SmartOLT — sinal RX/TX */}
          <div style={{
            padding: 14, borderRadius: 12,
            border: signal ? "1px solid rgba(13,148,136,.35)" : "1px solid var(--border-default)",
            background: signal ? "rgba(13,148,136,.06)" : "var(--bg-surface-2)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <Signal size={14} strokeWidth={2} style={{ color: "#0d9488" }} />
              <strong style={{ fontSize: 12, color: "#0d9488",
                                 textTransform: "uppercase", letterSpacing: 0.5 }}>
                SmartOLT — Sinal Óptico
              </strong>
              {ontStatus && (
                <span style={{
                  marginLeft: "auto",
                  padding: "2px 9px", borderRadius: 999,
                  background: String(ontStatus).toLowerCase().includes("online")
                    ? "rgba(34,197,94,.15)" : "rgba(220,38,38,.15)",
                  color: String(ontStatus).toLowerCase().includes("online")
                    ? "#16a34a" : "#dc2626",
                  fontSize: 10, fontWeight: 800, letterSpacing: 0.4,
                }}>{ontStatus}</span>
              )}
            </div>
            {signal ? (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <SignalCell label="RX (recepção)" value={rx} suffix="dBm" color={rxColor(rx)} />
                <SignalCell label="TX (envio)" value={tx} suffix="dBm" color="var(--text-primary)" />
                {signal.olt_name && (
                  <SignalCell label="OLT" value={signal.olt_name} />
                )}
                {signal.pon_port && (
                  <SignalCell label="Porta PON" value={signal.pon_port} />
                )}
                {signal.ont_serial && (
                  <SignalCell label="Serial ONT" value={signal.ont_serial} mono />
                )}
                {signal.uptime && (
                  <SignalCell label="Uptime" value={signal.uptime} />
                )}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {sub?.pppoe_user
                  ? "Buscando sinal na OLT… (configure SmartOLT em Integrações)"
                  : "Sem usuário PPPoE cadastrado pra buscar sinal."}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ icon: Ico, label, children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Ico size={13} strokeWidth={2} style={{ color: "var(--text-muted)" }} />
      <span style={{ fontSize: 11, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       minWidth: 90, fontWeight: 700 }}>{label}</span>
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
}

function SignalCell({ label, value, suffix, color, mono }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.4, fontWeight: 700 }}>
        {label}
      </div>
      <div style={{
        fontSize: 14, fontWeight: 800,
        color: color || "var(--text-primary)",
        fontFamily: mono ? "ui-monospace, monospace" : "inherit",
        marginTop: 2,
      }}>
        {value == null || value === "" ? "—" : value}
        {value != null && suffix && (
          <span style={{ fontSize: 10, color: "var(--text-muted)",
                          fontWeight: 600, marginLeft: 3 }}>{suffix}</span>
        )}
      </div>
    </div>
  );
}

