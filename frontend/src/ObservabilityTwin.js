/* ObservabilityTwin.js — SmartProv Observability Twin (Sprint V5.2)
   Aba única. 10 cards no padrão PROBLEMA/CAUSA/IMPACTO/AÇÃO/
   CONFIANÇA/EVIDÊNCIA + Health Score + lista de incidentes
   correlacionados + botão para disparar pipeline. */
import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle }
  from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent }
  from "@/components/ui/tabs";
import { toast } from "sonner";
import ObservabilityCredentialsCard
  from "@/components/ObservabilityCredentialsCard";
import ObservabilityOnusTab
  from "@/components/ObservabilityOnusTab";
import ObservabilityOnusGrafanaTab
  from "@/components/ObservabilityOnusGrafanaTab";
import { api } from "@/lib/apiClient";

const getJSON = (path) => api.get(path);
const postJSON = (path) => api.post(path);

const HealthGauge = ({ health }) => {
  if (!health) return null;
  const s = health.score;
  const color = s >= 95 ? "text-emerald-600"
    : s >= 90 ? "text-emerald-500"
    : s >= 80 ? "text-amber-500"
    : s >= 70 ? "text-orange-500" : "text-rose-600";
  return (
    <div className="flex items-center gap-6 p-4 rounded-xl
      bg-gradient-to-br from-slate-50 to-white border border-slate-200"
      data-testid="obs-health-gauge">
      <div className={`text-5xl font-bold tracking-tight ${color}`}>
        {s.toFixed(1)}
      </div>
      <div className="space-y-1">
        <div className="text-xs uppercase tracking-widest text-slate-500">
          Saúde da Observabilidade
        </div>
        <div className={`text-lg font-semibold ${color}`}>
          {health.classification}
        </div>
        <div className="text-xs text-slate-500">
          janela {health.window_hours}h ·
          alertas críticos: {health.raw.zabbix_critical} ·
          host down: {health.raw.zabbix_host_down}
        </div>
      </div>
    </div>
  );
};

const Card6 = ({ card }) => {
  const c = card.confidence || 0;
  const tone = c >= 0.85 ? "bg-emerald-50 border-emerald-200 text-emerald-700"
    : c >= 0.65 ? "bg-amber-50 border-amber-200 text-amber-700"
    : "bg-rose-50 border-rose-200 text-rose-700";
  return (
    <Card className="border-slate-200 hover:shadow-md transition-shadow"
      data-testid={`obs-card-${(card.title || "").toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")}`}>
      <CardHeader className="pb-3 border-b border-slate-100">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base font-semibold text-slate-900">
            {card.title}
          </CardTitle>
          <Badge className={`text-[10px] uppercase border ${tone}`}>
            conf {Math.round(c * 100)}%
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-4 space-y-3 text-sm">
        <Row k="PROBLEMA" v={card.problem} />
        <Row k="CAUSA" v={card.cause} />
        <Row k="IMPACTO" v={card.impact} accent="text-rose-700" />
        <Row k="AÇÃO" v={card.action} accent="text-emerald-700" bold />
        <div className="pt-2 border-t border-slate-100">
          <div className="text-[10px] font-semibold uppercase
            tracking-wider text-slate-500 mb-1">EVIDÊNCIA</div>
          <ul className="space-y-1 max-h-24 overflow-auto">
            {(card.evidence || []).slice(0, 4).map((e, i) => (
              <li key={i} className="text-xs text-slate-600">
                <strong>{e.type}</strong>:{" "}
                {typeof e.value === "object"
                  ? JSON.stringify(e.value).slice(0, 80)
                  : String(e.value).slice(0, 80)}{" "}
                {e.source && <span className="text-slate-400">
                  ({e.source})</span>}
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
};

const Row = ({ k, v, accent = "text-slate-700", bold = false }) => (
  <div>
    <div className="text-[10px] font-semibold uppercase tracking-wider
      text-slate-500 mb-0.5">{k}</div>
    <div className={`${accent} ${bold ? "font-semibold" : ""}
      leading-snug`}>{v || "—"}</div>
  </div>
);

const ObservabilityTwin = () => {
  const [summary, setSummary] = useState(null);
  const [connStatus, setConnStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [s, c] = await Promise.all([
        getJSON("/api/ai-center/observability/summary?window_hours=24"),
        getJSON("/api/ai-center/observability/connectors/status"),
      ]);
      setSummary(s);
      setConnStatus(c);
    } catch (e) {
      toast.error(`Erro: ${e.message}`);
    }
  };

  useEffect(() => {
    (async () => { setLoading(true); await load(); setLoading(false); })();
  }, []);

  const onRun = async () => {
    try {
      setBusy(true);
      const r = await postJSON("/api/ai-center/observability/run");
      toast.success(
        `Pipeline OK · ${r.incidents_correlated} incidentes · ` +
        `${r.decisions.cycles_triggered} ciclos`);
      await load();
    } catch (e) {
      toast.error(`Falha pipeline: ${e.message}`);
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-5 px-1" data-testid="observability-twin">
      <header className="flex items-center justify-between
        flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight
            text-slate-900">
            Observability Twin
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Zabbix + Grafana + SmartOLT + Tickets como fontes vivas
            do Sistema Nervoso.{" "}
            {connStatus && (
              <span className={connStatus.mock_mode
                ? "text-amber-600" : "text-emerald-600"}>
                {connStatus.mock_mode ? "Modo MOCK (configure ENVs)"
                  : "Conectores REAIS"}
              </span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={onRun} disabled={busy}
            data-testid="obs-run-pipeline"
            className="bg-emerald-600 hover:bg-emerald-700">
            {busy ? "Executando..." : "Disparar Pipeline"}
          </Button>
          <Button variant="outline" onClick={load}
            data-testid="obs-refresh" disabled={busy}>
            Atualizar
          </Button>
        </div>
      </header>

      {loading ? (
        <Skeleton className="h-28 w-full rounded-lg" />
      ) : (
        <>
          <ObservabilityCredentialsCard />

          <Tabs defaultValue="resumo" className="w-full"
            data-testid="obs-main-tabs">
            <TabsList>
              <TabsTrigger value="resumo"
                data-testid="obs-tab-resumo">Resumo</TabsTrigger>
              <TabsTrigger value="onus"
                data-testid="obs-tab-onus">ONT/ONU (SmartOLT)</TabsTrigger>
              <TabsTrigger value="onus-grafana"
                data-testid="obs-tab-onus-grafana">
                ONT/ONU (Grafana)
              </TabsTrigger>
            </TabsList>

            <TabsContent value="resumo" className="space-y-5 pt-4">
              <HealthGauge health={summary?.health} />

              {summary?.incidents?.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50
                  p-4" data-testid="obs-incident-banner">
                  <div className="text-sm font-semibold text-amber-900 mb-1">
                    {summary.incidents.length} incidente(s) correlacionado(s)
                  </div>
                  <ul className="text-xs text-amber-800 space-y-0.5">
                    {summary.incidents.slice(0, 5).map((i) => (
                      <li key={i.incident_id}>
                        🛑 <strong>{i.host_name}</strong>{" "}
                        (sev {i.severity}) ·
                        {i.impacted_subscribers} cliente(s) ·
                        R$ {(i.revenue_at_risk_BRL || 0).toFixed(2)} em risco ·
                        conf {Math.round((i.confidence || 0) * 100)}%
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2
                xl:grid-cols-3 gap-4"
                data-testid="obs-grid">
                {(summary?.cards || []).map((c, i) => (
                  <Card6 key={i} card={c} />
                ))}
              </div>
            </TabsContent>

            <TabsContent value="onus" className="pt-4">
              <ObservabilityOnusTab />
            </TabsContent>

            <TabsContent value="onus-grafana" className="pt-4">
              <ObservabilityOnusGrafanaTab />
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
};

export default ObservabilityTwin;
