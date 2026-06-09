/**
 * DataQualityPanel.jsx — FASE 2 da Constituição V3.0
 *
 * Responde sem intervenção humana:
 *   1. Qual a qualidade dos dados hoje?
 *   2. O que está faltando?
 *   3. Quanto dinheiro isso impacta?
 *   4. O que precisa ser corrigido primeiro?
 *
 * Consome /api/ai-center/data-quality/*
 */
import React, { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  Cell,
} from "recharts";
import { client } from "@/api";


const LEVEL_COLOR = {
  SAUDAVEL: "#10b981",
  AMARELO: "#facc15",
  VERMELHO: "#f97316",
  INCIDENTE_EXECUTIVO: "#ef4444",
};

const DOMAIN_COLOR = {
  clientes: "#3b82f6",
  rede: "#a855f7",
  financeiro: "#10b981",
  whatsapp: "#22c55e",
  smartolt: "#0ea5e9",
  consistencia: "#f59e0b",
};

const DOMAIN_LABEL = {
  clientes: "Clientes",
  rede: "Rede",
  financeiro: "Financeiro",
  whatsapp: "WhatsApp",
  smartolt: "SmartOLT",
  consistencia: "Consistência",
};

function fmtBRL(n) {
  return (n || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2,
  });
}

function Pill({ level }) {
  const c = LEVEL_COLOR[level] || "#64748b";
  return (
    <span
      data-testid="dq-level-pill"
      style={{
        background: c + "33", color: c, padding: "4px 10px",
        borderRadius: 999, fontSize: 11, fontWeight: 700,
        letterSpacing: 1, textTransform: "uppercase",
      }}
    >
      {level}
    </span>
  );
}


function GaugeCard({ score, level }) {
  const c = LEVEL_COLOR[level] || "#64748b";
  return (
    <div
      data-testid="overall-gauge"
      style={{
        background: "linear-gradient(140deg, #020617 0%, #0b1220 100%)",
        border: `2px solid ${c}66`,
        borderRadius: 16, padding: 28,
        boxShadow: `0 8px 32px ${c}33`,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center",
                    justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: 11, color: "#64748b",
                        textTransform: "uppercase", letterSpacing: 1.4,
                        fontWeight: 600 }}>
            Score Geral · Data Quality
          </div>
          <div style={{ fontSize: 60, fontWeight: 900, color: "#f1f5f9",
                        lineHeight: 1, marginTop: 8 }}>
            {score?.toFixed(1)}<span style={{ fontSize: 24, color: c }}>%</span>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <Pill level={level} />
          <div style={{ marginTop: 12, fontSize: 11, color: "#475569" }}>
            Meta: <span style={{ color: "#10b981", fontWeight: 700 }}>95%</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function DomainCard({ name, info }) {
  const color = DOMAIN_COLOR[name];
  return (
    <div
      data-testid={`domain-card-${name}`}
      style={{
        background: "#0f172a", border: `1px solid ${color}33`,
        borderRadius: 12, padding: 18, color: "#e2e8f0",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center" }}>
        <div style={{ fontSize: 12, color: "#64748b",
                      textTransform: "uppercase", letterSpacing: 1.2,
                      fontWeight: 600 }}>
          {DOMAIN_LABEL[name]}
        </div>
        <div style={{ width: 6, height: 24, background: color,
                      borderRadius: 3 }} />
      </div>
      <div style={{ fontSize: 30, fontWeight: 800, color: "#f1f5f9",
                    marginTop: 6, lineHeight: 1.1 }}>
        {info?.score?.toFixed(1)}%
      </div>
      {info?.indicators && (
        <div style={{ marginTop: 12, fontSize: 11, color: "#94a3b8" }}>
          {Object.entries(info.indicators).map(([k, v]) => (
            <div key={k} style={{ display: "flex",
                                   justifyContent: "space-between",
                                   marginBottom: 2 }}>
              <span>{k.replace(/_pct$/, "").replace(/_/g, " ")}</span>
              <span style={{ color: v >= 95 ? "#10b981"
                                  : v >= 80 ? "#facc15" : "#f97316",
                              fontWeight: 600 }}>
                {typeof v === "number" ? `${v.toFixed(1)}%` : v}
              </span>
            </div>
          ))}
        </div>
      )}
      {info?.issues && Object.values(info.issues).some((v) => v > 0) && (
        <div style={{ marginTop: 10, padding: 8,
                      background: "#1e1b1b", borderRadius: 6,
                      fontSize: 10, color: "#fca5a5" }}>
          {Object.entries(info.issues)
            .filter(([, v]) => v > 0)
            .slice(0, 3)
            .map(([k, v]) => (
              <div key={k}>{k}: <b>{v}</b></div>
            ))}
        </div>
      )}
    </div>
  );
}


export default function DataQualityPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [backfilling, setBackfilling] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await client.get("/ai-center/data-quality/score");
      setData(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  const runBackfill = async () => {
    setBackfilling(true);
    try {
      const r = await client.post("/ai-center/data-quality/run-backfill");
      alert(
        `Backfill OK: +${r.data.subscribers_updated} subs. ` +
        `Score ${r.data.before.overall_score}% → ${r.data.after.overall_score}% ` +
        `(Δ ${r.data.delta > 0 ? "+" : ""}${r.data.delta})`
      );
      load();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBackfilling(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading && !data) {
    return (
      <div style={{ padding: 40, color: "#94a3b8", textAlign: "center" }}>
        Carregando Data Quality…
      </div>
    );
  }
  if (error) {
    return (
      <div style={{ padding: 40, background: "#7f1d1d",
                    color: "#fee2e2", borderRadius: 8 }}>
        {error}
      </div>
    );
  }
  if (!data) return null;

  const domainBars = Object.entries(data.domains).map(([k, v]) => ({
    name: DOMAIN_LABEL[k],
    score: v.score,
    color: DOMAIN_COLOR[k],
  }));

  const rev = data.revenue_impact || {};

  return (
    <div data-testid="data-quality-panel"
         style={{ padding: 24, background: "#020617", minHeight: "100vh" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ color: "#f1f5f9", fontSize: 26, fontWeight: 800,
                       margin: 0, letterSpacing: -0.5 }}>
            Data Quality IA
          </h1>
          <div style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>
            Fase 2 da Constituição V3.0 · Meta corporativa: 95%
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            data-testid="reload-btn"
            onClick={load}
            style={{ background: "#0ea5e9", color: "#fff",
                     border: "none", borderRadius: 8,
                     padding: "8px 14px", fontSize: 13,
                     cursor: "pointer", fontWeight: 600 }}>
            Atualizar
          </button>
          <button
            data-testid="run-backfill-btn"
            onClick={runBackfill}
            disabled={backfilling}
            style={{ background: backfilling ? "#475569" : "#10b981",
                     color: "#fff", border: "none", borderRadius: 8,
                     padding: "8px 14px", fontSize: 13,
                     cursor: backfilling ? "wait" : "pointer",
                     fontWeight: 600 }}>
            {backfilling ? "Backfilling…" : "Rodar Backfill"}
          </button>
        </div>
      </div>

      <div style={{ display: "grid",
                    gridTemplateColumns: "minmax(360px, 1fr) 2fr",
                    gap: 16, marginBottom: 24 }}>
        <GaugeCard score={data.overall_score}
                   level={data.overall_level} />

        <div data-testid="answers-card"
             style={{ background: "#0f172a",
                      border: "1px solid #1e293b",
                      borderRadius: 12, padding: 22 }}>
          <div style={{ fontSize: 11, color: "#7dd3fc",
                        textTransform: "uppercase", letterSpacing: 1.4,
                        marginBottom: 12, fontWeight: 700 }}>
            Diagnóstico Autônomo do Presidente IA
          </div>
          {Object.entries(data.answers || {}).map(([k, v]) => (
            <div key={k}
                 data-testid={`answer-${k}`}
                 style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: "#64748b",
                            textTransform: "uppercase", letterSpacing: 1 }}>
                {k.replace(/_/g, " ")}
              </div>
              <div style={{ fontSize: 14, color: "#e2e8f0", marginTop: 2 }}>
                {v}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 14, marginBottom: 24 }}>
        {Object.entries(data.domains).map(([k, v]) => (
          <DomainCard key={k} name={k} info={v} />
        ))}
      </div>

      <div data-testid="bar-card"
           style={{ background: "#0f172a", border: "1px solid #1e293b",
                    borderRadius: 12, padding: 20, marginBottom: 24 }}>
        <div style={{ fontSize: 13, color: "#7dd3fc", marginBottom: 12,
                      fontWeight: 600 }}>
          Score por Domínio
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={domainBars}>
            <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
            <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]}
                   tickFormatter={(v) => `${v}%`} />
            <Tooltip
              contentStyle={{ background: "#0f172a",
                              border: "1px solid #1e293b" }}
              formatter={(v) => `${v}%`} />
            <Bar dataKey="score" radius={[6, 6, 0, 0]}>
              {domainBars.map((d, i) => (
                <Cell key={i} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div data-testid="revenue-impact-card"
           style={{ background: "linear-gradient(140deg, #1e1b1b 0%, #0f172a 100%)",
                    border: "1px solid #ef444466",
                    borderRadius: 12, padding: 22 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "baseline" }}>
          <div style={{ fontSize: 12, color: "#fca5a5",
                        textTransform: "uppercase", letterSpacing: 1.4,
                        fontWeight: 700 }}>
            Revenue Impact · R$ represados por dados ruins
          </div>
          <span style={{ color: "#64748b", fontSize: 11 }}>
            {rev.actionable_pct}% acionável
          </span>
        </div>
        <div style={{ display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                      gap: 16, marginTop: 14 }}>
          <div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>
              Represado (R$)
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: "#fca5a5" }}>
              {fmtBRL(rev.locked_BRL)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>
              Carteira overdue total
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: "#cbd5e1" }}>
              {fmtBRL(rev.total_overdue_BRL)}
            </div>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              {rev.total_overdue_count} faturas
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>
              Faturas bloqueadas
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: "#fbbf24" }}>
              {rev.locked_count}
            </div>
          </div>
        </div>
        {rev.reasons && Object.keys(rev.reasons).length > 0 && (
          <div style={{ marginTop: 14, paddingTop: 14,
                        borderTop: "1px solid #1e293b" }}>
            <div style={{ fontSize: 11, color: "#94a3b8",
                          marginBottom: 6 }}>
              Causa-raiz por incidência:
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {Object.entries(rev.reasons).map(([k, v]) => (
                <div key={k}
                     data-testid={`reason-${k}`}
                     style={{ background: "#1e293b",
                              padding: "4px 10px", borderRadius: 6,
                              fontSize: 12 }}>
                  <span style={{ color: "#94a3b8" }}>{k}:</span>{" "}
                  <b style={{ color: "#fca5a5" }}>{v}</b>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div style={{ marginTop: 28, fontSize: 11, color: "#475569",
                    textAlign: "center" }}>
        Cada chamada deste painel grava um snapshot histórico em
        <code style={{ color: "#7dd3fc" }}> data_quality_snapshots</code>.
        Variação ≥ 1% emite DATA_QUALITY_DROP/RECOVERY no Event Bus.
      </div>
    </div>
  );
}
