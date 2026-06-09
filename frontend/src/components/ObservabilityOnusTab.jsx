/* ObservabilityOnusTab.jsx — Sub-aba ONT/ONU
   KPIs, status agregados e lista completa de ONUs/ONTs
   provenientes de /api/smartolt/clients-stock (cache local
   `db.smartolt_onus`, sincronizado a cada 15min). */
import React, { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle }
  from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import {
  Activity, Wifi, WifiOff, AlertTriangle, Search,
  RefreshCw, Radio, Signal,
} from "lucide-react";
import { api } from "@/lib/apiClient";

const apiGet = (path) => api.get(path);

// ─── helpers ───────────────────────────────────────────────
const STATUS_STYLES = {
  online: { bg: "bg-emerald-50", text: "text-emerald-700",
            border: "border-emerald-200", dot: "bg-emerald-500" },
  los: { bg: "bg-rose-50", text: "text-rose-700",
         border: "border-rose-200", dot: "bg-rose-500" },
  offline: { bg: "bg-slate-100", text: "text-slate-600",
             border: "border-slate-200", dot: "bg-slate-400" },
  "power fail": { bg: "bg-amber-50", text: "text-amber-700",
                  border: "border-amber-200", dot: "bg-amber-500" },
  authorized: { bg: "bg-sky-50", text: "text-sky-700",
                border: "border-sky-200", dot: "bg-sky-500" },
};

const styleFor = (status) => {
  const key = (status || "").toLowerCase();
  return STATUS_STYLES[key] || {
    bg: "bg-slate-50", text: "text-slate-600",
    border: "border-slate-200", dot: "bg-slate-300",
  };
};

const SIGNAL_TONES = {
  excellent: "text-emerald-700 bg-emerald-50 border-emerald-200",
  "very good": "text-emerald-700 bg-emerald-50 border-emerald-200",
  good: "text-green-700 bg-green-50 border-green-200",
  acceptable: "text-amber-700 bg-amber-50 border-amber-200",
  bad: "text-orange-700 bg-orange-50 border-orange-200",
  critical: "text-rose-700 bg-rose-50 border-rose-200",
};
const signalTone = (signal) =>
  SIGNAL_TONES[(signal || "").toLowerCase()]
  || "text-slate-600 bg-slate-50 border-slate-200";

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

const ObservabilityOnusTab = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(500);
  const [statusFilter, setStatusFilter] = useState("all");
  const [oltFilter, setOltFilter] = useState("all");
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const qs = new URLSearchParams();
        if (search) qs.set("search", search);
        qs.set("limit", String(limit));
        const data = await apiGet(`/api/smartolt/clients-stock?${qs}`);
        if (cancelled) return;
        setItems(data.items || []);
      } catch (e) {
        if (!cancelled) toast.error(`Falha ao carregar ONUs: ${e.message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [search, limit, refreshTick]);

  // ─── KPIs derivados ─────────────────────────────────────
  const kpis = useMemo(() => {
    const total = items.length;
    let online = 0, offline = 0, los = 0, powerFail = 0;
    let critical = 0, badSignal = 0;
    const olts = new Map();
    const zones = new Map();
    const statuses = new Map();
    items.forEach((it) => {
      const s = (it.status || "").toLowerCase();
      statuses.set(s || "unknown",
        (statuses.get(s || "unknown") || 0) + 1);
      if (s === "online") online += 1;
      else if (s === "los") los += 1;
      else if (s === "power fail") powerFail += 1;
      else if (s === "offline") offline += 1;
      const sig = (it.signal || "").toLowerCase();
      if (sig === "critical") critical += 1;
      if (sig === "bad") badSignal += 1;
      if (it.olt_name) {
        olts.set(it.olt_name, (olts.get(it.olt_name) || 0) + 1);
      }
      if (it.zone_name) {
        zones.set(it.zone_name, (zones.get(it.zone_name) || 0) + 1);
      }
    });
    const onlinePct = total ? Math.round((online / total) * 100) : 0;
    return {
      total, online, offline, los, powerFail,
      critical, badSignal, onlinePct,
      olts: [...olts.entries()].sort((a, b) => b[1] - a[1]),
      zones: [...zones.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8),
      statuses: [...statuses.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [items]);

  // ─── Lista filtrada por status/OLT ──────────────────────
  const filtered = useMemo(() => items.filter((it) => {
    if (statusFilter !== "all" &&
      (it.status || "").toLowerCase() !== statusFilter) return false;
    if (oltFilter !== "all" && it.olt_name !== oltFilter) return false;
    return true;
  }), [items, statusFilter, oltFilter]);

  return (
    <div className="space-y-5" data-testid="obs-onus-tab">
      {/* ─── KPIs ─── */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3"
        data-testid="obs-onus-kpis">
        <KpiCard icon={Radio} label="Total ONUs" value={kpis.total}
          tone="border-slate-200" testid="kpi-total" />
        <KpiCard icon={Wifi} label="Online"
          value={`${kpis.online} (${kpis.onlinePct}%)`}
          tone="border-emerald-200 bg-emerald-50/40"
          testid="kpi-online" />
        <KpiCard icon={WifiOff} label="LOS" value={kpis.los}
          tone="border-rose-200 bg-rose-50/40" testid="kpi-los" />
        <KpiCard icon={AlertTriangle} label="Power Fail"
          value={kpis.powerFail}
          tone="border-amber-200 bg-amber-50/40"
          testid="kpi-power-fail" />
        <KpiCard icon={Signal} label="Sinal Crítico"
          value={kpis.critical}
          tone="border-rose-200 bg-rose-50/40"
          testid="kpi-critical" />
        <KpiCard icon={Activity} label="Sinal Ruim"
          value={kpis.badSignal}
          tone="border-orange-200 bg-orange-50/40"
          testid="kpi-bad-signal" />
      </div>

      {/* ─── Status detalhado + Top OLTs ─── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="border-slate-200" data-testid="obs-onus-status-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold">
              Distribuição por Status
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="space-y-2">
              {kpis.statuses.length === 0 && !loading && (
                <div className="text-xs text-slate-400">
                  Sem dados de ONUs.
                </div>
              )}
              {kpis.statuses.map(([st, n]) => {
                const stl = styleFor(st);
                const pct = kpis.total
                  ? Math.round((n / kpis.total) * 100) : 0;
                return (
                  <div key={st} className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${stl.dot}`} />
                    <span className="text-sm capitalize w-28 flex-shrink-0">
                      {st || "(sem status)"}
                    </span>
                    <div className="flex-1 h-1.5 bg-slate-100 rounded">
                      <div className={`h-1.5 rounded ${stl.dot}`}
                        style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs text-slate-600 w-20 text-right">
                      {n} · {pct}%
                    </span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200" data-testid="obs-onus-olts-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold">
              Top OLTs (por nº de ONUs)
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="space-y-1.5">
              {kpis.olts.slice(0, 6).map(([olt, n]) => (
                <div key={olt}
                  className="flex items-center justify-between text-sm">
                  <span className="text-slate-700 font-mono text-xs truncate
                    max-w-[60%]">
                    {olt}
                  </span>
                  <Badge variant="outline" className="text-xs">
                    {n} ONUs
                  </Badge>
                </div>
              ))}
              {kpis.olts.length === 0 && !loading && (
                <div className="text-xs text-slate-400">
                  Sem dados.
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ─── Filtros + busca + refresh ─── */}
      <div className="flex flex-wrap items-end gap-2"
        data-testid="obs-onus-filters">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-slate-500 font-medium">
            Busca (nome / SN / endereço)
          </label>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-2 top-1/2
              -translate-y-1/2 text-slate-400" />
            <Input value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filtrar ONUs..."
              className="pl-8"
              data-testid="obs-onus-search" />
          </div>
        </div>
        <div className="min-w-[140px]">
          <label className="text-xs text-slate-500 font-medium">Status</label>
          <select value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full h-9 border border-slate-200 rounded px-2 text-sm"
            data-testid="obs-onus-status-filter">
            <option value="all">Todos</option>
            <option value="online">Online</option>
            <option value="los">LOS</option>
            <option value="offline">Offline</option>
            <option value="power fail">Power Fail</option>
          </select>
        </div>
        <div className="min-w-[160px]">
          <label className="text-xs text-slate-500 font-medium">OLT</label>
          <select value={oltFilter}
            onChange={(e) => setOltFilter(e.target.value)}
            className="w-full h-9 border border-slate-200 rounded px-2 text-sm"
            data-testid="obs-onus-olt-filter">
            <option value="all">Todas</option>
            {kpis.olts.map(([olt]) => (
              <option key={olt} value={olt}>{olt}</option>
            ))}
          </select>
        </div>
        <div className="min-w-[100px]">
          <label className="text-xs text-slate-500 font-medium">Limite</label>
          <select value={limit}
            onChange={(e) => setLimit(parseInt(e.target.value, 10))}
            className="w-full h-9 border border-slate-200 rounded px-2 text-sm"
            data-testid="obs-onus-limit">
            <option value="200">200</option>
            <option value="500">500</option>
            <option value="1000">1000</option>
            <option value="2000">2000</option>
          </select>
        </div>
        <Button variant="outline"
          onClick={() => setRefreshTick((t) => t + 1)}
          disabled={loading}
          data-testid="obs-onus-refresh">
          <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} />
          Atualizar
        </Button>
      </div>

      {/* ─── Lista ─── */}
      <Card className="border-slate-200" data-testid="obs-onus-list-card">
        <CardHeader className="pb-2 flex flex-row items-center
          justify-between">
          <CardTitle className="text-sm font-semibold">
            ONT/ONU ({filtered.length} de {items.length})
          </CardTitle>
          <span className="text-xs text-slate-400">
            Cache local SmartOLT · sync a cada 15min
          </span>
        </CardHeader>
        <CardContent className="pt-0">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-sm text-slate-400 py-6 text-center">
              Nenhuma ONU encontrada com os filtros aplicados.
            </div>
          ) : (
            <div className="overflow-x-auto max-h-[600px] overflow-y-auto
              border border-slate-100 rounded">
              <table className="min-w-full text-xs"
                data-testid="obs-onus-table">
                <thead className="bg-slate-50 sticky top-0 z-10">
                  <tr className="text-left text-slate-500 uppercase
                    text-[10px] tracking-wider">
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Nome</th>
                    <th className="px-3 py-2">SN</th>
                    <th className="px-3 py-2">OLT</th>
                    <th className="px-3 py-2">CTO Port</th>
                    <th className="px-3 py-2">Sinal</th>
                    <th className="px-3 py-2">Zona</th>
                    <th className="px-3 py-2">Endereço</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filtered.slice(0, 1000).map((it, i) => {
                    const stl = styleFor(it.status);
                    return (
                      <tr key={`${it.sn}-${i}`}
                        className="hover:bg-slate-50"
                        data-testid={`obs-onu-row-${i}`}>
                        <td className="px-3 py-1.5">
                          <span className={`inline-flex items-center
                            gap-1 px-1.5 py-0.5 rounded border text-[10px]
                            font-medium ${stl.bg} ${stl.text} ${stl.border}`}>
                            <span className={`w-1.5 h-1.5 rounded-full
                              ${stl.dot}`} />
                            {it.status || "—"}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 font-medium
                          text-slate-800 max-w-[180px] truncate"
                          title={it.name}>
                          {it.name || "—"}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">
                          {it.sn || "—"}
                        </td>
                        <td className="px-3 py-1.5 text-slate-700">
                          {it.olt_name || "—"}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">
                          {it.cto_port || "—"}
                        </td>
                        <td className="px-3 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded border
                            text-[10px] font-medium
                            ${signalTone(it.signal)}`}>
                            {it.signal || "—"}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-slate-600
                          max-w-[140px] truncate" title={it.zone_name}>
                          {it.zone_name || "—"}
                        </td>
                        <td className="px-3 py-1.5 text-slate-500
                          max-w-[200px] truncate" title={it.address}>
                          {it.address || "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filtered.length > 1000 && (
                <div className="text-xs text-slate-400 px-3 py-2 bg-slate-50">
                  Mostrando primeiras 1000 de {filtered.length}.
                  Use os filtros ou aumente o limite.
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default ObservabilityOnusTab;
