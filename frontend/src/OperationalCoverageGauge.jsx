/**
 * OperationalCoverageGauge — Phase D · CEO 19/06/2026
 *
 * Gauge "Cobertura Operacional" + Score Breakdown + Timeline 12 semanas.
 * Inserido como card extra dentro do Watchtower Patrimônio Consolidado.
 *
 * Faixas (CEO):
 *   < 80 %    → Vermelho
 *   80-90 %   → Amarelo
 *   90-98 %   → Verde
 *   ≥ 98 %    → Excelência
 */
import React, { useEffect, useState, useCallback } from "react";
import { client } from "./api";
import QuarantinePromotion from "./QuarantinePromotion";

const fmtPct = (v) => v == null ? "—" : `${Number(v).toFixed(2)}%`;
const fmtNum = (v) => v == null ? "—" : Number(v).toFixed(2);

function bandFor(pct) {
  if (pct == null) return { label: "—", color: "slate", tier: "slate" };
  if (pct >= 98) return {
    label: "EXCELÊNCIA",
    color: "text-emerald-200 bg-emerald-500/10 border-emerald-500/40",
    bar: "bg-emerald-400",
  };
  if (pct >= 90) return {
    label: "VERDE",
    color: "text-emerald-300 bg-emerald-500/10 border-emerald-500/30",
    bar: "bg-emerald-500",
  };
  if (pct >= 80) return {
    label: "AMARELO",
    color: "text-amber-300 bg-amber-500/10 border-amber-500/30",
    bar: "bg-amber-500",
  };
  return {
    label: "VERMELHO",
    color: "text-rose-300 bg-rose-500/10 border-rose-500/30",
    bar: "bg-rose-500",
  };
}

export default function OperationalCoverageGauge() {
  const [latest, setLatest] = useState(null);
  const [breakdown, setBreakdown] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [showQuarantine, setShowQuarantine] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const [bRes, tRes] = await Promise.all([
        client.get("/sprint5/audit-operacional/score-breakdown"),
        client.get("/sprint5/audit-operacional/timeline?weeks=12"),
      ]);
      setBreakdown(bRes.data);
      setLatest(bRes.data);
      setTimeline(tRes.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao carregar");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  if (loading && !latest) {
    return (
      <div
        className="rounded-2xl border border-slate-700 bg-slate-900/40 p-6"
        data-testid="opcov-loading"
      >
        <div className="text-slate-400 text-sm animate-pulse">
          Carregando Cobertura Operacional…
        </div>
      </div>
    );
  }
  if (err) {
    return (
      <div
        className="rounded-2xl border border-rose-500/40 bg-rose-950/30 p-6"
        data-testid="opcov-error"
      >
        <div className="text-rose-300 text-sm font-semibold mb-1">
          Erro ao carregar Cobertura Operacional
        </div>
        <div className="text-rose-200 text-xs">{String(err)}</div>
        <button
          onClick={fetchAll}
          className="mt-3 px-3 py-1 bg-rose-500/20 hover:bg-rose-500/30 rounded text-xs font-semibold"
          data-testid="opcov-retry-btn"
        >
          Tentar novamente
        </button>
      </div>
    );
  }

  if (!breakdown || breakdown.empty) {
    return (
      <div
        className="rounded-2xl border border-slate-700 bg-slate-900/40 p-6"
        data-testid="opcov-empty"
      >
        <div className="text-slate-400 text-sm">
          Nenhuma auditoria semanal executada ainda.
        </div>
      </div>
    );
  }

  const coverageComp = (breakdown.breakdown?.components || [])
    .find((c) => c.key === "coverage");
  const coverage = coverageComp?.value_pct ?? 0;
  const target = coverageComp?.target_pct ?? 95;
  const band = bandFor(coverage);
  const score = breakdown.score ?? 0;
  const status = breakdown.status ?? "—";
  const components = breakdown.breakdown?.components || [];
  const points = timeline?.points || [];
  const sum = timeline?.summary;
  // Min/Max para gráfico
  const ys = points.map((p) => p.score).filter((s) => s != null);
  const minY = Math.min(...(ys.length ? ys : [0]));
  const maxY = Math.max(...(ys.length ? ys : [10]), 10);

  return (
    <div className="space-y-4" data-testid="opcov-root">
      {/* GAUGE PRINCIPAL */}
      <div
        className={`rounded-2xl border p-6 ${band.color}`}
        data-testid="opcov-card-gauge"
      >
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div className="flex-1 min-w-[280px]">
            <div className="text-xs uppercase tracking-widest font-mono opacity-80">
              Cobertura Operacional · Phase D
            </div>
            <div
              className="text-7xl font-bold tabular-nums mt-1"
              data-testid="opcov-cobertura-pct"
            >
              {fmtPct(coverage)}
            </div>
            <div className="text-sm opacity-80 mt-1">
              Meta: {fmtPct(target)} · Status:{" "}
              <span data-testid="opcov-band-label" className="font-semibold">
                {band.label}
              </span>
            </div>
            {/* Barra horizontal com faixas */}
            <div className="mt-4 relative h-4 rounded-full bg-slate-800 overflow-hidden">
              <div
                className={`h-full ${band.bar} transition-all duration-500`}
                style={{ width: `${Math.min(coverage, 100)}%` }}
                data-testid="opcov-bar-fill"
              />
              {/* Marcadores 80, 90, 98 */}
              {[80, 90, 98].map((m) => (
                <div
                  key={m}
                  className="absolute top-0 h-full border-l border-slate-500/60"
                  style={{ left: `${m}%` }}
                  title={`${m}%`}
                />
              ))}
            </div>
            <div className="flex justify-between text-[10px] opacity-60 mt-1 font-mono">
              <span>0%</span>
              <span style={{ marginLeft: "30%" }}>80</span>
              <span>90</span>
              <span>98</span>
              <span>100%</span>
            </div>
          </div>
          <div className="text-right min-w-[160px]">
            <div className="text-xs uppercase tracking-widest opacity-80">
              Score Auditoria
            </div>
            <div
              className="text-4xl font-bold tabular-nums"
              data-testid="opcov-score"
            >
              {fmtNum(score)}
              <span className="text-2xl opacity-60">/10</span>
            </div>
            <div
              className="text-xs opacity-80 mt-1"
              data-testid="opcov-status"
            >
              {status}
            </div>
            <div className="text-[10px] opacity-60 mt-2 font-mono">
              {breakdown.week_iso}
            </div>
          </div>
        </div>
      </div>

      {/* SCORE BREAKDOWN */}
      <div
        className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6"
        data-testid="opcov-card-breakdown"
      >
        <div className="text-xs uppercase tracking-widest font-mono text-slate-400 mb-3">
          O que falta para chegar em 10/10
        </div>
        <div className="space-y-2">
          {components.map((c) => {
            const blocking = (c.penalty || 0) < 0;
            return (
              <div
                key={c.key}
                className={`flex items-center justify-between gap-3 rounded-lg px-3 py-2 ${blocking ? "bg-rose-500/5 border border-rose-500/20" : "bg-emerald-500/5 border border-emerald-500/20"}`}
                data-testid={`opcov-comp-${c.key}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-slate-200 truncate">
                    {c.label}
                  </div>
                  <div className="text-[11px] text-slate-400 font-mono">
                    {c.value_pct != null
                      ? `${fmtPct(c.value_pct)} · meta ${fmtPct(c.target_pct)}`
                      : `${c.value ?? "—"} · meta ${c.target ?? 0}`}
                  </div>
                </div>
                <div className={`tabular-nums font-bold text-sm ${blocking ? "text-rose-300" : "text-emerald-300"}`}>
                  {(c.penalty ?? 0) >= 0 ? "0.00" : c.penalty.toFixed(2)}
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 pt-3 border-t border-slate-700 flex justify-between text-sm">
          <span className="text-slate-400">Total de penalidades</span>
          <span
            className="font-bold tabular-nums text-rose-300"
            data-testid="opcov-total-penalty"
          >
            {fmtNum(breakdown.breakdown?.total_penalty)}
          </span>
        </div>
      </div>

      {/* TIMELINE 12 SEMANAS */}
      <div
        className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6"
        data-testid="opcov-card-timeline"
      >
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs uppercase tracking-widest font-mono text-slate-400">
            Evolução · últimas 12 semanas
          </div>
          {sum && (
            <div className="text-xs text-slate-400 font-mono">
              Δ score:{" "}
              <span
                className={(sum.score_delta || 0) >= 0
                  ? "text-emerald-300"
                  : "text-rose-300"}
                data-testid="opcov-delta-score"
              >
                {(sum.score_delta || 0) >= 0 ? "+" : ""}
                {fmtNum(sum.score_delta)}
              </span>
              {" · "}
              Δ cobertura:{" "}
              <span
                className={(sum.cobertura_delta_pp || 0) >= 0
                  ? "text-emerald-300"
                  : "text-rose-300"}
                data-testid="opcov-delta-cov"
              >
                {(sum.cobertura_delta_pp || 0) >= 0 ? "+" : ""}
                {fmtNum(sum.cobertura_delta_pp)} pp
              </span>
            </div>
          )}
        </div>
        {points.length === 0 ? (
          <div className="text-sm text-slate-500 py-4 text-center">
            Aguardando histórico (rodar Phase A semanalmente)
          </div>
        ) : (
          <div className="flex items-end gap-2 h-32" data-testid="opcov-timeline-bars">
            {points.map((p, idx) => {
              const sc = p.score ?? 0;
              const heightPct = Math.max(
                ((sc - minY) / Math.max(maxY - minY, 0.1)) * 100, 8);
              const b = bandFor(p.cobertura_operacional_pct);
              return (
                <div
                  key={`${p.week_iso}-${idx}`}
                  className="flex-1 flex flex-col items-center gap-1 min-w-0"
                  data-testid={`opcov-tl-${p.week_iso}`}
                >
                  <div className="text-[10px] tabular-nums text-slate-300 font-mono">
                    {fmtNum(sc)}
                  </div>
                  <div
                    className={`w-full ${b.bar} rounded-t opacity-90`}
                    style={{ height: `${heightPct}%` }}
                    title={`${p.week_iso} · ${fmtPct(p.cobertura_operacional_pct)}`}
                  />
                  <div className="text-[9px] text-slate-500 font-mono truncate w-full text-center">
                    {p.week_iso?.replace(/^\d{4}-/, "")}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* MUTIRÃO DE QUARENTENA — Phase D add-on */}
      <div
        className="rounded-2xl border border-slate-700 bg-slate-900/60 p-4"
        data-testid="opcov-card-quarantine"
      >
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-widest font-mono text-slate-400">
              Mutirão de Quarentena
            </div>
            <div className="text-sm text-slate-300 mt-1">
              Suba a cobertura aprovando/rejeitando manualmente as ONUs que
              não foram promovidas automaticamente.
            </div>
          </div>
          <button
            onClick={() => setShowQuarantine((s) => !s)}
            className="px-4 py-2 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-200 text-sm font-semibold"
            data-testid="opcov-toggle-quarantine-btn"
          >
            {showQuarantine ? "Ocultar" : "Promover Quarentena →"}
          </button>
        </div>
        {showQuarantine && (
          <div className="mt-4 pt-4 border-t border-slate-700">
            <QuarantinePromotion />
          </div>
        )}
      </div>
    </div>
  );
}
