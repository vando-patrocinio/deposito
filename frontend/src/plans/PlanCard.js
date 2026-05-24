import React from "react";
import {
  Zap, TrendingUp, Edit2, Trash2, Power, PowerOff, Calculator,
} from "lucide-react";

/* =============================================================
   PlanCard — card de leitura de um plano na listagem.
   Botões: Editar, Reajustar (se annual_adjustment_pct > 0),
           Ativar/Inativar, Excluir.
============================================================= */
export default function PlanCard({ plan, onEdit, onAdjust, onToggleActive, onDelete }) {
  const fmt = (v) => new Intl.NumberFormat("pt-BR",
        { style: "currency", currency: "BRL" }).format(v || 0);
  return (
    <div data-testid={`plan-card-${plan.id}`} className="surface" style={{
      padding: 16, borderRadius: 12,
      border: plan.active ? "1px solid var(--border-default)"
                          : "1px dashed rgba(148,163,184,.5)",
      opacity: plan.active ? 1 : 0.55,
      display: "flex", flexDirection: "column", gap: 8,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: "linear-gradient(135deg, #0d9488, #06b6d4)",
          color: "#fff", display: "grid", placeItems: "center",
          flexShrink: 0,
        }}>
          <Zap size={18} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 800,
                         color: "var(--text-primary)",
                         overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap" }}>
            {plan.name}
          </div>
          {plan.speed_label && (
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
              {plan.speed_label}{plan.speed_up_mbps
                ? ` (↓${plan.speed_down_mbps}/↑${plan.speed_up_mbps} Mbps)`
                : ""}
            </div>
          )}
        </div>
        {!plan.active && (
          <span style={{
            padding: "2px 7px", borderRadius: 999,
            background: "rgba(148,163,184,.2)", color: "#64748b",
            fontSize: 9, fontWeight: 800, letterSpacing: 0.5,
          }}>INATIVO</span>
        )}
      </div>

      <div style={{ fontSize: 22, fontWeight: 800,
                     color: "var(--text-primary)", letterSpacing: "-0.03em" }}>
        {fmt(plan.monthly_price)}
        <span style={{ fontSize: 11, color: "var(--text-muted)",
                        fontWeight: 500 }}>/mês</span>
      </div>

      {(plan.annual_adjustment_pct ?? 0) > 0 && (
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "3px 8px", borderRadius: 6,
          background: "rgba(245,158,11,.12)",
          color: "#b45309",
          fontSize: 10, fontWeight: 700, width: "fit-content",
        }}>
          <TrendingUp size={10} strokeWidth={2.5} />
          +{plan.annual_adjustment_pct}% ao ano (reajuste)
        </div>
      )}

      {plan.description && (
        <div style={{ fontSize: 11, color: "var(--text-secondary)",
                       fontStyle: "italic", marginTop: 4 }}>
          {plan.description}
        </div>
      )}

      <div style={{ display: "flex", gap: 6, marginTop: "auto", flexWrap: "wrap" }}>
        <button onClick={onEdit} className="btn btn-ghost btn-sm"
                data-testid={`plan-edit-${plan.id}`}>
          <Edit2 size={11} /> Editar
        </button>
        {(plan.annual_adjustment_pct ?? 0) > 0 && (
          <button onClick={onAdjust}
                  data-testid={`plan-adjust-${plan.id}`}
                  className="btn btn-secondary btn-sm"
                  title="Simular e aplicar reajuste anual de inflação"
                  style={{
                    background: "rgba(245,158,11,.12)",
                    color: "#b45309",
                    border: "1px solid rgba(245,158,11,.35)",
                  }}>
            <Calculator size={11} /> Reajustar
          </button>
        )}
        <button onClick={onToggleActive} className="btn btn-ghost btn-sm"
                title={plan.active ? "Inativar" : "Ativar"}>
          {plan.active ? <PowerOff size={11} /> : <Power size={11} />}
        </button>
        <button onClick={onDelete} className="btn btn-ghost btn-sm"
                style={{ marginLeft: "auto", color: "var(--danger)" }}
                title="Excluir">
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  );
}
