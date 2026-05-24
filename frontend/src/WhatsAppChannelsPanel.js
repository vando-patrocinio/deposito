import React, { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Star, StarOff, LogOut, Pencil, Check, X, QrCode } from "lucide-react";
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

   Todos os agentes IA (Isabella/Alvaro/Camila) respondem em qualquer canal —
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

function ChannelCard({ ch, onRename, onSetDefault, onConnect, onLogout, busy }) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(ch.channel_name || "");
  const connected = ch.live_connected || ch.live_state === "connected";

  useEffect(() => { setDraftName(ch.channel_name || ""); }, [ch.channel_name]);

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

      {/* Status + phone */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
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
      </div>

      {/* Ações */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {!connected && (
          <button
            data-testid={`channel-connect-btn-${ch.id}`}
            onClick={() => onConnect(ch)}
            disabled={busy}
            style={{
              padding: "8px 14px", background: "#0d9488", color: "white",
              border: "none", borderRadius: 8, cursor: "pointer", fontWeight: 600,
              fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6,
            }}
          >
            <QrCode size={14}/> Conectar via QR
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

export default function WhatsAppChannelsPanel() {
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [qrFor, setQrFor] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api.waChannelsList();
      setChannels(data?.channels || []);
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
            Conecte até <b>4 números</b>. Todos os agentes IA (Isabella, Alvaro, Camila)
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
        }}>
          {channels.map((ch) => (
            <ChannelCard
              key={ch.id}
              ch={ch}
              busy={busy}
              onRename={handleRename}
              onSetDefault={handleSetDefault}
              onConnect={(c) => setQrFor(c)}
              onLogout={handleLogout}
            />
          ))}
        </div>
      )}

      {qrFor && <QRModal channel={qrFor} onClose={() => { setQrFor(null); load(); }} />}
    </div>
  );
}
