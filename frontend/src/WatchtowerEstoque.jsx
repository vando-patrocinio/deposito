/**
 * Watchtower Estoque — Dashboard Patrimonial Executivo
 *
 * Sprint 1 (CEO 16/02/2026): patrimônio Ligo em 10 segundos.
 * 4 cards: Patrimônio · Operação · Qualidade · Alertas.
 *
 * Não importa lucide-react (já presente no projeto). Usa apenas Tailwind.
 */
import React, { useEffect, useState, useCallback } from "react";
import { client } from "./api";

const fmtBRL = (v) => {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 2,
  });
};
const fmtPct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
const fmtInt = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR"));

const GRADE_META = {
  A: { label: "Grade A", desc: "Valor por NF", color: "text-emerald-300", bar: "bg-emerald-500" },
  B: { label: "Grade B", desc: "Média ponderada", color: "text-sky-300", bar: "bg-sky-500" },
  C: { label: "Grade C", desc: "Modelo canônico", color: "text-amber-300", bar: "bg-amber-500" },
  D: { label: "Grade D", desc: "Referência mercado", color: "text-orange-300", bar: "bg-orange-500" },
  F: { label: "Grade F", desc: "Sem dado confiável", color: "text-rose-300", bar: "bg-rose-500" },
};

const LOCATION_META = {
  empresa: { label: "Empresa", icon: "🏢" },
  tecnico: { label: "Técnicos", icon: "🔧" },
  cliente: { label: "Clientes", icon: "👥" },
  defeito: { label: "Defeito", icon: "⚠️" },
  descarte: { label: "Descarte", icon: "🗑️" },
};

const ALERT_META = {
  autosn: { label: "AUTOSN", desc: "MAC/SN auto-gerados", color: "border-amber-500/40 bg-amber-500/10" },
  needs_review: { label: "Needs Review", desc: "Valuation precisa revisão humana", color: "border-rose-500/40 bg-rose-500/10" },
  sem_trilha: { label: "Sem Trilha", desc: "ONTs sem genesis canônico (pré-R1.4)", color: "border-slate-500/40 bg-slate-500/10" },
  reconciliacoes_30d: { label: "Reconciliações 30d", desc: "Correções SmartOLT (cadastro)", color: "border-sky-500/40 bg-sky-500/10" },
  duplicadas: { label: "Duplicadas", desc: "Mesma MAC em múltiplos docs", color: "border-rose-600/40 bg-rose-600/10" },
};

const Sparkline = ({ data = [], width = 220, height = 48 }) => {
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.cum_value || 0));
  const min = Math.min(...data.map((d) => d.cum_value || 0));
  const range = max - min || 1;
  const pts = data.map((d, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((d.cum_value - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={width} height={height} className="overflow-visible" data-testid="watchtower-sparkline">
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-emerald-400"
      />
      {data.map((d, i) => {
        const x = (i / (data.length - 1)) * width;
        const y = height - ((d.cum_value - min) / range) * height;
        return <circle key={i} cx={x} cy={y} r="1.5" className="fill-emerald-400" />;
      })}
    </svg>
  );
};

export default function WatchtowerEstoque() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [lastFetch, setLastFetch] = useState(null);

  const fetchSummary = useCallback(async (fresh = false, isInitial = false) => {
    if (!isInitial) setLoading(true);
    setErr(null);
    try {
      const res = await client.get(`/watchtower/estoque/summary${fresh ? "?fresh=true" : ""}`);
      setData(res.data);
      setLastFetch(new Date());
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao carregar Watchtower");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Defer to next tick — evita set-state-in-effect ao montar.
    const t = setTimeout(() => fetchSummary(false, true), 0);
    return () => clearTimeout(t);
  }, [fetchSummary]);

  if (loading && !data) {
    return (
      <div className="min-h-[400px] flex items-center justify-center text-slate-400" data-testid="watchtower-loading">
        <div className="animate-pulse">Carregando Watchtower Estoque…</div>
      </div>
    );
  }
  if (err) {
    return (
      <div className="min-h-[400px] flex items-center justify-center" data-testid="watchtower-error">
        <div className="bg-rose-950/40 border border-rose-500/30 text-rose-200 px-6 py-4 rounded-lg max-w-md">
          <div className="font-bold mb-1">Erro ao carregar Watchtower</div>
          <div className="text-sm">{String(err)}</div>
          <button
            onClick={() => fetchSummary(true)}
            data-testid="watchtower-retry-btn"
            className="mt-3 px-3 py-1.5 bg-rose-500/20 hover:bg-rose-500/30 rounded text-xs font-semibold"
          >Tentar novamente</button>
        </div>
      </div>
    );
  }

  const p = data?.patrimonio || {};
  const op = data?.operacao || {};
  const q = data?.qualidade || {};
  const a = data?.alertas || {};
  const deltaPos = (p.delta_mom_value || 0) >= 0;

  return (
    <div className="space-y-6 p-6 bg-slate-950 min-h-screen text-slate-100" data-testid="watchtower-estoque-root">
      {/* Header */}
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-widest text-emerald-400/80 font-mono">Dashboard Executivo · Patrimônio</div>
          <h1 className="text-3xl md:text-4xl font-bold mt-1">Watchtower Estoque</h1>
          <div className="text-sm text-slate-400 mt-1">
            Patrimônio da Ligo em tempo real · {data?.company_id} ·{" "}
            <span className="text-slate-500">
              atualizado {lastFetch ? lastFetch.toLocaleTimeString("pt-BR") : "—"}
              {data?.cache_hit && <span className="ml-1 text-amber-400/80">(cache 60s)</span>}
            </span>
          </div>
        </div>
        <button
          onClick={() => fetchSummary(true)}
          data-testid="watchtower-refresh-btn"
          disabled={loading}
          className="px-4 py-2 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
        >
          {loading ? "Atualizando…" : "↻ Forçar refresh"}
        </button>
      </div>

      {/* Card 1 — Patrimônio HERO */}
      <div
        className="relative overflow-hidden rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-950/40 via-slate-900 to-slate-900 p-8 md:p-10"
        data-testid="watchtower-card-patrimonio"
      >
        <div className="absolute -top-32 -right-32 w-96 h-96 bg-emerald-500/5 rounded-full blur-3xl pointer-events-none" />
        <div className="relative grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          <div className="lg:col-span-2">
            <div className="text-xs uppercase tracking-widest text-emerald-400/80 font-mono">Patrimônio Total</div>
            <div className="mt-3 text-5xl md:text-7xl font-bold text-white tabular-nums" data-testid="patrimonio-total-value">
              {fmtBRL(p.total)}
            </div>
            {p.delta_mom_value !== null && p.delta_mom_value !== undefined && (
              <div className={`mt-2 text-sm font-mono ${deltaPos ? "text-emerald-300" : "text-rose-300"}`}>
                {deltaPos ? "↑" : "↓"} {fmtBRL(Math.abs(p.delta_mom_value))} ({fmtPct(p.delta_mom_pct)}) vs mês anterior
              </div>
            )}
            <div className="grid grid-cols-3 gap-6 mt-8">
              <div data-testid="patrimonio-auditavel">
                <div className="text-xs text-slate-400 uppercase tracking-wider">Auditável</div>
                <div className="text-xl md:text-2xl font-bold text-emerald-300 tabular-nums mt-1">{fmtBRL(p.auditavel)}</div>
                <div className="text-xs text-slate-500 mt-0.5">{fmtInt(p.n_auditavel)} ONTs · Grade A+B</div>
              </div>
              <div data-testid="patrimonio-especulativo">
                <div className="text-xs text-slate-400 uppercase tracking-wider">Especulativo</div>
                <div className="text-xl md:text-2xl font-bold text-amber-300 tabular-nums mt-1">{fmtBRL(p.especulativo)}</div>
                <div className="text-xs text-slate-500 mt-0.5">{fmtInt(p.n_especulativo)} ONTs · Grade C+D+F</div>
              </div>
              <div data-testid="patrimonio-confianca">
                <div className="text-xs text-slate-400 uppercase tracking-wider">Confiança</div>
                <div className="text-xl md:text-2xl font-bold text-white tabular-nums mt-1">{fmtPct(p.confianca_pct)}</div>
                <div className="text-xs text-slate-500 mt-0.5">% Auditável / Total</div>
              </div>
            </div>
          </div>
          {/* Sparkline 12m */}
          <div className="lg:border-l lg:border-slate-800 lg:pl-8">
            <div className="text-xs uppercase tracking-widest text-slate-400 font-mono">Evolução 12 meses</div>
            <div className="mt-3 text-emerald-400/90" data-testid="patrimonio-sparkline-wrap">
              <Sparkline data={p.evolution_12m || []} width={260} height={56} />
            </div>
            <div className="flex justify-between mt-2 text-xs text-slate-500 font-mono">
              <span>{p.evolution_12m?.[0]?.month || "—"}</span>
              <span>{p.evolution_12m?.[p.evolution_12m?.length - 1]?.month || "—"}</span>
            </div>
            <div className="mt-4 text-xs text-slate-500">
              Snapshot cumulativo · proxy via <code className="text-slate-400">created_at</code>
            </div>
          </div>
        </div>
      </div>

      {/* Cards 2 + 3 + 4 (grid 3 colunas) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Card 2 — Operação (ONTs por Local) */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6" data-testid="watchtower-card-operacao">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-xs uppercase tracking-widest text-slate-400 font-mono">Operação</div>
              <h2 className="text-lg font-semibold text-white mt-0.5">ONTs por Local</h2>
            </div>
            <div className="text-2xl font-bold text-white tabular-nums" data-testid="operacao-total">{fmtInt(op.total)}</div>
          </div>
          <div className="space-y-2.5">
            {["empresa", "tecnico", "cliente", "defeito", "descarte"].map((k) => {
              const meta = LOCATION_META[k];
              const v = op[k] || 0;
              const pct = op.total > 0 ? (v / op.total) * 100 : 0;
              return (
                <div key={k} data-testid={`operacao-row-${k}`}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-300">
                      <span className="mr-2">{meta.icon}</span>{meta.label}
                    </span>
                    <span className="text-white tabular-nums font-semibold">{fmtInt(v)}</span>
                  </div>
                  <div className="h-1.5 bg-slate-800 rounded-full mt-1 overflow-hidden">
                    <div className="h-full bg-emerald-500/70" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Card 3 — Qualidade dos Dados */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6" data-testid="watchtower-card-qualidade">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-xs uppercase tracking-widest text-slate-400 font-mono">Qualidade</div>
              <h2 className="text-lg font-semibold text-white mt-0.5">Grades A → F</h2>
            </div>
            <div className="text-right">
              <div className="text-xs text-slate-400">Auditável</div>
              <div className="text-lg font-bold text-emerald-300 tabular-nums" data-testid="qualidade-auditavel-count">{fmtInt(q.auditavel_count)}</div>
            </div>
          </div>
          <div className="space-y-2.5">
            {["A", "B", "C", "D", "F"].map((g) => {
              const meta = GRADE_META[g];
              const v = q[g] || 0;
              const total = (q.A || 0) + (q.B || 0) + (q.C || 0) + (q.D || 0) + (q.F || 0);
              const pct = total > 0 ? (v / total) * 100 : 0;
              return (
                <div key={g} data-testid={`qualidade-row-${g}`}>
                  <div className="flex items-center justify-between text-sm">
                    <span>
                      <span className={`font-bold ${meta.color}`}>{meta.label}</span>
                      <span className="text-slate-500 text-xs ml-2">{meta.desc}</span>
                    </span>
                    <span className="text-white tabular-nums font-semibold">{fmtInt(v)}</span>
                  </div>
                  <div className="h-1.5 bg-slate-800 rounded-full mt-1 overflow-hidden">
                    <div className={`h-full ${meta.bar} opacity-80`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Card 4 — Alertas */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6" data-testid="watchtower-card-alertas">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-xs uppercase tracking-widest text-slate-400 font-mono">Alertas</div>
              <h2 className="text-lg font-semibold text-white mt-0.5">Itens pendentes</h2>
            </div>
            <div className="text-2xl font-bold text-amber-300 tabular-nums" data-testid="alertas-total">{fmtInt(a.total)}</div>
          </div>
          <div className="space-y-2.5">
            {["autosn", "needs_review", "sem_trilha", "reconciliacoes_30d", "duplicadas"].map((k) => {
              const meta = ALERT_META[k];
              const v = a[k] || 0;
              return (
                <div
                  key={k}
                  data-testid={`alertas-row-${k}`}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg border ${meta.color}`}
                >
                  <div>
                    <div className="text-sm font-semibold text-white">{meta.label}</div>
                    <div className="text-xs text-slate-400 mt-0.5">{meta.desc}</div>
                  </div>
                  <div className="text-xl font-bold text-white tabular-nums">{fmtInt(v)}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Footer info */}
      <div className="text-xs text-slate-500 text-center font-mono">
        Sprint 1 (CEO 16/02/2026) · Backend: <code>/api/watchtower/estoque/summary</code> · Cache 60s · 12m janela
      </div>
    </div>
  );
}
