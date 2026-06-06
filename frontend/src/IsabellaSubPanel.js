import React, { useCallback, useEffect, useState } from "react";
import {
  Bot, Users, Sparkles, Clock, Zap, RefreshCw, Power,
  TrendingUp, MessageSquare, Crown, Award,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   IsabellaSubPanel — sub-aba "Isabella" da Central IA
   KPIs: % IA vs humano, ranking, tempo médio, % uso polish,
   toggle polish on/off, série temporal de mensagens.
============================================================= */

const PERIODS = [
  { id: 1,  label: "Hoje" },
  { id: 7,  label: "7 dias" },
  { id: 30, label: "30 dias" },
  { id: 90, label: "90 dias" },
];

export default function IsabellaSubPanel() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [savingToggle, setSavingToggle] = useState(false);

  const reload = useCallback(async () => {
    setRefreshing(true);
    try {
      const k = await api.isabellaKpis(days);
      setData(k);
    } catch (e) {
      console.error("[isabella] reload err:", e);
    } finally { setLoading(false); setRefreshing(false); }
  }, [days]);

  useEffect(() => { reload(); }, [reload]);

  const togglePolish = async () => {
    if (!data || savingToggle) return;
    setSavingToggle(true);
    try {
      const next = !data.polish_button_enabled;
      await api.isabellaConfigSet(next);
      setData((d) => ({ ...d, polish_button_enabled: next }));
    } catch (e) {
      await window.alert("Erro ao salvar: " + (e?.response?.data?.detail || e.message));
    } finally { setSavingToggle(false); }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
        <RefreshCw size={28} style={{ animation: "ci-spin 1s linear infinite" }} />
        <div style={{ marginTop: 10, fontSize: 13 }}>Carregando KPIs da Isabella…</div>
      </div>
    );
  }
  if (!data) return null;

  const t = data.totals;
  const r = data.ratios;

  return (
    <div data-testid="isabella-subpanel" style={{ display: "grid", gap: 14 }}>
      {/* Header + period toggle + status do botão polish */}
      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(139,92,246,.10) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(139,92,246,.35)",
        }}>
          <Bot size={24} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, letterSpacing: "-0.02em" }}>
            Isabella — Performance da Assistente IA
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            {t.all_messages.toLocaleString("pt-BR")} mensagens nos últimos {data.days} dia{data.days > 1 ? "s" : ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {PERIODS.map((p) => (
            <button key={p.id} onClick={() => setDays(p.id)}
                    data-testid={`isa-period-${p.id}`}
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
                  data-testid="isa-reload">
            <RefreshCw size={13}
                       style={{ animation: refreshing ? "ci-spin 1s linear infinite" : "none" }} />
          </button>
        </div>
      </div>

      {/* Toggle do botão "Enviar com IA" */}
      <div className="surface" data-testid="isa-polish-toggle-card" style={{
        padding: 16, borderRadius: 12,
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
        border: data.polish_button_enabled
          ? "2px solid #3b82f6" : "1px solid var(--border-default)",
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 10,
          background: data.polish_button_enabled
            ? "linear-gradient(135deg, #3b82f6, #2563eb)"
            : "linear-gradient(135deg, #94a3b8, #64748b)",
          color: "#fff", display: "grid", placeItems: "center",
          flexShrink: 0,
        }}>
          <Sparkles size={18} strokeWidth={2.2} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: 14, fontWeight: 800, color: "var(--text-primary)" }}>
            Botão “Enviar com IA”
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            {data.polish_button_enabled
              ? "Ativo — atendentes veem o botão azul que reescreve o texto antes de enviar"
              : "Desativado — atendentes só veem o botão verde de envio direto"}
          </div>
        </div>
        <button onClick={togglePolish} disabled={savingToggle}
                data-testid="isa-polish-toggle"
                style={{
                  padding: "8px 16px", borderRadius: 999,
                  border: "none", cursor: savingToggle ? "default" : "pointer",
                  background: data.polish_button_enabled
                    ? "linear-gradient(180deg, #16a34a, #15803d)"
                    : "linear-gradient(180deg, #94a3b8, #64748b)",
                  color: "#fff", fontSize: 12.5, fontWeight: 800,
                  display: "inline-flex", alignItems: "center", gap: 6,
                  boxShadow: data.polish_button_enabled
                    ? "0 1px 3px rgba(22,163,74,.4)" : "0 1px 3px rgba(100,116,139,.3)",
                  opacity: savingToggle ? 0.6 : 1,
                }}>
          <Power size={13} strokeWidth={2.5} />
          {savingToggle ? "Salvando..." : (data.polish_button_enabled ? "Ativo" : "Desativado")}
        </button>
      </div>

      {/* KPI cards */}
      <div data-testid="isa-kpi-cards" style={{
        display: "grid", gap: 12,
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
      }}>
        <KpiCard
          icon={Bot} label="IA Isabella" testid="isa-kpi-ai"
          value={`${r.ai_share_pct}%`} sub={`${t.outbound_ai} mensagens`}
          color="#8b5cf6" />
        <KpiCard
          icon={Users} label="Humanos" testid="isa-kpi-human"
          value={`${r.human_share_pct}%`} sub={`${t.outbound_human} mensagens`}
          color="#0ea5e9" />
        <KpiCard
          icon={Sparkles} label="Uso do botão IA" testid="isa-kpi-polish"
          value={`${r.polish_use_pct}%`}
          sub={`${t.outbound_human_polished} de ${t.outbound_human} envios humanos`}
          color="#3b82f6" />
        <KpiCard
          icon={Clock} label="Tempo médio" testid="isa-kpi-handling"
          value={data.avg_handling_minutes ? `${data.avg_handling_minutes}m` : "—"}
          sub="duração de atendimento humano" color="#f59e0b" />
        <KpiCard
          icon={MessageSquare} label="Total" testid="isa-kpi-total"
          value={t.all_messages.toLocaleString("pt-BR")}
          sub={`${t.inbound} recebidas · ${t.outbound} enviadas`}
          color="#0d9488" />
      </div>

      {/* Distribuição IA × Humano (barra horizontal) */}
      <div className="surface" data-testid="isa-share-bar" style={{
        padding: 16, borderRadius: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <Zap size={15} style={{ color: "#8b5cf6" }} />
          <strong style={{ fontSize: 13, fontWeight: 800 }}>
            IA × Humano — quem está atendendo mais?
          </strong>
        </div>
        <div style={{
          display: "flex", height: 28, borderRadius: 8, overflow: "hidden",
          background: "var(--bg-surface-2)", fontSize: 11, fontWeight: 800,
        }}>
          {r.ai_share_pct > 0 && (
            <div style={{
              width: `${r.ai_share_pct}%`,
              background: "linear-gradient(90deg, #8b5cf6, #6366f1)",
              color: "#fff",
              display: "flex", alignItems: "center", justifyContent: "center",
              minWidth: r.ai_share_pct > 5 ? "auto" : 0,
            }}>
              {r.ai_share_pct >= 8 && `IA ${r.ai_share_pct}%`}
            </div>
          )}
          {r.human_share_pct > 0 && (
            <div style={{
              width: `${r.human_share_pct}%`,
              background: "linear-gradient(90deg, #0ea5e9, #0284c7)",
              color: "#fff",
              display: "flex", alignItems: "center", justifyContent: "center",
              minWidth: r.human_share_pct > 5 ? "auto" : 0,
            }}>
              {r.human_share_pct >= 8 && `Humanos ${r.human_share_pct}%`}
            </div>
          )}
        </div>
      </div>

      {/* Gráfico linear de mensagens por dia */}
      <MessagesChart series={data.series} />

      {/* Ranking de atendentes */}
      <RankingCard items={data.ranking} />
    </div>
  );
}

function KpiCard({ icon: Ico, label, value, sub, color, testid }) {
  return (
    <div className="surface" data-testid={testid} style={{
      padding: 14, borderRadius: 12,
      borderTop: `3px solid ${color}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <Ico size={14} style={{ color }} />
        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                        textTransform: "uppercase", letterSpacing: 0.5 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)",
                     letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function MessagesChart({ series }) {
  // Converte para SVG path inline. 3 séries (inbound, ai, human).
  const W = 720, H = 220, padL = 38, padB = 30, padT = 12, padR = 12;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const max = Math.max(1, ...series.map((s) => s.total));
  const xStep = series.length > 1 ? innerW / (series.length - 1) : 0;
  const xy = (idx, val) => [
    padL + idx * xStep,
    padT + innerH - (val / max) * innerH,
  ];
  const buildPath = (key) => series.map((s, i) => {
    const [x, y] = xy(i, s[key]);
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const total = series.reduce((acc, s) => acc + s.total, 0);

  // gridlines no Y (4 linhas)
  const gridY = [0, 0.25, 0.5, 0.75, 1].map((p) => ({
    y: padT + innerH - p * innerH,
    label: Math.round(p * max),
  }));
  // labels X — só primeiro, meio, último para não poluir
  const xLabels = series.length <= 8 ? series : series.filter(
    (_, i) => i === 0 || i === Math.floor(series.length / 2) || i === series.length - 1
  );

  return (
    <div className="surface" data-testid="isa-chart-card" style={{
      padding: 16, borderRadius: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12,
                     flexWrap: "wrap" }}>
        <TrendingUp size={15} style={{ color: "#0d9488" }} />
        <strong style={{ fontSize: 13, fontWeight: 800 }}>
          Mensagens por dia — {series.length} dia{series.length > 1 ? "s" : ""}
        </strong>
        <span style={{ marginLeft: "auto", fontSize: 11.5, color: "var(--text-muted)" }}>
          Total: <strong style={{ color: "var(--text-primary)" }}>{total.toLocaleString("pt-BR")}</strong>
        </span>
        <Legend />
      </div>
      <div style={{ overflow: "auto" }}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%"
             style={{ display: "block", maxWidth: "100%", height: "auto" }}
             preserveAspectRatio="xMidYMid meet">
          {/* Gridlines + Y labels */}
          {gridY.map((g, i) => (
            <g key={i}>
              <line x1={padL} y1={g.y} x2={W - padR} y2={g.y}
                    stroke="var(--border-default)" strokeDasharray="3,3"
                    strokeWidth="1" opacity="0.55" />
              <text x={padL - 6} y={g.y + 3} textAnchor="end"
                    fontSize="10" fill="var(--text-muted)">{g.label}</text>
            </g>
          ))}
          {/* Inbound (cinza/claro) */}
          <path d={buildPath("inbound")} fill="none"
                stroke="#94a3b8" strokeWidth="2" strokeLinejoin="round" />
          {/* AI */}
          <path d={buildPath("ai")} fill="none"
                stroke="#8b5cf6" strokeWidth="2.4" strokeLinejoin="round" />
          {/* Human */}
          <path d={buildPath("human")} fill="none"
                stroke="#0ea5e9" strokeWidth="2.4" strokeLinejoin="round" />
          {/* Pontos no fim de cada série */}
          {series.length > 0 && [
            { key: "inbound", color: "#94a3b8" },
            { key: "ai", color: "#8b5cf6" },
            { key: "human", color: "#0ea5e9" },
          ].map(({ key, color }) => {
            const last = series[series.length - 1];
            const [x, y] = xy(series.length - 1, last[key]);
            return (
              <circle key={key} cx={x} cy={y} r="4"
                      fill={color} stroke="#fff" strokeWidth="1.5" />
            );
          })}
          {/* X labels */}
          {xLabels.map((s, i) => {
            const idx = series.indexOf(s);
            const [x] = xy(idx, 0);
            const dt = new Date(s.day);
            const label = dt.toLocaleDateString("pt-BR", {
              day: "2-digit", month: "2-digit",
            });
            return (
              <text key={s.day} x={x} y={H - 8} textAnchor="middle"
                    fontSize="10" fill="var(--text-muted)">{label}</text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function Legend() {
  const items = [
    { color: "#8b5cf6", label: "IA" },
    { color: "#0ea5e9", label: "Humanos" },
    { color: "#94a3b8", label: "Recebidas" },
  ];
  return (
    <div style={{ display: "inline-flex", gap: 12, alignItems: "center" }}>
      {items.map((it) => (
        <span key={it.label} style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          fontSize: 11, color: "var(--text-secondary)", fontWeight: 600,
        }}>
          <span style={{
            width: 12, height: 3, borderRadius: 2, background: it.color,
          }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

function RankingCard({ items }) {
  return (
    <div className="surface" data-testid="isa-ranking-card" style={{
      padding: 16, borderRadius: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <Crown size={15} style={{ color: "#f59e0b" }} />
        <strong style={{ fontSize: 13, fontWeight: 800 }}>
          Ranking de atendentes — por volume de mensagens
        </strong>
      </div>
      {items.length === 0 ? (
        <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)",
                       fontSize: 12 }}>
          Sem mensagens humanas no período.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {items.map((it, i) => {
            const pct = items[0].messages
              ? Math.round((it.messages / items[0].messages) * 100)
              : 0;
            const medal = i === 0 ? "" : i === 1 ? "" : i === 2 ? "" : null;
            return (
              <div key={it.user_id || i} data-testid={`isa-rank-${i}`}
                   style={{
                     display: "grid",
                     gridTemplateColumns: "32px 1fr 100px 110px 90px",
                     alignItems: "center", gap: 8,
                     padding: "8px 4px",
                     borderBottom: "1px solid var(--border-default)",
                   }}>
                <span style={{ fontSize: 18, textAlign: "center" }}>
                  {medal || <span style={{ fontSize: 12, color: "var(--text-muted)",
                                            fontWeight: 700 }}>{i + 1}º</span>}
                </span>
                <strong style={{ fontSize: 13, color: "var(--text-primary)",
                                  overflow: "hidden", textOverflow: "ellipsis",
                                  whiteSpace: "nowrap" }}>
                  {it.name}
                </strong>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <div style={{
                    flex: 1, height: 6, borderRadius: 3,
                    background: "var(--bg-surface-2)", overflow: "hidden",
                  }}>
                    <div style={{
                      width: `${pct}%`, height: "100%",
                      background: "linear-gradient(90deg, #0ea5e9, #0284c7)",
                    }} />
                  </div>
                </div>
                <span style={{ fontSize: 12.5, fontWeight: 700,
                                color: "var(--text-primary)" }}>
                  {it.messages} msg
                </span>
                <span title={`${it.polished} mensagens com IA`}
                       style={{
                         fontSize: 11.5, fontWeight: 700,
                         display: "inline-flex", alignItems: "center", gap: 4,
                         color: it.polish_pct > 0 ? "#3b82f6" : "var(--text-muted)",
                       }}>
                  <Sparkles size={11} />
                  {it.polish_pct}%
                </span>
              </div>
            );
          })}
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 10.5, color: "var(--text-muted)" }}>
        <Award size={10} style={{ display: "inline", marginRight: 3,
                                    verticalAlign: "middle" }} />
        Coluna direita = % de mensagens enviadas usando o botão “Enviar com IA”
      </div>
    </div>
  );
}
