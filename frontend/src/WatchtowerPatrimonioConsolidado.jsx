/**
 * Watchtower Patrimônio Consolidado — Onda C P2 (18/06/2026)
 *
 * Sub-aba que responde 5 perguntas em <30s:
 *   P1) Quanto patrimônio existe?       → ATIVOS
 *   P2) Quanto vale?                     → VALOR
 *   P3) Quanto é auditável?              → PATRIMÔNIO CONFIÁVEL
 *   P4) Onde está?                       → ATIVOS · localização
 *   P5) O que não consigo rastrear?      → RASTREABILIDADE · piores
 */
import React, { useEffect, useState, useCallback } from "react";
import { client } from "./api";

const fmtInt = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR"));
const fmtBRL = (v) => v == null ? "—" : `R$ ${Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtPct = (v) => v == null ? "—" : `${Number(v).toFixed(1)}%`;

const tierColor = (tier) => ({
  excelencia: "text-emerald-300 bg-emerald-500/10 border-emerald-500/30",
  verde:      "text-emerald-300 bg-emerald-500/10 border-emerald-500/30",
  amarelo:    "text-amber-300 bg-amber-500/10 border-amber-500/30",
  vermelho:   "text-rose-300 bg-rose-500/10 border-rose-500/30",
})[tier] || "text-slate-300 bg-slate-800 border-slate-700";

export default function WatchtowerPatrimonioConsolidado() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await client.get("/watchtower/estoque/patrimonio-consolidado");
      setData(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading && !data) {
    return <div data-testid="patcons-loading" className="min-h-[300px] flex items-center justify-center text-slate-400"><div className="animate-pulse">Carregando Patrimônio Consolidado…</div></div>;
  }
  if (err) {
    return <div data-testid="patcons-error" className="min-h-[300px] flex items-center justify-center"><div className="bg-rose-950/40 border border-rose-500/30 text-rose-200 px-6 py-4 rounded-lg max-w-md"><div className="font-bold mb-1">Erro</div><div className="text-sm">{String(err)}</div><button onClick={fetchData} className="mt-3 px-3 py-1.5 bg-rose-500/20 hover:bg-rose-500/30 rounded text-xs font-semibold">Tentar novamente</button></div></div>;
  }

  const ativos = data?.ativos || {};
  const valor = data?.valor || {};
  const rast = data?.rastreabilidade || {};
  const confiavel = data?.patrimonio_confiavel || {};
  const cobertura = data?.cobertura_patrimonial || {};
  const recBreak = valor.recuperacoes_breakdown || { operacional: {}, extraordinaria: {} };
  const dist = rast.distribution || {};

  return (
    <div className="space-y-6" data-testid="patcons-root">
      {/* KPI PRIMÁRIO — Cobertura Patrimonial (Ajuste 2 · gate Sprint 5.1) */}
      <div className={`rounded-2xl border p-6 ${tierColor(cobertura.tier)}`} data-testid="patcons-card-cobertura">
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-widest font-mono opacity-80">Cobertura Patrimonial · KPI PRIMÁRIO (gate Sprint 5.1)</div>
            <div className="text-6xl font-bold tabular-nums mt-1" data-testid="patcons-cobertura-pct">{fmtPct(cobertura.cobertura_pct)}</div>
            <div className="text-sm opacity-80 mt-1">
              {fmtInt(cobertura.intersect_count)} ONTs do estoque ∩ {fmtInt(cobertura.smartolt_total_docs)} ONUs no SmartOLT · Meta de desbloqueio ≥ {fmtPct(cobertura.meta_desbloqueio_sprint_51_pct)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs uppercase tracking-widest opacity-80">Auto Balanço (Sprint 5.1)</div>
            <div className="text-2xl font-bold tabular-nums" data-testid="patcons-auto-balanco-status">
              {cobertura.auto_balanco_bloqueado ? "BLOQUEADO" : "LIBERADO"}
            </div>
            <div className="text-xs opacity-70">gap: {fmtPct(cobertura.gap_para_meta_pct)}</div>
          </div>
        </div>
      </div>

      {/* HERO — KPI compound: Patrimônio Confiável */}
      <div className={`rounded-2xl border p-6 ${tierColor(confiavel.tier)}`} data-testid="patcons-card-hero">
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-widest font-mono opacity-80">Patrimônio Confiável (rastreabilidade × confiabilidade financeira)</div>
            <div className="text-6xl font-bold tabular-nums mt-1" data-testid="patcons-confiavel-pct">{fmtPct(confiavel.patrimonio_confiavel_pct)}</div>
            <div className="text-sm opacity-80 mt-1">
              Rastreabilidade {fmtPct(confiavel.rastreabilidade_pct)} · Confiabilidade financeira {fmtPct(confiavel.confiabilidade_financeira_pct)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs uppercase tracking-widest opacity-80">Valor defensável</div>
            <div className="text-2xl font-bold tabular-nums" data-testid="patcons-valor-defensavel">{fmtBRL(confiavel.valor_defendvel_estimado)}</div>
            <div className="text-xs opacity-70">de {fmtBRL(valor.valor_atual)} atual</div>
          </div>
        </div>
      </div>

      {/* P1+P4 — ATIVOS TOTAIS */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6" data-testid="patcons-card-ativos">
        <div className="text-xs uppercase tracking-widest text-emerald-400/80 font-mono mb-1">Pergunta 1 + 4 · ATIVOS TOTAIS</div>
        <h2 className="text-lg font-semibold text-white">Quanto patrimônio existe e onde está?</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
          <KPI label="ONTs Total"          value={fmtInt(ativos.total)}             testid="ativos-total" color="text-white" />
          <KPI label="Compradas"           value={fmtInt(ativos.compradas)}         testid="ativos-compradas" />
          <KPI label="Em Cliente"          value={fmtInt(ativos.em_cliente)}        testid="ativos-cliente" color="text-emerald-300" />
          <KPI label="Em Técnico"          value={fmtInt(ativos.em_tecnico)}        testid="ativos-tecnico" color="text-sky-300" />
          <KPI label="Em Empresa"          value={fmtInt(ativos.em_empresa)}        testid="ativos-empresa" />
          <KPI label="Em Praça"            value={fmtInt(ativos.em_praca)}          testid="ativos-praca" />
          <KPI label="Em Defeito"          value={fmtInt(ativos.em_defeito)}        testid="ativos-defeito" color="text-rose-300" />
          <KPI label="Sem Localização"     value={fmtInt(ativos.sem_localizacao)}   testid="ativos-no-loc"  color={ativos.sem_localizacao > 0 ? "text-amber-300" : "text-slate-300"} />
        </div>
        {ativos.sintetica > 0 && (
          <div className="mt-3 text-xs text-amber-200/80" data-testid="ativos-sintetica-banner">
            ⚠️ {fmtInt(ativos.sintetica)} ONTs com trilha sintética (origem auto-marcada pela Onda A). Refino vem na Sprint 5.
          </div>
        )}
      </div>

      {/* P2 — VALOR PATRIMONIAL */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6" data-testid="patcons-card-valor">
        <div className="text-xs uppercase tracking-widest text-sky-400/80 font-mono mb-1">Pergunta 2 · VALOR PATRIMONIAL</div>
        <h2 className="text-lg font-semibold text-white">Quanto vale?</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-4">
          <KPI label="Aquisição"     value={fmtBRL(valor.aquisicao_total)}  testid="valor-aquisicao" />
          <KPI label="Depreciação"   value={fmtBRL(valor.depreciacao_total)} testid="valor-depreciacao" color="text-amber-300" />
          <KPI label="Valor Atual"   value={fmtBRL(valor.valor_atual)}      testid="valor-atual" color="text-emerald-300" />
          <KPI label="Perdas (est.)" value={fmtBRL(valor.perdas_estimadas)} testid="valor-perdas" color="text-rose-300" />
          <KPI label="Confiab. Financeira" value={fmtPct(valor.confiabilidade_financeira_pct)} testid="valor-confiab-fin" />
        </div>

        {/* Ajuste 2 · Split Recuperações Operacional × Extraordinária */}
        <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="patcons-card-recuperacoes-split">
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4" data-testid="rec-operacional">
            <div className="text-xs uppercase tracking-widest text-emerald-300/80 font-mono">Recuperação Operacional</div>
            <div className="text-2xl font-bold tabular-nums text-emerald-200 mt-1" data-testid="rec-operacional-valor">
              {fmtBRL(valor.recuperacoes_operacional)}
            </div>
            <div className="text-[11px] text-slate-400 mt-1">Swaps, reuso normal de equipamento, devoluções de campo.</div>
            {Object.keys(recBreak.operacional || {}).length > 0 && (
              <div className="mt-2 space-y-0.5 text-[11px] font-mono">
                {Object.entries(recBreak.operacional).map(([k, v]) => (
                  <div key={k} data-testid={`rec-op-${k}`} className="flex justify-between">
                    <span className="text-slate-400 truncate pr-2">{k}</span>
                    <span className="text-emerald-300 tabular-nums">{fmtBRL(v)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4" data-testid="rec-extraordinaria">
            <div className="text-xs uppercase tracking-widest text-amber-300/80 font-mono">Recuperação Extraordinária</div>
            <div className="text-2xl font-bold tabular-nums text-amber-200 mt-1" data-testid="rec-extraordinaria-valor">
              {fmtBRL(valor.recuperacoes_extraordinaria)}
            </div>
            <div className="text-[11px] text-slate-400 mt-1">Estornos RCA, ajustes forenses, reconciliações legacy. NÃO contamina KPI operacional.</div>
            {Object.keys(recBreak.extraordinaria || {}).length > 0 && (
              <div className="mt-2 space-y-0.5 text-[11px] font-mono">
                {Object.entries(recBreak.extraordinaria).map(([k, v]) => (
                  <div key={k} data-testid={`rec-ex-${k}`} className="flex justify-between">
                    <span className="text-slate-400 truncate pr-2">{k}</span>
                    <span className="text-amber-300 tabular-nums">{fmtBRL(v)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="mt-3 text-xs text-slate-500">
          Catálogo: <code>{data.price_catalog_meta?.source}</code> · {data.price_catalog_meta?.note}
        </div>
      </div>

      {/* P3+P5 — RASTREABILIDADE + drill-down */}
      <div className={`rounded-2xl border p-6 ${tierColor(rast.tier)}`} data-testid="patcons-card-rast">
        <div className="flex justify-between mb-3">
          <div>
            <div className="text-xs uppercase tracking-widest font-mono opacity-80">Pergunta 3 + 5 · ÍNDICE DE RASTREABILIDADE</div>
            <h2 className="text-lg font-semibold text-white mt-0.5">Quanto é auditável + o que não consigo rastrear?</h2>
          </div>
          <div className="text-right">
            <div className="text-4xl font-bold tabular-nums" data-testid="rast-overall-pct">{fmtPct(rast.overall_index_pct)}</div>
            <div className="text-xs opacity-70">tier <strong>{rast.tier}</strong></div>
          </div>
        </div>
        <div className="text-xs opacity-80 mb-3">
          5 campos × 20% cada: Origem · Localização · Responsável · Última Movimentação · Ticket/Evento
        </div>
        {/* Distribuição por bucket */}
        <div className="grid grid-cols-6 gap-1 mb-4">
          {["0_pct", "20_pct", "40_pct", "60_pct", "80_pct", "100_pct"].map((b, i) => (
            <div key={b} data-testid={`rast-bucket-${b}`} className="bg-slate-800/40 rounded p-2 text-center">
              <div className="text-xs opacity-70">{i * 20}%</div>
              <div className="text-lg font-bold tabular-nums">{fmtInt(dist[b])}</div>
            </div>
          ))}
        </div>
        {(rast.worst_assets || []).length > 0 && (
          <div>
            <div className="text-xs opacity-80 mb-2 uppercase tracking-wider">
              Top {Math.min(rast.worst_assets.length, 50)} piores (pra ação)
            </div>
            <div className="space-y-1 max-h-72 overflow-auto pr-1">
              {(rast.worst_assets || []).slice(0, 50).map((a) => (
                <div
                  key={a.ont_id}
                  data-testid={`rast-worst-${a.ont_id}`}
                  className="px-3 py-1.5 bg-slate-800/40 rounded text-xs flex justify-between"
                >
                  <span className="font-mono text-slate-300">
                    {a.ont_id} · {a.mac || a.sn || "?"} · {a.location_type || "sem_loc"}
                  </span>
                  <span className="text-rose-300 tabular-nums">
                    {a.score_pct}% · falta: {a.missing_fields.join(", ")}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="text-xs text-slate-500 text-center font-mono">
        Gerado em {new Date(data.generated_at).toLocaleString("pt-BR")} · Onda C P2 · 5 perguntas em &lt; 30s
      </div>
    </div>
  );
}

function KPI({ label, value, testid, color = "text-white" }) {
  return (
    <div data-testid={testid}>
      <div className="text-xs text-slate-400 uppercase tracking-wider">{label}</div>
      <div className={`text-xl font-bold tabular-nums mt-0.5 ${color}`}>{value}</div>
    </div>
  );
}
