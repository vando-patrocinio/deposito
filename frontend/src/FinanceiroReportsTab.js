/**
 * ReportsTab — Aba "Relatórios" do Financeiro.
 *
 * KPIs principais:
 *   • 4 cards de cabeçalho (Saldo, Receita do mês, Despesa do mês, Lucro líquido)
 *   • DRE simplificado (receitas/despesas por categoria, lucro)
 *   • Aging de contas a pagar (gráfico de barras por faixa)
 *   • Top 10 fornecedores do período
 *
 * Filtros: mês corrente / mês anterior / personalizado.
 */
import React, { useEffect, useState, useMemo } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Cell, Legend,
} from "recharts";
import {
  TrendingUp, TrendingDown, Wallet, DollarSign, AlertCircle,
  CheckCircle2, FileText, Download,
} from "lucide-react";

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const fmtMonth = (yyyyMm) => {
  if (!yyyyMm) return "";
  const [y, m] = yyyyMm.split("-");
  const names = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                 "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  return `${names[parseInt(m, 10) - 1]} ${y}`;
};

function defaultMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function prevMonth(yyyyMm) {
  const [y, m] = yyyyMm.split("-").map(Number);
  const py = m === 1 ? y - 1 : y;
  const pm = m === 1 ? 12 : m - 1;
  return `${py}-${String(pm).padStart(2, "0")}`;
}

export default function ReportsTab() {
  const [month, setMonth] = useState(defaultMonth());
  const [kpis, setKpis] = useState(null);
  const [dre, setDre] = useState(null);
  const [aging, setAging] = useState(null);
  const [topSuppliers, setTopSuppliers] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  async function loadAll(m) {
    setLoading(true); setErr("");
    try {
      const [k, d, a, ts] = await Promise.all([
        api.finReportsKpis({ month: m }),
        api.finReportsDre({ month: m }),
        api.finReportsAging(),
        api.finReportsTopSuppliers({ month: m, limit: 10 }),
      ]);
      setKpis(k); setDre(d); setAging(a); setTopSuppliers(ts);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }
  useEffect(() => { loadAll(month); /* eslint-disable-next-line */ }, [month]);

  return (
    <div data-testid="fin-reports-tab">
      <ReportsHeader month={month} setMonth={setMonth} />
      {err && (
        <div style={errBoxStyle}>
          <AlertCircle size={14} /> {err}
        </div>
      )}
      {loading && !kpis ? (
        <div style={{ padding: 60, textAlign: "center", color: "#94a3b8" }}>
          Carregando relatórios...
        </div>
      ) : (
        <>
          <KpisRow kpis={kpis} />
          <div style={{ display: "grid", gap: 16,
                          gridTemplateColumns: "1fr 1fr", marginTop: 16 }}>
            <DreCard dre={dre} />
            <AgingCard aging={aging} />
          </div>
          <div style={{ marginTop: 16 }}>
            <TopSuppliersCard data={topSuppliers} />
          </div>
        </>
      )}
    </div>
  );
}

// ============================================================
// Cabeçalho com seletor de mês
// ============================================================
function ReportsHeader({ month, setMonth }) {
  const current = defaultMonth();
  const prev = prevMonth(current);
  return (
    <div data-testid="reports-header" style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      marginBottom: 16, padding: "10px 14px",
      background: "linear-gradient(135deg, #0f172a, #1e293b)",
      borderRadius: 12, color: "white",
    }}>
      <div>
        <div style={{ fontSize: 11, opacity: 0.7, fontWeight: 600,
                         letterSpacing: 0.4, textTransform: "uppercase" }}>
          Relatórios Financeiros
        </div>
        <div style={{ fontSize: 18, fontWeight: 800, marginTop: 1 }}>
          {fmtMonth(month)}
        </div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        {[
          { v: prev, l: "Mês anterior" },
          { v: current, l: "Mês atual" },
        ].map((b) => (
          <button key={b.v} onClick={() => setMonth(b.v)}
              data-testid={`reports-month-${b.v}`}
              style={{
                padding: "6px 12px", borderRadius: 7,
                background: month === b.v ? "white" : "transparent",
                color: month === b.v ? "#0f172a" : "white",
                border: `1px solid ${month === b.v ? "white" : "rgba(255,255,255,.3)"}`,
                fontSize: 11.5, fontWeight: 700, cursor: "pointer",
              }}>{b.l}</button>
        ))}
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            data-testid="reports-month-picker"
            style={{
              padding: "6px 10px", borderRadius: 7,
              background: "transparent", color: "white",
              border: "1px solid rgba(255,255,255,.3)",
              fontSize: 11.5, fontWeight: 600, cursor: "pointer",
              colorScheme: "dark",
            }} />
      </div>
    </div>
  );
}

// ============================================================
// 4 cards KPI no topo
// ============================================================
function KpisRow({ kpis }) {
  if (!kpis) return null;
  const cards = [
    { id: "balance", label: "Saldo agregado", value: kpis.total_balance,
      icon: Wallet, color: "#0f172a", bg: "#f8fafc",
      sub: "todas contas ativas" },
    { id: "income", label: "Receita do mês", value: kpis.income_month,
      icon: TrendingUp, color: "#047857", bg: "#ecfdf5",
      sub: kpis.margin_pct + "% margem" },
    { id: "expense", label: "Despesa do mês", value: kpis.expense_month,
      icon: TrendingDown, color: "#b91c1c", bg: "#fef2f2",
      sub: (kpis.expense_month / (kpis.income_month || 1) * 100).toFixed(1) + "% das receitas" },
    { id: "net", label: kpis.net_month >= 0 ? "Lucro líquido" : "Prejuízo líquido",
      value: kpis.net_month,
      icon: DollarSign, color: kpis.net_month >= 0 ? "#047857" : "#b91c1c",
      bg: kpis.net_month >= 0 ? "#ecfdf5" : "#fef2f2",
      sub: kpis.net_month >= 0 ? "resultado positivo" : "resultado negativo" },
  ];
  return (
    <div style={{ display: "grid", gap: 12,
                    gridTemplateColumns: "repeat(4, 1fr)" }}>
      {cards.map((c) => (
        <KpiCard key={c.id} {...c} />
      ))}
      {/* Linha 2: pending/overdue */}
      <BillStatusCard
        label="Contas pendentes"
        count={kpis.pending.count}
        total={kpis.pending.total}
        color="#f59e0b" bg="#fef3c7"
        icon={FileText}
        testid="reports-pending"
      />
      <BillStatusCard
        label="Contas vencidas"
        count={kpis.overdue.count}
        total={kpis.overdue.total}
        color="#b91c1c" bg="#fef2f2"
        icon={AlertCircle}
        testid="reports-overdue"
      />
    </div>
  );
}

function KpiCard({ id, label, value, icon: Icon, color, bg, sub }) {
  return (
    <div data-testid={`reports-kpi-${id}`} style={{
      background: bg, border: "1px solid #e2e8f0",
      borderRadius: 12, padding: 14,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={14} color={color} />
        <span style={{ fontSize: 10.5, fontWeight: 700, color,
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color, marginTop: 6,
                       fontFamily: "ui-monospace, monospace" }}>
        {fmtMoney(value)}
      </div>
      <div style={{ fontSize: 10.5, color: "#64748b", marginTop: 2 }}>
        {sub}
      </div>
    </div>
  );
}

function BillStatusCard({ label, count, total, color, bg, icon: Icon, testid }) {
  return (
    <div data-testid={testid} style={{
      background: bg, border: "1px solid #e2e8f0", borderRadius: 12,
      padding: 14, gridColumn: "span 2",
      display: "flex", alignItems: "center", gap: 12,
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 10,
        background: color, color: "white",
        display: "grid", placeItems: "center", flexShrink: 0,
      }}>
        <Icon size={18} />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 10.5, fontWeight: 700, color,
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
          {label}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 2 }}>
          <span style={{ fontSize: 22, fontWeight: 800, color,
                            fontFamily: "ui-monospace, monospace" }}>
            {fmtMoney(total)}
          </span>
          <span style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
            · {count} conta{count === 1 ? "" : "s"}
          </span>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// DRE — Demonstração simplificada
// ============================================================
function DreCard({ dre }) {
  if (!dre) return <Card title="DRE — Demonstração de Resultado">Carregando...</Card>;
  return (
    <Card title={<span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      DRE — Demonstração de Resultado
    </span>}>
      <div data-testid="reports-dre" style={{
        background: "white", padding: 12, borderRadius: 10,
        border: "1px solid #e2e8f0",
      }}>
        <DreRow label="Receitas Brutas" value={dre.revenue.total}
                  bold positive />
        <DreSub label="↳ Movimentações (receita)"
                  value={dre.revenue.movements_income} />
        <DreSub label="↳ Faturas pagas (Atlaz)"
                  value={dre.revenue.subscriber_invoices_paid} />
        <Divider />
        <DreRow label="(-) Despesas Operacionais"
                  value={-dre.expenses.total} negative bold />
        {dre.expenses.by_category.slice(0, 6).map((c) => (
          <DreSub key={c.category_id}
                    label={`↳ ${c.name}`}
                    value={-c.amount}
                    swatch={c.color} />
        ))}
        {dre.expenses.by_category.length === 0 && (
          <div style={{ fontSize: 11, color: "#94a3b8",
                          padding: "6px 0", fontStyle: "italic" }}>
            Sem despesas no período.
          </div>
        )}
        <Divider strong />
        <DreRow
          label={dre.net >= 0 ? "= Lucro Líquido" : "= Prejuízo Líquido"}
          value={dre.net}
          positive={dre.net >= 0} negative={dre.net < 0}
          bold huge />
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 4,
                         textAlign: "right" }}>
          Margem líquida: <strong>{dre.margin_pct}%</strong>
        </div>
      </div>
    </Card>
  );
}

function DreRow({ label, value, bold, positive, negative, huge }) {
  const color = positive ? "#047857" : negative ? "#b91c1c" : "#0f172a";
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: huge ? "8px 0 0" : "4px 0",
      fontSize: huge ? 16 : 13,
      fontWeight: bold ? 800 : 500, color,
    }}>
      <span>{label}</span>
      <span style={{ fontFamily: "ui-monospace, monospace" }}>
        {fmtMoney(value)}
      </span>
    </div>
  );
}
function DreSub({ label, value, swatch }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "2px 0 2px 12px", fontSize: 11.5, color: "#64748b",
    }}>
      <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
        {swatch && (
          <span style={{ width: 8, height: 8, borderRadius: 2,
                            background: swatch, display: "inline-block" }} />
        )}
        {label}
      </span>
      <span style={{ fontFamily: "ui-monospace, monospace" }}>
        {fmtMoney(value)}
      </span>
    </div>
  );
}
function Divider({ strong }) {
  return (
    <div style={{
      height: 1, background: strong ? "#cbd5e1" : "#f1f5f9",
      margin: strong ? "6px 0" : "4px 0",
    }} />
  );
}

// ============================================================
// Aging — gráfico de barras horizontal
// ============================================================
function AgingCard({ aging }) {
  if (!aging) return <Card title="Aging de Contas">Carregando...</Card>;
  const buckets = aging.buckets;
  const chartData = buckets.filter((b) => b.total > 0).map((b) => ({
    label: b.label,
    value: b.total,
    color: b.key.startsWith("vencido") ? "#dc2626" : "#0ea5e9",
    key: b.key,
  }));
  return (
    <Card title={<span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      ⏰ Aging — Contas a Pagar
    </span>}>
      <div data-testid="reports-aging" style={{
        display: "grid", gap: 8,
        gridTemplateColumns: "1fr 1fr", marginBottom: 12,
      }}>
        <SummaryPill label="Vencidas" value={aging.summary.overdue_total} color="#dc2626" />
        <SummaryPill label="A vencer" value={aging.summary.upcoming_total} color="#0ea5e9" />
      </div>
      {chartData.length === 0 ? (
        <div style={{ padding: 20, textAlign: "center", color: "#94a3b8",
                         fontSize: 12 }}>
          ✓ Nenhuma conta pendente ou vencida.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 28)}>
          <BarChart data={chartData} layout="vertical"
                       margin={{ top: 0, right: 60, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10 }}
                      tickFormatter={(v) => `R$ ${(v / 1000).toFixed(0)}k`} />
            <YAxis type="category" dataKey="label" tick={{ fontSize: 10.5 }}
                      width={130} />
            <Tooltip formatter={(v) => fmtMoney(v)} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}>
              {chartData.map((d) => (
                <Cell key={d.key} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}

function SummaryPill({ label, value, color }) {
  return (
    <div style={{
      padding: 10, borderRadius: 8,
      background: color + "10", border: `1px solid ${color}30`,
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color,
                       textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 800, color,
                       fontFamily: "ui-monospace, monospace", marginTop: 2 }}>
        {fmtMoney(value)}
      </div>
    </div>
  );
}

// ============================================================
// Top fornecedores do período
// ============================================================
function TopSuppliersCard({ data }) {
  if (!data) return <Card title="Top Fornecedores">Carregando...</Card>;
  const rows = data.rows || [];
  const max = Math.max(...rows.map((r) => r.total), 1);
  return (
    <Card title={<span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      Top Fornecedores do Período
    </span>}>
      {rows.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: "#94a3b8",
                         fontSize: 12 }}>
          Nenhuma conta atribuída a fornecedor neste período.
        </div>
      ) : (
        <div data-testid="reports-top-suppliers" style={{
          display: "flex", flexDirection: "column", gap: 6,
        }}>
          {rows.map((r, i) => (
            <div key={r.supplier_id} style={{ position: "relative" }}>
              <div style={{
                position: "absolute", top: 0, left: 0,
                height: "100%", width: `${(r.total / max) * 100}%`,
                background: "linear-gradient(90deg, #0ea5e9, #38bdf8)",
                opacity: 0.12, borderRadius: 6,
              }} />
              <div style={{
                position: "relative", display: "flex",
                justifyContent: "space-between", alignItems: "center",
                padding: "8px 12px",
                background: "white",
                border: "1px solid #e2e8f0", borderRadius: 6,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10,
                                  minWidth: 0, flex: 1 }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: "50%",
                    background: i < 3 ? "#fbbf24" : "#e2e8f0",
                    color: i < 3 ? "#78350f" : "#64748b",
                    display: "grid", placeItems: "center",
                    fontSize: 11, fontWeight: 800,
                  }}>{i + 1}</span>
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: "#0f172a",
                                    overflow: "hidden", textOverflow: "ellipsis",
                                    whiteSpace: "nowrap" }}>
                    {r.supplier_name}
                  </span>
                  <span style={{ fontSize: 10.5, color: "#64748b" }}>
                    · {r.count} conta{r.count === 1 ? "" : "s"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                  {r.paid > 0 && (
                    <span style={pillStyle("#047857", "#ecfdf5")} title={`${r.paid} paga(s)`}>
                      <CheckCircle2 size={10} /> {r.paid}
                    </span>
                  )}
                  {r.pending > 0 && (
                    <span style={pillStyle("#b91c1c", "#fef2f2")} title={`${r.pending} pendente(s)`}>
                      <AlertCircle size={10} /> {r.pending}
                    </span>
                  )}
                  <span style={{
                    fontSize: 13, fontWeight: 800, color: "#0f172a",
                    fontFamily: "ui-monospace, monospace",
                    marginLeft: 8, minWidth: 100, textAlign: "right",
                  }}>
                    {fmtMoney(r.total)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function pillStyle(color, bg) {
  return {
    display: "inline-flex", alignItems: "center", gap: 3,
    padding: "1px 6px", borderRadius: 999,
    background: bg, color, fontSize: 10, fontWeight: 700,
    fontFamily: "ui-monospace, monospace",
  };
}

const errBoxStyle = {
  padding: 12, marginBottom: 12,
  background: "#fef2f2", border: "1px solid #fca5a5",
  borderRadius: 8, color: "#b91c1c", fontSize: 12,
  display: "flex", alignItems: "center", gap: 6,
};
