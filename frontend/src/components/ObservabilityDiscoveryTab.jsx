/* ObservabilityDiscoveryTab.jsx — Discovery REAL de ONT/ONU
   via Grafana proxy (Zabbix) + fallback Zabbix direto.

   Mostra SN, MAC, sinal RX/TX dBm, status, fonte (perfil Grafana
   ou Zabbix direto). */
import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle }
  from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import {
  RefreshCw, AlertTriangle, CheckCircle2,
  Wifi, Server, Radio,
} from "lucide-react";
import { api } from "@/lib/apiClient";

const KpiMini = ({ icon: Icon, label, value, tone }) => (
  <div className={`rounded-lg border ${tone} px-3 py-2 flex items-center
    gap-2 min-w-[120px]`}>
    <Icon className="w-4 h-4 opacity-70" />
    <div>
      <div className="text-[9px] uppercase font-semibold text-slate-500
        tracking-wider leading-none">{label}</div>
      <div className="text-base font-bold mt-0.5">{value}</div>
    </div>
  </div>
);

const ObservabilityDiscoveryTab = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  const run = async () => {
    setLoading(true);
    try {
      const r = await api.post(
        "/api/ai-center/observability/grafana/discover-onus");
      setData(r);
      if (r.onu_count > 0) {
        toast.success(`Discovery: ${r.onu_count} ONUs encontradas`);
      } else if (r.fallback_required) {
        toast.warning(
          "Discovery via Grafana proxy não autorizado. " +
          "Cadastre Zabbix diretamente.");
      } else {
        toast.info(
          `Discovery rodou em ${r.profiles} perfil(is) — nenhuma ONU encontrada.`);
      }
    } catch (e) {
      toast.error(`Falha no discovery: ${e.message}`);
    } finally { setLoading(false); }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api.post(
          "/api/ai-center/observability/grafana/discover-onus");
        if (!cancelled) setData(r);
      } catch (e) {
        if (!cancelled) console.warn("discovery err", e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [tick]);

  const reload = () => setTick((t) => t + 1);

  return (
    <div className="space-y-5" data-testid="obs-discovery-tab">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">
            Discovery REAL de ONT/ONU
          </h3>
          <p className="text-xs text-slate-500">
            Procura ONUs em todos os perfis Grafana habilitados +
            Zabbix direto. Extrai SN, MAC, sinal RX/TX (dBm), status.
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={reload} variant="outline" size="sm"
            disabled={loading}
            data-testid="discovery-refresh">
            <RefreshCw className={`w-4 h-4 mr-1 ${loading
              ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
          <Button onClick={run}
            className="bg-emerald-600 hover:bg-emerald-700"
            size="sm" disabled={loading}
            data-testid="discovery-run">
            {loading ? "Executando..." : "Forçar Discovery"}
          </Button>
        </div>
      </div>

      {loading && !data ? (
        <Skeleton className="h-32" />
      ) : (
        <>
          {/* KPIs */}
          <div className="flex flex-wrap gap-2"
            data-testid="discovery-kpis">
            <KpiMini icon={Server} label="Fontes"
              value={(data?.profiles || 0) + (data?.per_profile?.find(p =>
                p.profile === "_zabbix_direct" && p.configured !== false)
                ? 1 : 0)}
              tone="border-slate-200 bg-white" />
            <KpiMini icon={Wifi} label="ONUs Descobertas"
              value={data?.onu_count ?? 0}
              tone="border-emerald-200 bg-emerald-50/40" />
            <KpiMini icon={Radio} label="Items Zabbix"
              value={data?.total_items ?? 0}
              tone="border-blue-200 bg-blue-50/40" />
          </div>

          {/* Per-profile status */}
          <Card className="border-slate-200">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">
                Status por Fonte
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 pt-2">
              {(data?.per_profile || []).map((p, i) => {
                const ok = (p.onus_found || 0) > 0;
                const isZabbix = p.source === "zabbix_direct";
                return (
                  <div key={i} className={`flex items-start gap-2 p-2
                    rounded border ${ok
                      ? "bg-emerald-50/40 border-emerald-200"
                      : p.error || p.proxy_unauthorized
                        ? "bg-amber-50/40 border-amber-200"
                        : "bg-slate-50 border-slate-200"}`}>
                    {ok
                      ? <CheckCircle2 className="w-4 h-4 text-emerald-700
                          mt-0.5 flex-shrink-0" />
                      : <AlertTriangle className="w-4 h-4 text-amber-600
                          mt-0.5 flex-shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-sm font-semibold">
                          {isZabbix
                            ? "Zabbix Direto"
                            : `Grafana · ${p.profile}`}
                        </span>
                        <Badge variant="outline"
                          className={`text-[9px] ${ok
                            ? "border-emerald-300 text-emerald-700"
                            : "border-slate-300 text-slate-500"}`}>
                          {p.onus_found || 0} ONUs
                        </Badge>
                        {p.proxy_unauthorized && (
                          <Badge variant="outline"
                            className="text-[9px] border-amber-300
                            text-amber-700 bg-amber-50">
                            Proxy sem permissão
                          </Badge>
                        )}
                      </div>
                      {(p.hint || p.note || p.error) && (
                        <div className="text-[11px] text-slate-600 mt-1">
                          {p.error
                            ? <span className="text-rose-700">
                                Erro: {p.error}
                              </span>
                            : (p.hint || p.note)}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              {(data?.per_profile || []).length === 0 && !loading && (
                <div className="text-sm text-slate-400 text-center py-4">
                  Nenhuma fonte habilitada.
                </div>
              )}
            </CardContent>
          </Card>

          {/* Guidance banner */}
          {data?.guidance && (
            <div className="rounded-lg border border-amber-300 bg-amber-50
              p-3 text-sm text-amber-900" data-testid="discovery-guidance">
              <div className="font-semibold mb-1 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4" />
                Ação requerida para discovery completo
              </div>
              <div className="text-xs">{data.guidance}</div>
            </div>
          )}

          {/* ONU table */}
          <Card className="border-slate-200"
            data-testid="discovery-onu-list">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">
                ONUs Descobertas ({data?.onu_count || 0})
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {(data?.onus || []).length === 0 ? (
                <div className="text-sm text-slate-400 py-6 text-center">
                  Nenhuma ONU descoberta. {data?.fallback_required
                    ? "Configure Zabbix direto na aba Zabbix das credenciais."
                    : "Aguarde o discovery rodar."}
                </div>
              ) : (
                <div className="overflow-x-auto max-h-[600px]">
                  <table className="min-w-full text-xs"
                    data-testid="discovery-onu-table">
                    <thead className="bg-slate-50 sticky top-0 z-10">
                      <tr className="text-left text-[10px] uppercase
                        tracking-wider text-slate-500">
                        <th className="px-3 py-2">Host</th>
                        <th className="px-3 py-2">SN</th>
                        <th className="px-3 py-2">MAC</th>
                        <th className="px-3 py-2">RX (dBm)</th>
                        <th className="px-3 py-2">TX (dBm)</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">Fonte</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {(data.onus || []).slice(0, 500).map((o, i) => (
                        <tr key={`${o.hostid}-${i}`}
                          className="hover:bg-slate-50"
                          data-testid={`discovery-onu-row-${i}`}>
                          <td className="px-3 py-1.5 font-mono">
                            {o.name || o.host || "—"}
                          </td>
                          <td className="px-3 py-1.5 font-mono text-emerald-700">
                            {o.sn || "—"}
                          </td>
                          <td className="px-3 py-1.5 font-mono text-slate-700">
                            {o.mac || "—"}
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            {o.signal_rx_dbm ?? "—"}
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            {o.signal_tx_dbm ?? "—"}
                          </td>
                          <td className="px-3 py-1.5">
                            {o.status || "—"}
                          </td>
                          <td className="px-3 py-1.5 text-[10px]
                            text-slate-500">
                            {o._source === "zabbix_direct"
                              ? "Zabbix"
                              : `Graf:${o._profile}`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
};

export default ObservabilityDiscoveryTab;
