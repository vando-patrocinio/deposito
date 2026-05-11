import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Lightbulb, Trophy, TrendingUp, TrendingDown, Minus,
  Loader2, RefreshCw, Activity,
} from "lucide-react";

/* =============================================================
   Co-Pilot Ranking — quem aplica as dicas e quem tira proveito
   delta_csat positivo = atendente melhora CSAT quando segue a dica
============================================================= */

const PERIODS = [
  { id: 7, label: "7 dias" },
  { id: 14, label: "14 dias" },
  { id: 30, label: "30 dias" },
];

export default function CopilotRankingCard() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async () => {
    setRefreshing(true);
    try {
      const r = await api.copilotRankingWeekly(days);
      setData(r); setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setRefreshing(false); }
  }, [days]);

  useEffect(() => {
    reload();
    const id = setInterval(reload, 60000);
    return () => clearInterval(id);
  }, [reload]);

  const items = data?.items || [];
  const totals = data?.totals || {};

  return (
    <div data-testid="copilot-ranking-card" style={{
      padding: 20, borderRadius: 12,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
    }}>
      <div style={{
        display: "flex", alignItems: "flex-start",
        justifyContent: "space-between", gap: 12, marginBottom: 14, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6,
                            fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                            textTransform: "uppercase", letterSpacing: 0.6 }}>
            <Lightbulb size={11} strokeWidth={2.5} />
            Ranking Co-Pilot IA
          </div>
          <h3 style={{ fontSize: 16, fontWeight: 700, margin: "4px 0 0",
                          color: "var(--text-primary)", letterSpacing: "-0.012em" }}>
            Atendentes que aplicam dicas e ganham CSAT
          </h3>
          <p style={{ fontSize: 12, color: "var(--text-secondary)",
                        margin: "4px 0 0", maxWidth: 640, lineHeight: 1.5 }}>
            Mede adesão (dica → resposta humana em ≤
            {data?.apply_window_minutes || 30}min) e impacto
            (CSAT com hint × sem hint). Quem aplica e melhora CSAT sobe no ranking.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <PeriodTabs days={days} setDays={setDays} />
          <button onClick={reload} disabled={refreshing}
                  data-testid="copilot-ranking-refresh"
                  style={{
                    padding: "6px 10px", borderRadius: 6,
                    border: "1px solid var(--border-default)",
                    background: "var(--bg-surface)",
                    color: "var(--text-secondary)",
                    fontSize: 11, fontWeight: 600,
                    cursor: refreshing ? "wait" : "pointer",
                    display: "inline-flex", alignItems: "center", gap: 5,
                  }}>
            {refreshing
              ? <Loader2 size={11} style={{ animation: "spin 1s linear infinite" }} />
              : <RefreshCw size={11} />}
            Atualizar
          </button>
        </div>
      </div>

      {/* Totais */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 8, marginBottom: 14,
      }}>
        <TotalPill label="Dicas enviadas"
                    value={totals.hints_received ?? 0}
                    color="#d97706" icon={Lightbulb} />
        <TotalPill label="Dicas aplicadas"
                    value={totals.hints_applied ?? 0}
                    color="#16a34a" icon={Activity} />
        <TotalPill label="Adesão média"
                    value={`${Math.round((totals.avg_application_rate || 0) * 100)}%`}
                    color="#0ea5e9" icon={TrendingUp} />
      </div>

      {err && (
        <div style={{ padding: 10, borderRadius: 6, fontSize: 12,
                         background: "rgba(220,38,38,.08)", color: "#dc2626",
                         marginBottom: 12 }}>
          {err}
        </div>
      )}

      {/* Tabela */}
      {items.length === 0 ? (
        <div style={{
          padding: 32, textAlign: "center", borderRadius: 10,
          background: "var(--bg-surface-2)",
          border: "1px dashed var(--border-default)",
          fontSize: 12, color: "var(--text-muted)",
        }}>
          Nenhuma dica do Co-Pilot foi enviada no período selecionado.
          As dicas aparecem quando um atendente humano recebe nova mensagem
          do cliente em uma conversa atribuída.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 6 }}>
          {items.map((r, idx) => (
            <RankRow key={r.user_id} rank={idx + 1} row={r} />
          ))}
        </div>
      )}
    </div>
  );
}

function PeriodTabs({ days, setDays }) {
  return (
    <div style={{ display: "flex", gap: 2, padding: 2,
                     background: "var(--bg-surface-2)",
                     borderRadius: 6 }}>
      {PERIODS.map((p) => (
        <button key={p.id} onClick={() => setDays(p.id)}
                data-testid={`copilot-rank-period-${p.id}`}
                style={{
                  padding: "5px 10px", border: "none", borderRadius: 4,
                  background: days === p.id ? "var(--bg-surface)" : "transparent",
                  color: days === p.id ? "var(--text-primary)" : "var(--text-muted)",
                  fontSize: 11, fontWeight: 700, cursor: "pointer",
                  boxShadow: days === p.id ? "var(--shadow-sm)" : "none",
                }}>
          {p.label}
        </button>
      ))}
    </div>
  );
}

function TotalPill({ label, value, color, icon: Ico }) {
  return (
    <div style={{
      padding: "8px 10px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
      display: "flex", alignItems: "center", gap: 8,
    }}>
      <Ico size={14} strokeWidth={2} style={{ color }} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)",
                         textTransform: "uppercase", letterSpacing: 0.4 }}>
          {label}
        </div>
        <div style={{ fontSize: 16, fontWeight: 800, color: "var(--text-primary)",
                         fontFamily: "ui-monospace, monospace",
                         letterSpacing: "-0.02em", lineHeight: 1 }}>
          {value}
        </div>
      </div>
    </div>
  );
}

function RankRow({ rank, row }) {
  const scoreColor = row.score >= 75 ? "#16a34a"
                       : row.score >= 50 ? "#d97706"
                       : "#94a3b8";
  const apr = Math.round((row.application_rate || 0) * 100);
  const delta = row.delta_csat;
  const deltaIcon = delta == null ? Minus : (delta > 0.1 ? TrendingUp : (delta < -0.1 ? TrendingDown : Minus));
  const deltaColor = delta == null ? "#94a3b8"
                       : (delta > 0.1 ? "#16a34a"
                          : delta < -0.1 ? "#dc2626" : "#94a3b8");
  const Trophy_icon = rank === 1 ? Trophy : null;
  return (
    <div data-testid={`copilot-rank-row-${row.user_id}`}
          style={{
            display: "grid",
            gridTemplateColumns: "32px 1fr auto auto auto auto",
            alignItems: "center", gap: 10,
            padding: "10px 12px", borderRadius: 8,
            background: rank === 1
              ? "linear-gradient(90deg, rgba(217,119,6,.08), transparent)"
              : "var(--bg-surface)",
            border: `1px solid ${rank === 1 ? "rgba(217,119,6,.30)" : "var(--border-default)"}`,
          }}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%",
        background: scoreColor, color: "#fff",
        display: "grid", placeItems: "center",
        fontSize: 13, fontWeight: 800,
        fontFamily: "ui-monospace, monospace",
      }}>{rank}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <Avatar name={row.name} src={row.avatar} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700,
                          color: "var(--text-primary)",
                          letterSpacing: "-0.012em",
                          display: "flex", alignItems: "center", gap: 6 }}>
            {row.name}
            {Trophy_icon && <Trophy_icon size={13} color="#d97706" />}
          </div>
          <div style={{ fontSize: 10.5, color: "var(--text-muted)",
                          whiteSpace: "nowrap", overflow: "hidden",
                          textOverflow: "ellipsis", maxWidth: 280 }}>
            {row.email || row.user_id}
          </div>
        </div>
      </div>
      <Metric label="Recebidas"
                 value={row.hints_received}
                 color="#d97706" />
      <Metric label="Aplicadas"
                 value={`${row.hints_applied}`}
                 sub={`${apr}%`}
                 color={apr >= 60 ? "#16a34a" : apr >= 30 ? "#d97706" : "#94a3b8"} />
      <DeltaPill label="Δ CSAT"
                   value={delta == null ? "—" : (delta > 0 ? `+${delta}` : `${delta}`)}
                   icon={deltaIcon} color={deltaColor} />
      <ScorePill score={row.score} />
    </div>
  );
}

function Metric({ label, value, sub, color }) {
  return (
    <div style={{ textAlign: "right", minWidth: 80 }}>
      <div style={{ fontSize: 9, fontWeight: 700,
                       color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline",
                       justifyContent: "flex-end", gap: 4 }}>
        <div style={{ fontSize: 15, fontWeight: 800, color,
                         fontFamily: "ui-monospace, monospace",
                         letterSpacing: "-0.02em" }}>
          {value}
        </div>
        {sub && (
          <div style={{ fontSize: 11, color, fontWeight: 700,
                          fontFamily: "ui-monospace, monospace" }}>
            {sub}
          </div>
        )}
      </div>
    </div>
  );
}

function DeltaPill({ label, value, icon: Ico, color }) {
  return (
    <div style={{ textAlign: "right", minWidth: 80 }}>
      <div style={{ fontSize: 9, fontWeight: 700,
                       color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 3,
                       fontSize: 14, fontWeight: 800, color,
                       fontFamily: "ui-monospace, monospace",
                       letterSpacing: "-0.02em" }}>
        <Ico size={12} strokeWidth={2.5} />
        {value}
      </div>
    </div>
  );
}

function ScorePill({ score }) {
  const color = score >= 75 ? "#16a34a"
                  : score >= 50 ? "#d97706"
                  : "#94a3b8";
  return (
    <div data-testid="copilot-rank-score"
          style={{ textAlign: "right", minWidth: 60 }}>
      <div style={{ fontSize: 9, fontWeight: 700,
                       color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.4 }}>
        Score
      </div>
      <div style={{
        display: "inline-block",
        padding: "3px 10px", borderRadius: 999,
        background: `${color}15`, color,
        fontSize: 14, fontWeight: 800,
        fontFamily: "ui-monospace, monospace",
      }}>{score}</div>
    </div>
  );
}

function Avatar({ name, src, size = 32 }) {
  const initials = (name || "?").split(/\s+/)
    .filter(Boolean).slice(0, 2)
    .map((p) => p[0]).join("").toUpperCase() || "?";
  let h = 0;
  for (const c of (name || "")) h = (h * 31 + c.charCodeAt(0)) % 360;
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: src ? `url(${src}) center/cover` : `hsl(${h}, 55%, 55%)`,
      color: "#fff",
      display: "grid", placeItems: "center",
      fontSize: size * 0.38, fontWeight: 700,
      flexShrink: 0,
    }}>
      {!src && initials}
    </div>
  );
}
