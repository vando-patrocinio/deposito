/*
ReconciliationCard.js — Card de conciliação no Fluxo de Caixa.

Mostra lado a lado:
- Total bancário (Sicoob + Outros) recebido no período
- Total Atlaz (faturas pagas dos assinantes)
- Diferença + alerta visual quando há discrepância significativa

Útil pra identificar:
- Faturas Atlaz não conciliadas (cliente pagou em outro banco, MED)
- Recebimentos bancários sem fatura Atlaz correspondente
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { GitCompareArrows, AlertTriangle, CheckCircle2, Search } from "lucide-react";
import ReconcileMatchModal from "@/ReconcileMatchModal";

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL" });

export default function ReconciliationCard({ period = 30 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [periodRange, setPeriodRange] = useState({ from: "", to: "" });

  useEffect(() => {
    const now = new Date();
    const from = new Date(now);
    from.setDate(from.getDate() - period);
    const fromStr = from.toISOString().slice(0, 10);
    const toStr = now.toISOString().slice(0, 10);
    setPeriodRange({ from: fromStr, to: toStr });
    setLoading(true);
    api.bankImportReconciliation(fromStr, toStr)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [period]);

  if (loading) return null;
  if (!data) return null;

  const bank = data.bank.total;
  const atlaz = data.atlaz.total;
  const diff = data.diff;
  const hasAny = bank > 0 || atlaz > 0;
  if (!hasAny) return null;
  // Considera "conciliado" se a diferença for < 5% do maior valor (tolerância)
  const maxV = Math.max(bank, atlaz, 1);
  const diffPct = Math.abs(diff) / maxV * 100;
  const isOk = diffPct < 5;
  const tone = isOk ? {
    bg: "linear-gradient(135deg,#dcfce7 0%,#f0fdf4 100%)",
    border: "#86efac", color: "#15803d",
    Icon: CheckCircle2, msg: "Conciliado ✓",
  } : {
    bg: "linear-gradient(135deg,#fef3c7 0%,#fffbeb 100%)",
    border: "#fcd34d", color: "#92400e",
    Icon: AlertTriangle, msg: `Diferença de ${diffPct.toFixed(1)}%`,
  };
  const ToneIcon = tone.Icon;

  return (
    <Card title={(
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <GitCompareArrows size={16} />
        Conciliação · Banco × Atlaz ({period} dias)
      </span>
    )} action={(
      <button onClick={() => setShowModal(true)}
                data-testid="reconcile-open-modal"
                style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  padding: "6px 12px", borderRadius: 8,
                  background: "#0ea5e9", color: "#fff",
                  border: "none", cursor: "pointer", fontWeight: 700,
                  fontSize: 12,
                }}>
        <Search size={13} /> Ver discrepâncias & auto-baixar
      </button>
    )} data-testid="reconciliation-card">
      <div style={{
        background: tone.bg, border: `1px solid ${tone.border}`,
        borderRadius: 10, padding: 12, marginBottom: 10,
        display: "flex", alignItems: "center", gap: 10,
      }} data-testid="reconciliation-status">
        <ToneIcon size={20} style={{ color: tone.color }} />
        <div>
          <div style={{ fontSize: 13, fontWeight: 800, color: tone.color }}>
            {tone.msg}
          </div>
          <div style={{ fontSize: 11, color: tone.color, opacity: 0.85,
                          marginTop: 2 }}>
            {isOk
              ? "Os valores recebidos no banco batem com as faturas Atlaz pagas."
              : "Investigue: pode ter cliente que pagou em outro banco, MED de "
              + "pagamento ou fatura Atlaz fora do período bancário."}
          </div>
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 10,
      }}>
        <ReconBlock
          label="Banco" total={bank} count={data.bank.count}
          color="#0ea5e9"
          breakdown={[
            { label: "Sicoob", v: data.bank.sicoob.total,
              c: data.bank.sicoob.count },
            { label: "Outros", v: data.bank.outros.total,
              c: data.bank.outros.count },
          ]}
          testId="recon-bank" />
        <ReconBlock
          label="Atlaz" total={atlaz} count={data.atlaz.count}
          color="#10b981"
          testId="recon-atlaz" />
        <ReconBlock
          label="Diferença" total={diff} count={null}
          color={isOk ? "#15803d" : "#dc2626"}
          highlight isDiff
          testId="recon-diff" />
      </div>
      {showModal && (
        <ReconcileMatchModal
          from_date={periodRange.from} to_date={periodRange.to}
          onClose={() => setShowModal(false)}
          onMutated={() => {
            // Reload contadores principais
            api.bankImportReconciliation(periodRange.from, periodRange.to)
              .then(setData).catch(() => null);
          }} />
      )}
    </Card>
  );
}

function ReconBlock({ label, total, count, color, breakdown, highlight, isDiff,
                          testId }) {
  return (
    <div data-testid={testId} style={{
      padding: 12, borderRadius: 10,
      background: highlight ? color + "10" : "#fff",
      border: highlight ? `2px solid ${color}` : "1px solid #e2e8f0",
    }}>
      <div style={{ fontSize: 10.5, fontWeight: 800, color: "#64748b",
                       textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 800, color, marginTop: 4,
                       fontVariantNumeric: "tabular-nums" }}>
        {isDiff && total > 0 ? "+" : ""}{fmtMoney(total)}
      </div>
      {count != null && (
        <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
          {count} movimento{count !== 1 ? "s" : ""}
        </div>
      )}
      {breakdown && (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column",
                         gap: 2, paddingTop: 6,
                         borderTop: "1px dashed #e2e8f0" }}>
          {breakdown.map((b) => (
            <div key={b.label} style={{
              display: "flex", justifyContent: "space-between",
              fontSize: 11, color: "#64748b",
            }}>
              <span>{b.label}</span>
              <strong style={{ color: "#0f172a",
                                  fontVariantNumeric: "tabular-nums" }}>
                {fmtMoney(b.v)} <span style={{ opacity: 0.6 }}>({b.c})</span>
              </strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
