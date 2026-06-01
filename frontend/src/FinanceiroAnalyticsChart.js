import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, Area, AreaChart,
} from "recharts";
import { TrendingUp, TrendingDown, Activity, Equal } from "lucide-react";

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
  });

const RANGES = [
  { v: "1d", l: "Hoje (D+1)" },
  { v: "7d", l: "7 dias" },
  { v: "30d", l: "30 dias" },
  { v: "3m", l: "3 meses" },
  { v: "6m", l: "6 meses" },
  { v: "1y", l: "1 ano" },
  { v: "all", l: "5 anos" },
  { v: "custom", l: "Personalizado" },
];

function _todayStr() {
  return new Date().toISOString().slice(0, 10);
}
function _daysAgoStr(d) {
  const x = new Date(); x.setDate(x.getDate() - d);
  return x.toISOString().slice(0, 10);
}

const PERIODS = [
  { v: "day", l: "Dia" },
  { v: "month", l: "Mês" },
  { v: "year", l: "Ano" },
];

const REGULARITY_LABEL = {
  regular: { c: "#16a34a", l: "Regular", icon: Equal },
  moderada: { c: "#ca8a04", l: "Moderada", icon: Activity },
  irregular: { c: "#dc2626", l: "Irregular", icon: TrendingDown },
  sem_dados: { c: "#94a3b8", l: "Sem dados", icon: Equal },
};

const preset_btn = {
  padding: "6px 10px",
  borderRadius: 8,
  border: "1px solid #cbd5e1",
  background: "#f8fafc",
  color: "#0f172a",
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
  transition: "background 0.15s ease",
};

/**
 * Painel comparativo Recebimentos vs Despesas + regularidade.
 * Gráfico de linha com séries sobrepostas + métricas de média e CV.
 */
export default function AnalyticsChart() {
  const [range, setRange] = useState("30d");
  const [period, setPeriod] = useState("day");
  const [customFrom, setCustomFrom] = useState(_daysAgoStr(30));
  const [customTo, setCustomTo] = useState(_todayStr());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [chartType, setChartType] = useState("line"); // 'line' | 'area'
  // iter180 — botão de sync manual do Atlaz dentro do próprio gráfico
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

  async function reload() {
    setLoading(true);
    setError("");
    try {
      let url = `/financeiro/analytics?range=${range}&period=${period}`;
      if (range === "custom") {
        if (!customFrom || !customTo) {
          setError("Selecione data inicial e final");
          setData(null);
          setLoading(false);
          return;
        }
        if (customFrom > customTo) {
          setError("Data inicial deve ser anterior à final");
          setData(null);
          setLoading(false);
          return;
        }
        url += `&from_date=${customFrom}&to_date=${customTo}`;
      }
      const r = await api._client.get(url).then((r) => r.data);
      setData(r);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }
  useEffect(() => { reload(); }, [range, period, customFrom, customTo]); // eslint-disable-line

  // iter180 — Sync manual de pagamentos do Atlaz (sem sair da tela).
  async function syncFromAtlaz() {
    if (syncing) return;
    setSyncing(true); setSyncMsg("");
    try {
      const r = await api._client.post(
        "/atlaz-financeiro/sync-now?days_back=30&days_forward=15",
      ).then((r) => r.data);
      const ins = r?.inserted || 0;
      const upd = r?.updated || 0;
      setSyncMsg(`✓ ${ins} novas · ${upd} atualizadas`);
      // Recarrega o gráfico depois do sync (pagamentos novos podem mudar o range)
      await reload();
    } catch (e) {
      setSyncMsg(`Falha: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setSyncing(false);
      // Limpa mensagem depois de 6s
      setTimeout(() => setSyncMsg(""), 6000);
    }
  }

  // Auto-ajusta period se range for muito longo/curto
  useEffect(() => {
    if (["1d", "7d"].includes(range) && period !== "day") setPeriod("day");
    if (["1y", "all"].includes(range) && period === "day") setPeriod("month");
  }, [range]); // eslint-disable-line

  const incomeReg = data ? REGULARITY_LABEL[data.income_metrics.regularity]
                            : REGULARITY_LABEL.sem_dados;
  const expenseReg = data ? REGULARITY_LABEL[data.expense_metrics.regularity]
                              : REGULARITY_LABEL.sem_dados;

  return (
    <Card title="Análise Recebimentos vs Despesas">
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", gap: 12, flexWrap: "wrap",
                       margin: "0 0 14px" }}>
        <p style={{ color: "#64748b", fontSize: 13, margin: 0, flex: 1,
                       minWidth: 240 }}>
          Compare a regularidade dos recebimentos (lançamentos manuais +
          faturas pagas dos assinantes via Atlaz) contra as despesas operacionais.
        </p>
        <div style={{ display: "flex", flexDirection: "column",
                          alignItems: "flex-end", gap: 4 }}>
          <button data-testid="atlaz-sync-now-btn"
                  onClick={syncFromAtlaz}
                  disabled={syncing}
                  style={{
                    padding: "8px 14px", borderRadius: 8,
                    background: syncing ? "#94a3b8" : "#0e7490",
                    color: "#fff", border: "none",
                    fontSize: 12, fontWeight: 700, cursor: syncing ? "wait" : "pointer",
                    display: "flex", alignItems: "center", gap: 6,
                    whiteSpace: "nowrap",
                  }}>
            <span style={{ fontSize: 14, lineHeight: 1 }}>
              {syncing ? "⟳" : "⤓"}
            </span>
            {syncing ? "Sincronizando..." : "Atualizar do Atlaz"}
          </button>
          {syncMsg && (
            <span data-testid="atlaz-sync-msg"
                  style={{ fontSize: 11, color: syncMsg.startsWith("Falha")
                                ? "#dc2626" : "#16a34a", fontWeight: 600 }}>
              {syncMsg}
            </span>
          )}
        </div>
      </div>

      {/* Controles */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16,
                    marginBottom: 14, justifyContent: "space-between",
                    alignItems: "center" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {RANGES.map((r) => (
            <button key={r.v} onClick={() => setRange(r.v)}
              data-testid={`analytics-range-${r.v}`}
              style={{
                padding: "6px 12px", borderRadius: 8,
                background: range === r.v ? "#0f172a" : "#f1f5f9",
                color: range === r.v ? "#fff" : "#64748b",
                fontSize: 12, fontWeight: 600,
                border: "none", cursor: "pointer",
              }}>{r.l}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "#94a3b8",
                          fontWeight: 700, textTransform: "uppercase" }}>
            Agrupar
          </span>
          {PERIODS.map((p) => (
            <button key={p.v} onClick={() => setPeriod(p.v)}
              data-testid={`analytics-period-${p.v}`}
              style={{
                padding: "6px 12px", borderRadius: 8,
                background: period === p.v ? "#0e7490" : "#ecfeff",
                color: period === p.v ? "#fff" : "#0e7490",
                fontSize: 12, fontWeight: 600,
                border: "none", cursor: "pointer",
              }}>{p.l}</button>
          ))}
        </div>
      </div>

      {/* Date pickers (visível quando range=custom) */}
      {range === "custom" && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: 12,
          padding: 12, marginBottom: 14,
          background: "#f8fafc", borderRadius: 10,
          border: "1px solid #e2e8f0",
          alignItems: "center",
        }} data-testid="analytics-custom-range">
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 11, color: "#64748b",
                            fontWeight: 700, textTransform: "uppercase" }}>
              De
            </span>
            <input type="date" value={customFrom} max={customTo}
              onChange={(e) => setCustomFrom(e.target.value)}
              data-testid="analytics-custom-from"
              style={{
                padding: "8px 10px", borderRadius: 8,
                border: "1px solid #cbd5e1", fontSize: 13,
                color: "#0f172a", background: "#fff",
              }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 11, color: "#64748b",
                            fontWeight: 700, textTransform: "uppercase" }}>
              Até
            </span>
            <input type="date" value={customTo} min={customFrom}
              max={_todayStr()}
              onChange={(e) => setCustomTo(e.target.value)}
              data-testid="analytics-custom-to"
              style={{
                padding: "8px 10px", borderRadius: 8,
                border: "1px solid #cbd5e1", fontSize: 13,
                color: "#0f172a", background: "#fff",
              }} />
          </label>
          <div style={{ display: "flex", gap: 4, marginLeft: 4 }}>
            <button onClick={() => {
                const d = new Date();
                setCustomFrom(new Date(d.getFullYear(), d.getMonth(), 1)
                  .toISOString().slice(0, 10));
                setCustomTo(_todayStr());
              }}
              style={preset_btn} data-testid="analytics-preset-this-month">
              Este mês
            </button>
            <button onClick={() => {
                const d = new Date();
                setCustomFrom(new Date(d.getFullYear(), d.getMonth() - 1, 1)
                  .toISOString().slice(0, 10));
                setCustomTo(new Date(d.getFullYear(), d.getMonth(), 0)
                  .toISOString().slice(0, 10));
              }}
              style={preset_btn} data-testid="analytics-preset-last-month">
              Mês passado
            </button>
            <button onClick={() => {
                const d = new Date();
                setCustomFrom(new Date(d.getFullYear(), 0, 1)
                  .toISOString().slice(0, 10));
                setCustomTo(_todayStr());
              }}
              style={preset_btn} data-testid="analytics-preset-ytd">
              Ano corrente
            </button>
          </div>
        </div>
      )}

      {error && (
        <div style={{ padding: 10, background: "#fee2e2", color: "#991b1b",
                      borderRadius: 8, fontSize: 12, marginBottom: 10 }}>
          {error}
        </div>
      )}

      {loading || !data ? (
        <div style={{ color: "#94a3b8", padding: 20 }}>Carregando…</div>
      ) : (
        <>
          {/* Métricas de regularidade */}
          <div style={{ display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                        gap: 10, marginBottom: 16 }}>
            <MetricCard
              label="Média Recebimentos"
              value={fmtMoney(data.income_metrics.mean)}
              footer={
                <RegBadge reg={incomeReg}
                          cv={data.income_metrics.cv_pct} />
              }
              icon={TrendingUp} color="#16a34a"
            />
            <MetricCard
              label="Média Despesas"
              value={fmtMoney(data.expense_metrics.mean)}
              footer={
                <RegBadge reg={expenseReg}
                          cv={data.expense_metrics.cv_pct} />
              }
              icon={TrendingDown} color="#dc2626"
            />
            <MetricCard
              label="Resultado do período"
              value={fmtMoney(data.totals.net)}
              footer={
                <span style={{ fontSize: 11,
                                color: data.totals.net >= 0 ? "#16a34a" : "#dc2626",
                                fontWeight: 600 }}>
                  {data.totals.net >= 0 ? "🟢 Positivo" : "🔴 Negativo"}
                </span>
              }
              icon={Activity}
              color={data.totals.net >= 0 ? "#16a34a" : "#dc2626"}
            />
            <MetricCard
              label="Total Recebimentos"
              value={fmtMoney(data.totals.income)}
              footer={
                <span style={{ fontSize: 11, color: "#64748b" }}>
                  {data.income_metrics.active_periods || 0} períodos ativos
                </span>
              }
              icon={TrendingUp} color="#0f172a"
            />
          </div>

          {/* Toggle chart type */}
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            {[{ v: "line", l: "Linha" }, { v: "area", l: "Área" }].map((t) => (
              <button key={t.v} onClick={() => setChartType(t.v)}
                style={{
                  padding: "4px 10px", borderRadius: 6,
                  background: chartType === t.v ? "#e2e8f0" : "transparent",
                  color: "#64748b", fontSize: 11, fontWeight: 600,
                  border: "1px solid #e2e8f0", cursor: "pointer",
                }}>{t.l}</button>
            ))}
          </div>

          {/* Gráfico */}
          <div style={{ height: 340, marginTop: 4, minHeight: 200 }}
                data-testid="analytics-chart">
            <ResponsiveContainer width="100%" height="100%" minHeight={200}>
              {chartType === "area" ? (
                <AreaChart data={data.series}>
                  <defs>
                    <linearGradient id="gIncome" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#16a34a" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#16a34a" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gExpense" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#dc2626" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#dc2626" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }}
                          tickFormatter={(v) => `R$${v.toLocaleString("pt-BR")}`} />
                  <Tooltip formatter={(v) => fmtMoney(v)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" dataKey="income" name="Recebimentos"
                        stroke="#16a34a" strokeWidth={2.5}
                        fill="url(#gIncome)" />
                  <Area type="monotone" dataKey="expense" name="Despesas"
                        stroke="#dc2626" strokeWidth={2.5}
                        fill="url(#gExpense)" />
                </AreaChart>
              ) : (
                <LineChart data={data.series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }}
                          tickFormatter={(v) => `R$${v.toLocaleString("pt-BR")}`} />
                  <Tooltip formatter={(v) => fmtMoney(v)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="income" name="Recebimentos"
                        stroke="#16a34a" strokeWidth={2.5}
                        dot={{ r: 3 }} activeDot={{ r: 5 }} />
                  <Line type="monotone" dataKey="expense" name="Despesas"
                        stroke="#dc2626" strokeWidth={2.5}
                        dot={{ r: 3 }} activeDot={{ r: 5 }} />
                  <Line type="monotone" dataKey="net" name="Resultado"
                        stroke="#3b82f6" strokeWidth={1.5}
                        strokeDasharray="6 4"
                        dot={false} />
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>

          <div style={{ marginTop: 14, padding: 12, background: "#f8fafc",
                        borderRadius: 8, fontSize: 12, color: "#475569",
                        lineHeight: 1.6 }}>
            <strong>Como interpretar a regularidade:</strong><br />
            <span style={{ color: "#16a34a" }}>● Regular (CV &lt; 25%):</span> valores
            constantes e previsíveis.<br />
            <span style={{ color: "#ca8a04" }}>● Moderada (25-50%):</span> alguma
            sazonalidade.<br />
            <span style={{ color: "#dc2626" }}>● Irregular (&gt; 50%):</span> alta
            variabilidade. Investigue picos e quedas.
          </div>
        </>
      )}
    </Card>
  );
}

function MetricCard({ label, value, footer, icon: Ico, color }) {
  return (
    <div style={{
      padding: 14, borderRadius: 10, background: "#fff",
      border: "1px solid #e2e8f0",
      boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    marginBottom: 6 }}>
        {Ico && <Ico size={14} color={color} />}
        <div style={{ fontSize: 10, color: "#64748b",
                      textTransform: "uppercase", fontWeight: 700,
                      letterSpacing: 0.4 }}>
          {label}
        </div>
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color, marginBottom: 4 }}>
        {value}
      </div>
      <div>{footer}</div>
    </div>
  );
}

function RegBadge({ reg, cv }) {
  const Ico = reg.icon;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 999,
      background: reg.c + "20", color: reg.c,
      fontSize: 11, fontWeight: 700,
    }}>
      <Ico size={11} /> {reg.l} {cv !== undefined && cv > 0 && `(CV ${cv}%)`}
    </span>
  );
}
