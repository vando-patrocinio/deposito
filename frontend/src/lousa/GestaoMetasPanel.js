import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Button } from "@/ui";

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
  }, [loadConfig, loadLatestReport, loadLeaderboard]);

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
          <h2 style={{ margin: 0, fontSize: 20 }}>📊 Gestão e Metas</h2>
          <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 12 }}>
            Indicadores, evolução e gamificação · Pontos: reparo 1pt · retirada 1.5pt · instalação 3pt
          </p>
        </div>
        <Button onClick={runReport} disabled={reportBusy}
                 data-testid="gestao-ia-run-btn"
                 variant="primary">
          {reportBusy
            ? "🤖 GESTAO_IA pensando..."
            : "🤖 Gerar análise com GESTAO_IA"}
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
          ⚙️ Cards visíveis no app do técnico
        </div>
        {cfg && (
          <div style={{ display: "grid",
                            gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                            gap: 10 }}>
            {[
              ["show_performance", "🏆 Desempenho diário",
                "Card azul com pontos, sucesso, ranking"],
              ["show_achievements", "🏅 Medalhas",
                "Conquistas e progresso 1/11"],
              ["show_smart_route", "🗺️ Smart Route",
                "Otimização de rota por GPS"],
              ["show_points", "🎮 Pontos / Gamificação",
                "Mostrar pontos da gamificação"],
              ["enable_geofence_alerts", "📍 Alerta de geofence",
                "Cria bolha vermelha se técnico sair da área"],
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
            <span style={{ fontSize: 26 }}>🤖</span>
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
            🏆 Top técnicos por pontos (7 dias)
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
              📈 Hoje · ranking ao vivo
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
          Ainda não há análise GESTAO_IA. Clique em "Gerar análise" acima.
        </div>
      )}
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
