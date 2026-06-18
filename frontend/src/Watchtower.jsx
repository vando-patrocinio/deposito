/**
 * Watchtower — Shell de Painéis Executivos com sub-abas.
 *
 * Estrutura aprovada pelo CTO (18/06/2026):
 *   Watchtower
 *   ├─ IA Presidente
 *   ├─ Relacionamento
 *   ├─ Recebimentos
 *   ├─ Patrimônio (placeholder — bloqueado até validação dos 2 primeiros)
 *   └─ Estoque
 *
 * As 2 primeiras abas (IA Presidente + Relacionamento) entram nesta
 * sprint. Patrimônio fica como placeholder.
 */
import React, { useState } from "react";
import {
  Brain, Heart, DollarSign, Package, Boxes, Lock, Network, Calculator,
} from "lucide-react";
import WatchtowerIaPresidente from "@/WatchtowerIaPresidente";
import WatchtowerRelacionamento from "@/WatchtowerRelacionamento";
import WatchtowerRecebimentos from "@/WatchtowerRecebimentos";
import WatchtowerEstoque from "@/WatchtowerEstoque";
import WatchtowerRede from "@/WatchtowerRede";
import WatchtowerOSCost from "@/WatchtowerOSCost";

const TABS = [
  { id: "ia-presidente", label: "IA Presidente", Icon: Brain,
    Component: WatchtowerIaPresidente },
  { id: "relacionamento", label: "Relacionamento", Icon: Heart,
    Component: WatchtowerRelacionamento },
  { id: "recebimentos", label: "Recebimentos", Icon: DollarSign,
    Component: WatchtowerRecebimentos },
  { id: "rede", label: "Rede (Tier 2)", Icon: Network,
    Component: WatchtowerRede },
  { id: "oscost", label: "Custos OS", Icon: Calculator,
    Component: WatchtowerOSCost },
  { id: "patrimonio", label: "Patrimônio", Icon: Package,
    Component: PatrimonioPlaceholder, locked: true },
  { id: "estoque", label: "Estoque", Icon: Boxes,
    Component: WatchtowerEstoque },
];

export default function Watchtower() {
  const [activeId, setActiveId] = useState(() => {
    if (typeof window !== "undefined") {
      const saved = window.localStorage.getItem("watchtower_active_tab");
      if (saved && TABS.find((t) => t.id === saved)) return saved;
    }
    return "ia-presidente";
  });

  const changeTab = (id) => {
    setActiveId(id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("watchtower_active_tab", id);
    }
  };

  const Active = TABS.find((t) => t.id === activeId)?.Component
    || WatchtowerIaPresidente;

  return (
    <div data-testid="watchtower-shell"
      style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Sub-tabs bar */}
      <div data-testid="watchtower-subtabs" style={{
        display: "flex", gap: 2, padding: "10px 16px 0",
        borderBottom: "1px solid #e2e8f0", background: "#fafafa",
        overflowX: "auto",
      }}>
        {TABS.map((t) => {
          const active = t.id === activeId;
          return (
            <button key={t.id}
              data-testid={`watchtower-tab-${t.id}`}
              onClick={() => changeTab(t.id)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "10px 16px", fontSize: 13, fontWeight: 600,
                color: active ? "#0f172a" : "#64748b",
                background: active ? "white" : "transparent",
                border: "1px solid transparent",
                borderBottom: active
                  ? "2px solid #0f172a"
                  : "2px solid transparent",
                borderRadius: "8px 8px 0 0",
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}>
              <t.Icon size={14} />
              {t.label}
              {t.locked && <Lock size={11} color="#94a3b8" />}
            </button>
          );
        })}
      </div>

      {/* Active tab content */}
      <div style={{ flex: 1, overflow: "auto", background: "#f8fafc" }}>
        <Active />
      </div>
    </div>
  );
}

function PatrimonioPlaceholder() {
  return (
    <div data-testid="watchtower-patrimonio-placeholder" style={{
      padding: 32, textAlign: "center", color: "#64748b", maxWidth: 600,
      margin: "60px auto",
    }}>
      <div style={{
        width: 64, height: 64, borderRadius: "50%",
        background: "#f1f5f9", display: "inline-flex",
        alignItems: "center", justifyContent: "center", marginBottom: 16,
      }}>
        <Lock size={28} color="#94a3b8" />
      </div>
      <h3 style={{ fontSize: 18, color: "#0f172a", margin: "0 0 8px" }}>
        Patrimônio · em construção
      </h3>
      <p style={{ fontSize: 14, lineHeight: 1.5 }}>
        Aguardando validação das 2 primeiras abas (IA Presidente e
        Relacionamento) antes de habilitar CAPEX + ativos + depreciação.
      </p>
    </div>
  );
}
