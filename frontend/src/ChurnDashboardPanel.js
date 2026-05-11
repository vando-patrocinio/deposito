import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import {
  TrendingDown, Users, Calendar, MapPin, AlertCircle,
  Clock, Loader2, RefreshCw, ArrowDownRight, Sparkles, ChevronDown, ChevronUp,
  History, GitCompare,
} from "lucide-react";
import ChurnBriefingScheduleCard from "@/ChurnBriefingScheduleCard";

const PERIODS = [
  { days: 30,  label: "30 dias" },
  { days: 90,  label: "90 dias" },
  { days: 180, label: "6 meses" },
  { days: 365, label: "12 meses" },
];

const KIND_COLORS = {
  cancelamento: "#dc2626",
  retirada: "#a855f7",
};

const REASON_COLORS = [
  "#dc2626", "#f59e0b", "#0ea5e9", "#10b981", "#a855f7",
  "#ec4899", "#64748b", "#0d9488",
];

function fmtNum(n) {
  return Number(n || 0).toLocaleString("pt-BR");
}

function fmtMonth(ym) {
  if (!ym) return "—";
  const [y, m] = ym.split("-");
  const labels = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"];
  return `${labels[parseInt(m,10)-1]}/${y.slice(2)}`;
}

/**
 * ChurnDashboardPanel — sub-aba "Churn" da Central IA.
 * Best practices ISP/Telecom 2026: múltiplas dimensões (tempo, geografia,
 * motivo), distinção entre pedido (cancelamento) e operação (retirada),
 * tempo médio de vida do cliente, alertas de churn iminente.
 */
export default function ChurnDashboardPanel() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(180);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [insight, setInsight] = useState(null);
  const [insightLoading, setInsightLoading] = useState(false);
  const [insightErr, setInsightErr] = useState("");
  const [insightOpen, setInsightOpen] = useState(true);
  // Histórico + comparação
  const [history, setHistory] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [comparison, setComparison] = useState(null);
  const [comparing, setComparing] = useState(false);

  const load = useCallback(async (d) => {
    setLoading(true); setErr("");
    try {
      const r = await api.churnDashboard(d);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(days); setInsight(null); }, [load, days]);

  const generateInsight = useCallback(async () => {
    setInsightLoading(true); setInsightErr(""); setInsight(null);
    setComparison(null);
    setInsightOpen(true);
    try {
      const r = await api.churnAiInsight(days);
      setInsight(r);
      // Refresh history após gerar novo
      try {
        const h = await api.churnAiInsightHistory(20);
        setHistory(h.items || []);
      } catch (e) { /* ignore */ }
    } catch (e) {
      setInsightErr(e?.response?.data?.detail || e.message);
    } finally {
      setInsightLoading(false);
    }
  }, [days]);

  // Carrega histórico ao montar
  useEffect(() => {
    api.churnAiInsightHistory(20).then((r) => setHistory(r.items || []))
      .catch(() => { /* ignore */ });
  }, []);

  const loadHistoricInsight = useCallback(async (id) => {
    setInsightLoading(true); setInsightErr(""); setComparison(null);
    setInsightOpen(true);
    try {
      const r = await api.churnAiInsightGet(id);
      setInsight(r);
    } catch (e) {
      setInsightErr(e?.response?.data?.detail || e.message);
    } finally {
      setInsightLoading(false);
      setHistoryOpen(false);
    }
  }, []);

  const compareWithPrevious = useCallback(async () => {
    if (!insight?.id || history.length < 2) return;
    const baseIdx = history.findIndex((h) => h.id === insight.id);
    // O próximo na lista (mais antigo) é o "anterior"
    const prev = history[baseIdx >= 0 ? baseIdx + 1 : 1];
    if (!prev) return;
    setComparing(true); setComparison(null);
    try {
      const r = await api.churnAiInsightCompare(insight.id, prev.id);
      setComparison({ ...r, prev_label: `${prev.date} · ${prev.window_days}d` });
    } catch (e) {
      setComparison({ error: e?.response?.data?.detail || e.message });
    } finally {
      setComparing(false);
    }
  }, [insight, history]);

  const maxMonth = useMemo(() => {
    if (!data?.by_month) return 1;
    return Math.max(1, ...data.by_month.map((m) => m.count));
  }, [data]);

  const maxReason = useMemo(() => {
    if (!data?.by_reason?.length) return 1;
    return Math.max(1, ...data.by_reason.map((r) => r.count));
  }, [data]);

  const maxNeigh = useMemo(() => {
    if (!data?.by_neighborhood?.length) return 1;
    return Math.max(1, ...data.by_neighborhood.map((n) => n.count));
  }, [data]);

  if (loading && !data) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)",
                      display: "flex", justifyContent: "center", alignItems: "center", gap: 8 }}>
        <Loader2 size={18} className="animate-spin" />
        <span>Carregando dashboard de churn...</span>
      </div>
    );
  }

  if (err) {
    return (
      <div style={{ padding: 16, background: "#fef2f2", color: "#be123c",
                      borderRadius: 10, fontSize: 13 }}>
        Erro: {err}
      </div>
    );
  }

  const k = data?.kpis || {};

  return (
    <div data-testid="churn-dashboard" style={{ display: "grid", gap: 16 }}>
      {/* Header + period */}
      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(220,38,38,0.08), var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #dc2626, #ec4899)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(220,38,38,.35)",
        }}>
          <TrendingDown size={24} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, letterSpacing: "-0.02em" }}>
            Churn — Análise de Cancelamentos
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            Dados sincronizados do Atlaz · {data?.window_days || days} dias
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, background: "var(--bg-surface-2)",
                        padding: 3, borderRadius: 8 }}>
          {PERIODS.map((p) => (
            <button key={p.days}
                      onClick={() => setDays(p.days)}
                      data-testid={`churn-period-${p.days}`}
                      style={{
                        padding: "6px 12px", border: 0, borderRadius: 6,
                        cursor: "pointer", fontSize: 12, fontWeight: 600,
                        background: days === p.days ? "var(--bg-surface)" : "transparent",
                        color: days === p.days ? "var(--text-primary)" : "var(--text-muted)",
                        boxShadow: days === p.days ? "var(--shadow-sm)" : "none",
                      }}>{p.label}</button>
          ))}
        </div>
        <button onClick={() => load(days)}
                  data-testid="churn-refresh-btn"
                  style={{ padding: 8, border: "1px solid var(--border-default)",
                              background: "var(--bg-surface)", borderRadius: 8,
                              cursor: "pointer", color: "var(--text-muted)" }}>
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        </button>
        <button onClick={generateInsight} disabled={insightLoading}
                  data-testid="churn-ai-insight-btn"
                  style={{
                    padding: "8px 14px", border: 0, borderRadius: 8,
                    background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                    color: "#fff", cursor: insightLoading ? "wait" : "pointer",
                    display: "inline-flex", alignItems: "center", gap: 6,
                    fontSize: 12, fontWeight: 700,
                    boxShadow: "0 4px 14px rgba(99,102,241,0.35)",
                  }}>
          {insightLoading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          Analisar com IA
        </button>
        {history.length > 0 && (
          <div style={{ position: "relative" }}>
            <button onClick={() => setHistoryOpen(!historyOpen)}
                      data-testid="churn-history-btn"
                      style={{
                        padding: 8, border: "1px solid var(--border-default)",
                        background: "var(--bg-surface)", borderRadius: 8,
                        cursor: "pointer", color: "var(--text-muted)",
                        display: "inline-flex", alignItems: "center", gap: 4,
                        fontSize: 11,
                      }}
                      title={`${history.length} briefing(s) no histórico`}>
              <History size={14} />
              <span style={{ fontWeight: 700 }}>{history.length}</span>
            </button>
            {historyOpen && (
              <div data-testid="churn-history-dropdown" style={{
                position: "absolute", top: "calc(100% + 6px)", right: 0,
                width: 320, maxHeight: 360, overflow: "auto",
                background: "var(--bg-surface)",
                border: "1px solid var(--border-default)",
                borderRadius: 10, zIndex: 50,
                boxShadow: "0 12px 32px rgba(0,0,0,0.18)",
                padding: 8,
              }}>
                <div style={{ fontSize: 11, fontWeight: 700,
                                color: "var(--text-muted)",
                                textTransform: "uppercase", letterSpacing: 0.4,
                                padding: "4px 8px 6px" }}>
                  Briefings salvos
                </div>
                {history.map((h) => (
                  <button key={h.id}
                            onClick={() => loadHistoricInsight(h.id)}
                            data-testid={`churn-history-item-${h.id}`}
                            style={{
                              display: "block", width: "100%", textAlign: "left",
                              padding: "8px 10px", border: 0, borderRadius: 6,
                              background: insight?.id === h.id ? "var(--bg-surface-2)" : "transparent",
                              cursor: "pointer", fontSize: 12,
                              borderLeft: insight?.id === h.id ? "3px solid #6366f1" : "3px solid transparent",
                            }}
                            onMouseEnter={(e) => {
                              if (insight?.id !== h.id)
                                e.currentTarget.style.background = "var(--bg-surface-2)";
                            }}
                            onMouseLeave={(e) => {
                              if (insight?.id !== h.id)
                                e.currentTarget.style.background = "transparent";
                            }}>
                    <div style={{ fontWeight: 600,
                                    color: "var(--text-primary)" }}>
                      {h.date} · {h.window_days}d
                    </div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)",
                                    marginTop: 2 }}>
                      {h.based_on?.total_churn ?? 0} churn(s)
                      {h.based_on?.top_reason ? ` · ${h.based_on.top_reason}` : ""}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* AI Insight */}
      {(insight || insightErr || insightLoading) && (
        <div data-testid="churn-ai-insight-card" style={{
          padding: 16, borderRadius: 12,
          background: "linear-gradient(135deg, rgba(99,102,241,0.05), var(--bg-surface) 70%)",
          border: "1px solid rgba(99,102,241,0.25)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <Sparkles size={14} color="#6366f1" />
            <span style={{ fontSize: 13, fontWeight: 800,
                              letterSpacing: "-0.012em" }}>
              Briefing executivo — Claude Sonnet 4.5
            </span>
            {insight && (
              <button onClick={() => setInsightOpen(!insightOpen)}
                        style={{ marginLeft: "auto", padding: 4, border: 0,
                                    background: "transparent", cursor: "pointer",
                                    color: "var(--text-muted)" }}>
                {insightOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
            )}
          </div>
          {insightLoading && (
            <div style={{ color: "var(--text-muted)", fontSize: 12,
                            display: "flex", alignItems: "center", gap: 8 }}>
              <Loader2 size={13} className="animate-spin" />
              Claude está analisando seus dados de churn...
            </div>
          )}
          {insightErr && (
            <div style={{ padding: 10, background: "#fef2f2",
                            color: "#be123c", borderRadius: 8, fontSize: 12 }}>
              {insightErr}
            </div>
          )}
          {insight && insightOpen && (
            <>
              <div style={{
                fontSize: 13, lineHeight: 1.65,
                color: "var(--text-primary)",
                whiteSpace: "pre-wrap",
              }} dangerouslySetInnerHTML={{
                __html: (insight.insight || "")
                  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                  .replace(/\*\*(.+?)\*\*/g, '<strong style="color: var(--text-primary)">$1</strong>')
                  .replace(/^- (.+)$/gm, '<div style="margin: 4px 0 4px 16px; position: relative"><span style="position:absolute;left:-12px;color:#6366f1">•</span>$1</div>'),
              }} />
              <div style={{ marginTop: 12, paddingTop: 10,
                              borderTop: "1px dashed var(--border-default)",
                              display: "flex", alignItems: "center", gap: 10,
                              fontSize: 10, color: "var(--text-muted)" }}>
                <span>Gerado por {insight.model} · {insight.provider} · janela {insight.window_days}d</span>
                {history.length >= 2 && (
                  <button onClick={compareWithPrevious} disabled={comparing}
                            data-testid="churn-compare-btn"
                            style={{
                              marginLeft: "auto",
                              padding: "5px 10px", border: "1px solid #6366f1",
                              background: "transparent", color: "#6366f1",
                              borderRadius: 6, cursor: comparing ? "wait" : "pointer",
                              display: "inline-flex", alignItems: "center", gap: 4,
                              fontSize: 11, fontWeight: 700,
                            }}>
                    {comparing ? <Loader2 size={11} className="animate-spin" /> : <GitCompare size={11} />}
                    Comparar com anterior
                  </button>
                )}
              </div>
            </>
          )}
          {comparison && !comparison.error && (
            <div data-testid="churn-comparison-card" style={{
              marginTop: 12, padding: 12,
              background: "var(--bg-surface-2)",
              border: "1px dashed #6366f1",
              borderRadius: 10,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6,
                              fontSize: 11, fontWeight: 700,
                              color: "#6366f1", marginBottom: 8,
                              textTransform: "uppercase", letterSpacing: 0.4 }}>
                <GitCompare size={12} />
                Comparação com {comparison.prev_label}
              </div>
              <div style={{
                fontSize: 12.5, lineHeight: 1.6,
                color: "var(--text-primary)",
              }} dangerouslySetInnerHTML={{
                __html: (comparison.comparison || "")
                  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                  .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                  .replace(/^- (.+)$/gm, '<div style="margin: 4px 0 4px 16px; position: relative"><span style="position:absolute;left:-12px;color:#6366f1">•</span>$1</div>')
                  .replace(/↑/g, '<span style="color:#dc2626">↑</span>')
                  .replace(/↓/g, '<span style="color:#10b981">↓</span>')
                  .replace(/→/g, '<span style="color:#64748b">→</span>'),
              }} />
            </div>
          )}
          {comparison?.error && (
            <div style={{ marginTop: 10, padding: 8, background: "#fef2f2",
                            color: "#be123c", borderRadius: 6, fontSize: 12 }}>
              Erro ao comparar: {comparison.error}
            </div>
          )}
        </div>
      )}

      {/* Agendamento automático */}
      <ChurnBriefingScheduleCard />

      {/* KPIs */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
                      gap: 12 }}>
        <KpiCard icon={Users} color="#dc2626"
                    label="Churn total"
                    value={fmtNum(k.total_churn)}
                    hint={`${k.finalized} efetivado(s) · ${k.pending} pendente(s)`} />
        <KpiCard icon={ArrowDownRight} color="#f59e0b"
                    label="Taxa de churn"
                    value={`${k.churn_rate_pct ?? 0}%`}
                    hint={`base ${fmtNum(k.total_subscribers)} assinantes ativos`} />
        <KpiCard icon={Clock} color="#0d9488"
                    label="Tempo médio de vida"
                    value={k.avg_lifetime_days != null
                      ? `${Math.round(k.avg_lifetime_days)} dias`
                      : "—"}
                    hint={k.median_lifetime_days != null
                      ? `mediana ${Math.round(k.median_lifetime_days)}d · ${k.lifetime_samples} amostras`
                      : "Sem dados de instalação"} />
        <KpiCard icon={AlertCircle} color="#a855f7"
                    label="Pipeline pendente"
                    value={fmtNum(k.pending)}
                    hint="Pediram cancelamento, ainda não retirado" />
      </div>

      {/* Time series mensal */}
      <Card title="Cancelamentos por mês" subtitle="Últimos 12 meses (independente do filtro de período)">
        {data?.by_month?.length ? (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 6,
                          height: 160, padding: 12,
                          background: "var(--bg-surface-2)",
                          borderRadius: 10 }} data-testid="churn-by-month">
            {data.by_month.map((m) => {
              const h = Math.max(3, (m.count / maxMonth) * 100);
              return (
                <div key={m.month} style={{ flex: 1, display: "flex",
                                                  flexDirection: "column", alignItems: "center",
                                                  gap: 4 }}>
                  <div style={{
                    fontSize: 11, fontWeight: 700,
                    color: m.count > 0 ? "#dc2626" : "var(--text-muted)",
                    fontVariantNumeric: "tabular-nums",
                  }}>{m.count}</div>
                  <div title={`${m.month}: ${m.count} cancelamento(s)`}
                       style={{
                         width: "100%",
                         height: `${h}%`,
                         minHeight: 3,
                         background: m.count === 0
                           ? "var(--border-default)"
                           : "linear-gradient(180deg, #ef4444, #dc2626)",
                         borderRadius: "3px 3px 0 0",
                         transition: "height .35s",
                       }} />
                  <div style={{ fontSize: 10, color: "var(--text-muted)",
                                  whiteSpace: "nowrap" }}>
                    {fmtMonth(m.month)}
                  </div>
                </div>
              );
            })}
          </div>
        ) : <Empty />}
      </Card>

      {/* Motivos + Bairros lado a lado */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
                      gap: 16 }}>
        <Card title="Top motivos" subtitle="Inferido do assunto/relato do chamado"
              icon={AlertCircle}>
          {data?.by_reason?.length ? (
            <div style={{ display: "grid", gap: 8 }} data-testid="churn-by-reason">
              {data.by_reason.map((r, i) => {
                const pct = Math.max(3, (r.count / maxReason) * 100);
                return (
                  <div key={r.label}
                       style={{ display: "grid",
                                  gridTemplateColumns: "150px 1fr 50px",
                                  gap: 10, alignItems: "center", fontSize: 12 }}>
                    <div style={{ fontWeight: 600, whiteSpace: "nowrap",
                                    overflow: "hidden", textOverflow: "ellipsis" }}
                         title={r.label}>
                      {r.label}
                    </div>
                    <div style={{ background: "var(--bg-surface-2)",
                                    height: 16, borderRadius: 4, overflow: "hidden" }}>
                      <div style={{
                        width: `${pct}%`, height: "100%",
                        background: REASON_COLORS[i % REASON_COLORS.length],
                        opacity: 0.85, transition: "width .35s",
                      }} />
                    </div>
                    <div style={{ textAlign: "right", fontWeight: 700,
                                    fontVariantNumeric: "tabular-nums" }}>
                      {r.count}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : <Empty />}
        </Card>

        <Card title="Top bairros" subtitle="Maior concentração de churn"
              icon={MapPin}>
          {data?.by_neighborhood?.length ? (
            <div style={{ display: "grid", gap: 8 }} data-testid="churn-by-neighborhood">
              {data.by_neighborhood.map((n) => {
                const pct = Math.max(3, (n.count / maxNeigh) * 100);
                return (
                  <div key={n.label}
                       style={{ display: "grid",
                                  gridTemplateColumns: "150px 1fr 50px",
                                  gap: 10, alignItems: "center", fontSize: 12 }}>
                    <div style={{ fontWeight: 600, whiteSpace: "nowrap",
                                    overflow: "hidden", textOverflow: "ellipsis" }}
                         title={n.label}>
                      {n.label}
                    </div>
                    <div style={{ background: "var(--bg-surface-2)",
                                    height: 16, borderRadius: 4, overflow: "hidden" }}>
                      <div style={{
                        width: `${pct}%`, height: "100%",
                        background: "#0d9488", opacity: 0.85,
                      }} />
                    </div>
                    <div style={{ textAlign: "right", fontWeight: 700,
                                    fontVariantNumeric: "tabular-nums" }}>
                      {n.count}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : <Empty />}
        </Card>
      </div>

      {/* Split cancelamento vs retirada */}
      <Card title="Pedido × Operação"
            subtitle="Diferença entre cliente pedir cancelamento e equipe retirar equipamento">
        {data?.by_kind ? (
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}
               data-testid="churn-by-kind">
            {[
              { id: "cancelamento", label: "Pedidos de cancelamento", desc: "Cliente solicitou cancelamento" },
              { id: "retirada",      label: "Retiradas de equipamento", desc: "Equipe operacional foi até o cliente" },
            ].map((row) => (
              <div key={row.id} style={{
                flex: "1 1 240px", padding: 14,
                background: "var(--bg-surface-2)", borderRadius: 10,
                borderLeft: `3px solid ${KIND_COLORS[row.id]}`,
              }}>
                <div style={{ fontSize: 11, fontWeight: 700,
                                color: "var(--text-muted)", textTransform: "uppercase",
                                letterSpacing: 0.4 }}>
                  {row.label}
                </div>
                <div style={{ fontSize: 28, fontWeight: 800, marginTop: 4,
                                color: KIND_COLORS[row.id],
                                fontVariantNumeric: "tabular-nums" }}>
                  {data.by_kind[row.id] || 0}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                  {row.desc}
                </div>
              </div>
            ))}
          </div>
        ) : <Empty />}
      </Card>

      {/* Últimos churns */}
      {data?.recent?.length > 0 && (
        <Card title="Últimos cancelamentos finalizados"
              subtitle="20 registros mais recentes"
              icon={Calendar}>
          <div style={{ display: "grid", gap: 4 }} data-testid="churn-recent-list">
            {data.recent.map((r) => (
              <div key={r.ticket_id}
                   style={{ display: "grid",
                              gridTemplateColumns: "1fr 130px 130px 110px",
                              gap: 10, padding: "8px 10px", fontSize: 12,
                              background: "var(--bg-surface-2)", borderRadius: 6,
                              alignItems: "center" }}>
                <span style={{ fontWeight: 600 }}>{r.client_name}</span>
                <span style={{ color: "var(--text-muted)" }}>{r.neighborhood}</span>
                <span style={{
                  fontSize: 10, fontWeight: 700,
                  padding: "3px 7px", borderRadius: 999,
                  background: `${KIND_COLORS[r.kind]}22`,
                  color: KIND_COLORS[r.kind],
                  textAlign: "center", width: "fit-content",
                }}>
                  {r.reason}
                </span>
                <span style={{ color: "var(--text-muted)", fontSize: 10,
                                  textAlign: "right" }}>
                  {r.closed_at ? new Date(r.closed_at).toLocaleDateString("pt-BR") : "—"}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function KpiCard({ icon: Icon, color, label, value, hint }) {
  return (
    <div className="surface" style={{
      padding: 14, borderRadius: 12,
      border: "1px solid var(--border-default)",
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                      fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                      textTransform: "uppercase", letterSpacing: 0.4 }}>
        <Icon size={13} color={color} />
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 800, color,
                      fontVariantNumeric: "tabular-nums",
                      lineHeight: 1.1, marginTop: 2 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.4 }}>
        {hint}
      </div>
    </div>
  );
}

function Card({ title, subtitle, icon: Icon, children }) {
  return (
    <div className="surface" style={{
      padding: 16, borderRadius: 12,
      border: "1px solid var(--border-default)",
    }}>
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6,
                        fontSize: 13, fontWeight: 700, letterSpacing: "-0.012em" }}>
          {Icon && <Icon size={14} color="var(--text-muted)" />}
          {title}
        </div>
        {subtitle && (
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            {subtitle}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

function Empty() {
  return (
    <div style={{ padding: 30, textAlign: "center",
                    color: "var(--text-muted)", fontSize: 12 }}>
      Sem dados no período selecionado.
    </div>
  );
}
