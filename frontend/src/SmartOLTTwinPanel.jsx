/**
 * SmartOLTTwinPanel.jsx — FASE 4 da Constituição V3.0
 * Gêmeo digital da rede: ONU/CTO/PON/VLAN health + heatmap + predições.
 */
import React, { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { client } from "@/api";

const LEVEL_COLOR = {
  EXCELENTE: "#10b981",
  SAUDAVEL: "#22c55e",
  ATENCAO: "#facc15",
  CRITICO: "#f97316",
  INCIDENTE: "#ef4444",
  SATURADA: "#ef4444",
};

function fmtBRL(n) {
  return (n || 0).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
}

function Panel({ title, children, testid, right }) {
  return (
    <div data-testid={testid}
         style={{ background: "#0f172a", border: "1px solid #1e293b",
                  borderRadius: 12, padding: 18, color: "#e2e8f0" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 13, color: "#7dd3fc",
                     fontWeight: 700, letterSpacing: 0.5 }}>{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}


export default function SmartOLTTwinPanel() {
  const [worry, setWorry] = useState(null);
  const [cto, setCto] = useState([]);
  const [pon, setPon] = useState([]);
  const [vlan, setVlan] = useState([]);
  const [pred, setPred] = useState(null);
  const [rev, setRev] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [w, c, p, v, pr, r] = await Promise.all([
        client.get("/ai-center/smartolt-twin/what-to-worry"),
        client.get("/ai-center/smartolt-twin/cto-health"),
        client.get("/ai-center/smartolt-twin/pon-health"),
        client.get("/ai-center/smartolt-twin/vlan-health"),
        client.get("/ai-center/smartolt-twin/predictions"),
        client.get("/ai-center/smartolt-twin/revenue-at-risk"),
      ]);
      setWorry(w.data); setCto(c.data.items || []);
      setPon(p.data.items || []); setVlan(v.data.items || []);
      setPred(pr.data); setRev(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  if (loading && !cto.length) {
    return <div style={{ padding: 40, color: "#94a3b8" }}>Carregando…</div>;
  }
  if (error) return <div style={{ padding: 24, background: "#7f1d1d",
                                    color: "#fee2e2", borderRadius: 8 }}>
                       {error}</div>;

  const ctoBars = cto.slice(0, 12).map((c) => ({
    name: c.cto?.length > 14 ? c.cto.substring(0, 13) + "…" : c.cto,
    score: c.score, color: LEVEL_COLOR[c.level],
    full: c.cto,
  }));

  return (
    <div data-testid="smartolt-twin-panel"
         style={{ padding: 24, background: "#020617", minHeight: "100vh" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 22 }}>
        <div>
          <h1 style={{ color: "#f1f5f9", fontSize: 26, fontWeight: 800,
                       margin: 0 }}>
            SmartOLT Digital Twin
          </h1>
          <div style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>
            Fase 4 · Gêmeo digital da rede em tempo real
          </div>
        </div>
        <button data-testid="reload-btn" onClick={load}
                style={{ background: "#0ea5e9", color: "#fff",
                         border: "none", borderRadius: 8,
                         padding: "8px 14px", fontSize: 13,
                         cursor: "pointer", fontWeight: 600 }}>
          Atualizar
        </button>
      </div>

      {/* Pergunta-chave da IA */}
      <div data-testid="what-to-worry-card"
           style={{ background: "linear-gradient(140deg, #1e1b1b 0%, #0f172a 100%)",
                    border: "1px solid #f9731666",
                    borderRadius: 14, padding: 22, marginBottom: 22 }}>
        <div style={{ fontSize: 11, color: "#fbbf24",
                      textTransform: "uppercase", letterSpacing: 1.4,
                      fontWeight: 700, marginBottom: 12 }}>
          "Se eu não investir nada por 30d, onde explode?" · Presidente IA
        </div>
        <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                      gap: 14 }}>
          {[
            ["CTO que mais preocupa", worry?.qual_cto_preocupa],
            ["Bairro degradando", worry?.bairro_degradando],
            ["Onde haverá saturação", worry?.onde_havera_saturacao],
            ["Risco operacional", worry?.risco_operacional],
            ["Onde investir primeiro", worry?.onde_investir_primeiro],
            ["Próximo problema (30d)", worry?.predicted_next_problem_30d],
          ].map(([label, val]) => (
            <div key={label}
                 data-testid={`worry-${label.toLowerCase().replace(/\s/g,"-")}`}>
              <div style={{ fontSize: 11, color: "#64748b",
                            textTransform: "uppercase", letterSpacing: 1 }}>
                {label}
              </div>
              <div style={{ fontSize: 14, color: "#f1f5f9",
                            marginTop: 2, fontWeight: 600 }}>
                {val || "—"}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Revenue at risk */}
      <Panel testid="revenue-risk-card"
             title="Revenue at Risk · R$ em risco AGORA"
             right={
               <span style={{ color: "#fbbf24", fontSize: 11,
                              fontWeight: 700 }}>
                 {rev?.subs_in_bad_onu} subs ONU ruim · {rev?.subs_in_critical_cto} CTO crítica
               </span>
             }>
        <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                      gap: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>Mensal</div>
            <div style={{ fontSize: 28, fontWeight: 800,
                          color: "#fca5a5" }}>
              {fmtBRL(rev?.monthly_BRL_at_risk)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>Anual</div>
            <div style={{ fontSize: 22, fontWeight: 700,
                          color: "#fbbf24" }}>
              {fmtBRL(rev?.annual_BRL_at_risk)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>
              VLANs saturadas
            </div>
            <div style={{ fontSize: 16, color: "#cbd5e1" }}>
              {(rev?.saturated_vlans || []).join(", ") || "—"}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>
              CTOs críticas
            </div>
            <div style={{ fontSize: 12, color: "#cbd5e1" }}>
              {(rev?.critical_ctos || []).slice(0, 4).join(", ") || "—"}
            </div>
          </div>
        </div>
      </Panel>

      {/* CTO Health */}
      <div style={{ marginTop: 22 }}>
        <Panel testid="cto-health-card"
               title="CTO Health · Ranking de saúde"
               right={
                 <span style={{ fontSize: 11, color: "#64748b" }}>
                   {cto.length} CTOs
                 </span>
               }>
          {ctoBars.length > 0 && (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={ctoBars} margin={{ bottom: 30 }}>
                <XAxis dataKey="name" stroke="#64748b" fontSize={10}
                       angle={-30} textAnchor="end" height={50} />
                <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]}
                       tickFormatter={(v) => `${v}`} />
                <Tooltip
                  contentStyle={{ background: "#0f172a",
                                  border: "1px solid #1e293b" }} />
                <Bar dataKey="score" radius={[6, 6, 0, 0]}>
                  {ctoBars.map((d, i) => (
                    <Cell key={i} fill={d.color || "#64748b"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          <table style={{ width: "100%", color: "#cbd5e1",
                          fontSize: 13, borderCollapse: "collapse",
                          marginTop: 14 }}>
            <thead>
              <tr style={{ color: "#64748b", textAlign: "left" }}>
                <th style={{ padding: 6 }}>CTO</th>
                <th style={{ padding: 6 }}>Score</th>
                <th style={{ padding: 6 }}>Nível</th>
                <th style={{ padding: 6 }}>ONUs</th>
                <th style={{ padding: 6 }}>Offline</th>
              </tr>
            </thead>
            <tbody>
              {cto.map((c) => (
                <tr key={c.cto} data-testid={`cto-row-${c.cto}`}>
                  <td style={{ padding: 6,
                               borderBottom: "1px solid #1e293b" }}>{c.cto}</td>
                  <td style={{ padding: 6, fontWeight: 700,
                               borderBottom: "1px solid #1e293b",
                               color: LEVEL_COLOR[c.level] }}>
                    {c.score}
                  </td>
                  <td style={{ padding: 6, fontSize: 11,
                               borderBottom: "1px solid #1e293b",
                               color: LEVEL_COLOR[c.level] }}>
                    {c.level}
                  </td>
                  <td style={{ padding: 6,
                               borderBottom: "1px solid #1e293b" }}>{c.total_onus}</td>
                  <td style={{ padding: 6,
                               borderBottom: "1px solid #1e293b",
                               color: c.offline > 0 ? "#fca5a5" : "#cbd5e1" }}>
                    {c.offline}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      {/* Predições */}
      <div style={{ marginTop: 22 }}>
        <Panel testid="predictions-card"
               title="Predições (heurística estado-atual)">
          <div style={{ display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                        gap: 14 }}>
            {pred && Object.entries({
              CTO_DEGRADED: pred.CTO_DEGRADED,
              CTO_CRITICAL: pred.CTO_CRITICAL,
              VLAN_SATURATED: pred.VLAN_SATURATED,
              MASS_OFFLINE: pred.MASS_OFFLINE,
              CHURN_BY_SIGNAL: pred.CHURN_BY_SIGNAL,
            }).map(([k, v]) => (
              <div key={k}
                   data-testid={`pred-${k}`}
                   style={{ background: "#020617",
                            border: "1px solid #1e293b",
                            borderRadius: 8, padding: 14 }}>
                <div style={{ fontSize: 10, color: "#94a3b8",
                              textTransform: "uppercase",
                              letterSpacing: 1, fontWeight: 700 }}>{k}</div>
                <div style={{ fontSize: 28, fontWeight: 800,
                              color: v?.predicted_count > 0 ? "#fca5a5"
                                                           : "#10b981" }}>
                  {v?.predicted_count ?? 0}
                </div>
                {(v?.top || []).slice(0, 3).map((it, i) => (
                  <div key={i} style={{ fontSize: 11,
                                         color: "#94a3b8" }}>
                    • {String(it)}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {/* PON + VLAN */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                    gap: 16, marginTop: 22 }}>
        <Panel testid="pon-health-card"
               title={`Top ${Math.min(pon.length, 10)} PONs piores`}>
          <div style={{ maxHeight: 320, overflowY: "auto" }}>
            <table style={{ width: "100%", color: "#cbd5e1",
                            fontSize: 12, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "#64748b", textAlign: "left" }}>
                  <th style={{ padding: 4 }}>PON</th>
                  <th style={{ padding: 4 }}>Score</th>
                  <th style={{ padding: 4 }}>Total</th>
                  <th style={{ padding: 4 }}>Off</th>
                </tr>
              </thead>
              <tbody>
                {pon.slice(0, 20).map((p) => (
                  <tr key={p.pon}>
                    <td style={{ padding: 4, fontFamily: "monospace",
                                 fontSize: 11 }}>{p.pon}</td>
                    <td style={{ padding: 4, fontWeight: 700,
                                 color: LEVEL_COLOR[p.level] }}>
                      {p.score}
                    </td>
                    <td style={{ padding: 4 }}>{p.total}</td>
                    <td style={{ padding: 4, color: "#fca5a5" }}>
                      {p.offline + p.los + p.power_fail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel testid="vlan-health-card" title="VLAN Health · Utilização">
          {vlan.length === 0 ? (
            <div style={{ color: "#475569", padding: 16 }}>Sem dados.</div>
          ) : (
            <table style={{ width: "100%", color: "#cbd5e1",
                            fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "#64748b", textAlign: "left" }}>
                  <th style={{ padding: 6 }}>VLAN</th>
                  <th style={{ padding: 6 }}>Subs</th>
                  <th style={{ padding: 6 }}>Utilização</th>
                  <th style={{ padding: 6 }}>Nível</th>
                </tr>
              </thead>
              <tbody>
                {vlan.map((v) => (
                  <tr key={v.vlan}>
                    <td style={{ padding: 6, fontFamily: "monospace" }}>
                      {String(v.vlan)}
                    </td>
                    <td style={{ padding: 6 }}>{v.count}</td>
                    <td style={{ padding: 6,
                                 color: v.utilization_pct >= 80
                                        ? "#fca5a5" : "#cbd5e1" }}>
                      {v.utilization_pct}%
                    </td>
                    <td style={{ padding: 6,
                                 color: LEVEL_COLOR[v.level],
                                 fontWeight: 700 }}>
                      {v.level}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      <div style={{ marginTop: 28, fontSize: 11, color: "#475569",
                    textAlign: "center" }}>
        Cálculo on-demand · sem cache · dados live do MongoDB.
        Score score &lt;70 dispara CTO_DEGRADED/CRITICAL no Event Bus.
      </div>
    </div>
  );
}
