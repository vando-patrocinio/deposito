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
import { Card } from "@/ui";
import { toast } from "sonner";
import RedeIaMap from "@/RedeIaMap";
import ReconcileAuditPanel from "@/ReconcileAuditPanel";
import CTOLocationViewer from "@/CTOLocationViewer";
import CTOOccupancyPanel from "@/CTOOccupancyPanel";
import { KpiCard, AlertCard } from "@/components/Dashboard2026";

const TABS = [
  { id: "overview", label: "Painel" },
  { id: "ctos", label: "CTOs" },
  { id: "occupancy", label: "📊 Ocupação" },
  { id: "pendencies", label: "Pendências" },
  { id: "map", label: "Mapa interativo" },
  { id: "reconcile", label: "🔍 Conciliação" },
  { id: "bairros", label: "Bairros / VLAN" },
  { id: "history", label: "Histórico" },
  { id: "diretrizes", label: "Diretrizes" },
  { id: "audit", label: "🛡 Auditoria", auditorOnly: true },
];

const STATUS_BADGE = {
  pending_validation: { l: "Aguardando validação", c: "#ca8a04", bg: "#fef9c3" },
  pending_correction: { l: "Correção solicitada", c: "#9a3412", bg: "#fed7aa" },
  approved: { l: "Aprovada", c: "#15803d", bg: "#dcfce7" },
  rejected: { l: "Rejeitada", c: "#b91c1c", bg: "#fee2e2" },
};

export default function RedeIaPanel({ currentUser }) {
  const [tab, setTab] = useState("overview");
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
            🔔 Notificações
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
      {tab === "pendencies" && <Pendencies />}
      {tab === "occupancy" && <CTOOccupancyPanel />}
      {tab === "map" && <RedeIaMap />}
      {tab === "reconcile" && <ReconcileAuditPanel />}
      {tab === "bairros" && <BairrosManager />}
      {tab === "history" && <HistoryList />}
      {tab === "diretrizes" && <DiretrizesEditor />}
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
  useEffect(() => {
    api.redeIaCtosList().then((r) => setCtos(r.items || []));
    api.redeIaPendencies().then((r) => setPend(r.items || []));
    api.redeIaBairros().then((r) => setBairros(r.items || []));
    api.redeIaMapData().then((r) => setMapData(r)).catch(() => {});
    api.redeIaFiberAlerts(200).then(setFiberAlerts).catch(() => {});
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
            <AlertCard tone="info" icon="📭"
              testId="rede-ia-alert-no-ctos"
              title="Nenhuma CTO cadastrada"
              detail="Use o app do técnico para cadastrar as primeiras CTOs." />
          )}
          {criticalVlans.length > 0 && (
            <AlertCard tone="bad" icon="🔴"
              testId="rede-ia-alert-critical-vlans"
              title={`${criticalVlans.length} VLAN${criticalVlans.length !== 1 ? "s" : ""} em estado crítico`}
              detail={criticalVlans.slice(0, 3).map((v) =>
                `VLAN ${v.vlan} (${v.avg_score}%)`).join(" · ")} />
          )}
          {warningVlans.length > 0 && criticalVlans.length === 0 && (
            <AlertCard tone="warn" icon="🟡"
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
            <AlertCard tone="warn" icon="📶"
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
          🛰 Integração SmartOLT IA
          <span style={{ fontSize: 11, fontWeight: 500, color: "var(--text-muted)" }}>
            (rede_IA cruza CTOs com ONUs reais)
          </span>
        </h3>
        <div style={{ display: "grid",
                         gridTemplateColumns: "repeat(auto-fit, minmax(180px,1fr))",
                         gap: 10 }}>
          <MiniKpi label="CTOs com ONUs detectadas"
            value={`${ctosWithOnu} / ${mapData.ctos?.length || 0}`}
            color="#0ea5e9" />
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
      </Card>

      {/* CTOs por Técnico + Filial */}
      <CtoStatsBlock stats={techStats}
                      period={statsPeriod}
                      onChangePeriod={setStatsPeriod} />

      {/* Saúde por VLAN */}
      {mapData.vlans && mapData.vlans.length > 0 && (
        <Card style={{ padding: 16 }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>
            📡 Média de sinal por VLAN (vinda do SmartOLT)
          </h3>
          <div style={{ display: "grid", gap: 8 }}>
            {mapData.vlans.map((v) => {
              const status = v.avg_score < 50 ? "critical"
                : v.avg_score < 75 ? "warning" : "ok";
              const bg = status === "critical" ? "#fee2e2"
                : status === "warning" ? "#fef3c7" : "#dcfce7";
              const fg = status === "critical" ? "#991b1b"
                : status === "warning" ? "#92400e" : "#166534";
              return (
                <div key={v.vlan} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 14px", borderRadius: 10,
                  background: bg, border: `1px solid ${fg}33`,
                }}>
                  <div style={{ fontWeight: 800, fontSize: 14, color: fg, minWidth: 130 }}>
                    VLAN {v.vlan} ({v.sigla})
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{
                      height: 8, borderRadius: 99,
                      background: "rgba(0,0,0,0.08)",
                      overflow: "hidden",
                    }}>
                      <div style={{
                        height: "100%", width: `${v.avg_score}%`,
                        background: fg, transition: "width .3s",
                      }} />
                    </div>
                  </div>
                  <div style={{ fontSize: 13, color: fg, fontWeight: 700,
                                  minWidth: 56, textAlign: "right" }}>
                    {v.avg_score}%
                  </div>
                  <div style={{ fontSize: 11, color: fg, minWidth: 120 }}>
                    {v.cto_count} CTOs · {v.critical || 0}🔴 {v.warning || 0}🟡 {v.ok || 0}🟢
                  </div>
                </div>
              );
            })}
          </div>
          <p style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted)" }}>
            ℹ️ A rede_IA consulta o SmartOLT em tempo real para calcular a saúde média
            das CTOs por VLAN. CTOs sem ONUs detectadas pelo SmartOLT são contabilizadas
            como "sem dados" e não influenciam a média.
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
          🏆 Ranking de CTOs · {periodLabel[period] || "Geral"}
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
                        ? "linear-gradient(135deg,#0ea5e9,#6366f1)"
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
            👷 Por técnico
          </div>
          {byTech.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Nenhum dado ainda.
            </div>
          )}
          <div style={{ display: "grid", gap: 6 }}>
            {byTech.map((t, idx) => {
              const medals = ["🥇", "🥈", "🥉"];
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
                         background: "linear-gradient(135deg,#0ea5e9,#6366f1)",
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
                    background: "linear-gradient(90deg,#0ea5e9,#6366f1)",
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
                height: 10, background: "#6366f1", borderRadius: 2,
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
            🏢 Por filial
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
            🧵 Curva de lançamento de fibra
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
              ⚠️ Saldo baixo (&lt; {alerts.threshold}m)
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
                              background: "linear-gradient(135deg,#0ea5e9,#6366f1)",
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
                              style={{ ...btnSm("#0ea5e9"), textDecoration: "none",
                                        display: "inline-flex", alignItems: "center" }}>
                            ☁
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
      {busy ? "…" : "☁+"}
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
  const load = useCallback(async () => {
    setLoading(true);
    const r = await api.redeIaPendencies();
    setItems(r.items || []);
    setLoading(false);
  }, []);
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
                       alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>Pendências de validação</h3>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {loading ? "Carregando..." : `${items.length} aguardando`}
        </span>
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
                  {p.smartolt_hints && p.smartolt_hints.matched > 0 && (
                    <div data-testid={`smartolt-hints-${p.id}`} style={{
                      marginTop: 10, padding: "8px 10px", borderRadius: 6,
                      background: "#ecfdf5", border: "1px solid #6ee7b7",
                      fontSize: 11, color: "#065f46",
                    }}>
                      <strong>🛰 SmartOLT detectou {p.smartolt_hints.matched} ONUs</strong>
                      {p.smartolt_hints.alerts > 0 && (
                        <span style={{ color: "#b91c1c", marginLeft: 6 }}>
                          ⚠️ {p.smartolt_hints.alerts} com alerta de sinal
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
                      🗺 Ver no mapa
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
          📸 {ctoName || "CTO"}
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
                                          cidade: "", estado: "", regiao: "" });
  const [err, setErr] = useState("");
  const [onusModal, setOnusModal] = useState(null); // {vlan, bairro}
  const load = useCallback(async () => {
    const r = await api.redeIaBairros();
    setItems(r.items || []);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setErr("");
    try {
      await api.redeIaBairroCreate({
        ...form, vlan: parseInt(form.vlan, 10),
      });
      setForm({ bairro: "", sigla: "", vlan: "", cidade: "", estado: "", regiao: "" });
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
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr auto",
                       gap: 8, marginBottom: 14, alignItems: "end" }}>
        <Field l="Bairro" v={form.bairro} on={(v) => setForm({ ...form, bairro: v })}
                tid="bairro-input" />
        <Field l="Sigla" v={form.sigla}
                on={(v) => setForm({ ...form, sigla: v.toUpperCase() })} tid="sigla-input" />
        <Field l="VLAN" v={form.vlan} on={(v) => setForm({ ...form, vlan: v })}
                tid="vlan-input" type="number" />
        <Field l="Cidade" v={form.cidade} on={(v) => setForm({ ...form, cidade: v })} />
        <Field l="UF" v={form.estado} on={(v) => setForm({ ...form, estado: v.toUpperCase() })} />
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
            <th style={th}>Cidade/UF</th><th style={th}></th>
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
                <button onClick={() => setOnusModal({ vlan: b.vlan, bairro: b.bairro })}
                        style={{ ...btnSm("#0ea5e9"), padding: "4px 10px",
                                  fontSize: 11, marginRight: 6 }}
                        data-testid={`bairro-list-onus-${b.id}`}
                        title={`Buscar ONUs na SmartOLT pela VLAN ${b.vlan}`}>
                  📡 ONUs
                </button>
                <button onClick={() => del(b.id)}
                        style={{ ...btnSm("#dc2626"), padding: "4px 8px", fontSize: 11 }}
                        data-testid={`bairro-del-${b.id}`}>×</button>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan="5" style={{ ...td, textAlign: "center", padding: 20,
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
              📡 ONUs autorizadas — VLAN {vlan}
            </h3>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b" }}>
              Bairro: <strong>{bairro}</strong>
              {data && (
                <> · {data.count} ONUs encontradas na SmartOLT
                  <span style={{ marginLeft: 8, fontSize: 10, padding: "2px 6px",
                                  background: "#dcfce7", color: "#166534",
                                  borderRadius: 999, fontWeight: 700 }}>
                    LIVE
                  </span>
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
                placeholder="🔎 Filtrar por nome, SN, endereço ou zona..."
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
              ⚠️ {error}
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
                          {o.address}
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
              🔧 {onuLive.name || "ONU"}
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
              📡 Sinal atual
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
                           borderRadius: 6, fontSize: 12 }}>⚠️ {sigError}</div>
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
            {feedback.ok ? "✓ " : "⚠️ "}{feedback.msg}
          </div>
        )}

        {/* ACTION HISTORY */}
        <div>
          <strong style={{ fontSize: 12, color: "#0f172a",
                            textTransform: "uppercase", letterSpacing: 0.6 }}>
            🕓 Histórico de ações
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
            🛡 Auditoria de Lançamentos
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
            ⚠ Apagar TODOS (filtrados)
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
              ⚠ Apagar lançamentos em massa
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
