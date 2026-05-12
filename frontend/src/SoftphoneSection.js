/**
 * SoftphoneSection — Softphone WebRTC/SIP para chamadas via MagnusBilling/Asterisk.
 *
 * Arquitetura:
 *   - Biblioteca: JsSIP (SIP sobre WebSocket Secure + WebRTC para mídia)
 *   - Server: Asterisk com chan_pjsip + transport-wss (porta padrão 8089)
 *   - URL WSS: `wss://<sip_server>:8089/ws`
 *   - Credenciais: reaproveita `sip_username`, `sip_password`, `sip_server`
 *     já salvos no card MagnusBilling. Overrides ficam em localStorage.
 *
 * Pré-requisitos no servidor (MagnusBilling/Asterisk):
 *   - Endpoint pjsip com `webrtc=yes`, `transport=transport-wss`,
 *     `media_encryption=dtls`, `dtls_auto_generate_cert=yes`, `ice_support=yes`
 *   - HTTPS habilitado em /etc/asterisk/http.conf
 *   - Provedor (TudoVoIP) costuma já entregar isso pronto.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card } from "@/ui";
import { api } from "@/api";
import JsSIP from "jssip";
import {
  Phone, PhoneOff, PhoneCall, Mic, MicOff, Delete,
  CheckCircle2, AlertTriangle, RefreshCw, Settings as SettingsIcon,
  PhoneIncoming, PhoneOutgoing, Clock,
} from "lucide-react";

const LS_KEY = "softphone_sip_overrides_v1";

const STATUS_LABELS = {
  idle: { txt: "Desconectado", color: "#64748b", dot: "#94a3b8" },
  connecting: { txt: "Conectando…", color: "#0f766e", dot: "#fbbf24" },
  registered: { txt: "Registrado", color: "#15803d", dot: "#22c55e" },
  failed: { txt: "Falha de registro", color: "#b91c1c", dot: "#ef4444" },
  unregistered: { txt: "Não registrado", color: "#64748b", dot: "#94a3b8" },
};

function loadOverrides() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || "{}");
  } catch { return {}; }
}
function saveOverrides(o) { localStorage.setItem(LS_KEY, JSON.stringify(o)); }

function fmtDur(sec) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export default function SoftphoneSection() {
  const [creds, setCreds] = useState(null);          // SIP creds vindas do card MagnusBilling
  const [overrides, setOverrides] = useState(loadOverrides());
  const [status, setStatus] = useState("idle");
  const [showSettings, setShowSettings] = useState(false);
  const [error, setError] = useState("");
  const [dial, setDial] = useState("");
  const [activeCall, setActiveCall] = useState(null); // { dir, peer, startedAt, muted }
  const [callElapsed, setCallElapsed] = useState(0);
  const [cdr, setCdr] = useState([]);
  const [cdrLoading, setCdrLoading] = useState(false);

  const uaRef = useRef(null);
  const sessionRef = useRef(null);
  const audioRef = useRef(null);
  const tickRef = useRef(null);

  // ---- Carregar credenciais MagnusBilling ----
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await api.aihubIntegrations();
        const mb = (r.items || []).find((x) => x.type === "magnusbilling");
        if (!alive) return;
        const c = mb?.config || {};
        setCreds({
          sip_username: c.sip_username || "",
          sip_password: c.sip_password || "",
          sip_server: c.sip_server || "",
          sip_did: c.sip_did || "",
        });
      } catch {
        if (alive) setCreds({ sip_username: "", sip_password: "", sip_server: "" });
      }
    })();
    return () => { alive = false; };
  }, []);

  // ---- CDR (histórico) ----
  const loadCdr = useCallback(async () => {
    setCdrLoading(true);
    try {
      const r = await api.aihubMagnusCdr(40);
      setCdr(r.items || []);
    } catch { setCdr([]); }
    finally { setCdrLoading(false); }
  }, []);
  useEffect(() => { loadCdr(); }, [loadCdr]);

  // ---- Configuração efetiva (overrides têm prioridade) ----
  const eff = {
    username: overrides.username || creds?.sip_username || "",
    password: overrides.password || creds?.sip_password || "",
    server: overrides.server || creds?.sip_server || "",
    wssPort: overrides.wssPort || 8089,
    wssPath: overrides.wssPath || "/ws",
    realm: overrides.realm || overrides.server || creds?.sip_server || "",
  };
  const wssUrl = `wss://${eff.server}:${eff.wssPort}${eff.wssPath}`;
  const sipUri = `sip:${eff.username}@${eff.realm || eff.server}`;

  // ---- Conectar / desconectar ----
  const connect = useCallback(() => {
    if (!eff.username || !eff.password || !eff.server) {
      setError("Configure credenciais SIP no card MagnusBilling ou em Configurações avançadas.");
      return;
    }
    setError("");
    try {
      const socket = new JsSIP.WebSocketInterface(wssUrl);
      const ua = new JsSIP.UA({
        sockets: [socket],
        uri: sipUri,
        password: eff.password,
        register: true,
        session_timers: false,
        user_agent: "PontoIA-Softphone/1.0",
      });

      ua.on("connecting", () => setStatus("connecting"));
      ua.on("connected", () => setStatus("connecting"));
      ua.on("disconnected", () => setStatus("idle"));
      ua.on("registered", () => { setStatus("registered"); setError(""); });
      ua.on("unregistered", () => setStatus("unregistered"));
      ua.on("registrationFailed", (e) => {
        setStatus("failed");
        setError(`Registro falhou: ${e?.cause || "verifique credenciais/WSS"}`);
      });

      ua.on("newRTCSession", (data) => {
        const session = data.session;
        const direction = data.originator === "remote" ? "incoming" : "outgoing";
        const peer = (session.remote_identity?.uri?.user) || (data.request?.from?.uri?.user) || "—";
        sessionRef.current = session;
        setActiveCall({ direction, peer, startedAt: null, muted: false });

        session.on("peerconnection", (e) => {
          const pc = e.peerconnection;
          pc.addEventListener("track", (ev) => {
            if (audioRef.current && ev.streams[0]) {
              audioRef.current.srcObject = ev.streams[0];
              audioRef.current.play().catch(() => {});
            }
          });
        });
        session.on("accepted", () => {
          setActiveCall((c) => c ? { ...c, startedAt: Date.now() } : null);
        });
        session.on("ended", () => {
          sessionRef.current = null;
          setActiveCall(null);
          setCallElapsed(0);
          loadCdr();
        });
        session.on("failed", (e) => {
          sessionRef.current = null;
          setActiveCall(null);
          setCallElapsed(0);
          setError(`Chamada falhou: ${e?.cause || "desconhecido"}`);
        });
      });

      ua.start();
      uaRef.current = ua;
    } catch (e) {
      setError(`Erro ao iniciar UA: ${e?.message || e}`);
      setStatus("failed");
    }
  }, [eff.username, eff.password, eff.server, eff.realm, eff.wssPort, eff.wssPath, wssUrl, sipUri, loadCdr]);

  const disconnect = useCallback(() => {
    try { sessionRef.current?.terminate(); } catch {}
    try { uaRef.current?.stop(); } catch {}
    uaRef.current = null;
    sessionRef.current = null;
    setActiveCall(null);
    setStatus("idle");
  }, []);

  // ---- Timer da chamada ativa ----
  useEffect(() => {
    if (activeCall?.startedAt) {
      tickRef.current = setInterval(() => {
        setCallElapsed(Math.floor((Date.now() - activeCall.startedAt) / 1000));
      }, 1000);
      return () => clearInterval(tickRef.current);
    }
    setCallElapsed(0);
    return undefined;
  }, [activeCall?.startedAt]);

  // ---- Cleanup ao desmontar ----
  useEffect(() => () => {
    try { sessionRef.current?.terminate(); } catch {}
    try { uaRef.current?.stop(); } catch {}
  }, []);

  // ---- Ações de chamada ----
  function placeCall(number) {
    const num = (number || dial || "").trim();
    if (!num) return;
    if (!uaRef.current || status !== "registered") {
      setError("Conecte ao SIP antes de ligar.");
      return;
    }
    setError("");
    const target = `sip:${num}@${eff.realm || eff.server}`;
    const options = {
      mediaConstraints: { audio: true, video: false },
      pcConfig: { iceServers: overrides.iceStun ? [{ urls: overrides.iceStun }] : [{ urls: "stun:stun.l.google.com:19302" }] },
    };
    try {
      uaRef.current.call(target, options);
    } catch (e) {
      setError(`call() falhou: ${e?.message || e}`);
    }
  }
  function answer() {
    try {
      sessionRef.current?.answer({
        mediaConstraints: { audio: true, video: false },
        pcConfig: { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] },
      });
    } catch (e) { setError(`answer() falhou: ${e?.message || e}`); }
  }
  function hangup() {
    try { sessionRef.current?.terminate(); } catch {}
  }
  function toggleMute() {
    if (!sessionRef.current) return;
    if (activeCall?.muted) {
      sessionRef.current.unmute({ audio: true });
      setActiveCall((c) => ({ ...c, muted: false }));
    } else {
      sessionRef.current.mute({ audio: true });
      setActiveCall((c) => ({ ...c, muted: true }));
    }
  }
  function sendDtmf(digit) {
    if (sessionRef.current && activeCall) {
      try { sessionRef.current.sendDTMF(digit); } catch {}
    } else {
      setDial((d) => (d + digit).slice(0, 32));
    }
  }
  function backspace() { setDial((d) => d.slice(0, -1)); }

  // ---- Render ----
  if (!creds) {
    return <div style={{ padding: 24, color: "#64748b" }}>Carregando credenciais SIP…</div>;
  }
  const st = STATUS_LABELS[status] || STATUS_LABELS.idle;
  const inCall = !!activeCall;
  const inRinging = inCall && !activeCall.startedAt && activeCall.direction === "incoming";

  return (
    <div data-testid="softphone-section" style={{ display: "grid", gridTemplateColumns: "minmax(320px, 380px) 1fr", gap: 18 }}>
      {/* Coluna esquerda: status + dialer + controle */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Card>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.6 }}>
                SIP Softphone
              </div>
              <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a", marginTop: 2 }}>
                {eff.username || "—"}
              </div>
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                {eff.server ? wssUrl : "Sem servidor configurado"}
              </div>
            </div>
            <button
              data-testid="softphone-settings-btn"
              onClick={() => setShowSettings((v) => !v)}
              title="Configurações avançadas"
              style={{ background: "transparent", border: "1px solid #e2e8f0", padding: 8, borderRadius: 8, cursor: "pointer", color: "#475569" }}
            ><SettingsIcon size={16} /></button>
          </div>

          {/* Status + actions */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: "#f8fafc", borderRadius: 10, marginBottom: 12 }}>
            <span style={{ width: 9, height: 9, borderRadius: 999, background: st.dot, boxShadow: status === "registered" ? "0 0 0 4px rgba(34,197,94,.15)" : "none" }} />
            <span data-testid="softphone-status" style={{ fontSize: 13, fontWeight: 700, color: st.color }}>{st.txt}</span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
              {status === "registered" || status === "connecting"
                ? <Button onClick={disconnect} data-testid="softphone-disconnect" variant="ghost"><PhoneOff size={14} /> Encerrar</Button>
                : <Button onClick={connect} data-testid="softphone-connect"><PhoneCall size={14} /> Conectar</Button>}
            </div>
          </div>

          {error && (
            <div style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: 10, background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, color: "#b91c1c", fontSize: 12, marginBottom: 10 }}>
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span data-testid="softphone-error">{error}</span>
            </div>
          )}

          {showSettings && (
            <AdvancedSettings
              overrides={overrides}
              onSave={(o) => { setOverrides(o); saveOverrides(o); setShowSettings(false); }}
              onReset={() => { setOverrides({}); saveOverrides({}); setShowSettings(false); }}
              defaults={{ server: creds.sip_server, username: creds.sip_username, realm: creds.sip_server }}
            />
          )}

          {/* Dialer / chamada ativa */}
          {inCall ? (
            <ActiveCallView call={activeCall} elapsed={callElapsed}
                            onHangup={hangup} onMute={toggleMute}
                            onAnswer={answer} ringing={inRinging}
                            onDtmf={sendDtmf} />
          ) : (
            <Dialer dial={dial} setDial={setDial}
                    onPress={(d) => setDial((cur) => (cur + d).slice(0, 32))}
                    onBackspace={backspace}
                    onCall={() => placeCall()} canCall={status === "registered"} />
          )}
        </Card>

        <audio ref={audioRef} autoPlay data-testid="softphone-audio" style={{ display: "none" }} />
      </div>

      {/* Coluna direita: CDR + instruções */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Card>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: "#0f172a" }}>Histórico de chamadas</h3>
            <button onClick={loadCdr} disabled={cdrLoading} title="Atualizar"
                    style={{ background: "transparent", border: "1px solid #e2e8f0", padding: 6, borderRadius: 6, cursor: "pointer", color: "#475569" }}
                    data-testid="softphone-cdr-refresh">
              <RefreshCw size={14} className={cdrLoading ? "animate-spin" : ""} />
            </button>
          </div>
          <CdrList items={cdr} loading={cdrLoading} onDial={(num) => { setDial(num); }} />
        </Card>

        <Card>
          <h3 style={{ margin: "0 0 8px", fontSize: 14, fontWeight: 800, color: "#0f172a" }}>Pré-requisitos do servidor</h3>
          <div style={{ fontSize: 12, color: "#475569", lineHeight: 1.6 }}>
            • Asterisk/MagnusBilling com <strong>chan_pjsip</strong> e <code style={{ background: "#f1f5f9", padding: "1px 4px", borderRadius: 3 }}>transport-wss</code> ativo (porta padrão <strong>8089</strong>)<br />
            • Endpoint pjsip do ramal com <code style={{ background: "#f1f5f9", padding: "1px 4px", borderRadius: 3 }}>webrtc=yes</code>, <code style={{ background: "#f1f5f9", padding: "1px 4px", borderRadius: 3 }}>ice_support=yes</code>, <code style={{ background: "#f1f5f9", padding: "1px 4px", borderRadius: 3 }}>media_encryption=dtls</code><br />
            • HTTPS habilitado em <code style={{ background: "#f1f5f9", padding: "1px 4px", borderRadius: 3 }}>http.conf</code> com certificado válido<br />
            • Se WSS estiver em outra porta/path, ajuste em "Configurações avançadas".
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ============================================================ */
/* Subcomponentes                                                */
/* ============================================================ */

function Dialer({ dial, setDial, onPress, onBackspace, onCall, canCall }) {
  const KEYS = [
    ["1", ""], ["2", "ABC"], ["3", "DEF"],
    ["4", "GHI"], ["5", "JKL"], ["6", "MNO"],
    ["7", "PQRS"], ["8", "TUV"], ["9", "WXYZ"],
    ["*", ""], ["0", "+"], ["#", ""],
  ];
  return (
    <div>
      <input
        type="text"
        value={dial}
        onChange={(e) => setDial(e.target.value.replace(/[^0-9*#+]/g, ""))}
        placeholder="Digite o número"
        data-testid="softphone-input"
        style={{
          width: "100%", padding: "12px 14px", fontSize: 22, fontWeight: 700,
          textAlign: "center", border: "1px solid #e2e8f0", borderRadius: 10,
          letterSpacing: "0.04em", color: "#0f172a", background: "#fff",
        }}
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginTop: 12 }}>
        {KEYS.map(([k, sub]) => (
          <button key={k} onClick={() => onPress(k)} data-testid={`softphone-key-${k}`}
                  style={{
                    aspectRatio: "1.6 / 1", border: "1px solid #e2e8f0", background: "#fff",
                    borderRadius: 10, cursor: "pointer", display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center", color: "#0f172a", transition: "background 120ms",
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "#f1f5f9"}
                  onMouseLeave={(e) => e.currentTarget.style.background = "#fff"}>
            <span style={{ fontSize: 20, fontWeight: 700 }}>{k}</span>
            {sub && <span style={{ fontSize: 9, color: "#94a3b8", marginTop: 2, letterSpacing: 0.4 }}>{sub}</span>}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={onBackspace} data-testid="softphone-backspace" disabled={!dial}
                style={{ flex: "0 0 70px", background: "#f1f5f9", border: "1px solid #e2e8f0", borderRadius: 10, padding: 12, cursor: dial ? "pointer" : "not-allowed", opacity: dial ? 1 : 0.5 }}>
          <Delete size={18} />
        </button>
        <button onClick={onCall} disabled={!canCall || !dial} data-testid="softphone-call-btn"
                style={{
                  flex: 1, background: canCall && dial ? "#16a34a" : "#94a3b8", color: "#fff",
                  border: 0, borderRadius: 10, padding: "14px 0", fontSize: 14, fontWeight: 800,
                  cursor: canCall && dial ? "pointer" : "not-allowed", display: "flex",
                  alignItems: "center", justifyContent: "center", gap: 8,
                }}>
          <Phone size={18} /> Ligar
        </button>
      </div>
    </div>
  );
}

function ActiveCallView({ call, elapsed, onHangup, onMute, onAnswer, ringing, onDtmf }) {
  return (
    <div data-testid="softphone-active-call" style={{ background: "#0f172a", color: "#fff", borderRadius: 12, padding: 16, textAlign: "center" }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.6 }}>
        {call.direction === "incoming" ? <PhoneIncoming size={12} /> : <PhoneOutgoing size={12} />}
        {ringing ? "Chamada recebida" : call.direction === "incoming" ? "Em atendimento" : "Em ligação"}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, margin: "10px 0 4px", letterSpacing: 0.4 }}>{call.peer}</div>
      <div style={{ fontSize: 14, color: "#94a3b8" }}>
        {call.startedAt ? fmtDur(elapsed) : (ringing ? "tocando…" : "discando…")}
      </div>
      <div style={{ display: "flex", justifyContent: "center", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
        {ringing && (
          <button onClick={onAnswer} data-testid="softphone-answer"
                  style={{ background: "#16a34a", color: "#fff", border: 0, borderRadius: 999, width: 48, height: 48, cursor: "pointer", display: "grid", placeItems: "center" }}>
            <Phone size={20} />
          </button>
        )}
        {call.startedAt && (
          <button onClick={onMute} data-testid="softphone-mute"
                  style={{ background: call.muted ? "#fbbf24" : "#334155", color: "#fff", border: 0, borderRadius: 999, width: 48, height: 48, cursor: "pointer", display: "grid", placeItems: "center" }}>
            {call.muted ? <MicOff size={20} /> : <Mic size={20} />}
          </button>
        )}
        <button onClick={onHangup} data-testid="softphone-hangup"
                style={{ background: "#dc2626", color: "#fff", border: 0, borderRadius: 999, width: 48, height: 48, cursor: "pointer", display: "grid", placeItems: "center" }}>
          <PhoneOff size={20} />
        </button>
      </div>
      {call.startedAt && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6, marginTop: 14 }}>
          {["1","2","3","4","5","6","7","8","9","*","0","#"].map((k) => (
            <button key={k} onClick={() => onDtmf(k)} data-testid={`softphone-dtmf-${k}`}
                    style={{ background: "#1e293b", color: "#fff", border: 0, borderRadius: 6, padding: "8px 0", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
              {k}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function CdrList({ items, loading, onDial }) {
  if (loading) return <div style={{ padding: 16, color: "#64748b", fontSize: 13 }}>Carregando…</div>;
  if (!items.length) return <div style={{ padding: 16, color: "#94a3b8", fontSize: 13, textAlign: "center" }}>Nenhuma chamada registrada.</div>;
  return (
    <div style={{ maxHeight: 460, overflowY: "auto" }}>
      {items.map((c, i) => {
        const dst = c.dst || c.destination || c.callee || "—";
        const src = c.src || c.source || c.caller || "—";
        const dur = Number(c.billsec || c.duration || 0);
        const when = c.calldate || c.start || c.startTime || "";
        const status = (c.disposition || c.status || "").toUpperCase();
        const isAnswered = status === "ANSWERED" || status === "ANSWER";
        return (
          <div key={c.id || i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 4px", borderBottom: "1px solid #f1f5f9" }}>
            <span style={{ width: 26, height: 26, borderRadius: 999, background: isAnswered ? "#dcfce7" : "#fee2e2", display: "grid", placeItems: "center", color: isAnswered ? "#16a34a" : "#dc2626" }}>
              <PhoneOutgoing size={13} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: "#0f172a" }}>{dst}</div>
              <div style={{ fontSize: 11, color: "#64748b" }}>{when} · de {src} · {fmtDur(dur)} · {status || "—"}</div>
            </div>
            <button onClick={() => onDial(dst)} title="Discar"
                    style={{ background: "transparent", border: "1px solid #e2e8f0", borderRadius: 6, padding: 6, cursor: "pointer", color: "#475569" }}>
              <Phone size={13} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function AdvancedSettings({ overrides, defaults, onSave, onReset }) {
  const [s, setS] = useState({
    server: overrides.server || "",
    username: overrides.username || "",
    password: overrides.password || "",
    realm: overrides.realm || "",
    wssPort: overrides.wssPort || 8089,
    wssPath: overrides.wssPath || "/ws",
    iceStun: overrides.iceStun || "",
  });
  const inp = { width: "100%", padding: "8px 10px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, marginTop: 4 };
  const lbl = { fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.4 };
  return (
    <div style={{ padding: 12, background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: 10, marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 800, color: "#0f172a", marginBottom: 8 }}>Configurações avançadas (override)</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div><label style={lbl}>Servidor SIP (host)</label>
          <input style={inp} placeholder={defaults.server || "sip.tudovoip.com.br"} value={s.server} onChange={(e) => setS({ ...s, server: e.target.value })} data-testid="softphone-adv-server" />
        </div>
        <div><label style={lbl}>Realm / domínio</label>
          <input style={inp} placeholder={defaults.realm || "sip.tudovoip.com.br"} value={s.realm} onChange={(e) => setS({ ...s, realm: e.target.value })} />
        </div>
        <div><label style={lbl}>Usuário (ramal)</label>
          <input style={inp} placeholder={defaults.username || "1147099675"} value={s.username} onChange={(e) => setS({ ...s, username: e.target.value })} />
        </div>
        <div><label style={lbl}>Senha</label>
          <input style={inp} type="password" placeholder="••••••••" value={s.password} onChange={(e) => setS({ ...s, password: e.target.value })} />
        </div>
        <div><label style={lbl}>Porta WSS</label>
          <input style={inp} type="number" value={s.wssPort} onChange={(e) => setS({ ...s, wssPort: Number(e.target.value) || 8089 })} />
        </div>
        <div><label style={lbl}>Path WSS</label>
          <input style={inp} value={s.wssPath} onChange={(e) => setS({ ...s, wssPath: e.target.value })} />
        </div>
        <div style={{ gridColumn: "1 / -1" }}><label style={lbl}>STUN (opcional)</label>
          <input style={inp} placeholder="stun:stun.l.google.com:19302" value={s.iceStun} onChange={(e) => setS({ ...s, iceStun: e.target.value })} />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
        <Button variant="ghost" onClick={onReset} data-testid="softphone-adv-reset">Limpar overrides</Button>
        <Button onClick={() => onSave(s)} data-testid="softphone-adv-save"><CheckCircle2 size={14} /> Salvar</Button>
      </div>
    </div>
  );
}
