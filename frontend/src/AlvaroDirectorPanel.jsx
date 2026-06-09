/**
 * AlvaroPanel.jsx — FASE 7 Diretor de Operações Digital
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const LEVEL_COLOR = {
  DESTAQUE: "#10b981", REGULAR: "#fbbf24", ATENCAO: "#ef4444",
  SAUDAVEL: "#10b981", CRITICA: "#ef4444",
};

function Section({ title, children, testid }) {
  return (
    <div data-testid={testid} style={{ marginBottom: 18 }}>
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   margin: "0 0 10px 0",
                   textTransform: "uppercase",
                   letterSpacing: 1.2 }}>{title}</h3>
      {children}
    </div>
  );
}


export default function AlvaroPanel() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    client.get("/ai-center/alvaro/director-summary")
      .then((r) => setData(r.data));
  };

  const runBriefing = async (kind) => {
    setBusy(true);
    try {
      const r = await client.post(
        `/ai-center/alvaro/briefing?kind=${kind}`);
      alert(`Briefing ${kind}:\n\n${r.data.body}`);
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  useEffect(() => { load(); }, []);

  if (!data) return <div style={{ color: "#94a3b8" }}>Carregando Álvaro…</div>;

  return (
    <div data-testid="alvaro-panel">
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 18 }}>
        <h2 style={{ color: "#f1f5f9", margin: 0, fontSize: 22 }}>
          Álvaro · Diretor de Operações
        </h2>
        <div style={{ display: "flex", gap: 8 }}>
          {["07h", "12h", "18h"].map((k) => (
            <button key={k} data-testid={`brief-${k}`}
                    onClick={() => runBriefing(k)} disabled={busy}
                    style={{ background: "#3b82f6", color: "#fff",
                             border: "none", borderRadius: 8,
                             padding: "8px 12px", fontSize: 12,
                             cursor: busy ? "wait" : "pointer",
                             fontWeight: 600 }}>
              Briefing {k}
            </button>
          ))}
        </div>
      </div>

      <div style={{ background: "linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%)",
                    border: "1px solid #3b82f666",
                    borderRadius: 12, padding: 18, marginBottom: 18 }}>
        <div style={{ fontSize: 11, color: "#93c5fd",
                      textTransform: "uppercase", letterSpacing: 1.5,
                      fontWeight: 700 }}>
          Resumo executivo · Álvaro
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "#f1f5f9",
                      marginTop: 6 }}>
          {data.headline}
        </div>
      </div>

      <Section testid="techs-section" title="Top 5 Técnicos">
        <table style={{ width: "100%", color: "#cbd5e1",
                        fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "#64748b", textAlign: "left" }}>
              <th style={{ padding: 6 }}>Técnico</th>
              <th style={{ padding: 6 }}>Score</th>
              <th style={{ padding: 6 }}>Tickets</th>
              <th style={{ padding: 6 }}>Taxa fechamento</th>
              <th style={{ padding: 6 }}>Nível</th>
            </tr>
          </thead>
          <tbody>
            {data.top_technicians.map((t) => (
              <tr key={t.collaborator_id}>
                <td style={{ padding: 6, fontFamily: "monospace",
                             borderBottom: "1px solid #1e293b" }}>
                  {(t.collaborator_id || "").substring(0, 20)}
                </td>
                <td style={{ padding: 6,
                             borderBottom: "1px solid #1e293b",
                             color: LEVEL_COLOR[t.level],
                             fontWeight: 700 }}>{t.score}</td>
                <td style={{ padding: 6,
                             borderBottom: "1px solid #1e293b" }}>{t.total_tickets}</td>
                <td style={{ padding: 6,
                             borderBottom: "1px solid #1e293b" }}>
                  {t.closure_rate}%
                </td>
                <td style={{ padding: 6,
                             borderBottom: "1px solid #1e293b",
                             color: LEVEL_COLOR[t.level],
                             fontWeight: 700 }}>{t.level}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section testid="regions-section" title="Regiões (piores primeiro)">
        <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 10 }}>
          {data.region_ranking.slice(0, 6).map((r) => (
            <div key={r.region}
                 style={{ background: "#0f172a",
                          border: `1px solid ${LEVEL_COLOR[r.level]}33`,
                          borderRadius: 8, padding: 12 }}>
              <div style={{ fontSize: 12, color: "#cbd5e1",
                            fontWeight: 600 }}>{r.region}</div>
              <div style={{ fontSize: 22, fontWeight: 800,
                            color: LEVEL_COLOR[r.level] }}>{r.score}</div>
              <div style={{ fontSize: 10, color: "#94a3b8" }}>
                {r.subscribers} subs · {r.tickets} tickets · {r.bad_onus} ONUs ruins
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section testid="bottlenecks-section" title="Gargalos detectados">
        {data.bottlenecks.length === 0
          ? <div style={{ color: "#10b981", fontSize: 13 }}>
              ✓ Sem gargalos críticos.
            </div>
          : data.bottlenecks.map((b, i) => (
            <div key={i}
                 style={{ background: "#0f172a",
                          border: "1px solid #ef444466",
                          borderRadius: 8, padding: 12,
                          marginBottom: 8, color: "#fca5a5" }}>
              <b>{b.type}</b> · {b.description}
              <span style={{ marginLeft: 8, color: "#fbbf24" }}>
                [{b.severity}]
              </span>
            </div>
          ))}
      </Section>

      <Section testid="waste-section" title="Desperdícios">
        <div style={{ background: "#0f172a", border: "1px solid #1e293b",
                      borderRadius: 8, padding: 14, color: "#cbd5e1",
                      fontSize: 13 }}>
          {data.waste.waste_summary}
        </div>
      </Section>

      <Section testid="recs-section" title="Recomendações operacionais">
        {data.recommendations.map((r) => (
          <div key={r.id}
               style={{ background: "#0f172a", border: "1px solid #1e293b",
                        borderRadius: 8, padding: 14, marginBottom: 8 }}>
            <div style={{ display: "flex",
                          justifyContent: "space-between" }}>
              <b style={{ color: "#7dd3fc", fontSize: 13 }}>
                {r.problem}
              </b>
              <span style={{ background: r.urgency === "ALTA" ? "#7f1d1d"
                                         : "#854d0e",
                             color: "#fff", padding: "2px 8px",
                             borderRadius: 999, fontSize: 10,
                             fontWeight: 700 }}>
                {r.urgency}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "#94a3b8",
                          marginTop: 4 }}>
              Impacto: <b style={{ color: "#fbbf24" }}>{r.impact}</b>
            </div>
            <div style={{ fontSize: 12, color: "#cbd5e1",
                          marginTop: 4 }}>
              ↳ Ação: {r.action}
            </div>
            <div style={{ fontSize: 12, color: "#86efac",
                          marginTop: 2 }}>
              ✓ Esperado: {r.expected_result}
            </div>
          </div>
        ))}
      </Section>
    </div>
  );
}
