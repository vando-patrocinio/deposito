/**
 * RealRevenuePanel.jsx — V6.2 FASES 3+5+6
 * Receita Real (Estimado/Confirmado/Recebido) + ROI Prioritizer +
 * Presidente IA em linguagem natural.
 *
 * V6.2 / Regra Máxima: o diretor responde em < 30s:
 *   1. Quanto dinheiro está em risco?
 *   2. Quanto dinheiro a IA gerou?
 *   3. Qual é o maior bloqueador?
 *   4. Qual ação gera mais retorno agora?
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const fmtBRL = (n) => (Number(n) || 0).toLocaleString("pt-BR",
  { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const fmtBRL2 = (n) => (Number(n) || 0).toLocaleString("pt-BR",
  { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
const fmtN = (n) => (Number(n) || 0).toLocaleString("pt-BR");

const PRIO_COLOR = { P0: "#ef4444", P1: "#fbbf24", P2: "#3b82f6" };

export default function RealRevenuePanel() {
  const [rev, setRev] = useState(null);
  const [prio, setPrio] = useState(null);
  const [pres, setPres] = useState(null);

  useEffect(() => {
    Promise.all([
      client.get("/ai-center/v62/revenue-real?days=30"),
      client.get("/ai-center/v62/roi-priorities"),
      client.get("/ai-center/v62/presidente-natural"),
    ]).then(([a, b, c]) => {
      setRev(a.data); setPrio(b.data); setPres(c.data);
    });
  }, []);

  if (!rev || !prio || !pres) return <div style={{ color: "#94a3b8" }}>
    Carregando Receita Real Center…
  </div>;

  return (
    <div data-testid="real-revenue-panel">
      <h2 style={{ color: "#f1f5f9", marginTop: 0, fontSize: 22 }}>
        Real Revenue Center · V6.2
      </h2>

      {/* Presidente IA narrativa */}
      <div data-testid="presidente-narrative" style={{
        background: "linear-gradient(135deg, #1e3a8a 0%, #020617 100%)",
        border: "1px solid #3b82f666",
        borderRadius: 14, padding: 20, marginBottom: 18,
      }}>
        <div style={{ color: "#93c5fd", fontSize: 11,
                       letterSpacing: 1.8, fontWeight: 800,
                       textTransform: "uppercase" }}>
          🎙️ Presidente IA · linguagem natural
        </div>
        <div style={{ color: "#f1f5f9", fontSize: 15,
                       lineHeight: 1.7, marginTop: 8 }}>
          {pres.narrative_lines.map((line, i) => (
            <p key={i} style={{ margin: "0 0 6px 0" }}>● {line}</p>
          ))}
        </div>
      </div>

      {/* 3 colunas: Estimado / Confirmado / Recebido */}
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "8px 0 10px 0" }}>
        Quanto a IA gerou de verdade? · últimos 30 dias
      </h3>
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                    gap: 14, marginBottom: 18 }}>
        <RevCard testid="rev-estimated" title="ESTIMADO"
                  sub="projeção em pipeline"
                  value={rev.estimated.BRL}
                  count={rev.estimated.count}
                  color="#94a3b8" />
        <RevCard testid="rev-confirmed" title="CONFIRMADO"
                  sub="ações executadas/dispatched"
                  value={rev.confirmed.BRL}
                  count={rev.confirmed.count}
                  color="#7dd3fc" />
        <RevCard testid="rev-received" title="RECEBIDO"
                  sub="outcome com R$ real"
                  value={rev.received.BRL}
                  count={rev.received.count}
                  color="#10b981" highlight />
      </div>

      <div data-testid="conversion-rate" style={{
        background: "#0f172a", border: "1px solid #1e293b",
        borderRadius: 8, padding: 14, marginBottom: 18,
        textAlign: "center",
      }}>
        <span style={{ color: "#94a3b8", fontSize: 11,
                          letterSpacing: 1.4,
                          textTransform: "uppercase" }}>
          Conversão Confirmado → Recebido
        </span>
        <div style={{ fontSize: 36, fontWeight: 900,
                       color: rev.conversion_pct >= 50 ? "#10b981"
                         : rev.conversion_pct >= 20 ? "#fbbf24"
                         : "#ef4444",
                       marginTop: 4 }}>
          {rev.conversion_pct}%
        </div>
      </div>

      {/* ROI Prioritizer */}
      <h3 style={{ color: "#7dd3fc", fontSize: 13, fontWeight: 700,
                   textTransform: "uppercase", letterSpacing: 1.2,
                   margin: "8px 0 10px 0" }}>
        ROI Prioritizer · onde a IA deve trabalhar primeiro
        <span style={{ color: "#94a3b8", fontWeight: 500,
                         marginLeft: 8, fontSize: 11 }}>
          ({fmtBRL(prio.total_BRL_at_stake)} em jogo)
        </span>
      </h3>
      <div data-testid="roi-list">
        {prio.items.length === 0 ? (
          <div style={{ color: "#10b981", padding: 14,
                          background: "#064e3b22",
                          borderRadius: 8 }}>
            ✓ Nenhuma ação pendente de alta prioridade.
          </div>
        ) : prio.items.slice(0, 12).map((it, i) => (
          <div key={i} data-testid={`roi-${i}`}
               style={{ background: "#0f172a",
                          border: `1px solid ${PRIO_COLOR[it.priority]}55`,
                          borderRadius: 8, padding: 14, marginBottom: 8,
                          display: "flex", gap: 12,
                          alignItems: "center" }}>
            <div style={{ minWidth: 28, textAlign: "center",
                            fontSize: 18, fontWeight: 900,
                            color: "#7dd3fc" }}>
              #{i + 1}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "#94a3b8",
                              fontWeight: 700, letterSpacing: 1.2,
                              textTransform: "uppercase" }}>
                {it.category}
              </div>
              <div style={{ fontSize: 14, fontWeight: 700,
                              color: "#f1f5f9", marginTop: 2 }}>
                {it.label}
              </div>
              <div style={{ fontSize: 12, color: "#cbd5e1",
                              marginTop: 4 }}>
                ↳ {it.action}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 10, color: "#94a3b8",
                              letterSpacing: 1.2,
                              textTransform: "uppercase" }}>
                ROI
              </div>
              <div style={{ fontSize: 20, fontWeight: 800,
                              color: "#10b981" }}>
                {fmtBRL(it.roi_BRL)}
              </div>
              <div style={{ marginTop: 4 }}>
                <span style={{
                  background: PRIO_COLOR[it.priority] + "33",
                  color: PRIO_COLOR[it.priority],
                  border: `1px solid ${PRIO_COLOR[it.priority]}`,
                  padding: "2px 8px", borderRadius: 999,
                  fontSize: 10, fontWeight: 800,
                  letterSpacing: 1.2,
                }}>{it.priority}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RevCard({ title, sub, value, count, color, testid, highlight }) {
  return (
    <div data-testid={testid} style={{
      background: highlight ? "#064e3b" : "#0f172a",
      border: `2px solid ${color}${highlight ? "" : "55"}`,
      borderRadius: 12, padding: 18,
      boxShadow: highlight ? `0 0 24px ${color}33` : "none",
    }}>
      <div style={{ fontSize: 11, color: "#94a3b8",
                     fontWeight: 800, letterSpacing: 2 }}>
        {title}
      </div>
      <div style={{ fontSize: 28, fontWeight: 900, color,
                     marginTop: 8 }}>
        {fmtBRL2(value)}
      </div>
      <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 6 }}>
        {count} eventos · {sub}
      </div>
    </div>
  );
}
