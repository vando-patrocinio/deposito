import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Card, Metric } from "@/ui";
import { DollarSign, RefreshCw, Loader2, BarChart3, Layers } from "lucide-react";

const PERIODS = [
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
  { label: "90 dias", days: 90 },
];

function fmtUSD(n) {
  const v = Number(n || 0);
  if (v === 0) return "US$ 0,00";
  if (v < 0.01) return `US$ ${v.toFixed(4)}`;
  return `US$ ${v.toFixed(2)}`;
}
function fmtNum(n) {
  return Number(n || 0).toLocaleString("pt-BR");
}

// Mapeia service → cor de destaque (gradient)
const SERVICE_COLOR = {
  text:   "linear-gradient(90deg, #6366f1, #8b5cf6)",
  vision: "linear-gradient(90deg, #10b981, #14b8a6)",
  stt:    "linear-gradient(90deg, #f59e0b, #f97316)",
  tts:    "linear-gradient(90deg, #ec4899, #f43f5e)",
};
const SERVICE_ICON = {
  text:   "",
  vision: "️",
  stt:    "",
  tts:    "",
};
const SERVICE_LABEL_SHORT = {
  text:   "Texto",
  vision: "Visão",
  stt:    "STT",
  tts:    "TTS",
  total:  "Total",
};

// Formata "qtd. unidade" pra cada serviço
function fmtAgentUnits(a) {
  const svc = a.service || "text";
  if (svc === "vision") return `${fmtNum(a.units)} img`;
  if (svc === "stt")    return `${fmtNum(a.units)} seg`;
  if (svc === "tts")    return `${fmtNum(a.units)} chars`;
  return `${fmtNum(a.total_tokens)} tok`;
}

/**
 * Motor IA — Dashboard de Custos.
 * Mostra tokens consumidos e custo estimado (USD) por agente, modelo e dia.
 * Permite identificar onde o orçamento de IA está sendo gasto.
 */
export default function MotorIaUsageCard() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [todayStatus, setTodayStatus] = useState(null);
  const [budget, setBudget] = useState(null);
  const [showLimits, setShowLimits] = useState(false);
  const [savingLimits, setSavingLimits] = useState(false);
  const [draftLimits, setDraftLimits] = useState({
    daily_limit_usd: 0, vision: 0, stt: 0, tts: 0, text: 0,
  });

  const load = async (d = days) => {
    setLoading(true); setErr("");
    try {
      const [res, today, b] = await Promise.all([
        api.motorIaUsage(d),
        api.motorIaBudgetStatusToday().catch(() => null),
        api.motorIaBudgetGet().catch(() => null),
      ]);
      setData(res);
      setTodayStatus(today);
      if (b) {
        setBudget(b);
        const sl = b.daily_service_limits || {};
        setDraftLimits({
          daily_limit_usd: Number(b.daily_limit_usd || 0),
          vision: Number(sl.vision || 0),
          stt:    Number(sl.stt || 0),
          tts:    Number(sl.tts || 0),
          text:   Number(sl.text || 0),
        });
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro ao carregar uso");
    } finally {
      setLoading(false);
    }
  };

  const saveLimits = async () => {
    setSavingLimits(true);
    try {
      await api.motorIaBudgetSave({
        daily_limit_usd: Number(draftLimits.daily_limit_usd) || 0,
        daily_service_limits: {
          vision: Number(draftLimits.vision) || 0,
          stt:    Number(draftLimits.stt) || 0,
          tts:    Number(draftLimits.tts) || 0,
          text:   Number(draftLimits.text) || 0,
        },
      });
      const today = await api.motorIaBudgetStatusToday().catch(() => null);
      setTodayStatus(today);
      setShowLimits(false);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro ao salvar limites");
    } finally {
      setSavingLimits(false);
    }
  };

  useEffect(() => { load(days); /* eslint-disable-next-line */ }, [days]);

  const maxCostAgent = useMemo(() => {
    if (!data?.by_agent?.length) return 0;
    return Math.max(...data.by_agent.map((a) => a.cost_usd || 0), 0.0001);
  }, [data]);

  const maxDaily = useMemo(() => {
    if (!data?.daily?.length) return 0;
    return Math.max(...data.daily.map((d) => d.cost_usd || 0), 0.0001);
  }, [data]);

  return (
    <Card
      title="Custo do Motor IA"
      subtitle="Tokens e custo estimado por agente, modelo e dia. Use para identificar onde o orçamento de IA é gasto."
      action={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 4, background: "var(--surface-2, #f1f5f9)",
                          padding: 3, borderRadius: 8 }}>
            {PERIODS.map((p) => (
              <button
                key={p.days}
                onClick={() => setDays(p.days)}
                data-testid={`usage-period-${p.days}`}
                style={{
                  padding: "5px 10px", border: 0, borderRadius: 6, cursor: "pointer",
                  fontSize: 12, fontWeight: 600,
                  background: days === p.days ? "var(--surface, #fff)" : "transparent",
                  color: days === p.days ? "var(--text-primary, #0f172a)" : "var(--text-muted, #64748b)",
                  boxShadow: days === p.days ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                }}
              >{p.label}</button>
            ))}
          </div>
          <button
            onClick={() => load(days)} disabled={loading}
            data-testid="usage-refresh-btn"
            style={{
              padding: "6px 10px", border: "1px solid var(--border, #e2e8f0)",
              background: "var(--surface, #fff)", borderRadius: 8, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12,
              color: "var(--text-muted, #64748b)",
            }}
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Atualizar
          </button>
        </div>
      }
      data-testid="motor-ia-usage-card"
    >
      {err && (
        <div style={{ padding: 10, background: "#fef2f2", color: "#be123c",
                        borderRadius: 8, fontSize: 13, marginBottom: 12 }}>
          {err}
        </div>
      )}

      {/* Banner de alerta diário */}
      {todayStatus?.has_alerts && (
        <div data-testid="usage-daily-alert"
             style={{
               display: "flex", alignItems: "center", gap: 10,
               padding: "10px 12px", marginBottom: 12,
               background: todayStatus.alerts.some((a) => a.status === "exceeded")
                 ? "linear-gradient(90deg, #fee2e2, #fecaca)"
                 : "linear-gradient(90deg, #fef3c7, #fde68a)",
               borderRadius: 10, border: "1px solid #fca5a5",
               fontSize: 12.5, color: "#7f1d1d",
             }}>
          <span aria-hidden style={{ fontSize: 18 }}>
            {todayStatus.alerts.some((a) => a.status === "exceeded") ? "" : "️"}
          </span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>
              {todayStatus.alerts.some((a) => a.status === "exceeded")
                ? "Limite diário ULTRAPASSADO"
                : "Atenção: limite diário próximo do teto"}
            </div>
            <div style={{ fontSize: 11.5, opacity: 0.85 }}>
              {todayStatus.alerts.map((a) => (
                <span key={a.service} style={{ marginRight: 10 }}>
                  <strong>{(SERVICE_LABEL_SHORT[a.service] || a.service)}</strong>
                  {": "}{fmtUSD(a.spent_usd)} / {fmtUSD(a.limit_usd)}
                </span>
              ))}
            </div>
          </div>
          <button
            onClick={() => setShowLimits((v) => !v)}
            data-testid="usage-limits-toggle"
            style={{
              padding: "5px 10px", border: "1px solid #fca5a5",
              background: "rgba(255,255,255,0.6)", color: "#7f1d1d",
              borderRadius: 6, cursor: "pointer", fontSize: 11, fontWeight: 600,
            }}
          >Ajustar limites</button>
        </div>
      )}

      {/* Mini-resumo do dia (quando não há alerta, mas há gasto) */}
      {!todayStatus?.has_alerts && todayStatus?.total_spent_usd > 0 && (
        <div data-testid="usage-today-summary"
             style={{
               display: "flex", alignItems: "center", gap: 10,
               padding: "8px 12px", marginBottom: 12,
               background: "var(--surface-2, #f1f5f9)", borderRadius: 8,
               fontSize: 11.5, color: "var(--text-muted, #64748b)",
             }}>
          <span aria-hidden></span>
          <div style={{ flex: 1 }}>
            Hoje: <strong style={{ color: "var(--text-primary, #0f172a)" }}>
              {fmtUSD(todayStatus.total_spent_usd)}
            </strong>
            {todayStatus.daily_limit_usd > 0 &&
              ` de ${fmtUSD(todayStatus.daily_limit_usd)} (${
                Math.round((todayStatus.total_spent_usd / todayStatus.daily_limit_usd) * 100)
              }%)`}
          </div>
          <button
            onClick={() => setShowLimits((v) => !v)}
            data-testid="usage-limits-toggle-mini"
            style={{
              padding: "3px 8px", border: "1px solid var(--border, #e2e8f0)",
              background: "var(--surface, #fff)",
              color: "var(--text-muted, #64748b)",
              borderRadius: 6, cursor: "pointer", fontSize: 10.5,
            }}
          >Limites</button>
        </div>
      )}

      {/* Painel de configuração de limites diários (colapsável) */}
      {showLimits && (
        <div data-testid="usage-limits-panel"
             style={{
               padding: 12, marginBottom: 14,
               background: "var(--surface-2, #f8fafc)",
               border: "1px dashed var(--border, #cbd5e1)",
               borderRadius: 10,
             }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8,
                          color: "var(--text-primary, #0f172a)" }}>
            Limites diários de gasto (USD)
            <span style={{ fontWeight: 400, fontSize: 11,
                            color: "var(--text-muted, #64748b)", marginLeft: 6 }}>
              · use 0 para desativar um serviço
            </span>
          </div>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                          gap: 10 }}>
            {[
              { k: "daily_limit_usd", label: "Total diário", icon: "" },
              { k: "text",   label: "Texto",          icon: SERVICE_ICON.text },
              { k: "vision", label: "Visão",          icon: SERVICE_ICON.vision },
              { k: "stt",    label: "STT (Whisper)",  icon: SERVICE_ICON.stt },
              { k: "tts",    label: "TTS",            icon: SERVICE_ICON.tts },
            ].map((f) => (
              <label key={f.k}
                     style={{ display: "flex", flexDirection: "column",
                                gap: 4, fontSize: 11,
                                color: "var(--text-muted, #64748b)" }}>
                <span>
                  <span aria-hidden style={{ marginRight: 3 }}>{f.icon}</span>
                  {f.label}
                </span>
                <input
                  type="number"
                  min="0"
                  step="0.5"
                  value={draftLimits[f.k]}
                  onChange={(e) => setDraftLimits((s) => ({
                    ...s, [f.k]: e.target.value,
                  }))}
                  data-testid={`usage-limit-input-${f.k}`}
                  style={{
                    padding: "6px 8px",
                    border: "1px solid var(--border, #e2e8f0)",
                    borderRadius: 6, fontSize: 13,
                    background: "var(--surface, #fff)",
                  }}
                />
              </label>
            ))}
          </div>
          <div style={{ marginTop: 10, display: "flex", gap: 8,
                          justifyContent: "flex-end" }}>
            <button
              onClick={() => setShowLimits(false)}
              data-testid="usage-limits-cancel"
              style={{
                padding: "6px 12px",
                border: "1px solid var(--border, #e2e8f0)",
                background: "var(--surface, #fff)",
                color: "var(--text-muted, #64748b)",
                borderRadius: 6, cursor: "pointer", fontSize: 12,
              }}
            >Cancelar</button>
            <button
              onClick={saveLimits} disabled={savingLimits}
              data-testid="usage-limits-save"
              style={{
                padding: "6px 12px", border: 0,
                background: "linear-gradient(90deg, #6366f1, #8b5cf6)",
                color: "#fff", borderRadius: 6,
                cursor: savingLimits ? "wait" : "pointer", fontSize: 12,
                fontWeight: 600,
              }}
            >{savingLimits ? "Salvando..." : "Salvar limites"}</button>
          </div>
        </div>
      )}

      {/* Totais */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                      gap: 12, marginBottom: 20 }}>
        <Metric label="Custo estimado"
                  value={fmtUSD(data?.totals?.cost_usd)}
                  hint={`${data?.totals?.calls || 0} chamada(s)`} />
        <Metric label="Tokens (entrada)"
                  value={fmtNum(data?.totals?.prompt_tokens)} mono />
        <Metric label="Tokens (saída)"
                  value={fmtNum(data?.totals?.completion_tokens)} mono />
        <Metric label="Tokens totais"
                  value={fmtNum(data?.totals?.total_tokens)} mono />
      </div>

      {/* Por agente — barras horizontais */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10,
                        color: "var(--text-primary, #0f172a)",
                        display: "flex", alignItems: "center", gap: 6 }}>
          <BarChart3 size={14} /> Custo por Agente
        </div>
        {!data?.by_agent?.length ? (
          <div style={{ fontSize: 12, color: "var(--text-muted, #64748b)",
                          padding: 12, textAlign: "center",
                          background: "var(--surface-2, #f8fafc)", borderRadius: 8 }}>
            Sem chamadas registradas no período.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }} data-testid="usage-by-agent">
            {data.by_agent.map((a) => {
              const pct = Math.max(2, ((a.cost_usd || 0) / maxCostAgent) * 100);
              const svc = a.service || "text";
              return (
                <div key={a.agent}
                     style={{ display: "grid",
                                gridTemplateColumns: "150px 1fr 100px 90px",
                                gap: 10, alignItems: "center", fontSize: 12 }}>
                  <div style={{ fontWeight: 600, color: "var(--text-primary, #0f172a)",
                                  whiteSpace: "nowrap", overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  display: "flex", alignItems: "center", gap: 4 }}
                       title={a.label}>
                    <span aria-hidden style={{ fontSize: 12 }}>
                      {SERVICE_ICON[svc] || ""}
                    </span>
                    {a.label}
                  </div>
                  <div style={{ background: "var(--surface-2, #f1f5f9)",
                                  height: 18, borderRadius: 4, overflow: "hidden" }}>
                    <div style={{
                      width: `${pct}%`,
                      height: "100%",
                      background: SERVICE_COLOR[svc] || SERVICE_COLOR.text,
                      transition: "width 0.5s ease",
                    }} />
                  </div>
                  <div style={{ textAlign: "right", color: "var(--text-muted, #64748b)",
                                  fontVariantNumeric: "tabular-nums" }}>
                    {fmtAgentUnits(a)}
                  </div>
                  <div style={{ textAlign: "right", fontWeight: 700,
                                  color: "var(--text-primary, #0f172a)",
                                  fontVariantNumeric: "tabular-nums" }}>
                    {fmtUSD(a.cost_usd)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Por serviço (Text / Vision / TTS / STT) */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10,
                        color: "var(--text-primary, #0f172a)",
                        display: "flex", alignItems: "center", gap: 6 }}>
          <Layers size={14} /> Custo por Serviço
        </div>
        {!data?.by_service?.length ? (
          <div style={{ fontSize: 12, color: "var(--text-muted, #64748b)",
                          padding: 12, textAlign: "center",
                          background: "var(--surface-2, #f8fafc)", borderRadius: 8 }}>
            Sem registros no período.
          </div>
        ) : (
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                          gap: 10 }}
               data-testid="usage-by-service">
            {data.by_service.map((s) => (
              <div key={s.service}
                   data-testid={`usage-service-${s.service}`}
                   style={{ padding: 12,
                              background: "var(--surface-2, #f8fafc)",
                              borderRadius: 10,
                              borderLeft: `3px solid transparent`,
                              borderImage: `${SERVICE_COLOR[s.service] || SERVICE_COLOR.text} 1`,
                              borderImageSlice: 1 }}>
                <div style={{ fontSize: 11,
                                color: "var(--text-muted, #64748b)",
                                marginBottom: 4, fontWeight: 600,
                                textTransform: "uppercase",
                                letterSpacing: 0.3 }}>
                  <span aria-hidden style={{ marginRight: 4 }}>
                    {SERVICE_ICON[s.service] || ""}
                  </span>
                  {s.label}
                </div>
                <div style={{ fontSize: 18, fontWeight: 800,
                                color: "var(--text-primary, #0f172a)",
                                fontVariantNumeric: "tabular-nums" }}>
                  {fmtUSD(s.cost_usd)}
                </div>
                <div style={{ fontSize: 11,
                                color: "var(--text-muted, #94a3b8)",
                                marginTop: 4,
                                fontVariantNumeric: "tabular-nums" }}>
                  {s.service === "text"
                    ? `${fmtNum(s.total_tokens)} ${s.unit_label}`
                    : `${fmtNum(s.units)} ${s.unit_label}`}
                  {" · "}{s.calls} call
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Por modelo */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10,
                        color: "var(--text-primary, #0f172a)",
                        display: "flex", alignItems: "center", gap: 6 }}>
          <DollarSign size={14} /> Custo por Modelo
        </div>
        {!data?.by_model?.length ? (
          <div style={{ fontSize: 12, color: "var(--text-muted, #64748b)" }}>—</div>
        ) : (
          <div style={{ display: "grid", gap: 6 }} data-testid="usage-by-model">
            {data.by_model.map((m) => (
              <div key={m.model}
                   style={{ display: "grid",
                              gridTemplateColumns: "1fr 90px 80px 90px",
                              gap: 10, alignItems: "center", fontSize: 12,
                              padding: "6px 10px",
                              background: "var(--surface-2, #f8fafc)",
                              borderRadius: 6 }}>
                <code style={{ fontSize: 11, color: "var(--text-primary, #0f172a)",
                                  whiteSpace: "nowrap", overflow: "hidden",
                                  textOverflow: "ellipsis" }}>
                  {m.model}
                </code>
                <div style={{ textAlign: "right", color: "var(--text-muted, #64748b)" }}>
                  {fmtNum(m.total_tokens)} tok
                </div>
                <div style={{ textAlign: "right", color: "var(--text-muted, #64748b)" }}>
                  {m.calls} call
                </div>
                <div style={{ textAlign: "right", fontWeight: 700,
                                color: "var(--text-primary, #0f172a)" }}>
                  {fmtUSD(m.cost_usd)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Série diária — sparkline */}
      {data?.daily?.length > 1 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10,
                          color: "var(--text-primary, #0f172a)" }}>
            Tendência diária ({data.window_days} dias)
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3,
                          height: 70, padding: 8,
                          background: "var(--surface-2, #f8fafc)",
                          borderRadius: 8 }}
               data-testid="usage-daily-sparkline">
            {data.daily.map((d) => {
              const h = Math.max(2, ((d.cost_usd || 0) / maxDaily) * 100);
              return (
                <div key={d.date}
                     title={`${d.date}: ${fmtUSD(d.cost_usd)} • ${fmtNum(d.total_tokens)} tok`}
                     style={{
                       flex: 1,
                       height: `${h}%`,
                       minHeight: 2,
                       background: "linear-gradient(180deg, #8b5cf6, #6366f1)",
                       borderRadius: "2px 2px 0 0",
                       cursor: "pointer",
                     }} />
              );
            })}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between",
                          fontSize: 10, color: "var(--text-muted, #94a3b8)",
                          marginTop: 4 }}>
            <span>{data.daily[0]?.date}</span>
            <span>{data.daily[data.daily.length - 1]?.date}</span>
          </div>
        </div>
      )}

      <div style={{ marginTop: 16, padding: 10,
                      background: "var(--surface-2, #f8fafc)", borderRadius: 8,
                      fontSize: 11, color: "var(--text-muted, #64748b)",
                      lineHeight: 1.5 }}>
        <strong>Como é calculado:</strong> tokens (texto) usam a tabela de preços
        oficial do OpenRouter por modelo. Visão Gemini cobra por imagem (~$0,0003),
        Whisper cobra por segundo (~$0,0001) e TTS cobra por caractere (~$0,000015).
        Valores em USD aproximados; consulte a fatura do provedor para o valor exato.
      </div>
    </Card>
  );
}
