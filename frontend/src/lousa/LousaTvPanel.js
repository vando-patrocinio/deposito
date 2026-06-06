/* LousaTvPanel — Lousa replicada na SmartTV.
 *
 * Modo público via ?portal=lousa-tv&t=<tv_token>.
 *
 * iter215ai (2026-06): Layout dividido:
 *  - Esquerda (~78%): grade da Lousa (técnicos × slots de horário × bolhas)
 *  - Direita (~22%): Histórico de Ações rolando em tempo real
 *  - Topo: header thin com brand + KPIs + relógio + áudio
 *
 * Atualiza grade a cada 20s, histórico a cada 15s.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { Wrench, Settings, ArrowUpRight, Star, Shield, Tag, Zap,
         AlertTriangle, User, MapPin, Volume2, Bell, Radio, Play,
         Plus, X, ArrowLeftRight, Check, Calendar, RotateCcw } from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const REFRESH_GRID_MS = 20_000;
const REFRESH_LOGS_MS = 15_000;

const PALETTE = {
  bg: "#f4f5f8",
  panel: "#ffffff",
  panelAlt: "#fafbfc",
  ink: "#1f2933",
  inkSoft: "#5f6b7a",
  inkMuted: "#8a94a3",
  border: "#e2e8f0",
  brand: "#4b1d7a",
  brandSoft: "#f3eafd",
  secondary: "#f28c28",
  secondarySoft: "#fef3e2",
  success: "#237a4b",
  successSoft: "#dcf2e4",
  warning: "#9a6700",
  warningSoft: "#fff4d6",
  danger: "#b42318",
  dangerSoft: "#fde8e6",
  info: "#1d4ed8",
  infoSoft: "#eaf0ff",
};

const TYPE_META = {
  reparo: { icon: Wrench, label: "Reparo", color: PALETTE.info },
  instalacao: { icon: Settings, label: "Instalação", color: PALETTE.brand },
  retirada: { icon: ArrowUpRight, label: "Retirada", color: PALETTE.inkSoft },
  prioridade: { icon: Star, label: "Prioridade", color: PALETTE.secondary },
  preventiva: { icon: Shield, label: "Preventiva", color: PALETTE.success },
  venda: { icon: Tag, label: "Venda", color: PALETTE.brand },
  rompimento: { icon: Zap, label: "Rompimento", color: PALETTE.danger },
  alerta_geofence: { icon: AlertTriangle, label: "Geofence", color: PALETTE.danger },
};

const ACTION_META = {
  criada: { icon: Plus, label: "Criada", color: PALETTE.info },
  aberta: { icon: Play, label: "Iniciada", color: PALETTE.success },
  finalizada: { icon: Check, label: "Finalizada", color: PALETTE.success },
  encerrar: { icon: X, label: "Encerrada", color: PALETTE.inkMuted },
  reagendar: { icon: Calendar, label: "Reagendada", color: PALETTE.info },
  cancelar: { icon: X, label: "Cancelada", color: PALETTE.danger },
  transferida: { icon: ArrowLeftRight, label: "Transferida", color: PALETTE.success },
};

const AI_AGENTS = {
  isabella: "Isabella", alvaro: "Álvaro", camila: "Camila",
};
function detectAgent(origin) {
  const o = (origin || "").toLowerCase();
  for (const k of Object.keys(AI_AGENTS)) if (o.includes(k)) return AI_AGENTS[k];
  return null;
}

function bubbleBorder(t) {
  const ttype = t.type || "reparo";
  if (ttype === "alerta_geofence") return PALETTE.danger;
  if (ttype === "rompimento") return PALETTE.brand;
  const origin = (t.origin_source || "").toLowerCase();
  if (origin.includes("isabella") || origin.includes("alvaro")
      || origin.includes("camila") || origin === "ai_agent") return PALETTE.success;
  if (t.priority === "horario" || t.scheduled_time) return PALETTE.secondary;
  return PALETTE.info;
}

function slaPulse(t, slaMap) {
  const sla = (slaMap || {})[t.type || "reparo"] || 60;
  const opened = t.opened_at || t.created_at;
  if (!opened || t.status !== "aberta") return "none";
  const ageMin = (Date.now() - new Date(opened).getTime()) / 60000;
  if (ageMin > sla) return "overdue";
  if (ageMin > sla * 0.8) return "warn";
  return "ok";
}

function fmtClock(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("pt-BR",
      { hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}
function fmtRelative(iso) {
  if (!iso) return "—";
  try {
    const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (min < 1) return "agora";
    if (min < 60) return `${min}min`;
    const h = Math.floor(min / 60), m = min % 60;
    return `${h}h${m > 0 ? `${String(m).padStart(2, "0")}` : ""}`;
  } catch { return "—"; }
}

// ── Audio engine (mantido) ─────────────────────────────────────────────────
function useAudioEngine() {
  const ctxRef = useRef(null);
  const enabledRef = useRef(false);
  function ensure() {
    if (ctxRef.current) return ctxRef.current;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    ctxRef.current = new Ctx();
    return ctxRef.current;
  }
  function enable() { enabledRef.current = true; ensure(); }
  function beep(freq = 800, durMs = 200) {
    if (!enabledRef.current) return;
    const ctx = ensure(); if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine"; osc.frequency.value = freq;
    osc.connect(gain); gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + durMs / 1000);
    osc.start(); osc.stop(ctx.currentTime + durMs / 1000 + 0.05);
  }
  function speak(text) {
    if (!enabledRef.current) return;
    if (!window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "pt-BR"; u.rate = 0.95; u.pitch = 1.0; u.volume = 1.0;
    window.speechSynthesis.speak(u);
  }
  return { enable, beep, speak };
}

// ── Página principal ───────────────────────────────────────────────────────
export default function LousaTvPanel() {
  const params = new URLSearchParams(window.location.search);
  const initialToken = params.get("t") || "";
  const [token, setToken] = useState(initialToken);
  const [tokenInput, setTokenInput] = useState("");
  const [data, setData] = useState(null);
  const [logs, setLogs] = useState([]);
  const [err, setErr] = useState("");
  // iter215aj — Áudio LIGADO por padrão. O AudioContext exige um gesto
  // do usuário pra ser inicializado (autoplay policy do browser), então
  // anexamos UM listener global que ativa o contexto no primeiro toque/clique.
  const [audioEnabled, setAudioEnabled] = useState(true);
  const audio = useAudioEngine();
  useEffect(() => {
    if (!audioEnabled) return;
    let armed = true;
    const onAnyGesture = () => {
      if (!armed) return;
      armed = false;
      try { audio.enable(); } catch { /* ignore */ }
      window.removeEventListener("click", onAnyGesture);
      window.removeEventListener("touchstart", onAnyGesture);
      window.removeEventListener("keydown", onAnyGesture);
    };
    window.addEventListener("click", onAnyGesture);
    window.addEventListener("touchstart", onAnyGesture);
    window.addEventListener("keydown", onAnyGesture);
    return () => {
      window.removeEventListener("click", onAnyGesture);
      window.removeEventListener("touchstart", onAnyGesture);
      window.removeEventListener("keydown", onAnyGesture);
    };
  }, [audioEnabled, audio]);
  const seenOverdueRef = useRef(new Set());
  const seenGeofenceRef = useRef(new Set());

  // Fetch grade
  useEffect(() => {
    if (!token) return;
    let alive = true;
    async function load() {
      try {
        const r = await axios.get(
          `${BACKEND}/api/lousa/public/tv-grid/${encodeURIComponent(token)}`);
        if (!alive) return;
        setData(r.data); setErr("");
        const allTickets = [];
        for (const col of (r.data.columns || [])) {
          for (const slot of (col.slots || [])) {
            for (const t of (slot.tickets || [])) allTickets.push(t);
          }
          for (const t of (col.unscheduled || [])) allTickets.push(t);
        }
        const slaMap = r.data.sla_map || {};
        for (const t of allTickets) {
          const pulse = slaPulse(t, slaMap);
          if (pulse === "overdue" && !seenOverdueRef.current.has(t.id)) {
            seenOverdueRef.current.add(t.id);
            audio.beep(440, 600);
            audio.speak(`Atenção. Serviço atrasado de ${t.client_snapshot?.name || "cliente"}.`);
          }
          if (t.type === "alerta_geofence"
              && !seenGeofenceRef.current.has(t.id)) {
            seenGeofenceRef.current.add(t.id);
            audio.beep(880, 300);
            audio.beep(660, 300);
            audio.speak(`Alerta geofence: ${t.client_snapshot?.name || "técnico"} fora da área.`);
          }
        }
      } catch (e) {
        if (!alive) return;
        const msg = e?.response?.data?.detail || e.message;
        setErr(typeof msg === "string" ? msg : "Erro ao carregar lousa.");
      }
    }
    load();
    const it = setInterval(load, REFRESH_GRID_MS);
    return () => { alive = false; clearInterval(it); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Fetch logs
  useEffect(() => {
    if (!token) return;
    let alive = true;
    async function load() {
      try {
        const r = await axios.get(
          `${BACKEND}/api/lousa/public/tv-logs/${encodeURIComponent(token)}`);
        if (alive) setLogs(r.data?.items || []);
      } catch { /* ignore — logs são complemento */ }
    }
    load();
    const it = setInterval(load, REFRESH_LOGS_MS);
    return () => { alive = false; clearInterval(it); };
  }, [token]);

  const totals = useMemo(() => {
    if (!data) return { open: 0, scheduled: 0, overdue: 0, agents: 0 };
    let open = 0, scheduled = 0, overdue = 0;
    const slaMap = data.sla_map || {};
    for (const col of (data.columns || [])) {
      for (const slot of (col.slots || [])) {
        for (const t of (slot.tickets || [])) {
          if (t.status === "aberta") open++;
          if (t.scheduled_time) scheduled++;
          if (slaPulse(t, slaMap) === "overdue") overdue++;
        }
      }
    }
    const agents = (data.columns || []).filter((c) => c.clock_state?.is_online).length;
    return { open, scheduled, overdue, agents };
  }, [data]);

  if (!token) return <TokenLogin tokenInput={tokenInput}
                                   setTokenInput={setTokenInput}
                                   setToken={setToken} />;
  if (err) return <ErrorScreen err={err}/>;
  if (!data) return <LoadingScreen/>;

  return (
    <div style={tvWrap(PALETTE.bg, false)}>
      <Header
        audioEnabled={audioEnabled}
        onToggleAudio={() => {
          if (audioEnabled) {
            // Desliga
            setAudioEnabled(false);
          } else {
            // Re-liga
            audio.enable();
            setAudioEnabled(true);
          }
        }}
        cols={data.columns?.length || 0}
        totals={totals}
      />
      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) 360px",
        gap: 14, padding: "0 14px 14px", flex: 1, minHeight: 0,
      }}>
        {/* Grade da Lousa */}
        <GridArea data={data} />
        {/* Histórico de Ações lateral */}
        <LogsSidebar logs={logs} />
      </div>
      <PulseStyles />
    </div>
  );
}

function tvWrap(bg, center = true) {
  return {
    minHeight: "100vh", height: "100vh",
    width: "100vw", background: bg, color: PALETTE.ink,
    display: "flex", flexDirection: "column",
    alignItems: center ? "center" : "stretch",
    justifyContent: center ? "center" : "flex-start",
    padding: center ? 24 : 0, overflow: "hidden",
    fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif",
  };
}

function TokenLogin({ tokenInput, setTokenInput, setToken }) {
  return (
    <div style={tvWrap(PALETTE.bg)}>
      <div style={{
        background: PALETTE.panel, padding: 40, borderRadius: 18,
        maxWidth: 520, width: "100%",
        boxShadow: "0 12px 28px -10px rgba(31,41,51,0.10)",
        border: `1px solid ${PALETTE.border}`,
      }}>
        <h1 style={{ margin: 0, fontSize: 32, color: PALETTE.ink,
                      letterSpacing: "-0.02em", fontWeight: 700 }}>
          Lousa TV
        </h1>
        <p style={{ color: PALETTE.inkSoft, marginTop: 10, fontSize: 15, lineHeight: 1.6 }}>
          Informe o token da TV para conectar. O gestor obtém o token no painel administrativo (botão TV).
        </p>
        <input value={tokenInput} data-testid="tv-token-input"
          onChange={(e) => setTokenInput(e.target.value.trim())}
          placeholder="Cole o token aqui"
          style={{
            width: "100%", padding: 14, borderRadius: 10,
            border: `1px solid ${PALETTE.border}`,
            background: "#fff", color: PALETTE.ink, fontSize: 15,
            marginTop: 16, boxSizing: "border-box",
          }}/>
        <button data-testid="tv-token-connect"
          onClick={() => {
            if (tokenInput.length < 16) return;
            const url = new URL(window.location.href);
            url.searchParams.set("t", tokenInput);
            window.history.replaceState({}, "", url.toString());
            setToken(tokenInput);
          }}
          style={{
            width: "100%", marginTop: 14, padding: 14,
            borderRadius: 10, border: 0, background: PALETTE.brand,
            color: "white", fontSize: 16, fontWeight: 700, cursor: "pointer",
          }}>Conectar</button>
      </div>
    </div>
  );
}
function ErrorScreen({ err }) {
  return (
    <div style={tvWrap(PALETTE.bg)}>
      <div style={{
        color: PALETTE.danger, fontSize: 20, textAlign: "center",
        padding: 24, borderRadius: 12, background: PALETTE.dangerSoft,
        border: `1px solid ${PALETTE.danger}`, fontWeight: 600,
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <AlertTriangle size={26} strokeWidth={2.2}/> {err}
      </div>
    </div>
  );
}
function LoadingScreen() {
  return (
    <div style={tvWrap(PALETTE.bg)}>
      <div style={{ color: PALETTE.inkSoft, fontSize: 20, fontWeight: 600 }}>
        Carregando lousa…
      </div>
    </div>
  );
}

// ── Header ─────────────────────────────────────────────────────────────────
function Header({ audioEnabled, onToggleAudio, cols, totals }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 18,
      padding: "14px 18px",
      borderBottom: `1px solid ${PALETTE.border}`,
      background: PALETTE.panel,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 11,
          background: PALETTE.brand, color: "white",
          display: "grid", placeItems: "center",
          fontWeight: 800, letterSpacing: "-0.04em", fontSize: 16,
        }}>SP</div>
        <div>
          <div style={{
            fontSize: 18, fontWeight: 700, color: PALETTE.ink,
            letterSpacing: "-0.02em", lineHeight: 1,
          }}>Lousa Operacional</div>
          <div style={{ fontSize: 12, color: PALETTE.inkSoft, marginTop: 3 }}>
            {cols} colaborador{cols !== 1 ? "es" : ""} · atualiza a cada 20s
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginLeft: 20 }}>
        <Kpi label="Em aberto" value={totals.open} tone="info" />
        <Kpi label="Agendadas" value={totals.scheduled} tone="brand" />
        <Kpi label="Atrasadas" value={totals.overdue}
              tone={totals.overdue > 0 ? "danger" : "muted"} />
        <Kpi label="Online" value={totals.agents} tone="success" />
      </div>

      <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
        <ClockLive />
        {audioEnabled ? (
          <button data-testid="tv-disable-audio" onClick={onToggleAudio}
                  title="Desligar avisos sonoros + TTS"
                  style={{
                    padding: "8px 14px", borderRadius: 10,
                    background: PALETTE.successSoft, color: PALETTE.success,
                    fontSize: 12, fontWeight: 700,
                    display: "flex", alignItems: "center", gap: 6,
                    border: `1px solid ${PALETTE.success}40`,
                    cursor: "pointer",
                  }}>
            <Bell size={13} strokeWidth={2.5}/> Áudio ATIVO
            <span style={{
              color: PALETTE.inkSoft, fontSize: 10, marginLeft: 4,
              textTransform: "uppercase", letterSpacing: 0.5,
            }}>desligar</span>
          </button>
        ) : (
          <button data-testid="tv-enable-audio" onClick={onToggleAudio}
                  title="Ligar avisos sonoros + TTS"
                  style={{
                    padding: "10px 16px", borderRadius: 10, border: 0,
                    background: PALETTE.brand, color: "white",
                    fontWeight: 700, cursor: "pointer", fontSize: 13,
                    display: "flex", alignItems: "center", gap: 6,
                  }}>
            <Volume2 size={15} strokeWidth={2.5}/> Ligar áudio
          </button>
        )}
      </div>
    </div>
  );
}

function Kpi({ label, value, tone }) {
  const t = {
    info:    { bg: PALETTE.infoSoft, fg: PALETTE.info },
    brand:   { bg: PALETTE.brandSoft, fg: PALETTE.brand },
    success: { bg: PALETTE.successSoft, fg: PALETTE.success },
    danger:  { bg: PALETTE.dangerSoft, fg: PALETTE.danger },
    muted:   { bg: "#f1f5f9", fg: PALETTE.inkSoft },
  }[tone] || { bg: "#f1f5f9", fg: PALETTE.inkSoft };
  return (
    <div style={{
      background: t.bg, padding: "8px 14px", borderRadius: 10,
      display: "flex", flexDirection: "column", minWidth: 86,
    }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: t.fg,
        textTransform: "uppercase", letterSpacing: 0.6,
      }}>{label}</div>
      <div style={{
        fontSize: 22, fontWeight: 700, color: t.fg,
        lineHeight: 1, marginTop: 3, letterSpacing: "-0.02em",
      }}>{value}</div>
    </div>
  );
}

function ClockLive() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const i = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(i);
  }, []);
  return (
    <div style={{
      fontSize: 20, fontVariantNumeric: "tabular-nums",
      color: PALETTE.ink, fontWeight: 700,
      letterSpacing: "-0.02em",
      padding: "5px 12px", borderRadius: 10,
      background: PALETTE.panelAlt, border: `1px solid ${PALETTE.border}`,
    }}>
      {now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
    </div>
  );
}

// ── Grid Area (escala a grade pra ocupar bem a tela) ───────────────────────
function GridArea({ data }) {
  const cols = data.columns || [];
  return (
    <div style={{
      display: "grid", gap: 10, minWidth: 0,
      gridTemplateColumns: `repeat(${Math.max(1, cols.length)}, minmax(260px, 1fr))`,
      overflowX: "auto", overflowY: "hidden",
    }}>
      {cols.map((col, idx) => (
        <Column key={col.collaborator?.id || `col-${idx}`} col={col}
                  slaMap={data.sla_map || {}}
                  slots={data.grid?.slots || []} />
      ))}
    </div>
  );
}

function Column({ col, slaMap, slots }) {
  const c = col.collaborator || {};
  const slotted = col.slots || [];
  const isOnline = !!col.clock_state?.is_online;
  const totalTickets = slotted.reduce(
    (a, s) => a + (s.tickets || []).length, 0) + (col.unscheduled || []).length;
  return (
    <div style={{
      background: PALETTE.panel,
      borderRadius: 12, padding: 12,
      border: `1px solid ${PALETTE.border}`,
      boxShadow: "0 1px 3px rgba(31,41,51,0.04)",
      display: "flex", flexDirection: "column", gap: 6,
      minHeight: 0, overflow: "auto",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        paddingBottom: 10, borderBottom: `1px solid ${PALETTE.border}`,
      }}>
        <div style={{
          width: 38, height: 38, borderRadius: 11,
          background: PALETTE.brandSoft, color: PALETTE.brand,
          display: "grid", placeItems: "center",
          fontWeight: 800, position: "relative", fontSize: 15,
        }}>
          {(c.name || "?").charAt(0).toUpperCase()}
          <span style={{
            position: "absolute", bottom: -2, right: -2,
            width: 11, height: 11, borderRadius: "50%",
            background: isOnline ? PALETTE.success : PALETTE.inkMuted,
            border: `2px solid ${PALETTE.panel}`,
          }}/>
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{
            fontSize: 14, fontWeight: 700, color: PALETTE.ink,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            letterSpacing: "-0.01em",
          }}>{c.name || "—"}</div>
          <div style={{
            fontSize: 11, color: PALETTE.inkSoft, marginTop: 2,
            display: "flex", alignItems: "center", gap: 4,
          }}>
            <MapPin size={10} strokeWidth={2.4}/>
            {c.praca || c.cargo || "—"}
            {isOnline && (
              <span style={{
                marginLeft: 3, color: PALETTE.success, fontWeight: 700,
                display: "inline-flex", alignItems: "center", gap: 2,
              }}>
                <Radio size={9} strokeWidth={3}/> ON
              </span>
            )}
          </div>
        </div>
        <div style={{
          fontSize: 12, color: PALETTE.brand, fontWeight: 800,
          padding: "3px 10px", borderRadius: 999,
          background: PALETTE.brandSoft, minWidth: 28, textAlign: "center",
        }}>{totalTickets}</div>
      </div>

      {slots.length > 0 && slotted.map((s, idx) => (
        <SlotBlock key={s.label || `slot-${idx}`} slot={s} slaMap={slaMap} />
      ))}

      {totalTickets === 0 && (
        <div style={{
          color: PALETTE.inkMuted, fontSize: 12, padding: "20px 10px",
          textAlign: "center",
        }}>Sem serviços neste turno</div>
      )}
    </div>
  );
}

function SlotBlock({ slot, slaMap }) {
  const tickets = slot.tickets || [];
  if (tickets.length === 0) return null;
  return (
    <div>
      <div style={{
        fontSize: 10, color: PALETTE.inkSoft, padding: "6px 4px 4px",
        fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <span style={{ width: 3, height: 12, borderRadius: 2, background: PALETTE.brand }}/>
        {slot.label || "—"}
      </div>
      {tickets.map((t, idx) => (
        <Bubble key={t.id || `t-${idx}`} t={t} slaMap={slaMap} />
      ))}
    </div>
  );
}

function Bubble({ t, slaMap }) {
  const border = bubbleBorder(t);
  const pulse = slaPulse(t, slaMap);
  const cs = t.client_snapshot || {};
  const agent = detectAgent(t.origin_source);
  const meta = TYPE_META[t.type] || { icon: User, label: t.type || "OS", color: PALETTE.inkSoft };
  const Icon = meta.icon;
  let pulseClass = "";
  if (pulse === "overdue") pulseClass = "tv-pulse-overdue";
  if (t.type === "alerta_geofence") pulseClass = "tv-pulse-red";

  return (
    <div className={pulseClass} style={{
      background: PALETTE.panel, color: PALETTE.ink,
      borderRadius: 10, padding: "8px 10px", marginBottom: 6,
      borderLeft: `4px solid ${border}`,
      boxShadow: "0 1px 3px rgba(31,41,51,0.06)",
      border: `1px solid ${PALETTE.border}`,
      fontSize: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <span style={{
          width: 24, height: 24, borderRadius: 7,
          background: meta.color + "12", color: meta.color,
          display: "grid", placeItems: "center", flexShrink: 0,
        }}>
          <Icon size={13} strokeWidth={2.3} />
        </span>
        <span style={{
          fontWeight: 700, flex: 1, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap",
          color: PALETTE.ink, fontSize: 13,
          letterSpacing: "-0.01em",
        }}>{cs.name || "—"}</span>
        {agent && (
          <span style={{
            fontSize: 9, color: PALETTE.success,
            background: PALETTE.successSoft, padding: "1px 6px",
            borderRadius: 999, fontWeight: 700, whiteSpace: "nowrap",
          }}>IA · {agent}</span>
        )}
        {t.scheduled_time && (
          <span style={{
            fontSize: 10, color: PALETTE.secondary,
            background: PALETTE.secondarySoft,
            padding: "1px 7px", borderRadius: 999, fontWeight: 700,
            whiteSpace: "nowrap",
          }}>{fmtClock(t.scheduled_time)}</span>
        )}
      </div>
      <div style={{
        display: "flex", gap: 6, marginTop: 4, alignItems: "center",
        color: PALETTE.inkSoft, fontSize: 11, lineHeight: 1.3,
      }}>
        <span style={{
          color: meta.color, fontWeight: 700, fontSize: 10,
          textTransform: "uppercase", letterSpacing: 0.4,
        }}>{meta.label}</span>
        <span style={{ color: PALETTE.inkMuted }}>·</span>
        <span style={{
          flex: 1, whiteSpace: "nowrap", overflow: "hidden",
          textOverflow: "ellipsis",
        }}>
          {cs.address || "—"}{cs.neighborhood ? ` · ${cs.neighborhood}` : ""}
        </span>
      </div>
    </div>
  );
}

// ── Histórico de Ações lateral ─────────────────────────────────────────────
function LogsSidebar({ logs }) {
  return (
    <div style={{
      background: PALETTE.panel, borderRadius: 12, padding: 14,
      border: `1px solid ${PALETTE.border}`,
      boxShadow: "0 1px 3px rgba(31,41,51,0.04)",
      display: "flex", flexDirection: "column", minHeight: 0,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        paddingBottom: 12, borderBottom: `1px solid ${PALETTE.border}`,
      }}>
        <div style={{
          fontSize: 15, fontWeight: 700, color: PALETTE.ink,
          letterSpacing: "-0.01em",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <RotateCcw size={15} strokeWidth={2.4}/>
          Histórico de Ações
        </div>
        <span style={{
          fontSize: 11, color: PALETTE.brand, fontWeight: 700,
          background: PALETTE.brandSoft, padding: "3px 9px",
          borderRadius: 999,
        }}>{logs.length}</span>
      </div>
      <div style={{
        flex: 1, overflowY: "auto", marginTop: 10,
        display: "flex", flexDirection: "column", gap: 6,
        scrollBehavior: "smooth",
      }}>
        {logs.length === 0 && (
          <div style={{
            color: PALETTE.inkMuted, fontSize: 12,
            padding: "30px 10px", textAlign: "center",
          }}>Sem ações registradas hoje</div>
        )}
        {logs.map((l, idx) => <LogRow key={l.id || idx} log={l} />)}
      </div>
    </div>
  );
}

function LogRow({ log }) {
  const meta = ACTION_META[log.action]
            || { icon: User, label: log.action, color: PALETTE.inkSoft };
  const Icon = meta.icon;
  // Resumo do detalhe (1 linha)
  let detail = log.details || "";
  if (detail.length > 80) detail = detail.slice(0, 77) + "…";
  return (
    <div style={{
      padding: "8px 10px",
      borderLeft: `3px solid ${meta.color}`,
      background: PALETTE.panelAlt,
      borderRadius: 8, display: "flex", gap: 9, alignItems: "flex-start",
    }}>
      <span style={{
        width: 22, height: 22, borderRadius: 6,
        background: meta.color + "14", color: meta.color,
        display: "grid", placeItems: "center", flexShrink: 0, marginTop: 1,
      }}>
        <Icon size={12} strokeWidth={2.3}/>
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontSize: 12, fontWeight: 700, color: meta.color,
            letterSpacing: "-0.01em",
          }}>{meta.label}</span>
          <span style={{
            fontSize: 9, color: PALETTE.inkMuted, fontWeight: 600,
            textTransform: "uppercase", letterSpacing: 0.4,
          }}>{log.actor_role || "—"} · {log.actor_name || "—"}</span>
        </div>
        {detail && (
          <div style={{
            fontSize: 11, color: PALETTE.inkSoft, marginTop: 2,
            overflow: "hidden", textOverflow: "ellipsis",
            display: "-webkit-box", WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical", lineHeight: 1.35,
          }}>{detail}</div>
        )}
      </div>
      <span style={{
        fontSize: 10, color: PALETTE.inkMuted, fontWeight: 600,
        flexShrink: 0, whiteSpace: "nowrap", marginTop: 2,
      }}>{fmtRelative(log.at)}</span>
    </div>
  );
}

function PulseStyles() {
  return (
    <style>{`
      @keyframes tv-pulse-overdue-kf {
        0%, 100% { box-shadow: 0 1px 3px rgba(180,35,24,0.30); border-color: #b42318; }
        50% { box-shadow: 0 0 22px 4px rgba(180,35,24,0.45); border-color: #b42318; }
      }
      @keyframes tv-pulse-red-kf {
        0%, 100% { box-shadow: 0 1px 3px rgba(180,35,24,0.40); }
        50% { box-shadow: 0 0 22px 6px rgba(180,35,24,0.90); }
      }
      .tv-pulse-overdue { animation: tv-pulse-overdue-kf 1.4s ease-in-out infinite; }
      .tv-pulse-red { animation: tv-pulse-red-kf 0.9s ease-in-out infinite; }
    `}</style>
  );
}
