import React, { useCallback, useEffect, useState } from "react";
import {
  Activity, AlertTriangle, Award, Bot, Brain,
  Clock, Smile, Frown, Meh, Sparkles, TrendingDown, TrendingUp,
  Users, Zap, RefreshCw, GraduationCap, Radio,
} from "lucide-react";
import { api } from "@/api";
import SmartOltAiPanel from "@/SmartOltAiPanel";

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
  const [section, setSection] = useState("kpis");
  const [days, setDays] = useState(7);
  const [kpis, setKpis] = useState(null);
  const [attendants, setAttendants] = useState([]);
  const [intents, setIntents] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [productivity, setProductivity] = useState(null);
  const [aiEval, setAiEval] = useState(null);
  const [aiLearning, setAiLearning] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async () => {
    setRefreshing(true);
    try {
      const [k, a, i, al, p, ae, al2] = await Promise.all([
        api.centralIaKpis(days),
        api.centralIaAttendants(days),
        api.centralIaIntents(days),
        api.centralIaAlerts(),
        api.centralIaProductivity(days).catch(() => null),
        api.centralIaAiEvaluations(days).catch(() => null),
        api.centralIaAiLearning(Math.max(days, 7)).catch(() => null),
      ]);
      setKpis(k); setAttendants(a.items || []); setIntents(i.items || []);
      setAlerts(al.items || []);
      setProductivity(p);
      setAiEval(ae);
      setAiLearning(al2);
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
      <style>{`@keyframes ci-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
                @keyframes ci-pulse { 0%,100% { opacity:1; transform:scale(1);} 50%{opacity:.55;transform:scale(.85);} }`}</style>

      {/* Sub-tabs interno: KPIs / SmartOLT AI */}
      <div data-testid="central-ia-subtabs" style={{
        display: "flex", gap: 4, padding: 4,
        background: "var(--bg-surface-2)", borderRadius: 8,
        border: "1px solid var(--border-default)", width: "fit-content",
      }}>
        <SubTabBtn active={section === "kpis"} onClick={() => setSection("kpis")}
                    icon={Brain} label="Dashboard IA" testId="subtab-kpis" />
        <SubTabBtn active={section === "smartolt"} onClick={() => setSection("smartolt")}
                    icon={Radio} label="SmartOLT AI" testId="subtab-smartolt" />
      </div>

      {section === "smartolt" ? <SmartOltAiPanel /> : (
      <>

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

          {/* Avaliações originadas da IA — CSAT, NPS-like, FCR, comparação humano */}
          {aiEval && <AiEvaluationsCard data={aiEval} days={days} />}
          {aiLearning && <AiLearningCard data={aiLearning} />}

          {/* Produtividade dos atendentes — tempo logado, ocioso, AHT, score */}
          {productivity && <ProductivityCard data={productivity} days={days} />}
        </>
      )}

      {/* Coaching IA — só contadores (detalhe é individual no chat) */}
      <CoachingStatsCard />

      {/* Alertas proativos */}
      <AlertsCard items={alerts} onReload={reload} />
      </>
      )}
    </div>
  );
}

function SubTabBtn({ active, onClick, icon: Ico, label, testId }) {
  return (
    <button onClick={onClick} data-testid={testId} style={{
      padding: "7px 14px", borderRadius: 6,
      border: "none",
      background: active ? "var(--bg-surface)" : "transparent",
      color: active ? "var(--text-primary)" : "var(--text-muted)",
      fontSize: 12, fontWeight: 600, cursor: "pointer",
      display: "inline-flex", alignItems: "center", gap: 6,
      boxShadow: active ? "0 1px 3px rgba(0,0,0,.06)" : "none",
      transition: "all .15s",
    }}>
      <Ico size={13} strokeWidth={2} />
      {label}
    </button>
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
                  {a.negative_count > 0 ? (
                    <span style={{ color: "#dc2626", fontWeight: 700 }}>
                      {a.negative_count}
                    </span>
                  ) : "—"}
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
function CoachingStatsCard() {
  const [byUser, setByUser] = useState([]);
  const [total, setTotal] = useState({ count: 0, unread: 0 });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.centralIaCoachingByUser(7);
        if (cancelled) return;
        setByUser(r.items || []);
        const tot = (r.items || []).reduce((acc, u) => ({
          count: acc.count + u.count, unread: acc.unread + (u.unread || 0),
        }), { count: 0, unread: 0 });
        setTotal(tot);
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="surface" style={{ padding: 16, borderRadius: 12 }}
         data-testid="ci-coaching-stats-card">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <GraduationCap size={14} style={{ color: "#a855f7" }} />
        <span style={{ fontSize: 11, fontWeight: 800, color: "#a855f7",
                       textTransform: "uppercase", letterSpacing: 0.5 }}>
          Coaching por Atendente
        </span>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>
          {total.count} total · <strong style={{ color: total.unread > 0 ? "#dc2626" : "var(--text-muted)" }}>
            {total.unread} não lidos
          </strong>
        </span>
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10 }}>
        Detalhes de cada coaching aparecem como popup para o próprio atendente
        durante a conversa. Aqui você vê só os contadores.
      </div>
      {byUser.length === 0 ? (
        <div style={{ padding: 14, fontSize: 12, color: "var(--text-muted)",
                       background: "var(--bg-surface-2)", borderRadius: 8,
                       textAlign: "center" }}>
          Nenhum coaching nos últimos 7 dias.
        </div>
      ) : (
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--text-muted)", fontSize: 10,
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
              <th style={{ textAlign: "left", padding: "6px 4px" }}>Atendente</th>
              <th style={{ textAlign: "center", padding: "6px 4px" }}>Total</th>
              <th style={{ textAlign: "center", padding: "6px 4px" }}>Não lidos</th>
              <th style={{ textAlign: "center", padding: "6px 4px" }}>Reconhecidos</th>
              <th style={{ textAlign: "center", padding: "6px 4px" }}>Score médio</th>
            </tr>
          </thead>
          <tbody>
            {byUser.map((u) => (
              <tr key={u.user_id} style={{ borderTop: "1px solid var(--border-default)" }}>
                <td style={{ padding: "8px 4px", fontWeight: 600 }}>{u.user_name || u.user_id}</td>
                <td style={{ textAlign: "center", padding: "8px 4px" }}>{u.count}</td>
                <td style={{ textAlign: "center", padding: "8px 4px",
                              color: u.unread > 0 ? "#dc2626" : "var(--text-muted)",
                              fontWeight: u.unread > 0 ? 700 : 400 }}>
                  {u.unread}
                </td>
                <td style={{ textAlign: "center", padding: "8px 4px", color: "#16a34a", fontWeight: 600 }}>
                  {u.ack}
                </td>
                <td style={{ textAlign: "center", padding: "8px 4px",
                              fontWeight: 700, color: csatColor(u.avg_score) }}>
                  {u.avg_score}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
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
              animation: a.severity === "critical" ? "ci-pulse 1.4s ease-in-out infinite" : "none",
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

/* =============================================================
   ProductivityCard — KPIs avançados de produtividade por atendente.
============================================================= */
function ProductivityCard({ data, days }) {
  const { items = [], team = {} } = data || {};
  const fmtDur = (s) => {
    if (s == null) return "—";
    if (s < 60) return `${s}s`;
    const m = Math.round(s / 60);
    return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h${(m % 60).toString().padStart(2,"0")}m`;
  };
  const scoreColor = (v) => {
    if (v == null) return "var(--text-muted)";
    if (v >= 75) return "#16a34a";
    if (v >= 50) return "#eab308";
    return "#dc2626";
  };

  return (
    <div className="surface" data-testid="ci-productivity-card" style={{
      padding: 18, borderRadius: 14,
      border: "1px solid var(--border-default)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                     marginBottom: 14, flexWrap: "wrap" }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: "linear-gradient(135deg, #6366f1, #4f46e5)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 12px rgba(99,102,241,.35)",
        }}>
          <Activity size={17} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <strong style={{ fontSize: 14, color: "var(--text-primary)" }}>
            Produtividade dos atendentes
          </strong>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
            Tempo logado, ocioso, AHT, throughput e score composto · Últimos {days} dias
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <ProdKpi label="Atendentes" value={team.attendants_count || 0} />
          <ProdKpi label="Conversas" value={team.total_conversations || 0} />
          <ProdKpi label="Msgs" value={team.total_messages || 0} />
          <ProdKpi label="CSAT" value={team.avg_csat != null ? team.avg_csat : "—"}
                    color={team.avg_csat >= 7 ? "#16a34a" : team.avg_csat >= 5 ? "#eab308" : "#dc2626"} />
          <ProdKpi label="% ocioso" value={team.avg_idle_pct != null ? `${team.avg_idle_pct}%` : "—"}
                    color={team.avg_idle_pct <= 30 ? "#16a34a" : team.avg_idle_pct <= 50 ? "#eab308" : "#dc2626"} />
          <ProdKpi label="FRT médio" value={fmtDur(team.avg_frt_seconds)}
                    color={team.avg_frt_seconds <= 300 ? "#16a34a" : team.avg_frt_seconds <= 900 ? "#eab308" : "#dc2626"} />
        </div>
      </div>

      {items.length === 0 ? (
        <div style={{
          padding: 30, textAlign: "center",
          color: "var(--text-muted)", fontSize: 12,
          background: "var(--bg-surface-2)", borderRadius: 10,
        }}>
          Sem dados de produtividade ainda no período. Atendentes humanos que
          responderem conversas via WhatsApp aparecem aqui automaticamente.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{
                borderBottom: "2px solid var(--border-default)",
                textAlign: "left", fontSize: 10, fontWeight: 800,
                color: "var(--text-muted)",
                textTransform: "uppercase", letterSpacing: 0.4,
              }}>
                <th style={{ padding: "8px 6px" }}>Atendente</th>
                <th style={{ padding: "8px 6px", textAlign: "center" }} title="Score composto: 40% CSAT + 25% volume + 20% adesão + 15% velocidade">Score</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }}>Conv.</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="Mensagens enviadas">Msgs</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="Tempo logado (estimado, cap 8h/dia)">Logado</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="Tempo ocioso (logado − em conversa)">Ocioso</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="Mensagens por hora ativa">Thrpt</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="First Response Time médio">FRT</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="Average Handle Time">AHT</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }}>CSAT</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="% conversas devolvidas pra IA">IA %</th>
                <th style={{ padding: "8px 6px", textAlign: "right" }} title="Coachings não lidos / total">Coach</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => (
                <tr key={it.user_id}
                    data-testid={`ci-prod-row-${it.user_id}`}
                    style={{
                      borderBottom: "1px solid var(--border-default)",
                      background: idx === 0 ? "rgba(22,163,74,.04)" : "transparent",
                    }}>
                  <td style={{ padding: "9px 6px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{
                        width: 26, height: 26, borderRadius: "50%",
                        background: idx === 0
                          ? "linear-gradient(135deg, #f59e0b, #d97706)"
                          : "var(--bg-surface-2)",
                        color: idx === 0 ? "#fff" : "var(--text-primary)",
                        display: "grid", placeItems: "center",
                        fontSize: 10, fontWeight: 800,
                      }}>{idx + 1}</div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 700, maxWidth: 180,
                                       overflow: "hidden", textOverflow: "ellipsis",
                                       whiteSpace: "nowrap" }}>
                          {it.name}
                          {idx === 0 && (
                            <Award size={11} strokeWidth={2.5}
                                   style={{ color: "#d97706", marginLeft: 4,
                                             verticalAlign: "middle" }} />
                          )}
                        </div>
                        <div style={{ fontSize: 9, color: "var(--text-muted)" }}>
                          {it.role} · {it.active_days} dia(s)
                        </div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "center" }}>
                    <div style={{
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      width: 36, height: 36, borderRadius: "50%",
                      background: `${scoreColor(it.productivity_score)}18`,
                      color: scoreColor(it.productivity_score),
                      fontSize: 12, fontWeight: 800,
                      border: `2px solid ${scoreColor(it.productivity_score)}`,
                    }}>{it.productivity_score != null ? Math.round(it.productivity_score) : "—"}</div>
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "right", fontWeight: 600 }}>
                    {it.conversations}
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "right" }}>{it.messages_sent}</td>
                  <td style={{ padding: "9px 6px", textAlign: "right" }}>{fmtDur(it.logged_seconds)}</td>
                  <td style={{ padding: "9px 6px", textAlign: "right" }}>
                    <span style={{
                      padding: "2px 7px", borderRadius: 5,
                      background: it.idle_pct == null ? "transparent"
                        : it.idle_pct <= 30 ? "rgba(22,163,74,.12)"
                        : it.idle_pct <= 50 ? "rgba(234,179,8,.15)"
                        : "rgba(220,38,38,.12)",
                      color: it.idle_pct == null ? "var(--text-muted)"
                        : it.idle_pct <= 30 ? "#15803d"
                        : it.idle_pct <= 50 ? "#a16207"
                        : "#b91c1c",
                      fontWeight: 700, fontSize: 11,
                    }}>{it.idle_pct != null ? `${it.idle_pct}%` : "—"}</span>
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "right",
                                fontSize: 11, color: "var(--text-secondary)" }}>
                    {it.msgs_per_hour != null ? `${it.msgs_per_hour}/h` : "—"}
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "right",
                                color: it.frt_avg_seconds == null ? "var(--text-muted)"
                                  : it.frt_avg_seconds <= 300 ? "#15803d"
                                  : it.frt_avg_seconds <= 900 ? "#a16207" : "#b91c1c",
                                fontWeight: 600 }}>
                    {fmtDur(it.frt_avg_seconds)}
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "right" }}>{fmtDur(it.aht_avg_seconds)}</td>
                  <td style={{ padding: "9px 6px", textAlign: "right" }}>
                    {it.csat_avg != null
                      ? <span style={{
                          fontWeight: 700,
                          color: it.csat_avg >= 7 ? "#15803d"
                            : it.csat_avg >= 5 ? "#a16207" : "#b91c1c",
                        }}>{it.csat_avg.toFixed(1)}</span>
                      : "—"}
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "right", fontSize: 11 }}>
                    {it.ai_usage_pct != null ? `${it.ai_usage_pct}%` : "—"}
                  </td>
                  <td style={{ padding: "9px 6px", textAlign: "right" }}>
                    {it.coachings_unread > 0
                      ? <span title={`${it.coachings_unread} coaching(s) não lido(s)`}
                              style={{
                          padding: "2px 7px", borderRadius: 999,
                          background: "#a855f7", color: "#fff",
                          fontSize: 10, fontWeight: 800,
                        }}>{it.coachings_unread}</span>
                      : it.coachings_total > 0
                        ? <span title={`${it.coachings_total} coaching(s) já lido(s)`}
                                style={{ color: "var(--text-muted)", fontSize: 10 }}>
                            {it.coachings_total}
                          </span>
                        : <span style={{ color: "var(--text-muted)" }}>—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{
        marginTop: 12, padding: "8px 12px", borderRadius: 8,
        background: "var(--bg-surface-2)",
        fontSize: 10, color: "var(--text-muted)",
        display: "flex", flexWrap: "wrap", gap: 14,
      }}>
        <span><strong>Score</strong> = 40% CSAT + 25% volume + 20% adesão + 15% velocidade</span>
        <span><strong>FRT ideal</strong>: ≤ 5min</span>
        <span><strong>Ocioso saudável</strong>: ≤ 30%</span>
        <span><strong>Tempo logado</strong>: estimado por atividade (cap 8h/dia)</span>
      </div>
    </div>
  );
}

function ProdKpi({ label, value, color }) {
  return (
    <div style={{
      padding: "5px 10px", borderRadius: 8,
      background: "var(--bg-surface-2)",
      textAlign: "center", minWidth: 60,
    }}>
      <div style={{ fontSize: 9, color: "var(--text-muted)",
                     textTransform: "uppercase", fontWeight: 700,
                     letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 800,
                     color: color || "var(--text-primary)",
                     marginTop: 1 }}>{value}</div>
    </div>
  );
}


/* =============================================================
   AiEvaluationsCard — KPIs de avaliações originadas da IA (Jerusa).
   Boas práticas (Forrester, Zendesk, Salesforce):
   - CSAT médio (0-10)
   - NPS-like score (% promotores 9-10 − % detratores ≤6)
   - Distribuição visual em barras
   - FCR (First Contact Resolution) %
   - Comparação direta com atendimentos humanos
   - Trend de volume e CSAT (últimos 14 dias)
============================================================= */
function AiEvaluationsCard({ data, days }) {
  const ai = data?.ai_only || {};
  const human = data?.human || {};
  const trend = data?.trend_14d || [];
  const fmtDur = (s) => {
    if (s == null) return "—";
    if (s < 60) return `${s}s`;
    const m = Math.round(s / 60);
    return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h${(m % 60).toString().padStart(2,"0")}m`;
  };

  const csatColor = (v) => {
    if (v == null) return "var(--text-muted)";
    if (v >= 8) return "#16a34a";
    if (v >= 6) return "#eab308";
    return "#dc2626";
  };

  return (
    <div className="surface" data-testid="ci-ai-evals-card" style={{
      padding: 18, borderRadius: 14,
      border: "1px solid rgba(13,148,136,.3)",
      background: "linear-gradient(135deg, rgba(13,148,136,.05), var(--bg-surface))",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                     marginBottom: 14, flexWrap: "wrap" }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: "linear-gradient(135deg, #0d9488, #06b6d4)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 12px rgba(13,148,136,.4)",
        }}>
          <Bot size={17} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <strong style={{ fontSize: 14, color: "#0d9488" }}>
            Avaliações originadas pela IA (Jerusa)
          </strong>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
            CSAT, NPS-like, FCR e comparação com atendimentos humanos · Últimos {days} dias
          </div>
        </div>
      </div>

      {/* Linha de cards principais */}
      <div style={{ display: "grid",
                     gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                     gap: 10, marginBottom: 14 }}>
        <BigKpi label="Total avaliadas"
                value={ai.total}
                sub={`${human.total || 0} humanas`} />
        <BigKpi label="CSAT médio"
                value={ai.avg_csat != null ? ai.avg_csat.toFixed(1) : "—"}
                color={csatColor(ai.avg_csat)}
                sub={human.avg_csat != null
                  ? `Humanos: ${human.avg_csat.toFixed(1)}` : null} />
        <BigKpi label="NPS-like"
                value={ai.nps != null ? (ai.nps > 0 ? `+${ai.nps}` : ai.nps) : "—"}
                color={ai.nps >= 50 ? "#16a34a"
                  : ai.nps >= 0 ? "#eab308" : "#dc2626"}
                sub="promotores − detratores (%)" />
        <BigKpi label="FCR"
                value={ai.fcr_rate != null ? `${ai.fcr_rate}%` : "—"}
                color={ai.fcr_rate >= 70 ? "#16a34a"
                  : ai.fcr_rate >= 40 ? "#eab308" : "#dc2626"}
                sub="resolvidas no 1º contato" />
        <BigKpi label="FRT médio"
                value={fmtDur(ai.avg_frt_seconds)}
                color={ai.avg_frt_seconds <= 60 ? "#16a34a"
                  : ai.avg_frt_seconds <= 300 ? "#eab308" : "#dc2626"} />
        <BigKpi label="AHT médio"
                value={fmtDur(ai.avg_aht_seconds)} />
      </div>

      {/* Distribuição NPS-like em barras */}
      {ai.total > 0 && (
        <div style={{
          padding: 14, borderRadius: 10,
          background: "var(--bg-surface-2)",
          marginBottom: 14,
        }}>
          <div style={{
            fontSize: 10, fontWeight: 800,
            color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: 0.4,
            marginBottom: 8,
          }}>
            Distribuição das notas — modelo NPS
          </div>
          <div style={{ display: "flex", height: 24, borderRadius: 6,
                         overflow: "hidden", border: "1px solid var(--border-default)" }}>
            <div title={`Promotores (9-10): ${ai.promoters} (${ai.promoters_pct}%)`}
                  style={{
                    flex: ai.promoters,
                    background: "linear-gradient(180deg, #22c55e, #16a34a)",
                    display: "grid", placeItems: "center",
                    color: "#fff", fontSize: 11, fontWeight: 800,
                  }}>
              {ai.promoters_pct >= 8 ? `${ai.promoters_pct}%` : ""}
            </div>
            <div title={`Neutros (7-8): ${ai.neutrals} (${(100 - ai.promoters_pct - ai.detractors_pct).toFixed(1)}%)`}
                  style={{
                    flex: ai.neutrals,
                    background: "linear-gradient(180deg, #fbbf24, #d97706)",
                    display: "grid", placeItems: "center",
                    color: "#fff", fontSize: 11, fontWeight: 800,
                  }}>
              {(100 - ai.promoters_pct - ai.detractors_pct) >= 8
                ? `${(100 - ai.promoters_pct - ai.detractors_pct).toFixed(0)}%` : ""}
            </div>
            <div title={`Detratores (≤6): ${ai.detractors} (${ai.detractors_pct}%)`}
                  style={{
                    flex: ai.detractors,
                    background: "linear-gradient(180deg, #f87171, #dc2626)",
                    display: "grid", placeItems: "center",
                    color: "#fff", fontSize: 11, fontWeight: 800,
                  }}>
              {ai.detractors_pct >= 8 ? `${ai.detractors_pct}%` : ""}
            </div>
          </div>
          <div style={{
            display: "flex", justifyContent: "space-between",
            marginTop: 6, fontSize: 10, color: "var(--text-muted)",
          }}>
            <span><span style={{ color: "#16a34a", fontWeight: 700 }}>
              ●</span> Promotores (9-10): {ai.promoters}</span>
            <span><span style={{ color: "#d97706", fontWeight: 700 }}>
              ●</span> Neutros (7-8): {ai.neutrals}</span>
            <span><span style={{ color: "#dc2626", fontWeight: 700 }}>
              ●</span> Detratores (≤6): {ai.detractors}</span>
          </div>
        </div>
      )}

      {/* Trend dos últimos 14 dias */}
      {trend.length > 0 && (
        <div style={{
          padding: 14, borderRadius: 10,
          background: "var(--bg-surface-2)",
        }}>
          <div style={{
            fontSize: 10, fontWeight: 800,
            color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: 0.4,
            marginBottom: 8,
          }}>
            Tendência — últimos 14 dias (volume IA + CSAT)
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: `repeat(${trend.length}, 1fr)`,
            gap: 4, alignItems: "end", height: 70,
          }}>
            {trend.map((t) => {
              const maxCount = Math.max(...trend.map((x) => x.count), 1);
              const h = (t.count / maxCount) * 60;
              return (
                <div key={t.date} title={`${t.date}: ${t.count} avals · CSAT ${t.avg_csat ?? "—"}`}
                      style={{
                        display: "flex", flexDirection: "column",
                        alignItems: "center", gap: 3,
                      }}>
                  <div style={{
                    width: "100%", maxWidth: 24,
                    height: `${h}px`, minHeight: 2,
                    background: csatColor(t.avg_csat),
                    borderRadius: 3,
                    transition: "all .3s",
                  }} />
                  <div style={{ fontSize: 8, color: "var(--text-muted)" }}>
                    {t.date.slice(5)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {ai.total === 0 && (
        <div style={{
          padding: 30, textAlign: "center",
          color: "var(--text-muted)", fontSize: 12,
          background: "var(--bg-surface-2)", borderRadius: 10,
        }}>
          Sem avaliações de conversas atendidas pela IA ainda no período.
          Conversas atendidas apenas pela Jerusa (sem intervenção humana)
          aparecem aqui automaticamente quando avaliadas pelo worker.
        </div>
      )}
    </div>
  );
}

function BigKpi({ label, value, color, sub }) {
  return (
    <div style={{
      padding: 12, borderRadius: 10,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
    }}>
      <div style={{
        fontSize: 9, fontWeight: 800,
        color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.4,
      }}>{label}</div>
      <div style={{
        fontSize: 22, fontWeight: 800,
        color: color || "var(--text-primary)",
        letterSpacing: "-0.03em", marginTop: 2,
      }}>{value ?? "—"}</div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}


/* =============================================================
   AiLearningCard — evolução do aprendizado da IA monitorando
   mensagens dos atendentes humanos.
============================================================= */
function AiLearningCard({ data }) {
  const sim = data?.similarity_score;
  const autonomy = data?.autonomy_rate;
  const trend = data?.trend_4w || [];
  const last = trend[trend.length - 1]?.similarity_pct;
  const prev = trend[trend.length - 2]?.similarity_pct;
  const delta = (last != null && prev != null) ? (last - prev) : null;
  const deltaPositive = delta != null && delta > 0;
  const max = Math.max(1, ...trend.map((t) => t.similarity_pct || 0));
  const [showExamples, setShowExamples] = useState(false);
  const [examples, setExamples] = useState(null);
  const [loadingEx, setLoadingEx] = useState(false);

  const openExamples = async () => {
    setShowExamples(true);
    if (examples) return;
    setLoadingEx(true);
    try {
      const r = await api.centralIaAiLearningExamples();
      setExamples(r.examples || []);
    } catch (e) {
      setExamples([]);
    } finally { setLoadingEx(false); }
  };

  return (
    <div data-testid="ai-learning-card" style={{
      padding: 18, borderRadius: 12,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
    }}>
      <div style={{
        marginBottom: 16, display: "flex",
        justifyContent: "space-between", alignItems: "flex-start", gap: 12,
        flexWrap: "wrap",
      }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.6 }}>
            Aprendizado da IA
          </div>
          <h3 style={{ fontSize: 16, fontWeight: 700, margin: "4px 0 0",
                          color: "var(--text-primary)",
                          letterSpacing: "-0.012em" }}>
            Evolução da IA monitorando atendentes
          </h3>
          <p style={{ fontSize: 12, color: "var(--text-secondary)",
                        margin: "4px 0 0", maxWidth: 560, lineHeight: 1.5 }}>
            A IA observa as mensagens enviadas pelos atendentes humanos e aprende
            o vocabulário, tom e estruturas que funcionam — sem replicar erros.
            Atendimentos com CSAT ≥ 8 viram exemplos no prompt da IA.
          </p>
        </div>
        <button onClick={openExamples}
                data-testid="ai-learning-examples-btn"
                style={{
                  padding: "6px 12px", borderRadius: 6,
                  border: "1px solid var(--border-default)",
                  background: "transparent",
                  color: "var(--text-primary)",
                  fontSize: 11, fontWeight: 600, cursor: "pointer",
                  whiteSpace: "nowrap",
                }}>
          Ver exemplos atuais
        </button>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 10, marginBottom: 18,
      }}>
        <div style={{
          padding: 14, borderRadius: 8,
          border: "1px solid var(--border-default)",
          background: "var(--bg-surface-2)",
        }}>
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                          textTransform: "uppercase", fontWeight: 700,
                          letterSpacing: 0.5 }}>Similaridade humano · IA</div>
          <div style={{ fontSize: 28, fontWeight: 800,
                          color: sim == null ? "var(--text-muted)"
                                 : sim >= 60 ? "#16a34a"
                                 : sim >= 40 ? "#d97706" : "#dc2626",
                          letterSpacing: "-0.02em", marginTop: 4 }}>
            {sim == null ? "—" : `${sim}%`}
          </div>
          {delta != null && (
            <div style={{ fontSize: 11, marginTop: 4,
                            color: deltaPositive ? "#16a34a" : "#dc2626",
                            fontWeight: 600 }}>
              {deltaPositive ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}pp vs semana anterior
            </div>
          )}
        </div>
        <div style={{
          padding: 14, borderRadius: 8,
          border: "1px solid var(--border-default)",
          background: "var(--bg-surface-2)",
        }}>
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                          textTransform: "uppercase", fontWeight: 700,
                          letterSpacing: 0.5 }}>Taxa de autonomia</div>
          <div style={{ fontSize: 28, fontWeight: 800,
                          color: "var(--text-primary)",
                          letterSpacing: "-0.02em", marginTop: 4 }}>
            {autonomy == null ? "—" : `${autonomy}%`}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
            Conversas resolvidas só pela IA
          </div>
        </div>
        <div style={{
          padding: 14, borderRadius: 8,
          border: "1px solid var(--border-default)",
          background: "var(--bg-surface-2)",
        }}>
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                          textTransform: "uppercase", fontWeight: 700,
                          letterSpacing: 0.5 }}>Corpus de aprendizado</div>
          <div style={{ fontSize: 28, fontWeight: 800,
                          color: "var(--text-primary)",
                          letterSpacing: "-0.02em", marginTop: 4 }}>
            {data?.human_samples ?? "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
            Mensagens humanas analisadas
          </div>
        </div>
        <div style={{
          padding: 14, borderRadius: 8,
          border: "1px solid var(--border-default)",
          background: "var(--bg-surface-2)",
        }}>
          <div style={{ fontSize: 10, color: "var(--text-muted)",
                          textTransform: "uppercase", fontWeight: 700,
                          letterSpacing: 0.5 }}>Mensagens IA</div>
          <div style={{ fontSize: 28, fontWeight: 800,
                          color: "var(--text-primary)",
                          letterSpacing: "-0.02em", marginTop: 4 }}>
            {data?.ai_messages ?? "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
            Enviadas pela IA no período
          </div>
        </div>
      </div>

      {trend.length > 0 && (
        <div>
          <div style={{ fontSize: 11, color: "var(--text-muted)",
                          fontWeight: 700, textTransform: "uppercase",
                          letterSpacing: 0.5, marginBottom: 8,
                          display: "flex", justifyContent: "space-between" }}>
            <span>Evolução (4 semanas)</span>
            {!trend.some((t) => t.similarity_pct != null) && (
              <span style={{ fontSize: 9, color: "var(--text-muted)",
                                fontWeight: 500, textTransform: "none",
                                letterSpacing: 0 }}>
                Aguardando histórico
              </span>
            )}
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: `repeat(${trend.length}, 1fr)`,
            gap: 8, alignItems: "end", height: 100, padding: "0 6px",
          }}>
            {trend.map((w, idx) => {
              const v = w.similarity_pct;
              const h = v != null ? Math.max(6, (v / max) * 100) : 6;
              return (
                <div key={idx} style={{
                  display: "flex", flexDirection: "column",
                  alignItems: "center", gap: 4, height: "100%",
                  justifyContent: "flex-end",
                }} title={`${w.week_start}: ${v ?? "—"}%`}>
                  <div style={{ fontSize: 10, fontWeight: 700,
                                  color: "var(--text-primary)" }}>
                    {v != null ? `${v}%` : "—"}
                  </div>
                  <div style={{
                    width: "100%", height: `${h}%`, minHeight: 6,
                    background: v == null ? "var(--bg-surface-2)"
                                : v >= 60 ? "#16a34a"
                                : v >= 40 ? "#d97706" : "#dc2626",
                    borderRadius: "4px 4px 0 0",
                    opacity: idx === trend.length - 1 ? 1 : 0.55,
                  }} />
                </div>
              );
            })}
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: `repeat(${trend.length}, 1fr)`,
            gap: 8, marginTop: 4, padding: "0 6px",
          }}>
            {trend.map((w, idx) => (
              <div key={idx} style={{
                fontSize: 9, color: "var(--text-muted)",
                textAlign: "center", fontFamily: "ui-monospace, monospace",
              }}>
                {new Date(w.week_start).toLocaleDateString("pt-BR",
                  { day: "2-digit", month: "2-digit" })}
              </div>
            ))}
          </div>
        </div>
      )}

      {showExamples && (
        <div onClick={() => setShowExamples(false)} style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,.6)",
          display: "grid", placeItems: "center", zIndex: 1100, padding: 16,
        }} data-testid="ai-learning-examples-modal">
          <div onClick={(e) => e.stopPropagation()} style={{
            background: "var(--bg-surface)", borderRadius: 12,
            width: "min(640px, 100%)", maxHeight: "85vh", overflow: "auto",
            border: "1px solid var(--border-default)",
            boxShadow: "0 20px 50px rgba(0,0,0,.4)",
          }}>
            <div style={{
              padding: "16px 20px",
              borderBottom: "1px solid var(--border-default)",
              display: "flex", justifyContent: "space-between",
              alignItems: "center",
            }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700,
                                color: "var(--text-muted)",
                                textTransform: "uppercase",
                                letterSpacing: 0.5 }}>
                  Few-shot examples ativos
                </div>
                <h3 style={{ fontSize: 14, fontWeight: 700,
                                color: "var(--text-primary)", margin: "3px 0 0",
                                letterSpacing: "-0.01em" }}>
                  Exemplos que a IA está aprendendo agora
                </h3>
              </div>
              <button onClick={() => setShowExamples(false)}
                      style={{
                        width: 28, height: 28, borderRadius: 6,
                        border: "1px solid var(--border-default)",
                        background: "transparent", cursor: "pointer",
                        color: "var(--text-muted)",
                      }}>×</button>
            </div>
            <div style={{ padding: 20 }}>
              {loadingEx ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Carregando…
                </div>
              ) : !examples || examples.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)",
                                lineHeight: 1.6 }}>
                  Ainda não há conversas com CSAT ≥ 8 nos últimos 30 dias.
                  À medida que atendentes humanos resolverem bem chamados,
                  os exemplos aparecerão aqui automaticamente.
                </div>
              ) : (
                <div style={{ display: "grid", gap: 12 }}>
                  {examples.map((ex, i) => (
                    <div key={i} style={{
                      padding: 12, borderRadius: 8,
                      background: "var(--bg-surface-2)",
                      border: "1px solid var(--border-default)",
                    }}>
                      <div style={{
                        fontSize: 9, fontWeight: 700,
                        color: "#16a34a",
                        textTransform: "uppercase", letterSpacing: 0.5,
                        marginBottom: 6,
                      }}>
                        Exemplo {i + 1} · CSAT {ex.csat}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)",
                                       marginBottom: 4 }}>
                        Cliente:
                      </div>
                      <div style={{ fontSize: 13, color: "var(--text-primary)",
                                       marginBottom: 10,
                                       padding: "8px 10px", borderRadius: 6,
                                       background: "var(--bg-surface)",
                                       border: "1px solid var(--border-default)" }}>
                        {ex.q}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)",
                                       marginBottom: 4 }}>
                        Atendente:
                      </div>
                      <div style={{ fontSize: 13, color: "var(--text-primary)",
                                       padding: "8px 10px", borderRadius: 6,
                                       background: "rgba(34,197,94,.06)",
                                       border: "1px solid rgba(34,197,94,.20)" }}>
                        {ex.a}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

