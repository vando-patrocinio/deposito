/* =============================================================
   RedeIaPanel — Painel administrativo da Rede IA
   - Visão geral / KPIs
   - Lista de CTOs (filtros)
   - Pendências de validação (Aprovar/Solicitar correção/Rejeitar)
   - Histórico de alterações
   - Bairros / VLAN map (admin)
   - Diretrizes da rede_IA (system prompt)
   - Fluxograma (React Flow) — em sub-aba
============================================================= */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import {
  Line, LineChart, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { api } from "@/api";
import { fmtAddress } from "@/utils/format";
import { Card } from "@/ui";
import { toast } from "sonner";
import RedeIaMap from "@/RedeIaMap";
import LigoMapsPanel from "@/LigoMapsPanel";
import ReconcileAuditPanel from "@/ReconcileAuditPanel";
import CTOLocationViewer from "@/CTOLocationViewer";
import CTOOccupancyPanel from "@/CTOOccupancyPanel";
import { KpiCard, AlertCard } from "@/components/Dashboard2026";

const TABS = [
  { id: "overview", label: "Painel" },
  { id: "ctos", label: "CTOs" },
  { id: "ports_base", label: "Base de Portas" },
  { id: "occupancy", label: "Ocupação" },
  { id: "pendencies", label: "Pendências" },
  { id: "map", label: "Mapa interativo" },
  { id: "docs_map", label: "Documentação (As-Built)" },
  { id: "reconcile", label: "Conciliação" },
  { id: "bairros", label: "Bairros / VLAN" },
  { id: "orphan_cables", label: "Cabos órfãos" },
  { id: "history", label: "Histórico" },
  { id: "diretrizes", label: "Diretrizes" },
  { id: "audit", label: "Auditoria", auditorOnly: true },
];

const STATUS_BADGE = {
  pending_validation: { l: "Aguardando validação", c: "#ca8a04", bg: "#fef9c3" },
  pending_correction: { l: "Correção solicitada", c: "#9a3412", bg: "#fed7aa" },
  approved: { l: "Aprovada", c: "#15803d", bg: "#dcfce7" },
  rejected: { l: "Rejeitada", c: "#b91c1c", bg: "#fee2e2" },
};

export default function RedeIaPanel({ currentUser }) {
  const [tab, setTab] = useState("overview");
  // iter186 — escuta evento global pra mudar de tab (do RedeIaMap)
  useEffect(() => {
    const handler = (e) => {
      const t = e?.detail?.tab;
      if (t) setTab(t);
    };
    window.addEventListener("rede-ia-navigate", handler);
    return () => window.removeEventListener("rede-ia-navigate", handler);
  }, []);
  const isAuditor = !!currentUser
    && (currentUser.is_super_admin
        || (currentUser.role || "").toLowerCase() === "auditor");
  const [notifCount, setNotifCount] = useState(0);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState([]);

  const loadNotifs = useCallback(async () => {
    try {
      const r = await api.redeIaNotifications(false);
      setNotifs(r.items || []);
      setNotifCount(r.unread || 0);
    } catch (_) {}
  }, []);
  useEffect(() => {
    loadNotifs();
    const id = setInterval(loadNotifs, 25000);
    return () => clearInterval(id);
  }, [loadNotifs]);

  const markAll = async () => {
    try { await api.redeIaNotifMarkRead(null, true); await loadNotifs(); }
    catch (e) { await window.alert(e?.response?.data?.detail || "Erro"); }
  };
  const markOne = async (id) => {
    try { await api.redeIaNotifMarkRead(id, false); await loadNotifs(); }
    catch (_) {}
  };

  return (
    <div data-testid="rede-ia-panel" style={{ display: "grid", gap: 16 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                         flexWrap: "wrap", gap: 8 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0,
                         color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
            Rede IA
          </h1>
          <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: 13 }}>
            Supervisora inteligente da rede FTTH — padroniza CTOs, valida topologia e mantém
            o fluxograma sempre atualizado.
          </p>
        </div>
        {/* Bell de notificações */}
        <div style={{ position: "relative" }}>
          <button data-testid="rede-ia-notif-bell"
            onClick={() => setNotifOpen(!notifOpen)}
            style={{
              position: "relative", padding: "8px 14px", borderRadius: 10,
              background: notifCount > 0 ? "#dc2626" : "var(--bg-surface)",
              color: notifCount > 0 ? "#fff" : "var(--text-primary)",
              border: "1px solid var(--border-default)",
              cursor: "pointer", fontSize: 14, fontWeight: 700,
              display: "inline-flex", alignItems: "center", gap: 8,
            }}>
            Notificações
            {notifCount > 0 && (
              <span style={{
                background: "#fff", color: "#dc2626", borderRadius: 99,
                padding: "1px 7px", fontSize: 11, fontWeight: 800,
              }}>{notifCount}</span>
            )}
          </button>
          {notifOpen && (
            <div data-testid="rede-ia-notif-panel"
              style={{
                position: "absolute", right: 0, top: "calc(100% + 6px)",
                width: 360, maxHeight: 480, overflow: "auto",
                background: "var(--bg-surface)",
                border: "1px solid var(--border-default)",
                borderRadius: 12, padding: 0, zIndex: 200,
                boxShadow: "0 12px 32px rgba(0,0,0,0.18)",
              }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "center", padding: "12px 14px",
                              borderBottom: "1px solid var(--border-default)" }}>
                <strong style={{ fontSize: 13 }}>Notificações ({notifCount} novas)</strong>
                <button onClick={markAll}
                  style={{ padding: "4px 10px", borderRadius: 6, border: 0,
                            background: "#0f172a", color: "#fff",
                            fontSize: 11, fontWeight: 700, cursor: "pointer" }}>
                  Marcar todas
                </button>
              </div>
              {notifs.length === 0 && (
                <div style={{ padding: 20, textAlign: "center",
                                 color: "var(--text-muted)", fontSize: 12 }}>
                  Nenhuma notificação ainda.
                </div>
              )}
              {notifs.map((n) => (
                <div key={n.id} onClick={() => !n.read && markOne(n.id)}
                  style={{
                    padding: "10px 14px",
                    borderBottom: "1px solid var(--border-default)",
                    cursor: n.read ? "default" : "pointer",
                    background: n.read ? "transparent" : "#fef3c7",
                  }}>
                  <div style={{ display: "flex", justifyContent: "space-between",
                                  gap: 8, alignItems: "flex-start" }}>
                    <strong style={{ fontSize: 12, color: "var(--text-primary)",
                                       lineHeight: 1.3 }}>{n.title}</strong>
                    {!n.read && <span style={{ width: 8, height: 8,
                                                  background: "#dc2626",
                                                  borderRadius: 99, marginTop: 4,
                                                  flexShrink: 0 }} />}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-secondary)",
                                  marginTop: 4, lineHeight: 1.4 }}>
                    {n.message}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)",
                                  marginTop: 4 }}>
                    {new Date(n.created_at).toLocaleString("pt-BR")}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </header>

      <div style={{ display: "flex", gap: 4, flexWrap: "wrap",
                       borderBottom: "1px solid var(--border-default)", paddingBottom: 0 }}>
        {TABS.filter((t) => !t.auditorOnly || isAuditor).map((t) => (
          <button key={t.id} data-testid={`rede-ia-tab-${t.id}`}
                  onClick={() => setTab(t.id)}
                  style={{
                    padding: "10px 14px", borderRadius: "6px 6px 0 0",
                    background: tab === t.id ? "var(--bg-surface)" : "transparent",
                    border: tab === t.id ? "1px solid var(--border-default)"
                                          : "1px solid transparent",
                    borderBottom: tab === t.id ? "1px solid var(--bg-surface)" : "none",
                    color: tab === t.id ? "var(--text-primary)" : "var(--text-secondary)",
                    fontWeight: tab === t.id ? 700 : 500, fontSize: 13, cursor: "pointer",
                    marginBottom: -1,
                  }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview />}
      {tab === "ctos" && <CTOsList />}
      {tab === "ports_base" && <PortBaseTab />}
      {tab === "pendencies" && <Pendencies />}
      {tab === "occupancy" && <CTOOccupancyPanel />}
      {tab === "map" && <RedeIaMap />}
      {tab === "docs_map" && <LigoMapsPanel />}
      {tab === "reconcile" && <ReconcileAuditPanel />}
      {tab === "bairros" && <BairrosManager />}
      {tab === "orphan_cables" && <OrphanCablesPanel />}
      {tab === "history" && <HistoryList />}
      {tab === "diretrizes" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <DiretrizesEditor />
          <CableSlackEditor />
        </div>
      )}
      {tab === "audit" && isAuditor && <AuditCables currentUser={currentUser} />}
    </div>
  );
}

/* ------------- Overview ------------- */
function Overview() {
  const [ctos, setCtos] = useState([]);
  const [pend, setPend] = useState([]);
  const [bairros, setBairros] = useState([]);
  const [mapData, setMapData] = useState({ vlans: [], ces: [], cables: [] });
  const [techStats, setTechStats] = useState({ by_technician: [], by_branch: [] });
  const [statsPeriod, setStatsPeriod] = useState("all");
  const [fiberKpi, setFiberKpi] = useState(null);
  const [fiberKpiDays, setFiberKpiDays] = useState(30);
  const [fiberAlerts, setFiberAlerts] = useState({ alerts: [], threshold: 200 });
  // iter211f — estoque total de fibras (empresa + técnicos) por tipo
  const [fiberStock, setFiberStock] = useState(null);
  useEffect(() => {
    api.redeIaCtosList().then((r) => setCtos(r.items || []));
    api.redeIaPendencies().then((r) => setPend(r.items || []));
    api.redeIaBairros().then((r) => setBairros(r.items || []));
    api.redeIaMapData().then((r) => setMapData(r)).catch(() => {});
    api.redeIaFiberAlerts(200).then(setFiberAlerts).catch(() => {});
    // Estoque de fibras agregado (empresa + todos os técnicos)
    api.stokStock().then((stock) => {
      const totals = { fibra_06fo: 0, fibra_12fo: 0, fibra_24fo: 0,
                        fibra_48fo: 0, fibra_96fo: 0 };
      Object.values(stock || {}).forEach((loc) => {
        Object.keys(totals).forEach((k) => {
          totals[k] += Number(loc?.[k] || 0);
        });
      });
      setFiberStock(totals);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    api.redeIaFiberKpi(fiberKpiDays).then(setFiberKpi).catch(() => {});
  }, [fiberKpiDays]);
  useEffect(() => {
    api.redeIaStatsByTechnician(statsPeriod).then(setTechStats).catch(() => {});
  }, [statsPeriod]);
  const approved = ctos.filter((c) => c.status === "approved").length;
  const totalPorts = ctos.reduce((acc, c) => acc + (c.capacity || 0), 0);
  const usedPorts = ctos.reduce(
    (acc, c) => acc + ((c.ports || []).filter((p) => p.status === "used").length), 0,
  );
  const occupancyRate = totalPorts
    ? Math.round((usedPorts / totalPorts) * 100) : 0;
  // Integração SmartOLT
  const ctosWithOnu = (mapData.ctos || []).filter((c) => (c.health?.total || 0) > 0).length;
  const totalCableMeters = (mapData.cables || []).reduce(
    (s, c) => s + (c.length_m || 0), 0);
  const cableByType = {};
  (mapData.cables || []).forEach((c) => {
    cableByType[c.type] = (cableByType[c.type] || 0) + (c.length_m || 0);
  });
  // Alertas
  const criticalVlans = (mapData.vlans || []).filter((v) => v.avg_score < 50);
  const warningVlans = (mapData.vlans || []).filter((v) => v.avg_score >= 50 && v.avg_score < 75);
  const highOccupancy = occupancyRate >= 80;
  const noCtos = ctos.length === 0;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Strip de alertas */}
      {(criticalVlans.length > 0 || pend.length > 0 || highOccupancy || noCtos) && (
        <div data-testid="rede-ia-alerts-strip" style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit,minmax(230px,1fr))",
          gap: 10,
        }}>
          {noCtos && (
            <AlertCard tone="info" icon=""
              testId="rede-ia-alert-no-ctos"
              title="Nenhuma CTO cadastrada"
              detail="Use o app do técnico para cadastrar as primeiras CTOs." />
          )}
          {criticalVlans.length > 0 && (
            <AlertCard tone="bad" icon=""
              testId="rede-ia-alert-critical-vlans"
              title={`${criticalVlans.length} VLAN${criticalVlans.length !== 1 ? "s" : ""} em estado crítico`}
              detail={criticalVlans.slice(0, 3).map((v) =>
                `VLAN ${v.vlan} (${v.avg_score}%)`).join(" · ")} />
          )}
          {warningVlans.length > 0 && criticalVlans.length === 0 && (
            <AlertCard tone="warn" icon=""
              testId="rede-ia-alert-warning-vlans"
              title={`${warningVlans.length} VLAN${warningVlans.length !== 1 ? "s" : ""} em atenção`}
              detail="Sinal médio entre 50% e 75% — vale fiscalizar." />
          )}
          {pend.length > 0 && (
            <AlertCard tone="warn" icon="⏳"
              testId="rede-ia-alert-pendencies"
              title={`${pend.length} CTO${pend.length !== 1 ? "s" : ""} aguardando validação`}
              detail="Gestor de Rede deve aprovar para sincronizar com SmartOLT." />
          )}
          {highOccupancy && (
            <AlertCard tone="warn" icon=""
              testId="rede-ia-alert-high-occupancy"
              title={`Taxa de ocupação ${occupancyRate}% — alta`}
              detail="Considere planejar expansão (mais portas / CTOs)." />
          )}
        </div>
      )}

      {/* KPIs contextuais 2026 */}
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(200px,1fr))",
                       gap: 12 }}>
        <KpiCard
          testId="rede-ia-kpi-ctos-total"
          label="CTOs cadastradas"
          value={ctos.length}
          tone="info"
          hint={`${approved} aprovadas · ${pend.length} pendentes`} />
        <KpiCard
          testId="rede-ia-kpi-ctos-approved"
          label="CTOs aprovadas"
          value={approved}
          tone={ctos.length > 0 && approved === ctos.length ? "good"
               : ctos.length > 0 && approved / ctos.length > 0.7 ? "good"
               : "warn"}
          progress={ctos.length > 0 ? (approved / ctos.length) * 100 : 0}
          hint={ctos.length > 0
            ? `${Math.round((approved / ctos.length) * 100)}% do total`
            : "Sem CTOs ainda"} />
        <KpiCard
          testId="rede-ia-kpi-pendencies"
          label="Pendências de validação"
          value={pend.length}
          tone={pend.length === 0 ? "good"
               : pend.length < 5 ? "warn" : "bad"}
          hint={pend.length === 0
            ? "Tudo em dia"
            : "Aguardando ação do gestor"} />
        <KpiCard
          testId="rede-ia-kpi-bairros"
          label="Bairros mapeados"
          value={bairros.length}
          tone="info"
          hint={`${mapData.vlans?.length || 0} VLAN(s) monitoradas`} />
        <KpiCard
          testId="rede-ia-kpi-ports"
          label="Portas ocupadas"
          value={`${usedPorts} / ${totalPorts}`}
          tone={occupancyRate >= 80 ? "bad"
               : occupancyRate >= 60 ? "warn" : "good"}
          progress={occupancyRate}
          hint={`${occupancyRate}% utilizadas`} />
        <KpiCard
          testId="rede-ia-kpi-cables"
          label="Cabo óptico total"
          value={(totalCableMeters / 1000).toFixed(2)}
          unit="km"
          tone="info"
          hint={`${mapData.cables?.length || 0} cabo(s) cadastrado(s)`} />
        {fiberKpi && (
          <KpiCard
            testId="rede-ia-kpi-fiber-week"
            label={`Fibra lançada (${fiberKpiDays}d)`}
            value={fiberKpi.total_meters}
            unit="m"
            tone={fiberKpi.total_meters > 0 ? "good" : "info"}
            hint={`${fiberKpi.cables_count} cabo(s) · 6FO ${fiberKpi.by_type["6fo"]}m · 12FO ${fiberKpi.by_type["12fo"]}m · 24FO ${fiberKpi.by_type["24fo"]}m`} />
        )}
      </div>

      {/* iter211f — Card de estoque atual de fibras (agregado) */}
      {fiberStock && (
        <Card data-testid="rede-ia-fiber-stock" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center",
                          justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                              color: "#0f172a" }}>Estoque de Fibras</h3>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                Saldo agregado (empresa + técnicos). Atualizado quando um cabo
                é lançado no mapa.
              </div>
            </div>
            <span style={{ fontSize: 11, fontWeight: 700,
                              padding: "3px 8px", borderRadius: 999,
                              background: "#dbeafe", color: "#1e40af" }}>
              auto-baixa ativa
            </span>
          </div>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(160px,1fr))",
                          gap: 10 }}>
            {[
              { key: "fibra_06fo", label: "6 FO", color: "#facc15" },
              { key: "fibra_12fo", label: "12 FO", color: "#fb923c" },
              { key: "fibra_24fo", label: "24 FO", color: "#ef4444" },
              { key: "fibra_48fo", label: "48 FO", color: "#8b5cf6" },
              { key: "fibra_96fo", label: "96 FO", color: "#0f172a" },
            ].map((it) => {
              const meters = fiberStock[it.key] || 0;
              const isLow = meters < 200 && meters >= 0;
              const isNeg = meters < 0;
              const valueLabel = Math.abs(meters) >= 1000
                ? `${(meters / 1000).toFixed(2)} km`
                : `${meters} m`;
              return (
                <div key={it.key}
                  data-testid={`fiber-stock-${it.key}`}
                  style={{
                    padding: 12,
                    borderRadius: 8,
                    border: "1px solid " + (isNeg ? "#fecaca"
                                              : isLow ? "#fde68a" : "#e2e8f0"),
                    background: isNeg ? "#fef2f2"
                                  : isLow ? "#fffbeb" : "#fff",
                  }}>
                  <div style={{ display: "flex", alignItems: "center",
                                  gap: 8, marginBottom: 6 }}>
                    <span style={{
                      display: "inline-block", width: 14, height: 14,
                      borderRadius: 4, background: it.color,
                      border: "2px solid #fff",
                      boxShadow: "0 0 0 1px rgba(0,0,0,0.08)",
                    }} />
                    <span style={{ fontSize: 12, fontWeight: 800,
                                      color: "#475569",
                                      textTransform: "uppercase",
                                      letterSpacing: 0.5 }}>{it.label}</span>
                  </div>
                  <div style={{
                    fontSize: 22, fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                    color: isNeg ? "#dc2626"
                              : isLow ? "#d97706" : "#0f172a",
                    lineHeight: 1,
                  }}>{valueLabel}</div>
                  {isNeg && (
                    <div style={{ fontSize: 10, fontWeight: 700,
                                    color: "#dc2626", marginTop: 4 }}>
                      ️ saldo negativo
                    </div>
                  )}
                  {isLow && !isNeg && (
                    <div style={{ fontSize: 10, fontWeight: 700,
                                    color: "#d97706", marginTop: 4 }}>
                      ️ saldo baixo
                    </div>
                  )}
                  {!isLow && !isNeg && (
                    <div style={{ fontSize: 10, color: "#64748b",
                                    marginTop: 4 }}>
                      em estoque
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Gráfico temporal de fibra lançada + alertas de saldo */}
      {fiberKpi && (
        <FiberTimelineCard kpi={fiberKpi} days={fiberKpiDays}
                            onChangeDays={setFiberKpiDays}
                            alerts={fiberAlerts} />
      )}

      {/* Integração SmartOLT */}
      <Card style={{ padding: 16 }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 15,
                       display: "flex", alignItems: "center", gap: 8 }}>
          Integração SmartOLT IA
          <span style={{ fontSize: 11, fontWeight: 500, color: "var(--text-muted)" }}>
            (rede_IA cruza CTOs com ONUs reais)
          </span>
        </h3>
        <div style={{ display: "grid",
                         gridTemplateColumns: "repeat(auto-fit, minmax(180px,1fr))",
                         gap: 10 }}>
          <MiniKpi label="CTOs com ONUs detectadas"
            value={`${ctosWithOnu} / ${mapData.ctos?.length || 0}`}
            color="#f28c28" />
          <MiniKpi label="VLANs monitoradas"
            value={mapData.vlans?.length || 0} color="#7c3aed" />
          <MiniKpi label="CEs (Caixas Emenda)"
            value={mapData.ces?.length || 0} color="#1e40af" />
          <MiniKpi label="Cabos cadastrados"
            value={`${mapData.cables?.length || 0} (${(totalCableMeters/1000).toFixed(2)} km)`}
            color="#ea580c" />
        </div>

        {Object.keys(cableByType).length > 0 && (
          <div style={{ marginTop: 12, padding: 10,
                          background: "var(--bg-surface-2)", borderRadius: 8,
                          fontSize: 12 }}>
            <strong>Comprimento por tipo:</strong>{" "}
            {Object.entries(cableByType).map(([type, m]) => (
              <span key={type} style={{ marginRight: 14 }}>
                {type.toUpperCase()}: <strong>{(m/1000).toFixed(2)} km</strong>
              </span>
            ))}
          </div>
        )}

        {/* iter180 — sync VLAN do SmartOLT → subscribers */}
        <SmartoltVlanSyncCard />

        {/* iter181 — Sentinela IA: threshold de aprovação ajustável */}
        <SentinelaThresholdCard />

        {/* iter182 — Alertas de degradação de sinal */}
        <SignalDegradationCard />
      </Card>

      {/* CTOs por Técnico + Filial */}
      <CtoStatsBlock stats={techStats}
                      period={statsPeriod}
                      onChangePeriod={setStatsPeriod} />

      {/* iter180 — Sinal por VLAN agrupado por OLT */}
      {mapData.vlans_by_olt && mapData.vlans_by_olt.length > 0 && (
        <div data-testid="vlans-by-olt-grid" style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
          gap: 12,
        }}>
          {mapData.vlans_by_olt.map((olt) => {
            const oltDbm = olt.avg_signal_dbm;
            const hasDbm = typeof oltDbm === "number";
            const sigStatus = hasDbm
              ? (oltDbm >= -20 ? "ok" : oltDbm >= -25 ? "warning" : "critical")
              : "neutral";
            const headerBg = sigStatus === "critical" ? "#fee2e2"
              : sigStatus === "warning" ? "#fef3c7"
              : sigStatus === "ok" ? "#dcfce7" : "#e0e7ff";
            const headerFg = sigStatus === "critical" ? "#991b1b"
              : sigStatus === "warning" ? "#92400e"
              : sigStatus === "ok" ? "#166534" : "#3730a3";
            return (
              <Card key={olt.olt_name}
                    data-testid={`olt-vlans-card-${olt.olt_name}`}
                    style={{ padding: 0, overflow: "hidden" }}>
                <div style={{
                  padding: "12px 16px", background: headerBg, color: headerFg,
                  display: "flex", alignItems: "center", gap: 12,
                  borderBottom: `1px solid ${headerFg}33`,
                }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 800, fontSize: 14,
                                      fontFamily: "monospace" }}>
                      {olt.olt_name}
                    </div>
                    <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2 }}>
                      {olt.vlan_count} VLANs · {olt.onu_count} ONUs online
                    </div>
                  </div>
                  <div style={{ minWidth: 92, textAlign: "center",
                                    padding: "6px 10px", borderRadius: 8,
                                    background: "rgba(255,255,255,0.5)" }}>
                    <div style={{ fontSize: 18, fontWeight: 800, lineHeight: 1 }}>
                      {hasDbm ? oltDbm.toFixed(1) : "—"}
                    </div>
                    <div style={{ fontSize: 9, letterSpacing: 1,
                                      opacity: 0.8, marginTop: 1 }}>
                      dBm méd
                    </div>
                  </div>
                </div>

                <div style={{ maxHeight: 360, overflowY: "auto", padding: 8 }}>
                  {olt.vlans.map((v) => {
                    const dbm = v.avg_signal_dbm;
                    const hd = typeof dbm === "number";
                    const st = hd ? (dbm >= -20 ? "ok"
                      : dbm >= -25 ? "warning" : "critical") : "neutral";
                    const bg = st === "critical" ? "#fee2e2"
                      : st === "warning" ? "#fef3c7"
                      : st === "ok" ? "#dcfce7" : "#f1f5f9";
                    const fg = st === "critical" ? "#991b1b"
                      : st === "warning" ? "#92400e"
                      : st === "ok" ? "#166534" : "#475569";
                    return (
                      <div key={v.vlan}
                           data-testid={`olt-${olt.olt_name}-vlan-${v.vlan}`}
                           style={{
                             display: "flex", alignItems: "center", gap: 10,
                             padding: "6px 10px", marginBottom: 4,
                             borderRadius: 6, background: bg,
                             border: `1px solid ${fg}22`,
                           }}>
                        <div style={{
                          fontFamily: "monospace", fontWeight: 800,
                          fontSize: 12, color: fg, minWidth: 70,
                        }}>VLAN {v.vlan}</div>
                        <div style={{
                          fontSize: 11, color: fg, flex: 1, opacity: 0.85,
                        }}>{v.onu_count} ONUs</div>
                        <div style={{
                          minWidth: 70, textAlign: "right",
                          fontFamily: "monospace", fontWeight: 800,
                          fontSize: 13, color: fg,
                        }}>
                          {hd ? `${dbm.toFixed(1)}` : "—"}
                          <span style={{ fontSize: 9, marginLeft: 2,
                                            opacity: 0.7 }}>dBm</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Saúde por VLAN (consolidado — todas as VLANs do provedor) */}
      {mapData.vlans && mapData.vlans.length > 0 && (
        <Card style={{ padding: 16 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>
            Média de sinal por VLAN (vinda do SmartOLT)
          </h3>
          <p style={{ margin: "0 0 12px", fontSize: 11.5,
                          color: "var(--text-muted)", lineHeight: 1.4 }}>
            Sinal RX médio em 1490 nm extraído das ONUs online.
            Ótimo ≥ -20 dBm · Atenção -20 a -25 · Crítico &lt; -25 dBm.
          </p>
          <div style={{ display: "grid", gap: 8 }}>
            {mapData.vlans.map((v) => {
              const dbm = v.avg_signal_dbm;
              const hasDbm = typeof dbm === "number";
              // iter180 — Cor por faixa de dBm (quando temos sinal real),
              // fallback no score quando não temos.
              let sig_status;
              if (hasDbm) {
                sig_status = dbm >= -20 ? "ok"
                  : dbm >= -25 ? "warning" : "critical";
              } else {
                sig_status = v.avg_score < 50 ? "critical"
                  : v.avg_score < 75 ? "warning" : "ok";
              }
              const smartoltOnly = v.source === "smartolt_only";
              const bg = sig_status === "critical" ? "#fee2e2"
                : sig_status === "warning" ? "#fef3c7"
                : sig_status === "ok" ? "#dcfce7" : "#f1f5f9";
              const fg = sig_status === "critical" ? "#991b1b"
                : sig_status === "warning" ? "#92400e"
                : sig_status === "ok" ? "#166534" : "#475569";
              return (
                <div key={v.vlan} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 14px", borderRadius: 10,
                  background: bg, border: `1px solid ${fg}33`,
                }}>
                  <div style={{ fontWeight: 800, fontSize: 14, color: fg,
                                  minWidth: 130, display: "flex",
                                  alignItems: "center", gap: 6 }}>
                    VLAN {v.vlan}
                    {smartoltOnly && (
                      <span style={{ fontSize: 9, padding: "1px 5px",
                                        borderRadius: 4,
                                        background: "rgba(0,0,0,0.10)",
                                        fontWeight: 700 }}>
                        sem CTO
                      </span>
                    )}
                  </div>

                  {/* iter180 — Sinal médio em dBm: número primário */}
                  <div data-testid={`vlan-${v.vlan}-dbm`} style={{
                    minWidth: 120, textAlign: "center",
                    padding: "6px 10px", borderRadius: 8,
                    background: hasDbm ? `${fg}1a` : "rgba(0,0,0,0.06)",
                    color: fg, fontWeight: 800,
                  }}>
                    <div style={{ fontSize: 18, lineHeight: 1.1 }}>
                      {hasDbm ? dbm.toFixed(1) : "—"}
                    </div>
                    <div style={{ fontSize: 9, opacity: 0.8,
                                      letterSpacing: 1, marginTop: 1 }}>
                      {hasDbm ? "dBm RX" : "sem dado"}
                    </div>
                  </div>

                  {/* Barra de score auxiliar */}
                  <div style={{ flex: 1 }}>
                    <div style={{
                      height: 6, borderRadius: 99,
                      background: "rgba(0,0,0,0.08)",
                      overflow: "hidden",
                    }}>
                      <div style={{
                        height: "100%", width: `${v.avg_score}%`,
                        background: fg, transition: "width .3s",
                      }} />
                    </div>
                    <div style={{ fontSize: 10, color: fg, marginTop: 2,
                                      opacity: 0.8 }}>
                      score {v.avg_score}%
                    </div>
                  </div>

                  <div style={{ fontSize: 11, color: fg, minWidth: 180,
                                  textAlign: "right" }}>
                    {v.cto_count > 0 && (
                      <span>{v.cto_count} CTOs · </span>
                    )}
                    {v.subscriber_count > 0 && (
                      <strong>{v.subscriber_count} assin.</strong>
                    )}
                    {/* iter181 — clientes com porta CTO designada (≠ total
                        assinantes; mostra cobertura de mapeamento físico) */}
                    {v.cto_assigned_count > 0 && (
                      <span title="Clientes com porta CTO designada nesta VLAN"
                            data-testid={`vlan-${v.vlan}-cto-assigned`}
                            style={{ marginLeft: 4, padding: "1px 6px",
                                       borderRadius: 6,
                                       background: `${fg}22`,
                                       fontWeight: 700, fontSize: 10.5 }}>
                        {v.cto_assigned_count} c/ porta
                      </span>
                    )}
                    {v.onu_online_count > 0 && (
                      <span> · {v.onu_online_count} ONUs</span>
                    )}
                    {v.cto_count > 0 && (
                      <div style={{ marginTop: 2 }}>
                        {v.critical || 0}{v.warning || 0}{v.ok || 0}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <p style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted)" }}>
            ℹ️ Para atualizar o dado, use o card “Sincronizar VLAN do SmartOLT”
            logo acima. O worker automático também roda a cada 1h em background.
          </p>
        </Card>
      )}
    </div>
  );
}

/* ------------- CTO Stats (por técnico + filial) ------------- */
function CtoStatsBlock({ stats, period, onChangePeriod }) {
  const byTech = stats?.by_technician || [];
  const byBranch = stats?.by_branch || [];
  if (byTech.length === 0 && byBranch.length === 0) return null;
  const techMax = Math.max(1, ...byTech.map((t) => t.total));
  const branchMax = Math.max(1, ...byBranch.map((b) => b.total));
  const periodLabel = { all: "Geral", month: "Este mês", week: "Últimos 7 dias" };
  return (
    <Card style={{ padding: 16 }} data-testid="cto-stats-by-technician">
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12, flexWrap: "wrap",
                       gap: 8 }}>
        <h3 style={{ margin: 0, fontSize: 15,
                       display: "flex", alignItems: "center", gap: 8 }}>
          Ranking de CTOs · {periodLabel[period] || "Geral"}
          <span style={{ fontSize: 11, fontWeight: 500,
                           color: "var(--text-muted)" }}>
            ({stats.total_ctos || 0} no período)
          </span>
        </h3>
        <div style={{ display: "flex", gap: 4 }}>
          {[
            { id: "month", label: "Mês" },
            { id: "week", label: "7 dias" },
            { id: "all", label: "Geral" },
          ].map((opt) => (
            <button key={opt.id}
                    data-testid={`stats-period-${opt.id}`}
                    onClick={() => onChangePeriod && onChangePeriod(opt.id)}
                    style={{
                      padding: "4px 10px", borderRadius: 999, fontSize: 11,
                      fontWeight: 700, cursor: "pointer",
                      border: "1px solid var(--border-default)",
                      background: period === opt.id
                        ? "linear-gradient(135deg,#f28c28,#4b1d7a)"
                        : "var(--bg-surface-2)",
                      color: period === opt.id ? "white" : "var(--text-secondary)",
                      transition: "all .15s",
                    }}>
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(320px,1fr))",
                       gap: 16 }}>
        {/* Por técnico */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 700,
                          color: "var(--text-muted)", marginBottom: 8,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            Por técnico
          </div>
          {byTech.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Nenhum dado ainda.
            </div>
          )}
          <div style={{ display: "grid", gap: 6 }}>
            {byTech.map((t, idx) => {
              const medals = ["", "", ""];
              const medalBg = ["linear-gradient(135deg,#fbbf24,#f59e0b)",
                                "linear-gradient(135deg,#cbd5e1,#94a3b8)",
                                "linear-gradient(135deg,#f97316,#c2410c)"];
              const isTop = idx < 3;
              return (
              <div key={t.tech_id}
                    data-testid={`stat-tech-${t.tech_id}`}
                    style={{ display: "grid",
                              gridTemplateColumns: "32px 110px 1fr 50px",
                              alignItems: "center", gap: 8, fontSize: 12 }}>
                {isTop ? (
                  <span data-testid={`tech-medal-${idx + 1}`}
                         title={`Top ${idx + 1} do ranking`}
                         style={{
                           width: 26, height: 26, borderRadius: "50%",
                           background: medalBg[idx],
                           display: "flex", alignItems: "center",
                           justifyContent: "center", fontSize: 14,
                           boxShadow: "0 2px 4px rgba(0,0,0,0.18)",
                         }}>
                    {medals[idx]}
                  </span>
                ) : (
                  <span style={{ fontSize: 11, color: "var(--text-muted)",
                                  textAlign: "center", fontWeight: 700 }}>
                    {idx + 1}º
                  </span>
                )}
                <span title={t.tech_name}
                       style={{
                         padding: "2px 8px", borderRadius: 999,
                         fontSize: 11, fontWeight: 800,
                         background: "linear-gradient(135deg,#f28c28,#4b1d7a)",
                         color: "white", textAlign: "center",
                         overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap",
                       }}>
                  {t.first_name}
                </span>
                <div style={{
                  height: 16, borderRadius: 4,
                  background: "rgba(99,102,241,0.12)",
                  overflow: "hidden", position: "relative",
                }}>
                  <div style={{
                    width: `${(t.total / techMax) * 100}%`,
                    height: "100%",
                    background: "linear-gradient(90deg,#f28c28,#4b1d7a)",
                    transition: "width .35s",
                  }} />
                  {t.approved > 0 && (
                    <div title={`${t.approved} aprovadas`}
                         style={{
                           position: "absolute", top: 0, left: 0, height: "100%",
                           width: `${(t.approved / techMax) * 100}%`,
                           background: "linear-gradient(90deg,#15803d,#22c55e)",
                           opacity: 0.9,
                         }} />
                  )}
                </div>
                <strong style={{ textAlign: "right",
                                  color: "var(--text-primary)" }}>
                  {t.total}
                </strong>
              </div>
              );
            })}
          </div>
          {byTech.length > 0 && (
            <div style={{ marginTop: 10, fontSize: 10,
                            color: "var(--text-muted)",
                            display: "flex", gap: 12 }}>
              <span><span style={{ display: "inline-block", width: 10,
                height: 10, background: "#22c55e", borderRadius: 2,
                marginRight: 4, verticalAlign: "middle" }} />
                Aprovadas
              </span>
              <span><span style={{ display: "inline-block", width: 10,
                height: 10, background: "#4b1d7a", borderRadius: 2,
                marginRight: 4, verticalAlign: "middle" }} />
                Total (inclui pendentes)
              </span>
            </div>
          )}
        </div>

        {/* Por filial */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 700,
                          color: "var(--text-muted)", marginBottom: 8,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            Por filial
          </div>
          {byBranch.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Nenhum dado ainda.
            </div>
          )}
          <div style={{ display: "grid", gap: 6 }}>
            {byBranch.map((b) => (
              <div key={b.praca_id}
                    data-testid={`stat-branch-${b.praca_id}`}
                    style={{ display: "grid",
                              gridTemplateColumns: "1fr 50px",
                              alignItems: "center", gap: 8, fontSize: 12 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 12,
                                  color: "var(--text-primary)",
                                  marginBottom: 3 }}>
                    {b.praca_name}
                    {b.city && (
                      <span style={{ fontWeight: 400, color: "var(--text-muted)",
                                      marginLeft: 6, fontSize: 11 }}>
                        · {b.city}
                      </span>
                    )}
                  </div>
                  <div style={{
                    height: 12, borderRadius: 4,
                    background: "rgba(234,88,12,0.12)",
                    overflow: "hidden",
                  }}>
                    <div style={{
                      width: `${(b.total / branchMax) * 100}%`,
                      height: "100%",
                      background: "linear-gradient(90deg,#ea580c,#f59e0b)",
                      transition: "width .35s",
                    }} />
                  </div>
                </div>
                <strong style={{ textAlign: "right",
                                  color: "var(--text-primary)" }}>
                  {b.total}
                </strong>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}


function MiniKpi({ label, value, color }) {
  return (
    <div style={{
      padding: "10px 12px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface-2)",
    }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                       fontWeight: 700, textTransform: "uppercase",
                       letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800, marginTop: 4,
                       color: color || "var(--text-primary)" }}>{value}</div>
    </div>
  );
}

function KPI({ label, value, color }) {
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, marginTop: 6,
                       color: color || "var(--text-primary)", letterSpacing: -0.4 }}>
        {value}
      </div>
    </Card>
  );
}

/* ------------- CTOs list ------------- */
function FiberTimelineCard({ kpi, days, onChangeDays, alerts }) {
  const sevColor = {
    critical: { bg: "#fef2f2", fg: "#991b1b", border: "#fecaca" },
    warning:  { bg: "#fffbeb", fg: "#92400e", border: "#fcd34d" },
    info:     { bg: "#eff6ff", fg: "#1e40af", border: "#bfdbfe" },
  };
  const hasAlerts = (alerts?.alerts || []).length > 0;
  return (
    <Card style={{ padding: 18 }} data-testid="rede-ia-fiber-timeline-card">
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12, flexWrap: "wrap",
                       gap: 8 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>
            Curva de lançamento de fibra
          </h3>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Metros lançados por dia · útil para forecasting de bobinas
          </div>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {[7, 30, 90].map((d) => (
            <button key={d}
                      data-testid={`fiber-range-${d}`}
                      onClick={() => onChangeDays(d)}
                      style={{
                        padding: "5px 12px", borderRadius: 6,
                        border: "1px solid var(--border-default)",
                        background: days === d ? "#0f766e" : "transparent",
                        color: days === d ? "white" : "var(--text-secondary)",
                        fontWeight: 700, fontSize: 11, cursor: "pointer",
                      }}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid",
                       gridTemplateColumns: hasAlerts ? "2fr 1fr" : "1fr",
                       gap: 14 }}>
        {/* Chart */}
        <div style={{ height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={kpi.timeline}
                          margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date"
                       tickFormatter={(v) => v.slice(5)} fontSize={10}
                       interval="preserveStartEnd" />
              <YAxis fontSize={10} unit="m" />
              <RTooltip
                contentStyle={{ fontSize: 12, borderRadius: 6 }}
                formatter={(v) => [`${v}m`, "Fibra"]}
                labelFormatter={(v) => new Date(v).toLocaleDateString("pt-BR")} />
              <Line type="monotone" dataKey="meters"
                      stroke="#0f766e" strokeWidth={2.5}
                      dot={{ r: 3, fill: "#0f766e" }}
                      activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Alertas de saldo */}
        {hasAlerts && (
          <div data-testid="rede-ia-fiber-alerts">
            <div style={{ fontSize: 11, fontWeight: 800,
                            textTransform: "uppercase",
                            color: "var(--text-secondary)",
                            letterSpacing: 0.4, marginBottom: 6 }}>
              ️ Saldo baixo (&lt; {alerts.threshold}m)
            </div>
            <div style={{ maxHeight: 200, overflowY: "auto",
                            display: "grid", gap: 4 }}>
              {alerts.alerts.map((a, i) => {
                const c = sevColor[a.severity] || sevColor.info;
                return (
                  <div key={i}
                        data-testid={`fiber-alert-${a.location}-${a.consumable_id}`}
                        style={{ padding: "6px 8px",
                                  background: c.bg,
                                  border: `1px solid ${c.border}`,
                                  color: c.fg, borderRadius: 6,
                                  fontSize: 11 }}>
                    <div style={{ display: "flex",
                                    justifyContent: "space-between",
                                    fontWeight: 700 }}>
                      <span>{a.location_label}</span>
                      <span>{a.qty}m</span>
                    </div>
                    <div style={{ fontSize: 10, opacity: 0.85 }}>
                      {a.consumable_label}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}


/* ------------- CTOs list ------------- */
function CTOsList() {
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [qrModal, setQrModal] = useState(null); // {id, name}
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.redeIaCtosList(statusFilter ? { status: statusFilter } : {});
      setItems(r.items || []);
    } finally { setLoading(false); }
  }, [statusFilter]);
  useEffect(() => { load(); }, [load]);
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <select data-testid="rede-ia-cto-filter-status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                style={{ padding: "8px 10px", borderRadius: 8,
                          border: "1px solid var(--border-default)", fontSize: 13 }}>
          <option value="">Todos os status</option>
          <option value="pending_validation">Aguardando validação</option>
          <option value="approved">Aprovadas</option>
          <option value="rejected">Rejeitadas</option>
          <option value="pending_correction">Correção solicitada</option>
        </select>
        <span style={{ fontSize: 12, color: "var(--text-muted)", padding: "8px 4px" }}>
          {loading ? "Carregando..." : `${items.length} CTOs`}
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid var(--border-default)" }}>
              <th style={th}>Nome</th>
              <th style={th}>VLAN</th>
              <th style={th}>Bairro</th>
              <th style={th}>Capac.</th>
              <th style={th}>Ocupadas</th>
              <th style={th}>Status</th>
              <th style={th}>Técnico</th>
              <th style={th}>Filial</th>
              <th style={th}>QR</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => {
              const used = (c.ports || []).filter((p) => p.status === "used").length;
              const st = STATUS_BADGE[c.status] || {};
              return (
                <tr key={c.id} data-testid={`cto-row-${c.id}`}
                    style={{ borderBottom: "1px solid var(--border-default)" }}>
                  <td style={td}><strong>{c.name}</strong></td>
                  <td style={td}>{c.vlan}</td>
                  <td style={td}>{c.address?.bairro}</td>
                  <td style={td}>{c.capacity}</td>
                  <td style={td}>{used}/{c.capacity}</td>
                  <td style={td}>
                    <span style={{
                      padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 700,
                      color: st.c, background: st.bg,
                    }}>{st.l || c.status}</span>
                  </td>
                  <td style={td}>
                    {c.technician_first_name || c.technician_name ? (
                      <span data-testid={`cto-tech-tag-${c.id}`}
                            style={{
                              padding: "3px 9px", borderRadius: 999,
                              fontSize: 11, fontWeight: 800,
                              background: "linear-gradient(135deg,#f28c28,#4b1d7a)",
                              color: "white", letterSpacing: 0.4,
                              boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
                            }}
                            title={c.technician_name || ""}>
                        {(c.technician_first_name
                          || (c.technician_name || "").split(" ")[0]
                          || "—").toUpperCase()}
                      </span>
                    ) : "—"}
                  </td>
                  <td style={td}
                       title={c.technician_praca_name || ""}>
                    <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                      {c.technician_praca_name
                        || c.address?.cidade
                        || "—"}
                    </span>
                  </td>
                  <td style={td}>
                    {c.status === "approved" ? (
                      <div style={{ display: "flex", gap: 4 }}>
                        <button data-testid={`cto-qr-${c.id}`}
                                onClick={() => setQrModal({ id: c.id, name: c.name })}
                                style={btnSm("#7c3aed")}>QR</button>
                        <a href={`${process.env.REACT_APP_BACKEND_URL}/api/rede-ia/ctos/${c.id}/pdf.pdf`}
                            target="_blank" rel="noreferrer"
                            data-testid={`cto-pdf-${c.id}`}
                            style={{ ...btnSm("#dc2626"), textDecoration: "none",
                                      display: "inline-flex", alignItems: "center" }}>
                          PDF
                        </a>
                        {c.pdf_drive_url ? (
                          <a href={c.pdf_drive_url} target="_blank" rel="noreferrer"
                              data-testid={`cto-drive-${c.id}`}
                              title="Abrir PDF salvo no Drive"
                              style={{ ...btnSm("#f28c28"), textDecoration: "none",
                                        display: "inline-flex", alignItems: "center" }}>
                            
                          </a>
                        ) : (
                          <DriveResendBtn ctoId={c.id} onDone={load} />
                        )}
                      </div>
                    ) : (
                      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
            {items.length === 0 && !loading && (
              <tr><td colSpan="8" style={{ ...td, textAlign: "center",
                                              color: "var(--text-muted)", padding: 20 }}>
                Nenhuma CTO cadastrada.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {qrModal && (
        <CTOQrModal cto={qrModal} onClose={() => setQrModal(null)} />
      )}
    </Card>
  );
}


function DriveResendBtn({ ctoId, onDone }) {
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try {
      await api.redeIaCtoPdfRegenerate(ctoId);
      onDone?.();
    } catch (e) {
      const msg = e?.response?.data?.detail || "Falha ao enviar para Drive";
      await window.alert(msg);
    } finally { setBusy(false); }
  };
  return (
    <button data-testid={`cto-drive-send-${ctoId}`}
            onClick={send} disabled={busy}
            title="Enviar PDF para Google Drive"
            style={{ ...btnSm("#475569"), opacity: busy ? 0.5 : 1 }}>
      {busy ? "…" : "+"}
    </button>
  );
}

function CTOQrModal({ cto, onClose }) {  const [imgSrc, setImgSrc] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let revokeUrl = null;
    const token = (typeof window !== "undefined") && window.localStorage.getItem("ponto_token");
    fetch(`${process.env.REACT_APP_BACKEND_URL}/api/rede-ia/ctos/${cto.id}/qrcode.png`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        revokeUrl = url;
        setImgSrc(url);
        setLoading(false);
      })
      .catch(() => setLoading(false));
    return () => { if (revokeUrl) URL.revokeObjectURL(revokeUrl); };
  }, [cto.id]);
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", zIndex: 9999,
      display: "grid", placeItems: "center",
    }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="cto-qr-modal"
           style={{ background: "#fff", borderRadius: 14, padding: 24,
                     width: "min(420px, 92vw)", textAlign: "center" }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 18 }}>{cto.name}</h3>
        <p style={{ margin: "0 0 14px", fontSize: 12, color: "#64748b" }}>
          Imprima este QR Code e cole na CTO física. Apenas técnicos com
          o app SmartProv conseguem ler (assinatura HMAC).
        </p>
        <div style={{ background: "#fff", padding: 14, border: "1px solid #e2e8f0",
                        borderRadius: 10, marginBottom: 14, minHeight: 200,
                        display: "grid", placeItems: "center" }}>
          {loading ? (
            <span style={{ color: "#64748b", fontSize: 13 }}>Gerando QR…</span>
          ) : imgSrc ? (
            <img src={imgSrc} alt={`QR ${cto.name}`}
                 style={{ width: "100%", maxWidth: 320, height: "auto" }} />
          ) : (
            <span style={{ color: "#dc2626", fontSize: 13 }}>Falha ao gerar QR</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button data-testid="cto-qr-print" onClick={() => window.print()}
                  style={btnSm("#0f172a")}>Imprimir</button>
          {imgSrc && (
            <a href={imgSrc} download={`qr-${cto.name}.png`}
               style={{ ...btnSm("#7c3aed"), textDecoration: "none" }}
               data-testid="cto-qr-download">Baixar PNG</a>
          )}
          <button onClick={onClose} style={btnSm("#64748b")}>Fechar</button>
        </div>
      </div>
    </div>
  );
}
const th = { textAlign: "left", padding: "8px 10px", fontSize: 11,
              color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 };
const td = { padding: "10px", color: "var(--text-primary)", verticalAlign: "middle" };

/* ------------- Pendencies (validation workflow) ------------- */
function Pendencies() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(null); // {item, action}
  const [mapModal, setMapModal] = useState(null); // {item}
  const [photoLightbox, setPhotoLightbox] = useState(null); // {url, cto, pendencyId}
  const [comment, setComment] = useState("");
  // iter180 — filtro Sentinela IA: mostrar só pendências com score < 85
  const [onlyLowScore, setOnlyLowScore] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    const r = await api.redeIaPendencies(
      onlyLowScore ? { min_score: 85 } : {},
    );
    setItems(r.items || []);
    setLoading(false);
  }, [onlyLowScore]);
  useEffect(() => { load(); }, [load]);
  const submit = async () => {
    try {
      await api.redeIaValidate(modal.item.cto_id, modal.action, comment);
      setModal(null); setComment("");
      load();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    }
  };
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12, gap: 10,
                       flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>Pendências de validação</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {/* iter180 — filtro Sentinela IA */}
          <label data-testid="sentinela-low-score-filter"
                 style={{ display: "flex", alignItems: "center", gap: 6,
                            fontSize: 12, cursor: "pointer", userSelect: "none",
                            padding: "5px 10px", borderRadius: 999,
                            border: "1px solid var(--border-default)",
                            background: onlyLowScore ? "#fee2e2" : "transparent",
                            color: onlyLowScore ? "#b91c1c" : "var(--text-muted)",
                            fontWeight: 700 }}>
            <input type="checkbox" checked={onlyLowScore}
                   onChange={(e) => setOnlyLowScore(e.target.checked)}
                   style={{ accentColor: "#b91c1c" }} />
            Só score &lt; 85
          </label>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {loading ? "Carregando..." : `${items.length} aguardando`}
          </span>
        </div>
      </div>
      {items.length === 0 && !loading && (
        <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>
          ✓ Nenhuma pendência. Tudo em dia.
        </div>
      )}
      <div style={{ display: "grid", gap: 10 }}>
        {items.map((p) => {
          const c = p.cto_snapshot || {};
          return (
            <div key={p.id} data-testid={`pendency-${p.id}`} style={{
              padding: 14, border: "1px solid var(--border-default)", borderRadius: 10,
              background: "var(--bg-surface-2)",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                <div style={{ minWidth: 200 }}>
                  <div style={{ fontWeight: 800, fontSize: 16 }}>{c.name}</div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                    {c.address?.rua}, {c.address?.numero} · {c.address?.bairro} · VLAN {c.vlan}
                  </div>
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    <strong>Cap:</strong> {c.capacity} portas · <strong>Tipo:</strong> {c.network_type}
                    {c.splitter ? ` (splitter ${c.splitter})` : ""}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
                    Técnico: {p.technician_name || "—"} · {new Date(p.created_at).toLocaleString("pt-BR")}
                  </div>
                  {/* iter180 — Badge Sentinela IA */}
                  {p.sentinela && (
                    <SentinelaBadge sentinela={p.sentinela} pendencyId={p.id} />
                  )}
                  {p.smartolt_hints && p.smartolt_hints.matched > 0 && (
                    <div data-testid={`smartolt-hints-${p.id}`} style={{
                      marginTop: 10, padding: "8px 10px", borderRadius: 6,
                      background: "#ecfdf5", border: "1px solid #6ee7b7",
                      fontSize: 11, color: "#065f46",
                    }}>
                      <strong>SmartOLT detectou {p.smartolt_hints.matched} ONUs</strong>
                      {p.smartolt_hints.alerts > 0 && (
                        <span style={{ color: "#b91c1c", marginLeft: 6 }}>
                          ️ {p.smartolt_hints.alerts} com alerta de sinal
                        </span>
                      )}
                      <div style={{ marginTop: 4 }}>
                        {(p.smartolt_hints.candidates || []).slice(0, 3).map((cd, i) => (
                          <div key={i}>
                            • <strong>{cd.olt_name}</strong> Slot {cd.board}/PON {cd.port}
                            ({cd.count} ONUs)
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {c.photo_data_url && (
                    <div data-testid={`pendency-photo-${p.id}`} style={{
                      marginTop: 10, borderRadius: 8, overflow: "hidden",
                      border: "1px solid var(--border-default)", maxWidth: 240,
                      position: "relative", cursor: "zoom-in",
                    }}
                          onDoubleClick={() => setPhotoLightbox({
                            url: c.photo_data_url, cto: c, pendencyId: p.id,
                          })}
                          title="Clique 2× para ampliar">
                      <img src={c.photo_data_url} alt="Foto CTO"
                        style={{ width: "100%", display: "block",
                                  maxHeight: 180, objectFit: "cover" }} />
                      <div style={{
                        position: "absolute", bottom: 4, right: 6,
                        padding: "2px 6px", borderRadius: 4,
                        background: "rgba(15,23,42,.65)", color: "white",
                        fontSize: 10, fontWeight: 700,
                      }}>2× ampliar</div>
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {((c.gps?.lat && c.gps?.lng) || (c.lat && c.lng)) && (
                    <button data-testid={`pendency-map-${p.id}`}
                            onClick={() => setMapModal({ item: p })}
                            style={btnSm("#0f766e")}>
                      Ver no mapa
                    </button>
                  )}
                  <button data-testid={`pendency-approve-${p.id}`}
                          onClick={() => { setModal({ item: p, action: "approve" }); setComment(""); }}
                          style={btnSm("#16a34a")}>Aprovar</button>
                  <button data-testid={`pendency-correct-${p.id}`}
                          onClick={() => { setModal({ item: p, action: "request_correction" }); setComment(""); }}
                          style={btnSm("#ca8a04")}>Solicitar correção</button>
                  <button data-testid={`pendency-reject-${p.id}`}
                          onClick={() => { setModal({ item: p, action: "reject" }); setComment(""); }}
                          style={btnSm("#dc2626")}>Rejeitar</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {modal && (
        <div onClick={() => setModal(null)} style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 9999,
          display: "grid", placeItems: "center",
        }}>
          <div onClick={(e) => e.stopPropagation()} data-testid="pendency-modal"
            style={{ background: "var(--bg-surface)", borderRadius: 12, padding: 20,
                      width: "min(440px,92vw)" }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>
              {modal.action === "approve" && "Aprovar CTO"}
              {modal.action === "request_correction" && "Solicitar correção"}
              {modal.action === "reject" && "Rejeitar CTO"}
            </h3>
            <p style={{ margin: "0 0 12px", fontSize: 13, color: "var(--text-secondary)" }}>
              <strong>{modal.item.cto_snapshot?.name}</strong>
            </p>
            <textarea data-testid="pendency-comment" value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Comentário (opcional)..." rows={3}
              style={{ width: "100%", padding: 10, borderRadius: 8,
                        border: "1px solid var(--border-default)", fontSize: 13,
                        fontFamily: "inherit", boxSizing: "border-box", resize: "vertical" }} />
            <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
              <button onClick={() => setModal(null)} style={btnSm("#64748b")}>Cancelar</button>
              <button data-testid="pendency-submit" onClick={submit} style={btnSm("#0f172a")}>
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

      {mapModal && (
        <CTOLocationViewer
          cto={mapModal.item.cto_snapshot || {}}
          onClose={() => setMapModal(null)}
        />
      )}

      {photoLightbox && (
        <PhotoLightbox
          url={photoLightbox.url}
          ctoName={photoLightbox.cto?.name}
          uploadedByName={photoLightbox.cto?.technician_name}
          onClose={() => setPhotoLightbox(null)}
        />
      )}
    </Card>
  );
}

/* PhotoLightbox — modal full-screen pra ampliar foto da CTO.
   Pedido do usuário: 'com 2 clics posso abrir a foto'. */
// =============================================================================
// SentinelaBadge — iter180. Badge compacto + tooltip com detalhes da
// Sentinela IA (score, ação sugerida, dedupe, GPS, visão do Claude 4.5).
// =============================================================================
function SmartoltVlanSyncCard() {
  const [cov, setCov] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setCov(await api.redeIaSmartoltVlanCoverage()); } catch (e) { /* silent */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function doDryRun() {
    setBusy(true); setResult(null);
    try {
      const r = await api.redeIaSmartoltSyncVlan(true);
      setPreview(r);
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }
  async function doApply() {
    if (!window.confirm(
      "Aplicar a atualização da VLAN em " + (preview?.updated || "?")
      + " assinantes?")) return;
    setBusy(true);
    try {
      const r = await api.redeIaSmartoltSyncVlan(false);
      setResult(r); setPreview(null);
      load();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }

  return (
    <div data-testid="smartolt-vlan-sync-card" style={{
      marginTop: 14, padding: 12,
      background: "var(--bg-surface-2)", borderRadius: 10,
      border: "1px solid var(--border-default)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                       flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 800 }}>
          Sincronizar VLAN do SmartOLT
        </span>
        {cov && (
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            cobertura: <strong>{cov.with_vlan}/{cov.total}</strong>
            {" "}({cov.coverage_pct}%)
          </span>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button data-testid="smartolt-vlan-sync-dryrun" onClick={doDryRun}
                  disabled={busy}
                  style={{
                    padding: "6px 12px", borderRadius: 8,
                    background: busy ? "#94a3b8" : "#0e7490",
                    color: "#fff", border: 0, fontSize: 12, fontWeight: 700,
                    cursor: busy ? "wait" : "pointer",
                  }}>
            {busy && !preview ? "Analisando..." : "Pré-visualizar"}
          </button>
          {preview && (
            <button data-testid="smartolt-vlan-sync-apply" onClick={doApply}
                    disabled={busy}
                    style={{
                      padding: "6px 12px", borderRadius: 8,
                      background: "#16a34a", color: "#fff", border: 0,
                      fontSize: 12, fontWeight: 700,
                      cursor: busy ? "wait" : "pointer",
                    }}>
              Aplicar {preview.updated}
            </button>
          )}
        </div>
      </div>

      <p style={{ marginTop: 6, fontSize: 11, color: "var(--text-muted)",
                     lineHeight: 1.5 }}>
        Lê <code>service_ports[].vlan</code> de cada ONU online do SmartOLT
        e grava em <code>subscribers.current_vlan</code> usando match por
        PPPoE → nome da ONU → SN.
      </p>

      {preview && (
        <div data-testid="smartolt-vlan-sync-preview" style={{
          marginTop: 8, padding: 8, background: "#fff",
          borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 11.5,
        }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12,
                          fontWeight: 700, marginBottom: 6 }}>
            <span>{preview.scanned} ONUs</span>
            <span>· {preview.with_vlan} c/ VLAN</span>
            <span style={{ color: "#16a34a" }}>
              → {preview.updated} atualizar
            </span>
            <span style={{ color: "#475569" }}>
              · {preview.unchanged} já ok
            </span>
            <span style={{ color: "#b45309" }}>
              · {preview.no_subscriber} sem assinante
            </span>
          </div>
          <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>
            Match: pppoe={preview.matched_by_pppoe} · nome={preview.matched_by_name}
            · sn={preview.matched_by_sn}
          </div>
          {/* iter181 — Fallback VLAN 1: alerta de degradação se muito alto */}
          {(preview.default_vlan_1_applied > 0
            || preview.default_vlan_1_skipped_instalacao > 0) && (() => {
              const matched = (preview.matched_by_pppoe || 0)
                + (preview.matched_by_name || 0)
                + (preview.matched_by_sn || 0);
              const def1 = preview.default_vlan_1_applied || 0;
              const total = matched + def1;
              const pctDef = total > 0
                ? Math.round((def1 / total) * 100) : 0;
              // Degradação SmartOLT se >40% dos clientes caem em VLAN 1
              const degraded = pctDef > 40;
              const palette = degraded
                ? { bg: "#fee2e2", fg: "#991b1b", bd: "#fca5a5" }
                : { bg: "#fef3c7", fg: "#92400e", bd: "#fcd34d" };
              return (
                <div data-testid="smartolt-vlan-default-alert" style={{
                  marginTop: 6, padding: "6px 10px", borderRadius: 8,
                  background: palette.bg, color: palette.fg,
                  border: `1px solid ${palette.bd}`,
                  fontSize: 11, lineHeight: 1.5,
                }}>
                  <div style={{ fontWeight: 800, fontSize: 11.5 }}>
                    {degraded ? "️ SmartOLT degradado" : "Default VLAN 1"}
                    <span style={{ marginLeft: 6, fontWeight: 700 }}>
                      {def1} clientes → VLAN 1 ({pctDef}%)
                    </span>
                  </div>
                  <div style={{ fontSize: 10.5, marginTop: 2 }}>
                    Match SmartOLT: <strong>{matched}</strong> · Sem match
                    (default): <strong>{def1}</strong>
                    {preview.default_vlan_1_skipped_instalacao > 0 && (
                      <> · ️ {preview.default_vlan_1_skipped_instalacao}
                        {" "}pulados (instalação ativa)</>
                    )}
                  </div>
                  {degraded && (
                    <div style={{ fontSize: 10, marginTop: 3, opacity: 0.85 }}>
                      Mais de 40% dos clientes não foram encontrados na
                      SmartOLT. Verifique se PPPoE/SN estão sincronizados.
                    </div>
                  )}
                </div>
              );
            })()}
          {(preview.samples || []).length > 0 && (
            <table style={{ marginTop: 6, width: "100%", fontSize: 10.5,
                              borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "#f1f5f9" }}>
                  <th style={{ textAlign: "left", padding: 4 }}>Assinante</th>
                  <th style={{ padding: 4 }}>De</th>
                  <th style={{ padding: 4 }}>Para</th>
                  <th style={{ padding: 4 }}>OLT/PON</th>
                  <th style={{ padding: 4 }}>Match</th>
                </tr>
              </thead>
              <tbody>
                {preview.samples.map((s, i) => (
                  <tr key={i}>
                    <td style={{ padding: 4 }}>{s.subscriber_name}</td>
                    <td style={{ padding: 4, textAlign: "center" }}>
                      {s.previous_vlan ?? "—"}
                    </td>
                    <td style={{ padding: 4, textAlign: "center",
                                   fontWeight: 700, color: "#0e7490" }}>
                      {s.new_vlan}
                    </td>
                    <td style={{ padding: 4, fontFamily: "monospace",
                                   fontSize: 10 }}>{s.olt || "—"}{s.pon ? `·${s.pon}` : ""}</td>
                    <td style={{ padding: 4 }}>{s.match}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {result && (
        <div data-testid="smartolt-vlan-sync-result" style={{
          marginTop: 8, padding: 8, background: "#dcfce7",
          color: "#166534", borderRadius: 8, fontSize: 12, fontWeight: 700,
        }}>
          ✓ {result.updated} assinantes atualizados via SmartOLT
          {result.default_vlan_1_applied > 0 && (
            <span style={{ marginLeft: 6, color: "#92400e" }}>
              · {result.default_vlan_1_applied} → VLAN 1 (default)
            </span>
          )}
          {result.default_vlan_1_skipped_instalacao > 0 && (
            <span style={{ marginLeft: 6, color: "#475569",
                             fontWeight: 600 }}>
              · ️ {result.default_vlan_1_skipped_instalacao}
              {" "}pulados (instalação ativa)
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// SentinelaThresholdCard — iter181. Seletor de qualidade mínima exigida da
// Sentinela IA (foto de CTO/CE/OS). Default 69, podendo ir até 85 (rigoroso).
// =============================================================================
function SentinelaThresholdCard() {
  const [config, setConfig] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [savedMsg, setSavedMsg] = React.useState(null);

  React.useEffect(() => {
    let alive = true;
    api._client.get("/rede-ia/sentinela/config")
      .then((r) => { if (alive) setConfig(r.data); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const save = async (value) => {
    if (!config || busy) return;
    setBusy(true); setSavedMsg(null);
    try {
      await api._client.patch("/rede-ia/sentinela/config",
        { sentinela_min_score: value });
      setConfig({ ...config, sentinela_min_score: value });
      setSavedMsg({ kind: "ok", text: `Mínimo atualizado para ${value}/100` });
      setTimeout(() => setSavedMsg(null), 3000);
    } catch (e) {
      setSavedMsg({ kind: "err",
                       text: e?.response?.data?.detail || "Falhou" });
    } finally { setBusy(false); }
  };

  if (!config) {
    return (
      <div style={{ marginTop: 12, padding: 12, borderRadius: 10,
                      background: "#f8fafc", border: "1px solid #e2e8f0",
                      fontSize: 12, color: "#64748b" }}>
        Carregando config da Sentinela IA…
      </div>
    );
  }

  const current = config.sentinela_min_score;
  return (
    <div data-testid="sentinela-threshold-card" style={{
      marginTop: 12, padding: 12, borderRadius: 10,
      background: "linear-gradient(135deg,#fef3c7,#fde68a)",
      border: "1px solid #f59e0b",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                      marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 17 }}>️</span>
        <strong style={{ fontSize: 13, color: "#78350f" }}>
          Sentinela IA — Qualidade mínima da foto
        </strong>
        <span data-testid="sentinela-threshold-value" style={{
          marginLeft: "auto", padding: "3px 9px", borderRadius: 999,
          background: "#92400e", color: "#fff",
          fontWeight: 800, fontSize: 12,
        }}>{current}/100</span>
      </div>

      <p style={{ margin: "0 0 8px", fontSize: 11.5, color: "#78350f",
                    lineHeight: 1.4 }}>
        Score mínimo exigido pra aprovar foto de CTO/CE/OS. Fotos abaixo
        desse limite pedem novo clique. Default da plataforma: <strong>69</strong>.
      </p>

      {/* Slider rápido */}
      <input data-testid="sentinela-threshold-slider"
        type="range" min={30} max={95} step={1} value={current}
        disabled={busy}
        onChange={(e) => setConfig({
          ...config, sentinela_min_score: parseInt(e.target.value, 10) })}
        onMouseUp={(e) => save(parseInt(e.target.value, 10))}
        onTouchEnd={(e) => save(parseInt(e.target.value, 10))}
        style={{ width: "100%", accentColor: "#92400e" }} />

      {/* Presets */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
                      marginTop: 6 }}>
        {(config.presets || []).map((p) => {
          const active = current === p.value;
          return (
            <button key={p.value}
              data-testid={`sentinela-preset-${p.value}`}
              onClick={() => save(p.value)} disabled={busy}
              title={p.desc}
              style={{
                flex: "1 1 calc(50% - 6px)", minWidth: 120,
                padding: "6px 10px", borderRadius: 8,
                background: active ? "#92400e" : "#fff7ed",
                color: active ? "#fff" : "#78350f",
                border: `1px solid ${active ? "#92400e" : "#fcd34d"}`,
                fontSize: 11, fontWeight: 700, cursor: "pointer",
                textAlign: "left",
              }}>
              <div style={{ fontSize: 12 }}>
                {p.label} · {p.value}
              </div>
              <div style={{ fontSize: 9.5, fontWeight: 500, opacity: 0.85,
                              marginTop: 1 }}>
                {p.desc}
              </div>
            </button>
          );
        })}
      </div>

      {savedMsg && (
        <div data-testid="sentinela-threshold-msg" style={{
          marginTop: 8, padding: "4px 8px", borderRadius: 6,
          fontSize: 11, fontWeight: 700,
          background: savedMsg.kind === "ok" ? "#dcfce7" : "#fee2e2",
          color: savedMsg.kind === "ok" ? "#166534" : "#991b1b",
        }}>
          {savedMsg.kind === "ok" ? "✓ " : "✗ "}{savedMsg.text}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// SignalDegradationCard — iter182. Card de alertas de ONUs com degradação
// de sinal detectada nas últimas 24h (delta ≥ 3 dBm pior que a média).
// Atualiza automaticamente sempre que o worker SmartOLT rodar (15min).
// =============================================================================
function SignalDegradationCard() {
  const [items, setItems] = React.useState([]);
  const [busy, setBusy] = React.useState(true);
  const [showAll, setShowAll] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    api._client.get("/smartolt/signal-degradation?status=active&limit=50")
      .then((r) => { if (alive) setItems(r.data.items || []); })
      .catch(() => {})
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, []);

  if (busy) {
    return (
      <div style={{ marginTop: 12, padding: 10, borderRadius: 10,
                      background: "#f8fafc", border: "1px solid #e2e8f0",
                      fontSize: 11.5, color: "#64748b" }}>
        Carregando alertas de degradação…
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div data-testid="signal-degradation-card-empty" style={{
        marginTop: 12, padding: 10, borderRadius: 10,
        background: "#f0fdf4", border: "1px solid #86efac",
        fontSize: 11.5, color: "#15803d", fontWeight: 700,
      }}>
        ✓ Nenhuma ONU em degradação no momento
      </div>
    );
  }

  const visible = showAll ? items : items.slice(0, 10);
  // ordena pelo pior delta (mais negativo primeiro)
  const sorted = [...visible].sort(
    (a, b) => (a.delta_dbm || 0) - (b.delta_dbm || 0));

  return (
    <div data-testid="signal-degradation-card" style={{
      marginTop: 12, padding: 12, borderRadius: 10,
      background: "linear-gradient(135deg,#fef2f2,#fee2e2)",
      border: "1px solid #f87171",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                      marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 17 }}></span>
        <strong style={{ fontSize: 13, color: "#991b1b" }}>
          ONUs degradando ({items.length})
        </strong>
        <span style={{ marginLeft: "auto", fontSize: 10.5,
                        color: "#7f1d1d" }}>
          Δ ≥ -3 dBm em 24h
        </span>
      </div>

      <p style={{ margin: "0 0 8px", fontSize: 11.5, color: "#7f1d1d",
                    lineHeight: 1.4 }}>
        Sinal piorou comparado à média das últimas 24h. Pode ser chuva,
        splitter sujo, fibra dobrada ou ONT com problema.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 5,
                      maxHeight: 320, overflowY: "auto" }}>
        {sorted.map((a) => (
          <div key={a.unique_external_id}
            data-testid={`signal-deg-${a.unique_external_id}`}
            style={{ padding: "7px 9px", borderRadius: 7,
                       background: "#fff", border: "1px solid #fca5a5",
                       display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700,
                              color: "#0f172a",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap" }}>
                {a.name || a.unique_external_id}
              </div>
              <div style={{ fontSize: 10, color: "#64748b",
                              marginTop: 1 }}>
                {a.olt_name || "—"} ·{" "}
                <span style={{ fontFamily: "monospace" }}>
                  {a.current_rx_dbm} dBm
                </span>{" "}
                <span style={{ color: "#94a3b8" }}>
                  (média 24h: {a.avg_24h_rx_dbm})
                </span>
              </div>
            </div>
            <div style={{ fontSize: 12, fontWeight: 800,
                            padding: "3px 8px", borderRadius: 999,
                            background: a.delta_dbm <= -5
                              ? "#7f1d1d" : "#dc2626",
                            color: "#fff" }}>
              {a.delta_dbm > 0 ? "+" : ""}{a.delta_dbm} dB
            </div>
          </div>
        ))}
      </div>

      {items.length > 10 && (
        <button data-testid="signal-deg-toggle-all"
          onClick={() => setShowAll((v) => !v)}
          style={{ marginTop: 8, padding: "5px 10px", borderRadius: 6,
                     background: "transparent", border: "1px solid #f87171",
                     color: "#991b1b", fontSize: 11, fontWeight: 700,
                     cursor: "pointer", width: "100%" }}>
          {showAll ? "▲ Mostrar só top 10"
                   : `▼ Ver todos os ${items.length} alertas`}
        </button>
      )}
    </div>
  );
}



// =============================================================================
// PortBaseSearchCard — iter182. Busca global na Base de Portas.
// Usuário digita MAC, SN, PPPoE, nome do cliente ou nome da CTO e o sistema
// retorna em <1s qual CTO+Porta o cliente está ocupando, com status, sinal
// e VLAN. Usa o endpoint /api/cto-ports?q=...
// =============================================================================
function PortBaseSearchCard() {
  const [query, setQuery] = React.useState("");
  const [items, setItems] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [stats, setStats] = React.useState(null);

  // Carrega stats no mount
  React.useEffect(() => {
    api._client.get("/cto-ports/stats")
      .then((r) => setStats(r.data))
      .catch(() => {});
  }, []);

  // Debounce search
  React.useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setItems([]); return; }
    let cancelled = false;
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const r = await api._client.get(
          `/cto-ports/?q=${encodeURIComponent(q)}&limit=20`,
        ).then((x) => x.data);
        if (cancelled) return;
        setItems(r.items || []);
      } catch { /* silent */ }
      finally { if (!cancelled) setBusy(false); }
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [query]);

  const statusColor = (s) => s === "occupied" ? "#16a34a"
    : s === "defective" ? "#dc2626" : "#94a3b8";
  const statusLabel = (s) => s === "occupied" ? "Ocupada"
    : s === "defective" ? "Defeito" : "Livre";

  return (
    <div data-testid="port-base-search-card" style={{
      marginTop: 12, padding: 12, borderRadius: 10,
      background: "linear-gradient(135deg,#ecfeff,#cffafe)",
      border: "1px solid #f28c28",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                      marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 17 }}></span>
        <strong style={{ fontSize: 13, color: "#155e75" }}>
          Base de Portas — busca global
        </strong>
        {stats && (
          <span style={{ marginLeft: "auto", fontSize: 11,
                          color: "#0e7490" }}>
            {stats.total} portas · {stats.occupied} ocupadas
            {" "}· {stats.free} livres · {stats.occupancy_rate}%
          </span>
        )}
      </div>

      <p style={{ margin: "0 0 8px", fontSize: 11.5, color: "#155e75",
                    lineHeight: 1.4 }}>
        Digite <strong>MAC, SN, PPPoE, nome do cliente</strong> ou nome
        da CTO. Resultado em &lt;1s.
      </p>

      <input data-testid="port-base-search-input"
        value={query} onChange={(e) => setQuery(e.target.value)}
        placeholder="Ex.: ALCLFC090E99 · CTO_301_001 · José Silva"
        style={{ width: "100%", padding: "10px 12px", borderRadius: 8,
                   border: "1px solid #f28c28",
                   fontSize: 13, boxSizing: "border-box",
                   background: "#fff", color: "#0f172a" }} />

      {busy && (
        <div style={{ marginTop: 6, fontSize: 11, color: "#0e7490" }}>
          Buscando…
        </div>
      )}

      {!busy && query.trim().length >= 2 && items.length === 0 && (
        <div data-testid="port-base-search-empty" style={{
          marginTop: 8, padding: "8px 10px", borderRadius: 8,
          background: "#fff", color: "#64748b", fontSize: 11.5,
        }}>
          Nenhuma porta encontrada para “{query}”.
        </div>
      )}

      {items.length > 0 && (
        <div data-testid="port-base-search-results" style={{
          marginTop: 8, display: "flex", flexDirection: "column",
          gap: 6, maxHeight: 380, overflowY: "auto",
        }}>
          {items.map((p) => (
            <div key={p.id} data-testid={`port-${p.id}`} style={{
              padding: "8px 10px", borderRadius: 8, background: "#fff",
              border: "1px solid #e2e8f0",
              display: "flex", alignItems: "center", gap: 10,
              flexWrap: "wrap",
            }}>
              <span style={{ padding: "2px 7px", borderRadius: 999,
                              background: statusColor(p.status),
                              color: "#fff", fontSize: 9.5,
                              fontWeight: 800,
                              textTransform: "uppercase",
                              letterSpacing: 0.4 }}>
                {statusLabel(p.status)}
              </span>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700,
                                color: "#0f172a" }}>
                  {p.cto_name} <span style={{ color: "#f28c28" }}>·</span>{" "}
                  porta <strong>{p.port_number}</strong>
                  {p.vlan != null && (
                    <span style={{ marginLeft: 6, fontSize: 10,
                                     padding: "1px 5px", borderRadius: 4,
                                     background: "#f1f5f9", color: "#475569",
                                     fontWeight: 600 }}>
                      VLAN {p.vlan}
                    </span>
                  )}
                </div>
                {(p.subscriber_name || p.pppoe_user) && (
                  <div style={{ fontSize: 11, color: "#475569",
                                  marginTop: 2 }}>
                    {p.subscriber_name || "—"}
                    {p.pppoe_user && (
                      <span style={{ marginLeft: 6,
                                       fontFamily: "monospace",
                                       fontSize: 10.5,
                                       color: "#0e7490" }}>
                        {p.pppoe_user}
                      </span>
                    )}
                  </div>
                )}
                {(p.mac || p.sn) && (
                  <div style={{ fontSize: 10, marginTop: 2,
                                  fontFamily: "monospace",
                                  color: "#94a3b8" }}>
                    {p.mac && <span>MAC: {p.mac}</span>}
                    {p.mac && p.sn && " · "}
                    {p.sn && <span>SN: {p.sn}</span>}
                  </div>
                )}
              </div>
              {p.signal_dbm != null && (
                <div style={{ fontSize: 11, fontWeight: 800,
                                padding: "3px 8px", borderRadius: 999,
                                color: p.signal_dbm > -25 ? "#15803d"
                                  : p.signal_dbm > -28 ? "#b45309"
                                  : "#991b1b",
                                background: p.signal_dbm > -25 ? "#dcfce7"
                                  : p.signal_dbm > -28 ? "#fef3c7"
                                  : "#fee2e2" }}>
                  {Number(p.signal_dbm).toFixed(1)} dBm
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// =============================================================================
// PortBaseTab — iter182. Sub-aba dedicada à Base de Portas.
// Contém a busca global + lista agrupada por CTO (visão de mapa de calor)
// com filtros por status.
// =============================================================================
function PortBaseTab() {
  const [stats, setStats] = React.useState(null);
  const [ctos, setCtos] = React.useState([]);
  const [filter, setFilter] = React.useState("all");
  const [busy, setBusy] = React.useState(false);
  const [resyncBusy, setResyncBusy] = React.useState(false);
  const [resyncMsg, setResyncMsg] = React.useState(null);

  const loadAll = React.useCallback(async () => {
    setBusy(true);
    try {
      const [s, list] = await Promise.all([
        api._client.get("/cto-ports/stats").then((r) => r.data),
        api._client.get("/cto-ports/?limit=500").then((r) => r.data),
      ]);
      setStats(s);
      const grouped = {};
      for (const p of (list.items || [])) {
        if (!grouped[p.cto_id]) {
          grouped[p.cto_id] = {
            cto_id: p.cto_id, cto_name: p.cto_name,
            olt_name: p.olt_name, vlan: p.vlan,
            neighborhood: p.neighborhood,
            technician_name: p.cto_technician_name,
            ports: [],
          };
        }
        grouped[p.cto_id].ports.push(p);
      }
      const arr = Object.values(grouped);
      arr.forEach((c) => c.ports.sort(
        (a, b) => (a.port_number || 0) - (b.port_number || 0)));
      arr.sort((a, b) => (a.cto_name || "").localeCompare(b.cto_name || ""));
      setCtos(arr);
    } catch (e) {
      console.error("[port-base-tab] load fail", e);
    } finally { setBusy(false); }
  }, []);

  React.useEffect(() => { loadAll(); }, [loadAll]);

  const doResync = async () => {
    if (resyncBusy) return;
    setResyncBusy(true); setResyncMsg(null);
    try {
      const r = await api._client.post(
        "/cto-ports/sync", {}).then((x) => x.data);
      setResyncMsg({ ok: true,
        text: `✓ ${r.ports_synced} portas re-sincronizadas`
          + ` (${r.ctos_synced} CTOs)` });
      await loadAll();
    } catch (e) {
      setResyncMsg({ ok: false,
        text: e?.response?.data?.detail || "Falhou" });
    } finally {
      setResyncBusy(false);
      setTimeout(() => setResyncMsg(null), 4000);
    }
  };

  // iter182 — Backfill: importa em massa vínculos legados de subscribers
  const doBackfill = async () => {
    if (resyncBusy) return;
    // DRY-RUN primeiro pra mostrar preview
    setResyncBusy(true); setResyncMsg(null);
    try {
      const dry = await api._client.post(
        "/cto-ports/backfill-from-subscribers",
        { dry_run: true }).then((x) => x.data);
      if (dry.linked === 0) {
        setResyncMsg({ ok: true,
          text: `Nenhum vínculo legado para importar. Escaneados: `
            + `${dry.scanned} subscribers.` });
        return;
      }
      const ok = window.confirm(
        `Importar ${dry.linked} vínculo(s) cliente↔porta?\n\n`
        + `Escaneados: ${dry.scanned}\n`
        + `A serem vinculados: ${dry.linked}\n`
        + `Pulados (sem CTO): ${dry.skipped_no_cto}\n`
        + `Pulados (porta ocupada): ${dry.skipped_port_occupied}\n`
        + `Pulados (porta inexistente): ${dry.skipped_port_not_found}\n\n`
        + `Primeiros 5:\n`
        + (dry.samples || []).slice(0, 5).map((s) =>
            `  • ${s.subscriber_name} → ${s.cto_name} P${s.port_number}`)
          .join("\n"));
      if (!ok) {
        setResyncMsg({ ok: true, text: "Importação cancelada." });
        return;
      }
      const r = await api._client.post(
        "/cto-ports/backfill-from-subscribers",
        { dry_run: false }).then((x) => x.data);
      setResyncMsg({ ok: true,
        text: `✓ ${r.linked} vínculos importados`
          + ` de ${r.scanned} subscribers escaneados.` });
      await loadAll();
    } catch (e) {
      setResyncMsg({ ok: false,
        text: e?.response?.data?.detail || "Falhou" });
    } finally {
      setResyncBusy(false);
      setTimeout(() => setResyncMsg(null), 8000);
    }
  };

  const statusColor = (s) => s === "occupied" ? "#16a34a"
    : s === "defective" ? "#dc2626" : "#cbd5e1";
  const portTitle = (p) => {
    if (p.status === "occupied") {
      return `Porta ${p.port_number} · ${p.subscriber_name || "(sem nome)"}`
        + (p.pppoe_user ? ` · ${p.pppoe_user}` : "")
        + (p.signal_dbm != null
            ? ` · ${Number(p.signal_dbm).toFixed(1)} dBm` : "");
    }
    if (p.status === "defective") return `Porta ${p.port_number} · DEFEITO`;
    return `Porta ${p.port_number} · LIVRE`;
  };

  const shouldShowPort = (p) => filter === "all" || p.status === filter;
  const shouldShowCto = (c) => filter === "all"
    || c.ports.some(shouldShowPort);

  // iter182 — Ações destrutivas: liberar porta / apagar CTO inteira
  const releasePort = async (port) => {
    if (port.status !== "occupied") {
      window.alert("Porta já está livre.");
      return;
    }
    const ok = window.confirm(
      `Liberar a porta ${port.port_number} da ${port.cto_name}?\n\n`
      + `Cliente atual: ${port.subscriber_name || "(sem nome)"}\n\n`
      + `O vínculo do cliente com esta porta será REMOVIDO. `
      + `O cliente em si NÃO será apagado.`);
    if (!ok) return;
    try {
      await api._client.post(
        `/cto-ports/${port.cto_id}/port/${port.port_number}/release`,
        { reason: "manual_admin_ui" });
      await loadAll();
    } catch (e) {
      window.alert("Falhou: " + (e?.response?.data?.detail || "erro"));
    }
  };

  const deleteCto = async (cto) => {
    const occ = cto.ports.filter((p) => p.status === "occupied").length;
    if (occ > 0) {
      window.alert(
        `Não dá pra apagar ${cto.cto_name}: tem ${occ} porta(s) ocupada(s).\n\n`
        + `Libere as portas primeiro (clique no quadradinho verde, ou use `
        + `"Liberar TODAS" se for migração).`);
      return;
    }
    const ok = window.confirm(
      `Apagar a CTO ${cto.cto_name} permanentemente?\n\n`
      + `Esta ação NÃO pode ser desfeita. Todas as ${cto.ports.length} `
      + `portas serão removidas da base.`);
    if (!ok) return;
    try {
      await api._client.delete(`/cto-ports/cto/${cto.cto_id}`);
      await loadAll();
    } catch (e) {
      window.alert("Falhou: " + (e?.response?.data?.detail || "erro"));
    }
  };

  // iter182 — Libera TODAS as portas ocupadas de uma CTO de uma vez.
  // Confirmação DUPLA pra evitar acidente.
  const releaseAllPorts = async (cto) => {
    const occupied = cto.ports.filter((p) => p.status === "occupied");
    if (occupied.length === 0) {
      window.alert("Nenhuma porta ocupada para liberar.");
      return;
    }
    const clientList = occupied.slice(0, 5)
      .map((p) => `  • P${p.port_number} → ${p.subscriber_name || "(sem nome)"}`)
      .join("\n");
    const more = occupied.length > 5
      ? `\n  ... e mais ${occupied.length - 5} cliente(s)` : "";
    // CONFIRM 1 — visão geral
    const ok1 = window.confirm(
      `LIBERAR TODAS as ${occupied.length} portas ocupadas da `
      + `${cto.cto_name}?\n\n`
      + `Clientes que serão DESVINCULADOS:\n${clientList}${more}\n\n`
      + `Isto é normalmente usado em migração de provedor ou desativação. `
      + `Os clientes em si não serão apagados.\n\nContinuar?`);
    if (!ok1) return;
    // CONFIRM 2 — exige digitar o nome da CTO
    const typed = window.prompt(
      `️ CONFIRMAÇÃO FINAL\n\nDigite o nome da CTO para confirmar:\n`
      + `  ${cto.cto_name}`, "");
    if (typed !== cto.cto_name) {
      if (typed != null) {
        window.alert("Nome digitado não confere. Operação CANCELADA.");
      }
      return;
    }
    try {
      const r = await api._client.post(
        `/cto-ports/cto/${cto.cto_id}/release-all`,
        { reason: "bulk_admin_ui" }).then((x) => x.data);
      window.alert(`✓ ${r.released_count} portas liberadas.`);
      await loadAll();
    } catch (e) {
      window.alert("Falhou: " + (e?.response?.data?.detail || "erro"));
    }
  };

  return (
    <div data-testid="port-base-tab" style={{ display: "flex",
                                                 flexDirection: "column",
                                                 gap: 12 }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                      alignItems: "center" }}>
        {stats && (
          <div data-testid="port-base-stats-strip" style={{
            display: "flex", gap: 8, flexWrap: "wrap", flex: 1,
            minWidth: 280,
          }}>
            <StatPill label="Total" value={stats.total}
                       color="#0f172a" bg="#f1f5f9" />
            <StatPill label="Ocupadas" value={stats.occupied}
                       color="#15803d" bg="#dcfce7" />
            <StatPill label="Livres" value={stats.free}
                       color="#475569" bg="#e2e8f0" />
            <StatPill label="Defeito" value={stats.defective}
                       color="#991b1b" bg="#fee2e2" />
            <StatPill label="Ocupação"
                       value={`${stats.occupancy_rate}%`}
                       color="#0e7490" bg="#cffafe" />
          </div>
        )}
        <button data-testid="port-base-resync-btn"
          onClick={doResync} disabled={resyncBusy}
          title="Re-sincronizar a base de portas a partir de ctos.ports[]"
          style={{
            padding: "8px 14px", borderRadius: 10,
            background: resyncBusy ? "#94a3b8" : "#f28c28",
            color: "#fff", border: 0, fontSize: 12, fontWeight: 700,
            cursor: resyncBusy ? "wait" : "pointer",
          }}>
          {resyncBusy ? "Re-sincronizando…" : "Re-sincronizar"}
        </button>
        <button data-testid="port-base-backfill-btn"
          onClick={doBackfill} disabled={resyncBusy}
          title="Importa em massa vínculos de subscribers (legado) para a Base de Portas"
          style={{
            padding: "8px 14px", borderRadius: 10,
            background: resyncBusy ? "#94a3b8" : "#8b5cf6",
            color: "#fff", border: 0, fontSize: 12, fontWeight: 700,
            cursor: resyncBusy ? "wait" : "pointer",
          }}>
          Importar vínculos
        </button>
      </div>

      {resyncMsg && (
        <div data-testid="port-base-resync-msg" style={{
          padding: "8px 12px", borderRadius: 8, fontSize: 12,
          background: resyncMsg.ok ? "#dcfce7" : "#fee2e2",
          color: resyncMsg.ok ? "#166534" : "#991b1b", fontWeight: 700,
        }}>{resyncMsg.text}</div>
      )}

      <PortBaseSearchCard />

      <div style={{ display: "flex", gap: 8, alignItems: "center",
                      flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>Mapa de portas por CTO</strong>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {["all", "occupied", "free", "defective"].map((f) => (
            <button key={f}
              data-testid={`port-base-filter-${f}`}
              onClick={() => setFilter(f)}
              style={{
                padding: "5px 10px", borderRadius: 999,
                background: filter === f ? "#0f172a" : "#fff",
                color: filter === f ? "#fff" : "#475569",
                border: `1px solid ${filter === f
                  ? "#0f172a" : "#cbd5e1"}`,
                fontSize: 11, fontWeight: 700, cursor: "pointer",
              }}>
              {f === "all" ? "Todas"
                : f === "occupied" ? "Ocupadas"
                : f === "free" ? "Livres" : "Defeito"}
            </button>
          ))}
        </div>
      </div>

      {busy && ctos.length === 0 && (
        <div style={{ padding: 20, textAlign: "center",
                        color: "#64748b", fontSize: 12 }}>
          Carregando base de portas…
        </div>
      )}

      {!busy && ctos.length === 0 && (
        <div style={{ padding: 20, textAlign: "center",
                        color: "#64748b", fontSize: 12 }}>
          Nenhuma CTO encontrada. Clique em “Re-sincronizar” para popular.
        </div>
      )}

      <div data-testid="port-base-cto-grid" style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
        gap: 12,
      }}>
        {ctos.filter(shouldShowCto).map((c) => {
          const occ = c.ports.filter((p) => p.status === "occupied").length;
          const tot = c.ports.length;
          const pct = tot ? Math.round((occ / tot) * 100) : 0;
          return (
            <div key={c.cto_id}
              data-testid={`port-base-cto-${c.cto_id}`}
              style={{ padding: 12, borderRadius: 12, background: "#fff",
                          border: "1px solid #e2e8f0" }}>
              <div style={{ display: "flex", alignItems: "center",
                              gap: 8, marginBottom: 8 }}>
                <strong style={{ fontSize: 12.5, color: "#0f172a",
                                  flex: 1, minWidth: 0,
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap" }}>
                  {c.cto_name || c.cto_id}
                </strong>
                <span style={{ fontSize: 11, fontWeight: 700,
                                color: pct >= 80 ? "#dc2626"
                                  : pct >= 50 ? "#b45309" : "#16a34a" }}>
                  {occ}/{tot} ({pct}%)
                </span>
                {occ > 0 && (
                  <button
                    data-testid={`port-base-release-all-${c.cto_id}`}
                    onClick={() => releaseAllPorts(c)}
                    title={`Liberar TODAS as ${occ} portas ocupadas`
                      + ` (migração / desativação)`}
                    style={{
                      background: "#fef3c7", color: "#92400e",
                      border: 0, borderRadius: 6, padding: "3px 6px",
                      fontSize: 11, fontWeight: 700, cursor: "pointer",
                    }}>
                    
                  </button>
                )}
                <button
                  data-testid={`port-base-delete-cto-${c.cto_id}`}
                  onClick={() => deleteCto(c)}
                  disabled={occ > 0}
                  title={occ > 0
                    ? `Libere as ${occ} porta(s) ocupada(s) antes de apagar`
                    : `Apagar CTO ${c.cto_name} permanentemente`}
                  style={{
                    background: occ > 0 ? "#f1f5f9" : "#fee2e2",
                    color: occ > 0 ? "#94a3b8" : "#991b1b",
                    border: 0, borderRadius: 6, padding: "3px 6px",
                    fontSize: 11, fontWeight: 700,
                    cursor: occ > 0 ? "not-allowed" : "pointer",
                  }}>
                  
                </button>
              </div>
              <div style={{ display: "flex", gap: 6, fontSize: 9.5,
                              color: "#64748b", marginBottom: 8,
                              flexWrap: "wrap" }}>
                {c.olt_name && <span>{c.olt_name}</span>}
                {c.vlan != null && <span>· VLAN {c.vlan}</span>}
                {c.technician_name && (
                  <span data-testid={`cto-tech-${c.cto_id}`}
                        style={{ color: "#0e7490", fontWeight: 700 }}>
                    · {c.technician_name}
                  </span>
                )}
                {c.neighborhood && <span>· {c.neighborhood}</span>}
              </div>
              <div style={{ display: "grid", gridTemplateColumns:
                              "repeat(auto-fill, minmax(36px, 1fr))",
                              gap: 4 }}>
                {c.ports.filter(shouldShowPort).map((p) => (
                  <div key={p.id}
                    title={p.status === "occupied"
                      ? `${portTitle(p)}\n\n(clique pra LIBERAR a porta)`
                      : portTitle(p)}
                    data-testid={`port-cell-${p.id}`}
                    onClick={() => {
                      if (p.status === "occupied") releasePort(p);
                    }}
                    style={{
                      aspectRatio: "1", borderRadius: 6,
                      background: statusColor(p.status),
                      color: "#fff", display: "flex",
                      alignItems: "center", justifyContent: "center",
                      fontSize: 11, fontWeight: 800,
                      border: p.status === "free"
                        ? "1px solid #cbd5e1" : "none",
                      cursor: p.status === "occupied"
                        ? "pointer" : "default",
                    }}>{p.port_number}</div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                      fontSize: 10.5, color: "#64748b",
                      marginTop: 4 }}>
        <span>Ocupada</span>
        <span style={{ color: "#94a3b8" }}>⬜ Livre</span>
        <span style={{ color: "#dc2626" }}>Defeito</span>
      </div>
    </div>
  );
}

function StatPill({ label, value, color, bg }) {
  return (
    <div style={{
      padding: "8px 14px", borderRadius: 10, background: bg,
      display: "flex", flexDirection: "column", minWidth: 78,
    }}>
      <span style={{ fontSize: 9.5, fontWeight: 700, color,
                       textTransform: "uppercase", letterSpacing: 0.5,
                       opacity: 0.7 }}>
        {label}
      </span>
      <strong style={{ fontSize: 16, color }}>{value}</strong>
    </div>
  );
}



// =============================================================================
// SentinelaBadge — iter180. Badge compacto + tooltip com detalhes da
// Sentinela IA (score, ação sugerida, dedupe, GPS, visão do Claude 4.5).
// =============================================================================
function SentinelaBadge({ sentinela, pendencyId }) {
  const score = sentinela.score ?? 0;
  const action = sentinela.action || "—";
  const palette = score >= 85
    ? { bg: "#dcfce7", fg: "#166534", bd: "#86efac" }
    : score >= 60
      ? { bg: "#fef3c7", fg: "#92400e", bd: "#fcd34d" }
      : { bg: "#fee2e2", fg: "#991b1b", bd: "#fca5a5" };
  const cond = (sentinela.vision || {}).condition || "—";
  const dupOf = (sentinela.dedupe || {}).duplicate_of;
  const gpsDist = (sentinela.gps_check || {}).distance_m;
  return (
    <div data-testid={`sentinela-badge-${pendencyId}`} style={{
      marginTop: 8, padding: "6px 10px", borderRadius: 8,
      background: palette.bg, color: palette.fg,
      border: `1px solid ${palette.bd}`,
      fontSize: 11, lineHeight: 1.45,
      display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center",
    }}>
      <span style={{ fontWeight: 800, fontSize: 12 }}>
        Sentinela {score}/100
      </span>
      <span style={{ opacity: 0.6 }}>·</span>
      <span style={{ fontWeight: 700, textTransform: "uppercase",
                       letterSpacing: 0.4 }}>{action}</span>
      {cond && cond !== "ok" && cond !== "—" && (
        <>
          <span style={{ opacity: 0.6 }}>·</span>
          <span style={{ fontWeight: 700 }}>
            CTO {cond.replace("_", " ")}
          </span>
        </>
      )}
      {dupOf && (
        <>
          <span style={{ opacity: 0.6 }}>·</span>
          <span>️ duplicada</span>
        </>
      )}
      {typeof gpsDist === "number" && gpsDist > 0 && (
        <>
          <span style={{ opacity: 0.6 }}>·</span>
          <span>{gpsDist}m do pino</span>
        </>
      )}
      {sentinela.vision?.reasoning && (
        <div style={{ width: "100%", marginTop: 4, opacity: 0.85,
                          fontStyle: "italic" }}>
          “{sentinela.vision.reasoning}”
        </div>
      )}
    </div>
  );
}


function PhotoLightbox({ url, ctoName, uploadedByName, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div data-testid="photo-lightbox"
          onClick={onClose}
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(0,0,0,.92)",
            display: "grid", placeItems: "center", padding: 20,
            cursor: "zoom-out",
          }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ display: "flex", flexDirection: "column", gap: 12,
                      maxWidth: "92vw", maxHeight: "92vh",
                      alignItems: "center" }}>
        <div style={{
          padding: "6px 14px", borderRadius: 999,
          background: "rgba(255,255,255,.1)", color: "white",
          fontSize: 12, fontWeight: 700, display: "flex", gap: 10,
          alignItems: "center",
        }}>
          {ctoName || "CTO"}
          {uploadedByName && (
            <span style={{ opacity: 0.7, fontWeight: 500 }}>
              · {uploadedByName}
            </span>
          )}
        </div>
        <img src={url} alt="Foto CTO ampliada"
              data-testid="lightbox-img"
              style={{
                maxWidth: "100%", maxHeight: "82vh", borderRadius: 8,
                boxShadow: "0 12px 40px rgba(0,0,0,.6)",
                cursor: "default",
              }} />
        <button data-testid="lightbox-close"
                onClick={onClose}
                style={{
                  padding: "8px 18px", borderRadius: 8,
                  border: "1px solid rgba(255,255,255,.3)",
                  background: "rgba(255,255,255,.1)", color: "white",
                  fontSize: 12, fontWeight: 700, cursor: "pointer",
                }}>
          Fechar (Esc)
        </button>
      </div>
    </div>
  );
}
const btnSm = (color) => ({
  padding: "6px 12px", borderRadius: 6, border: "0",
  background: color, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer",
});

/* ------------- Bairros / VLAN map ------------- */
function BairrosManager() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ bairro: "", sigla: "", vlan: "",
                                          cidade: "", estado: "", regiao: "",
                                          olt_name: "" });
  const [oltNames, setOltNames] = useState([]); // iter211be
  const [err, setErr] = useState("");
  const [onusModal, setOnusModal] = useState(null); // {vlan, bairro}
  const load = useCallback(async () => {
    const [r, o] = await Promise.all([
      api.redeIaBairros(),
      api.redeIaOltNames().catch(() => ({ items: [] })),
    ]);
    setItems(r.items || []);
    setOltNames(o.items || []);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setErr("");
    try {
      await api.redeIaBairroCreate({
        ...form, vlan: parseInt(form.vlan, 10),
      });
      setForm({ bairro: "", sigla: "", vlan: "", cidade: "", estado: "",
                  regiao: "", olt_name: "" });
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Erro ao salvar.");
    }
  };
  const del = async (id) => {
    if (!await window.confirm("Remover bairro?")) return;
    await api.redeIaBairroDelete(id);
    load();
  };
  return (
    <Card style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 12px", fontSize: 16 }}>Bairros e VLAN</h3>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>
        Cadastre os bairros atendidos. A sigla e a VLAN são usadas pela rede_IA para gerar
        nomenclaturas padronizadas das CTOs (ex: <code>CTO 001_301_COR</code>).
        Vincule à <strong>OLT SmartOLT</strong> caso o bairro seja atendido por uma —
        assim as CTOs criadas com essa VLAN serão automaticamente registradas no SmartOLT.
      </p>
      <div style={{ display: "grid",
                       gridTemplateColumns: "2fr 1fr 1fr 1fr 0.7fr 1.2fr auto",
                       gap: 8, marginBottom: 14, alignItems: "end" }}>
        <Field l="Bairro" v={form.bairro} on={(v) => setForm({ ...form, bairro: v })}
                tid="bairro-input" />
        <Field l="Sigla" v={form.sigla}
                on={(v) => setForm({ ...form, sigla: v.toUpperCase() })} tid="sigla-input" />
        <Field l="VLAN" v={form.vlan} on={(v) => setForm({ ...form, vlan: v })}
                tid="vlan-input" type="number" />
        <Field l="Cidade" v={form.cidade} on={(v) => setForm({ ...form, cidade: v })} />
        <Field l="UF" v={form.estado} on={(v) => setForm({ ...form, estado: v.toUpperCase() })} />
        <div>
          <label style={{ display: "block", fontSize: 11, color: "var(--text-muted)",
                          fontWeight: 600, marginBottom: 3 }}>
            OLT (SmartOLT)
          </label>
          <select data-testid="bairro-olt-select"
                  value={form.olt_name || ""}
                  onChange={(e) => setForm({ ...form, olt_name: e.target.value })}
                  style={{ width: "100%", padding: "7px 9px",
                            border: "1px solid var(--border-default)",
                            borderRadius: 6, fontSize: 12, background: "white" }}>
            <option value="">— sem SmartOLT —</option>
            {oltNames.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <button data-testid="bairro-save" onClick={save} style={btnSm("#0f172a")}>
          Adicionar
        </button>
      </div>
      {err && (
        <div style={{ color: "#b91c1c", fontSize: 12, marginBottom: 10 }}>{err}</div>
      )}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "2px solid var(--border-default)" }}>
            <th style={th}>Bairro</th><th style={th}>Sigla</th><th style={th}>VLAN</th>
            <th style={th}>Cidade/UF</th><th style={th}>OLT</th><th style={th}></th>
          </tr>
        </thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.id} style={{ borderBottom: "1px solid var(--border-default)" }}>
              <td style={td}>{b.bairro}</td>
              <td style={td}><strong>{b.sigla}</strong></td>
              <td style={td}>{b.vlan}</td>
              <td style={td}>{b.cidade}{b.estado ? `/${b.estado}` : ""}</td>
              <td style={td}>
                {b.olt_name
                  ? <span style={{ padding: "2px 8px", fontSize: 11,
                                     background: "#ecfdf5", color: "#065f46",
                                     border: "1px solid #6ee7b7",
                                     borderRadius: 999, fontWeight: 700,
                                     fontFamily: "monospace" }}>
                      {b.olt_name}
                    </span>
                  : <span style={{ color: "#94a3b8", fontSize: 11 }}>—</span>}
              </td>
              <td style={td}>
                <button onClick={() => setOnusModal({ vlan: b.vlan, bairro: b.bairro })}
                        style={{ ...btnSm("#f28c28"), padding: "4px 10px",
                                  fontSize: 11, marginRight: 6 }}
                        data-testid={`bairro-list-onus-${b.id}`}
                        title={`Buscar ONUs na SmartOLT pela VLAN ${b.vlan}`}>
                  ONUs
                </button>
                <button onClick={() => del(b.id)}
                        style={{ ...btnSm("#dc2626"), padding: "4px 8px", fontSize: 11 }}
                        data-testid={`bairro-del-${b.id}`}>×</button>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan="6" style={{ ...td, textAlign: "center", padding: 20,
                                            color: "var(--text-muted)" }}>
              Nenhum bairro cadastrado. Adicione o primeiro acima.
            </td></tr>
          )}
        </tbody>
      </table>
      {onusModal && (
        <OnusByVlanModal {...onusModal} onClose={() => setOnusModal(null)} />
      )}
    </Card>
  );
}

function OnusByVlanModal({ vlan, bairro, onClose }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [selectedOnu, setSelectedOnu] = useState(null);

  useEffect(() => {
    setLoading(true);
    api._client.get(`/smartolt/onus/by-vlan/${vlan}`)
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, [vlan]);

  const filtered = (data?.onus || []).filter((o) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (o.name || "").toLowerCase().includes(s)
        || (o.sn || "").toLowerCase().includes(s)
        || (o.address || "").toLowerCase().includes(s)
        || (o.zone_name || "").toLowerCase().includes(s);
  });

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, zIndex: 1000,
                   background: "rgba(2,6,23,0.65)",
                   display: "grid", placeItems: "center", padding: 20 }}
         data-testid="onus-by-vlan-modal">
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: "white", borderRadius: 14, padding: 20,
                     maxWidth: 1100, width: "100%", maxHeight: "85vh",
                     overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 18, color: "#0f172a" }}>
              ONUs autorizadas — VLAN {vlan}
            </h3>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b" }}>
              Bairro: <strong>{bairro}</strong>
              {data && (
                <> · {data.count} ONUs encontradas na SmartOLT
                  <span style={{ marginLeft: 8, fontSize: 10, padding: "2px 6px",
                                  background: data.source === "smartolt_cache"
                                                ? "#fef3c7" : "#dcfce7",
                                  color: data.source === "smartolt_cache"
                                           ? "#92400e" : "#166534",
                                  borderRadius: 999, fontWeight: 700 }}>
                    {data.source === "smartolt_cache" ? "CACHE" : "LIVE"}
                  </span>
                  {data.cache_warning && (
                    <span style={{ display: "block", marginTop: 4,
                                       fontSize: 10, color: "#92400e",
                                       fontStyle: "italic" }}>
                      ️ {data.cache_warning}
                    </span>
                  )}
                </>
              )}
            </p>
          </div>
          <button onClick={onClose}
                   style={{ border: "none", background: "transparent",
                             cursor: "pointer", fontSize: 22, color: "#64748b" }}>×</button>
        </div>

        <input type="text" value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filtrar por nome, SN, endereço ou zona..."
                data-testid="onus-by-vlan-search"
                style={{ padding: "8px 12px", borderRadius: 8,
                          border: "1px solid #cbd5e1", fontSize: 13,
                          marginBottom: 12 }} />

        <div style={{ flex: 1, overflowY: "auto",
                       border: "1px solid #e2e8f0", borderRadius: 8 }}>
          {loading && (
            <div style={{ padding: 40, textAlign: "center", color: "#64748b" }}>
              ⏳ Buscando ONUs na SmartOLT...
            </div>
          )}
          {error && (
            <div style={{ padding: 20, background: "#fee2e2", color: "#991b1b",
                           fontSize: 13, borderRadius: 8, margin: 10 }}>
              ️ {error}
            </div>
          )}
          {!loading && !error && data && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f8fafc", position: "sticky", top: 0 }}>
                  {["Nome / PPPoE", "SN", "OLT", "B/P/ONU", "Zona", "Status", "Sinal"]
                  .map((h, i) => (
                    <th key={i} style={{ padding: "10px 12px", textAlign: "left",
                                          fontSize: 11, fontWeight: 700, color: "#475569",
                                          letterSpacing: 0.5, textTransform: "uppercase" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => (
                  <tr key={o.unique_external_id}
                       data-testid={`onu-row-${o.unique_external_id}`}
                       onClick={() => setSelectedOnu(o)}
                       style={{ borderTop: "1px solid #f1f5f9",
                                  cursor: "pointer",
                                  transition: "background 120ms" }}
                       onMouseEnter={(e) => {
                         e.currentTarget.style.background = "#f1f5f9";
                       }}
                       onMouseLeave={(e) => {
                         e.currentTarget.style.background = "transparent";
                       }}>
                    <td style={{ padding: "8px 12px", fontWeight: 600 }}>
                      {o.name || "—"}
                      {o.address && (
                        <div style={{ fontSize: 10, color: "#94a3b8" }}>
                          {fmtAddress(o.address)}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "monospace",
                                  fontSize: 11, color: "#64748b" }}>{o.sn || "—"}</td>
                    <td style={{ padding: "8px 12px" }}>{o.olt_name || "—"}</td>
                    <td style={{ padding: "8px 12px", fontFamily: "monospace",
                                  fontSize: 11 }}>
                      {o.board}/{o.port}/{o.onu}
                    </td>
                    <td style={{ padding: "8px 12px" }}>{o.zone_name || "—"}</td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{
                        padding: "2px 8px", borderRadius: 999, fontSize: 10,
                        fontWeight: 700,
                        background: o.status === "Online" ? "#dcfce7" : "#fee2e2",
                        color: o.status === "Online" ? "#166534" : "#991b1b",
                      }}>{o.status || "—"}</span>
                    </td>
                    <td style={{ padding: "8px 12px",
                                  fontFamily: "monospace", fontSize: 11 }}>
                      {o.signal_text || "—"}
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={7} style={{ padding: 30, textAlign: "center",
                                                  color: "#94a3b8" }}>
                    {search ? "Nenhuma ONU corresponde ao filtro." : "Nenhuma ONU encontrada nesta VLAN."}
                  </td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {selectedOnu && (
        <OnuDetailModal
          onu={selectedOnu}
          onClose={() => setSelectedOnu(null)}
        />
      )}
    </div>
  );
}

/* =============================================================
   OnuDetailModal — drill-down de uma ONU específica.
   Mostra: sinal live (com refresh), status, último sync, histórico
   das ações (reboots, etc) e botão de Reboot com confirmação visual.
============================================================= */
function OnuDetailModal({ onu, onClose }) {
  const [sigLoading, setSigLoading] = useState(true);
  const [sigData, setSigData] = useState(null);
  const [sigError, setSigError] = useState("");
  const [actions, setActions] = useState([]);
  const [actionsLoading, setActionsLoading] = useState(true);
  const [rebooting, setRebooting] = useState(false);
  const [confirmReboot, setConfirmReboot] = useState(false);
  const [feedback, setFeedback] = useState(null); // {ok,msg}

  const extId = onu.unique_external_id;

  const loadSignal = useCallback(() => {
    setSigLoading(true);
    setSigError("");
    api.smartoltOnuSignal(extId)
      .then((r) => setSigData(r))
      .catch((e) => setSigError(e?.response?.data?.detail || e.message))
      .finally(() => setSigLoading(false));
  }, [extId]);

  const loadActions = useCallback(() => {
    setActionsLoading(true);
    api.smartoltOnuActions(extId, 20)
      .then((r) => setActions(r.items || []))
      .catch(() => setActions([]))
      .finally(() => setActionsLoading(false));
  }, [extId]);

  useEffect(() => { loadSignal(); loadActions(); }, [loadSignal, loadActions]);

  const onuLive = sigData?.onu || onu;
  const rxLabel = onuLive.signal_1490 || onuLive.signal_text || "—";

  const doReboot = async () => {
    setConfirmReboot(false);
    setRebooting(true);
    setFeedback(null);
    try {
      await api.smartoltOnuReboot(extId);
      setFeedback({ ok: true,
        msg: "Reboot enviado. A conexão volta em ~30s." });
      // Recarrega ações
      await loadActions();
    } catch (e) {
      setFeedback({ ok: false,
        msg: e?.response?.data?.detail || e.message });
    } finally {
      setRebooting(false);
    }
  };

  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, zIndex: 1010,
                   background: "rgba(2,6,23,0.7)",
                   display: "grid", placeItems: "center", padding: 20 }}
         data-testid="onu-detail-modal">
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: "white", borderRadius: 14, padding: 20,
                     maxWidth: 640, width: "100%", maxHeight: "85vh",
                     overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 17, color: "#0f172a" }}>
              {onuLive.name || "ONU"}
            </h3>
            <p style={{ margin: "4px 0 0", fontSize: 11, color: "#64748b" }}>
              SN: <code>{onuLive.sn || "—"}</code> · OLT {onuLive.olt_name || "—"}
              · B/P/ONU {onuLive.board}/{onuLive.port}/{onuLive.onu}
            </p>
          </div>
          <button onClick={onClose}
                   style={{ border: "none", background: "transparent",
                             cursor: "pointer", fontSize: 22, color: "#64748b" }}>
            ×
          </button>
        </div>

        {/* SIGNAL CARD */}
        <div style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                       padding: 14, marginBottom: 14, background: "#f8fafc" }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                         alignItems: "center", marginBottom: 8 }}>
            <strong style={{ fontSize: 13, color: "#0f172a" }}>
              Sinal atual
            </strong>
            <button onClick={loadSignal} disabled={sigLoading}
                     data-testid="onu-signal-refresh"
                     style={{ padding: "4px 10px", fontSize: 11, borderRadius: 6,
                               background: "white", border: "1px solid #cbd5e1",
                               cursor: sigLoading ? "wait" : "pointer",
                               color: "#475569", fontWeight: 600 }}>
              {sigLoading ? "Atualizando..." : "↻ Atualizar"}
            </button>
          </div>
          {sigError && (
            <div style={{ padding: 8, background: "#fee2e2", color: "#991b1b",
                           borderRadius: 6, fontSize: 12 }}>️ {sigError}</div>
          )}
          {!sigError && (
            <div style={{ display: "grid",
                           gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
              <SigBox label="RX 1490" value={rxLabel} highlight />
              <SigBox label="TX 1310" value={onuLive.signal_1310 || "—"} />
              <SigBox label="Status"
                       value={onuLive.status || "—"}
                       color={onuLive.status === "Online" ? "#16a34a" : "#dc2626"} />
            </div>
          )}
          <div style={{ marginTop: 8, fontSize: 10, color: "#94a3b8" }}>
            Última leitura: {onuLive.signal_synced_at
              ? new Date(onuLive.signal_synced_at).toLocaleString("pt-BR")
              : "—"}
            {sigData?.cached === false && (
              <span style={{ marginLeft: 8, padding: "1px 6px",
                              background: "#dcfce7", color: "#166534",
                              borderRadius: 999, fontSize: 9, fontWeight: 700 }}>
                LIVE
              </span>
            )}
          </div>
        </div>

        {/* ACTIONS */}
        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          <button onClick={() => setConfirmReboot(true)}
                   disabled={rebooting}
                   data-testid="onu-reboot-btn"
                   style={{ flex: 1, padding: "10px 14px", borderRadius: 8,
                             background: "#dc2626", color: "white", border: "none",
                             fontWeight: 700, fontSize: 13,
                             cursor: rebooting ? "wait" : "pointer",
                             opacity: rebooting ? 0.6 : 1 }}>
            {rebooting ? "Reiniciando..." : "⟳ Reiniciar ONU"}
          </button>
        </div>

        {feedback && (
          <div style={{ padding: 10, borderRadius: 8, fontSize: 12,
                         background: feedback.ok ? "#dcfce7" : "#fee2e2",
                         color: feedback.ok ? "#166534" : "#991b1b",
                         marginBottom: 12 }}
               data-testid="onu-action-feedback">
            {feedback.ok ? "✓ " : "️ "}{feedback.msg}
          </div>
        )}

        {/* ACTION HISTORY */}
        <div>
          <strong style={{ fontSize: 12, color: "#0f172a",
                            textTransform: "uppercase", letterSpacing: 0.6 }}>
            Histórico de ações
          </strong>
          <div style={{ marginTop: 8, maxHeight: 200, overflowY: "auto",
                         border: "1px solid #e2e8f0", borderRadius: 8 }}>
            {actionsLoading && (
              <div style={{ padding: 14, textAlign: "center", fontSize: 12,
                             color: "#94a3b8" }}>Carregando...</div>
            )}
            {!actionsLoading && actions.length === 0 && (
              <div style={{ padding: 14, textAlign: "center", fontSize: 12,
                             color: "#94a3b8" }}>
                Nenhuma ação registrada nesta ONU.
              </div>
            )}
            {!actionsLoading && actions.map((a) => (
              <div key={a.id} style={{ padding: "8px 12px",
                                          borderTop: "1px solid #f1f5f9",
                                          fontSize: 12, display: "flex",
                                          justifyContent: "space-between",
                                          alignItems: "center" }}>
                <div>
                  <strong style={{
                    color: a.result_ok ? "#166534" : "#991b1b",
                    textTransform: "uppercase", fontSize: 10,
                    letterSpacing: 0.5,
                  }}>
                    {a.action} {a.result_ok ? "✓" : "✗"}
                  </strong>
                  <div style={{ fontSize: 11, color: "#64748b" }}>
                    {a.actor_user || "—"}
                  </div>
                </div>
                <span style={{ fontSize: 10, color: "#94a3b8" }}>
                  {a.created_at
                    ? new Date(a.created_at).toLocaleString("pt-BR")
                    : "—"}
                </span>
              </div>
            ))}
          </div>
        </div>

        {confirmReboot && (
          <ConfirmRebootModal
            onCancel={() => setConfirmReboot(false)}
            onConfirm={doReboot}
            onuName={onuLive.name}
          />
        )}
      </div>
    </div>
  );
}

function SigBox({ label, value, highlight, color }) {
  return (
    <div style={{ padding: 10, borderRadius: 8,
                   background: highlight ? "#eff6ff" : "white",
                   border: "1px solid " + (highlight ? "#bfdbfe" : "#e2e8f0"),
                   textAlign: "center" }}>
      <div style={{ fontSize: 9, color: "#64748b", textTransform: "uppercase",
                     fontWeight: 700, letterSpacing: 0.6 }}>{label}</div>
      <div style={{ marginTop: 3, fontSize: 13, fontWeight: 700,
                     fontFamily: "monospace",
                     color: color || "#0f172a" }}>{value}</div>
    </div>
  );
}

function ConfirmRebootModal({ onCancel, onConfirm, onuName }) {
  return (
    <div onClick={onCancel}
         data-testid="onu-reboot-confirm-modal"
         style={{ position: "fixed", inset: 0, zIndex: 1020,
                   background: "rgba(2,6,23,0.7)",
                   display: "grid", placeItems: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: "white", borderRadius: 14, padding: 22,
                     maxWidth: 380, width: "100%", textAlign: "center",
                     boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}>
        <div style={{ width: 52, height: 52, borderRadius: "50%",
                       background: "#dc2626", color: "white",
                       display: "grid", placeItems: "center",
                       margin: "0 auto 12px",
                       fontSize: 24, fontWeight: 700 }}>⟳</div>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0f172a" }}>
          Reiniciar ONU?
        </h3>
        <p style={{ margin: "8px 0 18px", fontSize: 13, color: "#475569" }}>
          A ONU <strong>{onuName || "selecionada"}</strong> será reiniciada.
          O cliente perde a conexão por ~30 segundos.
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button onClick={onCancel}
                   data-testid="onu-reboot-no"
                   style={{ padding: "9px 24px", borderRadius: 9, fontSize: 13,
                             fontWeight: 700, cursor: "pointer",
                             background: "white", color: "#475569",
                             border: "1.5px solid #cbd5e1", minWidth: 90 }}>
            NÃO
          </button>
          <button onClick={onConfirm}
                   data-testid="onu-reboot-yes"
                   style={{ padding: "9px 24px", borderRadius: 9, fontSize: 13,
                             fontWeight: 700, cursor: "pointer",
                             background: "#dc2626", color: "white", border: "none",
                             minWidth: 90 }}>
            SIM
          </button>
        </div>
      </div>
    </div>
  );
}
function Field({ l, v, on, tid, type = "text" }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 600 }}>{l}</span>
      <input data-testid={tid} value={v} type={type}
        onChange={(e) => on(e.target.value)}
        style={{ padding: "8px 10px", borderRadius: 8,
                  border: "1px solid var(--border-default)", fontSize: 13 }} />
    </label>
  );
}

/* ------------- History ------------- */
function HistoryList() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.redeIaHistory().then((r) => setItems(r.items || []));
  }, []);
  return (
    <Card style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 12px", fontSize: 16 }}>Histórico de alterações</h3>
      <div style={{ display: "grid", gap: 6 }}>
        {items.map((h) => (
          <div key={h.id} style={{
            padding: "10px 12px", borderLeft: "3px solid #7c3aed",
            background: "var(--bg-surface-2)", borderRadius: 6, fontSize: 12,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <strong>{h.action}</strong>
              <span style={{ color: "var(--text-muted)" }}>
                {new Date(h.timestamp).toLocaleString("pt-BR")}
              </span>
            </div>
            <div style={{ color: "var(--text-secondary)", marginTop: 4 }}>
              {h.by_user_name} ({h.by_role}) · CTO {h.cto_id}
              {h.motivo ? ` · ${h.motivo}` : ""}
            </div>
          </div>
        ))}
        {items.length === 0 && (
          <div style={{ padding: 20, textAlign: "center",
                          color: "var(--text-muted)" }}>Sem histórico.</div>
        )}
      </div>
    </Card>
  );
}

/* ------------- Diretrizes editor ------------- */
function DiretrizesEditor() {
  const [text, setText] = useState("");
  const [meta, setMeta] = useState({});
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [aiReport, setAiReport] = useState(null);
  useEffect(() => {
    api.redeIaDiretrizes().then((r) => {
      setText(r.text || "");
      setMeta({ updated_at: r.updated_at, updated_by: r.updated_by });
    });
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.redeIaDiretrizesUpdate(text);
      setMeta({ updated_at: r.updated_at, updated_by: r.updated_by });
    } catch (e) {
      await window.alert("Erro ao salvar: " + (e?.response?.data?.detail || e.message));
    } finally { setSaving(false); }
  };
  const analyze = async () => {
    setAnalyzing(true); setAiReport(null);
    try {
      const r = await api.redeIaAnalyze({});
      setAiReport(r);
    } catch (e) {
      await window.alert("Erro IA: " + (e?.response?.data?.detail || e.message));
    } finally { setAnalyzing(false); }
  };
  return (
    <Card style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>Diretrizes da rede_IA</h3>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>
        Defina a missão, regras e critérios técnicos que orientam a IA. Esse texto é
        usado como system prompt quando a IA analisa a rede.
      </p>
      <textarea data-testid="diretrizes-text" value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        style={{ width: "100%", padding: 12, borderRadius: 8,
                  border: "1px solid var(--border-default)", fontSize: 13,
                  fontFamily: "inherit", lineHeight: 1.5, boxSizing: "border-box",
                  resize: "vertical" }} />
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginTop: 10, gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {meta.updated_at
            ? `Atualizado por ${meta.updated_by} em ${new Date(meta.updated_at).toLocaleString("pt-BR")}`
            : "Padrão da rede_IA"}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button data-testid="diretrizes-analyze" onClick={analyze}
                  disabled={analyzing} style={btnSm("#7c3aed")}>
            {analyzing ? "Analisando..." : "Analisar rede com IA"}
          </button>
          <button data-testid="diretrizes-save" onClick={save}
                  disabled={saving} style={btnSm("#0f172a")}>
            {saving ? "Salvando..." : "Salvar diretrizes"}
          </button>
        </div>
      </div>

      {aiReport && (
        <div data-testid="ai-report" style={{
          marginTop: 16, padding: 14, borderRadius: 10,
          background: "#f5f3ff", border: "1px solid #c4b5fd",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 6, color: "#5b21b6" }}>
            Relatório da rede_IA
          </div>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit",
                          fontSize: 13, color: "#1e1b4b", margin: 0 }}>
            {aiReport.report || JSON.stringify(aiReport, null, 2)}
          </pre>
        </div>
      )}
    </Card>
  );
}


/* ============================================================
 * ORPHAN CABLES PANEL — Cabos com pontas soltas (iter186)
 * Lista, sugestões com IA heurística, vinculação 1-clique.
 * ============================================================ */
function OrphanCablesPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [suggestions, setSuggestions] = useState([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [elements, setElements] = useState([]); // CTOs/CEs pra vincular
  const [linking, setLinking] = useState(null); // {cable_id, end} em curso
  const [linkModal, setLinkModal] = useState(null);
  // iter186 — Modal "Confiança visual" + auto-vision
  const [visualReview, setVisualReview] = useState(null);
  const [pendingReviews, setPendingReviews] = useState([]);
  const [autoCfg, setAutoCfg] = useState(null);
  const [autoSaving, setAutoSaving] = useState(false);
  // {cable, end} → abre picker

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [orph, mapData, pending, cfg] = await Promise.all([
        api.redeIaCablesOrphan(),
        api.redeIaMapData().catch(() => ({ ctos: [], ces: [] })),
        api.redeIaVisionPendingReview().catch(() => ({ items: [] })),
        api.redeIaVisionAutoConfig().catch(() => null),
      ]);
      setItems(orph.items || []);
      setPendingReviews(pending.items || []);
      setAutoCfg(cfg);
      // Constrói lista de elementos vinculáveis (CTOs + CEs)
      const els = [
        ...(mapData.ctos || []).map((c) => ({
          id: c.id, name: c.name, type: "cto", lat: c.lat, lng: c.lng,
          bairro: (c.address || {}).bairro, vlan: c.vlan, sigla: c.sigla,
        })),
        ...(mapData.ces || []).map((c) => ({
          id: c.id, name: c.name, type: "ce", lat: c.lat, lng: c.lng,
          bairro: (c.address || {}).bairro, vlan: c.vlan, sigla: c.sigla,
        })),
      ];
      setElements(els);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const runAiSuggest = async () => {
    setAnalyzing(true);
    try {
      const r = await api.redeIaCablesOrphanSuggest();
      setSuggestions(r.items || []);
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setAnalyzing(false);
    }
  };

  const runVisionSuggest = async () => {
    setAnalyzing(true);
    try {
      const r = await api.redeIaCablesOrphanSuggestVision();
      setSuggestions(r.items || []);
      if ((r.items || []).length === 0) {
        await window.alert(
          "Vision IA: nenhuma sugestão encontrada.\n\n"
          + "Verifique se os cabos têm foto da plaqueta legível "
          + "e se há CTOs/CEs com nomes correspondentes na rede.",
        );
      }
    } catch (e) {
      await window.alert("Erro IA Visão: "
        + (e?.response?.data?.detail || e.message));
    } finally {
      setAnalyzing(false);
    }
  };

  const link = async (cableId, endpoint, elementId) => {
    setLinking({ cable_id: cableId, end: endpoint });
    try {
      await api.redeIaCableLinkEndpoint(cableId, endpoint, elementId);
      // Remove sugestão e cabo da lista se ficou completo
      setSuggestions((prev) => prev.filter(
        (s) => !(s.cable_id === cableId && s.end === endpoint),
      ));
      await reload();
    } catch (e) {
      await window.alert(
        "Erro ao vincular: " + (e?.response?.data?.detail || e.message),
      );
    } finally { setLinking(null); }
  };

  const saveAutoCfg = async (next) => {
    setAutoSaving(true);
    try {
      const r = await api.redeIaVisionAutoConfigUpdate(next);
      setAutoCfg(r);
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setAutoSaving(false); }
  };

  const runAutoNow = async () => {
    setAnalyzing(true);
    try {
      const r = await api.redeIaVisionAutoRunNow();
      await reload();
      await window.alert(
        `Scan executado:\n• ${r.scanned} cabos órfãos analisados\n`
        + `• ${r.auto_linked} auto-vinculados (≥${autoCfg?.auto_link_threshold || 90}%)\n`
        + `• ${r.pending_review} aguardando revisão\n`
        + `• ${r.skipped} ignorados (sem foto ou sem match)`,
      );
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setAnalyzing(false); }
  };

  const approveReview = async (rid) => {
    await api.redeIaVisionReviewApprove(rid);
    await reload();
  };
  const rejectReview = async (rid) => {
    await api.redeIaVisionReviewReject(rid);
    await reload();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", gap: 10, marginBottom: 10,
                          flexWrap: "wrap" }}>
          <div>
            <h3 style={{ margin: "0 0 4px", fontSize: 16 }}>
              Cabos órfãos
            </h3>
            <p style={{ fontSize: 12, color: "var(--text-muted)",
                              margin: 0 }}>
              Cabos lançados sem origem ou destino vinculados ({items.length}
              {" "}total). Aparecem em <strong>laranja tracejado</strong> no
              mapa principal.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button data-testid="orphan-ai-suggest" onClick={runAiSuggest}
                       disabled={analyzing || items.length === 0}
                       style={btnSm("#7c3aed")}>
              {analyzing ? "Analisando..." : "Heurística (geo)"}
            </button>
            <button data-testid="orphan-vision-suggest" onClick={runVisionSuggest}
                       disabled={analyzing || items.length === 0}
                       style={btnSm("#0d9488")}>
              {analyzing ? "Analisando..." : "Vision IA (lê plaqueta)"}
            </button>
          </div>
        </div>

        {loading && (
          <div style={{ padding: 20, textAlign: "center",
                            color: "var(--text-muted)" }}>
            Carregando cabos...
          </div>
        )}

        {!loading && items.length === 0 && (
          <div style={{ padding: 20, textAlign: "center",
                            color: "var(--text-muted)", background: "#f8fafc",
                            borderRadius: 10, border: "1px dashed #cbd5e1" }}>
            ✅ Nenhum cabo órfão na rede. Todos têm origem e destino vinculados.
          </div>
        )}

        {/* Sugestões da IA */}
        {suggestions.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 700,
                              color: "#5b21b6", marginBottom: 8 }}>
              {suggestions.length} sugestão(ões) de vínculo
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {suggestions.map((s, idx) => {
                const isLinking = linking?.cable_id === s.cable_id
                    && linking?.end === s.end;
                const confColor = s.confidence >= 70 ? "#16a34a"
                  : s.confidence >= 40 ? "#ea580c" : "#dc2626";
                return (
                  <div key={`${s.cable_id}-${s.end}-${idx}`}
                          onClick={() => s.source === "vision_ai"
                            && setVisualReview(s)}
                          style={{
                            display: "flex", gap: 10, padding: 10,
                            background: "#fff",
                            border: "1px solid #c4b5fd",
                            borderRadius: 10, alignItems: "center",
                            flexWrap: "wrap",
                            cursor: s.source === "vision_ai"
                              ? "pointer" : "default",
                          }}>
                    <div style={{
                      width: 42, textAlign: "center", color: confColor,
                      fontWeight: 900, fontSize: 18,
                    }}>{s.confidence}%</div>
                    <div style={{ flex: 1, minWidth: 200 }}>
                      <div style={{ fontSize: 13, fontWeight: 700,
                                        color: "var(--text-primary)" }}>
                        {s.cable_name}
                        {" "}<span style={{ color: "#94a3b8" }}>
                          ({s.end === "from " ? "Origem" : "Destino"})
                        </span>
                        {" → "}<strong>{s.suggested_element_name}</strong>
                        {s.source === "vision_ai" && (
                          <span style={{
                            marginLeft: 6, fontSize: 9, fontWeight: 800,
                            padding: "2px 6px", borderRadius: 4,
                            background: "#ccfbf1", color: "#0d9488",
                          }}>VISION IA</span>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)",
                                       marginTop: 3 }}>
                        {(s.reasons || []).join(" · ")}
                        {s.source === "vision_ai" && (
                          <span style={{ color: "#0d9488", marginLeft: 6,
                                            fontWeight: 700 }}>
                            ️ clique para revisar visualmente
                          </span>
                        )}
                      </div>
                    </div>
                    <button data-testid={`suggest-accept-${s.cable_id}-${s.end}`}
                                onClick={(ev) => {
                                  ev.stopPropagation();
                                  link(s.cable_id, s.end,
                                       s.suggested_element_id);
                                }}
                                disabled={!!linking}
                                style={btnSm("#16a34a")}>
                      {isLinking ? "Vinculando..." : "✓ Vincular"}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Lista de cabos órfãos */}
        {!loading && items.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {items.map((cab) => (
              <div key={cab.id} style={{
                padding: 12, background: "#fff8f1",
                border: "1px solid #fed7aa", borderRadius: 10,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between",
                                  alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 800,
                                       color: "var(--text-primary)" }}>
                      {cab.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)",
                                     marginTop: 3 }}>
                      {cab.total_length_m ? `${Math.round(cab.total_length_m)}m`
                        : "—"}
                      {" · "}{cab.fo_count || "—"}FO
                      {" · VLAN "}{cab.vlan || "—"}
                      {" · "}{cab.technician_name || "—"}
                    </div>
                  </div>
                  <span style={{
                    fontSize: 10, fontWeight: 800, padding: "3px 8px",
                    borderRadius: 999, background: "#fed7aa",
                    color: "#9a3412", textTransform: "uppercase",
                    letterSpacing: 0.5,
                  }}>cabo solto</span>
                </div>
                <div style={{ marginTop: 10, display: "flex", gap: 8,
                                  flexWrap: "wrap" }}>
                  {cab.loose_ends.map((ep) => (
                    <button
                      key={`${cab.id}-${ep.end}`}
                      data-testid={`orphan-link-${cab.id}-${ep.end}`}
                      onClick={() => setLinkModal({ cable: cab, end: ep })}
                      style={{
                        padding: "8px 12px", borderRadius: 8,
                        border: "1px solid #ea580c", background: "#fff",
                        color: "#9a3412", fontSize: 12, fontWeight: 700,
                        cursor: "pointer",
                      }}>
                      Vincular {ep.end === "from " ? "Origem" : "Destino"}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Modal de vínculo manual */}
      {linkModal && (
        <LinkEndpointModal
          cable={linkModal.cable}
          end={linkModal.end}
          elements={elements}
          onClose={() => setLinkModal(null)}
          onConfirm={async (elementId) => {
            await link(linkModal.cable.id, linkModal.end.end, elementId);
            setLinkModal(null);
          }} />
      )}

      {/* ======== AUTO-VINCULAÇÃO VISION IA (cron noturno) ======== */}
      {autoCfg && (
        <Card style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "center", gap: 8, flexWrap: "wrap",
                            marginBottom: 10 }}>
            <div>
              <h3 style={{ margin: "0 0 4px", fontSize: 16 }}>
                Auto-vínculo noturno (Vision IA)
              </h3>
              <p style={{ fontSize: 12, color: "var(--text-muted)",
                                margin: 0, lineHeight: 1.45 }}>
                Cron diário às {String(autoCfg.run_hour_utc).padStart(2, "0")}h
                UTC ({((autoCfg.run_hour_utc - 3 + 24) % 24)}h BRT) lê plaquetas
                de cabos órfãos com Claude Sonnet 4.5 e auto-vincula quando
                confiança ≥ {autoCfg.auto_link_threshold}%.
              </p>
            </div>
            <button data-testid="auto-vision-run-now" onClick={runAutoNow}
                       disabled={analyzing}
                       style={btnSm("#0d9488")}>
              {analyzing ? "..." : "▶ Rodar agora"}
            </button>
          </div>
          <div style={{ display: "grid", gap: 10,
                            gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
            <label style={{ display: "flex", flexDirection: "column",
                                gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 700 }}>
                Ativo
              </span>
              <input type="checkbox" data-testid="auto-vision-enabled"
                        checked={!!autoCfg.enabled}
                        disabled={autoSaving}
                        onChange={(e) => saveAutoCfg({
                          ...autoCfg, enabled: e.target.checked,
                        })}
                        style={{ width: 20, height: 20 }} />
            </label>
            <NumField testid="auto-vision-threshold"
              label="Auto-vincular (%)"
              help="Confiança ≥ X vincula sem revisão"
              value={autoCfg.auto_link_threshold} min={50} max={100}
              onChange={(v) => saveAutoCfg({
                ...autoCfg, auto_link_threshold: v,
              })} />
            <NumField testid="auto-vision-review"
              label="Revisar (%)"
              help="Confiança entre review e auto vai pra revisão manual"
              value={autoCfg.review_threshold} min={0} max={99}
              onChange={(v) => saveAutoCfg({
                ...autoCfg, review_threshold: v,
              })} />
            <NumField testid="auto-vision-hour"
              label="Hora UTC do scan"
              help="0-23 (default 6h UTC = 3h BRT)"
              value={autoCfg.run_hour_utc} min={0} max={23}
              onChange={(v) => saveAutoCfg({
                ...autoCfg, run_hour_utc: v,
              })} />
          </div>
        </Card>
      )}

      {/* ======== REVISÃO MANUAL (confiança média) ======== */}
      {pendingReviews.length > 0 && (
        <Card style={{ padding: 16 }}>
          <h3 style={{ margin: "0 0 4px", fontSize: 16 }}>
            ️ {pendingReviews.length} sugestão(ões) IA aguardando revisão
          </h3>
          <p style={{ fontSize: 12, color: "var(--text-muted)",
                            margin: "0 0 12px" }}>
            Cabos cuja Vision IA detectou plaqueta mas com confiança
            intermediária ({autoCfg?.review_threshold || 50}% a
            {" "}{(autoCfg?.auto_link_threshold || 90) - 1}%) — revisar manualmente.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {pendingReviews.map((r) => (
              <div key={r.id} style={{
                padding: 10, background: "#fffbeb",
                border: "1px solid #fde68a", borderRadius: 10,
                display: "flex", gap: 10, alignItems: "center",
                flexWrap: "wrap",
              }}>
                <div style={{
                  width: 42, textAlign: "center",
                  color: r.confidence >= 70 ? "#16a34a" : "#ea580c",
                  fontWeight: 900, fontSize: 18,
                }}>{r.confidence}%</div>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>
                    {r.cable_name}
                    {" "}<span style={{ color: "#94a3b8" }}>
                      ({r.end === "from " ? "Origem" : "Destino"})
                    </span>
                    {" → "}<strong>{r.suggested_element_name}</strong>
                  </div>
                  <div style={{ fontSize: 11, color: "#92400e", marginTop: 3 }}>
                    IA leu: <strong>“{r.extracted_text}”</strong>
                    {" · "}{r.distance_m}m
                  </div>
                </div>
                <button onClick={() => setVisualReview({
                          ...r, source: "vision_ai",
                        })}
                        style={btnSm("#7c3aed")}>️ Ver</button>
                <button onClick={() => approveReview(r.id)}
                        style={btnSm("#16a34a")}>✓</button>
                <button onClick={() => rejectReview(r.id)}
                        style={btnSm("#dc2626")}>✕</button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ======== MODAL CONFIANÇA VISUAL ======== */}
      {visualReview && (
        <VisualReviewModal
          item={visualReview}
          onClose={() => setVisualReview(null)}
          onAccept={async () => {
            await link(visualReview.cable_id, visualReview.end,
                        visualReview.suggested_element_id);
            setVisualReview(null);
            setSuggestions((prev) => prev.filter(
              (s) => !(s.cable_id === visualReview.cable_id
                       && s.end === visualReview.end),
            ));
          }} />
      )}
    </div>
  );
}

function VisualReviewModal({ item, onClose, onAccept }) {
  const [linking, setLinking] = useState(false);
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.65)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1100, padding: 16,
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: "#fff", borderRadius: 16, maxWidth: 720, width: "100%",
        maxHeight: "90vh", display: "flex", flexDirection: "column",
        overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{ padding: "14px 18px",
                          borderBottom: "1px solid #e2e8f0",
                          display: "flex", justifyContent: "space-between",
                          alignItems: "center", gap: 10 }}>
          <div>
            <div style={{ fontSize: 11, color: "#0d9488", fontWeight: 800,
                              textTransform: "uppercase", letterSpacing: 0.6 }}>
              ️ Confiança visual — Vision IA
            </div>
            <div style={{ fontSize: 17, fontWeight: 800, marginTop: 2 }}>
              {item.cable_name}
              {" "}<span style={{ color: "#94a3b8", fontWeight: 500 }}>
                ({item.end === "from " ? "Origem" : "Destino"})
              </span>
              {" → "}<span style={{ color: "#0d9488" }}>
                {item.suggested_element_name}
              </span>
            </div>
          </div>
          <button onClick={onClose}
                       style={{ background: "#f1f5f9", border: 0, padding: 10,
                                    borderRadius: 8, cursor: "pointer",
                                    fontSize: 16, fontWeight: 800 }}>
            ✕
          </button>
        </div>

        {/* Conteúdo */}
        <div style={{ flex: 1, overflowY: "auto", padding: 18 }}>
          {/* Confidence badge */}
          <div style={{ display: "flex", gap: 12, alignItems: "center",
                            marginBottom: 14 }}>
            <div style={{
              width: 78, height: 78, borderRadius: "50%",
              background: item.confidence >= 70 ? "#dcfce7"
                : item.confidence >= 40 ? "#fed7aa" : "#fee2e2",
              color: item.confidence >= 70 ? "#16a34a"
                : item.confidence >= 40 ? "#ea580c" : "#dc2626",
              display: "grid", placeItems: "center",
              fontSize: 24, fontWeight: 900,
              border: "4px solid",
              borderColor: item.confidence >= 70 ? "#16a34a"
                : item.confidence >= 40 ? "#ea580c" : "#dc2626",
            }}>
              {item.confidence}%
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>
                Confiança da Vision IA
              </div>
              <div style={{ fontSize: 12, color: "#64748b",
                                  lineHeight: 1.5 }}>
                {item.ai_reasoning || item.reasoning || "—"}
              </div>
            </div>
          </div>

          {/* Foto + OCR lado a lado */}
          <div style={{ display: "grid", gap: 12,
                            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}>
            {item.photo_url && (
              <div style={{ background: "#0f172a", borderRadius: 12,
                                  overflow: "hidden", aspectRatio: "1",
                                  display: "grid", placeItems: "center" }}>
                <img src={item.photo_url} alt="plaqueta"
                          style={{ maxWidth: "100%", maxHeight: "100%",
                                       objectFit: "contain" }} />
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ background: "#f1f5f9", padding: 12,
                                  borderRadius: 10 }}>
                <div style={{ fontSize: 10, color: "#64748b", fontWeight: 800,
                                    textTransform: "uppercase",
                                    letterSpacing: 0.5, marginBottom: 4 }}>
                  Texto extraído pela IA
                </div>
                <div style={{ fontSize: 18, fontWeight: 900,
                                    fontFamily: "monospace", color: "#0f172a" }}>
                  “{item.extracted_text || "—"}”
                </div>
                {item.raw_text && item.raw_text !== item.extracted_text && (
                  <div style={{ fontSize: 11, color: "#475569",
                                      marginTop: 6, fontStyle: "italic" }}>
                    Texto bruto OCR: “{item.raw_text}”
                  </div>
                )}
              </div>
              <div style={{ background: "#ecfeff", padding: 12,
                                  borderRadius: 10 }}>
                <div style={{ fontSize: 10, color: "#0e7490", fontWeight: 800,
                                    textTransform: "uppercase",
                                    letterSpacing: 0.5, marginBottom: 4 }}>
                  GPS da ponta solta
                </div>
                <div style={{ fontSize: 13, fontWeight: 700,
                                    color: "#0f172a", fontFamily: "monospace" }}>
                  {item.end_lat?.toFixed?.(6)}, {item.end_lng?.toFixed?.(6)}
                </div>
                <a href={`https://www.google.com/maps?q=${item.end_lat},${item.end_lng}`}
                        target="_blank" rel="noreferrer"
                        style={{ fontSize: 11, color: "#0e7490",
                                       textDecoration: "underline",
                                       marginTop: 4, display: "block" }}>
                  Ver no Google Maps ↗
                </a>
              </div>
              <div style={{ background: "#fef3c7", padding: 12,
                                  borderRadius: 10 }}>
                <div style={{ fontSize: 10, color: "#92400e", fontWeight: 800,
                                    textTransform: "uppercase",
                                    letterSpacing: 0.5, marginBottom: 4 }}>
                  Distância CTO/CE candidata
                </div>
                <div style={{ fontSize: 18, fontWeight: 900,
                                    color: "#7c2d12" }}>
                  {item.distance_m}m
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: 14, borderTop: "1px solid #e2e8f0",
                          display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}
                       style={btnSm("#64748b")}>Cancelar</button>
          <button data-testid="visual-review-accept"
                       disabled={linking}
                       onClick={async () => {
                         setLinking(true);
                         try { await onAccept(); } finally { setLinking(false); }
                       }}
                       style={btnSm("#16a34a")}>
            {linking ? "Vinculando..." : "✓ Confirmar vínculo"}
          </button>
        </div>
      </div>
    </div>
  );
}

function LinkEndpointModal({ cable, end, elements, onClose, onConfirm }) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);

  // Ordena por proximidade
  const sorted = useMemo(() => {
    const hav = (a, b, c, d) => {
      const R = 6371000;
      const toRad = (x) => x * Math.PI / 180;
      const dla = toRad(c - a); const dlo = toRad(d - b);
      const la1 = toRad(a); const la2 = toRad(c);
      const aa = Math.sin(dla / 2) ** 2
          + Math.cos(la1) * Math.cos(la2) * Math.sin(dlo / 2) ** 2;
      return 2 * R * Math.asin(Math.sqrt(aa));
    };
    return (elements || [])
      .filter((e) => e.lat != null && e.lng != null)
      .map((e) => ({
        ...e,
        dist: hav(end.lat, end.lng, e.lat, e.lng),
      }))
      .filter((e) => {
        if (!query) return true;
        const q = query.toLowerCase();
        return (e.name || "").toLowerCase().includes(q)
            || (e.bairro || "").toLowerCase().includes(q)
            || String(e.vlan || "").includes(q);
      })
      .sort((a, b) => a.dist - b.dist);
  }, [elements, end, query]);

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: 16,
    }}>
      <div style={{
        background: "#fff", borderRadius: 14, maxWidth: 540, width: "100%",
        maxHeight: "85vh", display: "flex", flexDirection: "column",
        overflow: "hidden",
      }}>
        <div style={{ padding: 14, borderBottom: "1px solid #e2e8f0" }}>
          <div style={{ fontSize: 15, fontWeight: 800 }}>
            Vincular {end.end === "from " ? "Origem" : "Destino"} do cabo
          </div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 3 }}>
            {cable.name} · GPS da ponta: {end.lat.toFixed(5)},
            {" "}{end.lng.toFixed(5)}
          </div>
        </div>
        <div style={{ padding: 12 }}>
          <input value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Buscar CTO/CE por nome, bairro, VLAN..."
                    data-testid="link-modal-search"
                    style={{
                      width: "100%", padding: "10px 12px", fontSize: 14,
                      borderRadius: 8, border: "1px solid #cbd5e1",
                      boxSizing: "border-box",
                    }} />
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "0 12px 12px" }}>
          {sorted.slice(0, 50).map((el) => (
            <button key={el.id}
                       data-testid={`link-modal-item-${el.id}`}
                       onClick={() => setSelected(el)}
                       style={{
                         display: "flex", width: "100%", padding: 10,
                         marginBottom: 6, gap: 10, alignItems: "center",
                         border: selected?.id === el.id
                            ? "2px solid #10b981"
                            : "1px solid #e2e8f0",
                         background: selected?.id === el.id
                            ? "#ecfdf5" : "#fff",
                         borderRadius: 10, cursor: "pointer",
                         textAlign: "left",
                       }}>
              <span style={{
                width: 32, height: 32, borderRadius: 8,
                background: el.type === "ce" ? "#ede9fe" : "#e0f2fe",
                color: el.type === "ce" ? "#7c3aed" : "#f28c28",
                display: "grid", placeItems: "center",
                fontSize: 11, fontWeight: 800,
              }}>{el.type.toUpperCase()}</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700,
                                 color: "#0f172a" }}>{el.name}</div>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                  {el.bairro || "—"} · VLAN {el.vlan || "—"}
                  {" · "}<strong>{Math.round(el.dist)}m</strong>
                </div>
              </span>
            </button>
          ))}
        </div>
        <div style={{ padding: 12, borderTop: "1px solid #e2e8f0",
                          display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}
                       style={btnSm("#64748b")}>Cancelar</button>
          <button data-testid="link-modal-confirm"
                       disabled={!selected}
                       onClick={() => selected && onConfirm(selected.id)}
                       style={{ ...btnSm("#10b981"),
                                opacity: selected ? 1 : 0.5 }}>
            Vincular {selected ? selected.name : ""}
          </button>
        </div>
      </div>
    </div>
  );
}



/* ============================================================
 * CABLE SLACK CONFIG — sobras técnicas no lançamento de cabo
 * Card aparece na aba "Diretrizes" (Rede IA admin).
 * ============================================================ */
function CableSlackEditor() {
  const [cfg, setCfg] = useState({
    slack_start_m: 10, slack_end_m: 10,
    gps_min_distance_m: 5, gps_interval_seconds: 3,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.redeIaCableSlackGet()
      .then((r) => setCfg({
        slack_start_m: Number(r.slack_start_m) || 10,
        slack_end_m: Number(r.slack_end_m) || 10,
        gps_min_distance_m: Number(r.gps_min_distance_m) || 5,
        gps_interval_seconds: Number(r.gps_interval_seconds) || 3,
      }))
      .catch(() => { /* mantém defaults */ })
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true); setErr("");
    try {
      await api.redeIaCableSlackUpdate(cfg);
      setSavedAt(new Date());
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro ao salvar");
    } finally { setSaving(false); }
  };

  const upd = (k, v) => setCfg((p) => ({ ...p, [k]: v }));

  if (loading) {
    return (
      <Card style={{ padding: 16 }}>
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
          Carregando configuração de sobras...
        </div>
      </Card>
    );
  }

  return (
    <Card style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 6px", fontSize: 16 }}>
        Sobras técnicas — Lançamento de cabo
      </h3>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14,
                       lineHeight: 1.45 }}>
        Define a metragem adicionada automaticamente no início e no fim de
        cada cabo cadastrado pelo técnico (reserva para emenda/manobra).
        Os parâmetros de GPS controlam a precisão da gravação de trajeto.
      </p>

      <div style={{ display: "grid", gap: 14,
                          gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
        <NumField
          testid="slack-start"
          label="Sobra início (m)"
          help="Reserva técnica antes da Origem"
          value={cfg.slack_start_m}
          min={0} max={200}
          onChange={(v) => upd("slack_start_m", v)} />
        <NumField
          testid="slack-end"
          label="Sobra fim (m)"
          help="Reserva técnica depois do Destino"
          value={cfg.slack_end_m}
          min={0} max={200}
          onChange={(v) => upd("slack_end_m", v)} />
        <NumField
          testid="slack-gps-distance"
          label="GPS — distância mín. (m)"
          help="Ignora amostras mais próximas que isso"
          value={cfg.gps_min_distance_m}
          min={1} max={50} step={0.5}
          onChange={(v) => upd("gps_min_distance_m", v)} />
        <NumField
          testid="slack-gps-interval"
          label="GPS — intervalo mín. (s)"
          help="Tempo entre amostras consecutivas"
          value={cfg.gps_interval_seconds}
          min={1} max={30} step={0.5}
          onChange={(v) => upd("gps_interval_seconds", v)} />
      </div>

      <div style={{ marginTop: 14, padding: 12, background: "#ecfeff",
                          border: "1px solid #67e8f9", borderRadius: 10,
                          fontSize: 12, color: "#155e75" }}>
        Total adicionado por cabo: <strong>
          {Number(cfg.slack_start_m) + Number(cfg.slack_end_m)}m
        </strong> {" "}(={cfg.slack_start_m}m início + {cfg.slack_end_m}m fim)
      </div>

      <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginTop: 12, gap: 10,
                          flexWrap: "wrap" }}>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {savedAt
            ? `Salvo às ${savedAt.toLocaleTimeString("pt-BR")}`
            : "Será aplicado nos próximos cadastros de cabo"}
        </div>
        <button data-testid="slack-save" onClick={save}
                       disabled={saving} style={btnSm("#0d9488")}>
          {saving ? "Salvando..." : "Salvar sobras"}
        </button>
      </div>
      {err && (
        <div style={{ marginTop: 10, color: "#dc2626", fontSize: 12 }}>
          {err}
        </div>
      )}
    </Card>
  );
}

function NumField({ testid, label, help, value, onChange,
                       min = 0, max = 999, step = 1 }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 12, fontWeight: 700,
                         color: "var(--text-primary)" }}>{label}</span>
      <input
        data-testid={testid}
        type="number" inputMode="decimal"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
        style={{
          padding: "8px 10px", borderRadius: 8,
          border: "1px solid var(--border-default)", fontSize: 14,
        }} />
      {help && (
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{help}</span>
      )}
    </label>
  );
}


/* ============================================================
 * AUDITORIA — apaga lançamentos de cabo (individual/lote)
 * ============================================================ */
function AuditCables({ currentUser }) {
  const [items, setItems] = useState([]);
  const [filterType, setFilterType] = useState("");
  const [filterUser, setFilterUser] = useState("");
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [bulkConfirm, setBulkConfirm] = useState("");
  const [refundStock, setRefundStock] = useState(true);

  const reload = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.redeIaMapData();
      const cables = (r.cables || []).slice()
        .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      setItems(cables);
      setSelected({});
    } finally { setBusy(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const filtered = useMemo(() => items.filter((c) =>
    (!filterType || c.type === filterType)
    && (!filterUser || (c.created_by || "").toLowerCase()
                            .includes(filterUser.toLowerCase()))
  ), [items, filterType, filterUser]);

  const allSelected = filtered.length > 0
    && filtered.every((c) => selected[c.id]);
  const someSelected = Object.values(selected).some(Boolean);
  const selectedIds = Object.keys(selected).filter((k) => selected[k]);

  const toggleAll = () => {
    if (allSelected) setSelected({});
    else {
      const next = {};
      filtered.forEach((c) => { next[c.id] = true; });
      setSelected(next);
    }
  };

  const deleteOne = async (cableId) => {
    if (!window.confirm(`Apagar cabo ${cableId}? Esta ação devolve a fibra ao estoque.`)) return;
    setBusy(true);
    try {
      await api.redeIaCableDelete(cableId);
      toast.success(`Cabo ${cableId} apagado`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const deleteSelected = async () => {
    if (!selectedIds.length) return;
    if (!window.confirm(`Apagar ${selectedIds.length} lançamento(s) selecionado(s)?`)) return;
    setBusy(true);
    try {
      const r = await api.redeIaCableBulkDelete({
        cable_ids: selectedIds, refund_stock: refundStock,
      });
      toast.success(`${r.deleted} lançamento(s) apagado(s). ${r.refunded.length} fibra(s) devolvidas.`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const deleteBulk = async () => {
    if (bulkConfirm !== "APAGAR LANCAMENTOS") {
      toast.error("Digite exatamente: APAGAR LANCAMENTOS");
      return;
    }
    setBusy(true);
    try {
      const r = await api.redeIaCableBulkDelete({
        cable_types: filterType ? [filterType] : null,
        refund_stock: refundStock,
        confirm_token: "APAGAR LANCAMENTOS",
      });
      toast.success(`✅ Auditoria: ${r.deleted} lançamento(s) apagado(s). ${r.refunded.length} fibra(s) devolvidas.`);
      setShowBulk(false);
      setBulkConfirm("");
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const fmtDate = (iso) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch (e) { return iso; }
  };

  return (
    <Card style={{ padding: 18 }} data-testid="rede-ia-audit-cables">
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 14,
                       flexWrap: "wrap", gap: 8 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                          color: "#7c2d12" }}>
            Auditoria de Lançamentos
          </h3>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Apague cabos individualmente ou em lote. Refund automático
            de fibra (6/12/24FO) ao estoque. Apenas auditor.
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <label style={{ fontSize: 11, color: "var(--text-secondary)",
                            display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={refundStock}
                      data-testid="audit-refund-toggle"
                      onChange={(e) => setRefundStock(e.target.checked)} />
            Devolver fibra
          </label>
          <button data-testid="audit-bulk-btn"
                    disabled={busy}
                    onClick={() => setShowBulk(true)}
                    style={{ padding: "7px 14px",
                              background: "#dc2626", color: "white",
                              border: "none", borderRadius: 7,
                              fontWeight: 700, fontSize: 12,
                              cursor: busy ? "wait" : "pointer" }}>
            Apagar TODOS (filtrados)
          </button>
        </div>
      </div>

      {/* Filtros */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12,
                       padding: 10, background: "var(--bg-subtle)",
                       borderRadius: 8 }}>
        <select value={filterType}
                  data-testid="audit-filter-type"
                  onChange={(e) => setFilterType(e.target.value)}
                  style={{ padding: "5px 8px", fontSize: 12,
                            borderRadius: 6, border: "1px solid var(--border-default)" }}>
          <option value="">Todos tipos</option>
          <option value="drop">DROP</option>
          <option value="6fo">06FO</option>
          <option value="12fo">12FO</option>
          <option value="24fo">24FO</option>
          <option value="48fo">48FO</option>
          <option value="96fo">96FO</option>
        </select>
        <input placeholder="Filtrar por criador (nome)"
                  data-testid="audit-filter-user"
                  value={filterUser}
                  onChange={(e) => setFilterUser(e.target.value)}
                  style={{ flex: 1, padding: "5px 10px", fontSize: 12,
                            borderRadius: 6, border: "1px solid var(--border-default)" }}/>
        <button onClick={reload}
                  style={{ padding: "5px 12px", fontSize: 12,
                            borderRadius: 6, border: "1px solid var(--border-default)",
                            background: "white", cursor: "pointer",
                            fontWeight: 700 }}>
          ↻ Recarregar
        </button>
      </div>

      {someSelected && (
        <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", padding: "8px 12px",
                          background: "#fef3c7", border: "1px solid #fcd34d",
                          borderRadius: 6, marginBottom: 8, fontSize: 12 }}>
          <span><strong>{selectedIds.length}</strong> selecionado(s)</span>
          <button data-testid="audit-delete-selected"
                    onClick={deleteSelected}
                    disabled={busy}
                    style={{ padding: "5px 12px", background: "#dc2626",
                              color: "white", border: "none", borderRadius: 6,
                              fontWeight: 700, fontSize: 12,
                              cursor: busy ? "wait" : "pointer" }}>
            Apagar selecionados
          </button>
        </div>
      )}

      {/* Tabela */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse",
                              fontSize: 12 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)",
                            textAlign: "left", fontSize: 11 }}>
              <th style={{ padding: "6px 8px" }}>
                <input type="checkbox" checked={allSelected}
                          onChange={toggleAll}
                          data-testid="audit-select-all" />
              </th>
              <th style={{ padding: "6px 8px" }}>ID</th>
              <th style={{ padding: "6px 8px" }}>Tipo</th>
              <th style={{ padding: "6px 8px" }}>Metros</th>
              <th style={{ padding: "6px 8px" }}>Criado por</th>
              <th style={{ padding: "6px 8px" }}>Em</th>
              <th style={{ padding: "6px 8px" }}>Débito</th>
              <th style={{ padding: "6px 8px" }}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={8} style={{ padding: 20, textAlign: "center",
                              color: "var(--text-muted)", fontStyle: "italic" }}>
                Nenhum lançamento corresponde aos filtros.
              </td></tr>
            )}
            {filtered.map((c) => {
              const sd = c.stok_debit;
              const isFiber = ["6fo", "12fo", "24fo"].includes(c.type);
              return (
                <tr key={c.id}
                     data-testid={`audit-cable-row-${c.id}`}
                     style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <td style={{ padding: "6px 8px" }}>
                    <input type="checkbox"
                              checked={!!selected[c.id]}
                              data-testid={`audit-select-${c.id}`}
                              onChange={(e) => setSelected({
                                ...selected, [c.id]: e.target.checked,
                              })} />
                  </td>
                  <td style={{ padding: "6px 8px", fontFamily: "monospace",
                                  fontSize: 11 }}>{c.id}</td>
                  <td style={{ padding: "6px 8px", fontWeight: 700,
                                  color: isFiber ? "#4338ca" : "var(--text-primary)" }}>
                    {(c.type || "").toUpperCase()}
                  </td>
                  <td style={{ padding: "6px 8px", fontWeight: 700 }}>
                    {c.length_m ? `${Math.round(c.length_m)}m` : "—"}
                  </td>
                  <td style={{ padding: "6px 8px" }}>
                    {c.created_by || "—"}
                  </td>
                  <td style={{ padding: "6px 8px",
                                  color: "var(--text-muted)" }}>
                    {fmtDate(c.created_at)}
                  </td>
                  <td style={{ padding: "6px 8px", fontSize: 10 }}>
                    {sd ? (
                      <span style={{ background: "#f0fdf4",
                                        color: "#065f46",
                                        padding: "2px 6px",
                                        borderRadius: 4, fontWeight: 700 }}>
                        {Math.abs(sd.meters_signed)}m {sd.location === "empresa" ? "Empresa" : "Téc."}
                      </span>
                    ) : "—"}
                  </td>
                  <td style={{ padding: "6px 8px" }}>
                    <button data-testid={`audit-delete-${c.id}`}
                              onClick={() => deleteOne(c.id)}
                              disabled={busy}
                              style={{ padding: "3px 8px",
                                        background: "white",
                                        border: "1px solid #fecaca",
                                        color: "#dc2626", borderRadius: 4,
                                        cursor: busy ? "wait" : "pointer",
                                        fontWeight: 700, fontSize: 10 }}>
                      Apagar
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Modal bulk */}
      {showBulk && (
        <div onClick={() => setShowBulk(false)}
              style={{ position: "fixed", inset: 0,
                        background: "rgba(0,0,0,0.5)",
                        display: "flex", alignItems: "center",
                        justifyContent: "center", zIndex: 999 }}>
          <div onClick={(e) => e.stopPropagation()}
                data-testid="audit-bulk-modal"
                style={{ background: "white", padding: 22,
                          borderRadius: 12, maxWidth: 460,
                          border: "2px solid #dc2626" }}>
            <h3 style={{ margin: "0 0 10px", color: "#7f1d1d",
                            fontSize: 17, fontWeight: 800 }}>
              Apagar lançamentos em massa
            </h3>
            <p style={{ fontSize: 13, color: "#475569",
                          marginBottom: 12 }}>
              Esta ação <strong>irreversível</strong> vai apagar{" "}
              <strong>{filtered.length}</strong> lançamento(s)
              {filterType ? ` do tipo ${filterType.toUpperCase()}` : ""}.
              {refundStock ? " Fibra (6/12/24FO) será DEVOLVIDA ao estoque."
                            : " Fibra NÃO será devolvida."}
            </p>
            <p style={{ fontSize: 12, color: "#475569",
                          marginBottom: 8 }}>
              Para confirmar, digite: <code style={{
                background: "#fef3c7", padding: "2px 6px",
                borderRadius: 4, fontWeight: 700,
              }}>APAGAR LANCAMENTOS</code>
            </p>
            <input data-testid="audit-bulk-confirm"
                      value={bulkConfirm}
                      onChange={(e) => setBulkConfirm(e.target.value)}
                      autoFocus
                      style={{ width: "100%", padding: 8,
                                border: "1px solid #cbd5e1",
                                borderRadius: 6, fontSize: 13,
                                fontFamily: "monospace",
                                marginBottom: 14 }}/>
            <div style={{ display: "flex", gap: 8,
                            justifyContent: "flex-end" }}>
              <button onClick={() => { setShowBulk(false); setBulkConfirm(""); }}
                        style={{ padding: "8px 16px",
                                  background: "white",
                                  border: "1px solid var(--border-default)",
                                  borderRadius: 6, fontWeight: 700,
                                  fontSize: 12, cursor: "pointer" }}>
                Cancelar
              </button>
              <button onClick={deleteBulk}
                        data-testid="audit-bulk-confirm-btn"
                        disabled={busy || bulkConfirm !== "APAGAR LANCAMENTOS"}
                        style={{ padding: "8px 16px",
                                  background: bulkConfirm === "APAGAR LANCAMENTOS"
                                    ? "#dc2626" : "#cbd5e1",
                                  color: "white", border: "none",
                                  borderRadius: 6, fontWeight: 700, fontSize: 12,
                                  cursor: bulkConfirm === "APAGAR LANCAMENTOS"
                                    ? "pointer" : "not-allowed" }}>
                Confirmar exclusão
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
