/**
 * Watchtower Recebimentos — Dashboard Executivo
 *
 * Visão estratégica/CEO dos recebimentos:
 *   • KPI macro: total recebido (mês atual, MTD, MoM%)
 *   • Top 10 pagadores do período
 *   • Drill-down clicando em qualquer cliente
 *   • Comparação Mês Atual × Mês Passado
 *
 * Reutiliza os componentes de `PayersComponents.jsx` (TopPayersPanel +
 * PayersDrillDownModal) e o backend `/api/financeiro/analytics` +
 * `/api/financeiro/payers`.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  TrendingUp, DollarSign, Users, Calendar,
} from "lucide-react";
import { TopPayersPanel, PayersDrillDownModal } from "./PayersComponents";


const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
  });


function _firstDayOfMonth() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1)
    .toISOString().slice(0, 10);
}
function _lastDayOfPrevMonth() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 0)
    .toISOString().slice(0, 10);
}
function _firstDayOfPrevMonth() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth() - 1, 1)
    .toISOString().slice(0, 10);
}
function _todayStr() {
  return new Date().toISOString().slice(0, 10);
}


export default function WatchtowerRecebimentos() {
  const [current, setCurrent] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(true);
  const [drillOpen, setDrillOpen] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const monthFrom = _firstDayOfMonth();
      const today = _todayStr();
      const prevFrom = _firstDayOfPrevMonth();
      const prevTo = _lastDayOfPrevMonth();

      const [cur, prev] = await Promise.all([
        api._client.get(
          `/financeiro/analytics?range=custom&period=day` +
          `&from_date=${monthFrom}&to_date=${today}`,
        ).then((r) => r.data),
        api._client.get(
          `/financeiro/analytics?range=custom&period=day` +
          `&from_date=${prevFrom}&to_date=${prevTo}`,
        ).then((r) => r.data),
      ]);
      setCurrent(cur);
      setPrevious(prev);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  if (loading) {
    return <div style={{ padding: 32, textAlign: "center",
                          color: "#64748b" }}>Carregando recebimentos…</div>;
  }
  if (error) {
    return <div style={{ padding: 24, color: "#dc2626" }}>
      Erro: {error}</div>;
  }

  const curTotal = current?.totals?.income || 0;
  const prevTotal = previous?.totals?.income || 0;
  const momPct = prevTotal > 0
    ? ((curTotal - prevTotal) / prevTotal * 100).toFixed(1)
    : 0;
  const momPositive = curTotal >= prevTotal;
  const avgTicket = current?.unique_payers_count > 0
    ? curTotal / current.unique_payers_count : 0;

  return (
    <div data-testid="watchtower-recebimentos" style={{ padding: 16 }}>
      <div style={{ marginBottom: 18 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: "#0f172a",
                       margin: 0 }}>
          Watchtower Recebimentos
        </h2>
        <p style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
          Visão executiva de quem está pagando · {current?.from_date} → {current?.to_date}
        </p>
      </div>

      {/* KPIs principais */}
      <div style={{ display: "grid", gridTemplateColumns:
                    "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 12, marginBottom: 18 }}>
        <KpiCard
          icon={DollarSign}
          color="#16a34a"
          label="Recebido no mês"
          value={fmtMoney(curTotal)}
          subtitle={`vs ${fmtMoney(prevTotal)} no mês passado`}
          delta={momPct + "%"}
          deltaPositive={momPositive}
          testId="kpi-recebido-mes"
        />
        <KpiCard
          icon={Users}
          color="#0e7490"
          label="Clientes únicos pagantes"
          value={String(current?.unique_payers_count || 0)}
          subtitle="que pagaram alguma fatura"
          testId="kpi-pagadores-unicos"
        />
        <KpiCard
          icon={TrendingUp}
          color="#7c3aed"
          label="Ticket médio"
          value={fmtMoney(avgTicket)}
          subtitle="por cliente pagante"
          testId="kpi-ticket-medio"
        />
        <KpiCard
          icon={Calendar}
          color="#ea580c"
          label="Dias úteis decorridos"
          value={String(current?.income_metrics?.active_periods || 0)}
          subtitle="com pagamentos no mês"
          testId="kpi-dias-ativos"
        />
      </div>

      {/* Top Pagadores compact + botão de drill-down */}
      <TopPayersPanel
        topPayers={current?.top_payers || []}
        uniqueCount={current?.unique_payers_count || 0}
        period={`${current?.from_date} → ${current?.to_date}`}
        onOpenFullList={() => setDrillOpen(true)}
      />

      {drillOpen && (
        <PayersDrillDownModal
          date={null}
          fromDate={current?.from_date}
          toDate={current?.to_date}
          onClose={() => setDrillOpen(false)}
        />
      )}
    </div>
  );
}


function KpiCard({ icon: Ico, label, value, subtitle, color, delta,
                     deltaPositive, testId }) {
  return (
    <div data-testid={testId} style={{
      padding: 16, borderRadius: 10, background: "#fff",
      border: "1px solid #e2e8f0",
      boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    marginBottom: 8 }}>
        {Ico && <Ico size={16} color={color} />}
        <div style={{ fontSize: 10, color: "#64748b",
                      textTransform: "uppercase", fontWeight: 700,
                      letterSpacing: 0.4 }}>
          {label}
        </div>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color, marginBottom: 4 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: "#64748b" }}>{subtitle}</div>
      {delta !== undefined && (
        <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600,
                       color: deltaPositive ? "#16a34a" : "#dc2626" }}>
          {deltaPositive ? "↑" : "↓"} {delta} vs mês anterior
        </div>
      )}
    </div>
  );
}
