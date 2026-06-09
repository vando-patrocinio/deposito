/* ObservabilityDiscoveryTab.jsx — Discovery REAL de ONT/ONU
   via 3 fontes em paralelo:
     1) Grafana proxy (Zabbix)
     2) Zabbix direto
     3) SNMP direto nas OLTs (V-SOL/Huawei/ZTE) — cache 5min

   Mostra SN, MAC, sinal RX/TX dBm, status, fonte (Grafana / Zabbix /
   SNMP-direto). */
import React, { useEffect, useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle }
  from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import {
  RefreshCw, AlertTriangle, CheckCircle2,
  Wifi, Server, Radio, Cable, Zap,
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

const sourceBadge = (o) => {
  if (o._source === "olt_snmp_cache") return { label: "SNMP", tone: "bg-violet-50 text-violet-700 border-violet-300" };
  if (o._source === "zabbix_direct") return { label: "Zabbix", tone: "bg-blue-50 text-blue-700 border-blue-300" };
  return { label: `Graf:${o._profile || "?"}`, tone: "bg-slate-50 text-slate-600 border-slate-300" };
};

const ObservabilityDiscoveryTab = () => {
  const [grafData, setGrafData] = useState(null);
  const [snmpData, setSnmpData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [tick, setTick] = useState(0);

  const fetchAll = async (showToast = false) => {
    setLoading(true);
    const [g, s] = await Promise.allSettled([
      api.post("/api/ai-center/observability/grafana/discover-onus"),
      api.get("/api/admin/integrations/olt/cached"),
    ]);
    if (g.status === "fulfilled") setGrafData(g.value);
    else { setGrafData(null); console.warn("graf discovery", g.reason?.message); }
    if (s.status === "fulfilled") setSnmpData(s.value);
    else { setSnmpData(null); console.warn("snmp cached", s.reason?.message); }

    if (showToast) {
      const gn = g.status === "fulfilled" ? (g.value?.onu_count || 0) : 0;
      const sn = s.status === "fulfilled" ? (s.value?.onu_count || 0) : 0;
      const total = gn + sn;
      if (total > 0) toast.success(`Discovery: ${total} ONUs (Graf/Zbx: ${gn} · SNMP: ${sn})`);
      else toast.info("Nenhuma ONU descoberta nas fontes habilitadas.");
    }
    setLoading(false);
  };

  const run = async () => fetchAll(true);

  const forceSnmpPoll = async () => {
    setPolling(true);
    try {
      const r = await api.post("/api/admin/integrations/olt/poll-now");
      toast.success(`Poll SNMP: ${r.polled_ok || 0}/${r.olts || 0} OLTs em ${r.elapsed_s || 0}s`);
      setTick((t) => t + 1);
    } catch (e) {
      toast.error(`Falha poll SNMP: ${e.message}`);
    } finally { setPolling(false); }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!cancelled) await fetchAll(false);
    })();
    return () => { cancelled = true; };
  }, [tick]);

  const reload = () => setTick((t) => t + 1);

  const mergedOnus = useMemo(() => {
    const list = [];
    (grafData?.onus || []).forEach((o) => list.push(o));
    (snmpData?.onus || []).forEach((o) => list.push(o));
    return list;
  }, [grafData, snmpData]);

  const totalOnus = mergedOnus.length;
  const grafCount = grafData?.onu_count || 0;
  const snmpCount = snmpData?.onu_count || 0;
  const grafSources = (grafData?.profiles || 0) +
    ((grafData?.per_profile || []).find(p =>
      p.profile === "_zabbix_direct" && p.configured !== false) ? 1 : 0);
  const snmpSources = (snmpData?.per_olt || []).length;

  return (
    <div className="space-y-5" data-testid="obs-discovery-tab">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">
            Discovery REAL de ONT/ONU
          </h3>
          <p className="text-xs text-slate-500">
            Mescla 3 fontes: Grafana proxy · Zabbix direto · SNMP direto
            nas OLTs (V-SOL / Huawei / ZTE). Extrai SN, MAC, RX/TX dBm, status.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button onClick={reload} variant="outline" size="sm"
            disabled={loading}
            data-testid="discovery-refresh">
            <RefreshCw className={`w-4 h-4 mr-1 ${loading
              ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
          <Button onClick={forceSnmpPoll} variant="outline" size="sm"
            disabled={polling}
            className="border-violet-300 text-violet-700 hover:bg-violet-50"
            data-testid="discovery-snmp-poll">
            <Zap className={`w-4 h-4 mr-1 ${polling ? "animate-pulse" : ""}`} />
            {polling ? "Pollando..." : "Forçar Poll SNMP"}
          </Button>
          <Button onClick={run}
            className="bg-emerald-600 hover:bg-emerald-700"
            size="sm" disabled={loading}
            data-testid="discovery-run">
            {loading ? "Executando..." : "Forçar Discovery"}
          </Button>
        </div>
      </div>

      {loading && !grafData && !snmpData ? (
        <Skeleton className="h-32" />
      ) : (
        <>
          {/* KPIs */}
          <div className="flex flex-wrap gap-2"
            data-testid="discovery-kpis">
            <KpiMini icon={Server} label="Fontes"
              value={grafSources + snmpSources}
              tone="border-slate-200 bg-white" />
            <KpiMini icon={Wifi} label="Total ONUs"
              value={totalOnus}
              tone="border-emerald-200 bg-emerald-50/40" />
            <KpiMini icon={Radio} label="Graf/Zbx"
              value={grafCount}
              tone="border-blue-200 bg-blue-50/40" />
            <KpiMini icon={Cable} label="SNMP Direto"
              value={snmpCount}
              tone="border-violet-200 bg-violet-50/40" />
          </div>

          {/* Per-profile Grafana/Zabbix status */}
          <Card className="border-slate-200">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">
                Status por Fonte — Grafana / Zabbix
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 pt-2">
              {(grafData?.per_profile || []).map((p, i) => {
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
                      <div className="flex items-center gap-1.5 flex-wrap">
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
              {(grafData?.per_profile || []).length === 0 && !loading && (
                <div className="text-sm text-slate-400 text-center py-4">
                  Nenhuma fonte Grafana/Zabbix habilitada.
                </div>
              )}
            </CardContent>
          </Card>

          {/* Per-OLT SNMP status */}
          <Card className="border-violet-200"
            data-testid="discovery-snmp-status">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold
                flex items-center gap-2">
                <Cable className="w-4 h-4 text-violet-700" />
                Status por OLT — SNMP Direto
                <Badge variant="outline"
                  className="text-[9px] border-violet-300 text-violet-700">
                  cache 5min
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 pt-2">
              {(snmpData?.per_olt || []).map((p, i) => {
                const hasErr = !!p.error;
                const ok = !hasErr && (p.onu_count || 0) > 0;
                return (
                  <div key={`snmp-${i}`} className={`flex items-start gap-2 p-2
                    rounded border ${hasErr
                      ? "bg-rose-50/40 border-rose-200"
                      : ok
                        ? "bg-emerald-50/40 border-emerald-200"
                        : "bg-slate-50 border-slate-200"}`}
                    data-testid={`discovery-snmp-row-${i}`}>
                    {ok
                      ? <CheckCircle2 className="w-4 h-4 text-emerald-700
                          mt-0.5 flex-shrink-0" />
                      : <AlertTriangle className={`w-4 h-4 mt-0.5
                          flex-shrink-0 ${hasErr ? "text-rose-600" : "text-amber-600"}`} />}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="font-mono text-sm font-semibold">
                          OLT · {p.profile}
                        </span>
                        <Badge variant="outline"
                          className={`text-[9px] ${ok
                            ? "border-emerald-300 text-emerald-700"
                            : "border-slate-300 text-slate-500"}`}>
                          {p.onu_count || 0} ONUs
                        </Badge>
                        {p.polled_at && (
                          <span className="text-[10px] text-slate-500">
                            · {new Date(p.polled_at).toLocaleTimeString("pt-BR")}
                          </span>
                        )}
                      </div>
                      {hasErr && (
                        <div className="text-[11px] text-rose-700 mt-1">
                          Erro: {p.error}
                        </div>
                      )}
                      {p.errors && Object.keys(p.errors || {}).length > 0 && (
                        <div className="text-[11px] text-amber-700 mt-1">
                          Avisos: {Object.keys(p.errors).join(", ")}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              {(snmpData?.per_olt || []).length === 0 && !loading && (
                <div className="text-sm text-slate-400 text-center py-4">
                  Nenhuma OLT cadastrada para SNMP direto.
                  Cadastre em <b>Configurações → Integrações → OLT SNMP</b>.
                </div>
              )}
            </CardContent>
          </Card>

          {/* Guidance banner */}
          {grafData?.guidance && (
            <div className="rounded-lg border border-amber-300 bg-amber-50
              p-3 text-sm text-amber-900" data-testid="discovery-guidance">
              <div className="font-semibold mb-1 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4" />
                Ação requerida para discovery Grafana completo
              </div>
              <div className="text-xs">{grafData.guidance}</div>
            </div>
          )}

          {/* ONU table (merged) */}
          <Card className="border-slate-200"
            data-testid="discovery-onu-list">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">
                ONUs Descobertas ({totalOnus})
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {totalOnus === 0 ? (
                <div className="text-sm text-slate-400 py-6 text-center">
                  Nenhuma ONU descoberta.
                  {grafData?.fallback_required &&
                    " Configure Zabbix direto na aba Zabbix das credenciais."}
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
                        <th className="px-3 py-2">Vendor</th>
                        <th className="px-3 py-2">Fonte</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {mergedOnus.slice(0, 500).map((o, i) => {
                        const b = sourceBadge(o);
                        return (
                          <tr key={`${o.sn || o.hostid || o.mac || "x"}-${i}`}
                            className="hover:bg-slate-50"
                            data-testid={`discovery-onu-row-${i}`}>
                            <td className="px-3 py-1.5 font-mono">
                              {o.name || o.host || o.alias || "—"}
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
                            <td className="px-3 py-1.5 text-[10px] uppercase
                              text-slate-500">
                              {o.vendor || (o._source === "olt_snmp_cache"
                                ? "snmp" : "—")}
                            </td>
                            <td className="px-3 py-1.5">
                              <Badge variant="outline"
                                className={`text-[9px] ${b.tone}`}>
                                {b.label}
                              </Badge>
                            </td>
                          </tr>
                        );
                      })}
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
