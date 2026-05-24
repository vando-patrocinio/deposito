import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Plus, Search, Sparkles } from "lucide-react";

import PlanCard from "./plans/PlanCard";
import PlanEditor from "./plans/PlanEditor";
import AdjustmentModal from "./plans/AdjustmentModal";
import ScheduledAdjustmentsCard from "./plans/ScheduledAdjustmentsCard";

/* =============================================================
   PlansPanel — CRUD dos planos comerciais do provedor.
   Cada plano: nome, velocidade (down/up), valor mensal, reajuste anual (%).
   Usado depois em SubscribersPanel como dropdown.

   Sub-componentes em ./plans/ (refator iter107).
============================================================= */

const EMPTY_PLAN = {
  name: "", speed_down_mbps: "", speed_up_mbps: "",
  monthly_price: "", annual_adjustment_pct: 0,
  description: "", active: true,
  speed_reduced_down_mbps: 0.5, speed_reduced_up_mbps: 0.25,
};

export default function PlansPanel() {
  const [items, setItems] = useState([]);
  const [scheduled, setScheduled] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [adjusting, setAdjusting] = useState(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, sch] = await Promise.all([
        api.plansList(),
        api.planScheduledList({ status: "pending" }).catch(() => ({ items: [] })),
      ]);
      setItems(r.items || []);
      setScheduled(sch.items || []);
    } catch (e) {
      console.error(e);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = items.filter((p) =>
    !search.trim() ||
    (p.name || "").toLowerCase().includes(search.toLowerCase()) ||
    (p.speed_label || "").toLowerCase().includes(search.toLowerCase())
  );

  const onSave = async (plan) => {
    const payload = {
      ...plan,
      speed_down_mbps: plan.speed_down_mbps ? Number(plan.speed_down_mbps) : null,
      speed_up_mbps: plan.speed_up_mbps ? Number(plan.speed_up_mbps) : null,
      speed_reduced_down_mbps: plan.speed_reduced_down_mbps
        ? Number(plan.speed_reduced_down_mbps) : null,
      speed_reduced_up_mbps: plan.speed_reduced_up_mbps
        ? Number(plan.speed_reduced_up_mbps) : null,
      monthly_price: plan.monthly_price ? Number(plan.monthly_price) : 0,
      annual_adjustment_pct: Number(plan.annual_adjustment_pct || 0),
    };
    Object.keys(payload).forEach((k) => {
      if (payload[k] === null || payload[k] === "") delete payload[k];
    });
    try {
      if (plan.id) {
        await api.planUpdate(plan.id, payload);
      } else {
        await api.planCreate(payload);
      }
      setEditing(null);
      await load();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };

  const onDelete = async (plan) => {
    if (!await window.confirm(`Excluir o plano "${plan.name}"? Essa ação é irreversível.`)) return;
    try {
      await api.planDelete(plan.id);
      await load();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };

  const onToggleActive = async (plan) => {
    try {
      await api.planUpdate(plan.id, { active: !plan.active });
      await load();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };

  return (
    <div data-testid="plans-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div className="surface" style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, var(--accent-soft) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg, #0d9488, #06b6d4)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(13,148,136,.35)",
        }}>
          <Sparkles size={22} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                       letterSpacing: "-0.02em" }}>
            Planos Comerciais
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            Velocidade · Valor mensal · Reajuste anual de inflação. Usado no
            cadastro de Assinantes.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ position: "relative" }}>
            <Search size={13} style={{
              position: "absolute", left: 10, top: "50%",
              transform: "translateY(-50%)", color: "var(--text-muted)",
            }} />
            <input className="input" placeholder="Buscar plano..."
                    value={search} onChange={(e) => setSearch(e.target.value)}
                    style={{ paddingLeft: 30, minWidth: 200 }} />
          </div>
          <button className="btn btn-primary btn-sm"
                  onClick={() => setEditing({ ...EMPTY_PLAN })}
                  data-testid="plans-add-btn">
            <Plus size={13} /> Novo plano
          </button>
        </div>
      </div>

      {/* Editor (modal-style inline) */}
      {editing && (
        <PlanEditor plan={editing} onChange={setEditing}
                     onSave={() => onSave(editing)}
                     onCancel={() => setEditing(null)} />
      )}

      {/* Reajustes agendados (pendentes) */}
      {scheduled.length > 0 && (
        <ScheduledAdjustmentsCard items={scheduled} onChange={load} />
      )}

      {/* Lista */}
      {loading ? (
        <div className="surface" style={{ padding: 30, textAlign: "center",
                                            color: "var(--text-muted)" }}>
          Carregando planos...
        </div>
      ) : filtered.length === 0 ? (
        <div className="surface" style={{ padding: 30, textAlign: "center",
                                            color: "var(--text-muted)" }}>
          {items.length === 0
            ? "Nenhum plano cadastrado ainda. Crie o primeiro!"
            : "Nenhum plano bate com a busca."}
        </div>
      ) : (
        <div style={{ display: "grid", gap: 10,
                       gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
          {filtered.map((p) => (
            <PlanCard key={p.id} plan={p}
                      onEdit={() => setEditing({ ...p })}
                      onAdjust={() => setAdjusting(p)}
                      onToggleActive={() => onToggleActive(p)}
                      onDelete={() => onDelete(p)} />
          ))}
        </div>
      )}

      {adjusting && (
        <AdjustmentModal plan={adjusting}
                          onClose={() => setAdjusting(null)}
                          onApplied={() => { setAdjusting(null); load(); }} />
      )}
    </div>
  );
}
