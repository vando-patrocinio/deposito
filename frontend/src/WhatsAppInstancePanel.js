import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Loader2, CheckCircle2, AlertTriangle, RefreshCw, LogOut,
  MessageSquare, Smartphone, Bot, Zap,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   Painel Instância WhatsApp — só configuração:
   - Conectar via QR Code (Baileys sidecar)
   - Status da conexão (Conectado como +xxx)
   - Toggle Auto-Resposta IA Jerusa
   O chat propriamente dito (FocusChat) fica na aba "WhatsApp".
============================================================= */

const STATE_MAP = {
  connecting:   { label: "Conectando...",   color: "#0ea5e9", icon: Loader2 },
  connected:    { label: "Conectado",       color: "#16a34a", icon: CheckCircle2 },
  disconnected: { label: "Desconectado",    color: "#94a3b8", icon: AlertTriangle },
};

export default function WhatsAppInstancePanel() {
  const [status, setStatus] = useState("connecting");
  const [qr, setQr] = useState(null);
  const [me, setMe] = useState(null);
  const [lastQrAt, setLastQrAt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const pollRef = useRef(null);

  const fetchState = useCallback(async () => {
    try {
      const r = await api.waBaileysQR();
      setStatus(r.status || "disconnected");
      setQr(r.qr || null);
      setMe(r.me || null);
      setLastQrAt(r.last_qr_at || null);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
      setStatus("disconnected");
    }
  }, []);

  useEffect(() => {
    fetchState();
    let currentInterval = null;
    const setupPoll = () => {
      const need = status !== "connected";
      const interval = need ? 3000 : 8000;
      if (currentInterval !== interval) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(fetchState, interval);
        currentInterval = interval;
      }
    };
    setupPoll();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchState, status]);

  const logout = async () => {
    if (!window.confirm("Desconectar este número do WhatsApp?")) return;
    setBusy(true);
    try {
      await api.waBaileysLogout();
      await fetchState();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const refreshNow = async () => { setBusy(true); await fetchState(); setBusy(false); };

  const info = STATE_MAP[status] || STATE_MAP.disconnected;
  const StatusIcon = info.icon;
  const phoneNumber = me?.id ? me.id.split(":")[0].split("@")[0] : null;

  return (
    <div data-testid="wa-instance-panel" style={{ display: "grid", gap: 14 }}>
      <style>{`
        @keyframes wa-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
        @keyframes wa-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
      `}</style>

      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, #25d36622 0%, var(--bg-surface) 60%)",
        border: "1px solid var(--border-default)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{
            width: 52, height: 52, borderRadius: 14,
            background: "#25d366", color: "#fff",
            display: "grid", placeItems: "center",
            boxShadow: "0 4px 14px rgba(37,211,102,.35)",
          }}>
            <MessageSquare size={26} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                          letterSpacing: "-0.02em" }}>
              Conectar WhatsApp por QR Code
            </h2>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
              Escaneie o QR com seu WhatsApp (Aparelhos conectados) para vincular
              o número do provedor. Funciona igual ao WhatsApp Web.
            </div>
          </div>
          <div data-testid="wa-state-badge" style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "6px 13px", borderRadius: 999,
            background: "var(--bg-surface)",
            border: `1px solid ${info.color}`,
            color: info.color, fontSize: 12, fontWeight: 800,
            textTransform: "uppercase", letterSpacing: 0.6,
          }}>
            <StatusIcon size={14} strokeWidth={2.2}
                          style={{ animation: status === "connecting"
                            ? "wa-spin 1.2s linear infinite" : "none" }} />
            {info.label}
          </div>
        </div>
      </div>

      {err && (
        <div style={{
          padding: 10, borderRadius: 8,
          background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
          fontSize: 12, display: "flex", alignItems: "center", gap: 8,
        }} data-testid="wa-error">
          <AlertTriangle size={14} /> {err}
        </div>
      )}

      {status === "connected" ? (
        <ConnectedView phoneNumber={phoneNumber} me={me} onLogout={logout} busy={busy} />
      ) : (
        <QrView qr={qr} lastQrAt={lastQrAt} status={status}
                  onRefresh={refreshNow} busy={busy} />
      )}
    </div>
  );
}

function QrView({ qr, lastQrAt, status, onRefresh, busy }) {
  return (
    <div className="surface" style={{ padding: 24, borderRadius: 14 }}
         data-testid="wa-qr-view">
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 24,
                     alignItems: "center", flexWrap: "wrap" }}>
        <div style={{
          width: 320, height: 320, borderRadius: 14,
          background: "#fff", padding: 14,
          display: "grid", placeItems: "center",
          border: "1px solid var(--border-default)",
        }}>
          {qr ? (
            <img src={qr} alt="WhatsApp QR Code" data-testid="wa-qr-image"
                 style={{ width: "100%", height: "100%", objectFit: "contain" }} />
          ) : (
            <div style={{ textAlign: "center", color: "#666" }}>
              <Loader2 size={36}
                         style={{ animation: "wa-spin 1.2s linear infinite", marginBottom: 8 }} />
              <div style={{ fontSize: 12 }}>Gerando QR Code...</div>
            </div>
          )}
        </div>
        <div>
          <h3 style={{ margin: "0 0 12px", fontSize: 16, fontWeight: 800 }}>
            Como conectar
          </h3>
          <ol style={{ paddingLeft: 18, margin: 0, fontSize: 13, lineHeight: 1.8,
                       color: "var(--text-primary)" }}>
            <li>Abra o <strong>WhatsApp</strong> no seu celular</li>
            <li>Toque em <strong>Mais opções</strong> ou <strong>Configurações</strong></li>
            <li>Toque em <strong>Aparelhos conectados</strong></li>
            <li>Toque em <strong>Conectar um aparelho</strong></li>
            <li>Aponte a câmera para o QR Code ao lado</li>
          </ol>
          <div style={{
            marginTop: 14, padding: 10, borderRadius: 8,
            background: "var(--info-soft)", color: "var(--info-soft-fg)",
            fontSize: 11, display: "flex", alignItems: "flex-start", gap: 8,
          }}>
            <Smartphone size={14} strokeWidth={1.75}
                          style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              O QR <strong>expira a cada ~60s</strong> e atualiza sozinho.
              {lastQrAt && (
                <> Último gerado: <span className="mono">
                  {new Date(lastQrAt).toLocaleTimeString("pt-BR")}</span>.</>
              )}
            </span>
          </div>
          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-ghost btn-sm" onClick={onRefresh} disabled={busy}
                    data-testid="wa-refresh-btn">
              <RefreshCw size={13} /> Atualizar
            </button>
            {status === "connecting" && (
              <div style={{ fontSize: 11, color: "var(--text-muted)",
                             display: "flex", alignItems: "center", gap: 6,
                             animation: "wa-pulse 1.6s ease-in-out infinite" }}>
                <Loader2 size={12} style={{ animation: "wa-spin 1.2s linear infinite" }} />
                Aguardando escaneamento...
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ConnectedView({ phoneNumber, me, onLogout, busy }) {
  const [autoReply, setAutoReply] = useState({ enabled: false, agent_name: "Jerusa" });
  const [autoReplyBusy, setAutoReplyBusy] = useState(false);

  const loadAutoReply = useCallback(async () => {
    try {
      const r = await api.waBaileysGetAutoReply();
      setAutoReply({ enabled: !!r.enabled, agent_name: r.agent_name || "Jerusa" });
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadAutoReply(); }, [loadAutoReply]);

  const toggleAutoReply = async () => {
    setAutoReplyBusy(true);
    try {
      const r = await api.waBaileysSetAutoReply({ enabled: !autoReply.enabled });
      setAutoReply({ enabled: !!r.enabled, agent_name: r.agent_name || "Jerusa" });
    } catch (e) {
      alert("Falha ao alterar auto-reply: " + (e?.response?.data?.detail || e.message));
    } finally { setAutoReplyBusy(false); }
  };

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="surface" style={{
        padding: 16, borderRadius: 12,
        background: "linear-gradient(135deg, rgba(22,163,74,.12) 0%, var(--bg-surface) 60%)",
        border: "1px solid #16a34a55",
      }}>
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <CheckCircle2 size={28} strokeWidth={1.75} style={{ color: "#16a34a" }} />
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                           textTransform: "uppercase", letterSpacing: 0.6 }}>
              Conectado como
            </div>
            <div data-testid="wa-connected-phone"
                 className="mono"
                 style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>
              +{phoneNumber || "—"}
            </div>
            {me?.name && (
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                {me.name}
              </div>
            )}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onLogout} disabled={busy}
                  data-testid="wa-logout-btn"
                  style={{ color: "var(--danger)" }}>
            <LogOut size={13} /> Desconectar
          </button>
        </div>
      </div>

      <div className="surface" style={{
        padding: 16, borderRadius: 12,
        border: autoReply.enabled ? "1px solid #16a34a" : "1px solid var(--border-default)",
        background: autoReply.enabled
          ? "linear-gradient(135deg, rgba(22,163,74,.08) 0%, var(--bg-surface) 60%)"
          : "var(--bg-surface)",
      }} data-testid="wa-autoreply-card">
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{
            width: 42, height: 42, borderRadius: 10,
            background: autoReply.enabled ? "#16a34a" : "var(--bg-surface-2)",
            color: autoReply.enabled ? "#fff" : "var(--text-muted)",
            display: "grid", placeItems: "center",
            transition: "all .25s",
          }}>
            <Bot size={22} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <strong style={{ fontSize: 14 }}>Auto-Resposta com IA Jerusa</strong>
              {autoReply.enabled && (
                <span style={{
                  display: "inline-flex", alignItems: "center", gap: 3,
                  padding: "2px 8px", borderRadius: 999,
                  background: "rgba(22,163,74,.15)", color: "#15803d",
                  fontSize: 10, fontWeight: 800, textTransform: "uppercase",
                  letterSpacing: 0.6,
                }}>
                  <Zap size={9} /> Ativo 24/7
                </span>
              )}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3 }}>
              Quando uma mensagem chega, a <strong>{autoReply.agent_name}</strong> identifica
              o cliente automaticamente, busca contexto (plano, status, débitos) e responde
              sozinha. Conversação multi-turno persistente por contato.
            </div>
          </div>
          <button
            onClick={toggleAutoReply}
            disabled={autoReplyBusy}
            data-testid="wa-autoreply-toggle"
            style={{
              position: "relative", width: 58, height: 32, borderRadius: 999,
              border: "none", cursor: autoReplyBusy ? "wait" : "pointer",
              background: autoReply.enabled ? "#16a34a" : "var(--border-default)",
              transition: "background .25s",
              outline: "none",
            }}>
            <span style={{
              position: "absolute",
              top: 3, left: autoReply.enabled ? 29 : 3,
              width: 26, height: 26, borderRadius: "50%",
              background: "#fff",
              transition: "left .25s",
              boxShadow: "0 2px 6px rgba(0,0,0,.2)",
            }} />
          </button>
        </div>
        {autoReply.enabled && (
          <div style={{
            marginTop: 10, padding: 10, borderRadius: 8,
            background: "var(--info-soft)", color: "var(--info-soft-fg)",
            fontSize: 11, display: "flex", alignItems: "flex-start", gap: 8,
          }}>
            <AlertTriangle size={12} strokeWidth={1.75} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              A Jerusa está respondendo automaticamente todas as conversas (exceto grupos).
              Para retomar manualmente uma conversa específica, desligue este toggle.
              <strong> Mensagens com contexto de cliente identificado</strong> são personalizadas.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
