/* ObservabilityOnusGrafanaTab.jsx — Sub-aba ONT/ONU · Grafana
   KPIs derivados dos dashboards de OLT cadastrados no Grafana
   (tag "OLT" ou título contendo OLT/PON/ONU). */
import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle }
  from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import {
  Activity, Radio, AlertTriangle, ExternalLink,
  RefreshCw, BarChart3, Server, LayoutGrid,
} from "lucide-react";
import { api } from "@/lib/apiClient";

const VENDOR_COLORS = {
  HUAWEI: "bg-red-50 text-red-700 border-red-200",
  ZTE: "bg-blue-50 text-blue-700 border-blue-200",
  DATACOM: "bg-purple-50 text-purple-700 border-purple-200",
  FIBERHOME: "bg-amber-50 text-amber-700 border-amber-200",
  PARKS: "bg-teal-50 text-teal-700 border-teal-200",
  UNKNOWN: "bg-slate-50 text-slate-600 border-slate-200",
};

const KpiCard = ({ icon: Icon, label, value, tone, testid }) => (
  <Card className={`border ${tone}`} data-testid={testid}>
    <CardContent className="p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider
            text-slate-500 font-semibold">{label}</div>
          <div className="text-2xl font-bold mt-1">{value}</div>
        </div>
        <Icon className="w-7 h-7 opacity-60" />
      </div>
    </CardContent>
  </Card>
);

const ObservabilityOnusGrafanaTab = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get(
          "/api/ai-center/observability/grafana/olts");
        if (cancelled) return;
        setData(r);
      } catch (e) {
        if (!cancelled) {
          toast.error(`Falha ao carregar dados do Grafana: ${e.message}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [tick]);

  if (loading) {
    return (
      <div className="space-y-4" data-testid="obs-onus-grafana-loading">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[1, 2, 3, 4, 5].map((i) =>
            <Skeleton key={i} className="h-20 rounded-lg" />)}
        </div>
        <Skeleton className="h-32 rounded-lg" />
      </div>
    );
  }

  const kpis = data?.kpis || {};
  const items = data?.items || [];
  const vendors = kpis.vendors || {};

  return (
    <div className="space-y-5" data-testid="obs-onus-grafana-tab">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">
            ONT/ONU · vindo do Grafana
          </h3>
          <p className="text-xs text-slate-500">
            Dashboards de OLT publicados no Grafana ·
            data source Zabbix · atualizado em tempo real
          </p>
        </div>
        <Button variant="outline" size="sm"
          onClick={() => setTick((t) => t + 1)}
          data-testid="obs-onus-grafana-refresh">
          <RefreshCw className="w-4 h-4 mr-1" /> Atualizar
        </Button>
      </div>

      {/* KPIs principais */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3"
        data-testid="obs-onus-grafana-kpis">
        <KpiCard icon={Server} label="OLTs Monitorados"
          value={kpis.olts_monitored || 0}
          tone="border-emerald-200 bg-emerald-50/40"
          testid="kpi-grafana-olts" />
        <KpiCard icon={LayoutGrid} label="Total Panels"
          value={kpis.total_panels || 0}
          tone="border-slate-200" testid="kpi-grafana-panels" />
        <KpiCard icon={Radio} label="Panels de PON"
          value={kpis.pon_panels || 0}
          tone="border-blue-200 bg-blue-50/40"
          testid="kpi-grafana-pon" />
        <KpiCard icon={Activity} label="Panels de ONU/ONT"
          value={kpis.onu_panels || 0}
          tone="border-emerald-200 bg-emerald-50/40"
          testid="kpi-grafana-onu" />
        <KpiCard icon={AlertTriangle} label="Panels de Alerta"
          value={kpis.alert_panels || 0}
          tone="border-amber-200 bg-amber-50/40"
          testid="kpi-grafana-alert" />
      </div>

      {/* Vendors */}
      {Object.keys(vendors).length > 0 && (
        <Card className="border-slate-200"
          data-testid="obs-onus-grafana-vendors">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold">
              Distribuição por Fabricante
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="flex flex-wrap gap-2">
              {Object.entries(vendors).map(([v, n]) => (
                <Badge key={v} variant="outline"
                  className={`${VENDOR_COLORS[v] || VENDOR_COLORS.UNKNOWN}
                  gap-1.5 px-3 py-1`}>
                  <span className="font-semibold">{v}</span>
                  <span className="text-[10px]">{n} OLT(s)</span>
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Lista de OLTs */}
      <Card className="border-slate-200"
        data-testid="obs-onus-grafana-list">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold">
            OLTs Monitoradas ({items.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-2">
          {items.length === 0 ? (
            <div className="text-sm text-slate-400 py-6 text-center">
              Nenhum dashboard de OLT encontrado no Grafana.
              Verifique se há dashboards com tag <code>OLT</code> ou
              título contendo <code>OLT/PON/ONU</code>.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3
              gap-3">
              {items.map((o) => (
                <Card key={o.uid} className="border-slate-200
                  hover:shadow-md transition-shadow"
                  data-testid={`obs-grafana-olt-${o.uid}`}>
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-slate-900
                          text-sm truncate" title={o.title}>
                          {o.title}
                        </div>
                        <div className="flex items-center gap-1.5 mt-1
                          flex-wrap">
                          <Badge variant="outline"
                            className={`${VENDOR_COLORS[o.vendor]
                              || VENDOR_COLORS.UNKNOWN} text-[10px]`}>
                            {o.vendor}
                          </Badge>
                          {(o.tags || []).slice(0, 3).map((t) => (
                            <Badge key={t} variant="outline"
                              className="text-[10px] text-slate-500">
                              {t}
                            </Badge>
                          ))}
                        </div>
                      </div>
                      {o.url_grafana && (
                        <a href={o.url_grafana} target="_blank"
                          rel="noopener noreferrer"
                          className="text-slate-400 hover:text-slate-700"
                          title="Abrir no Grafana"
                          data-testid={`obs-grafana-olt-${o.uid}-link`}>
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      )}
                    </div>

                    <div className="grid grid-cols-4 gap-2 text-center
                      pt-2 border-t border-slate-100">
                      <div>
                        <div className="text-[9px] text-slate-500
                          uppercase">Panels</div>
                        <div className="text-base font-bold text-slate-800">
                          {o.panels || 0}
                        </div>
                      </div>
                      <div>
                        <div className="text-[9px] text-slate-500
                          uppercase">PON</div>
                        <div className="text-base font-bold text-blue-700">
                          {o.pon_panels || 0}
                        </div>
                      </div>
                      <div>
                        <div className="text-[9px] text-slate-500
                          uppercase">ONU</div>
                        <div className="text-base font-bold text-emerald-700">
                          {o.onu_panels || 0}
                        </div>
                      </div>
                      <div>
                        <div className="text-[9px] text-slate-500
                          uppercase">Alert</div>
                        <div className="text-base font-bold text-amber-700">
                          {o.alert_panels || 0}
                        </div>
                      </div>
                    </div>

                    {o.url_grafana && (
                      <a href={o.url_grafana} target="_blank"
                        rel="noopener noreferrer"
                        className="block text-center text-xs
                          font-medium text-emerald-700 hover:text-emerald-800
                          border border-emerald-200 rounded py-1.5
                          hover:bg-emerald-50 transition-colors"
                        data-testid={`obs-grafana-olt-${o.uid}-open`}>
                        Abrir Dashboard no Grafana →
                      </a>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {data?.grafana_url && (
        <div className="text-xs text-slate-400 flex items-center gap-2">
          <BarChart3 className="w-3 h-3" />
          Fonte: {data.grafana_url}
        </div>
      )}
    </div>
  );
};

export default ObservabilityOnusGrafanaTab;
