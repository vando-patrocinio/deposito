import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Loader2, CheckCircle2, AlertTriangle, RefreshCw, LogOut,
  MessageSquare, Smartphone, Edit2, Save, X, Plug,
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
      // Polling rápido enquanto aguarda escanear o QR → reflete conexão em ~1.5s
      const interval = need ? 1500 : 8000;
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

      {/* Card de Renomear instância (sempre visível) */}
      <InstanceNameCard status={status} />

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
    </div>
  );
}

function InstanceNameCard({ status }) {
  const [name, setName] = useState("Ligo");
  const [loaded, setLoaded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    api.waBaileysGetInstance()
      .then((r) => { if (alive) { setName(r.display_name || "Ligo"); setLoaded(true); } })
      .catch(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, []);

  const startEdit = () => { setDraft(name); setEditing(true); setErr(null); };
  const cancelEdit = () => { setEditing(false); setDraft(""); setErr(null); };
  const saveEdit = async () => {
    const v = draft.trim();
    if (!v || v.length > 40) {
      setErr("Use entre 1 e 40 caracteres.");
      return;
    }
    setBusy(true);
    try {
      await api.waBaileysSetInstance(v);
      setName(v);
      setEditing(false);
      // dispatch event para AIHubPanel atualizar imediatamente sem esperar polling
      window.dispatchEvent(new CustomEvent("wa-instance-renamed", { detail: { name: v } }));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const isConnected = status === "connected";
  return (
    <div data-testid="wa-instance-name-card" style={{
      padding: 14, borderRadius: 12,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
      display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
    }}>
      <div style={{
        position: "relative",
        width: 44, height: 44, borderRadius: 10,
        background: isConnected ? "rgba(22,163,74,.12)" : "var(--bg-surface-2)",
        border: `1px solid ${isConnected ? "#16a34a" : "var(--border-default)"}`,
        display: "grid", placeItems: "center",
        transition: "all .25s",
      }}>
        <Plug size={20} strokeWidth={2}
                style={{ color: isConnected ? "#16a34a" : "var(--text-muted)" }} />
        <span style={{
          position: "absolute", top: -3, right: -3,
          width: 11, height: 11, borderRadius: "50%",
          background: isConnected ? "#16a34a" : "#94a3b8",
          border: "2px solid var(--bg-surface)",
          boxShadow: isConnected ? "0 0 8px rgba(22,163,74,.7)" : "none",
        }} />
      </div>
      <div style={{ flex: 1, minWidth: 240 }}>
        <div style={{ fontSize: 10, fontWeight: 800,
                          color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.6 }}>
          Nome da instância WhatsApp
        </div>
        {editing ? (
          <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)}
                     autoFocus maxLength={40}
                     onKeyDown={(e) => {
                       if (e.key === "Enter") saveEdit();
                       if (e.key === "Escape") cancelEdit();
                     }}
                     data-testid="instance-name-input"
                     style={{
                       padding: "6px 10px", fontSize: 15, fontWeight: 700,
                       border: "1px solid var(--border-default)", borderRadius: 6,
                       background: "var(--bg-surface)", color: "var(--text-primary)",
                       width: 240, fontFamily: "inherit",
                     }} />
            <button onClick={saveEdit} disabled={busy}
                     data-testid="instance-name-save"
                     style={{
                       padding: "6px 10px", fontSize: 12, fontWeight: 700,
                       background: "#16a34a", color: "#fff",
                       border: "none", borderRadius: 6,
                       cursor: busy ? "wait" : "pointer",
                       display: "inline-flex", alignItems: "center", gap: 4,
                     }}>
              {busy
                ? <Loader2 size={12} style={{ animation: "wa-spin 1s linear infinite" }} />
                : <Save size={12} />}
              Salvar
            </button>
            <button onClick={cancelEdit}
                     data-testid="instance-name-cancel"
                     style={{
                       padding: "6px 10px", fontSize: 12, fontWeight: 600,
                       background: "var(--bg-surface-2)",
                       color: "var(--text-secondary)",
                       border: "1px solid var(--border-default)", borderRadius: 6,
                       cursor: "pointer",
                       display: "inline-flex", alignItems: "center", gap: 4,
                     }}>
              <X size={12} /> Cancelar
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
            <strong data-testid="instance-name-display"
                       style={{ fontSize: 18, color: "var(--text-primary)",
                                  letterSpacing: "-0.012em" }}>
              {loaded ? name : "..."}
            </strong>
            <button onClick={startEdit}
                     data-testid="instance-name-edit-btn"
                     style={{
                       padding: "4px 9px", fontSize: 11, fontWeight: 600,
                       background: "var(--bg-surface-2)",
                       color: "var(--text-secondary)",
                       border: "1px solid var(--border-default)", borderRadius: 5,
                       cursor: "pointer",
                       display: "inline-flex", alignItems: "center", gap: 4,
                     }}>
              <Edit2 size={10} /> Renomear
            </button>
          </div>
        )}
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
          Este nome aparece na aba principal de atendimento.
          {isConnected
            ? <span style={{ color: "#16a34a", fontWeight: 700 }}> Instância ativa e funcional.</span>
            : <span style={{ color: "#94a3b8", fontWeight: 600 }}> Conecte um número via QR Code para ativar.</span>}
        </div>
        {err && (
          <div style={{ fontSize: 11, color: "#dc2626", marginTop: 4 }}>
            {err}
          </div>
        )}
      </div>
    </div>
  );
}

