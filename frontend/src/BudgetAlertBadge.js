import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { AlertTriangle, Wallet } from "lucide-react";

const POLL_MS = 60_000; // 60s

/**
 * BudgetAlertBadge — sino persistente no header avisando que o orçamento
 * mensal do Motor IA está em estado `warn` ou `exceeded`. Polling a cada 60s.
 *
 * Props:
 *  - role: papel do usuário corrente (oculta para roles não-gestor).
 *  - onClick: callback para navegar até a aba Motor IA.
 */
export default function BudgetAlertBadge({ role, onClick }) {
  const [status, setStatus] = useState(null);
  const lastSeenRef = useRef(null); // pra detectar transições (toast futuro)

  useEffect(() => {
    // Só carrega pra papéis que enxergam Motor IA
    if (!["gestor", "administrador", "auditor"].includes(role)) return;
    let alive = true;
    const fetchStatus = async () => {
      try {
        const s = await api.motorIaBudgetStatus();
        if (!alive) return;
        // Detecta transição (foi ok/disabled → warn/exceeded)
        const prev = lastSeenRef.current;
        const cur = s?.status;
        if (prev && prev !== cur && (cur === "warn" || cur === "exceeded")) {
          // Hint visual extra: pisca uma vez (CSS animation)
          const el = document.getElementById("budget-alert-badge");
          if (el) {
            el.classList.remove("budget-pulse-strong");
            void el.offsetWidth;
            el.classList.add("budget-pulse-strong");
          }
        }
        lastSeenRef.current = cur;
        setStatus(s);
      } catch (e) {
        /* silently ignore — endpoint pode não estar disponível */
      }
    };
    fetchStatus();
    const t = setInterval(fetchStatus, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [role]);

  if (!status || !["warn", "exceeded"].includes(status.status)) return null;

  const isExceeded = status.status === "exceeded";
  const bg = isExceeded ? "#fef2f2" : "#fffbeb";
  const fg = isExceeded ? "#be123c" : "#b45309";
  const border = isExceeded ? "#fecaca" : "#fde68a";
  const label = isExceeded ? "Orçamento excedido" : "Orçamento próximo do limite";
  const pct = Number(status.used_pct || 0).toFixed(0);

  return (
    <>
      <style>{`
        @keyframes budget-pulse {
          0%, 100% { box-shadow: 0 0 0 0 ${isExceeded ? "rgba(220,38,38,0.45)" : "rgba(245,158,11,0.45)"}; }
          50%     { box-shadow: 0 0 0 6px ${isExceeded ? "rgba(220,38,38,0)" : "rgba(245,158,11,0)"}; }
        }
        #budget-alert-badge { animation: budget-pulse 2.4s ease-out infinite; }
        .budget-pulse-strong { animation: budget-pulse 0.7s ease-out 3 !important; }
      `}</style>
      <button
        id="budget-alert-badge"
        onClick={onClick}
        data-testid="budget-alert-badge"
        title={`${label} — ${pct}% (US$ ${Number(status.spent_usd).toFixed(2)} de US$ ${Number(status.monthly_limit_usd).toFixed(2)}). Clique para abrir Motor IA.`}
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "4px 10px", height: 28, borderRadius: 999,
          background: bg, color: fg, border: `1px solid ${border}`,
          cursor: "pointer", fontWeight: 700, fontSize: 11,
          whiteSpace: "nowrap",
        }}
      >
        {isExceeded ? <AlertTriangle size={13} /> : <Wallet size={13} />}
        <span>{isExceeded ? "Orçamento IA" : "Orçamento IA"}</span>
        <span style={{ opacity: 0.85, fontWeight: 600 }}>{pct}%</span>
      </button>
    </>
  );
}
