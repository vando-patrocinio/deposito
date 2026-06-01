/* ChurnReasonsKpiCard — KPI dos motivos de cancelamento (OS de retirada).
 *
 * Mostra:
 *   - 4 KPI tiles topo (Total retiradas, % categorizado, Top motivo, Coverage)
 *   - Distribuição por categoria (barras horizontais coloridas + %)
 *   - Lista de detalhes recentes (cliente + categoria + observações)
 *
 * Backend: GET /api/kpis/churn-reasons?period_days=30
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";

export default function ChurnReasonsKpiCard() {
  const [periodDays, setPeriodDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  // Painel de Insights IA (Claude 4.6 lendo as observações)
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiErr, setAiErr] = useState(null);
  const [aiData, setAiData] = useState(null);

  const runAi = useCallback(async () => {
    setAiLoading(true); setAiErr(null); setAiOpen(true);
    try {
      const r = await api._client
        .post(`/kpis/churn-reasons/ai-insights?period_days=${periodDays}`)
        .then((x) => x.data);
      setAiData(r);
    } catch (e) {
      setAiErr(e?.response?.data?.detail || e.message);
    } finally { setAiLoading(false); }
  }, [periodDays]);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await api._client
        .get("/kpis/churn-reasons", { params: { period_days: periodDays } })
        .then((x) => x.data);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, [periodDays]);

  useEffect(() => { load(); }, [load]);

  const maxCount = useMemo(
    () => Math.max(1, ...(data?.categories || []).map((c) => c.count)),
    [data],
  );

  return (
    <div data-testid="churn-reasons-kpi-card" style={{
      background: "white", border: "1px solid #e5e7eb", borderRadius: 14,
      padding: 20, marginBottom: 16,
      boxShadow: "0 1px 2px rgba(15,23,42,.04)",
    }}>
      <div style={{ display: "flex", alignItems: "center",
                       justifyContent: "space-between", marginBottom: 14 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                          color: "#0f172a", letterSpacing: -0.2 }}>
            📊 KPI · Motivos de Cancelamento
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b" }}>
            Análise das OS de retirada finalizadas — base para estratégia
            anti-churn e retenção.
          </p>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button
            data-testid="churn-ai-analyze-btn"
            onClick={runAi}
            disabled={aiLoading}
            style={{
              padding: "5px 12px", borderRadius: 6,
              border: 0,
              background: "linear-gradient(135deg,#7c3aed,#5b21b6)",
              color: "white", fontSize: 11, fontWeight: 800,
              cursor: aiLoading ? "wait" : "pointer",
              opacity: aiLoading ? 0.6 : 1,
              boxShadow: "0 1px 2px rgba(91,33,182,.3)",
              display: "inline-flex", alignItems: "center", gap: 4,
            }}>
            🤖 {aiLoading ? "Analisando…" : "Análise IA"}
          </button>
          {[7, 30, 90, 180].map((d) => (
            <button
              key={d}
              data-testid={`churn-period-${d}`}
              onClick={() => setPeriodDays(d)}
              style={{
                padding: "5px 10px", borderRadius: 6,
                border: "1px solid " + (periodDays === d ? "#0f172a" : "#cbd5e1"),
                background: periodDays === d ? "#0f172a" : "white",
                color: periodDays === d ? "white" : "#475569",
                fontSize: 11, fontWeight: 700, cursor: "pointer",
              }}>{d}d</button>
          ))}
        </div>
      </div>

      {loading && (
        <div style={{ padding: 30, color: "#94a3b8", fontSize: 13,
                          textAlign: "center" }}>Carregando KPI…</div>
      )}
      {err && (
        <div style={{ padding: 12, background: "#fee2e2", borderRadius: 8,
                          color: "#991b1b", fontSize: 12 }}>Erro: {err}</div>
      )}

      {!loading && !err && data && (
        <>
          {/* KPI tiles */}
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))",
            gap: 10, marginBottom: 18,
          }}>
            <KpiTile testid="churn-tile-total"
                       label="Retiradas" value={data.total_retiradas}
                       hint="No período" color="#0f172a" />
            <KpiTile testid="churn-tile-coverage"
                       label="Categorizado"
                       value={`${data.coverage_pct.toFixed(0)}%`}
                       hint={`${data.total_categorized} / ${data.total_retiradas}`}
                       color="#0d9488" />
            <KpiTile testid="churn-tile-top"
                       label="Top motivo"
                       value={data.top_category
                                ? `${data.top_category.icon} ${data.top_category.pct}%`
                                : "—"}
                       hint={data.top_category?.label || "Sem dados"}
                       color={data.top_category?.color || "#94a3b8"} />
            <KpiTile testid="churn-tile-period"
                       label="Período"
                       value={`${data.period_days}d`}
                       hint="Janela de análise" color="#475569" />
          </div>

          {/* Barras por categoria */}
          <div data-testid="churn-categories-bars">
            <div style={{
              fontSize: 11, fontWeight: 700, color: "#475569",
              textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8,
            }}>
              Distribuição por categoria
            </div>
            {data.categories.length === 0 && (
              <div style={{ padding: 16, color: "#94a3b8", fontSize: 12 }}>
                Sem motivos registrados no período.
              </div>
            )}
            {data.categories.map((c) => (
              <div key={c.key}
                     data-testid={`churn-cat-row-${c.key}`}
                     style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between",
                                  alignItems: "center", marginBottom: 4 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#334155" }}>
                    {c.icon} {c.label}
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: c.color }}>
                    {c.count} · {c.pct}%
                  </div>
                </div>
                <div style={{ height: 8, background: "#f1f5f9",
                                  borderRadius: 999, overflow: "hidden" }}>
                  <div style={{
                    height: "100%", width: `${(c.count / maxCount) * 100}%`,
                    background: c.color, transition: "width 400ms ease-out",
                  }} />
                </div>
              </div>
            ))}
          </div>

          {/* Detalhes recentes */}
          {data.recent_details.length > 0 && (
            <div style={{ marginTop: 16, paddingTop: 14,
                              borderTop: "1px solid #e5e7eb" }}>
              <div style={{
                fontSize: 11, fontWeight: 700, color: "#475569",
                textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8,
              }}>
                Últimas {data.recent_details.length} retiradas categorizadas
              </div>
              <div style={{
                display: "flex", flexDirection: "column", gap: 6,
                maxHeight: 260, overflowY: "auto", paddingRight: 4,
              }}>
                {data.recent_details.map((row) => (
                  <div key={row.ticket_id}
                          data-testid={`churn-detail-${row.ticket_id}`}
                          style={{
                            padding: "8px 10px", borderRadius: 8,
                            background: "#f8fafc", border: "1px solid #e2e8f0",
                            fontSize: 12,
                          }}>
                    <div style={{ display: "flex",
                                       justifyContent: "space-between" }}>
                      <span style={{ fontWeight: 700, color: "#0f172a" }}>
                        {row.client_name}
                      </span>
                      <span style={{
                        fontSize: 10, fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: 0.5,
                        color: "#475569",
                      }}>{row.category_label}</span>
                    </div>
                    {row.observacoes && (
                      <div style={{ color: "#475569", marginTop: 2,
                                        lineHeight: 1.4 }}>
                        “{row.observacoes.length > 200
                            ? row.observacoes.slice(0, 200) + "…"
                            : row.observacoes}”
                      </div>
                    )}
                    {(row.closed_at || row.technician) && (
                      <div style={{ marginTop: 4, fontSize: 10,
                                        color: "#94a3b8" }}>
                        {row.closed_at && new Date(row.closed_at)
                                              .toLocaleDateString("pt-BR")}
                        {row.technician && ` · ${row.technician}`}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {/* Painel IA · Claude 4.6 — insights acionáveis */}
          {aiOpen && (
            <div data-testid="churn-ai-panel"
                  style={{
                    marginTop: 18, padding: 16, borderRadius: 12,
                    background: "linear-gradient(135deg,#faf5ff 0%,#f3e8ff 100%)",
                    border: "1px solid #d8b4fe",
                  }}>
              <div style={{ display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center", marginBottom: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 18 }}>🤖</span>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 800,
                                      color: "#5b21b6" }}>
                      NEO · Análise de Retenção
                    </div>
                    <div style={{ fontSize: 10, color: "#7c3aed" }}>
                      Claude 4.6 lendo as observações livres dos técnicos
                    </div>
                  </div>
                </div>
                <button data-testid="churn-ai-close"
                          onClick={() => setAiOpen(false)}
                          style={{
                            background: "transparent", border: 0,
                            color: "#5b21b6", fontSize: 16, cursor: "pointer",
                          }}>×</button>
              </div>

              {aiLoading && (
                <div data-testid="churn-ai-loading"
                      style={{ padding: 20, color: "#7c3aed",
                                  fontSize: 13, textAlign: "center" }}>
                  🧠 Analisando observações com Claude 4.6… (10-30s)
                </div>
              )}

              {aiErr && (
                <div data-testid="churn-ai-error"
                      style={{ padding: 10, background: "#fee2e2",
                                  borderRadius: 6, color: "#991b1b",
                                  fontSize: 12 }}>
                  ⚠ {aiErr}
                </div>
              )}

              {!aiLoading && !aiErr && aiData && (
                <>
                  {aiData.executive_summary && (
                    <div data-testid="churn-ai-summary"
                          style={{
                            padding: 12, background: "white", borderRadius: 8,
                            fontSize: 13, lineHeight: 1.55, color: "#1e293b",
                            border: "1px solid #e9d5ff", marginBottom: 10,
                          }}>
                      <div style={{ fontSize: 10, fontWeight: 700,
                                        color: "#7c3aed",
                                        textTransform: "uppercase",
                                        letterSpacing: 0.5, marginBottom: 4 }}>
                        Resumo Executivo · {aiData.sample_size} obs analisadas
                      </div>
                      {aiData.executive_summary}
                    </div>
                  )}

                  {aiData.top_risk && (
                    <div data-testid="churn-ai-toprisk"
                          style={{
                            padding: "8px 12px", background: "#fef2f2",
                            border: "1px solid #fca5a5", borderRadius: 8,
                            fontSize: 12, color: "#991b1b", marginBottom: 12,
                            fontWeight: 600,
                          }}>
                      🚨 Alerta: {aiData.top_risk}
                    </div>
                  )}

                  <div style={{ fontSize: 11, fontWeight: 700, color: "#5b21b6",
                                    textTransform: "uppercase",
                                    letterSpacing: 0.5, marginBottom: 8 }}>
                    Temas identificados ({aiData.themes.length})
                  </div>

                  <div style={{ display: "flex", flexDirection: "column",
                                    gap: 8 }}>
                    {aiData.themes.map((t, idx) => (
                      <div key={idx}
                              data-testid={`churn-ai-theme-${idx}`}
                              style={{
                                padding: 12, background: "white",
                                borderRadius: 8, border: "1px solid #e9d5ff",
                              }}>
                        <div style={{ display: "flex",
                                          justifyContent: "space-between",
                                          marginBottom: 6 }}>
                          <div style={{ fontSize: 14, fontWeight: 800,
                                            color: "#0f172a" }}>
                            {t.title}
                          </div>
                          <div style={{
                            padding: "2px 8px", borderRadius: 999,
                            background: "#f3e8ff", color: "#7c3aed",
                            fontSize: 10, fontWeight: 800,
                          }}>
                            {t.count} casos
                          </div>
                        </div>
                        {t.evidence_quotes.length > 0 && (
                          <div style={{ marginBottom: 8 }}>
                            {t.evidence_quotes.slice(0, 3).map((q, i) => (
                              <div key={i} style={{
                                fontSize: 11, color: "#475569",
                                fontStyle: "italic", lineHeight: 1.5,
                                paddingLeft: 8,
                                borderLeft: "2px solid #d8b4fe",
                                marginBottom: 2,
                              }}>“{q}”</div>
                            ))}
                          </div>
                        )}
                        <div style={{
                          padding: "8px 10px", background: "#ecfdf5",
                          borderRadius: 6, fontSize: 12, color: "#065f46",
                          fontWeight: 600, lineHeight: 1.4,
                        }}>
                          💡 {t.recommended_action}
                        </div>
                        {t.potential_savings_clients_per_month > 0 && (
                          <div style={{ marginTop: 6, fontSize: 11,
                                            fontWeight: 700,
                                            color: "#0d9488" }}>
                            💰 Retenção potencial:{" "}
                            {t.potential_savings_clients_per_month} cliente
                            {t.potential_savings_clients_per_month !== 1 ? "s" : ""}/mês
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 10, color: "#7c3aed",
                                    marginTop: 10, textAlign: "right" }}>
                    Gerado em {new Date(aiData.generated_at)
                                .toLocaleString("pt-BR")} · cache 30min
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function KpiTile({ label, value, hint, color, testid }) {
  return (
    <div data-testid={testid} style={{
      padding: "12px 10px", borderRadius: 10, background: "#f8fafc",
      border: "1px solid #e2e8f0",
    }}>
      <div style={{
        fontSize: 9, fontWeight: 700, color: "#94a3b8",
        textTransform: "uppercase", letterSpacing: 0.5,
      }}>{label}</div>
      <div style={{
        fontSize: 22, fontWeight: 800, color, marginTop: 2,
        lineHeight: 1.1,
      }}>{value}</div>
      <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>{hint}</div>
    </div>
  );
}
