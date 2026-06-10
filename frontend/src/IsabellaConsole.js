/**
 * Isabella Console — single screen with tabs.
 * Tabs: Overview | Churn | Revenue | Dunning | Expansion | Twin |
 *       Outcomes | Council | Learning | Policies
 * Backend: /api/isabella/*  (already implemented; this file only exposes).
 */
import React, { useEffect, useMemo, useState } from "react";
import { Button } from "./components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/ui/tabs";
import { Badge } from "./components/ui/badge";
import { api } from "./api";
import { toast } from "sonner";

const BRL = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 2,
  });

const KIND_LABEL = {
  churn: "Churn",
  dunning: "Cobrança",
  revenue: "Receita",
  twin: "Digital Twin",
  expansion: "Expansão",
};

function OpportunityCard({ opp, onApprove, onDismiss }) {
  const k = opp.kind;
  return (
    <div
      className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 mb-3 hover:border-zinc-700 transition"
      data-testid={`isa-opp-card-${opp.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Badge variant="outline" className="text-xs">
              {KIND_LABEL[k] || k}
            </Badge>
            <Badge variant="secondary" className="text-xs">
              {opp.subkind}
            </Badge>
            <span className="text-xs text-zinc-500">
              score {Math.round(opp.score)}/100
            </span>
            <span className="text-xs text-zinc-500">
              prob {(opp.probability * 100).toFixed(0)}%
            </span>
          </div>
          <div className="font-semibold text-zinc-100 truncate">
            {opp.target_label}
          </div>
          <div className="text-xs text-zinc-400 mt-1">
            {(opp.reason_codes || []).slice(0, 2).join(" · ")}
          </div>
          <div className="text-xs text-zinc-500 mt-1">
            Impacto: <span className="text-emerald-400 font-medium">{BRL(opp.impact_brl)}</span>
          </div>
        </div>
        <div className="flex flex-col gap-2 shrink-0">
          <Button
            size="sm"
            data-testid={`isa-approve-${opp.id}`}
            onClick={() => onApprove(opp.id)}
          >
            Aprovar
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid={`isa-dismiss-${opp.id}`}
            onClick={() => onDismiss(opp.id)}
          >
            Dispensar
          </Button>
        </div>
      </div>
    </div>
  );
}

function OverviewTab({ kpis, exec, council }) {
  const totals = kpis?.totals || {};
  const c = exec?.components || {};
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Stat
        label="Oportunidades pendentes"
        value={totals.pending || 0}
        sub={BRL(totals.impact_pending_brl || 0)}
        testid="isa-stat-pending"
      />
      <Stat
        label="Engajamento"
        value={`${((exec?.opportunities?.engagement_rate || 0) * 100).toFixed(0)}%`}
        sub={`${exec?.opportunities?.approved || 0} aprovadas / ${exec?.opportunities?.dismissed || 0} dispensadas`}
        testid="isa-stat-engagement"
      />
      <Stat
        label="ROI real (30d)"
        value={BRL(exec?.roi_real_brl_total || 0)}
        sub={`precisão ${(((exec?.precision_rate) || 0) * 100).toFixed(0)}%`}
        testid="isa-stat-roi"
      />
      <Stat
        label="Churn evitado"
        value={BRL(c.churn_evitado_brl)}
        sub=""
        testid="isa-stat-churn"
      />
      <Stat
        label="Receita gerada"
        value={BRL(c.receita_gerada_brl)}
        sub=""
        testid="isa-stat-revenue"
      />
      <Stat
        label="Cobrança recuperada"
        value={BRL(c.dunning_recuperado_brl)}
        sub=""
        testid="isa-stat-dunning"
      />
      <div
        className="md:col-span-3 rounded-xl border border-zinc-800 p-5 bg-zinc-900/60"
        data-testid="isa-council-card"
      >
        <div className="text-sm text-zinc-400 mb-1">
          Última reunião do Conselho{" "}
          {council?.held_at &&
            new Date(council.held_at).toLocaleString("pt-BR")}
        </div>
        <div className="text-base text-zinc-100 font-semibold mb-2">
          Net outlook{" "}
          <span className="text-emerald-400">
            {BRL(council?.financial_summary?.net_outlook_brl || 0)}
          </span>
        </div>
        <ul className="space-y-1.5 text-sm text-zinc-300">
          {(council?.decisions || []).map((d) => (
            <li key={d.id || d.title} className="flex items-start gap-2">
              <Badge variant={d.priority === "P0" ? "destructive" : "secondary"}>
                {d.priority}
              </Badge>
              <span>{d.title}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, testid }) {
  return (
    <div
      className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5"
      data-testid={testid}
    >
      <div className="text-xs uppercase tracking-wide text-zinc-500">
        {label}
      </div>
      <div className="text-2xl font-bold text-zinc-100 mt-1">{value}</div>
      {sub && <div className="text-xs text-zinc-500 mt-1">{sub}</div>}
    </div>
  );
}

function CommanderTab({ kind, onChanged }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = async () => {
    setLoading(true);
    try {
      const r = await api.isaListOpportunities({
        kind,
        status: "pending",
        limit: 100,
      });
      setItems(r.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha ao carregar");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, [kind]);

  const scan = async () => {
    try {
      const r = await api.isaScan(kind);
      toast.success(`Scan OK: ${JSON.stringify(r).slice(0, 100)}`);
      await load();
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha no scan");
    }
  };

  const approve = async (id) => {
    try {
      await api.isaApprove(id, "via console");
      toast.success("Oportunidade aprovada");
      setItems((xs) => xs.filter((x) => x.id !== id));
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha ao aprovar");
    }
  };
  const dismiss = async (id) => {
    try {
      await api.isaDismiss(id, "via console");
      setItems((xs) => xs.filter((x) => x.id !== id));
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha ao dispensar");
    }
  };

  return (
    <div data-testid={`isa-tab-${kind}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-zinc-400 text-sm">
          {items.length} pendente(s) ·{" "}
          {KIND_LABEL[kind]} Commander
        </div>
        <Button size="sm" onClick={scan} data-testid={`isa-scan-${kind}`}>
          {loading ? "Carregando..." : "Re-scan"}
        </Button>
      </div>
      {items.length === 0 ? (
        <div className="text-center text-zinc-500 py-12">
          Sem oportunidades pendentes neste momento.
        </div>
      ) : (
        items.map((o) => (
          <OpportunityCard
            key={o.id}
            opp={o}
            onApprove={approve}
            onDismiss={dismiss}
          />
        ))
      )}
    </div>
  );
}

function OutcomesTab() {
  const [stats, setStats] = useState(null);
  const [resolving, setResolving] = useState(false);
  const load = async () => {
    try {
      setStats(await api.isaOutcomeStats(90));
    } catch (e) {
      toast.error("Falha ao carregar outcomes");
    }
  };
  useEffect(() => {
    load();
  }, []);

  const resolve = async () => {
    setResolving(true);
    try {
      const r = await api.isaResolveOutcomes(false);
      toast.success(
        `Resolvidos: ${r.resolved} (S=${r.success} F=${r.failure} I=${r.inconclusive})`
      );
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha ao resolver");
    } finally {
      setResolving(false);
    }
  };

  const t = stats?.totals || {};
  return (
    <div data-testid="isa-tab-outcomes">
      <div className="flex items-center justify-between mb-4">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 flex-1">
          <Stat label="Total" value={t.n_total || 0} testid="out-total" />
          <Stat
            label="Sucesso"
            value={t.n_success || 0}
            sub={`${((t.success_rate || 0) * 100).toFixed(0)}%`}
            testid="out-success"
          />
          <Stat label="Falha" value={t.n_failure || 0} testid="out-failure" />
          <Stat
            label="ROI real"
            value={BRL(t.roi_real || 0)}
            sub={`previsto ${BRL(t.impact_pred || 0)}`}
            testid="out-roi"
          />
          <Stat
            label="Precisão"
            value={`${((t.precision || 0) * 100).toFixed(0)}%`}
            testid="out-precision"
          />
        </div>
        <Button
          className="ml-3"
          onClick={resolve}
          data-testid="isa-resolve-outcomes"
        >
          {resolving ? "Medindo..." : "Resolver pendentes"}
        </Button>
      </div>
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-zinc-500 border-b border-zinc-800">
            <tr>
              <th className="text-left py-2 px-3">Playbook</th>
              <th className="text-right py-2 px-3">Tentativas</th>
              <th className="text-right py-2 px-3">Sucesso%</th>
              <th className="text-right py-2 px-3">ROI real</th>
              <th className="text-right py-2 px-3">Precisão</th>
            </tr>
          </thead>
          <tbody>
            {(stats?.by_playbook || []).map((p) => (
              <tr
                key={`${p.kind}-${p.subkind}-${p.playbook}`}
                className="border-b border-zinc-800/50"
              >
                <td className="py-2 px-3 text-zinc-200">
                  <Badge variant="outline" className="mr-2 text-xs">
                    {p.kind}
                  </Badge>
                  {p.subkind} · {p.playbook}
                </td>
                <td className="text-right py-2 px-3">{p.n_total}</td>
                <td className="text-right py-2 px-3">
                  {(p.success_rate * 100).toFixed(0)}%
                </td>
                <td className="text-right py-2 px-3">
                  {BRL(p.roi_real_brl)}
                </td>
                <td className="text-right py-2 px-3">
                  {(p.precision * 100).toFixed(0)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LearningTab() {
  const [report, setReport] = useState(null);
  const [ready, setReady] = useState(null);
  const load = async () => {
    try {
      const [r, e] = await Promise.all([
        api.isaLearningReport(90),
        api.isaAutoExecuteReady(90),
      ]);
      setReport(r);
      setReady(e);
    } catch (err) {
      toast.error("Falha ao carregar relatório de aprendizado");
    }
  };
  useEffect(() => {
    load();
  }, []);
  return (
    <div data-testid="isa-tab-learning">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <Stat
          label="Playbooks rastreados"
          value={report?.playbooks || 0}
          testid="learn-tracked"
        />
        <Stat
          label="Elegíveis a autoexecução"
          value={ready?.n_eligible || 0}
          sub={`${ready?.n_blocked || 0} bloqueados`}
          testid="learn-eligible"
        />
        <Stat
          label="Janela"
          value={`${report?.window_days || 90}d`}
          testid="learn-window"
        />
      </div>
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-zinc-500 border-b border-zinc-800">
            <tr>
              <th className="text-left py-2 px-3">Playbook</th>
              <th className="text-right py-2 px-3">Tentativas</th>
              <th className="text-right py-2 px-3">S</th>
              <th className="text-right py-2 px-3">F</th>
              <th className="text-right py-2 px-3">Peso</th>
              <th className="text-right py-2 px-3">Conf.</th>
              <th className="text-right py-2 px-3">Aprov.%</th>
              <th className="text-right py-2 px-3">ROI</th>
              <th className="text-center py-2 px-3">Auto?</th>
            </tr>
          </thead>
          <tbody>
            {(report?.items || []).map((it) => {
              const eligible = ready?.eligible?.find(
                (e) =>
                  e.kind === it.kind &&
                  e.subkind === it.subkind &&
                  e.playbook === it.playbook
              );
              return (
                <tr
                  key={`${it.kind}-${it.subkind}-${it.playbook}`}
                  className="border-b border-zinc-800/40 text-zinc-200"
                >
                  <td className="py-2 px-3">
                    <Badge variant="outline" className="mr-2 text-xs">
                      {it.kind}
                    </Badge>
                    {it.subkind} · {it.playbook}
                  </td>
                  <td className="text-right py-2 px-3">{it.attempts}</td>
                  <td className="text-right py-2 px-3 text-emerald-400">
                    {it.successes}
                  </td>
                  <td className="text-right py-2 px-3 text-rose-400">
                    {it.failures}
                  </td>
                  <td className="text-right py-2 px-3">
                    {it.weight.toFixed(3)}
                  </td>
                  <td className="text-right py-2 px-3">
                    {it.confidence.toFixed(2)}
                  </td>
                  <td className="text-right py-2 px-3">
                    {(it.approval_rate * 100).toFixed(0)}%
                  </td>
                  <td className="text-right py-2 px-3">
                    {BRL(it.roi_real_brl)}
                  </td>
                  <td className="text-center py-2 px-3">
                    {eligible ? (
                      <Badge variant="default">elegível</Badge>
                    ) : (
                      <span className="text-zinc-600">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {ready?.thresholds && (
        <div className="text-xs text-zinc-500 mt-3">
          Critério: attempts ≥ {ready.thresholds.attempts} · confidence ≥{" "}
          {ready.thresholds.confidence} · success_rate ≥{" "}
          {ready.thresholds.success_rate} · approval_rate ≥{" "}
          {ready.thresholds.approval_rate} · ROI &gt; 0
        </div>
      )}
    </div>
  );
}

function CouncilTab() {
  const [latest, setLatest] = useState(null);
  const [precision, setPrecision] = useState(null);
  const [running, setRunning] = useState(false);
  const load = async () => {
    try {
      const [l, p] = await Promise.all([
        api.isaCouncilLatest().catch(() => null),
        api.isaCouncilPrecision(90).catch(() => null),
      ]);
      setLatest(l);
      setPrecision(p);
    } catch (e) {
      toast.error("Falha ao carregar conselho");
    }
  };
  useEffect(() => {
    load();
  }, []);
  const hold = async () => {
    setRunning(true);
    try {
      const r = await api.isaCouncilHold();
      setLatest(r);
      toast.success("Reunião realizada");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Falha no conselho");
    } finally {
      setRunning(false);
    }
  };
  const audit = async () => {
    try {
      const r = await api.isaPrecisionRun(30);
      toast.success(
        `Precisão atual: ${((r.totals?.precision_rate || 0) * 100).toFixed(0)}%`
      );
      await load();
    } catch (e) {
      toast.error("Falha ao auditar precisão");
    }
  };
  return (
    <div data-testid="isa-tab-council">
      <div className="flex items-center gap-2 mb-4">
        <Button onClick={hold} data-testid="isa-council-hold">
          {running ? "Convocando..." : "Convocar reunião"}
        </Button>
        <Button variant="outline" onClick={audit} data-testid="isa-precision-audit">
          Auditar precisão
        </Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <Stat
          label="Reuniões (90d)"
          value={precision?.meetings || 0}
          testid="cou-meetings"
        />
        <Stat
          label="Previsto"
          value={BRL(precision?.total_predicted_brl || 0)}
          testid="cou-pred"
        />
        <Stat
          label="Realizado"
          value={BRL(precision?.roi_real_total_brl || 0)}
          sub={`precisão ${((precision?.council_precision_rate || 0) * 100).toFixed(2)}%`}
          testid="cou-real"
        />
      </div>
      {latest && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5">
          <div className="text-sm text-zinc-500 mb-2">
            Ata {latest.id} ·{" "}
            {new Date(latest.held_at).toLocaleString("pt-BR")}
          </div>
          <div className="grid grid-cols-3 gap-3 text-sm mb-3">
            <div>
              <div className="text-zinc-500">Receita potencial</div>
              <div className="text-emerald-400 font-semibold">
                {BRL(latest.financial_summary?.revenue_potential_brl)}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Perda em risco</div>
              <div className="text-rose-400 font-semibold">
                {BRL(latest.financial_summary?.loss_at_risk_brl)}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Net outlook</div>
              <div className="text-zinc-100 font-semibold">
                {BRL(latest.financial_summary?.net_outlook_brl)}
              </div>
            </div>
          </div>
          <div className="space-y-2">
            {(latest.decisions || []).map((d) => (
              <div
                key={d.id || d.title}
                className="flex items-start gap-2 text-sm text-zinc-300"
              >
                <Badge
                  variant={d.priority === "P0" ? "destructive" : "secondary"}
                >
                  {d.priority}
                </Badge>
                <div className="flex-1">
                  <div>{d.title}</div>
                  <div className="text-xs text-zinc-500">
                    {d.owner} · {d.rationale}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PoliciesTab() {
  const [policies, setPolicies] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const load = async () => {
    try {
      const [p, s] = await Promise.all([
        api.isaPolicies(true),
        api.isaMemorySuggestions(30, 3),
      ]);
      setPolicies(p.items || []);
      setSuggestions(s.suggestions || []);
    } catch (e) {
      toast.error("Falha ao carregar memória executiva");
    }
  };
  useEffect(() => {
    load();
  }, []);
  const deactivate = async (id) => {
    try {
      await api.isaDeactivatePolicy(id);
      toast.success("Política desativada");
      await load();
    } catch (e) {
      toast.error("Falha");
    }
  };
  const adoptSuggestion = async (sug) => {
    try {
      await api.isaAddPolicy({
        scope: sug.scope,
        action: sug.action,
        condition: {},
        reason: sug.reason,
        kind: sug.kind,
        subkind: sug.subkind,
        playbook: sug.playbook,
      });
      toast.success("Política criada");
      await load();
    } catch (e) {
      toast.error("Falha ao criar");
    }
  };
  return (
    <div data-testid="isa-tab-policies">
      <h3 className="text-base text-zinc-100 font-semibold mb-3">
        Políticas ativas ({policies.length})
      </h3>
      <div className="space-y-2 mb-6">
        {policies.length === 0 && (
          <div className="text-zinc-500 text-sm">
            Nenhuma política ativa — Isabella opera sem restrições.
          </div>
        )}
        {policies.map((p) => (
          <div
            key={p.id}
            className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 flex items-start justify-between gap-3"
            data-testid={`isa-policy-${p.id}`}
          >
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <Badge variant="destructive">{p.action}</Badge>
                <Badge variant="outline" className="text-xs">
                  {p.scope}
                </Badge>
                {p.kind && (
                  <Badge variant="secondary" className="text-xs">
                    {p.kind}/{p.subkind}/{p.playbook}
                  </Badge>
                )}
              </div>
              <div className="text-sm text-zinc-200">{p.reason}</div>
              <div className="text-xs text-zinc-500 mt-1">
                {p.decided_by} ·{" "}
                {new Date(p.created_at).toLocaleString("pt-BR")}
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => deactivate(p.id)}
              data-testid={`isa-policy-deactivate-${p.id}`}
            >
              Desativar
            </Button>
          </div>
        ))}
      </div>
      <h3 className="text-base text-zinc-100 font-semibold mb-3">
        Sugestões automáticas ({suggestions.length})
      </h3>
      <div className="space-y-2">
        {suggestions.length === 0 && (
          <div className="text-zinc-500 text-sm">
            Sem padrões claros de dismiss para virar política.
          </div>
        )}
        {suggestions.map((s, i) => (
          <div
            key={i}
            className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 flex items-start justify-between gap-3"
            data-testid={`isa-suggestion-${i}`}
          >
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <Badge variant="secondary">{s.action}</Badge>
                <Badge variant="outline" className="text-xs">
                  {s.kind}/{s.subkind}/{s.playbook}
                </Badge>
              </div>
              <div className="text-sm text-zinc-300">{s.reason}</div>
            </div>
            <Button
              size="sm"
              onClick={() => adoptSuggestion(s)}
              data-testid={`isa-suggestion-adopt-${i}`}
            >
              Adotar
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function IsabellaConsole() {
  const [kpis, setKpis] = useState(null);
  const [exec, setExec] = useState(null);
  const [council, setCouncil] = useState(null);

  const loadAll = async () => {
    try {
      const [k, e, c] = await Promise.all([
        api.isaKpis(),
        api.isaExecutionScore(30),
        api.isaCouncilLatest().catch(() => null),
      ]);
      setKpis(k.kpis);
      setExec(e);
      setCouncil(c);
    } catch (err) {
      toast.error("Falha ao carregar Isabella Console");
    }
  };
  useEffect(() => {
    loadAll();
  }, []);

  return (
    <div className="p-6 bg-zinc-950 min-h-screen" data-testid="isabella-console">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">
            Isabella Console
          </h1>
          <p className="text-zinc-400 text-sm mt-1">
            Sistema Nervoso Operacional · governança · aprendizado contínuo
          </p>
        </div>
        <Button onClick={loadAll} variant="outline" data-testid="isa-refresh">
          Atualizar
        </Button>
      </div>
      <Tabs defaultValue="overview" className="w-full">
        <TabsList
          className="grid grid-cols-10 mb-6"
          data-testid="isa-tabs"
        >
          <TabsTrigger value="overview" data-testid="tab-overview">
            Visão geral
          </TabsTrigger>
          <TabsTrigger value="churn" data-testid="tab-churn">
            Churn
          </TabsTrigger>
          <TabsTrigger value="dunning" data-testid="tab-dunning">
            Cobrança
          </TabsTrigger>
          <TabsTrigger value="revenue" data-testid="tab-revenue">
            Receita
          </TabsTrigger>
          <TabsTrigger value="expansion" data-testid="tab-expansion">
            Expansão
          </TabsTrigger>
          <TabsTrigger value="twin" data-testid="tab-twin">
            Twin
          </TabsTrigger>
          <TabsTrigger value="outcomes" data-testid="tab-outcomes">
            Outcomes
          </TabsTrigger>
          <TabsTrigger value="council" data-testid="tab-council">
            Conselho
          </TabsTrigger>
          <TabsTrigger value="learning" data-testid="tab-learning">
            Aprendizado
          </TabsTrigger>
          <TabsTrigger value="policies" data-testid="tab-policies">
            Memória
          </TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab kpis={kpis} exec={exec} council={council} />
        </TabsContent>
        <TabsContent value="churn">
          <CommanderTab kind="churn" onChanged={loadAll} />
        </TabsContent>
        <TabsContent value="dunning">
          <CommanderTab kind="dunning" onChanged={loadAll} />
        </TabsContent>
        <TabsContent value="revenue">
          <CommanderTab kind="revenue" onChanged={loadAll} />
        </TabsContent>
        <TabsContent value="expansion">
          <CommanderTab kind="expansion" onChanged={loadAll} />
        </TabsContent>
        <TabsContent value="twin">
          <CommanderTab kind="twin" onChanged={loadAll} />
        </TabsContent>
        <TabsContent value="outcomes">
          <OutcomesTab />
        </TabsContent>
        <TabsContent value="council">
          <CouncilTab />
        </TabsContent>
        <TabsContent value="learning">
          <LearningTab />
        </TabsContent>
        <TabsContent value="policies">
          <PoliciesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
