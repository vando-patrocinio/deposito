/**
 * IsabellaPanel.jsx — FASE 6 Isabella Revenue Engine
 * 6 scores + next_best_action + playbooks automáticos
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const SCORE_LABELS = {
  buy_score: "Buy",
  upgrade_score: "Upgrade",
  churn_score: "Churn",
  retention_score: "Retention",
  referral_score: "Referral",
  collection_score: "Collection",
};

const SCORE_COLORS = {
  buy_score: "#22c55e",
  upgrade_score: "#10b981",
  churn_score: "#ef4444",
  retention_score: "#3b82f6",
  referral_score: "#a855f7",
  collection_score: "#fbbf24",
};

function fmtBRL(n) {
  return (n || 0).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
}


export default function IsabellaPanel() {
  const [pot, setPot] = useState(null);
  const [wts, setWts] = useState(null);
  const [tops, setTops] = useState({});
  const [opps, setOpps] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const [p, w, o, ...allTops] = await Promise.all([
      client.get("/ai-center/isabella/revenue-potential"),
      client.get("/ai-center/isabella/where-to-sell"),
      client.get("/ai-center/isabella/opportunities?limit=20"),
      ...Object.keys(SCORE_LABELS).map((k) =>
        client.get(`/ai-center/isabella/top/${k}?limit=5`)),
    ]);
    setPot(p.data); setWts(w.data); setOpps(o.data.items || []);
    const t = {};
    Object.keys(SCORE_LABELS).forEach((k, i) => {
      t[k] = allTops[i].data.items || [];
    });
    setTops(t);
  };

  const recalc = async () => {
    setBusy(true);
    try {
      const r = await client.post("/ai-center/isabella/recalculate");
      const p = await client.post("/ai-center/isabella/run-playbooks");
      alert(`OK. Recalculado: ${r.data.scored} subs. ` +
            `Playbooks criados: ${JSON.stringify(p.data.created)}`);
      load();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  useEffect(() => { load(); }, []);

  return (
    <div data-testid="isabella-panel">
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 18 }}>
        <h2 style={{ color: "#f1f5f9", margin: 0, fontSize: 22 }}>
          Isabella · Revenue Engine
        </h2>
        <button onClick={recalc} disabled={busy}
                data-testid="recalc-btn"
                style={{ background: "#10b981", color: "#fff",
                         border: "none", borderRadius: 8,
                         padding: "8px 14px", fontSize: 13,
                         cursor: busy ? "wait" : "pointer",
                         fontWeight: 600 }}>
          {busy ? "Recalculando…" : "Recalcular + Playbooks"}
        </button>
      </div>

      {/* Pergunta executiva V4.0 */}
      {wts && (
        <div data-testid="where-to-sell-card"
             style={{ background: "linear-gradient(135deg, #064e3b 0%, #0f172a 100%)",
                      border: "1px solid #10b98166",
                      borderRadius: 14, padding: 22, marginBottom: 18 }}>
          <div style={{ fontSize: 11, color: "#86efac",
                        textTransform: "uppercase", letterSpacing: 1.5,
                        fontWeight: 700 }}>
            "Onde podemos vender mais hoje?" · Isabella
          </div>
          <pre style={{ marginTop: 10, color: "#e2e8f0", fontSize: 14,
                        fontFamily: "inherit", whiteSpace: "pre-wrap",
                        lineHeight: 1.6 }}>
            {wts.headline}
          </pre>
          <div style={{ marginTop: 8, fontSize: 12, color: "#86efac",
                        fontWeight: 600 }}>
            Recomendação: {wts.best_campaign}
          </div>
        </div>
      )}

      {/* Potential cards */}
      {pot && (
        <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 12, marginBottom: 20 }}>
          {[
            ["Candidatos Upgrade", pot.upgrade_candidates,
              `~${fmtBRL(pot.upgrade_monthly_BRL_estimate)}/mês`, "#10b981"],
            ["Candidatos Cross-Sell", pot.cross_sell_candidates,
              `~${fmtBRL(pot.cross_sell_monthly_BRL_estimate)}/mês`, "#22c55e"],
            ["Candidatos Cobrança", pot.collection_candidates,
              `Carteira: ${fmtBRL(pot.collection_recoverable_BRL)}`, "#fbbf24"],
            ["Recuperação 18%", `~${fmtBRL(pot.collection_recoverable_p18)}`,
              "Provável conversão", "#86efac"],
          ].map(([l, v, sub, c]) => (
            <div key={l} data-testid={`pot-${l}`}
                 style={{ background: "#0f172a",
                          border: `1px solid ${c}33`,
                          borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 10, color: "#64748b",
                            textTransform: "uppercase",
                            letterSpacing: 1, fontWeight: 700 }}>{l}</div>
              <div style={{ fontSize: 22, fontWeight: 800,
                            color: c }}>{v}</div>
              <div style={{ fontSize: 11, color: "#94a3b8",
                            marginTop: 2 }}>{sub}</div>
            </div>
          ))}
        </div>
      )}

      {/* Top 5 por score */}
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                    gap: 12, marginBottom: 20 }}>
        {Object.entries(SCORE_LABELS).map(([k, label]) => (
          <div key={k} data-testid={`top-${k}`}
               style={{ background: "#0f172a",
                        border: "1px solid #1e293b",
                        borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700,
                          color: SCORE_COLORS[k],
                          textTransform: "uppercase",
                          letterSpacing: 1, marginBottom: 8 }}>
              Top {label}
            </div>
            {(tops[k] || []).slice(0, 5).map((t, i) => (
              <div key={t.subscriber_id}
                   style={{ display: "flex",
                            justifyContent: "space-between",
                            padding: "4px 0", fontSize: 12,
                            borderBottom: "1px dotted #1e293b" }}>
                <span style={{ color: "#cbd5e1",
                               fontFamily: "monospace",
                               fontSize: 11 }}>
                  {t.subscriber_id.substring(0, 16)}
                </span>
                <span style={{ color: SCORE_COLORS[k],
                               fontWeight: 700 }}>{t[k]}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Oportunidades geradas */}
      <div data-testid="opportunities-card"
           style={{ background: "#0f172a", border: "1px solid #1e293b",
                    borderRadius: 10, padding: 14 }}>
        <div style={{ color: "#7dd3fc", fontWeight: 700,
                      marginBottom: 10, fontSize: 13 }}>
          Oportunidades geradas ({opps.length})
        </div>
        {opps.length === 0 ? (
          <div style={{ color: "#475569", fontSize: 12 }}>
            Nenhuma oportunidade. Clique "Recalcular + Playbooks".
          </div>
        ) : (
          <table style={{ width: "100%", color: "#cbd5e1",
                          fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: "#64748b", textAlign: "left" }}>
                <th style={{ padding: 6 }}>Tipo</th>
                <th style={{ padding: 6 }}>Subscriber</th>
                <th style={{ padding: 6 }}>Score</th>
                <th style={{ padding: 6 }}>Criada em</th>
              </tr>
            </thead>
            <tbody>
              {opps.map((o, i) => (
                <tr key={o.id || i}>
                  <td style={{ padding: 6,
                               borderBottom: "1px solid #1e293b" }}>
                    <span style={{ background: "#1e293b",
                                   padding: "2px 8px",
                                   borderRadius: 6,
                                   color: "#7dd3fc" }}>{o.kind}</span>
                  </td>
                  <td style={{ padding: 6,
                               borderBottom: "1px solid #1e293b",
                               fontFamily: "monospace",
                               fontSize: 11 }}>
                    {o.subscriber_id?.substring(0, 18)}
                  </td>
                  <td style={{ padding: 6,
                               borderBottom: "1px solid #1e293b",
                               color: "#10b981", fontWeight: 700 }}>
                    {o.score}
                  </td>
                  <td style={{ padding: 6,
                               borderBottom: "1px solid #1e293b",
                               color: "#64748b", fontSize: 11 }}>
                    {(o.created_at || "").substring(0, 19)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ marginTop: 20, fontSize: 11,
                    color: "#475569", textAlign: "center" }}>
        Scores heurísticos baseados em age + tickets + onu + invoices.
        Quando <code style={{ color: "#7dd3fc" }}>subscribers.plan_price</code> for
        populado, scores de upgrade/cross-sell ganham precisão.
      </div>
    </div>
  );
}
