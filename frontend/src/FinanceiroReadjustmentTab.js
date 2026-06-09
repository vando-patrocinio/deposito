import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import {
  TrendingUp, RefreshCw, CheckCircle2, AlertCircle, Calendar,
  ArrowUpRight, Users, Cake, TrendingDown,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Area, AreaChart, ReferenceLine,
} from "recharts";

/**
 * Reajuste Anual — subaba do Financeiro.
 *
 * Lista clientes com reajuste devido (vencidos) e próximos.
 * Permite aplicar individual ou em lote, baseado em índice oficial
 * (IPCA por padrão, configurável por cliente).
 *
 * Backend:
 *   GET  /api/financeiro/reajuste/indices
 *   POST /api/financeiro/reajuste/indices/{name}/refresh
 *   GET  /api/financeiro/reajuste/due?horizon_days=30
 *   POST /api/financeiro/reajuste/apply/{subscriber_id}
 *   POST /api/financeiro/reajuste/apply-all-due
 */
const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
  });

const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("pt-BR");
  } catch {
    return iso;
  }
};

export default function ReadjustmentTab() {
  const [indices, setIndices] = useState([]);
  const [dueData, setDueData] = useState({ due_now: [], upcoming: [] });
  const [horizon, setHorizon] = useState(30);
  const [busy, setBusy] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [refreshingIdx, setRefreshingIdx] = useState(null);
  const [cohort, setCohort] = useState(null);
  const [retention, setRetention] = useState(null);

  const loadIndices = async () => {
    try {
      const r = await api.reajusteIndices();
      setIndices(r.items || []);
    } catch (_e) { /* ignore */ }
  };

  const loadDue = async () => {
    setBusy(true);
    try {
      const r = await api.reajusteDue(horizon);
      setDueData(r || { due_now: [], upcoming: [] });
    } catch (_e) {
      setDueData({ due_now: [], upcoming: [] });
    } finally {
      setBusy(false);
    }
  };

  const loadCohort = async () => {
    try {
      const r = await api.reajusteCohort();
      setCohort(r);
    } catch (_e) { /* ignore */ }
  };

  const loadRetention = async () => {
    try {
      const r = await api.reajusteRetentionCurve();
      setRetention(r);
    } catch (_e) { /* ignore */ }
  };

  useEffect(() => { loadIndices(); loadCohort(); loadRetention(); }, []);
  useEffect(() => { loadDue(); }, [horizon]);

  const refreshIndex = async (name) => {
    setRefreshingIdx(name);
    try {
      await api.reajusteRefreshIndex(name);
      await loadIndices();
    } finally {
      setRefreshingIdx(null);
    }
  };

  const applyOne = async (id, name) => {
    if (!await window.confirm(`Aplicar reajuste em "${name}"?`)) return;
    try {
      await api.reajusteApply(id);
      await loadDue();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };

  const applyAllDue = async () => {
    if (!await window.confirm(
      `Aplicar reajuste em TODOS os ${dueData.due_now.length} ` +
      "clientes vencidos? Esta ação não pode ser desfeita."
    )) return;
    setBatchBusy(true);
    try {
      const r = await api.reajusteApplyAllDue();
      await loadDue();
      await window.alert(
        `✅ Aplicado em ${r.applied} cliente(s)\n` +
        `Aumento total mensal: ${fmtMoney(r.total_revenue_increase)}`
      );
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBatchBusy(false);
    }
  };

  return (
    <div data-testid="fin-readjustment-tab" style={{ display: "grid", gap: 16 }}>
      {/* Cards dos índices oficiais */}
      <Card title="Índices Oficiais — Banco Central / IBGE / FGV">
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          gap: 12,
        }}>
          {indices.map((idx) => (
            <div key={idx.name}
              data-testid={`reajuste-index-${idx.name}`}
              style={{
                padding: 14, borderRadius: 10,
                background: "#f8fafc", border: "1px solid #e2e8f0",
              }}>
              <div style={{
                display: "flex", justifyContent: "space-between",
                alignItems: "flex-start", marginBottom: 8,
              }}>
                <strong style={{ fontSize: 13, color: "#0f172a" }}>
                  {idx.name}
                </strong>
                <button onClick={() => refreshIndex(idx.name)}
                  disabled={refreshingIdx === idx.name}
                  data-testid={`reajuste-refresh-${idx.name}`}
                  style={{
                    border: "none", background: "transparent",
                    cursor: "pointer", color: "#64748b",
                    padding: 2,
                  }}>
                  <RefreshCw size={12}
                    className={refreshingIdx === idx.name ? "spin" : ""} />
                </button>
              </div>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#0f172a" }}>
                {idx.accumulated_12m != null
                  ? `${idx.accumulated_12m.toFixed(2)}%` : "—"}
              </div>
              <div style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>
                Acum. 12m · {idx.last_period || "sem dados"}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Trilha de Clientes por Anos de Casa */}
      {cohort && cohort.total_tracked > 0 && (
        <Card title={
          <span>
            <Cake size={14} style={{
              display: "inline", marginRight: 6, color: "#a855f7" }} />
            Trilha de Aniversário — {cohort.total_tracked} clientes ativos
          </span>
        }>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))",
            gap: 8,
          }}>
            {cohort.cohort.filter((c) => c.total > 0).map((c) => {
              const intensity = Math.min(c.total / 10, 1);
              return (
                <div key={c.year}
                  data-testid={`cohort-year-${c.year}`}
                  title={c.names.join(" · ")}
                  style={{
                    padding: 10, borderRadius: 8,
                    background: `rgba(168, 85, 247, ${0.05 + intensity * 0.20})`,
                    border: `1px solid rgba(168, 85, 247, ${0.20 + intensity * 0.30})`,
                    textAlign: "center",
                    cursor: "default",
                  }}>
                  <div style={{ fontSize: 18, fontWeight: 700,
                                 color: "#7e22ce" }}>
                    {c.year}{c.year === 20 ? "+" : ""}
                  </div>
                  <div style={{ fontSize: 9, color: "#a855f7",
                                 textTransform: "uppercase", fontWeight: 600,
                                 letterSpacing: 0.3 }}>
                    {c.year === 1 ? "ano" : "anos"}
                  </div>
                  <div style={{ marginTop: 4, fontSize: 14, fontWeight: 700,
                                 color: "#0f172a" }}>
                    {c.total}
                  </div>
                  <div style={{ fontSize: 9, color: "#64748b" }}>
                    clientes
                  </div>
                  {c.due_this_month > 0 && (
                    <div style={{
                      marginTop: 4, padding: "1px 6px", borderRadius: 4,
                      background: "#fef3c7", color: "#92400e",
                      fontSize: 9, fontWeight: 700,
                    }}>
                      {c.due_this_month} aniv.
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: "#16a34a",
                                 fontWeight: 600, marginTop: 2 }}>
                    {fmtMoney(c.active_value)}
                  </div>
                </div>
              );
            })}
          </div>
          {(cohort.untracked.no_install_date > 0 ||
             cohort.untracked.less_than_1_year > 0) && (
            <div style={{ marginTop: 12, padding: "8px 12px",
                           background: "#f8fafc", borderRadius: 6,
                           fontSize: 11, color: "#64748b" }}>
              <Users size={11} style={{ display: "inline", marginRight: 4 }} />
              Não exibidos: {cohort.untracked.less_than_1_year} cliente(s) com menos de 1 ano · {" "}
              {cohort.untracked.no_install_date} sem data de instalação cadastrada
            </div>
          )}
        </Card>
      )}

      {/* Curva de Retenção — % de clientes ainda ativos por ano */}
      {retention && retention.base_year_0 > 0 && (() => {
        // Encontra ano de maior churn (ponto de virada)
        const points = retention.curve || [];
        const churnPeak = points.slice(1).reduce(
          (max, p) => p.churn_pct_from_prev > (max?.churn_pct_from_prev || 0) ? p : max,
          null,
        );
        return (
          <Card title={
            <div style={{ display: "flex", justifyContent: "space-between",
                           alignItems: "center", width: "100%" }}>
              <span>
                <TrendingDown size={14} style={{
                  display: "inline", marginRight: 6, color: "#f28c28" }} />
                Curva de Retenção · base {retention.base_year_0} cliente(s)
              </span>
              {churnPeak && churnPeak.churn_pct_from_prev > 0 && (
                <span style={{
                  fontSize: 11, padding: "3px 8px", borderRadius: 4,
                  background: "#fef3c7", color: "#92400e", fontWeight: 600,
                }}>
                  Pico de churn: ano {churnPeak.year} (−{churnPeak.churn_pct_from_prev.toFixed(1)}%)
                </span>
              )}
            </div>
          }>
            <div style={{ width: "100%", height: 280 }}>
              <ResponsiveContainer>
                <AreaChart data={points}
                  margin={{ top: 10, right: 30, left: 0, bottom: 10 }}>
                  <defs>
                    <linearGradient id="retentionFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#f28c28" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#f28c28" stopOpacity={0.03} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="year"
                    label={{ value: "Anos de casa", position: "insideBottom",
                              offset: -5, fontSize: 11 }}
                    tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 100]}
                    tickFormatter={(v) => `${v}%`}
                    tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v, name) => {
                      if (name === "Retenção") return [`${v}%`, name];
                      if (name === "Churn") return [`${v}%`, name];
                      return [v, name];
                    }}
                    labelFormatter={(y) => `Ano ${y}`}
                    contentStyle={{ borderRadius: 6, fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={80} stroke="#16a34a" strokeDasharray="3 3"
                    label={{ value: "Meta 80%", fontSize: 10, fill: "#16a34a" }} />
                  <Area type="monotone" dataKey="retention_pct" name="Retenção"
                    stroke="#f28c28" strokeWidth={2.5}
                    fill="url(#retentionFill)" />
                  <Line type="monotone" dataKey="churn_pct_from_prev"
                    name="Churn" stroke="#dc2626" strokeWidth={1.5}
                    strokeDasharray="4 4" dot={{ r: 2 }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div style={{
              marginTop: 8, padding: "8px 12px", background: "#f8fafc",
              borderRadius: 6, fontSize: 11, color: "#64748b",
              lineHeight: 1.5,
            }}>
              <strong style={{ color: "#0f172a" }}>Como interpretar:</strong>{" "}
              A linha azul é o % de clientes ainda ativos relativo ao ano 0.
              A pontilhada vermelha é o % que cancelou de um ano pro outro.
              Meta de retenção saudável: ≥80% no ano 1.{" "}
              {churnPeak && churnPeak.year > 0 && (
                <>O ano <strong>{churnPeak.year}</strong> é seu ponto crítico —
                considere campanha preventiva 2 meses antes.</>
              )}
            </div>
          </Card>
        );
      })()}

      {/* Reajustes vencidos */}
      <Card title={
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", width: "100%" }}>
          <span>
            <AlertCircle size={14} style={{
              display: "inline", marginRight: 6, color: "#dc2626" }} />
            Vencidos — {dueData.due_now.length} cliente(s)
          </span>
          {dueData.due_now.length > 0 && (
            <button
              data-testid="reajuste-apply-all"
              onClick={applyAllDue} disabled={batchBusy}
              style={{
                padding: "6px 14px", borderRadius: 6,
                background: "#dc2626", color: "white",
                border: "none", cursor: "pointer", fontWeight: 600,
                fontSize: 12,
              }}>
              {batchBusy ? "Aplicando…" : "Aplicar todos vencidos"}
            </button>
          )}
        </div>
      }>
        <DueTable items={dueData.due_now} onApply={applyOne} busy={busy} />
      </Card>

      {/* Próximos */}
      <Card title={
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span>
            <Calendar size={14} style={{
              display: "inline", marginRight: 6, color: "#4b1d7a" }} />
            Próximos {horizon} dias — {dueData.upcoming.length} cliente(s)
          </span>
          <select value={horizon} onChange={(e) => setHorizon(+e.target.value)}
            data-testid="reajuste-horizon"
            style={{
              padding: "4px 8px", borderRadius: 6,
              border: "1px solid #e2e8f0", fontSize: 12,
            }}>
            <option value={30}>30 dias</option>
            <option value={60}>60 dias</option>
            <option value={90}>90 dias</option>
            <option value={180}>180 dias</option>
            <option value={365}>1 ano</option>
          </select>
        </div>
      }>
        <DueTable items={dueData.upcoming} onApply={applyOne} busy={busy} />
      </Card>
    </div>
  );
}

function DueTable({ items, onApply, busy }) {
  if (busy && items.length === 0) {
    return <div style={{ padding: 20, color: "#64748b" }}>Carregando…</div>;
  }
  if (items.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "30px 20px",
                     color: "#64748b" }}>
        <CheckCircle2 size={28} style={{ opacity: 0.4 }} />
        <p style={{ margin: "8px 0 0", fontSize: 13 }}>
          Nenhum reajuste pendente nesta janela.
        </p>
      </div>
    );
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table data-testid="reajuste-table"
        style={{ width: "100%", borderCollapse: "collapse",
                  fontSize: 12 }}>
        <thead>
          <tr style={{ background: "#f8fafc", textAlign: "left" }}>
            <th style={th}>Cliente</th>
            <th style={th}>Plano</th>
            <th style={th}>Atual</th>
            <th style={th}>Índice</th>
            <th style={th}>%</th>
            <th style={th}>Novo Valor</th>
            <th style={th}>Diferença</th>
            <th style={th}>Data Reajuste</th>
            <th style={th}>Ação</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.subscriber_id}
              data-testid={`reajuste-row-${it.subscriber_id}`}
              style={{ borderTop: "1px solid #e2e8f0" }}>
              <td style={td}>
                <div style={{ fontWeight: 600 }}>{it.name}</div>
                {it.external_code && (
                  <div style={{ fontSize: 10, color: "#94a3b8" }}>
                    Cód: {it.external_code}
                  </div>
                )}
              </td>
              <td style={td}>{it.plan_name || "—"}</td>
              <td style={td}>{fmtMoney(it.current_price)}</td>
              <td style={td}>
                <span style={{
                  padding: "2px 6px", borderRadius: 4, fontSize: 10,
                  background: "#dbeafe", color: "#1e40af", fontWeight: 600,
                }}>
                  {it.index_name}
                </span>
              </td>
              <td style={{ ...td, color: "#dc2626", fontWeight: 600 }}>
                +{(it.accumulated_pct || 0).toFixed(2)}%
              </td>
              <td style={{ ...td, fontWeight: 700 }}>
                {fmtMoney(it.new_price)}
              </td>
              <td style={td}>
                <ArrowUpRight size={11} style={{
                  display: "inline", color: "#16a34a", marginRight: 2 }} />
                <span style={{ color: "#16a34a", fontWeight: 600 }}>
                  +{fmtMoney(it.diff)}
                </span>
              </td>
              <td style={td}>{fmtDate(it.next_readjustment_at)}</td>
              <td style={td}>
                <button
                  data-testid={`reajuste-apply-${it.subscriber_id}`}
                  onClick={() => onApply(it.subscriber_id, it.name)}
                  style={{
                    padding: "4px 10px", borderRadius: 5,
                    background: it.is_due ? "#16a34a" : "#cbd5e1",
                    color: "white", border: "none", cursor: "pointer",
                    fontSize: 11, fontWeight: 600,
                  }}>
                  Aplicar
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const th = { padding: "8px 10px", fontSize: 11, fontWeight: 700,
              color: "#64748b", textTransform: "uppercase", letterSpacing: 0.3 };
const td = { padding: "10px", verticalAlign: "middle" };
