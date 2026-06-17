import React, { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Star, StarOff, LogOut, Pencil, Check, X, QrCode, Settings, Activity, AlertTriangle, ArrowRightLeft } from "lucide-react";
import { api } from "@/api";

/* =============================================================
   Painel de Canais WhatsApp (multi-número).

   Mostra os 4 slots de canais, com:
   - Nome customizável (clique no lápis)
   - Status live (connecting/connected/disconnected)
   - Número conectado (telefone do "me")
   - Botão "Conectar via QR" → abre modal com QR PNG
   - Botão "Desconectar"
   - Radio "Padrão para envios" (default outbound)

   Todos os agentes IA (Isabella/Alvaro/Pâmela) respondem em qualquer canal —
   o channel_name aparece como badge nas conversas pra identificar de qual
   número veio a mensagem.
============================================================= */

const STATE_VISUAL = {
  connected:    { color: "#16a34a", bg: "#dcfce7", border: "#86efac", label: "Conectado" },
  connecting:   { color: "#ca8a04", bg: "#fef9c3", border: "#fde047", label: "Conectando…" },
  disconnected: { color: "#dc2626", bg: "#fee2e2", border: "#fca5a5", label: "Desconectado" },
  unreachable:  { color: "#64748b", bg: "#f1f5f9", border: "#cbd5e1", label: "Sidecar fora" },
  banned:       { color: "#7f1d1d", bg: "#fee2e2", border: "#fca5a5", label: "Banido" },
};

function StateBadge({ state, connected }) {
  const key = state === "connected" || connected ? "connected"
    : state === "connecting" ? "connecting"
    : state === "unreachable" ? "unreachable"
    : state === "banned" ? "banned"
    : "disconnected";
  const v = STATE_VISUAL[key];
  return (
    <span
      data-testid={`channel-state-${key}`}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "3px 10px", borderRadius: 999,
        background: v.bg, color: v.color, border: `1px solid ${v.border}`,
        fontSize: 12, fontWeight: 600,
      }}
    >
      <span style={{
        width: 7, height: 7, borderRadius: "50%", background: v.color,
        animation: key === "connecting" ? "pulse 1.4s ease-in-out infinite" : "none",
      }} />
      {v.label}
    </span>
  );
}

function ChannelCard({ ch, onRename, onSetDefault, onConnect, onLogout, onConfigProvider, onQuickMigrate, onRefresh, busy }) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(ch.channel_name || "");
  const connected = ch.live_connected || ch.live_state === "connected";
  // QR aparece automaticamente quando o canal está desconectado/conectando.
  // O usuário pode fechar manualmente; reabre se o canal cair de novo.
  const [qrOpen, setQrOpen] = useState(!connected);
  const provider = ch.provider || "baileys";
  const providerLabel = provider === "evolution" ? "Evolution API" : "Baileys (interno)";
  const providerColor = provider === "evolution" ? "#7c3aed" : "#0ea5e9";

  useEffect(() => { setDraftName(ch.channel_name || ""); }, [ch.channel_name]);
  // Sincroniza qrOpen com o estado real do canal: abre se desconectar, fecha se conectar
  useEffect(() => { setQrOpen(!connected); }, [connected]);

  const submitRename = async () => {
    const trimmed = draftName.trim();
    if (!trimmed || trimmed === ch.channel_name) { setEditing(false); return; }
    await onRename(ch.id, trimmed);
    setEditing(false);
  };

  return (
    <div
      data-testid={`channel-card-${ch.id}`}
      style={{
        background: "white",
        border: ch.is_default_outbound ? "2px solid #0d9488" : "1px solid var(--border)",
        borderRadius: 14,
        padding: 18,
        boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
        position: "relative",
      }}
    >
      {ch.is_default_outbound && (
        <span style={{
          position: "absolute", top: -10, right: 14,
          background: "#0d9488", color: "white", fontSize: 10,
          padding: "3px 10px", borderRadius: 999, fontWeight: 700,
          letterSpacing: 0.5,
        }} data-testid={`channel-default-badge-${ch.id}`}>
          PADRÃO OUTBOUND
        </span>
      )}

      {/* Header: nome + ações de rename */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        {editing ? (
          <>
            <input
              autoFocus
              data-testid={`channel-name-input-${ch.id}`}
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitRename();
                if (e.key === "Escape") { setEditing(false); setDraftName(ch.channel_name); }
              }}
              maxLength={40}
              style={{
                flex: 1, padding: "6px 10px", border: "1px solid #cbd5e1",
                borderRadius: 8, fontSize: 16, fontWeight: 700,
              }}
            />
            <button
              data-testid={`channel-name-save-${ch.id}`}
              onClick={submitRename}
              style={{ padding: 6, background: "#0d9488", color: "white",
                        border: "none", borderRadius: 8, cursor: "pointer" }}
            ><Check size={16}/></button>
            <button
              data-testid={`channel-name-cancel-${ch.id}`}
              onClick={() => { setEditing(false); setDraftName(ch.channel_name); }}
              style={{ padding: 6, background: "#e2e8f0", color: "#475569",
                        border: "none", borderRadius: 8, cursor: "pointer" }}
            ><X size={16}/></button>
          </>
        ) : (
          <>
            <h3 style={{ flex: 1, margin: 0, fontSize: 17, fontWeight: 700, color: "#0f172a" }}
                data-testid={`channel-name-${ch.id}`}>
              {ch.channel_name}
            </h3>
            <button
              data-testid={`channel-name-edit-${ch.id}`}
              onClick={() => setEditing(true)}
              title="Renomear canal"
              style={{ padding: 4, background: "none", border: "none",
                        color: "#64748b", cursor: "pointer" }}
            ><Pencil size={14}/></button>
          </>
        )}
      </div>

      {/* Status + phone + provider */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <StateBadge state={ch.live_state} connected={connected} />
        {ch.phone_number && (
          <span style={{ fontSize: 13, color: "#475569", fontFamily: "JetBrains Mono, monospace" }}
                data-testid={`channel-phone-${ch.id}`}>
            +{ch.phone_number}
          </span>
        )}
        {!ch.phone_number && !connected && (
          <span style={{ fontSize: 12, color: "#94a3b8", fontStyle: "italic" }}>
            sem número
          </span>
        )}
        <span
          data-testid={`channel-provider-badge-${ch.id}`}
          style={{
            marginLeft: "auto",
            padding: "3px 10px",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 0.4,
            color: providerColor,
            background: `${providerColor}15`,
            border: `1px solid ${providerColor}55`,
            borderRadius: 999,
            textTransform: "uppercase",
          }}
        >
          {providerLabel}
        </span>
      </div>

      {/* Ações */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {!connected && (
          <button
            data-testid={`channel-connect-btn-${ch.id}`}
            onClick={() => {
              setQrOpen((v) => !v);
              if (onConnect) onConnect(ch);
            }}
            disabled={busy}
            style={{
              padding: "8px 14px",
              background: qrOpen ? "#fef3c7" : "#0d9488",
              color: qrOpen ? "#92400e" : "white",
              border: qrOpen ? "1px solid #fde68a" : "none",
              borderRadius: 8, cursor: "pointer", fontWeight: 600,
              fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6,
            }}
          >
            <QrCode size={14}/> {qrOpen ? "Fechar QR" : "Conectar via QR"}
          </button>
        )}
        {connected && (
          <button
            data-testid={`channel-logout-btn-${ch.id}`}
            onClick={() => onLogout(ch)}
            disabled={busy}
            style={{
              padding: "8px 14px", background: "#fef2f2", color: "#b91c1c",
              border: "1px solid #fecaca", borderRadius: 8, cursor: "pointer",
              fontWeight: 600, fontSize: 13,
              display: "inline-flex", alignItems: "center", gap: 6,
            }}
          >
            <LogOut size={14}/> Desconectar
          </button>
        )}
        {!ch.is_default_outbound && (
          <button
            data-testid={`channel-set-default-btn-${ch.id}`}
            onClick={() => onSetDefault(ch.id)}
            disabled={busy}
            style={{
              padding: "8px 14px", background: "white", color: "#0f766e",
              border: "1px solid #99f6e4", borderRadius: 8, cursor: "pointer",
              fontWeight: 600, fontSize: 13,
              display: "inline-flex", alignItems: "center", gap: 6,
            }}
          >
            <Star size={14}/> Definir como padrão outbound
          </button>
        )}
        {ch.is_default_outbound && (
          <span style={{
            padding: "8px 14px", color: "#0f766e", fontSize: 12,
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <StarOff size={14}/> usado pra envios proativos
          </span>
        )}
        <button
          data-testid={`channel-provider-btn-${ch.id}`}
          onClick={() => onConfigProvider(ch)}
          disabled={busy}
          title="Escolher provedor: Baileys interno ou Evolution API"
          style={{
            padding: "8px 14px",
            background: "white",
            color: providerColor,
            border: `1px solid ${providerColor}55`,
            borderRadius: 8,
            cursor: "pointer",
            fontWeight: 600,
            fontSize: 13,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            marginLeft: "auto",
          }}
        >
          <Settings size={14}/> Provedor
        </button>
      </div>

      {/* QR inline — renderizado dentro do card (não modal) */}
      {qrOpen && !connected && (
        <InlineQRPanel
          channel={ch}
          onConnected={() => { setQrOpen(false); if (onRefresh) onRefresh(); }}
          onClose={() => setQrOpen(false)}
        />
      )}
    </div>
  );
}

function InlineQRPanel({ channel, onConnected, onClose }) {
  const [qr, setQr] = useState(null);
  const [status, setStatus] = useState("loading");
  const [err, setErr] = useState(null);
  const [resetting, setResetting] = useState(false);

  const tick = useCallback(async () => {
    try {
      const data = await api.waChannelQR(channel.id);
      setQr(data?.qr || null);
      setStatus(data?.status || "unknown");
      setErr(null);
      if (data?.status === "connected") {
        setTimeout(() => { if (onConnected) onConnected(); }, 1200);
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Falha ao buscar QR");
      setStatus("error");
    }
  }, [channel.id, onConnected]);

  const forceReset = useCallback(async () => {
    setResetting(true);
    try {
      await api.waChannelReload(channel.id);
      setQr(null);
      setStatus("reloading");
      // Espera o sidecar reabrir o socket antes do próximo tick
      setTimeout(() => { tick(); }, 1800);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Falha no reset");
    } finally {
      setResetting(false);
    }
  }, [channel.id, tick]);

  useEffect(() => {
    tick();
    const t = setInterval(tick, 4000);
    return () => clearInterval(t);
  }, [tick]);

  return (
    <div
      data-testid={`inline-qr-${channel.id}`}
      style={{
        marginTop: 14,
        padding: 16,
        background: "linear-gradient(180deg,#f8fafc 0%,#ffffff 100%)",
        border: "1px dashed #cbd5e1",
        borderRadius: 12,
        display: "flex",
        gap: 16,
        alignItems: "center",
      }}
    >
      <div style={{
        width: 200, height: 200, flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "white", borderRadius: 10, border: "1px solid #e2e8f0",
        overflow: "hidden",
      }}>
        {status === "connected" ? (
          <div data-testid={`inline-qr-connected-${channel.id}`}
                style={{ color: "#16a34a", fontWeight: 700, fontSize: 14, textAlign: "center" }}>
            ✓ Conectado!
          </div>
        ) : qr ? (
          <img
            src={qr}
            alt="QR Code"
            data-testid={`inline-qr-image-${channel.id}`}
            style={{ width: "100%", height: "100%", objectFit: "contain" }}
          />
        ) : err ? (
          <div style={{ padding: 12, color: "#dc2626", fontSize: 11, textAlign: "center" }}>
            {err}
          </div>
        ) : (
          <Loader2 className="animate-spin" size={28} color="#0d9488"/>
        )}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <QrCode size={14} color="#0d9488"/>
          <b style={{ fontSize: 13, color: "#0f172a" }}>Escaneie com o WhatsApp</b>
          <button
            data-testid={`inline-qr-close-${channel.id}`}
            onClick={onClose}
            title="Fechar"
            style={{
              marginLeft: "auto", padding: 4, background: "transparent",
              color: "#64748b", border: "none", cursor: "pointer",
            }}
          ><X size={14}/></button>
        </div>
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#475569", lineHeight: 1.6 }}>
          <li>Abra o <b>WhatsApp</b> no celular</li>
          <li>Toque em <b>Mais opções (⋮)</b> ou <b>Configurações</b></li>
          <li><b>Aparelhos conectados</b> → <b>Conectar um aparelho</b></li>
          <li>Aponte a câmera pro QR ao lado</li>
        </ol>
        <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            fontSize: 11, fontWeight: 700, color: "#0d9488",
            background: "#ccfbf1", padding: "3px 8px", borderRadius: 999,
          }} data-testid={`inline-qr-status-${channel.id}`}>
            {status}
          </span>
          <button
            data-testid={`inline-qr-refresh-${channel.id}`}
            onClick={tick}
            style={{
              padding: "5px 10px", background: "white", color: "#0d9488",
              border: "1px solid #99f6e4", borderRadius: 6, cursor: "pointer",
              fontSize: 11, fontWeight: 600,
              display: "inline-flex", alignItems: "center", gap: 4,
            }}
          ><RefreshCw size={11}/> Atualizar QR</button>
          <button
            data-testid={`inline-qr-reset-${channel.id}`}
            onClick={forceReset}
            disabled={resetting}
            title="Reabre o socket Baileys quando o QR para de renovar"
            style={{
              padding: "5px 10px", background: "#fef2f2", color: "#b91c1c",
              border: "1px solid #fecaca", borderRadius: 6,
              cursor: resetting ? "wait" : "pointer",
              fontSize: 11, fontWeight: 600,
              display: "inline-flex", alignItems: "center", gap: 4,
            }}
          ><AlertTriangle size={11}/> {resetting ? "Resetando…" : "Force Reset"}</button>
          <span style={{ fontSize: 10, color: "#94a3b8" }}>
            atualiza a cada 4s
          </span>
        </div>
      </div>
    </div>
  );
}

function QRModal({ channel, onClose }) {
  const [qr, setQr] = useState(null);
  const [status, setStatus] = useState("loading");
  const [err, setErr] = useState(null);

  const tick = useCallback(async () => {
    try {
      const data = await api.waChannelQR(channel.id);
      setQr(data?.qr || null);
      setStatus(data?.status || "unknown");
      setErr(null);
      if (data?.status === "connected") setTimeout(onClose, 1200);
    } catch (e) {
      setErr(e?.message || "Falha ao buscar QR");
      setStatus("error");
    }
  }, [channel.id, onClose]);

  useEffect(() => {
    tick();
    const t = setInterval(tick, 4000);
    return () => clearInterval(t);
  }, [tick]);

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
    }}>
      <div data-testid="qr-modal" style={{
        background: "white", borderRadius: 16, padding: 28,
        maxWidth: 420, width: "92%", textAlign: "center",
        boxShadow: "0 25px 50px rgba(0,0,0,0.25)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
            Conectar {channel.channel_name}
          </h3>
          <button data-testid="qr-modal-close" onClick={onClose}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}>
            <X size={20}/>
          </button>
        </div>
        <p style={{ fontSize: 13, color: "#64748b", marginBottom: 18 }}>
          Abra o WhatsApp no celular → Configurações → <b>Aparelhos conectados</b> → escaneie:
        </p>
        {status === "connected" ? (
          <div style={{ padding: 32, color: "#16a34a", fontWeight: 700 }} data-testid="qr-connected">
            ✓ Conectado!
          </div>
        ) : qr ? (
          <img src={qr} alt="QR Code" data-testid="qr-image"
                style={{ width: "100%", maxWidth: 320, margin: "0 auto", borderRadius: 12 }} />
        ) : err ? (
          <div style={{ padding: 32, color: "#dc2626", fontSize: 13 }}>{err}</div>
        ) : (
          <div style={{ padding: 32, display: "flex", justifyContent: "center" }}>
            <Loader2 className="animate-spin" size={36} color="#0d9488"/>
          </div>
        )}
        <p style={{ fontSize: 11, color: "#94a3b8", marginTop: 16 }}>
          Status: <b>{status}</b> · QR expira em ~60s, atualiza automaticamente.
        </p>
      </div>
    </div>
  );
}

function ProviderHealthCard({ channelId, onMigrate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const d = await api.waChannelProviderHealth(channelId, 7);
      setData(d);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Falha");
    } finally { setLoading(false); }
  }, [channelId]);

  useEffect(() => { load(); }, [load]);

  if (loading && !data) {
    return (
      <div data-testid={`provider-health-loading-${channelId}`}
            style={{ marginTop: 12, padding: 10, fontSize: 12, color: "#64748b" }}>
        <Loader2 size={12} className="animate-spin"/> Coletando telemetria…
      </div>
    );
  }
  if (err || !data) return null;

  const rec = data.recommendation || {};
  const severity = rec.severity || "low";
  const sevColor = severity === "high" ? "#dc2626"
                  : severity === "medium" ? "#ca8a04" : "#16a34a";
  const sevBg = severity === "high" ? "#fef2f2"
                : severity === "medium" ? "#fefce8" : "#f0fdf4";
  const sevBorder = severity === "high" ? "#fca5a5"
                    : severity === "medium" ? "#fde047" : "#86efac";
  const cur = data.current || {};
  const fmt = (v, suf = "") => (v === null || v === undefined) ? "—" : `${v}${suf}`;

  return (
    <div
      data-testid={`provider-health-card-${channelId}`}
      style={{
        marginTop: 14,
        background: sevBg,
        border: `1px solid ${sevBorder}`,
        borderRadius: 10,
        padding: 12,
      }}
    >
      {/* Header com recomendação */}
      <div
        onClick={() => setExpanded((s) => !s)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          cursor: "pointer", userSelect: "none",
        }}
      >
        {severity === "high" ? (
          <AlertTriangle size={16} color={sevColor}/>
        ) : (
          <Activity size={16} color={sevColor}/>
        )}
        <div style={{ flex: 1, fontSize: 12, fontWeight: 700, color: sevColor }}>
          {rec.action === "consider_migrate" ? "🔁 Considere migrar de provider"
            : rec.action === "configure_alt" ? "⚙️ Configure o provider alternativo"
            : "✅ Provider saudável"}
        </div>
        <span style={{ fontSize: 11, color: "#475569" }}>
          {expanded ? "▴ ocultar" : "▾ ver detalhes"}
        </span>
      </div>

      {/* Razão da recomendação */}
      <div style={{ fontSize: 11, color: "#475569", marginTop: 6, lineHeight: 1.55 }}>
        {rec.reason}
      </div>

      {expanded && (
        <div style={{ marginTop: 12, display: "grid",
                       gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
          <Metric label="Mensagens 7d" value={fmt(cur.total_sent)} />
          <Metric label="Taxa de sucesso" value={cur.success_rate !== null
            ? `${cur.success_rate}%` : "—"} />
          <Metric label="Latência p50" value={fmt(cur.latency_p50_ms, "ms")} />
          <Metric label="Latência p95" value={fmt(cur.latency_p95_ms, "ms")} />
          {data.current_provider === "baileys" && (
            <Metric label="Crashes sidecar 7d" value={fmt(cur.crash_count_7d)}
                     highlight={cur.crash_count_7d >= 2} />
          )}
          <Metric label="Conectado agora?" value={cur.connected_now ? "sim" : "não"}
                   highlight={!cur.connected_now} />
        </div>
      )}

      {/* Ação rápida */}
      {rec.action === "consider_migrate" && data.alternative?.configured && (
        <button
          data-testid={`provider-health-migrate-btn-${channelId}`}
          onClick={() => onMigrate(channelId, data.alternative_provider)}
          style={{
            marginTop: 12, padding: "8px 12px", width: "100%",
            background: sevColor, color: "white", border: "none",
            borderRadius: 6, fontWeight: 700, fontSize: 12,
            cursor: "pointer", display: "inline-flex",
            alignItems: "center", justifyContent: "center", gap: 6,
          }}
        >
          <ArrowRightLeft size={12}/>
          Migrar agora para {data.alternative_provider}
        </button>
      )}
      {rec.action === "configure_alt" && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#64748b", fontStyle: "italic" }}>
          {data.alternative?.note}
        </div>
      )}
    </div>
  );
}


function Metric({ label, value, highlight }) {
  return (
    <div style={{
      background: "white",
      border: `1px solid ${highlight ? "#fca5a5" : "#e2e8f0"}`,
      borderRadius: 8,
      padding: "8px 10px",
    }}>
      <div style={{ fontSize: 10, color: "#64748b",
                     textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 14, fontWeight: 700,
                     color: highlight ? "#b91c1c" : "#0f172a", marginTop: 2 }}>
        {value}
      </div>
    </div>
  );
}


function ProviderModal({ channel, onClose, onSaved }) {
  const initialProvider = channel?.provider || "baileys";
  const [provider, setProvider] = useState(initialProvider);
  const [evoUrl, setEvoUrl] = useState(channel?.evolution_url || "");
  const [evoKey, setEvoKey] = useState("");
  const [evoInstance, setEvoInstance] = useState(
    channel?.evolution_instance
    || channel?.evolution_instance_name
    || channel?.id
    || ""
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [usingServerKey, setUsingServerKey] = useState(false);
  const [defaultsErr, setDefaultsErr] = useState("");
  const [loadingDefaults, setLoadingDefaults] = useState(false);

  // Carrega defaults do servidor (URL + API key do .env). Sempre que o
  // usuário cair em provider=evolution. Sobrescreve campos vazios; mantém
  // o que o usuário já digitou. Falhas viram mensagem visível + botão
  // "Recarregar" pra retry — silenciar isso quebrou a UX no ambiente
  // do CEO (17/02/2026).
  const fetchDefaults = useCallback(async (force = false) => {
    setLoadingDefaults(true);
    setDefaultsErr("");
    try {
      const d = await api.waChannelEvolutionDefaults();
      if (d?.evolution_url && (force || !evoUrl)) setEvoUrl(d.evolution_url);
      if (d?.evolution_api_key && (force || !evoKey)) {
        setEvoKey(d.evolution_api_key);
        setUsingServerKey(true);
      }
      if (force || !evoInstance) {
        setEvoInstance(
          channel?.evolution_instance
          || channel?.evolution_instance_name
          || channel?.id
          || ""
        );
      }
      if (!d?.evolution_url && !d?.evolution_api_key) {
        setDefaultsErr(
          "O servidor não tem EVOLUTION_URL/EVOLUTION_API_KEY no .env — preencha manual."
        );
      }
    } catch (e) {
      setDefaultsErr(
        e?.response?.data?.detail
        || e?.message
        || "Falha ao buscar defaults do servidor. Sua sessão pode ter expirado."
      );
    } finally {
      setLoadingDefaults(false);
    }
  }, [channel, evoUrl, evoKey, evoInstance]);

  React.useEffect(() => {
    if (provider !== "evolution") return;
    fetchDefaults(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider]);

  const handleSave = async () => {
    setSaving(true); setErr("");
    try {
      const payload = { provider };
      if (provider === "evolution") {
        if (!evoUrl.trim() || !evoKey.trim() || !evoInstance.trim()) {
          throw new Error("Para Evolution preencha URL, API key e nome da instance.");
        }
        const inst = evoInstance.trim();
        // Evolution v2 não aceita nomes de instance com espaço ou maiúsculas:
        // bate em /instance/connectionState/<name> e devolve 404. Bloqueamos
        // no front pra falhar rápido em vez de salvar e quebrar depois.
        if (!/^[a-z0-9._-]+$/.test(inst)) {
          throw new Error(
            "Nome da instance inválido. Use só letras minúsculas, números, ponto, underscore ou hífen (sem espaços). Ex: 'smartprov'."
          );
        }
        payload.evolution_url = evoUrl.trim();
        payload.evolution_api_key = evoKey.trim();
        payload.evolution_instance_name = inst;
      }
      await api.waChannelSetProvider(channel.id, payload);
      onSaved();
      onClose();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Falha ao salvar provedor");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      data-testid="provider-modal"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white", borderRadius: 14, padding: 24, width: 520, maxWidth: "92vw",
          boxShadow: "0 20px 50px rgba(15,23,42,0.25)",
        }}
      >
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#0f172a" }}>
          Provedor WhatsApp — {channel?.channel_name}
        </h3>
        <p style={{ color: "#64748b", fontSize: 13, marginTop: 6 }}>
          Escolha como este canal envia/recebe mensagens. <b>Baileys</b> usa o sidecar interno (atual).
          <b> Evolution API</b> usa um container Evolution self-hosted (mais estável em produção).
        </p>

        <div style={{ display: "flex", gap: 10, marginTop: 18, marginBottom: 14 }}>
          {[
            { value: "baileys", label: "Baileys (sidecar interno)", color: "#0ea5e9" },
            { value: "evolution", label: "Evolution API (externo)", color: "#7c3aed" },
          ].map((opt) => (
            <button
              key={opt.value}
              data-testid={`provider-option-${opt.value}`}
              onClick={() => setProvider(opt.value)}
              style={{
                flex: 1, padding: "12px 14px", borderRadius: 10, fontWeight: 700, fontSize: 13,
                cursor: "pointer",
                background: provider === opt.value ? opt.color : "white",
                color: provider === opt.value ? "white" : opt.color,
                border: `2px solid ${opt.color}`,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {provider === "evolution" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 6 }}>
            <div data-testid="provider-evolution-defaults-bar" style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              gap: 10, padding: "8px 10px", borderRadius: 8,
              background: defaultsErr ? "#fef2f2" : "#ecfeff",
              border: `1px solid ${defaultsErr ? "#fecaca" : "#a5f3fc"}`,
              fontSize: 11,
            }}>
              <span style={{
                color: defaultsErr ? "#b91c1c" : "#0e7490",
                lineHeight: 1.35, flex: 1,
              }}>
                {loadingDefaults
                  ? "Carregando defaults do servidor…"
                  : defaultsErr
                    ? defaultsErr
                    : "Defaults do servidor carregados (EVOLUTION_URL + API_KEY do .env)."}
              </span>
              <button
                data-testid="provider-evolution-reload-defaults"
                onClick={() => fetchDefaults(true)}
                disabled={loadingDefaults}
                style={{
                  padding: "4px 10px",
                  background: defaultsErr ? "#fee2e2" : "white",
                  color: defaultsErr ? "#b91c1c" : "#0e7490",
                  border: `1px solid ${defaultsErr ? "#fca5a5" : "#a5f3fc"}`,
                  borderRadius: 6, cursor: loadingDefaults ? "wait" : "pointer",
                  fontSize: 11, fontWeight: 700, whiteSpace: "nowrap",
                }}
              >
                {loadingDefaults ? "…" : "Recarregar"}
              </button>
            </div>
            <label style={{ fontSize: 12, fontWeight: 700, color: "#475569" }}>
              URL Evolution API
              <input
                data-testid="provider-evolution-url"
                value={evoUrl}
                onChange={(e) => setEvoUrl(e.target.value)}
                placeholder="https://evo.seudominio.com"
                style={{ width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1",
                          borderRadius: 8, marginTop: 4, fontSize: 13 }}
              />
            </label>
            <label style={{ fontSize: 12, fontWeight: 700, color: "#475569" }}>
              API Key global (apikey header)
              <input
                data-testid="provider-evolution-key"
                value={evoKey}
                onChange={(e) => { setEvoKey(e.target.value); setUsingServerKey(false); }}
                placeholder={channel?.evolution_api_key_masked
                  ? `(atual: ${channel.evolution_api_key_masked}) — cole nova chave pra trocar`
                  : "cole a AUTHENTICATION_API_KEY do container Evolution"}
                type="password"
                style={{ width: "100%", padding: "8px 10px",
                          border: `1px solid ${usingServerKey ? "#10b981" : "#cbd5e1"}`,
                          borderRadius: 8, marginTop: 4, fontSize: 13, fontFamily: "monospace",
                          background: usingServerKey ? "#ecfdf5" : "white" }}
              />
              {usingServerKey && (
                <div style={{ fontSize: 11, color: "#047857", marginTop: 4, fontWeight: 600 }}>
                  ✓ Preenchido automaticamente do servidor (EVOLUTION_API_KEY)
                </div>
              )}
            </label>
            <label style={{ fontSize: 12, fontWeight: 700, color: "#475569" }}>
              Nome da instance
              <input
                data-testid="provider-evolution-instance"
                value={evoInstance}
                onChange={(e) => setEvoInstance(e.target.value)}
                placeholder={`ex: ${channel?.id || "channel-1"}`}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1",
                          borderRadius: 8, marginTop: 4, fontSize: 13, fontFamily: "monospace" }}
              />
            </label>
            <p style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
              💡 Após salvar, clique <b>Conectar via QR</b> no card pra Evolution gerar a instance e
              retornar o QR. Configure o webhook depois apontando pro seu backend.
            </p>
          </div>
        )}

        {err && (
          <div data-testid="provider-error" style={{
            marginTop: 12, padding: "10px 12px", background: "#fef2f2", color: "#b91c1c",
            border: "1px solid #fecaca", borderRadius: 8, fontSize: 12,
          }}>
            {err}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
          <button
            data-testid="provider-cancel-btn"
            onClick={onClose}
            disabled={saving}
            style={{ padding: "10px 18px", background: "white", color: "#475569",
                      border: "1px solid #cbd5e1", borderRadius: 8, cursor: "pointer",
                      fontWeight: 600, fontSize: 13 }}
          >
            Cancelar
          </button>
          <button
            data-testid="provider-save-btn"
            onClick={handleSave}
            disabled={saving}
            style={{ padding: "10px 18px", background: "#0d9488", color: "white",
                      border: "none", borderRadius: 8, cursor: saving ? "wait" : "pointer",
                      fontWeight: 700, fontSize: 13 }}
          >
            {saving ? "Salvando…" : "Salvar provedor"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────
   ExternalChannelCard — Card para providers externos (Evolution API).
   Renderizado em seção própria, fora do grid Baileys.
   CTO 16/02/2026.
─────────────────────────────────────────────────────────────────── */
function ExternalChannelCard({ ch, busy, onConfigProvider, onLogout, onRefresh }) {
  const isAuthRequired = ch.live_state === "auth_required";
  const isConfigInvalid = ch.live_state === "config_invalid";
  const isUnreachable = ch.live_state === "unreachable";
  const isConnected = ch.live_state === "open" || ch.live_connected;

  const badge = isConnected
    ? { c: "#16a34a", bg: "#dcfce7", b: "#86efac", label: "Conectado" }
    : isAuthRequired
    ? { c: "#b45309", bg: "#fef3c7", b: "#fcd34d", label: "Auth Required" }
    : isConfigInvalid
    ? { c: "#dc2626", bg: "#fee2e2", b: "#fca5a5", label: "Config Inválida" }
    : isUnreachable
    ? { c: "#64748b", bg: "#f1f5f9", b: "#cbd5e1", label: "Inacessível" }
    : { c: "#ca8a04", bg: "#fef9c3", b: "#fde047", label: ch.live_state || "—" };

  return (
    <div
      data-testid={`external-channel-${ch.id}`}
      style={{
        background: "white",
        border: `1px solid ${isConnected ? "#86efac" : "#e2e8f0"}`,
        borderRadius: 12,
        padding: 18,
        boxShadow: "0 1px 2px rgba(0,0,0,.04)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <strong style={{ fontSize: 15, color: "#0f172a" }}>
              {ch.name || ch.channel_name || ch.id}
            </strong>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: "2px 7px",
              background: "#eef2ff", color: "#4338ca", borderRadius: 4,
              letterSpacing: 0.5,
            }}>{(ch.provider || "external").toUpperCase()}</span>
          </div>
          <div style={{ marginTop: 4, fontSize: 12, color: "#64748b" }}>
            {ch.evolution_url && <span>URL: {ch.evolution_url}</span>}
          </div>
          {ch.evolution_instance && (
            <div style={{ marginTop: 2, fontSize: 11, color: "#94a3b8" }}>
              Instância: <code>{ch.evolution_instance}</code>
            </div>
          )}
          {ch.phone_number && (
            <div style={{ marginTop: 6, fontSize: 13, color: "#0f172a", fontWeight: 600 }}>
              📱 {ch.phone_number}
            </div>
          )}
        </div>
        <span style={{
          padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700,
          background: badge.bg, color: badge.c, border: `1px solid ${badge.b}`,
          whiteSpace: "nowrap",
        }}>{badge.label}</span>
      </div>

      {ch.live_error && (
        <div style={{
          marginTop: 12, padding: 10,
          background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8,
          fontSize: 12, color: "#991b1b", lineHeight: 1.45,
        }} data-testid={`external-channel-${ch.id}-error`}>
          <AlertTriangle size={13} style={{ verticalAlign: "-2px", marginRight: 4 }}/>
          {ch.live_error}
        </div>
      )}

      <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          data-testid={`external-channel-${ch.id}-config`}
          onClick={() => onConfigProvider && onConfigProvider(ch)}
          disabled={busy}
          style={{
            padding: "7px 12px", background: "#0f766e", color: "white",
            border: "none", borderRadius: 6, fontWeight: 600, fontSize: 12,
            cursor: busy ? "not-allowed" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}
        >
          <Settings size={13}/> Configurar
        </button>
        <button
          data-testid={`external-channel-${ch.id}-refresh`}
          onClick={onRefresh}
          disabled={busy}
          style={{
            padding: "7px 12px", background: "white", color: "#0f766e",
            border: "1px solid #99f6e4", borderRadius: 6, fontWeight: 600, fontSize: 12,
            cursor: busy ? "not-allowed" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}
        >
          <RefreshCw size={13}/> Atualizar
        </button>
        {isConnected && (
          <button
            data-testid={`external-channel-${ch.id}-logout`}
            onClick={onLogout}
            disabled={busy}
            style={{
              padding: "7px 12px", background: "white", color: "#dc2626",
              border: "1px solid #fecaca", borderRadius: 6, fontWeight: 600, fontSize: 12,
              cursor: busy ? "not-allowed" : "pointer",
              display: "inline-flex", alignItems: "center", gap: 6,
            }}
          >
            <LogOut size={13}/> Desconectar
          </button>
        )}
      </div>
    </div>
  );
}



export default function WhatsAppChannelsPanel() {
  const [channels, setChannels] = useState([]);
  const [externals, setExternals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [providerFor, setProviderFor] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api.waChannelsList();
      setChannels(data?.channels || []);
      setExternals(data?.external_channels || []);
      setErr(null);
    } catch (e) {
      setErr(e?.message || "Falha ao carregar canais");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000); // poll a cada 8s
    return () => clearInterval(t);
  }, [load]);

  const handleRename = async (channelId, name) => {
    setBusy(true);
    try { await api.waChannelRename(channelId, name); await load(); }
    finally { setBusy(false); }
  };

  const handleSetDefault = async (channelId) => {
    setBusy(true);
    try { await api.waChannelSetDefault(channelId); await load(); }
    finally { setBusy(false); }
  };

  const handleLogout = async (ch) => {
    if (!window.confirm(`Desconectar ${ch.channel_name}?`)) return;
    setBusy(true);
    try { await api.waChannelLogout(ch.id); await load(); }
    finally { setBusy(false); }
  };

  return (
    <div data-testid="wa-channels-panel" style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#0f172a" }}>
            Canais WhatsApp
          </h2>
          <p style={{ margin: "6px 0 0", color: "#64748b", fontSize: 14 }}>
            Conecte até <b>4 números</b>. Todos os agentes IA (Isabella, Alvaro, Pâmela)
            atendem em <b>qualquer canal</b>. O nome do canal aparece nas conversas.
          </p>
        </div>
        <button
          data-testid="channels-refresh-btn"
          onClick={load}
          disabled={loading}
          style={{
            padding: "8px 14px", background: "white", color: "#0f766e",
            border: "1px solid #99f6e4", borderRadius: 8, cursor: "pointer",
            fontWeight: 600, fontSize: 13,
            display: "inline-flex", alignItems: "center", gap: 6,
          }}
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""}/> Atualizar
        </button>
      </div>

      {err && (
        <div style={{
          padding: 12, background: "#fef2f2", color: "#b91c1c",
          border: "1px solid #fecaca", borderRadius: 8, marginBottom: 16, fontSize: 13,
        }} data-testid="channels-error">
          {err}
        </div>
      )}

      {loading && channels.length === 0 ? (
        <div style={{ padding: 60, textAlign: "center" }}>
          <Loader2 className="animate-spin" size={32} color="#0d9488"/>
        </div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))",
          gap: 16,
          alignItems: "start",
        }}>
          {channels.map((ch) => (
            <ChannelCard
              key={ch.id}
              ch={ch}
              busy={busy}
              onRename={handleRename}
              onSetDefault={handleSetDefault}
              onLogout={handleLogout}
              onConfigProvider={(c) => setProviderFor(c)}
              onRefresh={load}
            />
          ))}
        </div>
      )}

      {/* ───── Provedores externos (Evolution API, etc) ─────
         CTO 16/02/2026 — Isolados do grid Baileys: falha aqui NÃO bloqueia
         os 4 canais Baileys. UI separada visualmente. */}
      {externals.length > 0 && (
        <div data-testid="external-channels-section" style={{ marginTop: 32 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 15, fontWeight: 700, color: "#0f172a" }}>
            Provedores externos
          </h3>
          <p style={{ margin: "0 0 14px", color: "#64748b", fontSize: 12 }}>
            Canais via APIs de terceiros (Evolution API, etc). Operam independente
            dos 4 sidecars Baileys — falhas aqui não afetam os canais acima.
          </p>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))",
            gap: 16,
          }}>
            {externals.map((ch) => (
              <ExternalChannelCard
                key={ch.id}
                ch={ch}
                busy={busy}
                onConfigProvider={(c) => setProviderFor(c)}
                onLogout={async () => {
                  if (!window.confirm(`Desconectar ${ch.name || ch.channel_name}?`)) return;
                  setBusy(true);
                  try {
                    const r = await api.waChannelLogout(ch.id);
                    if (r?.ok === false && r?.error) {
                      alert(`Não consegui desconectar: ${r.error}`);
                    }
                    await load();
                  } finally { setBusy(false); }
                }}
                onRefresh={load}
              />
            ))}
          </div>
        </div>
      )}

      {providerFor && (
        <ProviderModal
          channel={providerFor}
          onClose={() => setProviderFor(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
