/**
 * IsabellaNegotiationRulesCard.jsx — Card de Guardrails Isabella (P0 CTO 2026-02).
 *
 * Sem trava, qualquer cliente que pedir desconto/promessa via WhatsApp pode
 * receber resposta inventada pela IA. Este card permite ao gestor ligar/
 * desligar e calibrar limites de cada ação negociável.
 *
 * DEFAULT: tudo OFF (failsafe). Toggle explícito necessário para liberar.
 */
import React, { useEffect, useState } from "react";
import { Shield, ShieldAlert, ShieldCheck, AlertTriangle, Save, Settings2 } from "lucide-react";
import { api } from "@/api";

const ACTION_META = {
  promise_payment: {
    label: "Promessa de pagamento",
    desc: "Cliente promete pagar até X dias.",
    risk: "Pode atrasar receita se sem limite.",
    fields: [
      { key: "max_dias_extensao", label: "Máx. dias de extensão", type: "number", min: 1, max: 30 },
      { key: "max_promessas_por_ano", label: "Máx. promessas/ano por cliente", type: "number", min: 1, max: 12 },
    ],
  },
  discount: {
    label: "Desconto",
    desc: "IA oferece % ou R$ de desconto na fatura.",
    risk: "Sem teto = perda financeira imediata.",
    fields: [
      { key: "max_pct", label: "Máx. % de desconto", type: "number", min: 0, max: 100, step: 0.5 },
      { key: "max_brl", label: "Máx. R$ de desconto", type: "number", min: 0, step: 1 },
      { key: "requer_aprovacao_humana_acima_de_brl", label: "Acima de R$ exige humano", type: "number", min: 0, step: 1 },
    ],
  },
  second_invoice: {
    label: "Segunda via",
    desc: "Reenvio do boleto/PIX da fatura aberta.",
    risk: "Spam se sem cap mensal.",
    fields: [
      { key: "max_por_mes", label: "Máx. solicitações/mês por cliente", type: "number", min: 1, max: 30 },
    ],
  },
  installment: {
    label: "Parcelamento",
    desc: "Divide fatura em N parcelas.",
    risk: "Compromete fluxo de caixa.",
    fields: [
      { key: "max_parcelas", label: "Máx. parcelas", type: "number", min: 1, max: 24 },
      { key: "juros_pct", label: "Juros %", type: "number", min: 0, step: 0.1 },
    ],
  },
};

export default function IsabellaNegotiationRulesCard() {
  const [doc, setDoc] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);

  const load = async () => {
    try {
      const r = await api.isabellaNegotiationRules();
      setDoc(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  };
  useEffect(() => { load(); }, []);

  const updateField = (action, key, value) => {
    setDoc((s) => ({
      ...s,
      rules: {
        ...s.rules,
        [action]: { ...s.rules[action], [key]: value },
      },
    }));
  };

  const toggle = (action) => {
    updateField(action, "enabled", !doc.rules[action]?.enabled);
  };

  const save = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const out = await api.isabellaNegotiationRulesUpdate(doc.rules);
      setDoc(out);
      setMsg("Regras salvas. IA usará nas próximas decisões.");
      setTimeout(() => setMsg(null), 4000);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!doc) {
    return (
      <div data-testid="isabella-negotiation-card-loading" className="card"
        style={{ padding: 16 }}>
        <Shield size={16} /> Carregando regras…
      </div>
    );
  }

  const anyEnabled = Object.values(doc.rules || {}).some((r) => r?.enabled);

  return (
    <div data-testid="isabella-negotiation-card" className="card"
      style={{ padding: 16, marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
        marginBottom: 10, flexWrap: "wrap" }}>
        <Settings2 size={18} style={{ color: "var(--accent, #ff6b1a)" }} />
        <div>
          <h3 style={{ margin: 0, fontSize: 16 }}>
            Guardrails da Isabella · Negociação
          </h3>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            Define o que IA pode oferecer ao cliente. Default: tudo desligado.
          </div>
        </div>
        <span data-testid="isabella-negotiation-mode-badge" style={{
          marginLeft: "auto", fontSize: 11, fontWeight: 700,
          padding: "4px 10px", borderRadius: 999,
          background: anyEnabled ? "#fef3c7" : "#dcfce7",
          color: anyEnabled ? "#92400e" : "#166534",
          display: "inline-flex", alignItems: "center", gap: 4,
        }}>
          {anyEnabled
            ? <><ShieldAlert size={12} /> NEGOCIAÇÃO ATIVA</>
            : <><ShieldCheck size={12} /> MODO FAILSAFE (tudo OFF)</>}
        </span>
      </div>

      <div style={{ display: "grid", gap: 12 }}>
        {Object.entries(ACTION_META).map(([action, meta]) => {
          const cfg = doc.rules?.[action] || {};
          return (
            <div key={action} data-testid={`neg-rule-${action}`}
              style={{
                border: `1px solid ${cfg.enabled ? "#f59e0b" : "#e2e8f0"}`,
                borderRadius: 10, padding: 12,
                background: cfg.enabled ? "#fffbeb" : "#fafafa",
              }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <label style={{ display: "inline-flex", alignItems: "center",
                  gap: 8, cursor: "pointer", flex: 1 }}>
                  <input
                    type="checkbox"
                    data-testid={`neg-toggle-${action}`}
                    checked={!!cfg.enabled}
                    onChange={() => toggle(action)}
                    style={{ width: 18, height: 18, cursor: "pointer" }}
                  />
                  <strong style={{ fontSize: 14 }}>{meta.label}</strong>
                </label>
                <span style={{ fontSize: 10, color: "#94a3b8" }}>
                  {cfg.enabled ? "LIGADA" : "desligada"}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "#475569",
                marginTop: 4, marginLeft: 26 }}>{meta.desc}</div>
              <div style={{ fontSize: 11, color: "#b45309",
                marginTop: 2, marginLeft: 26,
                display: "inline-flex", alignItems: "center", gap: 4 }}>
                <AlertTriangle size={10} /> {meta.risk}
              </div>
              {cfg.enabled && (
                <div data-testid={`neg-fields-${action}`} style={{
                  display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: 8, marginTop: 10, marginLeft: 26,
                }}>
                  {meta.fields.map((f) => (
                    <div key={f.key}>
                      <div style={{ fontSize: 10, color: "#64748b",
                        marginBottom: 3, fontWeight: 600 }}>{f.label}</div>
                      <input
                        data-testid={`neg-field-${action}-${f.key}`}
                        type={f.type}
                        min={f.min} max={f.max} step={f.step || 1}
                        value={cfg[f.key] ?? ""}
                        onChange={(e) => updateField(action, f.key,
                          f.type === "number" ? parseFloat(e.target.value || 0) : e.target.value)}
                        style={{
                          width: "100%", padding: "6px 8px", fontSize: 13,
                          border: "1px solid #cbd5e1", borderRadius: 6,
                        }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {err && (
        <div data-testid="neg-err" style={{
          background: "#fee2e2", color: "#991b1b", padding: 10,
          borderRadius: 8, marginTop: 12, fontSize: 12,
        }}>{err}</div>
      )}
      {msg && (
        <div data-testid="neg-msg" style={{
          background: "#dcfce7", color: "#166534", padding: 10,
          borderRadius: 8, marginTop: 12, fontSize: 12,
        }}>{msg}</div>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end",
        marginTop: 14 }}>
        <button data-testid="neg-save-btn" onClick={save} disabled={busy}
          className="btn btn-primary"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Save size={14} /> {busy ? "Salvando…" : "Salvar regras"}
        </button>
      </div>

      <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 10,
        fontStyle: "italic" }}>
        Última atualização: {doc.updated_at || "—"} por {doc.updated_by || "—"}
      </div>
    </div>
  );
}
