import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot, User, Users, Search, Send, X, Loader2, Check, CheckCheck,
  Filter, MessageSquare, Clock, MoonStar, Hand, UserCheck,
  CheckCircle2, GraduationCap, ChevronDown, ChevronUp, Lightbulb,
  Wifi, WifiOff, Activity, Info, Signal, MapPin, Phone, CreditCard,
  AlertCircle, Sparkles, Lock, AlertTriangle, ClipboardList, RefreshCw,
  Settings, RotateCcw, Image, ImagePlus, Paperclip, FileDown, CalendarPlus, Mic, Play, Pause,
} from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/AuthContext";
import AgentConfigModal from "@/AgentConfigModal";
import WaChatFilterPopover, {
  makeBlankFilter, countActiveFilters, CHANNEL_OPTIONS,
} from "@/WaChatFilterPopover";
import { chimeNewMessage, notifyBrowser, requestNotificationPermission } from "@/chatSounds";
import { WaWallpaper } from "@/WaWallpaper";

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
  const { user: authUser } = useAuth();
  const [bucket, setBucket] = useState("automatico");
  const [conversations, setConversations] = useState([]);
  const lastUnreadRef = React.useRef({}); // phone -> unread_count anterior
  const firstLoadRef = React.useRef(true);
  const [buckets, setBuckets] = useState({});
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [search, setSearch] = useState("");
  const [attendants, setAttendants] = useState([]);
  const [loading, setLoading] = useState(true);
  /* Wallpaper customizado da empresa (data URL). Fallback estático Ligo. */
  const [wallpaperUrl, setWallpaperUrl] = useState(null);
  /* Avatar + presença do cliente vindo do WhatsApp (cache por phone). */
  const [contactProfiles, setContactProfiles] = useState({});
  const warmingRef = useRef(new Set());

  /* Filtro avançado de conversas — popover ao estilo BotZap/ChatGuru.
     Persistido em localStorage com TTL de 30min. Substitui o antigo
     "attendantFilter" como o canal central de filtros. */
  const ADV_FILTER_TTL_MS = 30 * 60 * 1000;
  const [advFilter, setAdvFilter] = useState(() => {
    if (typeof window === "undefined") return makeBlankFilter();
    try {
      const raw = window.localStorage.getItem("smartprov_chat_filter");
      if (!raw) return makeBlankFilter();
      const parsed = JSON.parse(raw);
      if (parsed.__set_at && (Date.now() - parsed.__set_at) > ADV_FILTER_TTL_MS) {
        window.localStorage.removeItem("smartprov_chat_filter");
        return makeBlankFilter();
      }
      return { ...makeBlankFilter(), ...parsed };
    } catch { return makeBlankFilter(); }
  });

  function persistAdvFilter(f) {
    setAdvFilter(f);
    try {
      const isBlank = countActiveFilters(f) === 0;
      if (isBlank) {
        window.localStorage.removeItem("smartprov_chat_filter");
      } else {
        window.localStorage.setItem(
          "smartprov_chat_filter",
          JSON.stringify({ ...f, __set_at: Date.now() }),
        );
      }
    } catch { /* ignore */ }
  }

  /* Filtro de atendente vindo do Central IA (deep-link) — mantido por
     compat. Quando ativo, é tratado como uma seleção forçada de userIds. */
  const ATTENDANT_FILTER_TTL_MS = 30 * 60 * 1000;
  const [attendantFilter, setAttendantFilter] = useState(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = window.localStorage.getItem("smartprov_attendant_filter");
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      const ts = parsed?.__set_at;
      if (ts && (Date.now() - ts) > ATTENDANT_FILTER_TTL_MS) {
        // expirou — descarta
        window.localStorage.removeItem("smartprov_attendant_filter");
        return null;
      }
      return parsed;
    } catch { return null; }
  });

  useEffect(() => {
    const onChange = (e) => {
      const d = e?.detail || null;
      if (d) d.__set_at = Date.now();
      setAttendantFilter(d);
      try {
        if (d) {
          window.localStorage.setItem(
            "smartprov_attendant_filter", JSON.stringify(d)
          );
        } else {
          window.localStorage.removeItem("smartprov_attendant_filter");
        }
      } catch { /* ignore */ }
      if (d) setBucket("manual");
    };
    window.addEventListener("smartprov-open-attendant", onChange);
    return () => window.removeEventListener("smartprov-open-attendant", onChange);
  }, []);

  /* Quando o filtro é setado, vai pro bucket "manual" (onde estão as humanas). */
  useEffect(() => {
    if (attendantFilter?.user_id) setBucket("manual");
  }, [attendantFilter?.user_id]);

  const clearAttendantFilter = useCallback(() => {
    setAttendantFilter(null);
    try { window.localStorage.removeItem("smartprov_attendant_filter"); } catch { /* ignore */ }
  }, []);

  /** Filtra rapidinho só as conversas atribuídas ao usuário logado.
   * UX: gestor abre o chat e quer ver SÓ o que ele tá atendendo. */
  const applyMyFilter = useCallback(() => {
    if (!authUser?.id) return;
    const filter = {
      user_id: authUser.id,
      name: (authUser.name || authUser.email || "minhas").split(" ")[0],
      __set_at: Date.now(),
      __self: true,  // diferencia do filtro vindo do Central IA
    };
    setAttendantFilter(filter);
    try {
      window.localStorage.setItem(
        "smartprov_attendant_filter", JSON.stringify(filter)
      );
    } catch { /* ignore */ }
    setBucket("manual");
  }, [authUser?.id, authUser?.name, authUser?.email]);

  const loadConversations = useCallback(async () => {
    try {
      const r = await api.waBaileysConversations();
      const items = r.items || [];

      // Detecta novas mensagens em conversas SEM atendente humano
      // (assignee_role === "ai" OU sem assignee_user_id) e dispara beep
      // + notificação. Pula no 1º load pra não tocar ao abrir o painel.
      if (!firstLoadRef.current) {
        for (const c of items) {
          const prev = lastUnreadRef.current[c.phone] || 0;
          const curr = c.unread_count || 0;
          const isUnassigned = !c.assignee_user_id ||
                                c.assignee_role === "ai" ||
                                c.assignee_role === "bot";
          if (curr > prev && isUnassigned && c.last_msg_direction === "inbound") {
            chimeNewMessage();
            const who = c.subscriber_name || c.profile_name || c.phone || "Cliente";
            const lastText = (c.last_msg || "").slice(0, 80);
            notifyBrowser(`Nova mensagem de ${who}`, lastText, "wa-new-msg");
            break; // só 1 alerta por ciclo (o debounce interno também segura)
          }
        }
      } else {
        firstLoadRef.current = false;
      }

      // Atualiza o cache de unread anterior
      const newMap = {};
      for (const c of items) newMap[c.phone] = c.unread_count || 0;
      lastUnreadRef.current = newMap;

      setConversations(items);
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
    requestNotificationPermission();
    // Carrega o wallpaper customizado uma vez ao abrir a tela
    api.waBaileysGetWallpaper()
      .then((r) => setWallpaperUrl(r?.image_data_url || null))
      .catch(() => { /* silent — usa fallback */ });
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
    /* Se há busca (do header) OU busca do popover, vasculha TODOS os buckets. */
    const popSearch = (advFilter.search || "").trim();
    const headerSearch = search.trim();
    const anySearch = !!(popSearch || headerSearch);
    let inBucket = anySearch
      ? conversations
      : conversations.filter((c) => c.bucket === bucket);

    /* === Filtro avançado === */
    // Apenas não lidas
    if (advFilter.unreadOnly) {
      inBucket = inBucket.filter((c) => (c.unread || 0) > 0);
    }
    // Apenas meus atendimentos
    if (advFilter.onlyMine && authUser?.id) {
      inBucket = inBucket.filter((c) => c.assignee_user_id === authUser.id);
    }
    // Filtrar por usuários
    if ((advFilter.userIds || []).length > 0) {
      const set = new Set(advFilter.userIds);
      inBucket = inBucket.filter((c) =>
        c.assignee_user_id && set.has(c.assignee_user_id)
      );
    }
    // Filtrar por canais
    if ((advFilter.channels || []).length > 0) {
      const set = new Set(advFilter.channels);
      inBucket = inBucket.filter((c) => {
        const ch = (c.channel || c.source || "baileys").toLowerCase();
        return set.has(ch);
      });
    }
    // Data range — data inicial do atendimento (assignee_assigned_at ou created_at)
    if (advFilter.dateAtendimentoIni) {
      const ini = new Date(advFilter.dateAtendimentoIni).getTime();
      inBucket = inBucket.filter((c) => {
        const t = c.assignee_assigned_at || c.created_at;
        if (!t) return false;
        return new Date(t).getTime() >= ini;
      });
    }
    if (advFilter.dateAtendimentoFim) {
      const fim = new Date(advFilter.dateAtendimentoFim).getTime() + 86399999;
      inBucket = inBucket.filter((c) => {
        const t = c.assignee_assigned_at || c.created_at;
        if (!t) return false;
        return new Date(t).getTime() <= fim;
      });
    }
    // Data range — última interação (last_inbound_at / last_message_at / updated_at)
    if (advFilter.dateInteracaoIni) {
      const ini = new Date(advFilter.dateInteracaoIni).getTime();
      inBucket = inBucket.filter((c) => {
        const t = c.last_message_at || c.last_inbound_at || c.updated_at;
        if (!t) return false;
        return new Date(t).getTime() >= ini;
      });
    }
    if (advFilter.dateInteracaoFim) {
      const fim = new Date(advFilter.dateInteracaoFim).getTime() + 86399999;
      inBucket = inBucket.filter((c) => {
        const t = c.last_message_at || c.last_inbound_at || c.updated_at;
        if (!t) return false;
        return new Date(t).getTime() <= fim;
      });
    }

    /* === Filtro de atendente do Central IA (deep-link legado) === */
    if (attendantFilter?.user_id) {
      inBucket = inBucket.filter(
        (c) => c.assignee_user_id === attendantFilter.user_id
      );
    }

    /* === Texto livre === */
    const q = (popSearch || headerSearch).toLowerCase();
    if (!q) return inBucket;
    return inBucket.filter((c) =>
      (c.phone || "").includes(q) ||
      (c.subscriber_name || "").toLowerCase().includes(q) ||
      (c.subscriber_external_code || "").toLowerCase().includes(q) ||
      (c.subscriber_branch || "").toLowerCase().includes(q) ||
      (c.push_name || "").toLowerCase().includes(q) ||
      (c.last_text || "").toLowerCase().includes(q) ||
      (c.assignee_name || "").toLowerCase().includes(q)
    );
  }, [conversations, bucket, search, attendantFilter, advFilter, authUser?.id]);

  const selectedConv = useMemo(
    () => conversations.find((c) => c.phone === selectedPhone) || null,
    [conversations, selectedPhone]
  );

  // Métricas por bucket: total e não lidas. Mostradas como badges em cada item.
  const bucketMetrics = useMemo(() => {
    const unread = {};
    for (const c of conversations) {
      const b = c.bucket;
      if (!b) continue;
      unread[b] = (unread[b] || 0) + (c.unread || 0);
    }
    return unread;
  }, [conversations]);

  // === Config modal (Configurar Robô da Isabella IA) ===
  const [configOpen, setConfigOpen] = useState(false);
  const openConfig = useCallback(() => setConfigOpen(true), []);
  const closeConfig = useCallback(() => setConfigOpen(false), []);

  // Calcula gridTemplateRows: opcional banner do attendant filter legacy
  // (auto) + opcional banner do filtro avançado com resumo (auto) + main (1fr).
  const hasFilterBanner = !!attendantFilter?.user_id;
  const advCount = countActiveFilters(advFilter);
  const hasAdvBanner = advCount > 0 && !hasFilterBanner;
  const gridRows = `${hasFilterBanner ? "auto " : ""}${hasAdvBanner ? "auto " : ""}1fr`;

  return (
    <div data-testid="wa-chat-layout" style={{
      display: "grid",
      gridTemplateRows: gridRows,
      height: "calc(100vh - 170px)", minHeight: 560,
      border: "1px solid var(--border-default)", borderRadius: 14,
      overflow: "hidden", background: "var(--bg-surface)",
    }}>
      <AgentConfigModal open={configOpen} onClose={closeConfig} />
      {attendantFilter?.user_id && (
        <div data-testid="attendant-filter-banner" style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "12px 16px",
          background: filteredConvs.length === 0
            ? "rgba(245, 158, 11, 0.12)" : "var(--accent-soft)",
          borderBottom: filteredConvs.length === 0
            ? "1px solid rgba(245, 158, 11, 0.4)"
            : "1px solid var(--border-default)",
          fontSize: 13, color: "var(--text-primary)",
        }}>
          <span style={{
            width: 10, height: 10, borderRadius: "50%",
            background: filteredConvs.length === 0 ? "#f59e0b" : "var(--accent)",
            flexShrink: 0,
            boxShadow: filteredConvs.length === 0
              ? "0 0 8px rgba(245, 158, 11, 0.6)" : "none",
            animation: filteredConvs.length === 0
              ? "wa-pulse 1.8s ease-in-out infinite" : "none",
          }} />
          <span style={{ flex: 1 }}>
            {filteredConvs.length === 0 ? (
              <>
                <strong style={{ color: "#92400e" }}>Filtro ativo:</strong>{" "}
                vendo só conversas de <strong>{attendantFilter.name}</strong> —
                {" "}<strong>NENHUMA conversa</strong> encontrada com esse filtro.
                <span style={{ marginLeft: 6, color: "#92400e", fontSize: 11.5 }}>
                  (Sem conversas? Clique em "Limpar filtro" pra ver tudo.)
                </span>
              </>
            ) : (
              <>
                Filtrando conversas atribuídas a <strong>{attendantFilter.name}</strong>
                <span style={{ marginLeft: 8, color: "var(--text-muted)", fontSize: 12 }}>
                  · {filteredConvs.length} conversa(s)
                </span>
              </>
            )}
          </span>
          <button
            onClick={clearAttendantFilter}
            data-testid="clear-attendant-filter"
            style={{
              padding: "7px 14px", borderRadius: 7,
              border: filteredConvs.length === 0
                ? "1px solid #f59e0b" : "1px solid var(--border-default)",
              background: filteredConvs.length === 0
                ? "#f59e0b" : "var(--bg-surface)",
              color: filteredConvs.length === 0 ? "#fff" : "var(--text-secondary)",
              fontSize: 12, fontWeight: 700, cursor: "pointer",
              transition: "all .15s",
            }}
          >Limpar filtro</button>
        </div>
      )}
      {hasAdvBanner && (
        <div data-testid="adv-filter-summary-banner" style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "10px 16px",
          background: filteredConvs.length === 0
            ? "rgba(245, 158, 11, 0.10)" : "var(--accent-soft)",
          borderBottom: "1px solid var(--border-default)",
          fontSize: 12.5, color: "var(--text-primary)",
        }}>
          <Filter size={14} style={{
            color: filteredConvs.length === 0 ? "#f59e0b" : "var(--accent)",
          }} />
          <span style={{ flex: 1 }}>
            <strong>{advCount} filtro{advCount > 1 ? "s" : ""} ativo{advCount > 1 ? "s" : ""}</strong>
            {" · "}<span style={{ color: "var(--text-muted)" }}>
              {filteredConvs.length} conversa{filteredConvs.length !== 1 ? "s" : ""} encontrada{filteredConvs.length !== 1 ? "s" : ""}
            </span>
          </span>
          <button
            onClick={() => persistAdvFilter(makeBlankFilter())}
            data-testid="clear-adv-filter"
            style={{
              padding: "5px 12px", borderRadius: 6,
              border: "1px solid var(--border-default)",
              background: "var(--bg-surface)",
              color: "var(--text-secondary)", fontSize: 11.5,
              fontWeight: 700, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 5,
            }}
          ><RotateCcw size={10} /> Limpar filtros</button>
        </div>
      )}
      <div style={{
        display: "grid",
        gridTemplateColumns: "320px 1fr",
        gap: 0, minHeight: 0,
      }}>
      {/* COLUNA 1 — Buckets em accordion (convs aparecem DENTRO do bucket aberto) */}
      <BucketSidebar bucket={bucket} setBucket={setBucket}
                      counts={buckets} unreadByBucket={bucketMetrics}
                      advFilter={advFilter}
                      onAdvFilterChange={persistAdvFilter}
                      onAdvFilterClear={() => persistAdvFilter(makeBlankFilter())}
                      authUser={authUser} attendants={attendants}
                      convs={filteredConvs}
                      selectedPhone={selectedPhone}
                      setSelectedPhone={setSelectedPhone}
                      search={search} setSearch={setSearch}
                      loading={loading}
                      contactProfiles={contactProfiles}
                      onAssignSelf={async (phone) => {
                        if (!authUser?.id) return;
                        try {
                          await api.waBaileysAssignConversation(phone, {
                            assignee_user_id: authUser.id, assignee_role: "human",
                          });
                          setSelectedPhone(phone);
                          await loadConversations();
                        } catch (e) {
                          alert("Erro ao atender: " + (e?.response?.data?.detail || e.message));
                        }
                      }} />

      {/* COLUNA 2 — Thread aberta (ocupa o resto da tela) */}
      <ChatThread
        conv={selectedConv} attendants={attendants}
        contactProfile={selectedConv ? contactProfiles[selectedConv.phone] : null}
        onWarmContact={warmContact}
        onChange={loadConversations}
        wallpaperUrl={wallpaperUrl}
        onOpenAgentConfig={openConfig}
        authUser={authUser}
      />
      </div>
    </div>
  );
}

/* ============================================================= */
/* BucketSidebar — accordion: clica num bucket → expande as conversas DENTRO.
   Deixa o menu mais compacto e organizado (1 só coluna no layout). */
function BucketSidebar({ bucket, setBucket, counts, unreadByBucket,
                            advFilter, onAdvFilterChange, onAdvFilterClear,
                            authUser, attendants,
                            convs, selectedPhone, setSelectedPhone,
                            search, setSearch, loading,
                            contactProfiles, onAssignSelf }) {
  const [bannerDismissed, setBannerDismissed] = React.useState(() => {
    try { return localStorage.getItem("wa_ready_banner_dismissed") === "1"; }
    catch { return false; }
  });
  const dismissBanner = () => {
    setBannerDismissed(true);
    try { localStorage.setItem("wa_ready_banner_dismissed", "1"); } catch { /* ignore */ }
  };
  const totalUnread = Object.values(unreadByBucket || {}).reduce((a, b) => a + (b || 0), 0);
  return (
    <div data-testid="wa-buckets-sidebar" style={{
      background: "#f4f6fb",
      borderRight: "1px solid var(--border-default)",
      display: "flex", flexDirection: "column",
      minHeight: 0,
    }}>
      {/* Header com busca + filtros (estilo FocusChat) */}
      <div style={{
        padding: "8px 10px 6px",
        background: "#ffffff",
        borderBottom: "1px solid #e5e7eb",
        display: "flex", flexDirection: "column", gap: 6,
      }}>
        {/* Busca global com ícones de filtro/histórico à direita */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "6px 10px", borderRadius: 8,
          background: "#ffffff",
          border: "1.5px solid #1f2937",
        }}>
          <Search size={13} strokeWidth={2.2} style={{ color: "#1f2937" }} />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
                 placeholder="Pesquisar"
                 data-testid="wa-search-input"
                 style={{
                   flex: 1, border: "none", outline: "none",
                   background: "transparent",
                   fontSize: 12.5, color: "#0f172a",
                 }} />
          {/* Indicador de filtros (badge verde) */}
          <div style={{ position: "relative", display: "inline-flex" }}>
            <WaChatFilterPopover
              value={advFilter}
              onChange={onAdvFilterChange}
              onClear={onAdvFilterClear}
              authUser={authUser}
              attendants={attendants}
              align="left"
            />
            {totalUnread > 0 && (
              <span style={{
                position: "absolute", top: -4, right: -4,
                minWidth: 14, height: 14, padding: "0 3px",
                borderRadius: 999, background: "#16a34a", color: "#fff",
                fontSize: 9, fontWeight: 800,
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                border: "2px solid #fff",
                pointerEvents: "none",
              }}>{totalUnread > 99 ? "99+" : totalUnread}</span>
            )}
          </div>
        </div>
      </div>

      {/* Lista de buckets — accordion (estilo cards FocusChat)
          Outer flex-column: cada bucket header sempre visível;
          quando aberto, o conteúdo do bucket ativo rola INTERNAMENTE
          (não empurra os outros pra fora da tela). */}
      <div style={{
        flex: 1, minHeight: 0,
        display: "flex", flexDirection: "column",
        overflow: "hidden",
        padding: "6px 7px 0",
      }}>
        {BUCKETS.map((b) => {
          const Ico = b.icon;
          const active = bucket === b.id;
          const n = counts[b.id] || 0;
          const unread = (unreadByBucket && unreadByBucket[b.id]) || 0;
          // Convs do bucket atual (apenas quando expandido)
          const bucketConvs = active ? (convs || []) : [];
          return (
            <div key={b.id} style={{
              marginBottom: 5,
              background: "#ffffff",
              borderRadius: 8,
              border: "1px solid #e5e7eb",
              boxShadow: active
                ? "0 2px 6px rgba(15, 23, 42, .07)"
                : "0 1px 1.5px rgba(15, 23, 42, .03)",
              overflow: "hidden",
              flex: active ? "1 1 auto" : "0 0 auto",
              minHeight: 0,
              display: "flex", flexDirection: "column",
            }}>
              <button onClick={() => setBucket(active ? "" : b.id)}
                      data-testid={`wa-bucket-${b.id}`}
                      title={active ? `Fechar ${b.label}` : `Abrir ${b.label}`}
                      style={{
                width: "100%",
                display: "flex", alignItems: "center", gap: 9,
                padding: "9px 12px",
                background: "transparent",
                border: "none",
                color: "#0f172a",
                cursor: "pointer", textAlign: "left",
                fontSize: 13.5, fontWeight: 700,
                transition: "background .15s",
                flexShrink: 0,
              }}
              onMouseEnter={(e) => {
                if (!active) e.currentTarget.style.background = "#f8fafc";
              }}
              onMouseLeave={(e) => {
                if (!active) e.currentTarget.style.background = "transparent";
              }}>
                <Ico size={17} strokeWidth={2}
                      style={{ color: "#0f172a", flexShrink: 0 }} />
                <span style={{ flex: 1, color: "#0f172a", letterSpacing: -0.2 }}>
                  {b.label}
                </span>
                {/* Pílula preta com count + badge verde sobreposto */}
                <span data-testid={`wa-bucket-count-${b.id}`} style={{
                  position: "relative",
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  minWidth: 30, height: 21, padding: "0 9px",
                  borderRadius: 999,
                  background: "#0f172a",
                  color: "#ffffff",
                  fontSize: 11.5, fontWeight: 800,
                }}>
                  {n}
                  {unread > 0 && (
                    <span data-testid={`wa-bucket-unread-${b.id}`}
                          title={`${unread} não lida${unread === 1 ? "" : "s"}`}
                          style={{
                      position: "absolute", top: -6, right: -6,
                      minWidth: 16, height: 16, padding: "0 4px",
                      borderRadius: 999, background: "#16a34a", color: "#fff",
                      fontSize: 9.5, fontWeight: 800,
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      border: "2px solid #ffffff",
                      lineHeight: 1,
                    }}>
                      {unread > 99 ? "99+" : unread}
                    </span>
                  )}
                </span>
                {/* Chevron ">" */}
                <span style={{
                  color: "#94a3b8", fontSize: 16, fontWeight: 400,
                  transform: active ? "rotate(90deg)" : "rotate(0deg)",
                  transition: "transform .18s",
                  display: "inline-block", lineHeight: 1, flexShrink: 0,
                }}>›</span>
              </button>

              {/* Convs nested DENTRO do bucket aberto — SCROLL INTERNO */}
              {active && (
                <div data-testid={`wa-bucket-content-${b.id}`}
                     style={{
                       borderTop: "1px solid #e5e7eb",
                       flex: 1, minHeight: 0,
                       overflowY: "auto",
                     }}>
                  {loading ? (
                    <div style={{ padding: 16, textAlign: "center", color: "#64748b" }}>
                      <Loader2 size={14} style={{ animation: "wa-spin 1s linear infinite" }} />
                      <div style={{ fontSize: 11, marginTop: 4 }}>Carregando...</div>
                    </div>
                  ) : bucketConvs.length === 0 ? (
                    <div style={{ padding: "12px 10px", textAlign: "center",
                                  color: "#64748b", fontSize: 11.5 }}>
                      Sem conversas em "{b.label}"
                    </div>
                  ) : bucketConvs.map((c) => (
                    <ConvRow key={c.phone} conv={c}
                              selected={selectedPhone === c.phone}
                              profile={contactProfiles?.[c.phone]}
                              authUser={authUser}
                              onAssignSelf={onAssignSelf}
                              onClick={() => setSelectedPhone(c.phone)} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Banner inferior "Tudo pronto, canal ativo e configurado" */}
      {!bannerDismissed && (
        <div data-testid="wa-ready-banner" style={{
          margin: "0 10px 10px",
          padding: "12px 16px",
          borderRadius: 10,
          background: "linear-gradient(135deg, #93c5fd, #60a5fa)",
          color: "#0f172a",
          display: "flex", alignItems: "center", gap: 10,
          fontSize: 13, fontWeight: 600,
          boxShadow: "0 2px 6px rgba(59,130,246,.25)",
        }}>
          <span style={{ fontSize: 14 }}>🎉</span>
          <span style={{ flex: 1 }}>
            Tudo <strong>pronto</strong>, canal ativo e configurado.
          </span>
          <button onClick={dismissBanner}
                  data-testid="wa-ready-banner-close"
                  title="Dispensar"
                  style={{
                    background: "transparent", border: "none",
                    color: "#0f172a", cursor: "pointer",
                    padding: 4, display: "inline-flex",
                    borderRadius: 4,
                  }}>
            <X size={16} strokeWidth={2.4} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ============================================================= */
function ConversationList({ bucket, convs, selectedPhone, setSelectedPhone,
                              search, setSearch, loading, totalInBucket,
                              contactProfiles, authUser, onAssignSelf }) {
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
                    authUser={authUser}
                    onAssignSelf={onAssignSelf}
                    onClick={() => setSelectedPhone(c.phone)} />
        ))}
      </div>
    </div>
  );
}

function ConvRow({ conv, selected, onClick, profile, authUser, onAssignSelf }) {
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
  // verde se online · laranja se aguardando · azul se há unread · laranja default (estilo screenshot)
  let statusColor = "#f59e0b";
  if (online) statusColor = "#22c55e";
  else if (conv.bucket === "aguardando") statusColor = "#f59e0b";
  else if (unread > 0) statusColor = "#0ea5e9";
  // Última msg: direção indica quem falou por último
  const dirIcon = conv.last_direction === "outbound" ? "▲" : "▼";
  const dirColor = conv.last_direction === "outbound" ? "#64748b" : "#0ea5e9";
  // IA digitando? Sobrescreve a última msg na preview.
  let aiTypingPreview = false;
  if (conv.ai_typing_until) {
    try {
      aiTypingPreview = new Date(conv.ai_typing_until).getTime() > Date.now();
    } catch { aiTypingPreview = false; }
  }
  const aiTypingAgentName = conv.ai_typing_agent || "Isabella";

  return (
    <button onClick={onClick}
            data-testid={`wa-conv-${conv.phone}`}
            style={{
              width: "100%", padding: "10px 11px",
              border: "none", borderBottom: "1px solid #f1f5f9",
              background: selected ? "#eff6ff" : "transparent",
              borderLeft: selected ? "3px solid #2563eb" : "3px solid transparent",
              cursor: "pointer", textAlign: "left",
              display: "flex", gap: 10, alignItems: "flex-start",
              transition: "background .15s",
            }}>
      {/* Avatar com WA badge bottom-left + status dot bottom-right */}
      <div style={{ position: "relative", flexShrink: 0, width: 44, height: 44 }}>
        <Avatar name={displayName} src={avatarSrc} isAi={false} size={44} />
        {/* WhatsApp badge */}
        <span title="WhatsApp" style={{
          position: "absolute", bottom: -1, left: -2,
          width: 17, height: 17, borderRadius: "50%",
          background: "#22c55e", color: "#fff",
          display: "grid", placeItems: "center",
          border: "2px solid #ffffff",
          boxShadow: "0 1px 2px rgba(0,0,0,.18)",
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
                  border: "2px solid #ffffff",
                }} />
        )}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Linha 1: nome + timestamp + Atender */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <strong style={{
              fontSize: 13, color: "#0f172a",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              display: "block",
              fontWeight: unread > 0 ? 800 : 700,
              letterSpacing: -0.2,
              lineHeight: 1.25,
            }}>{displayName}</strong>
            {/* Linha 2: telefone (sempre) */}
            <div style={{ fontSize: 11, color: "#64748b",
                           marginTop: 1, fontFamily: "ui-monospace, monospace",
                           overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              +{conv.phone}
              {conv.subscriber_external_code && (
                <span style={{ marginLeft: 5, color: "#64748b" }}>
                  · cód <strong style={{ color: "#475569" }}>
                    {conv.subscriber_external_code}
                  </strong>
                </span>
              )}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
            <span style={{ fontSize: 10.5, color: "#64748b",
                            fontWeight: unread > 0 ? 700 : 500 }}>
              {time}
            </span>
            {/* Botão "Atender" laranja inline (estilo screenshot) */}
            {(() => {
              const isMine = conv.assignee_user_id && authUser?.id
                              && conv.assignee_user_id === authUser.id;
              const hasHumanOther = conv.assignee_role === "human"
                                      && conv.assignee_user_id
                                      && !isMine;
              if (hasHumanOther) {
                return (
                  <span data-testid={`wa-conv-attendant-${conv.phone}`}
                        title={`Atribuída a ${conv.assignee_name}`}
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 3,
                          padding: "3px 9px", borderRadius: 5,
                          background: "linear-gradient(180deg, #2f80ed, #1d6cd8)",
                          color: "#fff", fontSize: 10.5, fontWeight: 700,
                          maxWidth: 80,
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                    <User size={9} strokeWidth={2.8} />
                    {conv.assignee_name}
                  </span>
                );
              }
              if ((isAi || !conv.assignee_user_id) && onAssignSelf && authUser?.id) {
                return (
                  <button
                    type="button"
                    data-testid={`wa-conv-attender-${conv.phone}`}
                    onClick={(ev) => { ev.stopPropagation(); onAssignSelf(conv.phone); }}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      padding: "3px 11px", borderRadius: 5,
                      background: "linear-gradient(180deg, #fb923c, #f97316)",
                      color: "#fff", fontSize: 10.5, fontWeight: 700,
                      border: "none", cursor: "pointer",
                      boxShadow: "0 1px 2px rgba(249,115,22,.4)",
                      transition: "transform .12s, box-shadow .12s",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.boxShadow = "0 2px 6px rgba(249,115,22,.55)";
                      e.currentTarget.style.transform = "translateY(-1px)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.boxShadow = "0 1px 2px rgba(249,115,22,.4)";
                      e.currentTarget.style.transform = "translateY(0)";
                    }}>
                    Atender
                  </button>
                );
              }
              if (isMine) {
                return (
                  <span data-testid={`wa-conv-mine-${conv.phone}`}
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 3,
                          padding: "3px 8px", borderRadius: 5,
                          background: "linear-gradient(180deg, #16a34a, #15803d)",
                          color: "#fff", fontSize: 10, fontWeight: 700,
                        }}>
                    <CheckCircle2 size={9} strokeWidth={2.8} />
                    Atendendo
                  </span>
                );
              }
              return null;
            })()}
          </div>
        </div>

        {/* Linha 3: ÚLTIMA MENSAGEM em destaque (prioridade) + unread badge */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6, marginTop: 5,
        }}>
          {/* Setinha azul direção (▲ outbound, ▼ inbound) */}
          <span style={{
            color: "#3b82f6",
            background: "#dbeafe",
            width: 17, height: 17, borderRadius: 4,
            fontSize: 10.5, fontWeight: 800, flexShrink: 0,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            lineHeight: 1,
          }}>
            {dirIcon}
          </span>
          <span style={{
            fontSize: 12.5,
            color: aiTypingPreview
              ? "#7c3aed"
              : (unread > 0 ? "#0f172a" : "#334155"),
            fontWeight: aiTypingPreview || unread > 0 ? 600 : 500,
            fontStyle: aiTypingPreview ? "italic" : "normal",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            flex: 1, minWidth: 0,
            lineHeight: 1.3,
          }}>
            {aiTypingPreview
              ? `${aiTypingAgentName} digitando…`
              : (conv.last_text || <em style={{ color: "#94a3b8", fontWeight: 400 }}>sem mensagens</em>)}
          </span>
          {unread > 0 && (
            <span data-testid={`wa-unread-${conv.phone}`} style={{
              minWidth: 19, height: 19, padding: "0 6px",
              borderRadius: 999, background: "#16a34a",
              color: "#fff", fontSize: 10.5, fontWeight: 800,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
              boxShadow: "0 1px 2px rgba(22,163,74,.4)",
            }}>{unread > 99 ? "99+" : unread}</span>
          )}
        </div>

        {/* Linha 4: tag filial + plano + canal + LID + falha (compacto, abaixo da msg) */}
        {(conv.subscriber_branch || (isIdentified && conv.subscriber_plan)
          || (conv.last_channel && conv.last_channel !== "baileys")
          || (conv.channels_used || []).filter((c) => c).length > 1
          || (conv.last_outbound_status || "").startsWith("failed")
          || conv.phone_is_lid) && (
          <div style={{
            display: "flex", alignItems: "center", gap: 5,
            marginTop: 4, flexWrap: "wrap",
          }}>
            {conv.subscriber_branch && (
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 3,
                fontSize: 10.5, fontWeight: 600,
                color: "#64748b", letterSpacing: 0.2,
              }}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M9 13h.01M9 17h.01M14 9h.01M14 13h.01M14 17h.01"/>
                </svg>
                {conv.subscriber_branch}
              </span>
            )}
            {isIdentified && conv.subscriber_plan && (
              <span style={{
                padding: "1px 6px", borderRadius: 4,
                background: "rgba(13,148,136,.12)",
                color: "#0d9488",
                fontSize: 10, fontWeight: 700,
              }}>
                {conv.subscriber_plan}
              </span>
            )}
            {conv.last_channel && conv.last_channel !== "baileys" && (
              <ChannelBadge channel={conv.last_channel} small />
            )}
            {(conv.channels_used || []).filter((c) => c).length > 1 && (
              <span title={`Este contato fala por: ${(conv.channels_used || []).join(", ")}`}
                     style={{
                       padding: "1px 4px", borderRadius: 4,
                       background: "#fef3c7", color: "#92400e",
                       border: "1px solid #fcd34d",
                       fontSize: 8.5, fontWeight: 700, flexShrink: 0,
                     }}>
                {(conv.channels_used || []).filter((c) => c).length}× canais
              </span>
            )}
            {(conv.last_outbound_status || "").startsWith("failed") && (
              <span
                data-testid={`wa-conv-ai-fail-${conv.phone}`}
                title={conv.last_outbound_error
                  ? `IA falhou: ${conv.last_outbound_error}`
                  : "Última resposta IA falhou"}
                style={{
                  padding: "0 6px", borderRadius: 999,
                  background: "#fee2e2", color: "#991b1b",
                  fontSize: 9.5, fontWeight: 800,
                  display: "inline-flex", alignItems: "center", gap: 2, flexShrink: 0,
                  border: "1px solid #fecaca", height: 16,
                }}>
                <AlertTriangle size={9} strokeWidth={2.5} /> Falha IA
              </span>
            )}
            {conv.phone_is_lid && (
              <span
                data-testid={`wa-conv-lid-${conv.phone}`}
                title={`WhatsApp LID anônimo. LID: ${conv.lid || conv.phone}`}
                style={{
                  padding: "0 5px", borderRadius: 999,
                  background: "#fef3c7", color: "#92400e",
                  fontSize: 9, fontWeight: 800,
                  display: "inline-flex", alignItems: "center", gap: 2, flexShrink: 0,
                  border: "1px solid #fde68a", height: 15,
                }}>
                <Lock size={8} strokeWidth={2.5} /> LID
              </span>
            )}
          </div>
        )}
      </div>
    </button>
  );
}


/* ============================================================= */
function ChatThread({ conv, attendants, contactProfile, onWarmContact, onChange,
                          wallpaperUrl, onOpenAgentConfig, authUser }) {
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
  /* KPIs do atendente (drill-down do Central IA). */
  const [attendantKpis, setAttendantKpis] = useState([]);
  /* Edit & Teach — modal de correção da resposta da Isabella */
  const [correctingMsg, setCorrectingMsg] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    let alive = true;
    api.centralIaAttendants(7).then((r) => {
      if (alive) setAttendantKpis(r?.items || []);
    }).catch(() => {});
    return () => { alive = false; };
  }, []);

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

  /* Tick para reavaliar o indicador "Isabella digitando..." conforme o
     ai_typing_until expira. Re-renderiza a cada 1.5s. */
  const [, setAiTypingTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setAiTypingTick((t) => t + 1), 1500);
    return () => clearInterval(id);
  }, []);
  const aiTypingUntil = conv?.ai_typing_until;
  const aiTypingAgent = conv?.ai_typing_agent || "Isabella IA";
  let aiTyping = false;
  if (aiTypingUntil) {
    try { aiTyping = new Date(aiTypingUntil).getTime() > Date.now(); }
    catch { aiTyping = false; }
  }

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

  // Tracking pra detectar primeiro load vs. updates do polling
  const lastConvPhoneRef = useRef(null);
  const lastMsgCountRef = useRef(0);
  /* pendingScrollToBottom: enquanto TRUE, todo render força scroll pro fundo.
     Só vira FALSE depois que vimos mensagens da conversa atual + scroll real
     foi aplicado. Isso lida com a race condition de stale messages + load
     assíncrono de balões com mídia. */
  const pendingScrollRef = useRef(false);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const [newCountWhileAway, setNewCountWhileAway] = useState(0);

  // Listener de scroll para detectar se o usuário rolou pra cima (lendo histórico).
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const onScroll = () => {
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      const farFromBottom = distFromBottom > 120;
      setShowScrollDown(farFromBottom);
      if (!farFromBottom) setNewCountWhileAway(0);  // chegou no fundo, reseta
    };
    el.addEventListener("scroll", onScroll);
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, [conv]);

  // Quando a conversa MUDA: marca pendingScrollToBottom=TRUE.
  // Esse flag fica ativo até nós conseguirmos efetivamente scrollar pro
  // fundo da NOVA conversa (não a antiga). Cobre o caso onde messages
  // ainda contém dados da conversa anterior e o load é assíncrono.
  useEffect(() => {
    if (!conv?.phone) return;
    if (lastConvPhoneRef.current !== conv.phone) {
      lastConvPhoneRef.current = conv.phone;
      lastMsgCountRef.current = 0;
      pendingScrollRef.current = true;
      setNewCountWhileAway(0);
      setShowScrollDown(false);
    }
  }, [conv?.phone]);

  useEffect(() => {
    if (!scrollRef.current || !conv?.phone) return;
    const el = scrollRef.current;

    // Modo "pending": acabou de trocar de conversa. Força scroll pro fundo
    // em VÁRIOS pontos no tempo pra cobrir o caso de balões com mídia
    // (imagens, áudio, avatar) que aumentam a altura depois do render.
    if (pendingScrollRef.current && messages.length > 0) {
      const forceBottom = () => {
        if (!scrollRef.current) return;
        scrollRef.current.scrollTo({
          top: scrollRef.current.scrollHeight + 9999, behavior: "auto",
        });
      };
      forceBottom();
      const raf = requestAnimationFrame(forceBottom);
      const timers = [50, 150, 350, 700, 1200, 2000].map(
        (ms) => setTimeout(forceBottom, ms),
      );
      // Encerra modo pending depois de 2.5s — qualquer scroll após isso
      // é considerado interação genuína do usuário.
      const closer = setTimeout(() => {
        pendingScrollRef.current = false;
        lastMsgCountRef.current = messages.length;
      }, 2500);
      return () => {
        cancelAnimationFrame(raf);
        timers.forEach(clearTimeout);
        clearTimeout(closer);
      };
    }

    // Modo "live": já estamos visualizando a conversa atual. Detecta
    // mensagens novas e decide se rola ou exibe badge.
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const wasNearBottom = distFromBottom < 120;
    const delta = messages.length - lastMsgCountRef.current;
    const grew = delta > 0;
    if (grew && wasNearBottom) {
      el.scrollTo({ top: 1e9, behavior: delta <= 3 ? "smooth" : "auto" });
    } else if (grew && !wasNearBottom) {
      const incomingNew = messages.slice(-delta).filter(
        (m) => m.direction === "inbound",
      ).length;
      if (incomingNew > 0) setNewCountWhileAway((c) => c + incomingNew);
    }
    lastMsgCountRef.current = messages.length;
    return undefined;
  }, [messages, conv?.phone]);

  const scrollToBottom = useCallback(() => {
    scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
    setNewCountWhileAway(0);
  }, []);

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

  // ---- Áudio (MediaRecorder) ----
  const [recording, setRecording] = useState(false);
  const [recDuration, setRecDuration] = useState(0);
  const recorderRef = useRef(null);
  const recChunksRef = useRef([]);
  const recTimerRef = useRef(null);

  const startRecording = async () => {
    if (!conv || isAi || recording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Prefer webm/opus pra compat com Baileys (ele faz transcode pro ogg).
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")
            ? "audio/ogg;codecs=opus" : "audio/webm");
      const mr = new MediaRecorder(stream, { mimeType: mime });
      recChunksRef.current = [];
      mr.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) recChunksRef.current.push(ev.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(recChunksRef.current, { type: mime });
        if (blob.size < 1000) {
          alert("Áudio muito curto, segure por mais tempo.");
          return;
        }
        const reader = new FileReader();
        reader.onload = async () => {
          const b64 = String(reader.result || "").split(",")[1];
          if (!b64) return;
          setSending(true);
          try {
            await api.waBaileysSendAudio(conv.phone, b64, mime, recDuration);
            await loadMessages();
          } catch (e) {
            alert("Erro ao enviar áudio: " + (e?.response?.data?.detail || e.message));
          } finally {
            setSending(false);
            setRecDuration(0);
          }
        };
        reader.readAsDataURL(blob);
      };
      mr.start();
      recorderRef.current = mr;
      setRecording(true);
      setRecDuration(0);
      recTimerRef.current = setInterval(
        () => setRecDuration((d) => d + 1), 1000);
    } catch (e) {
      alert("Não foi possível acessar o microfone: " + e.message);
    }
  };

  const stopRecording = (cancel = false) => {
    if (!recording) return;
    if (recTimerRef.current) {
      clearInterval(recTimerRef.current);
      recTimerRef.current = null;
    }
    setRecording(false);
    const mr = recorderRef.current;
    if (cancel && mr) {
      // Limpa chunks pra onstop ignorar (size < 1000 vai abortar)
      recChunksRef.current = [];
    }
    try { mr?.stop(); } catch { /* ignore */ }
    recorderRef.current = null;
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

  const [showFinalizeModal, setShowFinalizeModal] = useState(false);

  const finalize = () => setShowFinalizeModal(true);
  const doFinalize = async () => {
    setShowFinalizeModal(false);
    setBusy(true);
    try {
      await api.waBaileysFinalizeConversation(conv.phone);
      onChange();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const [resetting, setResetting] = useState(false);
  const [showImagePicker, setShowImagePicker] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const [showQuickImages, setShowQuickImages] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [pdfResult, setPdfResult] = useState(null);
  const resetConversation = async () => {
    if (!window.confirm(
      "Resetar esta conversa?\n\n" +
      "Vai APAGAR TODAS as mensagens (cliente + IA + coaching) " +
      "para começar do zero — útil pra testes da IA.\n\n" +
      "O contato permanece, mas o histórico de mensagens será perdido."
    )) return;
    setResetting(true);
    try {
      const r = await api.waBaileysResetConversation(conv.phone);
      alert(`Conversa resetada (${r.messages_deleted} mensagens apagadas).`);
      await loadMessages();
      onChange();
    } catch (e) {
      alert("Erro ao resetar: " + (e?.response?.data?.detail || e.message));
    } finally { setResetting(false); }
  };

  /* Anexo: gera PDF da conversa completa + vincula ao cadastro do cliente. */
  const exportConversationPdf = async () => {
    setExportingPdf(true);
    setPdfResult(null);
    try {
      const r = await api._client.post(
        `/whatsapp-baileys/conversation/${conv.phone}/export-pdf`,
      ).then((x) => x.data);
      const token = window.localStorage.getItem("ponto_token") || "";
      const dlUrl =
        `${process.env.REACT_APP_BACKEND_URL || ""}${r.download_url}?t=${encodeURIComponent(token)}`;
      // Auto-download
      const a = document.createElement("a");
      a.href = dlUrl;
      a.download = r.document?.file_name || "transcricao.pdf";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setPdfResult(r);
    } catch (e) {
      alert("Erro ao gerar PDF: " + (e?.response?.data?.detail || e.message));
    } finally { setExportingPdf(false); }
  };

  /* Timeline mesclada: mensagens reais (WhatsApp) + coaching INTERNO (só você vê),
     ordenado por created_at. Mantém este hook ANTES de qualquer early return
     pra atender a regra dos React Hooks.
     Iter75: insere separadores `{_kind:"daydiv"}` entre mensagens de dias
     diferentes para criar o efeito de "quebra de chat por dia" igual WhatsApp. */
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
    // Identifica quem iniciou o chat (primeira mensagem real) pra renderizar
    // o badge "Chat iniciado por: CLIENTE (data - hora)" no topo da conversa.
    const firstMsg = items.find((it) => it._kind === "msg");
    // Insere separadores de dia
    const out = [];
    if (firstMsg) {
      out.push({
        _kind: "chat_start",
        _ts: firstMsg._ts,
        started_by: firstMsg.direction === "inbound" ? "CLIENTE" : "ATENDIMENTO",
      });
    }
    let lastDay = "";
    for (const it of items) {
      const day = (it._ts || "").substring(0, 10);  // YYYY-MM-DD
      if (day && day !== lastDay) {
        out.push({ _kind: "daydiv", _ts: it._ts, day });
        lastDay = day;
      }
      out.push(it);
    }
    return out;
  }, [messages, coachings]);

  if (!conv) {
    // Empty state — usa o MESMO wallpaper customizado da empresa (igual ao chat).
    // Sem oval/mascote no centro — mantém limpo, como o WhatsApp Web.
    return (
      <div style={{
        flex: 1, minHeight: 0, position: "relative",
        backgroundColor: "#efeae2",
        backgroundImage: `url("${wallpaperUrl || '/wa-wallpaper-ligo.png?v=4'}")`,
        backgroundRepeat: wallpaperUrl ? "no-repeat" : "repeat",
        backgroundSize: wallpaperUrl ? "cover" : "auto",
        backgroundPosition: "center",
      }} data-testid="wa-empty-state" />
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
  if (aiTyping) {
    presenceLabel = `${aiTypingAgent} digitando…`;
    presenceColor = "#7c3aed";  // roxo IA
  }
  else if (typing) { presenceLabel = "digitando…"; presenceColor = "#22c55e"; }
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

  /* Drill-down inverso: KPIs do atendente humano que está respondendo
     (puxados de centralIaAttendants). Só mostra quando humano. */
  const attendantKpi = (!isAi && conv.assignee_user_id)
    ? attendantKpis.find((a) => a.user_id === conv.assignee_user_id)
    : null;

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
            flexWrap: "wrap",
          }}>
            <span className="mono">+{conv.phone}</span>
            <span style={{ opacity: 0.4 }}>·</span>
            <span style={{
              color: online ? "#16a34a" : "var(--text-muted)",
              fontWeight: online ? 600 : 400,
            }}>{presenceLabel}</span>
            {conv.last_channel && (
              <>
                <span style={{ opacity: 0.4 }}>·</span>
                <span data-testid="wa-thread-channel">
                  <ChannelBadge channel={conv.last_channel} />
                </span>
              </>
            )}
            {(conv.channels_used || []).filter((c) => c).length > 1 && (
              <span data-testid="wa-thread-multi-channel"
                    title={`Este contato fala por: ${(conv.channels_used || []).join(", ")}`}
                    style={{
                      padding: "1px 7px", borderRadius: 999,
                      background: "#fef3c7", color: "#92400e",
                      fontSize: 10, fontWeight: 800,
                      border: "1px solid #fde68a",
                      display: "inline-flex", alignItems: "center", gap: 3,
                    }}>
                {(conv.channels_used || []).filter((c) => c).length}× canais
              </span>
            )}
            {conv.phone_is_lid && (
              <>
                <span style={{ opacity: 0.4 }}>·</span>
                <span data-testid="wa-thread-lid-warn"
                       title="Número real ocultado por privacidade WhatsApp. Clique 'Vincular telefone' para identificar o cliente."
                       style={{
                         padding: "1px 7px", borderRadius: 999,
                         background: "#fef3c7", color: "#92400e",
                         fontSize: 10, fontWeight: 800,
                         border: "1px solid #fde68a",
                         display: "inline-flex", alignItems: "center", gap: 3,
                       }}>
                  <Lock size={9} strokeWidth={2.5} /> LID anônimo
                </span>
                <LidLinkButton conv={conv} onLinked={onChange} />
              </>
            )}
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
            <IconBtn
              data-testid="wa-take-over-btn"
              onClick={() => authUser?.id && assignTo(authUser.id)}
              disabled={busy || !authUser?.id}
              icon={<Hand size={14} strokeWidth={2} />}
              tooltip="Assumir conversa (atribuir a mim)"
              variant="primary"
            />
          ) : (
            <IconBtn
              data-testid="wa-give-back-ai-btn"
              onClick={giveBackToAi}
              disabled={busy}
              icon={<Bot size={14} strokeWidth={2} />}
              tooltip="Devolver para a Isabella IA"
            />
          )}
          <IconBtn
            data-testid="wa-attach-image-btn"
            onClick={() => setShowImagePicker(true)}
            disabled={busy}
            icon={<Image size={14} strokeWidth={2} />}
            tooltip="Anexar arquivo de imagem"
            hoverColor="#0ea5e9"
          />
          <IconBtn
            data-testid="wa-quick-images-btn"
            onClick={() => setShowQuickImages(true)}
            disabled={busy}
            icon={<ImagePlus size={14} strokeWidth={2} />}
            tooltip="Imagens Rápidas (até 5 imagens pré-cadastradas)"
            hoverColor="#7c3aed"
          />
          <IconBtn
            data-testid="wa-export-pdf-btn"
            onClick={exportConversationPdf}
            disabled={busy || exportingPdf}
            icon={<Paperclip size={14} strokeWidth={2}
                              className={exportingPdf ? "spin" : ""} />}
            tooltip="Anexo (gerar PDF da conversa e vincular ao cadastro do cliente)"
            hoverColor="#0e7490"
          />
          <IconBtn
            data-testid="wa-schedule-btn"
            onClick={() => setShowSchedule(true)}
            disabled={busy}
            icon={<CalendarPlus size={14} strokeWidth={2} />}
            tooltip="Criar agendamento (data, hora, motivo, cliente Atlaz)"
            hoverColor="#8b5cf6"
          />
          <IconBtn
            data-testid="wa-finalize-btn"
            onClick={finalize}
            disabled={busy}
            icon={<CheckCircle2 size={14} strokeWidth={2} />}
            tooltip="Finalizar conversa (encerrar atendimento)"
            hoverColor="var(--danger)"
          />
          {onOpenAgentConfig && (
            <IconBtn
              data-testid="wa-open-agent-config"
              onClick={onOpenAgentConfig}
              icon={<Settings size={14} strokeWidth={2} />}
              tooltip="Configurar Robô (Isabella IA)"
              hoverColor="#7c3aed"
            />
          )}
        </div>
      </div>

      {/* Image Picker — anexar foto à conversa */}
      {showImagePicker && (
        <ImagePickerModal
          phone={conv.phone}
          onClose={() => setShowImagePicker(false)}
          onSent={async () => { setShowImagePicker(false); await loadMessages(); }}
        />
      )}

      {/* Imagens Rápidas — envia uma das 5 pré-cadastradas */}
      {showQuickImages && (
        <QuickImagesPopover
          phone={conv.phone}
          onClose={() => setShowQuickImages(false)}
          onSent={async () => { setShowQuickImages(false); await loadMessages(); }}
        />
      )}

      {/* Resultado do PDF gerado (toast) */}
      {pdfResult && (
        <PdfResultToast result={pdfResult} onClose={() => setPdfResult(null)} />
      )}

      {/* Modal de confirmação para finalizar atendimento */}
      {showFinalizeModal && (
        <FinalizeAtendimentoModal
          onCancel={() => setShowFinalizeModal(false)}
          onConfirm={doFinalize}
        />
      )}

      {/* Agendamento — bolha de serviço (data, hora, motivo, cliente) */}
      {showSchedule && (
        <ScheduleModal
          phone={conv.phone}
          conv={conv}
          onClose={() => setShowSchedule(false)}
          onSaved={async () => { setShowSchedule(false); await loadMessages(); }}
        />
      )}

      {/* KPI strip do atendente humano — drill-down inverso do Central IA */}
      {attendantKpi && <AttendantKpiStrip kpi={attendantKpi} />}

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

      {/* Mensagens — papel de parede customizado Ligo */}
      <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex" }}>
      <div ref={scrollRef}
           data-testid="wa-messages-scroll"
           style={{
             flex: 1, minHeight: 0,
             overflowY: "auto", padding: "16px 18px",
             backgroundColor: "#efeae2",
             backgroundImage: `url("${wallpaperUrl || '/wa-wallpaper-ligo.png?v=4'}")`,
             backgroundRepeat: "repeat",
             backgroundSize: wallpaperUrl ? "cover" : "auto",
             backgroundBlendMode: "multiply",
           }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {timeline.map((it, idx) => {
            if (it._kind === "chat_start") {
              return <ChatStartBadge key="chat-start"
                                       started_by={it.started_by} ts={it._ts} />;
            }
            if (it._kind === "daydiv") {
              return <DayDivider key={`d-${it.day}`} day={it.day} />;
            }
            if (it._kind === "coaching") {
              return (
                <InternalCoachingBubble key={`c-${it.id}`} coach={it}
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
              );
            }
            return (
              <MsgBubble key={`m-${it.id}`} msg={it}
                          onCorrect={() => setCorrectingMsg({
                            msg: it,
                            userQuestion: _findPrevUserQuestion(timeline, idx),
                          })} />
            );
          })}
          {timeline.length === 0 && (
            <div style={{ textAlign: "center", color: "var(--text-muted)",
                           fontSize: 12, padding: 30 }}>
              Sem mensagens nesta conversa ainda.
            </div>
          )}
        </div>
      </div>
      {/* Botão flutuante "↓ Ir para o final" + badge de não lidas */}
      {showScrollDown && (
        <button onClick={scrollToBottom}
                data-testid="wa-scroll-to-bottom"
                title="Ir para a mensagem mais recente"
                style={{
                  position: "absolute", right: 18, bottom: 16, zIndex: 5,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 42, height: 42, borderRadius: "50%",
                  background: "#ffffff",
                  color: "#54656f", border: "none",
                  boxShadow: "0 4px 12px rgba(11,20,26,.18)",
                  cursor: "pointer", transition: "transform .12s, box-shadow .12s",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = "translateY(-2px)";
                  e.currentTarget.style.boxShadow = "0 6px 18px rgba(11,20,26,.25)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = "translateY(0)";
                  e.currentTarget.style.boxShadow = "0 4px 12px rgba(11,20,26,.18)";
                }}>
          <ChevronDown size={22} strokeWidth={2.2} />
          {newCountWhileAway > 0 && (
            <span data-testid="wa-scroll-newcount" style={{
              position: "absolute", top: -4, right: -4,
              minWidth: 20, height: 20, padding: "0 6px",
              borderRadius: 999, background: "#25d366", color: "#fff",
              fontSize: 10, fontWeight: 800,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              border: "2px solid #efeae2", lineHeight: 1,
            }}>
              {newCountWhileAway > 99 ? "99+" : newCountWhileAway}
            </span>
          )}
        </button>
      )}
      </div>

      {/* Indicador "Isabella digitando..." — aparece logo acima do composer
          quando a IA está processando a resposta (ai_typing_until > now). */}
      {aiTyping && (
        <div data-testid="wa-ai-typing-bar"
             style={{
               padding: "6px 14px",
               background: "var(--bg-surface)",
               borderTop: "1px solid var(--border-default)",
               display: "flex", alignItems: "center", gap: 8,
               fontSize: 12, color: "#7c3aed", fontWeight: 600,
               animation: "wa-typing-fade 0.3s ease",
             }}>
          <span style={{ display: "inline-flex", gap: 3 }}>
            <span className="wa-typing-dot" style={{
              width: 6, height: 6, borderRadius: "50%",
              background: "#7c3aed",
              animation: "wa-typing-dot 1.2s ease-in-out infinite",
            }} />
            <span className="wa-typing-dot" style={{
              width: 6, height: 6, borderRadius: "50%",
              background: "#7c3aed",
              animation: "wa-typing-dot 1.2s ease-in-out 0.2s infinite",
            }} />
            <span className="wa-typing-dot" style={{
              width: 6, height: 6, borderRadius: "50%",
              background: "#7c3aed",
              animation: "wa-typing-dot 1.2s ease-in-out 0.4s infinite",
            }} />
          </span>
          <span>{aiTypingAgent} digitando…</span>
        </div>
      )}

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
          : (recording
              ? `🔴 Gravando áudio... ${recDuration}s — clique no microfone novamente para enviar`
              : "Digite sua mensagem (vai pro cliente via WhatsApp)...")}
          value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !sending && send()}
          disabled={isAi || recording}
          data-testid="wa-composer-input"
          style={{ flex: 1 }} />
        {/* Botão de microfone — clica pra começar, clica pra parar/enviar.
            Long-press pra cancelar (segura por 1s e arrasta sai). */}
        {!isAi && !text.trim() && (
          <button
            data-testid="wa-mic-btn"
            onClick={() => (recording ? stopRecording(false) : startRecording())}
            onContextMenu={(e) => { e.preventDefault(); stopRecording(true); }}
            disabled={sending}
            title={recording
              ? "Parar e enviar áudio (botão direito = cancelar)"
              : "Gravar mensagem de voz"}
            style={{
              flexShrink: 0,
              width: 40, height: 40, borderRadius: "50%",
              border: "none", cursor: "pointer",
              display: "grid", placeItems: "center",
              background: recording
                ? "linear-gradient(135deg, #ef4444, #b91c1c)"
                : "linear-gradient(135deg, #25d366, #128c7e)",
              color: "#fff",
              boxShadow: recording
                ? "0 0 0 4px rgba(239,68,68,.3)" : "0 1px 3px rgba(18,140,126,.3)",
              transition: "all .2s",
              animation: recording ? "wa-pulse 1.4s ease-in-out infinite" : "none",
            }}>
            <Mic size={18} strokeWidth={2.2} />
          </button>
        )}
        <button onClick={send} disabled={sending || !text.trim() || isAi || recording}
                className="btn btn-primary btn-sm"
                data-testid="wa-composer-send"
                style={{ visibility: text.trim() ? "visible" : "hidden",
                          width: text.trim() ? "auto" : 0,
                          padding: text.trim() ? undefined : 0,
                          margin: text.trim() ? undefined : 0 }}>
          <Send size={13} /> {sending ? "..." : "Enviar"}
        </button>
      </div>

      <style>{`
        @keyframes wa-pulse { 0%,100% { transform:scale(1); opacity:1; }
          50% { transform:scale(1.25); opacity:.7; } }
        @keyframes wa-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
        @keyframes wa-typing-dot {
          0%,80%,100% { opacity: 0.3; transform: translateY(0); }
          40% { opacity: 1; transform: translateY(-2px); }
        }
        @keyframes wa-typing-fade {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {correctingMsg && (
        <AiCorrectionModal
          phone={conv?.phone}
          original={correctingMsg.msg}
          userQuestion={correctingMsg.userQuestion}
          onClose={() => setCorrectingMsg(null)}
          onSaved={async () => { setCorrectingMsg(null); await loadMessages(); }}
        />
      )}
    </div>
  );
}

// Badge discreto que mostra o canal de origem da mensagem.
// Aparece sempre que o canal NÃO é o padrão (baileys) — assim o gestor
// identifica visualmente que aquela conversa pode ter rotas múltiplas.
function ChannelBadge({ channel, small }) {
  if (!channel) return null;
  const map = {
    baileys: { label: "Baileys", color: "#15803d", bg: "#f0fdf4", border: "#bbf7d0" },
    twilio: { label: "Twilio", color: "#b91c1c", bg: "#fef2f2", border: "#fecaca" },
    meta_whatsapp_cloud: { label: "Meta Cloud", color: "#0369a1", bg: "#eff6ff", border: "#bfdbfe" },
    meta_messenger: { label: "Messenger", color: "#0369a1", bg: "#eff6ff", border: "#bfdbfe" },
    meta_instagram: { label: "Instagram", color: "#7c3aed", bg: "#faf5ff", border: "#e9d5ff" },
  };
  const info = map[channel] || { label: channel, color: "#64748b", bg: "#f8fafc", border: "#e2e8f0" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 3,
      padding: small ? "1px 5px" : "2px 7px",
      borderRadius: 4, fontSize: small ? 8.5 : 10, fontWeight: 700,
      color: info.color, background: info.bg,
      border: `1px solid ${info.border}`,
      letterSpacing: 0.3, textTransform: "uppercase",
      marginBottom: small ? 3 : 0, marginRight: 4,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: info.color }} />
      {info.label}
    </span>
  );
}

// Helper: encontra a última mensagem inbound (do cliente) ANTES da bolha
// que está sendo corrigida — essa é a "pergunta" que originou a resposta.
function _findPrevUserQuestion(timeline, idx) {
  for (let i = idx - 1; i >= 0; i--) {
    const t = timeline[i];
    if (t._kind === "coaching") continue;
    if (t.direction === "inbound" && t.text) return t.text;
  }
  return "";
}

/* =============================================================
   InternalCoachingBubble — bolha INTERNA de coaching IA inline.
   • Aparece no meio do chat, com fundo roxo distintivo
   • Visível APENAS para o atendente logado (filtrado no backend por user_id)
   • Nunca vai pelo WhatsApp pro cliente
   • Label "🔒 SOMENTE VOCÊ VÊ" pra reforçar
============================================================= */
// Botão circular só com ícone — tooltip aparece no hover.
function IconBtn({ icon, tooltip, onClick, disabled, variant = "default",
                    hoverColor, ...rest }) {
  const [hover, setHover] = useState(false);
  const isPrimary = variant === "primary";
  const baseColor = isPrimary ? "var(--bg-surface)" : "var(--text-secondary)";
  const baseBg = isPrimary ? "var(--text-primary)" : "transparent";
  const baseBorder = isPrimary ? "var(--text-primary)" : "var(--border-default)";
  const hoverC = hoverColor || (isPrimary ? baseColor : "var(--text-primary)");
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={onClick}
        disabled={disabled}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 32, height: 32, borderRadius: 8,
          background: baseBg,
          color: hover && !disabled && !isPrimary ? hoverC : baseColor,
          border: `1px solid ${hover && !disabled && !isPrimary ? hoverC : baseBorder}`,
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
          transition: "color 0.15s, border-color 0.15s, transform 0.15s",
          transform: hover && !disabled ? "translateY(-1px)" : "none",
        }}
        {...rest}
      >
        {icon}
      </button>
      {hover && tooltip && (
        <div role="tooltip"
              style={{
                position: "absolute", top: "calc(100% + 6px)", right: 0,
                background: "rgba(15,23,42,.95)", color: "white",
                padding: "5px 10px", borderRadius: 6,
                fontSize: 11, fontWeight: 500,
                whiteSpace: "nowrap", maxWidth: 280,
                pointerEvents: "none", zIndex: 100,
                boxShadow: "0 6px 18px rgba(0,0,0,.25)",
              }}>
          {tooltip}
        </div>
      )}
    </div>
  );
}

/* ChatStartBadge — pílula no TOPO do chat mostrando quem iniciou a conversa
   e quando. Aparece uma única vez (1ª mensagem real). */
function ChatStartBadge({ started_by, ts }) {
  if (!ts) return null;
  const dt = new Date(ts);
  if (isNaN(dt.getTime())) return null;
  const dataFmt = dt.toLocaleDateString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
  const horaFmt = dt.toLocaleTimeString("pt-BR", {
    hour: "2-digit", minute: "2-digit",
  });
  return (
    <div data-testid="wa-chat-start-badge"
         style={{
           display: "flex", justifyContent: "center",
           margin: "10px 0 14px",
         }}>
      <div style={{
        padding: "8px 18px", borderRadius: 18,
        background: "rgba(255,255,255,0.92)",
        backdropFilter: "blur(6px)",
        boxShadow: "0 1px 2px rgba(0,0,0,0.08)",
        fontSize: 12, fontWeight: 700, color: "#475569",
        textAlign: "center", lineHeight: 1.45,
        border: "1px solid rgba(15,23,42,0.06)",
      }}>
        <div style={{ letterSpacing: 0.5, textTransform: "uppercase",
                       fontSize: 11, color: "#334155" }}>
          Chat iniciado por: <span style={{ color: "#16a34a" }}>{started_by}</span>
        </div>
        <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600,
                       marginTop: 2 }}>
          ({dataFmt} – {horaFmt})
        </div>
      </div>
    </div>
  );
}


/* DayDivider — separador "Hoje", "Ontem" ou data formatada exibido entre
 * mensagens de dias diferentes, igual WhatsApp/Telegram. */
function DayDivider({ day }) {
  // day = "YYYY-MM-DD"
  const label = (() => {
    if (!day) return "";
    const [y, m, d] = day.split("-").map(Number);
    if (!y || !m || !d) return day;
    const dt = new Date(y, m - 1, d);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const ydt = new Date(today);
    ydt.setDate(today.getDate() - 1);
    if (dt.getTime() === today.getTime()) return "Hoje";
    if (dt.getTime() === ydt.getTime()) return "Ontem";
    const diff = (today - dt) / 86400000;
    if (diff > 0 && diff < 7) {
      // Dia da semana ("Sexta-feira")
      return dt.toLocaleDateString("pt-BR", { weekday: "long" })
                .replace(/^./, (c) => c.toUpperCase());
    }
    // Data completa em PT-BR
    return dt.toLocaleDateString("pt-BR", {
      day: "2-digit", month: "long", year: "numeric",
    });
  })();
  return (
    <div data-testid={`wa-daydiv-${day}`} style={{
      display: "flex", justifyContent: "center",
      margin: "12px 0 8px",
    }}>
      <span style={{
        padding: "4px 12px",
        borderRadius: 999,
        background: "rgba(225, 220, 200, 0.95)",
        color: "#54656f",
        fontSize: 11.5, fontWeight: 600,
        boxShadow: "0 1px 1px rgba(11,20,26,.08)",
        textTransform: "capitalize",
        letterSpacing: 0.2,
      }}>
        {label}
      </span>
    </div>
  );
}



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

function InternalNoteBubble({ msg }) {
  const time = msg.created_at
    ? new Date(msg.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : "";
  const kind = msg.internal_kind || "outage_active";
  let accent, bg, border, badge;
  if (kind === "copilot_hint") {
    accent = "#0ea5e9"; bg = "#f0f9ff"; border = "#bae6fd";
    badge = "Co-Pilot IA · Apenas você vê";
  } else if (kind === "outage_resolved") {
    accent = "#16a34a"; bg = "#f0fdf4"; border = "#bbf7d0";
    badge = "IA · Apenas você vê (não enviado ao cliente)";
  } else {
    accent = "#d97706"; bg = "#fffbeb"; border = "#fde68a";
    badge = "IA · Apenas você vê (não enviado ao cliente)";
  }
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "2px 0" }}>
      <div data-testid={`wa-internal-note-${msg.id || ""}`}
            data-internal-kind={kind}
            style={{
        maxWidth: "85%", width: "100%",
        padding: "9px 12px", borderRadius: 8,
        background: bg,
        border: `1px dashed ${border}`,
        borderLeft: `3px solid ${accent}`,
        fontSize: 12, lineHeight: 1.5,
        color: "#0f172a",
        position: "relative",
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 5,
          fontSize: 9.5, fontWeight: 800, color: accent,
          textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4,
        }}>
          {kind === "copilot_hint"
            ? <Lightbulb size={10} strokeWidth={2.5} />
            : <Lock size={10} strokeWidth={2.5} />}
          {badge}
        </div>
        <div style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{msg.text}</div>
        <div style={{
          fontSize: 9, color: "#94a3b8", marginTop: 4,
          textAlign: "right",
        }}>{time}</div>
      </div>
    </div>
  );
}

/* =============================================================
   InlineAudioPlayer — player de áudio compacto dentro do balão.
   Play/pause + barra de progresso + duração.
   `outbound` muda as cores pra combinar com o balão verde da atendente.
============================================================= */
function InlineAudioPlayer({ src, duration: durationProp, outbound }) {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [dur, setDur] = useState(Number(durationProp) || 0);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return undefined;
    const onTime = () => setPos(el.currentTime || 0);
    const onLoaded = () => {
      if (!isNaN(el.duration) && el.duration !== Infinity) setDur(el.duration);
    };
    const onEnd = () => { setPlaying(false); setPos(0); };
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("loadedmetadata", onLoaded);
    el.addEventListener("durationchange", onLoaded);
    el.addEventListener("ended", onEnd);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("loadedmetadata", onLoaded);
      el.removeEventListener("durationchange", onLoaded);
      el.removeEventListener("ended", onEnd);
    };
  }, []);

  const toggle = () => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) { el.pause(); setPlaying(false); }
    else { el.play().then(() => setPlaying(true)).catch(() => setPlaying(false)); }
  };

  const seek = (e) => {
    const el = audioRef.current;
    if (!el || !dur) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    el.currentTime = dur * ratio;
    setPos(dur * ratio);
  };

  const fmt = (s) => {
    if (!s || isNaN(s)) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${String(sec).padStart(2, "0")}`;
  };

  const pct = dur > 0 ? (pos / dur) * 100 : 0;
  const accent = outbound ? "#15803d" : "#0369a1";
  const trackBg = outbound ? "rgba(21,128,61,0.18)" : "rgba(3,105,161,0.18)";

  return (
    <div data-testid="wa-audio-player"
         style={{ display: "flex", alignItems: "center", gap: 10,
                   minWidth: 220, padding: "2px 0" }}>
      <button onClick={toggle}
              data-testid="wa-audio-play-btn"
              aria-label={playing ? "Pausar" : "Reproduzir"}
              style={{
                width: 32, height: 32, borderRadius: "50%",
                background: accent, color: "white",
                border: "none", cursor: "pointer",
                display: "grid", placeItems: "center",
                flexShrink: 0, boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
              }}>
        {playing ? <Pause size={14} strokeWidth={2.5} />
                  : <Play size={14} strokeWidth={2.5} style={{ marginLeft: 2 }} />}
      </button>
      <div style={{ flex: 1, minWidth: 80 }}>
        <div onClick={seek}
             data-testid="wa-audio-progress"
             style={{
               height: 4, background: trackBg, borderRadius: 999,
               cursor: dur > 0 ? "pointer" : "default", overflow: "hidden",
             }}>
          <div style={{
            width: pct + "%", height: "100%", background: accent,
            transition: playing ? "none" : "width 0.2s",
          }} />
        </div>
        <div style={{ fontSize: 10, color: "#64748b",
                       marginTop: 3, fontFamily: "monospace" }}>
          {fmt(pos)} / {fmt(dur)}
        </div>
      </div>
      <audio ref={audioRef} src={src} preload="metadata" style={{ display: "none" }} />
    </div>
  );
}

/* =============================================================
   QuickImagesPopover — modal listando as imagens rápidas
   pré-cadastradas em Configuração. Clica e envia direto.
============================================================= */
function QuickImagesPopover({ phone, onClose, onSent }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(null);
  const [caption, setCaption] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api._client.get("/whatsapp-baileys/quick-images")
      .then((r) => setItems(r.data.items || []))
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, []);

  async function send(it) {
    setSending(it.id);
    setError("");
    try {
      await api._client.post(`/whatsapp-baileys/quick-images/${it.id}/send`, {
        phone, caption,
      });
      onSent();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally { setSending(null); }
  }

  const token = window.localStorage.getItem("ponto_token") || "";
  const baseUrl = process.env.REACT_APP_BACKEND_URL || "";

  return (
    <div onClick={onClose} data-testid="wa-quick-images-modal"
         style={{ position: "fixed", inset: 0, zIndex: 1000,
                   background: "rgba(2,6,23,0.6)",
                   display: "grid", placeItems: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: "white", borderRadius: 14, padding: 20,
                     maxWidth: 720, width: "100%", maxHeight: "85vh",
                     overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#0f172a",
                        display: "flex", alignItems: "center", gap: 8 }}>
            <ImagePlus size={20} style={{ color: "#7c3aed" }} />
            Imagens Rápidas
          </h3>
          <button onClick={onClose} style={{ border: "none",
                                                background: "transparent",
                                                cursor: "pointer", color: "#64748b" }}>
            <X size={20} />
          </button>
        </div>

        <input type="text" value={caption}
                onChange={(e) => setCaption(e.target.value)}
                placeholder="Legenda (opcional, enviada junto da imagem)"
                data-testid="wa-quick-images-caption"
                style={{
                  width: "100%", padding: 10, borderRadius: 8,
                  border: "1px solid #cbd5e1", fontSize: 13,
                  fontFamily: "inherit", marginBottom: 14,
                }} />

        {loading ? (
          <p style={{ color: "#64748b", textAlign: "center", padding: 24 }}>
            Carregando...
          </p>
        ) : items.length === 0 ? (
          <div style={{ padding: 30, textAlign: "center",
                         background: "#f8fafc", borderRadius: 10,
                         border: "1px dashed #cbd5e1" }}>
            <ImagePlus size={32} style={{ color: "#94a3b8", marginBottom: 8 }} />
            <p style={{ color: "#64748b", fontSize: 13, margin: 0 }}>
              Nenhuma imagem rápida cadastrada.<br />
              Vá em <strong>Configuração → Imagens Rápidas</strong> para adicionar.
            </p>
          </div>
        ) : (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: 12,
          }}>
            {items.map((it) => (
              <div key={it.id}
                   data-testid={`wa-quick-images-card-${it.id}`}
                   style={{
                     border: "1px solid #e2e8f0",
                     borderRadius: 10, overflow: "hidden",
                     background: "white", position: "relative",
                     transition: "transform 0.15s, box-shadow 0.15s",
                   }}
                   onMouseEnter={(e) => {
                     e.currentTarget.style.boxShadow = "0 6px 16px rgba(124,58,237,0.18)";
                     e.currentTarget.style.transform = "translateY(-2px)";
                   }}
                   onMouseLeave={(e) => {
                     e.currentTarget.style.boxShadow = "none";
                     e.currentTarget.style.transform = "translateY(0)";
                   }}>
                <div style={{
                  aspectRatio: "16/10", background: "#f1f5f9",
                  backgroundImage: `url("${baseUrl}${it.url}?t=${encodeURIComponent(token)}")`,
                  backgroundSize: "cover", backgroundPosition: "center",
                }} />
                <div style={{ padding: 8, display: "flex",
                                 flexDirection: "column", gap: 6 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#475569",
                                  textAlign: "left", whiteSpace: "nowrap",
                                  overflow: "hidden", textOverflow: "ellipsis" }}
                        title={it.label || "(sem nome)"}>
                    {it.label || "(sem nome)"}
                  </div>
                  <button
                    onClick={() => send(it)}
                    disabled={sending === it.id}
                    data-testid={`wa-quick-images-send-${it.id}`}
                    style={{
                      padding: "8px 12px", borderRadius: 8,
                      border: "none",
                      background: sending === it.id
                        ? "#94a3b8"
                        : "linear-gradient(135deg, #25d366, #128c7e)",
                      color: "white", fontSize: 12, fontWeight: 700,
                      cursor: sending === it.id ? "wait" : "pointer",
                      display: "flex", alignItems: "center",
                      justifyContent: "center", gap: 6,
                      boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                    }}>
                    <Send size={12} strokeWidth={2.5} />
                    {sending === it.id ? "Enviando..." : "Enviar para o cliente"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div style={{ marginTop: 12, padding: 10, borderRadius: 8,
                         background: "#fee2e2", color: "#991b1b", fontSize: 12 }}>
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

/* =============================================================
   PdfResultToast — feedback após gerar transcrição PDF.

/* FinalizeAtendimentoModal — confirmação visual (não window.confirm) */
function FinalizeAtendimentoModal({ onCancel, onConfirm }) {
  return (
    <div onClick={onCancel}
         data-testid="wa-finalize-modal"
         style={{
           position: "fixed", inset: 0, zIndex: 1100,
           background: "rgba(2,6,23,0.55)",
           display: "grid", placeItems: "center", padding: 20,
         }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "white", borderRadius: 16, padding: 24,
             maxWidth: 380, width: "100%",
             boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
             textAlign: "center",
           }}>
        <div style={{
          width: 56, height: 56, borderRadius: "50%",
          background: "#16a34a", color: "white",
          display: "grid", placeItems: "center",
          margin: "0 auto 14px",
          boxShadow: "0 4px 14px rgba(22,163,74,0.3)",
        }}>
          <CheckCircle2 size={28} strokeWidth={2.5} />
        </div>
        <h3 style={{
          margin: 0, fontSize: 18, fontWeight: 700, color: "#0f172a",
        }}>
          Finalizar Atendimento
        </h3>
        <p style={{
          margin: "10px 0 22px", fontSize: 14, color: "#475569",
          lineHeight: 1.55,
        }}>
          Tem certeza que deseja finalizar o atendimento? A conversa sairá da fila.
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button onClick={onCancel}
                   data-testid="wa-finalize-no"
                   style={{
                     padding: "10px 28px", borderRadius: 10, fontSize: 14,
                     fontWeight: 700, cursor: "pointer",
                     background: "white", color: "#475569",
                     border: "1.5px solid #cbd5e1",
                     minWidth: 100,
                   }}>NÃO</button>
          <button onClick={onConfirm}
                   data-testid="wa-finalize-yes"
                   style={{
                     padding: "10px 28px", borderRadius: 10, fontSize: 14,
                     fontWeight: 700, cursor: "pointer",
                     background: "#16a34a", color: "white", border: "none",
                     boxShadow: "0 2px 6px rgba(22,163,74,0.25)",
                     minWidth: 100,
                   }}>SIM</button>
        </div>
      </div>
    </div>
  );
}


/* =============================================================
   PdfResultToast — feedback após gerar transcrição PDF.
============================================================= */
function PdfResultToast({ result, onClose }) {
  useEffect(() => {
    const id = setTimeout(onClose, 8000);
    return () => clearTimeout(id);
  }, [onClose]);
  return (
    <div data-testid="wa-pdf-result-toast"
         style={{
           position: "fixed", bottom: 20, right: 20, zIndex: 999,
           padding: 14, borderRadius: 10, maxWidth: 380,
           background: "#dcfce7", color: "#166534",
           border: "1px solid #86efac", fontSize: 13,
           boxShadow: "0 6px 16px rgba(0,0,0,0.1)",
         }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700 }}>
        <FileDown size={16} /> PDF gerado com sucesso
      </div>
      <div style={{ marginTop: 6, fontSize: 12 }}>
        {result.message_count} mensagens · {Math.round((result.document?.size_bytes || 0) / 1024)} KB
      </div>
      {result.subscriber_linked ? (
        <div style={{ marginTop: 6, fontSize: 11, color: "#166534" }}>
          ✓ Vinculado ao cadastro do cliente
        </div>
      ) : (
        <div style={{ marginTop: 6, fontSize: 11, color: "#92400e" }}>
          ⚠ Cliente não cadastrado — PDF salvo, mas sem vínculo
        </div>
      )}
    </div>
  );
}



function MsgBubble({ msg, onCorrect }) {
  // Nota interna (co-piloto IA — NUNCA enviada ao cliente)
  if (msg.direction === "internal" || msg.is_internal_note) {
    return <InternalNoteBubble msg={msg} />;
  }
  const out = msg.direction === "outbound";
  const isAi = !!msg.auto_reply;
  const isCorrection = !!msg.is_correction;
  const dst = msg.delivery_status || "";
  const failed = out && (dst === "failed" || dst.startsWith("failed_"));
  const sent = out && dst === "sent";
  // Failed AI sem texto (gerou erro antes de redigir) → render como placeholder.
  // Correções (is_correction) que falharam NÃO são silent failures da IA —
  // são re-envios manuais do atendente que não chegaram ao WhatsApp.
  const aiSilentFailure = failed && isAi && !isCorrection && !msg.text;
  const failureLabel = (() => {
    if (!failed) return null;
    if (isCorrection) return "Correção não enviada (WhatsApp offline)";
    if (dst === "failed_disabled") return "IA desligada — não respondeu";
    if (dst === "failed_no_agent") return "Agente IA não cadastrado";
    if (dst === "failed_llm_error") return "Motor IA falhou";
    if (dst === "failed_motor_ia_unavailable") return "Motor IA indisponível";
    if (dst === "failed_empty_reply") return "IA retornou resposta vazia";
    if (dst === "failed_sidecar") return "Falha ao enviar para WhatsApp";
    return "Não entregue";
  })();
  const time = msg.created_at
    ? new Date(msg.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : "";
  return (
    <div style={{
      display: "flex", justifyContent: out ? "flex-end" : "flex-start",
    }}>
      <div data-testid={`wa-msg-${msg.id || msg.message_id || ""}`}
            data-delivery={out ? (msg.delivery_status || "unknown") : ""}
            style={{
        maxWidth: "70%",
        padding: "8px 12px", borderRadius: out ? "12px 12px 4px 12px" : "12px 12px 12px 4px",
        background: failed
          ? "#fef2f2"
          : out ? (isAi ? "#bae6fd" : "#dcfce7") : "#fff",
        color: "#0f172a",
        border: failed
          ? "1px solid #fecaca"
          : "1px solid rgba(0,0,0,.05)",
        fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap",
        boxShadow: "0 1px 2px rgba(0,0,0,.05)",
        opacity: failed ? 0.95 : 1,
      }}>
        {/* Channel badge — discreto, mostra de onde a msg veio/saiu */}
        {msg.channel && msg.channel !== "baileys" && (
          <ChannelBadge channel={msg.channel} small />
        )}
        {out && isAi && (
          <div style={{ fontSize: 9, fontWeight: 800,
                         color: failed
                          ? (isCorrection ? "#92400e" : "#dc2626")
                          : (isCorrection ? "#15803d" : "#0369a1"),
                         marginBottom: 3, textTransform: "uppercase",
                         letterSpacing: 0.5, display: "flex", alignItems: "center", gap: 6 }}>
            {failed
              ? (isCorrection
                  ? "⚠ Correção · não enviada"
                  : "⚠ Isabella IA — falhou")
              : (isCorrection ? "Isabella IA · Corrigida" : "Isabella IA")}
            {!failed && msg.text && onCorrect && (
              <button
                onClick={() => onCorrect()}
                data-testid={`wa-correct-btn-${msg.id || ""}`}
                title="Corrigir esta resposta e ensinar a Isabella"
                style={{
                  marginLeft: "auto", border: "1px solid #bae6fd",
                  background: "rgba(255,255,255,.6)", color: "#0369a1",
                  borderRadius: 999, padding: "1px 8px",
                  fontSize: 9, fontWeight: 700, cursor: "pointer",
                  letterSpacing: 0.3,
                }}
              >
                ✏ Corrigir
              </button>
            )}
          </div>
        )}
        <div>{aiSilentFailure
          ? <em style={{ color: "#991b1b" }}>
              Cliente mandou mensagem, mas a IA não respondeu — {failureLabel}.
            </em>
          : msg.media_type === "audio" && msg.media_url
            ? <InlineAudioPlayer
                src={`${process.env.REACT_APP_BACKEND_URL || ""}${msg.media_url}?t=${encodeURIComponent(window.localStorage.getItem("ponto_token") || "")}`}
                duration={msg.media_duration_sec}
                outbound={out}
              />
            : msg.text}</div>
        <div style={{
          fontSize: 9, color: failed ? "#dc2626" : "#64748b", marginTop: 3,
          display: "flex", alignItems: "center", gap: 4, justifyContent: "flex-end",
          fontWeight: failed ? 700 : 400,
        }}>
          <span>{time}</span>
          {out && (failed ? (
            <span title={msg.delivery_error
                          ? `${failureLabel}: ${msg.delivery_error}`
                          : failureLabel}
                  data-testid={`wa-msg-failed-${msg.id || ""}`}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 3,
                    color: "#dc2626",
                  }}>
              <AlertTriangle size={11} strokeWidth={2.5} />
              <span>{failureLabel}</span>
            </span>
          ) : sent ? (
            <CheckCheck size={11} style={{ color: "#0ea5e9" }} />
          ) : (
            <Check size={11} style={{ color: "#94a3b8" }} />
          ))}
        </div>
      </div>
    </div>
  );
}

// Modal Edit & Teach — Corrigir resposta da Isabella e ensinar
function AiCorrectionModal({ phone, original, userQuestion, onClose, onSaved }) {
  const [correctReply, setCorrectReply] = useState("");
  const [reason, setReason] = useState("");
  const [resend, setResend] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const save = async () => {
    if (correctReply.trim().length < 2) {
      setErr("Digite a resposta correta.");
      return;
    }
    setSaving(true); setErr("");
    try {
      await api.aiCorrectionCreate({
        phone,
        original_msg_id: original?.id,
        user_question: userQuestion || "",
        ai_original_reply: original?.text || "",
        correct_reply: correctReply.trim(),
        reason: reason.trim(),
        resend_to_client: resend,
      });
      if (onSaved) await onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao salvar.");
    } finally { setSaving(false); }
  };

  return (
    <div onClick={onClose} data-testid="ai-correction-modal" style={{
      position: "fixed", inset: 0, background: "rgba(2,6,23,.55)",
      display: "grid", placeItems: "center", zIndex: 1000, padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 14, width: "100%", maxWidth: 560,
        padding: 22, border: "1px solid #e2e8f0",
        boxShadow: "0 20px 60px rgba(2,6,23,.25)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: "#fef3c7", color: "#b45309",
            display: "grid", placeItems: "center",
            border: "1px solid #fcd34d",
          }}>✏</div>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0f172a" }}>
              Corrigir e Ensinar a Isabella IA
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: 11, color: "#64748b" }}>
              A correção vira memória permanente — a IA não vai mais repetir o erro.
            </p>
          </div>
        </div>

        {userQuestion && (
          <div style={{ marginTop: 14, marginBottom: 10 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
              Cliente perguntou
            </div>
            <div style={{
              padding: "8px 12px", background: "#f8fafc",
              border: "1px solid #e2e8f0", borderRadius: 8,
              fontSize: 12, color: "#334155", maxHeight: 80, overflow: "auto",
            }}>{userQuestion}</div>
          </div>
        )}

        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#b91c1c", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
            Resposta atual (errada)
          </div>
          <div style={{
            padding: "8px 12px", background: "#fef2f2",
            border: "1px solid #fecaca", borderRadius: 8,
            fontSize: 12, color: "#7f1d1d", maxHeight: 100, overflow: "auto",
          }}>{original?.text || "—"}</div>
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 10, fontWeight: 700, color: "#15803d", textTransform: "uppercase", letterSpacing: 0.5, display: "block", marginBottom: 4 }}>
            Resposta correta
          </label>
          <textarea
            data-testid="ai-correction-textarea"
            value={correctReply}
            onChange={(e) => setCorrectReply(e.target.value)}
            rows={4}
            autoFocus
            placeholder="Como a Isabella deveria ter respondido neste contexto?"
            style={{
              width: "100%", padding: "10px 12px",
              background: "#f0fdf4", border: "1px solid #bbf7d0",
              borderRadius: 8, fontSize: 13, color: "#0f172a",
              resize: "vertical", fontFamily: "inherit",
            }}
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5, display: "block", marginBottom: 4 }}>
            Motivo (opcional)
          </label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Ex.: ignorou que o cliente já tem plano premium"
            style={{
              width: "100%", padding: "8px 12px",
              border: "1px solid #e2e8f0", borderRadius: 8,
              fontSize: 12, color: "#0f172a", boxSizing: "border-box",
            }}
          />
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#0f172a", cursor: "pointer", marginBottom: 14 }}>
          <input
            type="checkbox"
            checked={resend}
            onChange={(e) => setResend(e.target.checked)}
            data-testid="ai-correction-resend"
          />
          Reenviar versão corrigida ao cliente agora
        </label>

        {err && <div style={{ background: "#fef2f2", color: "#991b1b", padding: "8px 12px", borderRadius: 8, fontSize: 12, marginBottom: 10, border: "1px solid #fecaca" }}>{err}</div>}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} disabled={saving}
                   style={{ padding: "8px 14px", border: "1px solid #e2e8f0", borderRadius: 8, background: "white", color: "#475569", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
            Cancelar
          </button>
          <button
            data-testid="ai-correction-save"
            onClick={save}
            disabled={saving || correctReply.trim().length < 2}
            style={{ padding: "8px 16px", border: 0, borderRadius: 8, background: "#0f172a", color: "white", fontWeight: 700, fontSize: 13, cursor: "pointer", opacity: saving ? 0.6 : 1 }}
          >
            {saving ? "Salvando..." : "Salvar correção"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Modal para anexar imagem à conversa — escolher do dispositivo + preview + legenda.
function ImagePickerModal({ phone, onClose, onSent }) {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [caption, setCaption] = useState("");
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");
  const inputRef = useRef(null);

  const handleFile = (f) => {
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      setErr("Selecione um arquivo de imagem (PNG, JPG, WebP, GIF).");
      return;
    }
    if (f.size > 8 * 1024 * 1024) {
      setErr("Arquivo muito grande — máximo 8 MB.");
      return;
    }
    setErr("");
    setFile(f);
    const url = URL.createObjectURL(f);
    setPreviewUrl(url);
  };

  useEffect(() => {
    return () => { if (previewUrl) URL.revokeObjectURL(previewUrl); };
  }, [previewUrl]);

  const send = async () => {
    if (!file) { setErr("Escolha uma imagem primeiro."); return; }
    setSending(true); setErr("");
    try {
      // Converte para base64 e envia
      const reader = new FileReader();
      const dataUrl = await new Promise((res, rej) => {
        reader.onload = () => res(reader.result);
        reader.onerror = rej;
        reader.readAsDataURL(file);
      });
      await api.waBaileysSendImage(phone, dataUrl, caption || "");
      if (onSent) await onSent();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao enviar.");
    } finally { setSending(false); }
  };

  return (
    <div onClick={onClose} data-testid="image-picker-modal" style={{
      position: "fixed", inset: 0, background: "rgba(2,6,23,.55)",
      display: "grid", placeItems: "center", zIndex: 1000, padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 14, width: "100%", maxWidth: 480,
        padding: 22, border: "1px solid #e2e8f0",
        boxShadow: "0 20px 60px rgba(2,6,23,.25)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: "#dbeafe", color: "#0369a1",
            display: "grid", placeItems: "center",
            border: "1px solid #bae6fd",
          }}><Image size={18} /></div>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0f172a" }}>
              Anexar imagem
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: 11, color: "#64748b" }}>
              Escolha uma foto do dispositivo e adicione uma legenda opcional.
            </p>
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          onChange={(e) => handleFile(e.target.files?.[0])}
          style={{ display: "none" }}
          data-testid="image-picker-file-input"
        />

        {previewUrl ? (
          <div style={{ marginBottom: 12 }}>
            <img src={previewUrl} alt="preview"
                  style={{ width: "100%", maxHeight: 280, objectFit: "contain", borderRadius: 8, background: "#f8fafc", border: "1px solid #e2e8f0" }} />
            <button onClick={() => inputRef.current?.click()}
                     data-testid="image-picker-change"
                     style={{ marginTop: 8, padding: "6px 12px", border: "1px solid #e2e8f0", borderRadius: 8, background: "white", color: "#475569", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              Trocar imagem
            </button>
          </div>
        ) : (
          <button
            onClick={() => inputRef.current?.click()}
            data-testid="image-picker-choose"
            style={{
              width: "100%", padding: "32px 16px",
              border: "2px dashed #cbd5e1", borderRadius: 10,
              background: "#f8fafc", color: "#475569",
              fontSize: 13, fontWeight: 600, cursor: "pointer",
              display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
              marginBottom: 12,
            }}
          >
            <Image size={28} strokeWidth={1.5} style={{ color: "#94a3b8" }} />
            Clique para escolher uma imagem
            <span style={{ fontSize: 10, color: "#94a3b8", fontWeight: 500 }}>PNG, JPG, WebP, GIF · até 8 MB</span>
          </button>
        )}

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5, display: "block", marginBottom: 4 }}>
            Legenda (opcional)
          </label>
          <input
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="Adicione uma legenda..."
            data-testid="image-picker-caption"
            style={{
              width: "100%", padding: "8px 12px",
              border: "1px solid #e2e8f0", borderRadius: 8,
              fontSize: 13, color: "#0f172a", boxSizing: "border-box",
            }}
          />
        </div>

        {err && <div style={{ background: "#fef2f2", color: "#991b1b", padding: "8px 12px", borderRadius: 8, fontSize: 12, marginBottom: 10, border: "1px solid #fecaca" }}>{err}</div>}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} disabled={sending}
                   style={{ padding: "8px 14px", border: "1px solid #e2e8f0", borderRadius: 8, background: "white", color: "#475569", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
            Cancelar
          </button>
          <button
            onClick={send}
            disabled={sending || !file}
            data-testid="image-picker-send"
            style={{ padding: "8px 16px", border: 0, borderRadius: 8, background: "#0f172a", color: "white", fontWeight: 700, fontSize: 13, cursor: "pointer", opacity: sending || !file ? 0.6 : 1, display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <Send size={13} /> {sending ? "Enviando..." : "Enviar"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Modal de Agendamento — cria uma bolha de serviço com data, hora, motivo,
// descrição e cliente Atlaz (autocomplete por nome/CPF/telefone).
function ScheduleModal({ phone, conv, onClose, onSaved }) {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [time, setTime] = useState("09:00");
  const [reason, setReason] = useState("");
  const [description, setDescription] = useState("");
  const [clientName, setClientName] = useState(conv?.subscriber_name || conv?.profile_name || "");
  const [clientResults, setClientResults] = useState([]);
  const [clientPicked, setClientPicked] = useState(null);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  // Tenta auto-detectar pelo telefone na primeira renderização
  useEffect(() => {
    if (!phone || clientPicked) return;
    (async () => {
      try {
        const r = await api.subscribersByPhone?.(phone);
        if (r?.subscriber) {
          setClientPicked(r.subscriber);
          setClientName(r.subscriber.name);
        }
      } catch { /* ignore */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phone]);

  const searchClient = async (q) => {
    setClientName(q);
    setClientPicked(null);
    if (q.length < 3) { setClientResults([]); return; }
    setSearching(true);
    try {
      const r = await api.subscribersSearch?.(q);
      setClientResults(r?.items || []);
    } catch { setClientResults([]); }
    finally { setSearching(false); }
  };

  const save = async () => {
    if (!date || !time) { setErr("Data e hora são obrigatórias."); return; }
    if (!reason.trim()) { setErr("Informe o motivo do agendamento."); return; }
    setSaving(true); setErr("");
    try {
      await api.scheduleCreate?.({
        phone,
        date,
        time,
        reason: reason.trim(),
        description: description.trim(),
        subscriber_id: clientPicked?.id,
        subscriber_name: clientPicked?.name || clientName.trim() || "Não identificado",
        subscriber_document: clientPicked?.document,
      });
      if (onSaved) await onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao salvar.");
    } finally { setSaving(false); }
  };

  return (
    <div onClick={onClose} data-testid="schedule-modal" style={{
      position: "fixed", inset: 0, background: "rgba(2,6,23,.55)",
      display: "grid", placeItems: "center", zIndex: 1000, padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 14, width: "100%", maxWidth: 560,
        padding: 22, border: "1px solid #e2e8f0",
        boxShadow: "0 20px 60px rgba(2,6,23,.25)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: "#ede9fe", color: "#6d28d9",
            display: "grid", placeItems: "center",
            border: "1px solid #ddd6fe",
          }}><CalendarPlus size={18} /></div>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0f172a" }}>
              Novo agendamento
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: 11, color: "#64748b" }}>
              Cria uma bolha de serviço com data, hora, motivo e cliente Atlaz.
            </p>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
          <div>
            <label style={schLabel}>Data</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                    data-testid="schedule-date" style={schInput} />
          </div>
          <div>
            <label style={schLabel}>Hora</label>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)}
                    data-testid="schedule-time" style={schInput} />
          </div>
        </div>

        <div style={{ marginBottom: 10, position: "relative" }}>
          <label style={schLabel}>Cliente (Atlaz)</label>
          <input
            value={clientName}
            onChange={(e) => searchClient(e.target.value)}
            placeholder="Buscar por nome, CPF ou telefone..."
            data-testid="schedule-client-search"
            style={schInput}
          />
          {clientPicked && (
            <div style={{ marginTop: 6, padding: "6px 10px", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 6, fontSize: 11, color: "#166534" }}>
              ✓ Vinculado: <strong>{clientPicked.name}</strong> · {clientPicked.document || "—"}
            </div>
          )}
          {clientResults.length > 0 && !clientPicked && (
            <div style={{
              position: "absolute", top: "100%", left: 0, right: 0,
              background: "white", border: "1px solid #e2e8f0", borderRadius: 8,
              marginTop: 4, maxHeight: 180, overflowY: "auto", zIndex: 10,
              boxShadow: "0 8px 24px rgba(0,0,0,.08)",
            }}>
              {clientResults.slice(0, 8).map((c) => (
                <button key={c.id}
                         onClick={() => { setClientPicked(c); setClientName(c.name); setClientResults([]); }}
                         data-testid={`schedule-client-pick-${c.id}`}
                         style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 12px", border: 0, borderBottom: "1px solid #f1f5f9", background: "transparent", cursor: "pointer", fontSize: 12, color: "#0f172a" }}>
                  <strong>{c.name}</strong> <span style={{ color: "#94a3b8" }}>· {c.document || "—"}</span>
                </button>
              ))}
            </div>
          )}
          {searching && <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>buscando...</div>}
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={schLabel}>Motivo do agendamento</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Ex.: Instalação fibra, troca de equipamento, visita técnica"
            data-testid="schedule-reason"
            style={schInput}
          />
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={schLabel}>Descrição (opcional)</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Detalhes adicionais — endereço, observações, contato secundário..."
            data-testid="schedule-description"
            style={{ ...schInput, resize: "vertical", fontFamily: "inherit" }}
          />
        </div>

        {err && <div style={{ background: "#fef2f2", color: "#991b1b", padding: "8px 12px", borderRadius: 8, fontSize: 12, marginBottom: 10, border: "1px solid #fecaca" }}>{err}</div>}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} disabled={saving}
                   style={{ padding: "8px 14px", border: "1px solid #e2e8f0", borderRadius: 8, background: "white", color: "#475569", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
            Cancelar
          </button>
          <button
            onClick={save}
            disabled={saving || !reason.trim()}
            data-testid="schedule-save"
            style={{ padding: "8px 16px", border: 0, borderRadius: 8, background: "#0f172a", color: "white", fontWeight: 700, fontSize: 13, cursor: "pointer", opacity: saving ? 0.6 : 1, display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <CalendarPlus size={13} /> {saving ? "Salvando..." : "Criar agendamento"}
          </button>
        </div>
      </div>
    </div>
  );
}

const schLabel = { fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5, display: "block", marginBottom: 4 };
const schInput = { width: "100%", padding: "8px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, color: "#0f172a", boxSizing: "border-box" };

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
   CustomerProfileModal — perfil profissional do cliente
   Mostra: endereço completo, OLT/porta/VLAN/SN/sinal, status ONT,
   PPPoE, fabricante, histórico de chamados (90d), botão criar chamado
============================================================= */
function CustomerProfileModal({ phone, profile, onClose }) {
  const sub = profile?.subscriber;
  const addr = profile?.address;
  const signal = profile?.olt_signal;
  const tickets90 = profile?.tickets_90d || [];
  const ticketsCount = profile?.tickets_count_90d || 0;
  const ticketsOpen = profile?.tickets_open || 0;
  const avatarSrc = profile?.avatar || profile?.whatsapp?.avatar;
  const rx = signal?.signal_1490 ?? signal?.signal_1310 ?? signal?.rx_signal_dbm ?? signal?.rx;
  const tx = signal?.signal_1310 ?? signal?.tx_signal_dbm ?? signal?.tx;
  const ontStatus = signal?.status || signal?.ont_status;
  const isOntOnline = String(ontStatus || "").toLowerCase().includes("online");
  const [creatingTicket, setCreatingTicket] = useState(false);
  const [rebootingOnt, setRebootingOnt] = useState(false);
  const ontExtId = signal?.unique_external_id;

  const rxColor = (v) => {
    if (v == null) return "var(--text-muted)";
    const n = Number(v);
    if (Number.isNaN(n)) return "var(--text-muted)";
    if (n >= -25) return "#16a34a";
    if (n >= -27) return "#eab308";
    return "#dc2626";
  };

  const fullAddress = addr ? [
    [addr.street, addr.number].filter(Boolean).join(", "),
    addr.complement,
    addr.district,
    [addr.city, addr.state].filter(Boolean).join(" / "),
    addr.zip_code ? `CEP ${addr.zip_code}` : null,
  ].filter(Boolean).join(" · ") : (sub?.address || null);

  const onRebootOnt = async () => {
    if (!ontExtId) return;
    if (!window.confirm(
      "Reiniciar a ONT do cliente?\n\nA conexão vai cair por ~30s e voltar automaticamente.",
    )) return;
    setRebootingOnt(true);
    try {
      await api.smartoltOnuReboot(ontExtId);
      alert("ONT reiniciada. A conexão volta em ~30 segundos.");
    } catch (e) {
      alert("Falha ao reiniciar: " + (e?.response?.data?.detail || e.message));
    } finally {
      setRebootingOnt(false);
    }
  };

  const onCreateTicket = async () => {
    if (!sub) {
      alert("Vincule este cliente a um cadastro antes de criar chamado.");
      return;
    }
    setCreatingTicket(true);
    try {
      // Busca colaboradores ativos e abre prompt simples pra escolha
      const cols = await api.listCollaborators();
      const techs = (cols.items || cols || [])
        .filter((c) => c.active !== false && !c.atlaz_inbox);
      if (!techs.length) {
        alert("Nenhum técnico ativo disponível.");
        return;
      }
      const opts = techs.map((t, i) => `${i + 1}. ${t.name}`).join("\n");
      const pick = window.prompt(
        `Atribuir chamado a:\n\n${opts}\n\nDigite o número:`,
        "1",
      );
      const idx = parseInt(pick, 10) - 1;
      if (isNaN(idx) || idx < 0 || idx >= techs.length) return;
      const tech = techs[idx];
      const relato = window.prompt(
        "Descreva o problema (opcional):",
        `Cliente ${sub.name} via WhatsApp — solicitação de visita técnica.`,
      );
      if (relato === null) return;
      const payload = {
        client_name: sub.name,
        address: fullAddress || "Endereço não cadastrado",
        neighborhood: addr?.district || "",
        phone: phone,
        relato: relato || "",
        pppoe_user: sub.pppoe_user || "",
        type: "reparo",
        priority: "normal",
        assigned_collaborator_id: tech.id,
      };
      const t = await api.lousaCreateTicket(payload);
      alert(`Chamado criado: ${t.id?.slice(-8) || ""} → ${tech.name}`);
    } catch (e) {
      alert("Erro ao criar chamado: " + (e?.response?.data?.detail || e.message));
    } finally {
      setCreatingTicket(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.6)",
      display: "grid", placeItems: "center", zIndex: 1100,
      padding: 16,
    }} data-testid="wa-customer-modal">
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg-surface)",
        padding: 0, borderRadius: 14, width: "min(720px, 100%)",
        maxHeight: "88vh", overflow: "auto",
        boxShadow: "0 20px 50px rgba(0,0,0,.4)",
        border: "1px solid var(--border-default)",
      }}>
        {/* Header — sóbrio, sem gradiente */}
        <div style={{
          padding: "18px 20px",
          borderBottom: "1px solid var(--border-default)",
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <Avatar name={sub?.name || `+${phone}`} src={avatarSrc} size={48} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <strong style={{ fontSize: 16, fontWeight: 600,
                                 color: "var(--text-primary)", letterSpacing: "-0.015em" }}>
                {sub?.name || "Cliente não identificado"}
              </strong>
              {sub && (
                <StatusPill status={sub.status} />
              )}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 3,
                           display: "flex", alignItems: "center", gap: 12,
                           fontFamily: "ui-monospace, monospace" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <Phone size={11} /> +{phone}
              </span>
              {sub?.external_code && (
                <span>{sub.external_code}</span>
              )}
            </div>
          </div>
          <button onClick={onClose}
                  data-testid="wa-customer-close"
                  style={{
                    width: 30, height: 30, borderRadius: 6,
                    border: "1px solid var(--border-default)",
                    background: "transparent", cursor: "pointer",
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    color: "var(--text-muted)",
                  }}>
            <X size={14} />
          </button>
        </div>

        {/* No-link warning */}
        {!sub && (
          <div style={{
            margin: "16px 20px 0",
            padding: 12, borderRadius: 8,
            background: "rgba(245,158,11,.08)",
            border: "1px solid rgba(245,158,11,.30)",
            fontSize: 12,
            display: "flex", gap: 10, alignItems: "flex-start",
          }}>
            <AlertCircle size={14} strokeWidth={2} style={{ color: "#f59e0b", marginTop: 1, flexShrink: 0 }} />
            <div>
              <strong>Telefone não vinculado a nenhum cadastro.</strong>
              <div style={{ color: "var(--text-muted)", marginTop: 3 }}>
                Cadastre em Assinantes para que a IA carregue automaticamente os dados.
              </div>
            </div>
          </div>
        )}

        {/* Body — grid de seções */}
        <div style={{ padding: 20, display: "grid", gap: 16 }}>
          {/* Quick stats (3 cards) */}
          {sub && (
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
              gap: 8,
            }}>
              <StatCard label="Conexão" value={
                signal ? (isOntOnline ? "Online" : "Offline") : "—"
              } color={signal ? (isOntOnline ? "#16a34a" : "#dc2626") : "var(--text-muted)"} />
              <StatCard label="Chamados (90d)"
                        value={String(ticketsCount)}
                        color={ticketsCount >= 3 ? "#dc2626" : "var(--text-primary)"}
                        sub={ticketsOpen > 0 ? `${ticketsOpen} aberto(s)` : null} />
              <StatCard label="Sinal RX"
                        value={rx != null ? `${rx} dBm` : "—"}
                        color={rxColor(rx)} />
            </div>
          )}

          {/* Sessão: Plano + Filial + Cobrança */}
          {sub && (
            <Section title="Contrato">
              <FieldRow label="Plano" value={sub.plan_name} />
              <FieldRow label="Filial" value={sub.branch} />
              <FieldRow label="Vencimento" value={sub.due_day ? `Dia ${sub.due_day}` : null} />
              <FieldRow label="Débitos"
                          value={sub.debit_total != null
                            ? new Intl.NumberFormat("pt-BR",
                                { style: "currency", currency: "BRL" }).format(sub.debit_total)
                            : sub.debits}
                          valueColor={(sub.debit_total || 0) > 0 ? "#dc2626" : "var(--text-primary)"} />
            </Section>
          )}

          {/* Sessão: Endereço */}
          {fullAddress && (
            <Section title="Endereço" icon={MapPin}>
              <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.6 }}>
                {fullAddress}
              </div>
            </Section>
          )}

          {/* Sessão: Rede / SmartOLT */}
          <Section title="Rede & SmartOLT" icon={Signal}>
            <FieldRow label="PPPoE"
                        value={sub?.pppoe_user}
                        mono />
            <FieldRow label="OLT" value={signal?.olt_name} />
            <FieldRow label="Placa / Porta"
                        value={signal && (signal.board || signal.port)
                          ? `${signal.board || "?"} / ${signal.port || "?"}${signal.onu ? " · ONU " + signal.onu : ""}`
                          : null} />
            <FieldRow label="VLAN" value={signal?.vlan || sub?.metadata?.vlan} />
            <FieldRow label="Serial (SN)" value={signal?.sn} mono />
            <FieldRow label="Fabricante / Modelo"
                        value={signal?.onu_type_name || sub?.equipment} />
            <FieldRow label="Sinal RX" value={rx != null ? `${rx} dBm` : null}
                        valueColor={rxColor(rx)} mono />
            {tx != null && (
              <FieldRow label="Sinal TX" value={`${tx} dBm`} mono />
            )}
            <FieldRow label="Status ONT"
                        value={ontStatus}
                        valueColor={isOntOnline ? "#16a34a" : "#dc2626"} />
            {!signal && sub?.pppoe_user && (
              <div style={{ fontSize: 11, color: "var(--text-muted)", padding: "4px 0" }}>
                Aguardando dados da SmartOLT (sincronização periódica).
              </div>
            )}
            {!signal && !sub?.pppoe_user && (
              <div style={{ fontSize: 11, color: "var(--text-muted)", padding: "4px 0" }}>
                Sem PPPoE cadastrado — não foi possível buscar sinal.
              </div>
            )}
          </Section>

          {/* Sessão: Histórico de chamados (últimos 90 dias) */}
          <Section title="Histórico de chamados · 90 dias" icon={Activity}>
            {tickets90.length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                Nenhum chamado nos últimos 90 dias.
              </div>
            ) : (
              <div style={{ display: "grid", gap: 6, maxHeight: 220, overflowY: "auto" }}>
                {tickets90.map((t) => (
                  <TicketHistRow key={t.id} ticket={t} />
                ))}
              </div>
            )}
          </Section>

          {/* Action: reiniciar ONT + criar chamado */}
          <div style={{
            display: "flex", gap: 8, justifyContent: "flex-end",
            paddingTop: 4, flexWrap: "wrap",
          }}>
            <button onClick={onClose}
                    data-testid="wa-customer-cancel"
                    style={{
                      padding: "8px 14px", borderRadius: 6,
                      border: "1px solid var(--border-default)",
                      background: "transparent", color: "var(--text-secondary)",
                      fontSize: 12, fontWeight: 600, cursor: "pointer",
                    }}>
              Fechar
            </button>
            <button onClick={onRebootOnt}
                    disabled={rebootingOnt || !ontExtId}
                    data-testid="wa-customer-reboot-ont"
                    title={!ontExtId
                      ? "ONT não localizada na SmartOLT"
                      : "Reinicia a ONT do cliente via SmartOLT (~30s)"}
                    style={{
                      padding: "8px 14px", borderRadius: 6,
                      border: "1px solid #d97706",
                      background: "transparent",
                      color: "#d97706",
                      fontSize: 12, fontWeight: 600,
                      cursor: (rebootingOnt || !ontExtId) ? "not-allowed" : "pointer",
                      opacity: (rebootingOnt || !ontExtId) ? 0.5 : 1,
                      display: "inline-flex", alignItems: "center", gap: 6,
                    }}>
              <RefreshCw size={13} strokeWidth={2}
                          style={{ animation: rebootingOnt ? "wa-spin 1s linear infinite" : "none" }} />
              {rebootingOnt ? "Reiniciando..." : "Reiniciar ONT"}
            </button>
            <button onClick={onCreateTicket}
                    disabled={creatingTicket || !sub}
                    data-testid="wa-customer-create-ticket"
                    title={!sub ? "Cliente precisa estar cadastrado" : "Criar chamado na Lousa"}
                    style={{
                      padding: "8px 14px", borderRadius: 6,
                      border: "1px solid var(--text-primary)",
                      background: "var(--text-primary)",
                      color: "var(--bg-surface)",
                      fontSize: 12, fontWeight: 600,
                      cursor: (creatingTicket || !sub) ? "not-allowed" : "pointer",
                      opacity: (creatingTicket || !sub) ? 0.5 : 1,
                      display: "inline-flex", alignItems: "center", gap: 6,
                    }}>
              <ClipboardList size={13} strokeWidth={2} />
              {creatingTicket ? "Criando..." : "Criar chamado"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---- helper sub-components ---- */
function StatusPill({ status }) {
  const s = String(status || "").toLowerCase();
  const isActive = s === "ativo";
  const isBlocked = s === "bloqueado";
  return (
    <span style={{
      fontSize: 10, fontWeight: 700,
      padding: "2px 8px", borderRadius: 4,
      background: isActive ? "rgba(34,197,94,.15)"
        : isBlocked ? "rgba(220,38,38,.15)"
        : "rgba(148,163,184,.15)",
      color: isActive ? "#16a34a"
        : isBlocked ? "#dc2626"
        : "#64748b",
      textTransform: "uppercase", letterSpacing: 0.5,
    }}>{status || "—"}</span>
  );
}

function StatCard({ label, value, color, sub }) {
  return (
    <div style={{
      padding: "10px 12px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface-2)",
    }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                     fontWeight: 600, textTransform: "uppercase",
                     letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, marginTop: 4,
                     color: color || "var(--text-primary)",
                     letterSpacing: "-0.01em" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function Section({ title, icon: Ico, children }) {
  return (
    <div>
      <div style={{
        fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.6,
        display: "flex", alignItems: "center", gap: 6,
        marginBottom: 8,
        paddingBottom: 6,
        borderBottom: "1px solid var(--border-default)",
      }}>
        {Ico && <Ico size={11} strokeWidth={2} />}
        {title}
      </div>
      <div style={{ display: "grid", gap: 4 }}>{children}</div>
    </div>
  );
}

function FieldRow({ label, value, mono, valueColor }) {
  if (value == null || value === "") return null;
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "140px 1fr", gap: 12,
      fontSize: 12, padding: "3px 0", alignItems: "baseline",
    }}>
      <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>{label}</span>
      <span style={{
        color: valueColor || "var(--text-primary)",
        fontWeight: valueColor && valueColor !== "var(--text-primary)" ? 600 : 500,
        fontFamily: mono ? "ui-monospace, monospace" : "inherit",
        wordBreak: "break-word",
      }}>{value}</span>
    </div>
  );
}

function TicketHistRow({ ticket }) {
  const d = ticket.created_at
    ? new Date(ticket.created_at).toLocaleDateString("pt-BR",
        { day: "2-digit", month: "2-digit", year: "2-digit" })
    : "—";
  const isOpen = ["pendente", "aberta", "aguardando_atendimento"].includes(ticket.status);
  const closed = ticket.closed_at;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 10px", borderRadius: 6,
      background: "var(--bg-surface-2)",
      border: "1px solid var(--border-default)",
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: isOpen ? "#f59e0b" : closed ? "#16a34a" : "#94a3b8",
        flexShrink: 0,
      }} />
      <span style={{ fontSize: 11, color: "var(--text-muted)",
                       fontFamily: "ui-monospace, monospace",
                       width: 64, flexShrink: 0 }}>{d}</span>
      <span style={{ fontSize: 11, fontWeight: 600,
                       color: "var(--text-primary)",
                       textTransform: "uppercase",
                       letterSpacing: 0.3,
                       width: 80, flexShrink: 0 }}>
        {ticket.type || "—"}
      </span>
      <span style={{ flex: 1, fontSize: 12, color: "var(--text-secondary)",
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
        {ticket.client_snapshot?.relato || ticket.outcome || "—"}
      </span>
      <span style={{
        fontSize: 10, fontWeight: 700,
        padding: "2px 7px", borderRadius: 4,
        background: isOpen ? "rgba(245,158,11,.15)" : "rgba(148,163,184,.15)",
        color: isOpen ? "#d97706" : "#64748b",
        textTransform: "uppercase", letterSpacing: 0.4,
        flexShrink: 0,
      }}>{ticket.status || "?"}</span>
    </div>
  );
}


/* ============================================================= */
/* AttendantKpiStrip — drill-down inverso: mostra KPIs do atendente
   humano que está respondendo a conversa atual (puxados do Central IA). */
function _kpiCsatColor(v) {
  if (v == null) return "var(--text-muted)";
  if (v >= 4.5) return "#16a34a";
  if (v >= 3.5) return "#ca8a04";
  return "#dc2626";
}
function _kpiFmtSecs(s) {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return s < 3600 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h${m % 60}m`;
}

function AttendantKpiStrip({ kpi }) {
  if (!kpi) return null;
  const items = [
    { label: "CSAT", value: kpi.csat_avg ?? "—", color: _kpiCsatColor(kpi.csat_avg) },
    { label: "Volume 7d", value: kpi.volume ?? 0, color: "var(--text-primary)" },
    { label: "FCR", value: kpi.fcr_rate != null ? `${kpi.fcr_rate}%` : "—", color: "var(--text-primary)" },
    { label: "FRT médio", value: _kpiFmtSecs(kpi.frt_avg_seconds), color: "var(--text-primary)" },
    { label: "Sent. neg.", value: kpi.negative_count ?? 0, color: kpi.negative_count > 0 ? "#dc2626" : "var(--text-primary)" },
  ];
  return (
    <div data-testid="attendant-kpi-strip" style={{
      display: "flex", alignItems: "center", gap: 14,
      padding: "8px 18px",
      background: "var(--bg-surface)",
      borderBottom: "1px solid var(--border-default)",
      fontSize: 11, overflowX: "auto", whiteSpace: "nowrap",
    }}>
      <span style={{
        fontSize: 9.5, fontWeight: 800, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.5, flexShrink: 0,
      }}>
        KPIs · {kpi.name} <span style={{ opacity: 0.6 }}>(últimos 7 dias)</span>
      </span>
      {items.map((it) => (
        <div key={it.label} style={{ display: "flex", flexDirection: "column", flexShrink: 0 }}>
          <span style={{
            fontSize: 9, color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: 0.4,
          }}>{it.label}</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: it.color }}>{it.value}</span>
        </div>
      ))}
    </div>
  );
}



/* =============================================================
   LidLinkButton — vincula um jid@lid (anônimo) ao telefone real.
   Aparece no header da conversa quando phone_is_lid=true.
============================================================= */
function LidLinkButton({ conv, onLinked }) {
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e) {
    e?.preventDefault();
    setErr("");
    const clean = (phone || "").replace(/\D/g, "");
    if (clean.length < 10) {
      setErr("Telefone inválido — informe DDI + DDD + número (ex: 5521998176526).");
      return;
    }
    setBusy(true);
    try {
      const r = await api.waBaileysLidLink(conv.lid || conv.phone, clean);
      setOpen(false);
      setPhone("");
      // Notifica o pai (reload) e tenta abrir a conv nova (telefone real)
      onLinked?.(r?.phone);
    } catch (e) {
      setErr(extractErrorFromAxios(e));
    } finally { setBusy(false); }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="wa-thread-lid-link-btn"
        title="Informe o telefone real do cliente. As mensagens serão migradas e o cliente vinculado."
        style={{
          padding: "1px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800,
          border: "1px solid #f59e0b", background: "#f59e0b", color: "white",
          cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 3,
        }}>
        <Lightbulb size={9} strokeWidth={2.5} /> Vincular telefone
      </button>
      {open && (
        <div onClick={() => !busy && setOpen(false)}
             style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.55)",
                        display: "grid", placeItems: "center", zIndex: 9999 }}>
          <form onSubmit={submit} onClick={(e) => e.stopPropagation()}
                 data-testid="wa-lid-link-modal"
                 style={{ background: "var(--bg-surface)", borderRadius: 14,
                           padding: 22, width: "min(480px, 92vw)",
                           boxShadow: "0 20px 60px rgba(0,0,0,.35)" }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 800 }}>
              Vincular LID a telefone real
            </h3>
            <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.55 }}>
              Este cliente está usando a privacidade do WhatsApp <strong>(LID)</strong> e o
              número real está oculto. Informe o telefone correto e o sistema vai:
            </p>
            <ul style={{ margin: "0 0 14px", paddingLeft: 20, fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.6 }}>
              <li>Migrar todas as mensagens deste LID para o telefone real</li>
              <li>Tentar vincular automaticamente a um assinante existente</li>
              <li>Lembrar do mapping nas próximas mensagens deste mesmo LID</li>
            </ul>

            <div style={{ padding: 10, background: "var(--bg-surface-2)", borderRadius: 8,
                            fontSize: 12, marginBottom: 12 }}>
              <strong>LID atual:</strong> <span className="mono">{conv.lid || conv.phone}</span>
            </div>

            <label style={{ display: "block", fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
              Telefone real (DDI + DDD + número)
            </label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              autoFocus
              placeholder="5521998176526"
              data-testid="wa-lid-link-input"
              disabled={busy}
              style={{
                width: "100%", padding: "9px 12px",
                border: "1px solid var(--border-default)", borderRadius: 8,
                fontSize: 14, fontFamily: "ui-monospace, monospace",
                background: "var(--bg-surface)", color: "var(--text-primary)",
                marginBottom: 12,
              }}
            />

            {err && (
              <div style={{ background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
                              padding: 8, borderRadius: 8, fontSize: 12, marginBottom: 10 }}>
                {err}
              </div>
            )}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button type="button" onClick={() => setOpen(false)} disabled={busy}
                       style={{ padding: "8px 14px", borderRadius: 8,
                                  border: "1px solid var(--border-default)",
                                  background: "var(--bg-surface)", color: "var(--text-secondary)",
                                  fontSize: 12, fontWeight: 700, cursor: busy ? "wait" : "pointer" }}>
                Cancelar
              </button>
              <button type="submit" disabled={busy} data-testid="wa-lid-link-submit"
                       style={{ padding: "8px 14px", borderRadius: 8,
                                  border: "1px solid #f59e0b", background: "#f59e0b", color: "white",
                                  fontSize: 12, fontWeight: 800, cursor: busy ? "wait" : "pointer" }}>
                {busy ? "Migrando..." : "Vincular e migrar"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}



/* extractErrorFromAxios — converte qualquer formato de erro (string,
   422 Pydantic array, objeto) numa string segura para JSX. */
function extractErrorFromAxios(e) {
  const d = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (!d) return "Erro desconhecido.";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((x) => {
      if (typeof x === "string") return x;
      const loc = Array.isArray(x?.loc) ? x.loc.filter((y) => y !== "body").join(".") : "";
      const msg = x?.msg || x?.message || JSON.stringify(x);
      return loc ? `${loc}: ${msg}` : msg;
    }).filter(Boolean).join(" · ");
  }
  if (typeof d === "object") {
    return d.msg || d.message || d.error || d.detail || JSON.stringify(d);
  }
  return String(d);
}
