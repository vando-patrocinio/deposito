import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  X, Calculator, Calendar, AlertTriangle, Check, Sparkles,
  Users, DollarSign, TrendingUp,
} from "lucide-react";
import { Field, KpiCard } from "./_shared";

/* =============================================================
   AdjustmentModal — Simulador de reajuste anual.
   Pega o annual_adjustment_pct do plano (ou um override), calcula impacto
   nos assinantes ATIVOS, mostra preview (delta receita mensal + anual)
   e permite aplicar com 1 confirmação OU agendar (min. 30 dias — Marco Civil).
============================================================= */
export default function AdjustmentModal({ plan, onClose, onApplied }) {
  const [pctOverride, setPctOverride] = useState("");
  const [onlyActive, setOnlyActive] = useState(true);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [confirmStep, setConfirmStep] = useState(false);
  const [history, setHistory] = useState([]);
  /* Modos: "now" aplica imediatamente; "schedule" agenda pra data futura
     (default sugerido = 30 dias à frente — exigência Marco Civil). */
  const [mode, setMode] = useState("now");
  const [scheduleDate, setScheduleDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 31);  // 31 dias à frente — passa em min_days=30
    return d.toISOString().split("T")[0];
  });
  const [scheduleNote, setScheduleNote] = useState("");

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
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
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
      if (mode === "schedule") {
        body.scheduled_for = scheduleDate;
        body.min_days = 30;
        if (scheduleNote.trim()) body.note = scheduleNote.trim();
        await api.planAdjustmentSchedule(plan.id, body);
      } else {
        await api.planAdjustmentApply(plan.id, body);
      }
      onApplied();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
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

          {/* Modo: Aplicar agora OU agendar */}
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8,
          }}>
            <button onClick={() => setMode("now")}
                    data-testid="adj-mode-now"
                    style={{
                      padding: 12, borderRadius: 10, cursor: "pointer",
                      border: mode === "now"
                        ? "2px solid #f59e0b"
                        : "1px solid var(--border-default)",
                      background: mode === "now"
                        ? "rgba(245,158,11,.08)" : "var(--bg-surface)",
                      textAlign: "left",
                    }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6,
                             marginBottom: 4 }}>
                <Calculator size={13} style={{ color: "#f59e0b" }} />
                <strong style={{ fontSize: 13 }}>Aplicar agora</strong>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Reajuste imediato. Use quando já houve aviso prévio.
              </div>
            </button>
            <button onClick={() => setMode("schedule")}
                    data-testid="adj-mode-schedule"
                    style={{
                      padding: 12, borderRadius: 10, cursor: "pointer",
                      border: mode === "schedule"
                        ? "2px solid #0284c7"
                        : "1px solid var(--border-default)",
                      background: mode === "schedule"
                        ? "rgba(2,132,199,.08)" : "var(--bg-surface)",
                      textAlign: "left",
                    }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6,
                             marginBottom: 4 }}>
                <Calendar size={13} style={{ color: "#0284c7" }} />
                <strong style={{ fontSize: 13 }}>Agendar (Marco Civil 30d)</strong>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Aplicação automática na data marcada. Mínimo 30 dias.
              </div>
            </button>
          </div>

          {mode === "schedule" && (
            <div style={{
              padding: 14, borderRadius: 10,
              border: "1px solid rgba(2,132,199,.35)",
              background: "rgba(2,132,199,.05)",
              display: "grid", gridTemplateColumns: "1fr 2fr", gap: 12,
            }}>
              <Field label="Aplicar em (data)">
                <input className="input" type="date"
                        data-testid="adj-schedule-date"
                        value={scheduleDate}
                        min={new Date(Date.now() + 31 * 86400000)
                          .toISOString().split("T")[0]}
                        onChange={(e) => setScheduleDate(e.target.value)} />
              </Field>
              <Field label="Nota (opcional — aparece no histórico)">
                <input className="input"
                        value={scheduleNote}
                        onChange={(e) => setScheduleNote(e.target.value)}
                        placeholder="Ex.: Reajuste IPCA anual conforme contrato" />
              </Field>
            </div>
          )}

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
                        background: mode === "schedule"
                          ? "linear-gradient(135deg, #0284c7, #0369a1)"
                          : "linear-gradient(135deg, #f59e0b, #d97706)",
                        boxShadow: mode === "schedule"
                          ? "0 4px 12px rgba(2,132,199,.35)"
                          : "0 4px 12px rgba(245,158,11,.35)",
                      }}>
                {mode === "schedule"
                  ? <><Calendar size={12} /> Revisar e agendar</>
                  : <><Calculator size={12} /> Revisar e aplicar</>}
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
                    ? (mode === "schedule" ? "Agendando..." : "Aplicando...")
                    : mode === "schedule"
                      ? `Confirmar agendamento (+${preview.pct_applied}% em ${new Date(scheduleDate).toLocaleDateString("pt-BR")})`
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
