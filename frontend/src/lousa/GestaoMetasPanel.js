import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Button } from "@/ui";
import RetentionPlaybookCard from "./RetentionPlaybookCard";

/**
 * GestaoMetasPanel — aba executiva com KPIs, GESTAO_IA e toggles dos cards.
 * Tudo que era "Desempenho" e "Medalhas" do app do colaborador centraliza
 * aqui, com possibilidade do admin ativar/desativar a exibição no app.
 */
export default function GestaoMetasPanel() {
  const [report, setReport] = useState(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [cfg, setCfg] = useState(null);
  const [cfgBusy, setCfgBusy] = useState(false);
  const [err, setErr] = useState("");
  const [leaderboard, setLeaderboard] = useState(null);
  const [marketInput, setMarketInput] = useState("");
  const [swot, setSwot] = useState(null);
  const [swotBusy, setSwotBusy] = useState(false);
  const [swotErr, setSwotErr] = useState("");

  const loadConfig = useCallback(async () => {
    try {
      const r = await api._client
        .get("/lousa/admin/dashboard-config")
        .then((x) => x.data);
      setCfg(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, []);

  const loadLatestReport = useCallback(async () => {
    try {
      const r = await api._client
        .get("/gestao-ia/latest")
        .then((x) => x.data);
      setReport(r);
    } catch { /* sem report ainda */ }
  }, []);

  const loadLatestSwot = useCallback(async () => {
    try {
      const r = await api._client
        .get("/gestao-ia/competitive-analysis/latest")
        .then((x) => x.data);
      setSwot(r);
      if (r?.market_input) setMarketInput(r.market_input);
    } catch { /* sem swot ainda */ }
  }, []);

  const loadLeaderboard = useCallback(async () => {
    try {
      const r = await api._client
        .get("/lousa/public/leaderboard?company_id=co-demo&limit=20")
        .then((x) => x.data);
      setLeaderboard(r);
    } catch (e) {
      console.warn(e);
    }
  }, []);

  useEffect(() => {
    loadConfig();
    loadLatestReport();
    loadLeaderboard();
    loadLatestSwot();
  }, [loadConfig, loadLatestReport, loadLeaderboard, loadLatestSwot]);

  async function runReport() {
    setReportBusy(true);
    setErr("");
    try {
      const r = await api._client
        .post("/gestao-ia/generate", {})
        .then((x) => x.data);
      setReport(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao gerar");
    } finally {
      setReportBusy(false);
    }
  }

  async function runSwot() {
    if (!marketInput || marketInput.trim().length < 20) {
      setSwotErr("Forneça ao menos 20 caracteres de contexto de mercado.");
      return;
    }
    setSwotBusy(true);
    setSwotErr("");
    try {
      const r = await api._client
        .post("/gestao-ia/competitive-analysis",
              { market_input: marketInput })
        .then((x) => x.data);
      setSwot(r);
    } catch (e) {
      setSwotErr(e?.response?.data?.detail || e.message
                  || "Falha ao gerar análise");
    } finally {
      setSwotBusy(false);
    }
  }

  async function toggle(key, value) {
    setCfgBusy(true);
    try {
      const r = await api._client
        .post("/lousa/admin/dashboard-config", { [key]: value })
        .then((x) => x.data);
      setCfg(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setCfgBusy(false);
    }
  }

  return (
    <div data-testid="gestao-metas-panel">
      {/* HEADER */}
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", gap: 12,
                      marginBottom: 18, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20 }}>Gestão e Metas</h2>
          <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 12 }}>
            Indicadores, evolução e gamificação · Pontos: reparo 1pt · retirada 1.5pt · instalação 3pt
          </p>
        </div>
        <Button onClick={runReport} disabled={reportBusy}
                 data-testid="gestao-ia-run-btn"
                 variant="primary">
          {reportBusy
            ? "GESTAO_IA pensando..."
            : "Gerar análise com GESTAO_IA"}
        </Button>
      </div>

      {err && (
        <div style={{ padding: 12, background: "#fee2e2", color: "#7f1d1d",
                        borderRadius: 10, marginBottom: 14, fontSize: 13 }}>
          {err}
        </div>
      )}

      {/* CONFIG TOGGLES — ativar/desativar cards no app do técnico */}
      <section data-testid="dashboard-toggles" style={{
        background: "white", padding: "14px 16px", borderRadius: 14,
        border: "1px solid #e2e8f0", marginBottom: 18,
      }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1,
                        color: "#64748b", textTransform: "uppercase",
                        marginBottom: 10 }}>
          ️ Cards visíveis no app do técnico
        </div>
        {cfg && (
          <div style={{ display: "grid",
                            gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                            gap: 10 }}>
            {[
              ["show_performance", "Desempenho diário",
                "Card azul com pontos, sucesso, ranking"],
              ["show_achievements", "Medalhas",
                "Conquistas e progresso 1/11"],
              ["show_smart_route", "️ Smart Route",
                "Otimização de rota por GPS"],
              ["show_points", "Pontos / Gamificação",
                "Mostrar pontos da gamificação"],
              ["enable_geofence_alerts", "Alerta de geofence",
                "Cria bolha vermelha se técnico sair da área"],
              ["show_meu_dia_em_campo", "Meu dia em campo",
                "Card com métricas do dia + GPS + atalhos Isabella/Estoque/Frota (default desligado)"],
            ].map(([key, label, hint]) => (
              <ToggleCard key={key} testid={`toggle-${key}`}
                            label={label} hint={hint}
                            value={cfg[key] ?? true} disabled={cfgBusy}
                            onChange={(v) => toggle(key, v)} />
            ))}
          </div>
        )}
      </section>

      {/* AI REPORT */}
      {report?.ai_analysis && (
        <section data-testid="gestao-ai-report" style={{
          marginBottom: 18, padding: 18, borderRadius: 16,
          background: "linear-gradient(135deg,#0c4a6e,#075985)",
          color: "white",
        }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center",
                          marginBottom: 12 }}>
            <span style={{ fontSize: 26 }}></span>
            <div>
              <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1,
                              color: "#67e8f9", textTransform: "uppercase" }}>
                GESTAO_IA · Claude Sonnet 4.5
              </div>
              <div style={{ fontSize: 11, color: "#cbd5e1", marginTop: 2 }}>
                Gerado em {new Date(report.generated_at).toLocaleString("pt-BR")}
              </div>
            </div>
            <span style={{
              marginLeft: "auto", padding: "4px 10px", borderRadius: 999,
              background: "rgba(255,255,255,0.15)", fontSize: 11,
              fontWeight: 700,
            }}>Tendência: {report.ai_analysis.tendencia}</span>
          </div>
          <p style={{ fontSize: 14, lineHeight: 1.5, margin: 0,
                        color: "#f1f5f9" }}>
            {report.ai_analysis.resumo_executivo}
          </p>

          {/* KPIs */}
          {report.ai_analysis.kpis?.length > 0 && (
            <div style={{ marginTop: 14, display: "grid",
                            gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))",
                            gap: 10 }}>
              {report.ai_analysis.kpis.map((k, i) => (
                <div key={i} style={{
                  padding: "10px 12px", borderRadius: 10,
                  background: "rgba(255,255,255,0.08)",
                  border: "1px solid rgba(255,255,255,0.10)",
                }}>
                  <div style={{ fontSize: 10, color: "#94a3b8",
                                  textTransform: "uppercase", fontWeight: 700 }}>
                    {k.nome}
                  </div>
                  <div style={{ display: "flex", alignItems: "baseline",
                                  gap: 6, marginTop: 4 }}>
                    <span style={{ fontSize: 20, fontWeight: 800 }}>
                      {k.valor_atual}
                    </span>
                    <span style={{ fontSize: 16 }}>{k.status}</span>
                  </div>
                  <div style={{ fontSize: 10, color: "#cbd5e1", marginTop: 4 }}>
                    Meta: {k.meta}
                  </div>
                  <div style={{ fontSize: 10, color: "#e2e8f0", marginTop: 4,
                                  lineHeight: 1.4 }}>
                    {k.comentario}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Ações */}
          {report.ai_analysis.acoes_recomendadas?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#67e8f9",
                              textTransform: "uppercase", letterSpacing: 1,
                              marginBottom: 8 }}>
                Ações recomendadas
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12,
                              lineHeight: 1.55, color: "#f1f5f9" }}>
                {report.ai_analysis.acoes_recomendadas.map((a, i) => (
                  <li key={i}>
                    <strong>[{a.prioridade?.toUpperCase()}]</strong>{" "}
                    {a.acao}{" "}
                    <span style={{ color: "#94a3b8" }}>
                      ({a.responsavel})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Coaching */}
          {report.ai_analysis.coaching?.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "#67e8f9",
                              textTransform: "uppercase", letterSpacing: 1,
                              marginBottom: 8 }}>
                Coaching sugerido
              </div>
              {report.ai_analysis.coaching.map((c, i) => (
                <div key={i} style={{
                  padding: 10, marginBottom: 6, borderRadius: 8,
                  background: "rgba(255,255,255,0.06)",
                  fontSize: 12, color: "#e2e8f0",
                }}>
                  <strong>{c.tecnico}</strong> · {c.motivo} →{" "}
                  <em style={{ color: "#f1f5f9" }}>{c.sugestao}</em>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* TOP TÉCNICOS */}
      {report?.top_techs && report.top_techs.length > 0 && (
        <section data-testid="top-techs-section" style={{
          background: "white", padding: 16, borderRadius: 14,
          border: "1px solid #e2e8f0", marginBottom: 18,
        }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                          letterSpacing: 1, textTransform: "uppercase",
                          marginBottom: 12 }}>
            Top técnicos por pontos (7 dias)
          </div>
          <table style={{ width: "100%", fontSize: 12 }}>
            <thead>
              <tr style={{ color: "#94a3b8", textAlign: "left",
                              borderBottom: "1px solid #e2e8f0" }}>
                <th style={{ padding: 6 }}>#</th>
                <th style={{ padding: 6 }}>Técnico</th>
                <th style={{ padding: 6 }}>Pontos</th>
                <th style={{ padding: 6 }}>Fechadas</th>
                <th style={{ padding: 6 }}>Instal.</th>
                <th style={{ padding: 6 }}>Retir.</th>
                <th style={{ padding: 6 }}>Rep.</th>
                <th style={{ padding: 6 }}>% suc.</th>
              </tr>
            </thead>
            <tbody>
              {report.top_techs.map((t, i) => (
                <tr key={t.collaborator_id} style={{
                  borderBottom: "1px solid #f1f5f9",
                  background: i === 0 ? "#fff7ed" : "transparent",
                }}>
                  <td style={{ padding: 6, fontWeight: 800 }}>{i + 1}º</td>
                  <td style={{ padding: 6, fontWeight: 700 }}>{t.name}</td>
                  <td style={{ padding: 6 }}>{t.points}</td>
                  <td style={{ padding: 6 }}>{t.closed}</td>
                  <td style={{ padding: 6 }}>{t.instalacoes}</td>
                  <td style={{ padding: 6 }}>{t.retiradas}</td>
                  <td style={{ padding: 6 }}>{t.reparos}</td>
                  <td style={{ padding: 6 }}>{t.success_rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* Comparativo: ranking de hoje (leaderboard live) */}
      {leaderboard?.leaderboard?.length > 0 && (
        <section style={{
          background: "white", padding: 16, borderRadius: 14,
          border: "1px solid #e2e8f0", marginBottom: 18,
        }} data-testid="leaderboard-today">
          <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginBottom: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                            letterSpacing: 1, textTransform: "uppercase" }}>
              Hoje · ranking ao vivo
            </div>
            <a href="/mural" target="_blank" rel="noreferrer"
               style={{ fontSize: 11, color: "#0ea5e9",
                          textDecoration: "underline" }}>
              Abrir mural (TV) ↗
            </a>
          </div>
          <div style={{ fontSize: 12, color: "#475569" }}>
            {leaderboard.leaderboard.slice(0, 5).map((t) => (
              <div key={t.collaborator_id} style={{
                padding: "6px 8px", borderRadius: 8,
                display: "flex", justifyContent: "space-between",
                background: "#f8fafc", marginBottom: 4,
              }}>
                <span><strong>{t.rank}º</strong> {t.name}</span>
                <span>{t.closed_today} fechadas · {t.success_rate}%</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {!report && (
        <div style={{ padding: 28, textAlign: "center", color: "#94a3b8",
                        background: "#f8fafc", borderRadius: 12 }}>
          Ainda não há análise GESTAO_IA. Clique em “Gerar análise” acima.
        </div>
      )}

      {/* MODO CONCORRENTE */}
      <RetentionPlaybookCard />
      <section data-testid="competitive-section" style={{
        marginTop: 18, padding: 18, borderRadius: 16,
        background: "linear-gradient(135deg,#1e1b4b 0%,#312e81 100%)",
        color: "white",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
                        marginBottom: 12 }}>
          <span style={{ fontSize: 24 }}>️</span>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1,
                            color: "#c4b5fd", textTransform: "uppercase" }}>
              GESTAO_IA · Modo Concorrente
            </div>
            <div style={{ fontSize: 13, color: "#e0e7ff" }}>
              Cole dados do mercado e gere uma análise SWOT competitiva
            </div>
          </div>
        </div>
        <textarea data-testid="competitive-input"
                    value={marketInput}
                    onChange={(e) => setMarketInput(e.target.value)}
                    rows={5}
                    placeholder="Ex: Sumicity entrou no Centro com 500MB a R$79. Vivo Fibra expandindo em Vista Alegre. Cliente João reclamou e citou concorrente. Algumas reclamações sobre suporte demorado da TIM…"
                    style={{
                      width: "100%", padding: 10, borderRadius: 10,
                      border: "1px solid rgba(255,255,255,0.18)",
                      background: "rgba(15,23,42,0.6)", color: "white",
                      fontSize: 12, fontFamily: "inherit", resize: "vertical",
                    }} />
        <div style={{ display: "flex", gap: 10, alignItems: "center",
                        marginTop: 10, flexWrap: "wrap" }}>
          <Button onClick={runSwot} disabled={swotBusy}
                   data-testid="competitive-run-btn"
                   style={{ background: "#a78bfa", color: "#1c1917",
                              fontWeight: 800 }}>
            {swotBusy
              ? "️ Analisando concorrência..."
              : "️ Gerar SWOT competitivo"}
          </Button>
          {swot?.generated_at && (
            <span style={{ fontSize: 11, color: "#c4b5fd" }}>
              Última: {new Date(swot.generated_at).toLocaleString("pt-BR")}
            </span>
          )}
        </div>
        {swotErr && (
          <div data-testid="competitive-error" style={{
            marginTop: 10, padding: 10, background: "rgba(220,38,38,0.2)",
            borderRadius: 8, fontSize: 12, color: "#fecaca",
          }}>{swotErr}</div>
        )}

        {swot?.swot_analysis && (
          <div data-testid="competitive-result" style={{ marginTop: 14 }}>
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5,
                          color: "#f5f3ff" }}>
              {swot.swot_analysis.resumo_estrategico}
            </p>

            {/* SWOT 4 quadrantes */}
            <div style={{ marginTop: 14, display: "grid",
                            gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))",
                            gap: 10 }}>
              {[
                ["forcas", "FORÇAS", "#10b981"],
                ["fraquezas", "️ FRAQUEZAS", "#f59e0b"],
                ["oportunidades", "OPORTUNIDADES", "#06b6d4"],
                ["ameacas", "AMEAÇAS", "#ef4444"],
              ].map(([key, label, color]) => (
                <div key={key} style={{
                  padding: 12, borderRadius: 10,
                  background: "rgba(255,255,255,0.06)",
                  border: `1px solid ${color}55`,
                }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color,
                                  textTransform: "uppercase",
                                  letterSpacing: 1, marginBottom: 8 }}>
                    {label}
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11,
                                  color: "#e2e8f0", lineHeight: 1.5 }}>
                    {(swot.swot_analysis.swot?.[key] || []).map((it, i) => (
                      <li key={i}>{it}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            {/* Concorrentes identificados */}
            {swot.swot_analysis.concorrentes_identificados?.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 800, color: "#c4b5fd",
                                textTransform: "uppercase", marginBottom: 8 }}>
                  Concorrentes identificados
                </div>
                <div style={{ display: "grid",
                                gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))",
                                gap: 8 }}>
                  {swot.swot_analysis.concorrentes_identificados.map((c, i) => (
                    <div key={i} style={{
                      padding: 10, borderRadius: 8,
                      background: "rgba(255,255,255,0.06)",
                      fontSize: 11, lineHeight: 1.5,
                    }}>
                      <strong style={{ color: "#fbbf24" }}>{c.nome}</strong>
                      <span style={{
                        marginLeft: 6, padding: "1px 6px", borderRadius: 4,
                        background: c.ameaca_para_nos === "alta" ? "#dc2626"
                          : c.ameaca_para_nos === "media" ? "#f59e0b"
                          : "#10b981",
                        color: "white", fontSize: 9, fontWeight: 700,
                      }}>{(c.ameaca_para_nos || "").toUpperCase()}</span>
                      <div style={{ marginTop: 4, color: "#e0e7ff" }}>
                        ✅ {c.ponto_forte}
                      </div>
                      <div style={{ color: "#cbd5e1" }}>
                        ❌ {c.ponto_fraco}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Bairros a priorizar */}
            {swot.swot_analysis.bairros_a_priorizar?.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 800, color: "#c4b5fd",
                                textTransform: "uppercase", marginBottom: 6 }}>
                  Bairros a priorizar
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12,
                                color: "#e0e7ff" }}>
                  {swot.swot_analysis.bairros_a_priorizar.map((b, i) => (
                    <li key={i}>
                      <strong>{b.bairro}</strong> ({b.tipo_acao}) — {b.razao}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Ações */}
            {swot.swot_analysis.acoes_curto_prazo?.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 800, color: "#c4b5fd",
                                textTransform: "uppercase", marginBottom: 6 }}>
                  Ações curto prazo (≤30d)
                </div>
                {swot.swot_analysis.acoes_curto_prazo.map((a, i) => (
                  <div key={i} style={{
                    padding: "6px 10px", marginBottom: 4, borderRadius: 6,
                    background: "rgba(255,255,255,0.06)",
                    fontSize: 11, color: "#e2e8f0",
                  }}>
                    <strong>[{a.esforco?.toUpperCase()}]</strong> {a.acao}
                    <span style={{ color: "#94a3b8" }}>
                      {" "}— {a.responsavel} · {a.impacto_esperado}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Veredicto */}
            {swot.swot_analysis.verediito_final && (
              <div style={{
                marginTop: 14, padding: 12, borderRadius: 10,
                background: "linear-gradient(135deg,#fbbf24,#f59e0b)",
                color: "#1c1917", fontWeight: 700, fontSize: 13,
              }}>
                {swot.swot_analysis.verediito_final}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function ToggleCard({ label, hint, value, onChange, testid, disabled }) {
  return (
    <label data-testid={testid} style={{
      display: "flex", gap: 10, padding: "10px 12px",
      background: value ? "#ecfdf5" : "#f8fafc",
      borderRadius: 10,
      border: "1px solid " + (value ? "#10b981" : "#e2e8f0"),
      cursor: disabled ? "wait" : "pointer",
      transition: "background 200ms",
    }}>
      <input type="checkbox" checked={value} disabled={disabled}
              onChange={(e) => onChange(e.target.checked)}
              style={{ width: 18, height: 18, marginTop: 2 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 700,
                        color: value ? "#065f46" : "#0f172a" }}>{label}</div>
        <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
          {hint}
        </div>
      </div>
    </label>
  );
}
