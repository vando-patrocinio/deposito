/**
 * WatchtowerRede — KPIs da Célula REDE (Tier 2).
 *
 * Baseado em best-practice Tier 2 ITSM/FTTH:
 *  - Queue (Aguardando + Em atendimento)
 *  - Throughput (Taxa de escalação)
 *  - SLA (MTTR + Tempo em fila + FTFR + Reopen)
 *  - Top 5 causas
 *  - IA Value (Escalações Evitadas + Horas economizadas)
 */
import React, { useEffect, useState } from "react";
import { api } from "./api";

export default function WatchtowerRede() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const r = await api._client.get("/watchtower/rede/kpis?days=30");
        if (!cancel) setData(r.data);
      } catch (e) {
        if (!cancel) setError(e?.response?.data?.detail || e.message);
      }
    }
    load();
    const it = setInterval(load, 30000);
    return () => { cancel = true; clearInterval(it); };
  }, []);

  if (error) {
    return (
      <div className="p-6 text-rose-300" data-testid="watch-rede-error">
        Erro carregando KPIs REDE: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="p-6 text-slate-400" data-testid="watch-rede-loading">
        Carregando…
      </div>
    );
  }

  const q = data.queue || {};
  const t = data.throughput || {};
  const s = data.sla || {};
  const ai = data.ai_value || {};
  const top = data.top_causes || [];

  return (
    <div className="space-y-5" data-testid="watch-rede-root">
      <div>
        <div className="text-xs uppercase tracking-widest text-cyan-400/80 font-mono">
          Célula REDE · Tier 2 · janela {data.window_days}d
        </div>
        <h2 className="text-2xl font-bold text-white">Operação da Rede</h2>
      </div>

      {/* FILA */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3" data-testid="watch-rede-queue">
        <KCard label="Aguardando REDE" value={q.aguardando} color="text-amber-300" testid="rede-aguardando" />
        <KCard label="Em atendimento" value={q.em_atendimento} color="text-sky-300" testid="rede-em-atend" />
        <KCard label="Total ativo na célula" value={q.total_ativo} color="text-cyan-300" testid="rede-total-ativo" />
      </div>

      {/* THROUGHPUT + SLA */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="watch-rede-flow">
        <KCard label="Taxa de Escalação"
          value={`${t.taxa_escalacao_pct}%`}
          sub={`${t.total_escaladas_periodo}/${t.total_eligible_periodo} OS`}
          color="text-orange-300" testid="rede-taxa-escalacao" />
        <KCard label="MTTR Rede"
          value={fmtMin(s.mttr_minutes)}
          color="text-emerald-300" testid="rede-mttr" />
        <KCard label="Tempo Médio em Fila"
          value={fmtMin(s.tempo_medio_fila_minutes)}
          color="text-yellow-300" testid="rede-fila-tempo" />
        <KCard label="FTFR Rede"
          value={`${s.ftfr_pct}%`}
          sub={`${t.total_resolvidos} resolvidos`}
          color={s.ftfr_pct >= 85 ? "text-emerald-300" : "text-amber-300"}
          testid="rede-ftfr" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <KCard label="Reopen / Devolução ao Campo"
          value={`${s.reopen_pct}%`}
          sub={`${t.total_devolvidos_campo} devolvidas`}
          color={s.reopen_pct <= 10 ? "text-emerald-300" : "text-rose-300"}
          testid="rede-reopen" />
        <KCard label="🤖 Escalações Evitadas pela IA"
          value={ai.escalations_avoided}
          sub={`${ai.hours_saved_estimate}h economizadas · ${ai.avoid_rate_pct}% de aproveitamento`}
          color="text-purple-300" testid="rede-ai-avoided" />
      </div>

      {/* TOP CAUSAS */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"
        data-testid="watch-rede-causes">
        <div className="text-xs uppercase tracking-widest text-cyan-400/80 font-mono mb-2">
          Top 5 causas de escalação · {data.window_days}d
        </div>
        {top.length === 0 && (
          <div className="text-slate-500 text-sm">Sem escalações no período.</div>
        )}
        {top.map((c, i) => (
          <div key={i} className="flex items-center justify-between py-1.5 border-b border-slate-800 last:border-0"
            data-testid={`rede-cause-${i}`}>
            <span className="text-slate-300 text-sm">{c.cause}</span>
            <span className="font-mono text-cyan-300">{c.count}</span>
          </div>
        ))}
      </div>

      <div className="text-xs text-slate-500 font-mono" data-testid="watch-rede-model-info">
        Modelo IA: {ai.model_default} · janela: {data.window_days}d · refresh: 30s
      </div>
    </div>
  );
}

function fmtMin(m) {
  if (!m) return "—";
  if (m < 60) return `${Math.round(m)}m`;
  const h = Math.floor(m / 60);
  const mm = Math.round(m % 60);
  return `${h}h${mm > 0 ? ` ${mm}m` : ""}`;
}

function KCard({ label, value, sub, color = "text-white", testid }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"
      data-testid={testid ? `kcard-${testid}` : undefined}>
      <div className="text-[10px] uppercase tracking-widest text-slate-400 font-mono">
        {label}
      </div>
      <div className={`text-2xl font-bold tabular-nums mt-1 ${color}`}
        data-testid={testid ? `kcard-${testid}-value` : undefined}>
        {value ?? "—"}
      </div>
      {sub && (
        <div className="text-[10px] text-slate-500 mt-1">{sub}</div>
      )}
    </div>
  );
}
