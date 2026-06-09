/**
 * CashOperationPanel.jsx — V7.1 OPERAÇÃO CAIXA
 *
 * Critério de aceite V7.1: diretor responde em < 10s:
 *   1. Quanto dinheiro está em risco?
 *   2. Quanto a IA recuperou?
 *   3. O que impede recuperar mais?
 *   4. Qual ação gera mais dinheiro agora?
 *
 * Tudo em UMA tela. Sem investigação.
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const fmtBRL = (n) => (Number(n) || 0).toLocaleString("pt-BR",
  { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const fmtBRL2 = (n) => (Number(n) || 0).toLocaleString("pt-BR",
  { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
const fmtN = (n) => (Number(n) || 0).toLocaleString("pt-BR");

export default function CashOperationPanel() {
  const [wr, setWr] = useState(null);
  const [gl, setGl] = useState(null);
  const [top, setTop] = useState(null);
  const [a2c, setA2c] = useState(null);
  const [attr, setAttr] = useState(null);
  const [score, setScore] = useState(null);
  const [glMaster, setGlMaster] = useState(null);
  const [stream, setStream] = useState(null);

  const load = () => {
    Promise.all([
      client.get("/ai-center/cash/war-room"),
      client.get("/ai-center/cash/go-live"),
      client.get("/ai-center/cash/top-money-actions?top_n=10"),
      client.get("/ai-center/cash/action-to-cash?days=30"),
      client.get("/ai-center/cash/attribution?group_by=action_kind"),
      client.get("/ai-center/v80/score").catch(() => ({ data: null })),
      client.get("/ai-center/v80/golive-master")
        .catch(() => ({ data: null })),
      client.get("/ai-center/v80/money-stream?days=30")
        .catch(() => ({ data: null })),
    ]).then(([w, g, t, a, at, sc, gm, ms]) => {
      setWr(w.data); setGl(g.data); setTop(t.data);
      setA2c(a.data); setAttr(at.data);
      setScore(sc.data); setGlMaster(gm.data); setStream(ms.data);
    });
  };
  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  if (!wr || !gl || !top || !a2c || !attr)
    return <div style={{ color: "#94a3b8" }}>
      Carregando OPERAÇÃO CAIXA…
    </div>;

  return (
    <div data-testid="cash-operation-panel">
      {/* TÍTULO + HEADLINE */}
      <h2 style={{ color: "#f1f5f9", marginTop: 0, fontSize: 24 }}>
        💰 Operação Caixa · V8.0
      </h2>

      {/* SMARTPROV SCORE HERO */}
      {score && (() => {
        const c = score.score >= 81 ? "#10b981"
          : score.score >= 61 ? "#7dd3fc"
          : score.score >= 41 ? "#fbbf24" : "#ef4444";
        return (
          <div data-testid="smartprov-score-hero" style={{
            background: `linear-gradient(135deg, ${c}22 0%, #020617 100%)`,
            border: `2px solid ${c}`,
            borderRadius: 16, padding: 22, marginBottom: 14,
            display: "flex", gap: 22, alignItems: "center",
          }}>
            <div style={{ width: 140, height: 140, borderRadius: "50%",
                            border: `4px solid ${c}`,
                            background: "#020617",
                            display: "flex", flexDirection: "column",
                            alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 46, fontWeight: 900, color: c }}>
                {score.score}
              </div>
              <div style={{ fontSize: 10, color: "#94a3b8",
                              letterSpacing: 1.4, fontWeight: 700 }}>
                SMARTPROV
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "#94a3b8",
                              fontWeight: 800, letterSpacing: 1.8,
                              textTransform: "uppercase" }}>
                Score corporativo
              </div>
              <div style={{ fontSize: 32, fontWeight: 900, color: c,
                              marginTop: 4 }}>
                {score.classification}
              </div>
              <div style={{ display: "grid",
                              gridTemplateColumns: "repeat(5, 1fr)",
                              gap: 8, marginTop: 10 }}>
                {Object.entries(score.components).map(([k, v]) => (
                  <div key={k} style={{
                    background: "#0f172a",
                    border: "1px solid #1e293b",
                    borderRadius: 6, padding: 6, textAlign: "center",
                  }}>
                    <div style={{ fontSize: 9, color: "#64748b",
                                     letterSpacing: 1,
                                     textTransform: "uppercase" }}>
                      {k.replace("_", " ")}
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 700,
                                     color: v >= 75 ? "#10b981"
                                       : v >= 50 ? "#fbbf24" : "#ef4444" }}>
                      {v}%
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 11, color: "#cbd5e1",
                              marginTop: 8 }}>
                🎯 Gargalo: <b style={{ color: "#fbbf24" }}>
                  {score.bottleneck.name}
                </b> ({score.bottleneck.value}%) — investir aqui sobe o score
              </div>
            </div>
          </div>
        );
      })()}

      {/* GO LIVE MASTER (8 checks V8.0) */}
      {glMaster && (
        <div data-testid="golive-master" style={{
          background: glMaster.state === "VERDE"
            ? "linear-gradient(135deg, #064e3b 0%, #022c22 100%)"
            : "linear-gradient(135deg, #7f1d1d 0%, #450a0a 100%)",
          border: `2px solid ${glMaster.state === "VERDE" ? "#10b981" : "#ef4444"}`,
          borderRadius: 14, padding: 16, marginBottom: 14,
        }}>
          <div style={{ display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 10, color: "#cbd5e1",
                              letterSpacing: 2, fontWeight: 800,
                              textTransform: "uppercase" }}>
                GO LIVE Master · 8 dependências críticas
              </div>
              <div style={{ fontSize: 26, fontWeight: 900,
                              color: glMaster.state === "VERDE"
                                ? "#10b981" : "#ef4444",
                              marginTop: 4 }}>
                {glMaster.state === "VERDE" ? "🟢 100% VERDE" :
                  `🔴 VERMELHO · ${glMaster.blocker_count}/8`}
              </div>
            </div>
            <div style={{ flex: 1, marginLeft: 20,
                            display: "grid",
                            gridTemplateColumns: "repeat(4, 1fr)",
                            gap: 6 }}>
              {Object.entries(glMaster.checks).map(([k, v]) => (
                <div key={k} style={{ fontSize: 10,
                                          color: v ? "#10b981" : "#ef4444",
                                          fontFamily: "monospace" }}>
                  {v ? "✓" : "✗"} {k.substring(0, 20)}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* GO LIVE LIGHT — VERDE ou BLOQUEADO */}
      <div data-testid="go-live-indicator" style={{
        background: gl.state === "VERDE"
          ? "linear-gradient(135deg, #064e3b 0%, #022c22 100%)"
          : "linear-gradient(135deg, #7f1d1d 0%, #450a0a 100%)",
        border: `2px solid ${gl.state === "VERDE" ? "#10b981" : "#ef4444"}`,
        borderRadius: 14, padding: 18, marginBottom: 16,
        display: "flex", justifyContent: "space-between",
        alignItems: "center",
      }}>
        <div>
          <div style={{ fontSize: 10, color: "#cbd5e1",
                          fontWeight: 800, letterSpacing: 2,
                          textTransform: "uppercase" }}>
            WhatsApp · Operação Tese
          </div>
          <div style={{ fontSize: 24, fontWeight: 900,
                          color: gl.state === "VERDE"
                            ? "#10b981" : "#ef4444",
                          marginTop: 4 }}>
            {gl.state === "VERDE" ? "🟢 VERDE" : "🔴 BLOQUEADO"}
          </div>
        </div>
        <div style={{ flex: 1, marginLeft: 24,
                        fontSize: 12, color: "#cbd5e1" }}>
          {gl.next_step}
          {gl.blockers && gl.blockers.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11,
                            color: "#fca5a5" }}>
              Bloqueadores: {gl.blockers.join(" · ")}
            </div>
          )}
        </div>
      </div>

      {/* MONEY STREAM — onde dinheiro morre */}
      {stream && stream.biggest_leak && (
        <div data-testid="money-stream" style={{
          background: "linear-gradient(135deg, #78350f 0%, #020617 100%)",
          border: "1px solid #fbbf2466", borderRadius: 12,
          padding: 14, marginBottom: 14,
        }}>
          <div style={{ fontSize: 10, color: "#fde68a",
                          fontWeight: 800, letterSpacing: 1.8,
                          textTransform: "uppercase" }}>
            💸 Onde o dinheiro está morrendo?
          </div>
          <div style={{ fontSize: 16, fontWeight: 700,
                          color: "#fbbf24", marginTop: 4 }}>
            {stream.headline}
          </div>
          <div style={{ fontSize: 12, color: "#cbd5e1",
                          marginTop: 6 }}>
            Maior vazamento: <b>{stream.biggest_leak.stage_from}
            </b> → <b>{stream.biggest_leak.stage_to}</b> ·{" "}
            {stream.biggest_leak.lost_count} ações perdidas ·
            <b style={{ color: "#fbbf24" }}>{" "}
              {fmtBRL(stream.biggest_leak.lost_BRL)} em risco
            </b>
          </div>
        </div>
      )}

      {/* HEADLINE WAR ROOM */}
      <div style={{ background: "#0f172a",
                      border: "1px solid #1e293b",
                      borderRadius: 10, padding: 14,
                      marginBottom: 18, fontSize: 13,
                      color: "#7dd3fc", fontWeight: 600 }}>
        {wr.headline}
      </div>

      {/* 5 ESTADOS DA RECEITA */}
      <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(5, 1fr)",
                      gap: 10, marginBottom: 18 }}>
        <Big testid="r-risk" title="EM RISCO" value={wr.revenue_at_risk_BRL}
              color="#ef4444" />
        <Big testid="r-recoverable" title="RECUPERÁVEL"
              value={wr.revenue_recoverable_BRL} color="#fbbf24" />
        <Big testid="r-confirmed" title="CONFIRMADA 30d"
              value={wr.revenue_confirmed_30d} color="#7dd3fc" />
        <Big testid="r-received" title="RECEBIDA 30d"
              value={wr.revenue_received_30d} color="#10b981"
              highlight />
        <Big testid="r-lost" title="PERDIDA 7d"
              value={wr.revenue_lost_7d_BRL} color="#94a3b8" />
      </div>

      {/* KPI SUPREMO POR PERÍODO */}
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "0 0 10px 0" }}>
        💎 KPI Supremo · Dinheiro gerado pela IA
      </h3>
      <table data-testid="kpi-table"
             style={{ width: "100%", color: "#cbd5e1", fontSize: 13,
                        borderCollapse: "collapse",
                        background: "#0f172a", borderRadius: 8,
                        marginBottom: 18 }}>
        <thead>
          <tr style={{ color: "#64748b", background: "#1e293b",
                          textAlign: "left" }}>
            <th style={{ padding: 8 }}>Período</th>
            <th style={{ padding: 8, textAlign: "right" }}>Estimado</th>
            <th style={{ padding: 8, textAlign: "right" }}>Confirmado</th>
            <th style={{ padding: 8, textAlign: "right" }}>Recebido</th>
            <th style={{ padding: 8, textAlign: "right" }}>Conv%</th>
          </tr>
        </thead>
        <tbody>
          {["today", "7d", "30d", "12m"].map((p) => {
            const k = wr.kpi_by_period[p];
            return (
              <tr key={p}
                  style={{ borderBottom: "1px solid #1e293b" }}>
                <td style={{ padding: 8, fontWeight: 700,
                                color: "#7dd3fc" }}>{p.toUpperCase()}</td>
                <td style={{ padding: 8, textAlign: "right",
                                color: "#94a3b8" }}>
                  {fmtBRL2(k.estimated.BRL)}
                </td>
                <td style={{ padding: 8, textAlign: "right" }}>
                  {fmtBRL2(k.confirmed.BRL)}
                </td>
                <td style={{ padding: 8, textAlign: "right",
                                color: "#10b981", fontWeight: 700 }}>
                  {fmtBRL2(k.received.BRL)}
                </td>
                <td style={{ padding: 8, textAlign: "right",
                                color: k.conversion_pct >= 50 ? "#10b981"
                                  : k.conversion_pct >= 20 ? "#fbbf24"
                                  : "#ef4444",
                                fontWeight: 700 }}>
                  {k.conversion_pct}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* TOP 10 AÇÕES POR ROI */}
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "0 0 10px 0" }}>
        🎯 Top {top.count} ações para colocar dinheiro no caixa
        <span style={{ marginLeft: 8, color: "#94a3b8",
                          fontWeight: 500 }}>
          ({fmtBRL(top.total_BRL)} em jogo)
        </span>
      </h3>
      <div data-testid="top-actions" style={{ marginBottom: 18 }}>
        {top.items.map((it, i) => (
          <div key={i}
               style={{ background: "#0f172a",
                          border: "1px solid #1e293b",
                          borderRadius: 8, padding: 10,
                          marginBottom: 6,
                          display: "flex", gap: 10,
                          alignItems: "center" }}>
            <span style={{ minWidth: 26, textAlign: "center",
                              fontWeight: 900,
                              color: "#7dd3fc" }}>#{i + 1}</span>
            <div style={{ flex: 1 }}>
              <div style={{ color: "#f1f5f9", fontSize: 13,
                              fontWeight: 700 }}>{it.label}</div>
              <div style={{ color: "#94a3b8", fontSize: 11 }}>
                {it.action}
              </div>
            </div>
            <div style={{ color: "#10b981", fontWeight: 800,
                            fontSize: 16 }}>
              {fmtBRL(it.roi_BRL)}
            </div>
          </div>
        ))}
      </div>

      {/* FUNIL ACTION-TO-CASH */}
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "0 0 10px 0" }}>
        🔁 Funil Action → Cash (30d)
      </h3>
      <div data-testid="a2c-funnel" style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
        gap: 6, marginBottom: 18,
      }}>
        {Object.entries(a2c.funnel).map(([k, v]) => (
          <div key={k} style={{ background: "#0f172a",
                                  border: "1px solid #1e293b",
                                  borderRadius: 8, padding: 10,
                                  textAlign: "center" }}>
            <div style={{ fontSize: 10, color: "#94a3b8",
                            letterSpacing: 1.2,
                            textTransform: "uppercase" }}>
              {k}
            </div>
            <div style={{ fontSize: 20, fontWeight: 800,
                            color: k === "received"
                              ? "#10b981" : "#7dd3fc" }}>
              {fmtN(v)}
            </div>
            {a2c.conversion_rates_pct[k] !== undefined && (
              <div style={{ fontSize: 10, color: "#64748b" }}>
                {a2c.conversion_rates_pct[k]}%
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ATTRIBUTION (rastreabilidade) */}
      {attr.items.length > 0 && (
        <>
          <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                         textTransform: "uppercase", letterSpacing: 1.2,
                         margin: "0 0 10px 0" }}>
            🏷️ Quem gerou dinheiro (por action_kind)
          </h3>
          <table data-testid="attribution-table"
                  style={{ width: "100%", color: "#cbd5e1",
                              fontSize: 12, borderCollapse: "collapse",
                              background: "#0f172a", borderRadius: 8 }}>
            <thead>
              <tr style={{ color: "#64748b", background: "#1e293b" }}>
                <th style={{ padding: 8, textAlign: "left" }}>Tipo</th>
                <th style={{ padding: 8, textAlign: "right" }}>Eventos</th>
                <th style={{ padding: 8, textAlign: "right" }}>Esperado</th>
                <th style={{ padding: 8, textAlign: "right" }}>Realizado</th>
                <th style={{ padding: 8, textAlign: "right" }}>ROI%</th>
              </tr>
            </thead>
            <tbody>
              {attr.items.map((it) => (
                <tr key={it.key}
                    style={{ borderBottom: "1px solid #1e293b" }}>
                  <td style={{ padding: 8,
                                  fontFamily: "monospace" }}>
                    {it.key}
                  </td>
                  <td style={{ padding: 8, textAlign: "right" }}>
                    {it.events}
                  </td>
                  <td style={{ padding: 8, textAlign: "right" }}>
                    {fmtBRL2(it.expected_BRL)}
                  </td>
                  <td style={{ padding: 8, textAlign: "right",
                                  color: "#10b981", fontWeight: 700 }}>
                    {fmtBRL2(it.actual_BRL)}
                  </td>
                  <td style={{ padding: 8, textAlign: "right" }}>
                    {it.roi_pct}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function Big({ title, value, color, testid, highlight }) {
  return (
    <div data-testid={testid} style={{
      background: highlight ? "#064e3b" : "#0f172a",
      border: `2px solid ${color}${highlight ? "" : "55"}`,
      borderRadius: 12, padding: 14,
      boxShadow: highlight ? `0 0 24px ${color}33` : "none",
    }}>
      <div style={{ fontSize: 10, color: "#94a3b8",
                     fontWeight: 800, letterSpacing: 1.5 }}>
        {title}
      </div>
      <div style={{ fontSize: 22, fontWeight: 900, color,
                     marginTop: 6 }}>
        {fmtBRL(value)}
      </div>
    </div>
  );
}
