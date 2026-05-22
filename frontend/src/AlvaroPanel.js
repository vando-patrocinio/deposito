/* ALVARO IA — Painel de análise estratégica de conversas WhatsApp.
   Mostra:
   - Stats consolidadas das últimas 24h
   - Top bairros/ruas reclamações, bairros não/mal atendidos
   - Clientes em risco crítico (drill-down)
   - Recomendações por setor
   - Botão "Rodar análise agora"
*/
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import {
  Brain, Play, Loader2, AlertTriangle, TrendingDown, MapPin,
  Activity, Lightbulb, History, RefreshCw, X,
} from "lucide-react";

const RISK_COLORS = {
  baixo: "#16a34a",
  medio: "#f59e0b",
  alto: "#ea580c",
  critico: "#dc2626",
};

export default function AlvaroPanel() {
  const [report, setReport] = useState(null);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState([]);
  const [drilldown, setDrilldown] = useState(null); // {risco} for filter

  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api._client.get("/alvaro/reports/latest").then((x) => x.data);
      if (r?.report) {
        setReport(r.report);
        setMeta({
          run_id: r.run_id,
          finished_at: r.finished_at,
          phones_processed: r.phones_processed,
          analyses_ok: r.analyses_ok,
          analyses_failed: r.analyses_failed,
          period_hours: r.period_hours,
        });
      } else {
        setReport(null);
        setMeta(null);
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  async function runNow() {
    setRunning(true);
    setError("");
    try {
      await api._client.post("/alvaro/run-daily?hours_back=24&sync=false");
      // Mostra mensagem amigável; polling re-buscar o relatório a cada 30s
      const poll = setInterval(async () => {
        const r = await api._client.get("/alvaro/reports/latest").then((x) => x.data).catch(() => null);
        if (r?.report && r?.finished_at !== meta?.finished_at) {
          clearInterval(poll);
          setRunning(false);
          await reload();
        }
      }, 15000);
      // Stop polling after 10 minutes max
      setTimeout(() => { clearInterval(poll); setRunning(false); }, 10 * 60 * 1000);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
      setRunning(false);
    }
  }

  async function openHistory() {
    setHistoryOpen(true);
    const r = await api._client.get("/alvaro/reports?limit=20").then((x) => x.data);
    setHistory(r.items || []);
  }

  if (loading) {
    return (
      <div style={{ padding: 60, textAlign: "center" }}>
        <Loader2 size={28} style={{ animation: "spin 1s linear infinite", color: "#64748b" }} />
        <p style={{ color: "#64748b", marginTop: 12 }}>Carregando análise...</p>
      </div>
    );
  }

  if (!report) {
    return (
      <div style={{ maxWidth: 720, margin: "60px auto", padding: 40,
                     background: "white", borderRadius: 16,
                     border: "1px solid #e2e8f0", textAlign: "center" }}
           data-testid="alvaro-empty-state">
        <Brain size={48} style={{ color: "#7c3aed", marginBottom: 16 }} />
        <h2 style={{ fontSize: 24, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>
          ALVARO IA
        </h2>
        <p style={{ color: "#475569", fontSize: 14, lineHeight: 1.6, marginBottom: 24 }}>
          Análise estratégica das conversas WhatsApp das últimas 24h.
          Detecta risco de cancelamento, oportunidades comerciais, problemas
          geográficos recorrentes e gera recomendações por setor.
        </p>
        <button onClick={runNow} disabled={running}
                data-testid="alvaro-run-btn"
                style={btnPrimary}>
          {running ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />
                    : <Play size={16} />}
          {running ? "Analisando conversas..." : "Rodar primeira análise"}
        </button>
        {running && (
          <p style={{ marginTop: 16, fontSize: 12, color: "#64748b" }}>
            Isso pode levar de 1 a 5 minutos dependendo do volume.
            Acompanhe o status via "Atualizar" abaixo.
          </p>
        )}
        {error && (
          <div style={{ marginTop: 16, padding: 12, borderRadius: 8,
                         background: "#fee2e2", color: "#991b1b", fontSize: 12 }}>
            {error}
          </div>
        )}
      </div>
    );
  }

  const riskTotal = report.total_risco_cancelamento || {};
  const totalConv = report.total_conversas || 0;

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: "0 auto" }}
         data-testid="alvaro-panel">
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                     marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Brain size={28} style={{ color: "#7c3aed" }} />
            <h1 style={{ fontSize: 24, fontWeight: 700, color: "#0f172a", margin: 0 }}>
              ALVARO IA
            </h1>
            <span style={{
              padding: "3px 10px", borderRadius: 999,
              background: "rgba(124,58,237,0.1)", color: "#7c3aed",
              fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
            }}>DEEPSEEK V3.1</span>
          </div>
          <p style={{ color: "#64748b", fontSize: 13, marginTop: 6, margin: 0 }}>
            Período: <strong>{report.periodo_analisado}</strong>
            {meta?.finished_at && (
              <> · Última análise: {new Date(meta.finished_at).toLocaleString("pt-BR")}</>
            )}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={reload} style={btnSecondary} data-testid="alvaro-refresh">
            <RefreshCw size={14} /> Atualizar
          </button>
          <button onClick={openHistory} style={btnSecondary} data-testid="alvaro-history">
            <History size={14} /> Histórico
          </button>
          <button onClick={runNow} disabled={running}
                  style={btnPrimary} data-testid="alvaro-run-now">
            {running ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
                      : <Play size={14} />}
            {running ? "Rodando..." : "Rodar agora"}
          </button>
        </div>
      </div>

      {/* Resumo executivo */}
      {report.resumo_executivo && (
        <div style={{
          padding: 20, borderRadius: 12, marginBottom: 20,
          background: "linear-gradient(135deg, rgba(124,58,237,0.08), rgba(99,102,241,0.04))",
          border: "1px solid rgba(124,58,237,0.2)",
        }} data-testid="alvaro-executive-summary">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <Lightbulb size={16} style={{ color: "#7c3aed" }} />
            <strong style={{ fontSize: 12, color: "#7c3aed",
                              letterSpacing: 1, textTransform: "uppercase" }}>
              Resumo Executivo
            </strong>
          </div>
          <p style={{ margin: 0, fontSize: 15, color: "#1e293b", lineHeight: 1.6 }}>
            {report.resumo_executivo}
          </p>
        </div>
      )}

      {/* KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                     gap: 12, marginBottom: 20 }}>
        <Kpi label="Conversas analisadas" value={totalConv} icon={<Activity size={14} />} />
        <Kpi label="Nota média" value={(report.media_geral_notas || 0).toFixed(1) + " / 10"}
              color={report.media_geral_notas >= 7 ? "#16a34a"
                    : report.media_geral_notas >= 5 ? "#f59e0b" : "#dc2626"} />
        <Kpi label="Top piores (média)" value={(report.media_piores_resultados || 0).toFixed(1)}
              color="#dc2626" icon={<TrendingDown size={14} />} />
        <Kpi label="Top melhores (média)" value={(report.media_melhores_resultados || 0).toFixed(1)}
              color="#16a34a" />
      </div>

      {/* Risk grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                     gap: 8, marginBottom: 20 }}>
        {["baixo", "medio", "alto", "critico"].map((r) => (
          <button key={r}
                  data-testid={`alvaro-risk-${r}`}
                  onClick={() => setDrilldown({ risco: r })}
                  style={{
                    padding: 14, borderRadius: 10, cursor: "pointer",
                    background: "white", textAlign: "left",
                    border: `1px solid ${RISK_COLORS[r]}33`,
                    borderLeft: `4px solid ${RISK_COLORS[r]}`,
                    transition: "transform 0.15s",
                  }}>
            <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                           letterSpacing: 1, textTransform: "uppercase" }}>
              Risco {r}
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, color: RISK_COLORS[r],
                           marginTop: 4 }}>
              {riskTotal[r] || 0}
            </div>
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
              {totalConv > 0 ? Math.round(((riskTotal[r] || 0) / totalConv) * 100) : 0}% do total
            </div>
          </button>
        ))}
      </div>

      {/* Two columns: bairros + tipos */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16, marginBottom: 20 }}>
        <Card title="Top bairros com reclamações" icon={<MapPin size={14} />}>
          {(report.top_bairros_reclamacoes || []).slice(0, 8).map((b) => (
            <Row key={b.bairro} label={b.bairro} value={b.qtd} max={report.top_bairros_reclamacoes[0]?.qtd} />
          ))}
        </Card>
        <Card title="Tipos de reclamação mais frequentes" icon={<AlertTriangle size={14} />}>
          {(report.top_tipos_reclamacao || []).slice(0, 8).map((t) => (
            <Row key={t.tipo} label={t.tipo} value={t.qtd} max={report.top_tipos_reclamacao[0]?.qtd}
                  color="#f59e0b" />
          ))}
        </Card>
      </div>

      {/* Bairros não/mal atendidos */}
      {((report.bairros_nao_atendidos?.length || 0) + (report.bairros_mal_atendidos?.length || 0)) > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16, marginBottom: 20 }}>
          <Card title={`Bairros NÃO atendidos (${report.bairros_nao_atendidos?.length || 0})`}
                titleColor="#dc2626">
            {(report.bairros_nao_atendidos || []).length === 0 ? (
              <p style={{ fontSize: 12, color: "#94a3b8" }}>Nenhum identificado.</p>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {report.bairros_nao_atendidos.map((b) => (
                  <Tag key={b} text={b} color="#dc2626" />
                ))}
              </div>
            )}
          </Card>
          <Card title={`Bairros MAL atendidos (${report.bairros_mal_atendidos?.length || 0})`}
                titleColor="#ea580c">
            {(report.bairros_mal_atendidos || []).length === 0 ? (
              <p style={{ fontSize: 12, color: "#94a3b8" }}>Nenhum identificado.</p>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {report.bairros_mal_atendidos.map((b) => (
                  <Tag key={b} text={b} color="#ea580c" />
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* Clientes risco crítico */}
      {report.clientes_risco_critico?.length > 0 && (
        <Card title={`🚨 Clientes em RISCO CRÍTICO (${report.clientes_risco_critico.length})`}
              titleColor="#dc2626"
              testId="alvaro-critical-list">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                         gap: 10, marginTop: 8 }}>
            {report.clientes_risco_critico.slice(0, 12).map((c, i) => (
              <div key={i} style={{
                padding: 10, borderRadius: 8,
                background: "#fef2f2", border: "1px solid #fecaca",
                fontSize: 12,
              }}>
                <div style={{ fontWeight: 700, color: "#7f1d1d" }}>
                  {c.nome || c.telefone || "—"}
                </div>
                <div style={{ color: "#991b1b", marginTop: 2 }}>{c.telefone}</div>
                {c.motivo && (
                  <div style={{ color: "#64748b", marginTop: 4, fontSize: 11 }}>
                    {c.motivo}
                  </div>
                )}
                {c.nota > 0 && (
                  <div style={{ marginTop: 4, fontSize: 11, color: "#dc2626", fontWeight: 700 }}>
                    Nota: {c.nota}/10
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Recomendações por setor */}
      {report.recomendacoes && Object.keys(report.recomendacoes).length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: "#0f172a",
                        textTransform: "uppercase", letterSpacing: 1, marginBottom: 12 }}>
            <Lightbulb size={14} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
            Recomendações por setor
          </h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                         gap: 12 }} data-testid="alvaro-recommendations">
            {Object.entries(report.recomendacoes).map(([setor, items]) => (
              (items?.length || 0) > 0 && (
                <Card key={setor} title={setorLabel(setor)} testId={`alvaro-rec-${setor}`}>
                  <ul style={{ margin: 0, padding: "0 0 0 16px", fontSize: 13,
                                lineHeight: 1.6, color: "#334155" }}>
                    {items.map((rec, idx) => (
                      <li key={idx} style={{ marginBottom: 4 }}>{rec}</li>
                    ))}
                  </ul>
                </Card>
              )
            ))}
          </div>
        </div>
      )}

      {/* Oportunidades */}
      {((report.oportunidades_comerciais?.length || 0)
        + (report.oportunidades_expansao?.length || 0)) > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                       gap: 16, marginTop: 20 }}>
          <Card title="💰 Oportunidades comerciais"
                titleColor="#0e7490">
            {(report.oportunidades_comerciais || []).length === 0 ? (
              <p style={{ fontSize: 12, color: "#94a3b8" }}>Nenhuma detectada.</p>
            ) : (
              <ul style={{ margin: 0, padding: "0 0 0 16px", fontSize: 13,
                            lineHeight: 1.6, color: "#0e7490" }}>
                {report.oportunidades_comerciais.map((o, i) => (
                  <li key={i}>{o}</li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="🗺️ Oportunidades de expansão" titleColor="#7c3aed">
            {(report.oportunidades_expansao || []).length === 0 ? (
              <p style={{ fontSize: 12, color: "#94a3b8" }}>Nenhuma detectada.</p>
            ) : (
              <ul style={{ margin: 0, padding: "0 0 0 16px", fontSize: 13,
                            lineHeight: 1.6, color: "#7c3aed" }}>
                {report.oportunidades_expansao.map((o, i) => (
                  <li key={i}>{o}</li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}

      {drilldown && (
        <DrilldownModal risco={drilldown.risco} onClose={() => setDrilldown(null)} />
      )}
      {historyOpen && (
        <HistoryModal items={history} onClose={() => setHistoryOpen(false)} />
      )}
    </div>
  );
}

function Kpi({ label, value, color, icon }) {
  return (
    <div style={{ padding: 14, background: "white", borderRadius: 10,
                   border: "1px solid #e2e8f0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                     fontSize: 10, color: "#64748b", fontWeight: 700,
                     letterSpacing: 1, textTransform: "uppercase" }}>
        {icon} {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: color || "#0f172a",
                     marginTop: 6 }}>
        {value}
      </div>
    </div>
  );
}

function Card({ title, children, icon, titleColor, testId }) {
  return (
    <div style={{ padding: 16, background: "white", borderRadius: 10,
                   border: "1px solid #e2e8f0" }}
         data-testid={testId}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                     fontSize: 11, fontWeight: 700, marginBottom: 10,
                     color: titleColor || "#475569",
                     letterSpacing: 0.5, textTransform: "uppercase" }}>
        {icon} {title}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value, max, color = "#3b82f6" }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                     fontSize: 12, color: "#334155", marginBottom: 3 }}>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div style={{ height: 4, background: "#f1f5f9", borderRadius: 999, overflow: "hidden" }}>
        <div style={{ width: pct + "%", height: "100%",
                       background: color, transition: "width 0.4s" }} />
      </div>
    </div>
  );
}

function Tag({ text, color }) {
  return (
    <span style={{
      padding: "3px 9px", borderRadius: 999,
      background: color + "1A", color, fontSize: 11, fontWeight: 600,
      border: `1px solid ${color}33`,
    }}>{text}</span>
  );
}

function setorLabel(s) {
  const m = {
    suporte_tecnico: "🔧 Suporte Técnico",
    comercial: "💼 Comercial",
    financeiro: "💰 Financeiro",
    expansao_rede: "🌐 Expansão de Rede",
    gestao: "📊 Gestão",
  };
  return m[s] || s;
}

function DrilldownModal({ risco, onClose }) {
  const [items, setItems] = useState(null);
  useEffect(() => {
    api._client.get(`/alvaro/analyses?risco=${risco}&limit=100`)
        .then((r) => setItems(r.data.items || []))
        .catch(() => setItems([]));
  }, [risco]);
  return (
    <Modal title={`Conversas com risco ${risco.toUpperCase()}`} onClose={onClose} testId="alvaro-drilldown">
      {!items ? (
        <Loader2 size={24} style={{ animation: "spin 1s linear infinite" }} />
      ) : items.length === 0 ? (
        <p style={{ color: "#64748b" }}>Nenhuma conversa neste nível de risco.</p>
      ) : (
        <div style={{ maxHeight: 500, overflowY: "auto" }}>
          {items.map((a) => {
            const r = a.result || {};
            const an = r.analise || {};
            return (
              <div key={a.id} style={{
                padding: 12, borderBottom: "1px solid #f1f5f9", fontSize: 13,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>{r.cliente?.nome || r.cliente?.telefone || a.phone}</strong>
                  <span style={{ color: RISK_COLORS[risco], fontWeight: 700 }}>
                    Nota: {an.nota_1_a_10 || 0}/10
                  </span>
                </div>
                <div style={{ color: "#64748b", marginTop: 4 }}>
                  {an.motivo_principal_contato}
                </div>
                <div style={{ color: "#94a3b8", marginTop: 4, fontSize: 11 }}>
                  {an.tipo_reclamacao} · {an.sentimento} · Urgência: {an.urgencia}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}

function HistoryModal({ items, onClose }) {
  return (
    <Modal title="Histórico de relatórios" onClose={onClose} testId="alvaro-history-modal">
      {items.length === 0 ? (
        <p style={{ color: "#64748b" }}>Sem relatórios anteriores.</p>
      ) : (
        <div className="table-wrap" style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}><table style={{ width: "100%", minWidth: 640, fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 8 }}>Data</th>
              <th style={{ padding: 8 }}>Conversas</th>
              <th style={{ padding: 8 }}>Nota média</th>
              <th style={{ padding: 8 }}>Críticos</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #f1f5f9" }}>
                <td style={{ padding: 8 }}>
                  {new Date(r.finished_at).toLocaleString("pt-BR")}
                </td>
                <td style={{ padding: 8 }}>{r.report?.total_conversas || 0}</td>
                <td style={{ padding: 8 }}>{(r.report?.media_geral_notas || 0).toFixed(1)}</td>
                <td style={{ padding: 8, color: "#dc2626", fontWeight: 700 }}>
                  {r.report?.total_risco_cancelamento?.critico || 0}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </Modal>
  );
}

function Modal({ title, onClose, children, testId }) {
  return (
    <div onClick={onClose} data-testid={testId}
         style={{ position: "fixed", inset: 0, zIndex: 1000,
                   background: "rgba(2,6,23,0.7)",
                   display: "grid", placeItems: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: "white", borderRadius: 14, padding: 24,
                     maxWidth: 720, width: "100%", maxHeight: "85vh", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 18 }}>{title}</h3>
          <button onClick={onClose} style={{ border: "none", background: "transparent",
                                                cursor: "pointer", color: "#64748b" }}>
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

const btnPrimary = {
  padding: "10px 16px", borderRadius: 8, fontSize: 13, fontWeight: 700,
  background: "#7c3aed", color: "white", border: "none",
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6,
};

const btnSecondary = {
  padding: "10px 14px", borderRadius: 8, fontSize: 13, fontWeight: 600,
  background: "white", color: "#475569", border: "1px solid #cbd5e1",
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6,
};
