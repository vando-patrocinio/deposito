import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Loader2, CheckCircle2, AlertTriangle, RefreshCw, LogOut,
  MessageSquare, Smartphone, Edit2, Save, X, Plug,
  Maximize2, QrCode, ShieldCheck, Wifi, WifiOff,
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
    // Defer initial fetch — evita set-state-in-effect ao montar.
    const initialT = setTimeout(() => { fetchState(); }, 0);
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
    return () => {
      clearTimeout(initialT);
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchState, status]);

  const logout = async () => {
    if (!await window.confirm("Desconectar este número do WhatsApp?")) return;
    setBusy(true);
    try {
      await api.waBaileysLogout();
      await fetchState();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const refreshNow = async () => {
    setBusy(true); setErr(null);
    try {
      // Força um QR novo no sidecar (logout + reconnect interno)
      const r = await api.waBaileysRefreshQR();
      setStatus(r?.status || "qr_pending");
      if (r?.qr) {
        setQr(r.qr);
        setLastQrAt(new Date().toISOString());
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao gerar novo QR");
      // Mesmo falhando, faz fetch normal para mostrar status
      try { await fetchState(); } catch { /* ignore */ }
    } finally {
      setBusy(false);
    }
  };

  /**
   * Force Reset (Logout + Re-QR) — CTO 16/02/2026.
   *
   * Ação destrutiva: limpa credenciais do sidecar (auth_info + Mongo),
   * desloga do WhatsApp e força nova janela de QR Code.
   *
   * Quando usar:
   *   - sidecar travado em loop de "QR refs attempts ended"
   *   - retry_count saturado (12/12) sem reconectar
   *   - WhatsApp invalidou a sessão remotamente (ban temporário, multi-device limit)
   *   - número já está logado em outro lugar e quer "puxar" pra cá
   */
  const forceReset = async () => {
    // eslint-disable-next-line no-alert
    if (!window.confirm(
      "⚠️ FORCE RESET destrutivo\n\n" +
      "Vai:\n" +
      "  1. Deslogar do WhatsApp\n" +
      "  2. Limpar credenciais do sidecar (auth_info + Mongo)\n" +
      "  3. Reiniciar sessão e gerar novo QR Code\n\n" +
      "TODAS as mensagens em fila serão preservadas, mas o número fica " +
      "OFFLINE até alguém escanear o novo QR.\n\nConfirma?"
    )) return;
    setBusy(true); setErr(null);
    try {
      // 1. Logout (limpa creds)
      try {
        await api.waBaileysLogout();
      } catch (e) {
        // Logout pode falhar se já estava disconnected — não bloqueia
        console.warn("[force-reset] logout falhou (ignorado):", e?.message);
      }
      // 2. Aguarda sidecar reinicializar (~2s)
      await new Promise((r) => setTimeout(r, 2000));
      // 3. Pede QR fresh
      const r = await api.waBaileysRefreshQR();
      setStatus(r?.status || "connecting");
      if (r?.qr) {
        setQr(r.qr);
        setLastQrAt(new Date().toISOString());
      }
      // 4. Atualiza state geral
      await fetchState();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Force reset falhou");
      try { await fetchState(); } catch { /* ignore */ }
    } finally {
      setBusy(false);
    }
  };

  const info = STATE_MAP[status] || STATE_MAP.disconnected;
  const StatusIcon = info.icon;
  const phoneNumber = me?.id ? me.id.split(":")[0].split("@")[0] : null;

  return (
    <div data-testid="wa-instance-panel" style={{ display: "grid", gap: 14 }}>
      <style>{`
        @keyframes wa-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
        @keyframes wa-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes wa-fade-in { from { opacity: 0; transform: scale(.96); } to { opacity: 1; transform: scale(1); } }
        @keyframes wa-success-pop { 0% { transform: scale(.6); opacity: 0; } 60% { transform: scale(1.1); opacity: 1; } 100% { transform: scale(1); opacity: 1; } }
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

      {err && status === "connected" && (
        <div style={{
          padding: 10, borderRadius: 8,
          background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
          fontSize: 12, display: "flex", alignItems: "center", gap: 8,
        }} data-testid="wa-error">
          <AlertTriangle size={14} /> {err}
        </div>
      )}

      {status === "connected" ? (
        <ConnectedView phoneNumber={phoneNumber} me={me} onLogout={logout}
                         onForceReset={forceReset} busy={busy} />
      ) : (
        <QrView qr={qr} lastQrAt={lastQrAt} status={status}
                  onRefresh={refreshNow} onForceReset={forceReset}
                  busy={busy} errDetail={err} />
      )}
    </div>
  );
}

function QrView({ qr, lastQrAt, status, onRefresh, onForceReset, busy, errDetail }) {
  const [fullscreen, setFullscreen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const prevQrRef = useRef(qr);
  const [qrPulse, setQrPulse] = useState(false);

  // Atualiza o relógio a cada segundo para o countdown
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Animação de fade quando um novo QR chega
  useEffect(() => {
    if (qr && qr !== prevQrRef.current) {
      setQrPulse(true);
      const id = setTimeout(() => setQrPulse(false), 600);
      prevQrRef.current = qr;
      return () => clearTimeout(id);
    }
  }, [qr]);

  // Countdown — Baileys renova ~60s
  const QR_TTL_MS = 60_000;
  const ageMs = lastQrAt ? now - new Date(lastQrAt).getTime() : null;
  const remaining = ageMs != null
    ? Math.max(0, Math.min(QR_TTL_MS, QR_TTL_MS - ageMs))
    : null;
  const remainingSec = remaining != null ? Math.ceil(remaining / 1000) : null;
  const pctLeft = remaining != null ? Math.max(0, Math.min(1, remaining / QR_TTL_MS)) : 1;
  const willExpire = remainingSec != null && remainingSec <= 10 && qr;

  const isAuthErr = !!errDetail && /n[aã]o\s+autenticad|unauthor|401/i.test(String(errDetail));
  const isSidecarErr = !!errDetail && /sidecar|503|indispon/i.test(String(errDetail));

  // Computa cor do ring por urgência
  const ringColor = remainingSec == null
    ? "#16a34a"
    : remainingSec <= 5 ? "#dc2626"
    : remainingSec <= 15 ? "#f59e0b"
    : "#16a34a";

  // Tamanho do QR
  const QR_SIZE = 340;
  const RING_STROKE = 6;
  const RING_R = (QR_SIZE + RING_STROKE * 3) / 2;
  const RING_C = 2 * Math.PI * RING_R;

  // SubLabel principal
  let subLabel = "Aguardando você escanear…";
  let subColor = "var(--text-muted)";
  if (!qr) {
    subLabel = "Inicializando WhatsApp…";
    subColor = "var(--text-muted)";
  } else if (willExpire) {
    subLabel = `QR expira em ${remainingSec}s — escaneie já!`;
    subColor = "#dc2626";
  } else if (remainingSec != null) {
    subLabel = `Aguardando escaneamento · QR válido por ${remainingSec}s`;
    subColor = "#16a34a";
  }

  return (
    <>
      <div className="surface" style={{ padding: 24, borderRadius: 14 }}
           data-testid="wa-qr-view">
        <div style={{
          display: "grid",
          gridTemplateColumns: `${QR_SIZE + RING_STROKE * 4 + 20}px 1fr`,
          gap: 28, alignItems: "center", flexWrap: "wrap",
        }}>
          {/* ---------- Bloco do QR com ring countdown ---------- */}
          <div style={{
            position: "relative",
            width: QR_SIZE + RING_STROKE * 4,
            height: QR_SIZE + RING_STROKE * 4,
            margin: "0 auto",
          }}>
            {/* Ring SVG */}
            {qr && (
              <svg width={QR_SIZE + RING_STROKE * 4}
                   height={QR_SIZE + RING_STROKE * 4}
                   style={{ position: "absolute", inset: 0, transform: "rotate(-90deg)" }}>
                <circle cx={(QR_SIZE + RING_STROKE * 4) / 2}
                        cy={(QR_SIZE + RING_STROKE * 4) / 2}
                        r={RING_R}
                        stroke="rgba(148,163,184,0.18)"
                        strokeWidth={RING_STROKE}
                        fill="none" />
                <circle cx={(QR_SIZE + RING_STROKE * 4) / 2}
                        cy={(QR_SIZE + RING_STROKE * 4) / 2}
                        r={RING_R}
                        stroke={ringColor}
                        strokeWidth={RING_STROKE}
                        strokeLinecap="round"
                        fill="none"
                        strokeDasharray={RING_C}
                        strokeDashoffset={RING_C * (1 - pctLeft)}
                        style={{
                          transition: "stroke-dashoffset .8s linear, stroke .3s",
                          filter: willExpire ? "drop-shadow(0 0 6px #dc262688)" : "none",
                        }} />
              </svg>
            )}

            {/* Card QR central */}
            <div style={{
              position: "absolute",
              top: RING_STROKE * 2, left: RING_STROKE * 2,
              width: QR_SIZE, height: QR_SIZE,
              borderRadius: 18,
              background: "#fff",
              padding: 12,
              display: "grid", placeItems: "center",
              border: "1px solid rgba(15,23,42,.08)",
              boxShadow: "0 8px 32px rgba(15,23,42,.06)",
              overflow: "hidden",
              cursor: qr ? "zoom-in" : "default",
              transition: "transform .2s",
            }}
                 onClick={() => qr && setFullscreen(true)}
                 onMouseEnter={(e) => { if (qr) e.currentTarget.style.transform = "scale(1.012)"; }}
                 onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; }}>
              {qr ? (
                <>
                  <img src={qr} alt="WhatsApp QR Code" data-testid="wa-qr-image"
                       style={{
                         width: "100%", height: "100%", objectFit: "contain",
                         opacity: qrPulse ? 0.65 : 1,
                         transform: qrPulse ? "scale(.985)" : "scale(1)",
                         transition: "opacity .35s ease, transform .35s ease",
                         imageRendering: "pixelated",
                       }} />
                  {/* Indicador de hover/expand */}
                  <div style={{
                    position: "absolute", top: 10, right: 10,
                    width: 28, height: 28, borderRadius: 8,
                    background: "rgba(15,23,42,.78)", color: "#fff",
                    display: "grid", placeItems: "center",
                    pointerEvents: "none",
                    opacity: .85,
                  }}>
                    <Maximize2 size={14} />
                  </div>
                </>
              ) : (
                <div style={{ textAlign: "center", color: "#475569" }}
                     data-testid="wa-qr-loading">
                  <div style={{
                    width: 64, height: 64, borderRadius: 16,
                    background: "linear-gradient(135deg, #25d36622, #25d36608)",
                    margin: "0 auto 12px",
                    display: "grid", placeItems: "center",
                    animation: "wa-pulse 1.6s ease-in-out infinite",
                  }}>
                    <QrCode size={32} strokeWidth={1.6} style={{ color: "#25d366" }} />
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
                    Inicializando WhatsApp…
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                    Aguarde alguns segundos para o QR Code aparecer
                  </div>
                </div>
              )}
            </div>

            {/* Badge countdown abaixo do QR */}
            {qr && remainingSec != null && (
              <div data-testid="wa-qr-countdown" style={{
                position: "absolute",
                bottom: -10,
                left: "50%",
                transform: "translateX(-50%)",
                background: ringColor,
                color: "#fff",
                fontSize: 11,
                fontWeight: 800,
                padding: "4px 12px",
                borderRadius: 999,
                letterSpacing: 0.4,
                boxShadow: "0 4px 12px rgba(15,23,42,.18)",
                display: "inline-flex", alignItems: "center", gap: 5,
                animation: willExpire ? "wa-pulse 1s ease-in-out infinite" : "none",
              }}>
                <span className="mono">{remainingSec}s</span>
                <span style={{ opacity: .85 }}>· {willExpire ? "expirando" : "válido"}</span>
              </div>
            )}
          </div>

          {/* ---------- Instruções ---------- */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
              <Smartphone size={20} strokeWidth={1.75} style={{ color: "#25d366" }} />
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, letterSpacing: "-0.012em" }}>
                Como conectar
              </h3>
            </div>

            <ol style={{
              paddingLeft: 22, margin: 0, fontSize: 13, lineHeight: 1.85,
              color: "var(--text-primary)",
            }}>
              <li>Abra o <strong>WhatsApp</strong> no seu celular</li>
              <li>Toque em <strong>Mais opções</strong> (⋮) ou <strong>Configurações</strong></li>
              <li>Toque em <strong>Aparelhos conectados</strong></li>
              <li>Toque em <strong>Conectar um aparelho</strong></li>
              <li>Aponte a câmera para o <strong>QR Code ao lado</strong></li>
            </ol>

            <div style={{ marginTop: 14, fontSize: 12, color: subColor,
                            fontWeight: willExpire ? 800 : 600,
                            display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%",
                background: ringColor,
                animation: willExpire ? "wa-pulse 1s ease-in-out infinite" : "none",
              }} />
              {subLabel}
            </div>

            {lastQrAt && (
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
                Gerado às <span className="mono">{new Date(lastQrAt).toLocaleTimeString("pt-BR")}</span>
              </div>
            )}

            {/* Mensagens de erro amigáveis */}
            {isAuthErr && (
              <div data-testid="wa-qr-auth-error" style={{
                marginTop: 14, padding: 12, borderRadius: 10,
                background: "rgba(220,38,38,.08)",
                border: "1px solid rgba(220,38,38,.25)",
                fontSize: 12, color: "#b91c1c",
                display: "flex", alignItems: "flex-start", gap: 8,
              }}>
                <ShieldCheck size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                <div>
                  <strong>Sessão expirada.</strong> Faça login novamente para acessar a conexão WhatsApp.
                  <div style={{ marginTop: 6 }}>
                    <button onClick={() => { try { localStorage.removeItem("token"); } catch { /* ignore */ } ; window.location.reload(); }}
                            style={{ ...btnInlineStyle("danger") }}
                            data-testid="wa-qr-relogin-btn">
                      Fazer login
                    </button>
                  </div>
                </div>
              </div>
            )}

            {isSidecarErr && (
              <div data-testid="wa-qr-sidecar-error" style={{
                marginTop: 14, padding: 12, borderRadius: 10,
                background: "rgba(245,158,11,.10)",
                border: "1px solid rgba(245,158,11,.30)",
                fontSize: 12, color: "#92400e",
                display: "flex", alignItems: "flex-start", gap: 8,
              }}>
                <WifiOff size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                <div>
                  <strong>Serviço WhatsApp indisponível.</strong> Reconectando ao servidor…
                </div>
              </div>
            )}

            <div style={{ marginTop: 18, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button onClick={onRefresh} disabled={busy}
                      data-testid="wa-refresh-btn"
                      style={btnInlineStyle("primary")}>
                <RefreshCw size={13}
                            style={{ animation: busy ? "wa-spin 1s linear infinite" : "none" }} />
                Gerar novo QR
              </button>
              {qr && (
                <button onClick={() => setFullscreen(true)}
                        data-testid="wa-fullscreen-btn"
                        style={btnInlineStyle("ghost")}>
                  <Maximize2 size={13} /> Ampliar
                </button>
              )}
              {status === "connecting" && (
                <div style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "8px 12px",
                  fontSize: 11, color: "var(--text-muted)",
                  background: "var(--bg-surface-2)", borderRadius: 8,
                }}>
                  <Loader2 size={12} style={{ animation: "wa-spin 1.2s linear infinite" }} />
                  Aguardando escaneamento…
                </div>
              )}
              {onForceReset && (
                <button onClick={onForceReset} disabled={busy}
                        data-testid="wa-force-reset-btn"
                        title="Logout destrutivo + limpa creds + força novo QR (use se travado no QR)"
                        style={{
                          ...btnInlineStyle("ghost"),
                          borderColor: "rgba(220,38,38,.45)",
                          color: "#ef4444",
                        }}>
                  <AlertTriangle size={13} />
                  Force Reset
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ---------- Modal Fullscreen ---------- */}
      {fullscreen && qr && (
        <div data-testid="wa-qr-fullscreen"
             onClick={() => setFullscreen(false)}
             style={{
               position: "fixed", inset: 0, zIndex: 9999,
               background: "rgba(2,6,23,.86)",
               display: "grid", placeItems: "center",
               cursor: "zoom-out",
               animation: "wa-fade-in .2s ease-out",
             }}>
          <button onClick={() => setFullscreen(false)}
                  data-testid="wa-qr-fullscreen-close"
                  style={{
                    position: "absolute", top: 24, right: 24,
                    width: 40, height: 40, borderRadius: 12,
                    background: "rgba(255,255,255,.12)", color: "#fff",
                    border: "1px solid rgba(255,255,255,.22)",
                    cursor: "pointer", display: "grid", placeItems: "center",
                    backdropFilter: "blur(8px)",
                  }}>
            <X size={20} />
          </button>
          <div onClick={(e) => e.stopPropagation()}
               style={{
                 background: "#fff",
                 padding: 24,
                 borderRadius: 24,
                 boxShadow: "0 24px 80px rgba(0,0,0,.45)",
                 textAlign: "center",
               }}>
            <img src={qr} alt="QR" data-testid="wa-qr-fullscreen-image"
                 style={{ width: "min(70vh, 70vw)", height: "min(70vh, 70vw)",
                          imageRendering: "pixelated" }} />
            <div style={{ marginTop: 14, fontSize: 13, color: "#475569" }}>
              Aponte seu celular para o QR Code · clique fora para fechar
            </div>
            {remainingSec != null && (
              <div style={{
                marginTop: 10, fontSize: 13, fontWeight: 800,
                color: ringColor,
              }}>
                <span className="mono">{remainingSec}s</span> restantes
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/** Botão inline reutilizável dentro do painel WhatsApp */
function btnInlineStyle(tone) {
  const palettes = {
    primary: { bg: "#25d366", fg: "#fff", border: "transparent" },
    ghost:   { bg: "var(--bg-surface-2)", fg: "var(--text-primary)", border: "var(--border-default)" },
    danger:  { bg: "#dc2626", fg: "#fff", border: "transparent" },
  };
  const p = palettes[tone] || palettes.ghost;
  return {
    display: "inline-flex", alignItems: "center", gap: 6,
    padding: "8px 14px", fontSize: 12, fontWeight: 700,
    background: p.bg, color: p.fg,
    border: `1px solid ${p.border}`,
    borderRadius: 8, cursor: "pointer",
    transition: "transform .12s ease, box-shadow .12s ease",
  };
}

function ConnectedView({ phoneNumber, me, onLogout, onForceReset, busy }) {
  return (
    <div style={{ display: "grid", gap: 14 }} data-testid="wa-connected-view">
      <div className="surface" style={{
        padding: 22, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(22,163,74,.14) 0%, var(--bg-surface) 60%)",
        border: "1px solid #16a34a55",
        position: "relative", overflow: "hidden",
      }}>
        {/* Glow decorativo */}
        <div style={{
          position: "absolute", top: -40, right: -40,
          width: 160, height: 160, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(22,163,74,.22) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />
        <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap",
                       position: "relative" }}>
          <div style={{
            width: 56, height: 56, borderRadius: 16,
            background: "linear-gradient(135deg, #16a34a, #0f9d58)",
            display: "grid", placeItems: "center",
            boxShadow: "0 8px 24px rgba(22,163,74,.35)",
            animation: "wa-success-pop .55s cubic-bezier(.34,1.56,.64,1) both",
          }}>
            <CheckCircle2 size={30} strokeWidth={2.2} style={{ color: "#fff" }} />
          </div>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 800, color: "#15803d",
                              textTransform: "uppercase", letterSpacing: 0.8 }}>
                Conectado como
              </span>
              <span style={{
                width: 7, height: 7, borderRadius: "50%",
                background: "#22c55e",
                boxShadow: "0 0 8px #22c55e",
                animation: "wa-pulse 2s ease-in-out infinite",
              }} />
            </div>
            <div data-testid="wa-connected-phone"
                 className="mono"
                 style={{ fontSize: 22, fontWeight: 800, marginTop: 4,
                            letterSpacing: "-0.01em", color: "#0f172a" }}>
              +{phoneNumber || "—"}
            </div>
            {me?.name && (
              <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 2 }}>
                {me.name}
              </div>
            )}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onLogout} disabled={busy}
                  data-testid="wa-logout-btn"
                  style={{
                    color: "#dc2626",
                    border: "1px solid #fecaca",
                    background: "rgba(255,255,255,.7)",
                  }}>
            <LogOut size={13} /> Desconectar
          </button>
          {onForceReset && (
            <button className="btn btn-ghost btn-sm" onClick={onForceReset} disabled={busy}
                    data-testid="wa-force-reset-btn"
                    title="Logout destrutivo + limpa creds + força novo QR"
                    style={{
                      color: "#dc2626",
                      border: "1px solid #fecaca",
                      background: "rgba(255,255,255,.7)",
                    }}>
              <AlertTriangle size={13} /> Force Reset
            </button>
          )}
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

