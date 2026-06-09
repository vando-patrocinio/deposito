/**
 * NervousSystemPanel.jsx — FASE 3 da Constituição V3.0
 *
 * Responde sem humano: "O que aconteceu na empresa hoje?"
 * Consome /api/ai-center/nervous-system/*
 */
import React, { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  Cell, RadialBarChart, RadialBar, PolarAngleAxis,
} from "recharts";
import { client } from "@/api";


const LEVEL_COLOR = {
  VERDE: "#10b981",
  AMARELO: "#facc15",
  VERMELHO: "#f97316",
};

const DOMAIN_LABEL = {
  comercial: "Comercial",
  instalacoes: "Instalações",
  financeiro: "Financeiro",
  atendimento: "Atendimento",
  whatsapp: "WhatsApp",
  indicacoes: "Indicações",
  parceiros: "Parceiros",
  estoque: "Estoque",
  rede: "Rede",
  operacoes: "Operações",
  outros: "Outros",
};

const DOMAIN_COLOR = {
  comercial: "#22c55e",
  instalacoes: "#3b82f6",
  financeiro: "#10b981",
  atendimento: "#f59e0b",
  whatsapp: "#06b6d4",
  indicacoes: "#a855f7",
  parceiros: "#ec4899",
  estoque: "#facc15",
  rede: "#0ea5e9",
  operacoes: "#f97316",
  outros: "#64748b",
};


function Panel({ title, right, children, testid }) {
  return (
    <div data-testid={testid}
         style={{ background: "#0f172a", border: "1px solid #1e293b",
                  borderRadius: 12, padding: 20, color: "#e2e8f0" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 14, color: "#7dd3fc",
                     fontWeight: 600 }}>{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}


export default function NervousSystemPanel() {
  const [coverage, setCoverage] = useState(null);
  const [whatHappened, setWhatHappened] = useState(null);
  const [topEvents, setTopEvents] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [byDomain, setByDomain] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [cov, wh, top, tl, dom] = await Promise.all([
        client.get("/ai-center/nervous-system/coverage?window_days=7"),
        client.get("/ai-center/nervous-system/what-happened-today"),
        client.get("/ai-center/nervous-system/top-events?hours=24&limit=15"),
        client.get("/ai-center/nervous-system/timeline-today?limit=50"),
        client.get("/ai-center/nervous-system/by-domain?hours=24"),
      ]);
      setCoverage(cov.data);
      setWhatHappened(wh.data);
      setTopEvents(top.data.items || []);
      setTimeline(tl.data.items || []);
      setByDomain(dom.data.items || {});
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  const runSync = async () => {
    setSyncing(true);
    try {
      const r = await client.post("/ai-center/nervous-system/run-sync");
      alert(`Sync OK: ${r.data.emitted_total} eventos emitidos.`);
      load();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading && !coverage) {
    return <div style={{ padding: 40, color: "#94a3b8",
                          textAlign: "center" }}>Carregando…</div>;
  }
  if (error) {
    return <div style={{ padding: 24, background: "#7f1d1d",
                          color: "#fee2e2", borderRadius: 8 }}>{error}</div>;
  }
  if (!coverage) return null;

  const lvl = coverage.level;
  const ovr = coverage.overall_coverage_pct;
  const ovrColor = LEVEL_COLOR[lvl] || "#64748b";

  const radialData = [{
    name: "Cobertura",
    value: ovr,
    fill: ovrColor,
  }];

  const domainBars = Object.entries(coverage.domains).map(([k, v]) => ({
    name: DOMAIN_LABEL[k] || k,
    pct: v.coverage_pct,
    events: v.event_count,
    color: DOMAIN_COLOR[k] || "#64748b",
  }));

  return (
    <div data-testid="nervous-system-panel"
         style={{ padding: 24, background: "#020617", minHeight: "100vh" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ color: "#f1f5f9", fontSize: 26, fontWeight: 800,
                       margin: 0, letterSpacing: -0.5 }}>
            Sistema Nervoso IA
          </h1>
          <div style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>
            Fase 3 · Meta corporativa: 90% cobertura nervosa
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button data-testid="reload-btn" onClick={load}
                  style={{ background: "#0ea5e9", color: "#fff",
                           border: "none", borderRadius: 8,
                           padding: "8px 14px", fontSize: 13,
                           cursor: "pointer", fontWeight: 600 }}>
            Atualizar
          </button>
          <button data-testid="run-sync-btn" onClick={runSync}
                  disabled={syncing}
                  style={{ background: syncing ? "#475569" : "#10b981",
                           color: "#fff", border: "none", borderRadius: 8,
                           padding: "8px 14px", fontSize: 13,
                           cursor: syncing ? "wait" : "pointer",
                           fontWeight: 600 }}>
            {syncing ? "Sincronizando…" : "Rodar Sync"}
          </button>
        </div>
      </div>

      {/* Linha superior: gauge + what happened today */}
      <div style={{ display: "grid",
                    gridTemplateColumns: "minmax(320px, 1fr) 2fr",
                    gap: 16, marginBottom: 22 }}>
        <div data-testid="overall-gauge"
             style={{ background: "linear-gradient(140deg, #020617 0%, #0b1220 100%)",
                      border: `2px solid ${ovrColor}66`,
                      borderRadius: 16, padding: 22, textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#64748b",
                        letterSpacing: 1.4, textTransform: "uppercase",
                        fontWeight: 700 }}>
            Cobertura Nervosa (7d)
          </div>
          <ResponsiveContainer width="100%" height={170}>
            <RadialBarChart innerRadius="65%" outerRadius="100%"
                            data={radialData} startAngle={210} endAngle={-30}>
              <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
              <RadialBar background={{ fill: "#1e293b" }}
                         dataKey="value" cornerRadius={8} />
            </RadialBarChart>
          </ResponsiveContainer>
          <div style={{ marginTop: -120, position: "relative",
                        height: 0 }}>
            <div style={{ fontSize: 36, fontWeight: 800,
                          color: "#f1f5f9", marginTop: 30 }}>
              {ovr.toFixed(1)}<span style={{ fontSize: 16,
                                              color: ovrColor }}>%</span>
            </div>
          </div>
          <div style={{ marginTop: 120, fontSize: 12, color: "#94a3b8" }}>
            <b style={{ color: ovrColor }}>{lvl}</b>
            {" · "}
            {coverage.total_covered_types}/{coverage.total_expected_types} tipos
          </div>
        </div>

        <div data-testid="what-happened-card"
             style={{ background: "#0f172a", border: "1px solid #1e293b",
                      borderRadius: 12, padding: 22 }}>
          <div style={{ fontSize: 11, color: "#7dd3fc",
                        letterSpacing: 1.4, textTransform: "uppercase",
                        fontWeight: 700, marginBottom: 10 }}>
            "O que aconteceu na empresa hoje?" · Presidente IA
          </div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#f1f5f9",
                        marginBottom: 12 }}>
            {whatHappened?.headline}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(whatHappened?.bullets || []).map((b) => (
              <span key={b} style={{ background: "#1e293b",
                                       padding: "4px 10px",
                                       borderRadius: 6, fontSize: 12,
                                       color: "#cbd5e1" }}>{b}</span>
            ))}
          </div>
          {(whatHappened?.top || []).length > 0 && (
            <div style={{ marginTop: 14, paddingTop: 14,
                          borderTop: "1px solid #1e293b" }}>
              <div style={{ fontSize: 11, color: "#64748b",
                            marginBottom: 6 }}>
                Top 5 eventos do dia:
              </div>
              {(whatHappened.top || []).map((t) => (
                <div key={t.event_type}
                     data-testid={`top-event-${t.event_type}`}
                     style={{ display: "flex",
                              justifyContent: "space-between",
                              fontSize: 13, padding: "4px 0",
                              borderBottom: "1px dotted #1e293b" }}>
                  <span style={{ color: "#cbd5e1" }}>{t.label}</span>
                  <b style={{ color: "#7dd3fc" }}>{t.count}</b>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Cobertura por domínio */}
      <Panel testid="coverage-by-domain"
             title="Cobertura por Domínio (Constituição V3.0)"
             right={<span style={{ fontSize: 11, color: "#64748b" }}>
                      janela 7d
                    </span>}>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={domainBars}>
            <XAxis dataKey="name" stroke="#64748b" fontSize={11} />
            <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]}
                   tickFormatter={(v) => `${v}%`} />
            <Tooltip
              contentStyle={{ background: "#0f172a",
                              border: "1px solid #1e293b" }}
              formatter={(v) => `${v}%`} />
            <Bar dataKey="pct" radius={[6, 6, 0, 0]}>
              {domainBars.map((d, i) => (
                <Cell key={i} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <div style={{ display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 16, marginTop: 22 }}>
        <Panel testid="top-events-card"
               title="Top 15 eventos (24h)">
          {topEvents.length === 0 ? (
            <div style={{ color: "#475569", fontSize: 13, padding: 16 }}>
              Sem eventos.
            </div>
          ) : (
            <table style={{ width: "100%", color: "#cbd5e1",
                            fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "#64748b" }}>
                  <th style={{ padding: 6, textAlign: "left",
                               borderBottom: "1px solid #1e293b" }}>Evento</th>
                  <th style={{ padding: 6, textAlign: "right",
                               borderBottom: "1px solid #1e293b" }}>Qtd</th>
                </tr>
              </thead>
              <tbody>
                {topEvents.map((t) => (
                  <tr key={t.event_type}>
                    <td style={{ padding: 6,
                                 borderBottom: "1px solid #1e293b" }}>
                      {t.label}
                    </td>
                    <td style={{ padding: 6, textAlign: "right",
                                 borderBottom: "1px solid #1e293b",
                                 color: "#10b981", fontWeight: 700 }}>
                      {t.count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel testid="timeline-card"
               title="Timeline corporativa (hoje)"
               right={<span style={{ fontSize: 11, color: "#64748b" }}>
                        {timeline.length} itens
                      </span>}>
          <div style={{ maxHeight: 360, overflowY: "auto" }}>
            {timeline.length === 0 ? (
              <div style={{ color: "#475569", fontSize: 13, padding: 16 }}>
                Sem atividade hoje.
              </div>
            ) : timeline.map((t, i) => {
              const c = t.kind === "event" ? "#7dd3fc"
                       : t.kind === "decision" ? "#f59e0b"
                       : "#a855f7";
              return (
                <div key={i}
                     data-testid={`timeline-${i}`}
                     style={{ display: "flex", gap: 10,
                              padding: "6px 0",
                              borderBottom: "1px dotted #1e293b",
                              fontSize: 12 }}>
                  <div style={{ width: 4, background: c,
                                borderRadius: 2 }} />
                  <div style={{ color: "#64748b", width: 70,
                                fontFamily: "monospace" }}>
                    {(t.ts || "").substr(11, 8)}
                  </div>
                  <div style={{ color: c, width: 80, fontWeight: 600,
                                textTransform: "uppercase",
                                fontSize: 10 }}>
                    {t.kind}
                  </div>
                  <div style={{ color: "#e2e8f0", flex: 1 }}>
                    {t.label}
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      </div>

      <div style={{ marginTop: 28, fontSize: 11, color: "#475569",
                    textAlign: "center" }}>
        Sync polling roda automaticamente a cada 1 min (APScheduler · leader-elected).
        Bootstrap conservador: histórico pré-instalação <b>não</b> é re-emitido.
      </div>
    </div>
  );
}
