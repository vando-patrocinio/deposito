/**
 * RevenueOpsPanel.jsx — FASE 1 da Constituição V3.0
 *
 * Responde em tempo real:
 *   "Quanto dinheiro a IA gerou este mês?"
 *
 * KPIs principais:
 *   - Receita Recuperada
 *   - Receita Gerada
 *   - Churn Evitado
 *   - Custo Economizado
 *   - ROI
 *   - Top templates / canais / ações
 *   - Timeline diária
 *
 * Consome /api/ai-center/revenue/*
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, Legend, Cell,
} from "recharts";
import { api } from "@/api";

const PERIODS = [
  { value: "MTD",  label: "Mês atual" },
  { value: "YTD",  label: "Ano atual" },
  { value: "7d",   label: "7 dias" },
  { value: "30d",  label: "30 dias" },
  { value: "90d",  label: "90 dias" },
  { value: "all",  label: "Tudo" },
];

const KIND_COLOR = {
  recovered: "#10b981",
  generated: "#3b82f6",
  churn_prevented: "#f59e0b",
  cost_saved: "#a855f7",
};

const KIND_LABEL = {
  recovered: "Receita Recuperada",
  generated: "Receita Gerada",
  churn_prevented: "Churn Evitado",
  cost_saved: "Custo Economizado",
};

function fmtBRL(n) {
  return (n || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2,
  });
}

function KpiCard({ label, value, sub, color, testid }) {
  return (
    <div
      data-testid={testid}
      style={{
        background: "linear-gradient(140deg, #0b1220 0%, #111827 100%)",
        border: `1px solid ${color}33`,
        borderRadius: 14,
        padding: 22,
        boxShadow: `0 4px 24px ${color}1a`,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div style={{
        position: "absolute", top: 0, right: 0, width: 6, height: "100%",
        background: color, opacity: 0.7,
      }} />
      <div style={{ color: "#94a3b8", fontSize: 11,
                    letterSpacing: 1.4, textTransform: "uppercase",
                    fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ fontSize: 30, fontWeight: 800, color: "#f1f5f9",
                    marginTop: 8, lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ marginTop: 6, fontSize: 12, color: "#64748b" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function PanelCard({ title, right, children, testid }) {
  return (
    <div
      data-testid={testid}
      style={{
        background: "#0f172a",
        border: "1px solid #1e293b",
        borderRadius: 14,
        padding: 20,
        color: "#e2e8f0",
        minHeight: 280,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, color: "#7dd3fc",
                     fontWeight: 600 }}>{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}


export default function RevenueOpsPanel() {
  const [period, setPeriod] = useState("MTD");
  const [summary, setSummary] = useState(null);
  const [byTemplate, setByTemplate] = useState([]);
  const [byChannel, setByChannel] = useState([]);
  const [byAction, setByAction] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [topActions, setTopActions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, t, ch, a, tl, top] = await Promise.all([
        api.revenueSummary(period),
        api.revenueByTemplate(period, 10),
        api.revenueByChannel(period),
        api.revenueByActionType(period),
        api.revenueTimeline(period, "day"),
        api.revenueTopActions(period, 10),
      ]);
      setSummary(s);
      setByTemplate(t.items || []);
      setByChannel(ch.items || []);
      setByAction(a.items || []);
      setTimeline(tl.items || []);
      setTopActions(top.items || []);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "Erro ao carregar");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-line */ }, [period]);

  // Timeline para o LineChart — flat por dia
  const tlData = useMemo(() => {
    return timeline.map((b) => ({
      day: b.bucket,
      recovered: b.by_kind?.recovered || 0,
      generated: b.by_kind?.generated || 0,
      churn_prevented: b.by_kind?.churn_prevented || 0,
      cost_saved: b.by_kind?.cost_saved || 0,
      total: b.total_BRL || 0,
    }));
  }, [timeline]);

  const kpis = summary?.kpis || {};

  return (
    <div style={{ padding: 24, background: "#020617", minHeight: "100vh" }}
         data-testid="revenue-ops-panel">
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ color: "#f1f5f9", fontSize: 26, fontWeight: 800,
                       margin: 0, letterSpacing: -0.5 }}>
            RevenueOps IA
          </h1>
          <div style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>
            Quanto dinheiro a IA gerou? · Fase 1 da Constituição SmartProv V3.0
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            data-testid="period-select"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            style={{
              background: "#0f172a", color: "#e2e8f0",
              border: "1px solid #1e293b", borderRadius: 8,
              padding: "8px 12px", fontSize: 14,
            }}
          >
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <button
            data-testid="reload-btn"
            onClick={load}
            style={{
              background: "#0ea5e9", color: "#fff", border: "none",
              borderRadius: 8, padding: "8px 14px", fontSize: 13,
              cursor: "pointer", fontWeight: 600,
            }}
          >
            {loading ? "Atualizando…" : "Atualizar"}
          </button>
        </div>
      </div>

      {error && (
        <div data-testid="error-banner"
             style={{ background: "#7f1d1d", color: "#fee2e2", padding: 12,
                      borderRadius: 8, marginBottom: 16, fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* KPI Cards */}
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 16, marginBottom: 24 }}>
        <KpiCard
          testid="kpi-recovered"
          label="Receita Recuperada"
          value={fmtBRL(kpis.recovered_BRL)}
          sub={`${summary?.detail?.recovered?.count || 0} ações · ticket méd. ${fmtBRL(summary?.detail?.recovered?.avg_BRL)}`}
          color={KIND_COLOR.recovered}
        />
        <KpiCard
          testid="kpi-generated"
          label="Receita Gerada"
          value={fmtBRL(kpis.generated_BRL)}
          sub={`${summary?.detail?.generated?.count || 0} ações (upsell/cross-sell)`}
          color={KIND_COLOR.generated}
        />
        <KpiCard
          testid="kpi-churn-prevented"
          label="Churn Evitado"
          value={fmtBRL(kpis.churn_prevented_BRL)}
          sub={`${summary?.detail?.churn_prevented?.count || 0} clientes retidos`}
          color={KIND_COLOR.churn_prevented}
        />
        <KpiCard
          testid="kpi-cost-saved"
          label="Custo Economizado"
          value={fmtBRL(kpis.cost_saved_BRL)}
          sub={`${summary?.detail?.cost_saved?.count || 0} visitas/horas evitadas`}
          color={KIND_COLOR.cost_saved}
        />
        <KpiCard
          testid="kpi-total"
          label="TOTAL IA"
          value={fmtBRL(kpis.total_BRL)}
          sub={`${kpis.actions_count || 0} ações atribuídas`}
          color="#7dd3fc"
        />
      </div>

      {/* Timeline */}
      <div style={{ marginBottom: 24 }}>
        <PanelCard
          testid="timeline-card"
          title="Timeline diária — Receita por categoria"
          right={
            <span style={{ fontSize: 11, color: "#64748b" }}>
              {tlData.length} dias com atividade
            </span>
          }
        >
          {tlData.length === 0 ? (
            <div style={{ color: "#475569", fontSize: 13, padding: 20 }}>
              Sem dados no período selecionado.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={tlData}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="day" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11}
                       tickFormatter={(v) => `R$ ${v.toLocaleString("pt-BR")}`} />
                <Tooltip
                  contentStyle={{ background: "#0f172a",
                                  border: "1px solid #1e293b",
                                  borderRadius: 8 }}
                  formatter={(v) => fmtBRL(v)}
                />
                <Legend />
                <Line type="monotone" dataKey="recovered"
                      name="Recuperada"
                      stroke={KIND_COLOR.recovered} strokeWidth={2} />
                <Line type="monotone" dataKey="generated"
                      name="Gerada"
                      stroke={KIND_COLOR.generated} strokeWidth={2} />
                <Line type="monotone" dataKey="churn_prevented"
                      name="Churn Evitado"
                      stroke={KIND_COLOR.churn_prevented} strokeWidth={2} />
                <Line type="monotone" dataKey="cost_saved"
                      name="Custo Poupado"
                      stroke={KIND_COLOR.cost_saved} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </PanelCard>
      </div>

      {/* Grid: by_template + by_channel + by_action_type */}
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
                    gap: 16, marginBottom: 24 }}>
        <PanelCard testid="by-template-card" title="Top Templates (R$)">
          {byTemplate.length === 0 ? (
            <div style={{ color: "#475569", padding: 20, fontSize: 13 }}>
              Sem dados.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(byTemplate.length * 36, 200)}>
              <BarChart data={byTemplate} layout="vertical"
                        margin={{ left: 0, right: 12 }}>
                <XAxis type="number" stroke="#64748b" fontSize={11}
                       tickFormatter={(v) => `R$ ${(v/1000).toFixed(1)}k`} />
                <YAxis type="category" dataKey="template" stroke="#94a3b8"
                       fontSize={11} width={150} />
                <Tooltip
                  contentStyle={{ background: "#0f172a",
                                  border: "1px solid #1e293b" }}
                  formatter={(v) => fmtBRL(v)} />
                <Bar dataKey="total_BRL" fill="#10b981" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </PanelCard>

        <PanelCard testid="by-channel-card" title="Por Canal">
          {byChannel.length === 0 ? (
            <div style={{ color: "#475569", padding: 20, fontSize: 13 }}>
              Sem dados.
            </div>
          ) : (
            <table style={{ width: "100%", color: "#cbd5e1",
                            fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "#64748b", textAlign: "left" }}>
                  <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Canal</th>
                  <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>R$</th>
                  <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Ações</th>
                </tr>
              </thead>
              <tbody>
                {byChannel.map((c) => (
                  <tr key={c.channel} data-testid={`channel-row-${c.channel}`}>
                    <td style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>
                      {c.channel}
                    </td>
                    <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                                 color: "#10b981", fontWeight: 600 }}>
                      {fmtBRL(c.total_BRL)}
                    </td>
                    <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                                 color: "#94a3b8" }}>{c.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </PanelCard>

        <PanelCard testid="by-action-card" title="Por Tipo de Ação">
          {byAction.length === 0 ? (
            <div style={{ color: "#475569", padding: 20, fontSize: 13 }}>
              Sem dados.
            </div>
          ) : (
            <table style={{ width: "100%", color: "#cbd5e1",
                            fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "#64748b", textAlign: "left" }}>
                  <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Ação</th>
                  <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>R$</th>
                  <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Qtd</th>
                </tr>
              </thead>
              <tbody>
                {byAction.map((a) => (
                  <tr key={a.action_type} data-testid={`action-row-${a.action_type}`}>
                    <td style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>
                      {a.action_type}
                    </td>
                    <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                                 color: "#10b981", fontWeight: 600 }}>
                      {fmtBRL(a.total_BRL)}
                    </td>
                    <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                                 color: "#94a3b8" }}>{a.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </PanelCard>
      </div>

      {/* Top ações individuais */}
      <PanelCard testid="top-actions-card"
                 title="Top 10 ações por receita atribuída"
                 right={<span style={{ fontSize: 11, color: "#64748b" }}>
                          recente primeiro
                        </span>}>
        {topActions.length === 0 ? (
          <div style={{ color: "#475569", padding: 20, fontSize: 13 }}>
            Sem dados.
          </div>
        ) : (
          <table style={{ width: "100%", color: "#cbd5e1",
                          fontSize: 13, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: "#64748b", textAlign: "left" }}>
                <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>#</th>
                <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Cliente</th>
                <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Tipo</th>
                <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>R$</th>
                <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Template</th>
                <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Canal</th>
                <th style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>Reconhec.</th>
              </tr>
            </thead>
            <tbody>
              {topActions.map((a, i) => (
                <tr key={a.id} data-testid={`top-action-${i+1}`}>
                  <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                               color: "#64748b" }}>{i+1}</td>
                  <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                               fontFamily: "monospace", fontSize: 12 }}>
                    {a.subscriber_id || "—"}
                  </td>
                  <td style={{ padding: 8, borderBottom: "1px solid #1e293b" }}>
                    <span style={{ background: KIND_COLOR[a.kind] + "33",
                                   color: KIND_COLOR[a.kind],
                                   padding: "2px 8px", borderRadius: 6,
                                   fontSize: 11, fontWeight: 600 }}>
                      {KIND_LABEL[a.kind] || a.kind}
                    </span>
                  </td>
                  <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                               color: "#10b981", fontWeight: 600 }}>
                    {fmtBRL(a.amount_BRL)}
                  </td>
                  <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                               color: "#94a3b8", fontSize: 12 }}>
                    {a.template || "—"}
                  </td>
                  <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                               color: "#94a3b8", fontSize: 12 }}>
                    {a.channel || "—"}
                  </td>
                  <td style={{ padding: 8, borderBottom: "1px solid #1e293b",
                               color: "#64748b", fontSize: 11 }}>
                    {a.recognized_at?.split("T")[0]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </PanelCard>

      <div style={{ marginTop: 24, color: "#475569", fontSize: 11,
                    textAlign: "center" }}>
        SmartProv V3.0 · Fase 1 RevenueOps · Atualizado automaticamente
      </div>
    </div>
  );
}
