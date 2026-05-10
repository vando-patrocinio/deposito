import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Plus, Save, X, Edit2, Trash2, Search, Zap, TrendingUp,
  Power, PowerOff, Sparkles,
} from "lucide-react";

/* =============================================================
   PlansPanel — CRUD dos planos comerciais do provedor.
   Cada plano: nome, velocidade (down/up), valor mensal, reajuste anual (%).
   Usado depois em SubscribersPanel como dropdown.
============================================================= */

const EMPTY_PLAN = {
  name: "", speed_down_mbps: "", speed_up_mbps: "",
  monthly_price: "", annual_adjustment_pct: 0,
  description: "", active: true,
};

export default function PlansPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.plansList();
      setItems(r.items || []);
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
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };

  const onDelete = async (plan) => {
    if (!window.confirm(`Excluir o plano "${plan.name}"? Essa ação é irreversível.`)) return;
    try {
      await api.planDelete(plan.id);
      await load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };

  const onToggleActive = async (plan) => {
    try {
      await api.planUpdate(plan.id, { active: !plan.active });
      await load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
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
                      onToggleActive={() => onToggleActive(p)}
                      onDelete={() => onDelete(p)} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================= */
function PlanCard({ plan, onEdit, onToggleActive, onDelete }) {
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

      <div style={{ display: "flex", gap: 6, marginTop: "auto" }}>
        <button onClick={onEdit} className="btn btn-ghost btn-sm"
                data-testid={`plan-edit-${plan.id}`}>
          <Edit2 size={11} /> Editar
        </button>
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

/* ============================================================= */
function PlanEditor({ plan, onChange, onSave, onCancel }) {
  const set = (k, v) => onChange({ ...plan, [k]: v });
  const canSave = (plan.name || "").trim().length >= 2
    && (plan.monthly_price === 0 || plan.monthly_price > 0
        || (typeof plan.monthly_price === "string"
            && parseFloat(plan.monthly_price) >= 0));

  return (
    <div className="surface" data-testid="plan-editor" style={{
      padding: 18, borderRadius: 14,
      border: "2px solid var(--accent)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                     marginBottom: 14 }}>
        <Sparkles size={16} style={{ color: "var(--accent)" }} />
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>
          {plan.id ? `Editar plano: ${plan.name || "—"}` : "Novo plano"}
        </h3>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr",
                     gap: 12, marginBottom: 12 }}>
        <Field label="Nome do plano *">
          <input className="input" autoFocus
                  data-testid="plan-name"
                  value={plan.name || ""}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="Ex.: Fibra 500 Mega" />
        </Field>
        <Field label="Velocidade Download (Mbps)">
          <input className="input" type="number" min="1"
                  data-testid="plan-speed-down"
                  value={plan.speed_down_mbps || ""}
                  onChange={(e) => set("speed_down_mbps", e.target.value)}
                  placeholder="500" />
        </Field>
        <Field label="Velocidade Upload (Mbps)">
          <input className="input" type="number" min="1"
                  value={plan.speed_up_mbps || ""}
                  onChange={(e) => set("speed_up_mbps", e.target.value)}
                  placeholder="opcional" />
        </Field>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12,
                     marginBottom: 12 }}>
        <Field label="Valor mensal (R$) *">
          <input className="input" type="number" step="0.01" min="0"
                  data-testid="plan-price"
                  value={plan.monthly_price ?? ""}
                  onChange={(e) => set("monthly_price", e.target.value)}
                  placeholder="99.90" />
        </Field>
        <Field label="Reajuste anual de inflação (%)">
          <input className="input" type="number" step="0.1" min="0" max="100"
                  data-testid="plan-adjustment"
                  value={plan.annual_adjustment_pct ?? 0}
                  onChange={(e) => set("annual_adjustment_pct", e.target.value)}
                  placeholder="6.5" />
        </Field>
      </div>
      <Field label="Descrição (opcional)">
        <textarea className="input" rows={2}
                   value={plan.description || ""}
                   onChange={(e) => set("description", e.target.value)}
                   placeholder="Ex.: Plano mais vendido, ideal pra streaming 4K..." />
      </Field>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                     marginTop: 14 }}>
        <button onClick={onCancel} className="btn btn-ghost btn-sm">
          <X size={12} /> Cancelar
        </button>
        <button onClick={onSave} disabled={!canSave}
                data-testid="plan-save"
                className="btn btn-primary btn-sm">
          <Save size={12} /> Salvar
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 11, color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.4,
                     fontWeight: 700, marginBottom: 5 }}>
        {label}
      </div>
      {children}
    </label>
  );
}
