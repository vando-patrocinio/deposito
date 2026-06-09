/**
 * KnowledgeGraphPanel.jsx — FASE 6.5 IA Explicável
 * Pergunta "O que está causando os problemas?" com causa/efeito/impacto/ação.
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

function Card({ title, data }) {
  if (!data || !data.question) return null;
  return (
    <div data-testid={`card-${title}`}
         style={{ background: "#0f172a", border: "1px solid #1e293b",
                  borderRadius: 12, padding: 18, marginBottom: 14,
                  color: "#e2e8f0" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", marginBottom: 10 }}>
        <h3 style={{ margin: 0, color: "#7dd3fc", fontSize: 14,
                     fontWeight: 700 }}>{title}</h3>
        <span style={{ background: "#1e293b", padding: "3px 10px",
                       borderRadius: 999, fontSize: 11,
                       color: "#facc15", fontWeight: 700 }}>
          {Math.round((data.confidence || 0) * 100)}% confiança
        </span>
      </div>
      <div style={{ fontSize: 12, color: "#94a3b8",
                    marginBottom: 6, fontStyle: "italic" }}>
        "{data.question}"
      </div>
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 12, marginTop: 12 }}>
        {[
          ["CAUSA", data.cause, "#f97316"],
          ["EFEITO", data.effect, "#fbbf24"],
          ["IMPACTO", data.impact, "#ef4444"],
          ["AÇÃO", data.recommended_action, "#10b981"],
        ].map(([l, v, c]) => (
          <div key={l}>
            <div style={{ fontSize: 10, color: c,
                          textTransform: "uppercase",
                          letterSpacing: 1, fontWeight: 700 }}>{l}</div>
            <div style={{ fontSize: 13, color: "#e2e8f0",
                          marginTop: 2 }}>{v || "—"}</div>
          </div>
        ))}
      </div>
      {(data.factors || []).length > 0 && (
        <div style={{ marginTop: 14, paddingTop: 12,
                      borderTop: "1px solid #1e293b" }}>
          <div style={{ fontSize: 10, color: "#a855f7",
                        textTransform: "uppercase", letterSpacing: 1,
                        marginBottom: 6, fontWeight: 700 }}>
            Fatores ponderados
          </div>
          {data.factors.map((f) => (
            <div key={f.name}
                 style={{ display: "flex",
                          justifyContent: "space-between",
                          fontSize: 12, padding: "3px 0",
                          borderBottom: "1px dotted #1e293b" }}>
              <span style={{ color: "#cbd5e1" }}>
                {f.name} <span style={{ color: "#64748b" }}>
                  · peso {f.weight}</span>
              </span>
              <span style={{ color: "#7dd3fc",
                             fontFamily: "monospace" }}>
                {String(f.value)}
              </span>
            </div>
          ))}
        </div>
      )}
      {(data.evidence || []).length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 10,
                      borderTop: "1px dotted #1e293b" }}>
          <div style={{ fontSize: 10, color: "#64748b",
                        marginBottom: 4 }}>Evidências (dados reais):</div>
          {data.evidence.map((e, i) => (
            <div key={i} style={{ fontSize: 11,
                                   color: "#94a3b8",
                                   fontFamily: "monospace" }}>
              • {e}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


export default function KnowledgeGraphPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    client.get("/ai-center/knowledge-graph/what-causes-problems")
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ color: "#94a3b8" }}>Analisando grafo…</div>;
  if (!data) return null;

  return (
    <div data-testid="kg-panel">
      <div style={{ background: "linear-gradient(135deg, #1e1b1b 0%, #0f172a 100%)",
                    border: "1px solid #a855f766",
                    borderRadius: 14, padding: 22, marginBottom: 18 }}>
        <div style={{ fontSize: 11, color: "#c4b5fd",
                      textTransform: "uppercase", letterSpacing: 1.5,
                      fontWeight: 700 }}>
          Pergunta Executiva V4.0 · Knowledge Graph
        </div>
        <div style={{ fontSize: 24, fontWeight: 800,
                      color: "#f1f5f9", marginTop: 6 }}>
          "O que está causando os problemas?"
        </div>
        <div style={{ marginTop: 12, fontSize: 14,
                      color: "#e2e8f0", lineHeight: 1.6 }}>
          {data.summary}
        </div>
      </div>

      <Card title="Principal ofensor da rede (CTO)"
            data={data.top_offenders?.cto} />
      <Card title="Cliente em maior risco"
            data={data.top_offenders?.cliente_em_risco} />

      <div style={{ marginTop: 18, padding: 14,
                    background: "#0f172a",
                    border: "1px dashed #1e293b",
                    borderRadius: 10, color: "#cbd5e1",
                    fontSize: 12 }}>
        <b style={{ color: "#7dd3fc" }}>IA Explicável (XAI)</b> — toda resposta
        carrega fatores, peso, evidências e confiança. Endpoints disponíveis
        para explicar por que: cliente cancelou, CTO degrada, região tem mais
        tickets, campanha converteu, técnico produz mais.
      </div>
    </div>
  );
}
