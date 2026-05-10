import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  QrCode, Loader2, CheckCircle2, AlertTriangle, RefreshCw, LogOut,
  MessageSquare, Send, Smartphone,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   Conexão WhatsApp por QR Code (Baileys sidecar)
   - Polling de /qr a cada 3s quando desconectado
   - Polling de /status a cada 4s quando conectado
   - Auto-refresh do QR (expira a cada ~60s)
   - Painel de envio quando conectado
============================================================= */

const STATE_MAP = {
  connecting:   { label: "Conectando...",   color: "#0ea5e9", icon: Loader2 },
  connected:    { label: "Conectado",       color: "#16a34a", icon: CheckCircle2 },
  disconnected: { label: "Desconectado",    color: "#94a3b8", icon: AlertTriangle },
};

export default function WhatsAppQRPanel() {
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
    // Polling adaptativo: 3s quando precisa QR, 8s quando já conectado
    let currentInterval = null;
    const setupPoll = () => {
      if (currentInterval) clearInterval(currentInterval);
      const ms = status === "connected" ? 8000 : 3000;
      currentInterval = setInterval(fetchState, ms);
      pollRef.current = currentInterval;
    };
    setupPoll();
    return () => { if (currentInterval) clearInterval(currentInterval); };
    // Reage a mudanças de status pra trocar de cadência
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, fetchState]);

  const logout = async () => {
    if (!window.confirm("Tem certeza? Vai desconectar e exigir novo QR.")) return;
    setBusy(true); setErr(null);
    try {
      await api.waBaileysLogout();
      await new Promise((res) => setTimeout(res, 1500));
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
    <div data-testid="wa-qr-panel" style={{ display: "grid", gap: 14 }}>
      <style>{`
        @keyframes wa-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
        @keyframes wa-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
      `}</style>

      {/* Header */}
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
                          style={{ animation: status === "connecting" ? "wa-spin 1.2s linear infinite" : "none" }} />
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

      {/* Conteúdo principal */}
      {status === "connected" ? (
        <ConnectedView phoneNumber={phoneNumber} me={me} onLogout={logout} busy={busy} />
      ) : (
        <QrView qr={qr} lastQrAt={lastQrAt} status={status} onRefresh={refreshNow} busy={busy} />
      )}
    </div>
  );
}

/* ----- View desconectado: mostra QR ----- */
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
            <Smartphone size={14} strokeWidth={1.75} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              O QR <strong>expira a cada ~60s</strong> e atualiza sozinho.
              {lastQrAt && (
                <> Último gerado: <span className="mono">{new Date(lastQrAt).toLocaleTimeString("pt-BR")}</span>.</>
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

/* ----- View conectado: mostra dados + permite enviar mensagem teste ----- */
function ConnectedView({ phoneNumber, me, onLogout, busy }) {
  const [destPhone, setDestPhone] = useState("");
  const [msgText, setMsgText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState(null);
  const [messages, setMessages] = useState([]);

  const loadMessages = useCallback(async () => {
    try {
      const r = await api.waBaileysMessages(30);
      setMessages(r.items || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadMessages();
    const id = setInterval(loadMessages, 6000);
    return () => clearInterval(id);
  }, [loadMessages]);

  const send = async () => {
    if (!destPhone.trim() || !msgText.trim()) {
      alert("Informe número e mensagem."); return;
    }
    setSending(true); setSendResult(null);
    try {
      const r = await api.waBaileysSend(destPhone.trim(), msgText.trim());
      setSendResult({ ok: true, msg: "Mensagem enviada!" });
      setMsgText("");
      loadMessages();
    } catch (e) {
      setSendResult({ ok: false, msg: e?.response?.data?.detail || e.message });
    } finally { setSending(false); }
  };

  return (
    <div data-testid="wa-connected-view" style={{ display: "grid", gap: 14 }}>
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

      {/* Envio rápido */}
      <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <Send size={14} strokeWidth={1.75} style={{ color: "var(--accent)" }} />
          <strong style={{ fontSize: 13 }}>Enviar mensagem (teste)</strong>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "200px 1fr auto",
                       gap: 8, alignItems: "stretch" }}>
          <input className="input" placeholder="55219..."
                 value={destPhone} onChange={(e) => setDestPhone(e.target.value)}
                 data-testid="wa-dest-phone" />
          <input className="input" placeholder="Olá! Teste de envio"
                 value={msgText} onChange={(e) => setMsgText(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && send()}
                 data-testid="wa-msg-text" />
          <button className="btn btn-primary btn-sm" onClick={send} disabled={sending}
                  data-testid="wa-send-btn">
            <Send size={13} /> {sending ? "Enviando..." : "Enviar"}
          </button>
        </div>
        {sendResult && (
          <div data-testid="wa-send-result" style={{
            marginTop: 10, padding: 8, borderRadius: 8,
            background: sendResult.ok ? "var(--success-soft)" : "var(--danger-soft)",
            color: sendResult.ok ? "var(--success-soft-fg)" : "var(--danger-soft-fg)",
            fontSize: 11, display: "flex", alignItems: "center", gap: 6,
          }}>
            {sendResult.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            {sendResult.msg}
          </div>
        )}
      </div>

      {/* Histórico recente */}
      {messages.length > 0 && (
        <div className="surface" style={{ padding: 14, borderRadius: 12 }}
             data-testid="wa-history">
          <div style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                         textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 10 }}>
            Histórico recente ({messages.length})
          </div>
          <div style={{ display: "grid", gap: 6, maxHeight: 320, overflowY: "auto" }}>
            {messages.map((m) => (
              <div key={m.id} style={{
                padding: "6px 10px", borderRadius: 8, fontSize: 12,
                border: "1px solid var(--border-default)",
                background: m.direction === "outbound" ? "rgba(37,211,102,.07)" : "var(--bg-surface-2)",
                display: "flex", gap: 8, alignItems: "center",
              }}>
                <span style={{ fontSize: 10, fontWeight: 700,
                                color: m.direction === "outbound" ? "#15803d" : "var(--text-muted)",
                                textTransform: "uppercase", letterSpacing: 0.4,
                                minWidth: 60 }}>
                  {m.direction === "outbound" ? "→ Enviada" : "← Recebida"}
                </span>
                <span className="mono" style={{ fontSize: 11, minWidth: 110 }}>
                  +{m.phone}
                </span>
                <span style={{ flex: 1, color: "var(--text-primary)" }}>
                  {(m.text || "").slice(0, 140)}
                </span>
                <span style={{ fontSize: 10, color: "var(--text-muted)" }} className="mono">
                  {new Date(m.created_at).toLocaleTimeString("pt-BR")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
