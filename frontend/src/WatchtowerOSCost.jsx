/**
 * WatchtowerOSCost — DRE Operacional: custo médio de OS via IA Patrimonial.
 *
 * Fonte: GET /api/watchtower/os-cost/kpis?days=N
 *
 * KPIs:
 *  - Total R$ no período (DRE operacional)
 *  - Custo médio por tipo (instalacao/reparo/troca/rompimento)
 *  - Top 5 técnicos por custo
 *  - Top 5 bairros/zonas
 *  - IA Coverage % (quanto vem de narrativa IA vs form manual)
 */
import React, { useEffect, useState } from "react";
import { api } from "./api";

export default function WatchtowerOSCost() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(30);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const r = await api._client.get(`/watchtower/os-cost/kpis?days=${days}`);
        if (!cancel) setData(r.data);
      } catch (e) {
        if (!cancel) setError(e?.response?.data?.detail || e.message);
      }
    }
    load();
    return () => { cancel = true; };
  }, [days]);

  if (error) return <div className="p-6 text-rose-300" data-testid="oscost-error">{error}</div>;
  if (!data) return <div className="p-6 text-slate-400" data-testid="oscost-loading">Carregando…</div>;

  return (
    <div className="space-y-5" data-testid="watch-oscost-root">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <div className="text-xs uppercase tracking-widest text-emerald-400/80 font-mono">
            DRE Operacional · Custos via IA Patrimonial · {data.window_days}d
          </div>
          <h2 className="text-2xl font-bold text-white">Custo Real por OS</h2>
        </div>
        <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}
          data-testid="oscost-days-select"
          className="bg-slate-800 text-white text-sm rounded-md border border-slate-700 px-3 py-1.5">
          <option value="7">Últimos 7d</option>
          <option value="30">Últimos 30d</option>
          <option value="60">Últimos 60d</option>
          <option value="90">Últimos 90d</option>
        </select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KCard label="Total no período" value={brl(data.total_brl)}
          sub={`${data.total_os} OS`} color="text-emerald-300" testid="oscost-total" />
        <KCard label="Material consumido" value={brl(data.total_material_brl)}
          color="text-sky-300" testid="oscost-material" />
        <KCard label="Mão-de-obra estimada" value={brl(data.total_labor_brl)}
          color="text-yellow-300" testid="oscost-labor" />
        <KCard label="🤖 IA Coverage" value={`${data.ia_coverage_pct}%`}
          sub={`${data.total_ia_used}/${data.total_os} via narrativa`}
          color={data.ia_coverage_pct >= 50 ? "text-purple-300" : "text-slate-400"}
          testid="oscost-ia-cov" />
      </div>

      {/* Por tipo */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"
        data-testid="oscost-by-type">
        <div className="text-xs uppercase tracking-widest text-emerald-400/80 font-mono mb-3">
          Custo médio por tipo de OS
        </div>
        {data.by_type.length === 0 ? (
          <div className="text-slate-500 text-sm">Sem OS no período.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="text-left py-1.5">Tipo</th>
                <th className="text-right">OS</th>
                <th className="text-right">Médio</th>
                <th className="text-right">Material médio</th>
                <th className="text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.by_type.map((row) => (
                <tr key={row.service_type} className="border-t border-slate-800"
                  data-testid={`oscost-row-${row.service_type}`}>
                  <td className="py-2 text-slate-200">{row.service_type}</td>
                  <td className="text-right text-slate-400">{row.count}</td>
                  <td className="text-right text-emerald-300 font-mono">{brl(row.avg_cost)}</td>
                  <td className="text-right text-sky-300 font-mono">{brl(row.avg_material)}</td>
                  <td className="text-right text-slate-300 font-mono">{brl(row.total_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Top técnicos */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"
          data-testid="oscost-top-techs">
          <div className="text-xs uppercase tracking-widest text-emerald-400/80 font-mono mb-2">
            Top 5 técnicos · custo acumulado
          </div>
          {data.top_techs.map((r) => (
            <div key={r.collaborator_id} className="flex justify-between py-1.5 border-b border-slate-800 last:border-0">
              <span className="text-slate-300 text-sm font-mono">{r.collaborator_id.slice(0, 18)}</span>
              <span className="font-mono text-emerald-300">{brl(r.total_cost)} <span className="text-slate-500 text-xs">({r.count})</span></span>
            </div>
          ))}
        </div>

        {/* Top zonas */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"
          data-testid="oscost-top-zones">
          <div className="text-xs uppercase tracking-widest text-emerald-400/80 font-mono mb-2">
            Top 5 bairros · custo acumulado
          </div>
          {data.top_zones.map((r) => (
            <div key={r.zone} className="flex justify-between py-1.5 border-b border-slate-800 last:border-0">
              <span className="text-slate-300 text-sm">{r.zone}</span>
              <span className="font-mono text-emerald-300">{brl(r.total_cost)} <span className="text-slate-500 text-xs">({r.count})</span></span>
            </div>
          ))}
        </div>
      </div>

      <div className="text-xs text-slate-500 font-mono" data-testid="oscost-source">
        Motor: {data.model_default} · catálogo: catalog_estimated_v1
      </div>
    </div>
  );
}

function brl(v) {
  if (v == null) return "—";
  return new Intl.NumberFormat("pt-BR",
    { style: "currency", currency: "BRL" }).format(v);
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
      {sub && <div className="text-[10px] text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}
