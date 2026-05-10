import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Plus, Save, X, Edit2, Trash2, Search, Zap, TrendingUp,
  Power, PowerOff, Sparkles, Calculator, AlertTriangle, Check,
  Users, DollarSign,
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
  const [adjusting, setAdjusting] = useState(null);
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

/* ============================================================= */
function PlanCard({ plan, onEdit, onAdjust, onToggleActive, onDelete }) {
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

/* =============================================================
   AdjustmentModal — Simulador de reajuste anual.
   Pega o annual_adjustment_pct do plano (ou um override), calcula impacto
   nos assinantes ATIVOS, mostra preview (delta receita mensal + anual)
   e permite aplicar com 1 confirmação.
============================================================= */
function AdjustmentModal({ plan, onClose, onApplied }) {
  const [pctOverride, setPctOverride] = useState("");
  const [onlyActive, setOnlyActive] = useState(true);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [confirmStep, setConfirmStep] = useState(false);
  const [history, setHistory] = useState([]);

  const fmt = (v) => new Intl.NumberFormat("pt-BR",
        { style: "currency", currency: "BRL" }).format(v || 0);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    try {
      const body = { only_active_subscribers: onlyActive };
      if (pctOverride !== "" && Number(pctOverride) > 0) {
        body.pct_override = Number(pctOverride);
      }
      const r = await api.planAdjustmentPreview(plan.id, body);
      setPreview(r);
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  }, [plan.id, pctOverride, onlyActive]);

  useEffect(() => { loadPreview(); }, [loadPreview]);

  useEffect(() => {
    api.planAdjustmentHistory(plan.id)
      .then((r) => setHistory(r.items || []))
      .catch(() => {});
  }, [plan.id]);

  const apply = async () => {
    setApplying(true);
    try {
      const body = { only_active_subscribers: onlyActive };
      if (pctOverride !== "" && Number(pctOverride) > 0) {
        body.pct_override = Number(pctOverride);
      }
      await api.planAdjustmentApply(plan.id, body);
      onApplied();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
      setApplying(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
      display: "grid", placeItems: "center", zIndex: 1100,
    }} data-testid="adjustment-modal">
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg-surface)",
        borderRadius: 16, width: 640, maxHeight: "92vh", overflow: "auto",
        boxShadow: "0 20px 50px rgba(0,0,0,.4)",
      }}>
        {/* Header */}
        <div style={{
          padding: "20px 22px",
          background: "linear-gradient(135deg, rgba(245,158,11,.12), rgba(245,158,11,.04))",
          borderBottom: "1px solid var(--border-default)",
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12,
            background: "linear-gradient(135deg, #f59e0b, #d97706)",
            color: "#fff", display: "grid", placeItems: "center",
            boxShadow: "0 4px 14px rgba(245,158,11,.4)",
          }}>
            <Calculator size={20} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                          letterSpacing: "-0.02em" }}>
              Reajuste anual — {plan.name}
            </h3>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              Simule o impacto financeiro antes de aplicar
            </div>
          </div>
          <button onClick={onClose} className="btn btn-ghost btn-sm"><X size={14} /></button>
        </div>

        <div style={{ padding: 20, display: "grid", gap: 16 }}>
          {/* Controles */}
          <div style={{
            padding: 14, borderRadius: 10,
            border: "1px solid var(--border-default)",
            background: "var(--bg-surface-2)",
          }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12,
                           alignItems: "end" }}>
              <Field label={`Percentual de reajuste (% — configurado: ${plan.annual_adjustment_pct || 0}%)`}>
                <input className="input" type="number" step="0.1" min="0" max="100"
                        data-testid="adj-pct-override"
                        value={pctOverride}
                        onChange={(e) => setPctOverride(e.target.value)}
                        placeholder={String(plan.annual_adjustment_pct || 0)} />
              </Field>
              <label style={{ display: "flex", alignItems: "center", gap: 8,
                                fontSize: 12, color: "var(--text-primary)",
                                paddingBottom: 8 }}>
                <input type="checkbox" checked={onlyActive}
                        onChange={(e) => setOnlyActive(e.target.checked)}
                        data-testid="adj-only-active" />
                Aplicar apenas a assinantes ativos/em instalação/inadimplentes
              </label>
            </div>
          </div>

          {loading ? (
            <div style={{ textAlign: "center", padding: 30,
                           color: "var(--text-muted)" }}>
              Calculando impacto...
            </div>
          ) : !preview ? null : preview.affected_subscribers === 0 ? (
            <div style={{
              padding: 18, borderRadius: 10,
              background: "rgba(148,163,184,.10)",
              border: "1px dashed rgba(148,163,184,.4)",
              display: "flex", gap: 10, alignItems: "flex-start",
            }}>
              <AlertTriangle size={16} style={{ color: "#64748b", marginTop: 2 }} />
              <div>
                <strong style={{ fontSize: 13 }}>Nenhum assinante seria afetado.</strong>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 3 }}>
                  Sem clientes ativos neste plano. O reajuste só altera o
                  preço base do plano, sem impacto financeiro imediato.
                </div>
              </div>
            </div>
          ) : (
            <>
              {/* Cards de KPI */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                             gap: 12 }}>
                <KpiCard icon={Users} color="#0d9488"
                          label="Assinantes afetados"
                          value={preview.affected_subscribers} />
                <KpiCard icon={TrendingUp} color="#f59e0b"
                          label="Por assinante"
                          value={fmt(preview.delta_per_subscriber)}
                          sub={`${fmt(preview.plan.current_price)} → ${fmt(preview.new_price)}`} />
                <KpiCard icon={DollarSign} color="#0284c7"
                          label="Receita mensal +"
                          value={fmt(preview.delta_monthly_revenue)}
                          sub={`de ${fmt(preview.current_monthly_revenue)} para ${fmt(preview.new_monthly_revenue)}`} />
                <KpiCard icon={Sparkles} color="#15803d"
                          label="Receita anual +"
                          value={fmt(preview.delta_annual_revenue)}
                          sub="impacto em 12 meses" />
              </div>

              {/* Amostra de assinantes */}
              {preview.sample_subscribers?.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 800,
                                 color: "var(--text-muted)",
                                 textTransform: "uppercase",
                                 letterSpacing: 0.4, marginBottom: 8 }}>
                    Exemplos de assinantes impactados
                  </div>
                  <div style={{ display: "grid", gap: 5 }}>
                    {preview.sample_subscribers.map((s) => (
                      <div key={s.id} style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "8px 11px", borderRadius: 7,
                        background: "var(--bg-surface-2)",
                        fontSize: 12,
                      }}>
                        <span style={{ fontFamily: "ui-monospace, monospace",
                                         color: "var(--text-muted)",
                                         minWidth: 80, fontSize: 11 }}>
                          {s.external_code || "—"}
                        </span>
                        <strong style={{ flex: 1, minWidth: 0,
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap" }}>
                          {s.name}
                        </strong>
                        {s.branch && (
                          <span style={{
                            padding: "1px 7px", borderRadius: 5,
                            background: "rgba(100,116,139,.15)",
                            color: "var(--text-secondary)",
                            fontSize: 9, fontWeight: 700, letterSpacing: 0.3,
                            textTransform: "uppercase",
                          }}>{s.branch}</span>
                        )}
                        <span style={{
                          padding: "1px 7px", borderRadius: 5,
                          background: s.status === "ATIVO" ? "rgba(34,197,94,.15)"
                            : s.status === "INADIMPLENTE" ? "rgba(220,38,38,.15)"
                            : "rgba(245,158,11,.15)",
                          color: s.status === "ATIVO" ? "#15803d"
                            : s.status === "INADIMPLENTE" ? "#b91c1c"
                            : "#b45309",
                          fontSize: 9, fontWeight: 700,
                        }}>{s.status}</span>
                      </div>
                    ))}
                    {preview.affected_subscribers > preview.sample_subscribers.length && (
                      <div style={{ fontSize: 11, color: "var(--text-muted)",
                                     textAlign: "center", marginTop: 4 }}>
                        + {preview.affected_subscribers - preview.sample_subscribers.length} outro(s) assinante(s)
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Histórico */}
          {history.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 800,
                             color: "var(--text-muted)",
                             textTransform: "uppercase",
                             letterSpacing: 0.4, marginBottom: 8 }}>
                Histórico de reajustes deste plano
              </div>
              <div style={{ display: "grid", gap: 4 }}>
                {history.slice(0, 5).map((h) => (
                  <div key={h.id} style={{
                    fontSize: 11, color: "var(--text-secondary)",
                    padding: "6px 10px", borderRadius: 6,
                    background: "var(--bg-surface-2)",
                    display: "flex", gap: 8,
                  }}>
                    <span>{new Date(h.applied_at).toLocaleDateString("pt-BR")}</span>
                    <span>·</span>
                    <span><strong>+{h.pct_applied}%</strong></span>
                    <span>·</span>
                    <span>{fmt(h.previous_price)} → {fmt(h.new_price)}</span>
                    <span>·</span>
                    <span>{h.affected_subscribers} assinante(s)</span>
                    <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>
                      por {h.applied_by_name || h.applied_by}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Ações */}
          <div style={{
            display: "flex", gap: 8, justifyContent: "flex-end",
            marginTop: 4, paddingTop: 14,
            borderTop: "1px solid var(--border-default)",
          }}>
            <button onClick={onClose} className="btn btn-ghost btn-sm">
              <X size={12} /> Fechar sem aplicar
            </button>
            {preview && !confirmStep && (
              <button onClick={() => setConfirmStep(true)}
                      data-testid="adj-confirm-step"
                      disabled={applying}
                      className="btn btn-primary btn-sm"
                      style={{
                        background: "linear-gradient(135deg, #f59e0b, #d97706)",
                        boxShadow: "0 4px 12px rgba(245,158,11,.35)",
                      }}>
                <Calculator size={12} /> Revisar e aplicar
              </button>
            )}
            {preview && confirmStep && (
              <>
                <button onClick={() => setConfirmStep(false)}
                        className="btn btn-ghost btn-sm">
                  Voltar
                </button>
                <button onClick={apply}
                        data-testid="adj-apply-confirm"
                        disabled={applying}
                        className="btn btn-primary btn-sm"
                        style={{
                          background: "linear-gradient(135deg, #16a34a, #15803d)",
                        }}>
                  <Check size={12} />
                  {applying
                    ? "Aplicando..."
                    : `Confirmar reajuste de +${preview.pct_applied}%`}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function KpiCard({ icon: Ico, color, label, value, sub }) {
  return (
    <div style={{
      padding: 14, borderRadius: 12,
      border: `1px solid ${color}33`,
      background: `${color}0A`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                     marginBottom: 6 }}>
        <Ico size={12} strokeWidth={2} style={{ color }} />
        <span style={{ fontSize: 10, fontWeight: 800, color,
                         textTransform: "uppercase", letterSpacing: 0.4 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 20, fontWeight: 800,
                     color: "var(--text-primary)",
                     letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  );
}
