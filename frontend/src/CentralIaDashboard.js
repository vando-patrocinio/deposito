import React, { useCallback, useEffect, useState } from "react";
import {
  Activity, AlertTriangle, Award, BarChart3, Bot, Brain,
  Clock, Smile, Frown, Meh, Sparkles, TrendingDown, TrendingUp,
  User, Users, Zap, RefreshCw,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   Central IA Dashboard — KPIs + ranking + intents + alertas proativos
============================================================= */

const INTENT_LABELS = {
  venda_nova: "Venda Nova",
  suporte_lentidao: "Suporte / Lentidão",
  suporte_sem_sinal: "Sem Sinal",
  agendamento_visita: "Agendamento",
  fatura_segunda_via: "2ª Via Fatura",
  cancelamento: "Cancelamento",
  mudanca_plano: "Mudança de Plano",
  outros: "Outros",
};

const PERIODS = [
  { id: 1, label: "Hoje" },
  { id: 7, label: "7 dias" },
  { id: 30, label: "30 dias" },
];

function fmtSecs(s) {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return s < 3600 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h${m % 60}m`;
}

export default function CentralIaDashboard() {
  const [days, setDays] = useState(7);
  const [kpis, setKpis] = useState(null);
  const [attendants, setAttendants] = useState([]);
  const [intents, setIntents] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async () => {
    setRefreshing(true);
    try {
      const [k, a, i, al] = await Promise.all([
        api.centralIaKpis(days),
        api.centralIaAttendants(days),
        api.centralIaIntents(days),
        api.centralIaAlerts(),
      ]);
      setKpis(k); setAttendants(a.items || []); setIntents(i.items || []);
      setAlerts(al.items || []);
    } catch (e) {
      console.error(e);
    } finally { setLoading(false); setRefreshing(false); }
  }, [days]);

  useEffect(() => {
    reload();
    const id = setInterval(reload, 30000);
    return () => clearInterval(id);
  }, [reload]);

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
        <RefreshCw size={28} style={{ animation: "ci-spin 1s linear infinite" }} />
        <div style={{ marginTop: 10, fontSize: 13 }}>Carregando inteligência da Central IA...</div>
        <style>{`@keyframes ci-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  return (
    <div data-testid="central-ia-dashboard" style={{ display: "grid", gap: 16 }}>
      <style>{`@keyframes ci-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }`}</style>

      {/* Header + period toggle */}
      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, var(--accent-soft) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #0d9488, #06b6d4)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(13,148,136,.35)",
        }}>
          <Brain size={24} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, letterSpacing: "-0.02em" }}>
            Central IA — Inteligência de Atendimento
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            KPIs avaliados automaticamente pela IA · {kpis?.total_conversations || 0} conversas analisadas
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {PERIODS.map((p) => (
            <button key={p.id} onClick={() => setDays(p.id)}
                    data-testid={`ci-period-${p.id}`}
                    style={{
                      padding: "6px 14px", borderRadius: 999,
                      border: "1px solid var(--border-default)",
                      background: days === p.id ? "var(--accent)" : "var(--bg-surface)",
                      color: days === p.id ? "#fff" : "var(--text-primary)",
                      fontSize: 12, fontWeight: 700, cursor: "pointer",
                    }}>
              {p.label}
            </button>
          ))}
          <button onClick={reload} disabled={refreshing}
                  className="btn btn-ghost btn-sm" style={{ marginLeft: 6 }}
                  data-testid="ci-reload">
            <RefreshCw size={13}
                       style={{ animation: refreshing ? "ci-spin 1s linear infinite" : "none" }} />
          </button>
        </div>
      </div>

      {kpis?.no_data && (
        <div className="surface" style={{
          padding: 28, borderRadius: 12, textAlign: "center",
          color: "var(--text-muted)",
        }}>
          <Brain size={36} strokeWidth={1.5} style={{ opacity: 0.4 }} />
          <p style={{ marginTop: 12, fontSize: 13 }}>
            Sem conversas suficientes para avaliar ainda. <br />
            Conecte o WhatsApp e/ou aguarde algumas interações — a IA avalia
            cada conversa automaticamente a cada 5 minutos.
          </p>
        </div>
      )}

      {!kpis?.no_data && (
        <>
          {/* Cards de KPI */}
          <div style={{
            display: "grid", gap: 12,
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          }} data-testid="ci-kpi-cards">
            <KpiCard
              icon={Award} label="CSAT" value={kpis.csat_avg ?? "—"}
              suffix="/10" color="#0d9488"
              hint={kpis.csat_count ? `${kpis.csat_count} avaliações` : null}
              testid="ci-kpi-csat"
              trend={kpis.csat_avg >= 7 ? "up" : kpis.csat_avg && kpis.csat_avg < 5 ? "down" : null}
            />
            <KpiCard
              icon={Clock} label="FRT médio" value={fmtSecs(kpis.frt_avg_seconds)}
              color="#0ea5e9"
              hint={kpis.frt_p90_seconds ? `p90: ${fmtSecs(kpis.frt_p90_seconds)}` : null}
              testid="ci-kpi-frt"
              trend={kpis.frt_avg_seconds && kpis.frt_avg_seconds < 120 ? "up"
                : kpis.frt_avg_seconds && kpis.frt_avg_seconds > 600 ? "down" : null}
            />
            <KpiCard
              icon={Sparkles} label="FCR" value={`${kpis.fcr_rate ?? "—"}`}
              suffix="%" color="#a855f7"
              hint="resolução em 1 contato" testid="ci-kpi-fcr"
              trend={kpis.fcr_rate >= 60 ? "up" : kpis.fcr_rate && kpis.fcr_rate < 30 ? "down" : null}
            />
            <KpiCard
              icon={Bot} label="ARR (IA autônoma)" value={`${kpis.arr_rate ?? "—"}`}
              suffix="%" color="#f59e0b"
              hint="resolvidas só pela IA" testid="ci-kpi-arr"
              trend={kpis.arr_rate >= 70 ? "up" : null}
            />
            <KpiCard
              icon={Activity} label="Volume" value={kpis.total_conversations}
              color="#64748b"
              hint={`em ${kpis.days} dia${kpis.days > 1 ? "s" : ""}`}
              testid="ci-kpi-volume"
            />
          </div>

          {/* Sentiment + Intents — lado a lado */}
          <div style={{ display: "grid", gap: 12,
                         gridTemplateColumns: "1fr 1.2fr" }}>
            <SentimentCard sentiment={kpis.sentiment} total={kpis.total_conversations} />
            <IntentsCard intents={intents} />
          </div>

          {/* Ranking atendentes */}
          <AttendantsCard items={attendants} />
        </>
      )}

      {/* Alertas proativos */}
      <AlertsCard items={alerts} onReload={reload} />
    </div>
  );
}

/* ============================================================= */
function KpiCard({ icon: Icon, label, value, suffix, color, hint, trend, testid }) {
  return (
    <div className="surface" style={{
      padding: 16, borderRadius: 12,
      border: `1px solid ${color}33`,
      display: "flex", flexDirection: "column", gap: 8,
    }} data-testid={testid}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={14} strokeWidth={2} style={{ color }} />
        <span style={{ fontSize: 11, fontWeight: 800,
                       color: "var(--text-muted)", textTransform: "uppercase",
                       letterSpacing: 0.5 }}>
          {label}
        </span>
        {trend === "up" && <TrendingUp size={12} style={{ color: "#16a34a", marginLeft: "auto" }} />}
        {trend === "down" && <TrendingDown size={12} style={{ color: "#dc2626", marginLeft: "auto" }} />}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color: "var(--text-primary)",
                     letterSpacing: "-0.03em", display: "flex", alignItems: "baseline", gap: 3 }}>
        {value}
        {suffix && <span style={{ fontSize: 13, color: "var(--text-muted)", fontWeight: 600 }}>{suffix}</span>}
      </div>
      {hint && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{hint}</div>}
    </div>
  );
}

/* ============================================================= */
function SentimentCard({ sentiment, total }) {
  const items = [
    { id: "positivo", label: "Positivo", icon: Smile, color: "#16a34a", n: sentiment?.positivo || 0 },
    { id: "neutro",   label: "Neutro",   icon: Meh,   color: "#94a3b8", n: sentiment?.neutro || 0 },
    { id: "negativo", label: "Negativo", icon: Frown, color: "#dc2626", n: sentiment?.negativo || 0 },
  ];
  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}
         data-testid="ci-sentiment-card">
      <div style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
        Sentimento dos clientes
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {items.map((it) => {
          const pct = total ? (it.n / total * 100) : 0;
          const Ico = it.icon;
          return (
            <div key={it.id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Ico size={16} strokeWidth={1.75} style={{ color: it.color }} />
              <span style={{ fontSize: 12, minWidth: 70 }}>{it.label}</span>
              <div style={{ flex: 1, height: 8, borderRadius: 999,
                             background: "var(--bg-surface-2)", overflow: "hidden" }}>
                <div style={{
                  width: `${pct}%`, height: "100%", background: it.color,
                  transition: "width .4s",
                }} />
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, minWidth: 50,
                              textAlign: "right" }}>
                {it.n} <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                  ({Math.round(pct)}%)
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ============================================================= */
function IntentsCard({ intents }) {
  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}
         data-testid="ci-intents-card">
      <div style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
        Top motivos de contato
      </div>
      {intents.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 12 }}>
          Sem dados suficientes.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {intents.slice(0, 8).map((it, i) => (
            <div key={it.intent} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 700, minWidth: 20,
                              color: i < 3 ? "var(--accent)" : "var(--text-muted)" }}>
                #{i + 1}
              </span>
              <span style={{ fontSize: 12, flex: 1 }}>
                {INTENT_LABELS[it.intent] || it.intent}
              </span>
              <div style={{ width: 120, height: 6, borderRadius: 999,
                             background: "var(--bg-surface-2)", overflow: "hidden" }}>
                <div style={{ width: `${it.pct}%`, height: "100%",
                               background: "var(--accent)" }} />
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, minWidth: 36, textAlign: "right" }}>
                {it.count}
              </span>
              {it.csat_avg != null && (
                <span style={{ fontSize: 10, color: "var(--text-muted)", minWidth: 50, textAlign: "right" }}>
                  CSAT {it.csat_avg}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================= */
function AttendantsCard({ items }) {
  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}
         data-testid="ci-attendants-card">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <Users size={14} style={{ color: "var(--accent)" }} />
        <span style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
          Ranking de atendentes — IA vs Humanos
        </span>
      </div>
      {items.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 12 }}>
          Sem dados.
        </div>
      ) : (
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--text-muted)", fontSize: 10,
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
              <th style={th()}>Atendente</th>
              <th style={th("center")}>Volume</th>
              <th style={th("center")}>CSAT</th>
              <th style={th("center")}>FCR</th>
              <th style={th("center")}>FRT médio</th>
              <th style={th("center")}>Sentimento neg.</th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.user_id || a.name} style={{ borderTop: "1px solid var(--border-default)" }}>
                <td style={{ padding: "8px 4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {a.is_ai ? (
                      <div style={{
                        width: 28, height: 28, borderRadius: "50%",
                        background: "linear-gradient(135deg, #0d9488, #06b6d4)",
                        color: "#fff", display: "grid", placeItems: "center",
                      }}>
                        <Bot size={14} strokeWidth={2} />
                      </div>
                    ) : (
                      <div style={{
                        width: 28, height: 28, borderRadius: "50%",
                        background: a.avatar ? `url(${a.avatar}) center/cover` : "#94a3b8",
                        color: "#fff", display: "grid", placeItems: "center",
                        fontSize: 11, fontWeight: 700,
                      }}>
                        {!a.avatar && (a.name || "?")[0]?.toUpperCase()}
                      </div>
                    )}
                    <span style={{ fontWeight: 600 }}>{a.name}</span>
                    {a.is_ai && (
                      <span style={{ fontSize: 9, fontWeight: 800,
                                      background: "rgba(13,148,136,.15)", color: "#0d9488",
                                      padding: "1px 6px", borderRadius: 999 }}>
                        IA
                      </span>
                    )}
                  </div>
                </td>
                <td style={td("center")}>{a.volume}</td>
                <td style={{ ...td("center"), fontWeight: 700,
                              color: csatColor(a.csat_avg) }}>
                  {a.csat_avg ?? "—"}
                </td>
                <td style={td("center")}>{a.fcr_rate != null ? `${a.fcr_rate}%` : "—"}</td>
                <td style={td("center")}>{fmtSecs(a.frt_avg_seconds)}</td>
                <td style={td("center")}>
                  {a.negative_count > 0 && (
                    <span style={{ color: "#dc2626", fontWeight: 700 }}>
                      {a.negative_count}
                    </span>
                  ) || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function csatColor(v) {
  if (v == null) return "var(--text-muted)";
  if (v >= 8) return "#16a34a";
  if (v >= 6) return "#eab308";
  return "#dc2626";
}
function th(align = "left") {
  return { textAlign: align, padding: "8px 4px", fontWeight: 700 };
}
function td(align = "left") {
  return { textAlign: align, padding: "8px 4px" };
}

/* ============================================================= */
function AlertsCard({ items, onReload }) {
  if (!items || items.length === 0) {
    return (
      <div className="surface" style={{ padding: 16, borderRadius: 12 }}
           data-testid="ci-alerts-card">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <Zap size={14} style={{ color: "#16a34a" }} />
          <span style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            Alertas proativos
          </span>
        </div>
        <div style={{ fontSize: 12, color: "#16a34a", padding: "8px 0" }}>
          ✓ Nenhum alerta no momento — tudo sob controle.
        </div>
      </div>
    );
  }
  return (
    <div className="surface" style={{
      padding: 16, borderRadius: 12,
      border: "1px solid #f59e0b55",
    }} data-testid="ci-alerts-card">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <AlertTriangle size={14} style={{ color: "#f59e0b" }} />
        <span style={{ fontSize: 11, fontWeight: 800, color: "#f59e0b",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
          Alertas proativos ({items.length})
        </span>
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((a) => (
          <div key={a.id} style={{
            padding: "10px 12px", borderRadius: 8,
            background: a.severity === "critical" ? "rgba(220,38,38,.08)" : "rgba(245,158,11,.07)",
            border: `1px solid ${a.severity === "critical" ? "#dc262644" : "#f59e0b33"}`,
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <div style={{
              width: 8, height: 8, borderRadius: "50%",
              background: a.severity === "critical" ? "#dc2626" : "#f59e0b",
              animation: a.severity === "critical" ? "ci-spin 2s ease-in-out infinite" : "none",
              flexShrink: 0,
            }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                {a.title}
              </div>
              {a.subtitle && (
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                  {a.subtitle}
                </div>
              )}
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3,
                             display: "flex", gap: 8, flexWrap: "wrap" }}>
                {a.phone && (
                  <span className="mono">+{a.phone}</span>
                )}
                {a.intent && <span>· {INTENT_LABELS[a.intent] || a.intent}</span>}
                {a.csat_score != null && (
                  <span>· CSAT {a.csat_score}</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
