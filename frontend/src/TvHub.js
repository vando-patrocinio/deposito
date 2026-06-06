/* TvHub — Hub de telas públicas pra TV no escritório.
 *
 * URL pública sem auth:
 *   /tv?cid=co-demo                (default: rotaciona)
 *   /tv?cid=co-demo&mode=board     (Lousa Kanban)
 *   /tv?cid=co-demo&mode=isabella  (KPIs IA × humano)
 *   /tv?cid=co-demo&mode=finance   (Financeiro)
 *   /tv?cid=co-demo&mode=mural     (Mural de técnicos — usa LeaderboardMural)
 *   /tv?cid=co-demo&mode=rotate&interval=30
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ClipboardList, Bot, DollarSign, Trophy, Clock,
  AlertTriangle, MapPin, TrendingUp, CheckCircle2,
} from "lucide-react";
import LeaderboardMural from "@/LeaderboardMural";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

function useQuery() {
  return useMemo(() => {
    const p = new URLSearchParams(window.location.search);
    return {
      cid: p.get("cid") || "co-demo",
      mode: p.get("mode") || "rotate",
      interval: parseInt(p.get("interval") || "30", 10),
    };
  }, []);
}

const ROTATION_ORDER = ["board", "isabella", "finance", "mural"];

export default function TvHub() {
  const q = useQuery();
  const [activeMode, setActiveMode] = useState(
    q.mode === "rotate" ? ROTATION_ORDER[0] : q.mode
  );
  const [meta, setMeta] = useState({ name: "SmartProv", logo_url: null });

  // Auto-rotation
  useEffect(() => {
    if (q.mode !== "rotate") return;
    let i = 0;
    const t = setInterval(() => {
      i = (i + 1) % ROTATION_ORDER.length;
      setActiveMode(ROTATION_ORDER[i]);
    }, Math.max(10, q.interval) * 1000);
    return () => clearInterval(t);
  }, [q.mode, q.interval]);

  // Meta da empresa
  useEffect(() => {
    fetch(`${BACKEND}/api/tv/${q.cid}/meta`)
      .then((r) => r.json())
      .then(setMeta)
      .catch(() => {});
  }, [q.cid]);

  return (
    <div data-testid="tv-hub" style={{
      width: "100vw", height: "100vh", overflow: "hidden",
      background: "#0a0e1a", color: "#fff",
      fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
      display: "flex", flexDirection: "column",
    }}>
      <Header company={meta} mode={activeMode}
              isRotating={q.mode === "rotate"}
              onChange={setActiveMode} />
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {activeMode === "board" && <BoardScreen cid={q.cid} />}
        {activeMode === "isabella" && <IsabellaScreen cid={q.cid} />}
        {activeMode === "finance" && <FinanceScreen cid={q.cid} />}
        {activeMode === "mural" && <LeaderboardMural />}
      </div>
    </div>
  );
}

/* ============================ Header ============================ */
function Header({ company, mode, isRotating, onChange }) {
  const items = [
    { id: "board", label: "Quadro", icon: ClipboardList },
    { id: "isabella", label: "Isabella", icon: Bot },
    { id: "finance", label: "Financeiro", icon: DollarSign },
    { id: "mural", label: "Mural", icon: Trophy },
  ];
  return (
    <div style={{
      padding: "14px 28px",
      background: "linear-gradient(180deg, #111827, #0a0e1a)",
      borderBottom: "1px solid rgba(255,255,255,.08)",
      display: "flex", alignItems: "center", gap: 18, flexShrink: 0,
    }}>
      {company.logo_url ? (
        <img src={company.logo_url} alt={company.name}
             style={{ height: 38, width: "auto" }} />
      ) : (
        <div style={{
          width: 42, height: 42, borderRadius: 10,
          background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
          display: "grid", placeItems: "center",
          fontWeight: 800, fontSize: 18,
        }}>
          {(company.name || "S")[0]}
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: -0.5 }}>
          {company.name}
        </div>
        <div style={{ fontSize: 12, color: "rgba(255,255,255,.55)" }}>
          Painel ao vivo · {new Date().toLocaleDateString("pt-BR", {
            day: "2-digit", month: "long", year: "numeric",
          })}
        </div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        {items.map((it) => {
          const Ico = it.icon;
          const active = mode === it.id;
          return (
            <button key={it.id} onClick={() => onChange(it.id)}
                    data-testid={`tv-tab-${it.id}`}
                    style={{
                      padding: "8px 16px", borderRadius: 999,
                      border: active
                        ? "1px solid rgba(139,92,246,.6)"
                        : "1px solid rgba(255,255,255,.08)",
                      background: active
                        ? "linear-gradient(180deg, #8b5cf6, #6366f1)"
                        : "rgba(255,255,255,.05)",
                      color: "#fff", fontSize: 13, fontWeight: 700,
                      cursor: "pointer",
                      display: "inline-flex", alignItems: "center", gap: 6,
                    }}>
              <Ico size={14} /> {it.label}
            </button>
          );
        })}
      </div>
      {isRotating && <RotateBadge />}
      <Clock1 />
    </div>
  );
}

function RotateBadge() {
  return (
    <span style={{
      padding: "5px 11px", borderRadius: 999,
      background: "rgba(34,197,94,.15)", border: "1px solid rgba(34,197,94,.4)",
      color: "#86efac", fontSize: 11, fontWeight: 700,
      display: "inline-flex", alignItems: "center", gap: 5,
    }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%",
                      background: "#22c55e", boxShadow: "0 0 8px #22c55e" }} />
      ROTATING
    </span>
  );
}

function Clock1() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div style={{
      fontFamily: "ui-monospace, monospace",
      fontSize: 22, fontWeight: 700, color: "#fff",
      letterSpacing: 1,
    }}>
      {now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
    </div>
  );
}

/* ============================ BOARD (Kanban) ============================ */
function BoardScreen({ cid }) {
  const [data, setData] = useState(null);
  const reload = useCallback(() => {
    fetch(`${BACKEND}/api/tv/${cid}/board`).then((r) => r.json())
      .then(setData).catch(() => {});
  }, [cid]);
  useEffect(() => {
    reload();
    const t = setInterval(reload, 10000);
    return () => clearInterval(t);
  }, [reload]);

  if (!data) return <Loader label="Carregando quadro…" />;
  const COLS = [
    { id: "urgente",    label: "Urgente",    color: "#ef4444" },
    { id: "aguardando", label: "Aguardando", color: "#3b82f6" },
    { id: "em_rota",    label: "Em rota",    color: "#f59e0b" },
    { id: "atendendo",  label: "Atendendo",  color: "#22c55e" },
  ];

  return (
    <div data-testid="tv-board" style={{
      height: "100%", padding: "18px 28px",
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      {/* Top stats */}
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <BigStat label="Ativos agora"
                  value={data.active_total} color="#3b82f6" />
        <BigStat label="Finalizados hoje"
                  value={data.closed_today} color="#22c55e" />
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 13, color: "rgba(255,255,255,.5)" }}>
          atualizado {new Date(data.generated_at).toLocaleTimeString("pt-BR")}
        </span>
      </div>
      {/* Kanban */}
      <div style={{
        flex: 1, minHeight: 0,
        display: "grid",
        gridTemplateColumns: `repeat(${COLS.length}, 1fr)`,
        gap: 14,
      }}>
        {COLS.map((col) => {
          const items = data.columns[col.id] || [];
          return (
            <div key={col.id} data-testid={`tv-board-col-${col.id}`}
                  style={{
                    background: "rgba(255,255,255,.04)",
                    border: `1px solid ${col.color}33`,
                    borderTop: `3px solid ${col.color}`,
                    borderRadius: 12, padding: 14,
                    display: "flex", flexDirection: "column", gap: 10,
                    minHeight: 0,
                  }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <strong style={{ fontSize: 16, color: col.color }}>{col.label}</strong>
                <span style={{
                  marginLeft: "auto",
                  padding: "2px 10px", borderRadius: 999,
                  background: `${col.color}22`, color: col.color,
                  fontSize: 14, fontWeight: 800,
                }}>{items.length}</span>
              </div>
              <div style={{ flex: 1, overflowY: "auto",
                             display: "flex", flexDirection: "column", gap: 8 }}>
                {items.length === 0 ? (
                  <div style={{ padding: 20, textAlign: "center",
                                  color: "rgba(255,255,255,.3)", fontSize: 13 }}>
                    sem tickets
                  </div>
                ) : items.map((t) => (
                  <TicketCard key={t.id} t={t} accent={col.color} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TicketCard({ t, accent }) {
  return (
    <div data-testid={`tv-ticket-${t.id}`} style={{
      padding: 12,
      background: t.boss_mode
        ? "linear-gradient(135deg, rgba(239,68,68,.18), rgba(239,68,68,.05))"
        : "rgba(255,255,255,.03)",
      borderRadius: 10,
      border: t.boss_mode
        ? "1px solid rgba(239,68,68,.4)"
        : "1px solid rgba(255,255,255,.06)",
      animation: t.boss_mode ? "tv-pulse 1.6s ease-in-out infinite" : "none",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <strong style={{ fontSize: 14, flex: 1, color: "#fff",
                          letterSpacing: -0.2 }}>
          {t.subscriber_name}
        </strong>
        {t.minutes_open != null && (
          <span title="minutos desde abertura" style={{
            fontSize: 11, fontWeight: 700,
            color: t.minutes_open > 120 ? "#fca5a5" : "rgba(255,255,255,.5)",
          }}>
            <Clock size={10} style={{ marginRight: 3, verticalAlign: "middle" }} />
            {Math.floor(t.minutes_open)}m
          </span>
        )}
      </div>
      {t.subscriber_address && (
        <div style={{ fontSize: 11.5, color: "rgba(255,255,255,.55)",
                       marginTop: 4, display: "flex", alignItems: "center", gap: 4,
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
          <MapPin size={11} /> {t.subscriber_address}
        </div>
      )}
      <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          padding: "1px 7px", borderRadius: 4,
          background: `${accent}22`, color: accent,
          fontSize: 10, fontWeight: 700, textTransform: "uppercase",
          letterSpacing: 0.4,
        }}>
          {t.type}
        </span>
        {t.tech_name ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5,
                          fontSize: 11.5, color: "rgba(255,255,255,.75)",
                          marginLeft: "auto" }}>
            {t.tech_avatar ? (
              <img src={t.tech_avatar} alt="" width={18} height={18}
                   style={{ borderRadius: "50%", objectFit: "cover" }} />
            ) : (
              <span style={{ width: 18, height: 18, borderRadius: "50%",
                              background: "rgba(255,255,255,.1)" }} />
            )}
            {t.tech_name.split(" ")[0]}
          </span>
        ) : (
          <span style={{ fontSize: 11, color: "rgba(255,255,255,.4)",
                          marginLeft: "auto" }}>
            sem técnico
          </span>
        )}
      </div>
    </div>
  );
}

/* ============================ ISABELLA ============================ */
function IsabellaScreen({ cid }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    const reload = () => fetch(`${BACKEND}/api/tv/${cid}/isabella`)
      .then((r) => r.json()).then(setData).catch(() => {});
    reload();
    const t = setInterval(reload, 10000);
    return () => clearInterval(t);
  }, [cid]);
  if (!data) return <Loader label="Carregando KPIs Isabella…" />;
  const t = data.today, lb = data.live_buckets;
  return (
    <div data-testid="tv-isabella" style={{
      height: "100%", padding: "18px 28px",
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
        <BigStat label="Mensagens hoje" value={t.total.toLocaleString("pt-BR")}
                  color="#8b5cf6" big />
        <BigStat label="IA atendeu" value={`${t.ai_share_pct}%`}
                  color="#6366f1" sub={`${t.ai_replies} respostas`} big />
        <BigStat label="Vendas concluídas" value={t.sales_completed}
                  color="#22c55e" sub="Isabella → atendente" big />
      </div>
      {/* Buckets ao vivo */}
      <div style={{
        flex: 1, minHeight: 0,
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)", gap: 14,
      }}>
        <LiveBucket label="Com Isabella" value={lb.with_ai}
                     accent="#8b5cf6" />
        <LiveBucket label="⏳ Aguardando atendimento" value={lb.waiting}
                     accent="#f59e0b" pulse={lb.waiting > 0} />
        <LiveBucket label="Com humano" value={lb.with_human}
                     accent="#0ea5e9" />
      </div>
    </div>
  );
}

function LiveBucket({ label, value, accent, pulse }) {
  return (
    <div style={{
      padding: 28,
      background: "rgba(255,255,255,.04)",
      borderRadius: 16,
      border: `1px solid ${accent}33`,
      borderTop: `4px solid ${accent}`,
      display: "flex", flexDirection: "column", justifyContent: "center",
      alignItems: "center",
      animation: pulse ? "tv-pulse 1.6s ease-in-out infinite" : "none",
    }}>
      <div style={{ fontSize: 16, color: "rgba(255,255,255,.65)",
                     fontWeight: 600, marginBottom: 12 }}>
        {label}
      </div>
      <div style={{ fontSize: 96, fontWeight: 900, color: accent,
                     letterSpacing: -2, lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );
}

/* ============================ FINANCE ============================ */
function FinanceScreen({ cid }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    const reload = () => fetch(`${BACKEND}/api/tv/${cid}/finance`)
      .then((r) => r.json()).then(setData).catch(() => {});
    reload();
    const t = setInterval(reload, 30000);
    return () => clearInterval(t);
  }, [cid]);
  if (!data) return <Loader label="Carregando financeiro…" />;
  const fmt = (n) => "R$ " + n.toLocaleString("pt-BR",
                          { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (
    <div data-testid="tv-finance" style={{
      height: "100%", padding: "18px 28px",
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)",
                     gap: 14, flex: 1, minHeight: 0 }}>
        <BigCard
          icon={CheckCircle2}
          color="#22c55e"
          label="Pagas hoje"
          value={fmt(data.today.paid_total)}
          sub={`${data.today.paid_count} fatura${data.today.paid_count === 1 ? "" : "s"}`} />
        <BigCard
          icon={TrendingUp}
          color="#0ea5e9"
          label="Mês até hoje"
          value={fmt(data.month.paid_total)}
          sub={`${data.month.paid_count} faturas`} />
        <BigCard
          icon={Clock}
          color="#f59e0b"
          label="A vencer (3 dias)"
          value={fmt(data.upcoming_3d.total)}
          sub={`${data.upcoming_3d.count} faturas`} />
        <BigCard
          icon={AlertTriangle}
          color="#ef4444"
          label="Em atraso"
          value={fmt(data.overdue.total)}
          sub={`${data.overdue.count} faturas`}
          pulse={data.overdue.count > 0} />
      </div>
      {data.today.new_subscribers > 0 && (
        <div style={{
          padding: 18, borderRadius: 14,
          background: "linear-gradient(90deg, rgba(34,197,94,.18), rgba(34,197,94,.05))",
          border: "1px solid rgba(34,197,94,.3)",
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <div style={{ fontSize: 36 }}></div>
          <div>
            <div style={{ fontSize: 13, color: "rgba(255,255,255,.55)",
                           fontWeight: 600 }}>NOVAS ATIVAÇÕES HOJE</div>
            <div style={{ fontSize: 32, fontWeight: 900, color: "#86efac" }}>
              {data.today.new_subscribers} cliente{data.today.new_subscribers === 1 ? "" : "s"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================ Comp util ============================ */
function BigStat({ label, value, color, sub, big }) {
  return (
    <div style={{
      padding: big ? 20 : 14,
      background: "rgba(255,255,255,.04)",
      borderRadius: 12,
      borderLeft: `4px solid ${color}`,
      flex: 1,
    }}>
      <div style={{ fontSize: 12, color: "rgba(255,255,255,.55)",
                     fontWeight: 600, textTransform: "uppercase",
                     letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: big ? 48 : 28, fontWeight: 900, color,
                     letterSpacing: -1, marginTop: 4 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: "rgba(255,255,255,.5)",
                       marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function BigCard({ icon: Ico, label, value, sub, color, pulse }) {
  return (
    <div style={{
      padding: 28,
      background: "rgba(255,255,255,.04)",
      borderRadius: 16,
      border: `1px solid ${color}33`,
      borderTop: `4px solid ${color}`,
      display: "flex", flexDirection: "column", gap: 10,
      animation: pulse ? "tv-pulse 1.8s ease-in-out infinite" : "none",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Ico size={22} style={{ color }} />
        <div style={{ fontSize: 16, color: "rgba(255,255,255,.7)",
                       fontWeight: 700, textTransform: "uppercase",
                       letterSpacing: 0.5 }}>
          {label}
        </div>
      </div>
      <div style={{ fontSize: 60, fontWeight: 900, color,
                     letterSpacing: -1.5, lineHeight: 1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 14, color: "rgba(255,255,255,.55)",
                       fontWeight: 600 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function Loader({ label }) {
  return (
    <div style={{ height: "100%", display: "grid", placeItems: "center",
                   color: "rgba(255,255,255,.4)" }}>
      {label}
    </div>
  );
}

/* keyframes injetados uma única vez */
if (typeof document !== "undefined" && !document.getElementById("tv-hub-css")) {
  const css = document.createElement("style");
  css.id = "tv-hub-css";
  css.textContent = `
    @keyframes tv-pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,.4); }
      50% { box-shadow: 0 0 0 12px rgba(239,68,68,0); }
    }
  `;
  document.head.appendChild(css);
}
