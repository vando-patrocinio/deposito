/* WarRoomPanel.js — Sprint 7 / iter226
   Sala de Guerra do Presidente IA — 12 indicadores executivos. */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  Activity, AlertTriangle, Database, DollarSign, Gauge, RefreshCw,
  ShieldAlert, TrendingUp, Users, Wifi, Zap, Brain,
} from "lucide-react";

const C = {
  bg: "#0b1220", panel: "#101a2e", card: "#152238",
  ink: "#e2e8f0", muted: "#94a3b8",
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#22c55e", red: "#ef4444", amber: "#f59e0b",
  blue: "#3b82f6", border: "#1e293b",
};

const STATUS_COLOR = {
  saudavel: C.green, atencao: C.amber, critico: C.red, alerta: C.red,
};

export default function WarRoomPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const fetchData = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api._client.get("/presidente-ia/warroom");
      setData(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Erro");
    } finally { setLoading(false); }
  };

  useEffect(() => {
    fetchData();
    const i = setInterval(fetchData, 30000);
    return () => clearInterval(i);
  }, []);

  const exec = data?.executive;
  const dq = data?.data_quality;
  const alerts = data?.critical_alerts || [];
  const scores = exec?.scores || {};

  return (
    <div data-testid="warroom-panel" style={{
      background: C.bg, color: C.ink, minHeight: "100vh", padding: 24,
    }}>
      {/* Header */}
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 20, flexWrap: "wrap",
        gap: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Brain size={32} color={STATUS_COLOR[exec?.status] || C.purple} />
          <div>
            <h1 style={{
              margin: 0, fontSize: 22, fontWeight: 800,
              letterSpacing: -0.5,
            }} data-testid="warroom-title">
              Sala de Guerra — Presidente IA Autônomo
            </h1>
            <div style={{
              fontSize: 12, color: C.muted, marginTop: 4,
            }}>
              Sistema Nervoso Corporativo · Executivo Digital 24/7
            </div>
          </div>
        </div>
        <button onClick={fetchData} disabled={loading}
          data-testid="warroom-refresh"
          style={btnStyle(C.blue)}>
          <RefreshCw size={14} style={{
            animation: loading ? "spin 1s linear infinite" : "none",
          }} /> Atualizar
        </button>
      </div>

      {err && (
        <div data-testid="warroom-error" style={{
          background: "#7f1d1d", color: "#fee", padding: 12,
          borderRadius: 8, marginBottom: 16, fontSize: 13,
        }}>⚠ {err}</div>
      )}

      {/* Score central da empresa */}
      <div data-testid="exec-score-card" style={{
        background: C.panel, padding: 24, borderRadius: 12,
        marginBottom: 18,
        borderTop: `4px solid ${STATUS_COLOR[exec?.status] || C.muted}`,
        textAlign: "center",
      }}>
        <div style={{
          fontSize: 11, color: C.muted, fontWeight: 700,
          textTransform: "uppercase", letterSpacing: 1,
        }}>Saúde Geral da Empresa</div>
        <div style={{
          fontSize: 64, fontWeight: 900,
          color: STATUS_COLOR[exec?.status] || C.muted, marginTop: 4,
        }} data-testid="exec-score-value">
          {exec?.overall_score ?? "—"}
          <span style={{ fontSize: 24, color: C.muted }}>/100</span>
        </div>
        <div style={{
          fontSize: 14, fontWeight: 700,
          color: STATUS_COLOR[exec?.status] || C.muted,
          textTransform: "uppercase", letterSpacing: 2,
        }}>{exec?.status || "—"}</div>
      </div>

      {/* 5 scores por área */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
        gap: 12, marginBottom: 18,
      }}>
        <ScoreCard icon={<Database size={18} />} label="Qualidade Dados"
          value={scores.dados} testid="score-dados" />
        <ScoreCard icon={<Activity size={18} />} label="Operacional"
          value={scores.operacional} testid="score-operacional" />
        <ScoreCard icon={<TrendingUp size={18} />} label="Comercial"
          value={scores.comercial} testid="score-comercial" />
        <ScoreCard icon={<DollarSign size={18} />} label="Financeiro"
          value={scores.financeiro} testid="score-financeiro" />
        <ScoreCard icon={<ShieldAlert size={18} />} label="Segurança"
          value={scores.seguranca} testid="score-seguranca" />
      </div>

      {/* Cards de atividade hoje */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12, marginBottom: 18,
      }}>
        <Card icon={<AlertTriangle size={18} />}
          label="Alertas críticos" value={alerts.length}
          color={alerts.length ? C.red : C.green} testid="card-alerts" />
        <Card icon={<Brain size={18} />} label="Decisões hoje"
          value={data?.decisions_today ?? 0}
          color={C.purple} testid="card-decisions" />
        <Card icon={<Zap size={18} />} label="Ações hoje"
          value={data?.actions_today ?? 0}
          color={C.orange} testid="card-actions" />
        <Card icon={<Database size={18} />} label="Score de dados"
          value={dq?.score ?? "—"} color={C.blue}
          testid="card-data-quality" />
      </div>

      {/* Alertas críticos */}
      {alerts.length > 0 && (
        <div data-testid="alerts-row" style={{
          background: C.panel, border: `1px solid ${C.red}`,
          borderRadius: 12, padding: 16, marginBottom: 18,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            fontSize: 13, fontWeight: 800, color: C.red,
            marginBottom: 10,
          }}><Zap size={16} /> Alertas do Sistema Nervoso</div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 10,
          }}>
            {alerts.map((a, i) => (
              <div key={i} data-testid={`alert-${i}`} style={{
                background: C.card, padding: 10, borderRadius: 6,
                borderLeft: `4px solid ${
                  STATUS_COLOR[a.severity] || C.amber}`,
              }}>
                <div style={{ fontSize: 12, fontWeight: 800 }}>
                  {a.title}
                </div>
                <div style={{
                  fontSize: 11, color: C.muted, marginTop: 4,
                }}>{a.message}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Issues de Data Quality */}
      {dq?.issues && (
        <div data-testid="data-quality-card" style={{
          background: C.panel, padding: 14, borderRadius: 10,
        }}>
          <div style={{
            fontSize: 12, fontWeight: 700, color: C.muted,
            textTransform: "uppercase", marginBottom: 10,
          }}>Qualidade dos dados</div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 8,
          }}>
            {dq.issues.map((i, idx) => (
              <div key={idx} style={{
                background: C.card, padding: 8, borderRadius: 6,
              }} data-testid={`dq-issue-${i.key}`}>
                <div style={{
                  fontSize: 11, color: C.muted,
                }}>{i.label}</div>
                <div style={{
                  fontSize: 16, fontWeight: 800, marginTop: 2,
                  color: i.pct_clean >= 90 ? C.green
                    : i.pct_clean >= 70 ? C.amber : C.red,
                }}>{i.pct_clean}% limpos</div>
                <div style={{ fontSize: 10, color: C.muted }}>
                  {i.bad_count} de {i.total_count} com problema
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <style>{`@keyframes spin {
        from { transform: rotate(0); } to { transform: rotate(360deg); }
      }`}</style>
    </div>
  );
}

function ScoreCard({ icon, label, value, testid }) {
  const color = value >= 85 ? C.green : value >= 65 ? C.amber : C.red;
  return (
    <div data-testid={testid} style={{
      background: C.panel, padding: 14, borderRadius: 10,
      borderLeft: `4px solid ${color}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        color: C.muted, fontSize: 11, fontWeight: 700,
        textTransform: "uppercase",
      }}><span style={{ color }}>{icon}</span>{label}</div>
      <div style={{
        marginTop: 6, fontSize: 28, fontWeight: 800, color,
      }}>{value ?? "—"}</div>
    </div>
  );
}

function Card({ icon, label, value, color, testid }) {
  return (
    <div data-testid={testid} style={{
      background: C.panel, padding: 14, borderRadius: 10,
      borderTop: `3px solid ${color}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        color: C.muted, fontSize: 11, fontWeight: 700,
        textTransform: "uppercase",
      }}><span style={{ color }}>{icon}</span>{label}</div>
      <div style={{
        marginTop: 8, fontSize: 26, fontWeight: 800,
      }}>{value ?? "—"}</div>
    </div>
  );
}

const btnStyle = (bg) => ({
  background: bg, color: "#fff", border: 0,
  padding: "6px 12px", borderRadius: 6, cursor: "pointer",
  fontSize: 12, fontWeight: 700, display: "inline-flex",
  alignItems: "center", gap: 6,
});
