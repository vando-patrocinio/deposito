import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { Wallet, AlertTriangle, CheckCircle2, TrendingUp, Loader2, Save } from "lucide-react";

function fmtUSD(n) {
  const v = Number(n || 0);
  if (v < 0.01 && v > 0) return `US$ ${v.toFixed(4)}`;
  return `US$ ${v.toFixed(2)}`;
}

const STATUS_STYLES = {
  ok:        { bg: "#ecfdf5", fg: "#047857", border: "#a7f3d0", icon: CheckCircle2, label: "Dentro do orçamento" },
  warn:      { bg: "#fffbeb", fg: "#b45309", border: "#fde68a", icon: AlertTriangle, label: "Atenção: aproximando do limite" },
  exceeded:  { bg: "#fef2f2", fg: "#be123c", border: "#fecaca", icon: AlertTriangle, label: "Limite excedido" },
  disabled:  { bg: "#f1f5f9", fg: "#64748b", border: "#e2e8f0", icon: Wallet,        label: "Alertas desativados" },
};

/**
 * Motor IA — Card de Orçamento Mensal.
 * Configura limite USD/mês + threshold de aviso, e mostra status atual
 * (gasto do mês corrente, % usado, projeção linear até fim do mês).
 */
export default function MotorIaBudgetCard() {
  const [cfg, setCfg] = useState(null);
  const [status, setStatus] = useState(null);
  const [limit, setLimit] = useState("");
  const [threshold, setThreshold] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setMsg("");
    try {
      const [c, s] = await Promise.all([
        api.motorIaBudgetGet(),
        api.motorIaBudgetStatus(),
      ]);
      setCfg(c); setStatus(s);
      setLimit(String(c.monthly_limit_usd ?? 50));
      setThreshold(String(c.warn_threshold_pct ?? 80));
      setEnabled(!!c.enabled);
    } catch (e) {
      setMsg("Erro ao carregar: " + (e?.response?.data?.detail || e.message));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true); setMsg("");
    try {
      await api.motorIaBudgetSave({
        monthly_limit_usd: parseFloat(limit) || 0,
        warn_threshold_pct: parseInt(threshold, 10) || 80,
        enabled,
      });
      await load();
      setMsg("Orçamento salvo.");
    } catch (e) {
      setMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  if (!cfg || !status) {
    return (
      <Card title="Orçamento do Motor IA" data-testid="motor-ia-budget-card">
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 8,
                        color: "var(--text-muted, #64748b)", fontSize: 13 }}>
          <Loader2 size={14} className="animate-spin" /> Carregando...
        </div>
      </Card>
    );
  }

  const st = STATUS_STYLES[status.status] || STATUS_STYLES.disabled;
  const StIcon = st.icon;
  const pct = Math.min(100, Number(status.used_pct || 0));

  return (
    <Card
      title="Orçamento do Motor IA"
      subtitle="Define um teto mensal em USD. Você recebe alertas visuais ao se aproximar do limite ou excedê-lo."
      data-testid="motor-ia-budget-card"
    >
      {/* Status atual */}
      <div style={{
        padding: 14, marginBottom: 16,
        background: st.bg, border: `1px solid ${st.border}`,
        borderRadius: 10, display: "flex", alignItems: "center", gap: 12,
      }} data-testid={`budget-status-${status.status}`}>
        <StIcon size={20} color={st.fg} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 13, color: st.fg }}>
            {st.label}
          </div>
          <div style={{ fontSize: 12, color: st.fg, opacity: 0.85, marginTop: 2 }}>
            Mês corrente: <strong>{fmtUSD(status.spent_usd)}</strong>
            {status.enabled && status.monthly_limit_usd > 0 && (
              <> de {fmtUSD(status.monthly_limit_usd)} ({status.used_pct}%)</>
            )}
            {" · "}{status.calls} chamada(s)
          </div>
        </div>
        {status.enabled && (
          <div style={{ textAlign: "right", fontSize: 11, color: st.fg, opacity: 0.85 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 4,
                            justifyContent: "flex-end" }}>
              <TrendingUp size={12} />
              <span>Projeção:</span>
            </div>
            <div style={{ fontWeight: 700, fontSize: 13, marginTop: 2 }}>
              {fmtUSD(status.projected_month_usd)}
            </div>
          </div>
        )}
      </div>

      {/* Barra de progresso */}
      {status.enabled && status.monthly_limit_usd > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ position: "relative", height: 10,
                          background: "var(--surface-2, #f1f5f9)",
                          borderRadius: 6, overflow: "hidden" }}>
            <div style={{
              width: `${pct}%`, height: "100%",
              background: status.status === "exceeded" ? "#dc2626" :
                                  status.status === "warn"     ? "#f59e0b" : "#10b981",
              transition: "width 0.5s ease",
            }} />
            {/* Marca do threshold */}
            <div style={{
              position: "absolute", top: -3,
              left: `${status.warn_threshold_pct}%`,
              width: 2, height: 16, background: "#64748b", opacity: 0.6,
            }} title={`Aviso aos ${status.warn_threshold_pct}%`} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between",
                          fontSize: 10, color: "var(--text-muted, #94a3b8)",
                          marginTop: 4 }}>
            <span>US$ 0</span>
            <span>{fmtUSD(status.monthly_limit_usd)}</span>
          </div>
        </div>
      )}

      {/* Formulário de configuração */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr auto auto",
                      gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted, #64748b)" }}>
            Limite mensal (USD)
          </label>
          <input
            type="number" min="0" step="0.5"
            value={limit} onChange={(e) => setLimit(e.target.value)}
            data-testid="budget-limit-input"
            style={{
              width: "100%", marginTop: 4, padding: "7px 10px",
              border: "1px solid var(--border, #e2e8f0)", borderRadius: 8,
              fontSize: 13, fontVariantNumeric: "tabular-nums",
            }}
          />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted, #64748b)" }}>
            Avisar aos (%)
          </label>
          <input
            type="number" min="1" max="100" step="5"
            value={threshold} onChange={(e) => setThreshold(e.target.value)}
            data-testid="budget-threshold-input"
            style={{
              width: "100%", marginTop: 4, padding: "7px 10px",
              border: "1px solid var(--border, #e2e8f0)", borderRadius: 8,
              fontSize: 13, fontVariantNumeric: "tabular-nums",
            }}
          />
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 6,
                          fontSize: 12, fontWeight: 600,
                          color: "var(--text-primary, #0f172a)",
                          padding: "8px 10px" }}>
          <input
            type="checkbox" checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            data-testid="budget-enabled-toggle"
          />
          Ativar alertas
        </label>
        <button
          onClick={save} disabled={busy}
          data-testid="budget-save-btn"
          style={{
            padding: "8px 14px", border: 0, borderRadius: 8,
            background: "var(--text-primary, #0f172a)",
            color: "#fff", cursor: busy ? "wait" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
            fontSize: 12, fontWeight: 700,
          }}
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          Salvar
        </button>
      </div>

      {msg && (
        <div style={{
          marginTop: 10, fontSize: 12, fontWeight: 600,
          color: msg.startsWith("Erro") ? "#be123c" : "#166534",
        }}>{msg}</div>
      )}
    </Card>
  );
}
