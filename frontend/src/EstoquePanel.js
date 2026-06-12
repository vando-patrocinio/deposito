import React, { useEffect, useMemo, useState, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import PracaStockCard from "@/PracaStockCard";
import BalancoTab from "@/BalancoTab";
import { GranularResetButton, ShrinkageReportCard } from "@/StokAuditCards";
import CentralComprasPanel from "@/CentralComprasPanel";
import OntBatchHistoryPanel from "@/OntBatchHistoryPanel";
import StokTransfersPanel from "@/StokTransfersPanel";
import DefectiveOntsPanel from "@/DefectiveOntsPanel";
import WithdrawSnAuditPanel from "@/WithdrawSnAuditPanel";
import ClientEquipmentHistoryModal from "@/ClientEquipmentHistoryModal";
import OntTraceabilityModal from "@/OntTraceabilityModal";
import ManualWithdrawDialog from "@/ManualWithdrawDialog";
import OntDuplicateAlertsPanel from "@/OntDuplicateAlertsPanel";
import StokHealthDashboard from "@/StokHealthDashboard";
import StokAiReviewPanel from "@/StokAiReviewPanel";
import SmartoltHistoryPanel from "@/SmartoltHistoryPanel";

// ============================================================
// Helpers visuais
// ============================================================
const SUB_TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "saude", label: "Saúde" },
  { id: "onts", label: "ONTs" },
  { id: "insumos", label: "Insumos" },
  { id: "clientes", label: "Clientes (SmartOLT)" },
  { id: "smartolt-historico", label: "Histórico SmartOLT" },
  { id: "servicos", label: "Ordens de serviço" },
  { id: "balanco", label: "Balanço" },
  { id: "historico", label: "Histórico" },
  { id: "transfers", label: "Transferências" },
  { id: "ai-review", label: "Revisão IA" },
  { id: "defeitos", label: "️ Defeitos" },
  { id: "duplicados", label: "ONTs Duplicadas" },
  { id: "audit-sn", label: "Auditoria SN" },
  { id: "lotes", label: "Retiradas em Lote" },
  { id: "compras", label: "Central de Compras" },
];

const STATUS_COLORS = {
  disponivel: { bg: "#dcfce7", color: "#166534", label: "Disponível" },
  com_tecnico: { bg: "#dbeafe", color: "#1e40af", label: "Com técnico" },
  instalada: { bg: "#fed7aa", color: "#9a3412", label: "Instalada" },
  retirada_com_tecnico: { bg: "#fef3c7", color: "#92400e", label: "Retirada c/ téc." },
  retornada_empresa: { bg: "#e2e8f0", color: "#475569", label: "Retornada empresa" },
  ativo: { bg: "#dcfce7", color: "#166534", label: "Ativo" },
  fechado: { bg: "#e2e8f0", color: "#475569", label: "Fechado" },
  cancelado: { bg: "#fee2e2", color: "#991b1b", label: "Cancelado" },
  erro_estoque: { bg: "#fee2e2", color: "#991b1b", label: "Erro estoque" },
  defeito_devolver_empresa: { bg: "#fee2e2", color: "#7f1d1d", label: "Defeito · devolver" },
  defeito_em_analise: { bg: "#fef3c7", color: "#854d0e", label: "Em análise" },
  sucateada: { bg: "#e2e8f0", color: "#475569", label: "Sucateada" },
};

function StatusPill({ status }) {
  const s = STATUS_COLORS[status] || { bg: "#f1f5f9", color: "#475569", label: status };
  return (
    <span style={{ background: s.bg, color: s.color, padding: "2px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700, letterSpacing: 0.2 }}>
      {s.label}
    </span>
  );
}

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("pt-BR"); } catch { return iso; }
}

function asyncCall(fn, onDone, errMsgPrefix = "Erro") {
  return async (...args) => {
    try { await fn(...args); if (onDone) onDone(); }
    catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Erro desconhecido";
      await window.alert(`${errMsgPrefix}: ${detail}`);
    }
  };
}

// ============================================================
// Dialog primitivo
// ============================================================
function Modal({ open, onClose, title, children, footer, "data-testid": testId }) {
  if (!open) return null;
  return (
    <div data-testid={testId} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", zIndex: 100,
      display: "grid", placeItems: "center", padding: 16,
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 18, padding: 22, width: "100%", maxWidth: 560,
        boxShadow: "0 20px 60px rgba(15,23,42,.25)", maxHeight: "90vh", overflow: "auto",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "#0f172a" }}>{title}</h3>
          <button onClick={onClose} style={{ background: "transparent", border: "none", fontSize: 22, cursor: "pointer", color: "#64748b" }}>×</button>
        </div>
        {children}
        {footer && <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>{footer}</div>}
      </div>
    </div>
  );
}

const inputStyle = {
  width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid #cbd5e1",
  fontSize: 14, fontFamily: "inherit", outline: "none", boxSizing: "border-box",
};
const labelStyle = { fontSize: 12, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 6, display: "block" };
const btnPrimary = { padding: "9px 18px", background: "#0f172a", color: "white", border: "none", borderRadius: 10, fontWeight: 700, cursor: "pointer", fontSize: 13 };
const btnSec = { padding: "9px 18px", background: "white", color: "#0f172a", border: "1px solid #cbd5e1", borderRadius: 10, fontWeight: 700, cursor: "pointer", fontSize: 13 };
const btnDanger = { ...btnPrimary, background: "#dc2626" };
const btnGhost = { padding: "6px 12px", background: "transparent", color: "#0f172a", border: "1px solid #e2e8f0", borderRadius: 8, fontWeight: 600, cursor: "pointer", fontSize: 12 };

// ============================================================
// Dashboard 2026 — Summary First → Movement → Detail
// Blueprint: alerts top-strip, contextual KPI cards with sparkline,
// stock-by-location distribution, SKU stock with progress, activity feed.
// ============================================================
function DashboardSection({ dashboard, consumables, history = [], onts = [] }) {
  // ONTs agrupadas por técnico (location_type=tecnico) — para popover ao
  // clicar no item "ONT N" do card de cada técnico.
  const ontsByTech = React.useMemo(() => {
    const m = {};
    (onts || []).forEach((o) => {
      if (o.location_type === "tecnico" && o.location_id) {
        (m[o.location_id] = m[o.location_id] || []).push(o);
      }
    });
    return m;
  }, [onts]);

  // Histórico indexado por MAC (regex em description) — pra mini-timeline
  // expansível no popover.
  const historyByMac = React.useMemo(() => {
    const m = {};
    (history || []).forEach((h) => {
      const text = `${h.description || ""} ${h.notes || ""}`;
      const matches = text.match(/[0-9A-F]{2}(?::[0-9A-F]{2}){5}/gi);
      (matches || []).forEach((mac) => {
        const k = mac.toUpperCase();
        (m[k] = m[k] || []).push(h);
      });
    });
    // Ordena por data desc
    Object.keys(m).forEach((k) => m[k].sort((a, b) =>
      (b.created_at || b.date || "").localeCompare(
        a.created_at || a.date || "")));
    return m;
  }, [history]);

  const [popoverTechId, setPopoverTechId] = React.useState(null);
  const [expandedMac, setExpandedMac] = React.useState(null);
  React.useEffect(() => {
    if (!popoverTechId) return;
    const close = () => setPopoverTechId(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [popoverTechId]);
  if (!dashboard) return <Card>Carregando dashboard…</Card>;

  // ---- Métricas derivadas ----
  const totalOnts = dashboard.total_onts || 0;
  const companyOnts = dashboard.company_onts || 0;
  const techOnts = dashboard.tech_rows.reduce((s, t) => s + (t.tech_onts || 0), 0);
  const installedOnts = totalOnts - companyOnts - techOnts;

  // last 30d e last 7d trends
  const now = Date.now();
  const d30 = now - 30 * 86400 * 1000;
  const d7 = now - 7 * 86400 * 1000;
  const histInRange = history.filter((h) => {
    const t = new Date(h.date).getTime();
    return !isNaN(t) && t >= d30;
  });
  const installs30 = histInRange.filter((h) => h.type === "instalacao").length;
  const withdrawals30 = histInRange.filter((h) => h.type === "retirada").length;
  const returns30 = histInRange.filter((h) => h.type === "devolucao").length;
  const installs7 = history.filter((h) => h.type === "instalacao"
    && new Date(h.date).getTime() >= d7).length;
  const prevWeekInstalls = history.filter((h) => h.type === "instalacao"
    && new Date(h.date).getTime() >= d30
    && new Date(h.date).getTime() < d7).length / 3.3; // média semanal dos 23 dias anteriores
  const velocityDelta = prevWeekInstalls > 0
    ? Math.round(((installs7 - prevWeekInstalls) / prevWeekInstalls) * 100) : 0;

  // Days of supply: estoque atual / consumo médio diário (últimos 30d)
  const dailyConsumption = installs30 / 30.0;
  const daysOfSupply = dailyConsumption > 0
    ? Math.round(companyOnts / dailyConsumption) : null;

  // Low stock / stockout — para insumos
  const lowStockItems = consumables.filter((c) =>
    (dashboard.empresa_stock?.[c.id] || 0) > 0
    && (dashboard.empresa_stock?.[c.id] || 0) < 10);
  const stockoutItems = consumables.filter((c) =>
    (dashboard.empresa_stock?.[c.id] || 0) === 0);
  const hasOntStockout = companyOnts === 0;
  const lowOntStock = companyOnts > 0 && companyOnts < 5;

  // Sparkline data: instalações por dia nos últimos 14 dias
  const sparkInstalls = Array.from({ length: 14 }, (_, i) => {
    const day = now - (13 - i) * 86400 * 1000;
    const next = day + 86400 * 1000;
    return history.filter((h) => h.type === "instalacao"
      && new Date(h.date).getTime() >= day
      && new Date(h.date).getTime() < next).length;
  });

  const sparkAll = Array.from({ length: 14 }, (_, i) => {
    const day = now - (13 - i) * 86400 * 1000;
    const next = day + 86400 * 1000;
    return history.filter((h) => new Date(h.date).getTime() >= day
      && new Date(h.date).getTime() < next).length;
  });

  // Threshold da withdrawal_rate
  const rate = dashboard.withdrawal_rate || 0;
  const rateTone = rate >= 80 ? "good" : rate >= 60 ? "warn" : "bad";

  // Localização (donut alternativo - barras empilhadas horizontais)
  const locDist = [
    { key: "empresa", label: "Estoque", count: companyOnts, color: "#0ea5e9" },
    { key: "tecnicos", label: "Com técnicos", count: techOnts, color: "#8b5cf6" },
    { key: "instaladas", label: "Instaladas", count: installedOnts, color: "#10b981" },
  ];

  // Activity feed: últimas 8 movimentações
  const recentActivity = history
    .slice() // não-mutar
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
    .slice(0, 8);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* === Strip de alertas (só quando aplicável) === */}
      {(hasOntStockout || lowOntStock || stockoutItems.length > 0 || lowStockItems.length > 0) && (
        <div data-testid="stock-alerts-strip" style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
          gap: 10,
        }}>
          {hasOntStockout && (
            <AlertCard tone="bad" icon=""
              title="Estoque de ONTs zerado"
              detail="Nenhuma ONT disponível no estoque da empresa." />
          )}
          {!hasOntStockout && lowOntStock && (
            <AlertCard tone="warn" icon=""
              title={`Apenas ${companyOnts} ONT${companyOnts !== 1 ? "s" : ""} em estoque`}
              detail="Considere comprar mais para evitar atrasos nas instalações." />
          )}
          {stockoutItems.length > 0 && (
            <AlertCard tone="bad" icon=""
              title={`${stockoutItems.length} insumo${stockoutItems.length !== 1 ? "s" : ""} zerado${stockoutItems.length !== 1 ? "s" : ""}`}
              detail={stockoutItems.slice(0, 3).map((c) => c.name).join(", ")
                + (stockoutItems.length > 3 ? "…" : "")} />
          )}
          {lowStockItems.length > 0 && (
            <AlertCard tone="warn" icon=""
              title={`${lowStockItems.length} insumo${lowStockItems.length !== 1 ? "s" : ""} com estoque baixo`}
              detail={lowStockItems.slice(0, 3).map((c) =>
                `${c.name} (${dashboard.empresa_stock?.[c.id] || 0})`).join(", ")} />
          )}
        </div>
      )}

      {/* === Row 1: KPI cards contextuais === */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
        gap: 14,
      }}>
        <KpiCard
          testId="kpi-onts-stock"
          label="ONTs no estoque"
          value={companyOnts}
          unit="un"
          tone={companyOnts === 0 ? "bad" : companyOnts < 5 ? "warn" : "good"}
          hint={`${totalOnts} totais · ${techOnts} com técnicos`} />
        <KpiCard
          testId="kpi-installations"
          label="Instalações · 7 dias"
          value={installs7}
          unit=""
          tone={velocityDelta >= 0 ? "good" : velocityDelta > -20 ? "warn" : "bad"}
          delta={installs7 === 0 && prevWeekInstalls === 0 ? null : velocityDelta}
          sparkline={sparkInstalls.some((v) => v > 0) ? sparkInstalls : null}
          sparkColor="#10b981"
          hint={`${installs30} nos últimos 30d`} />
        <KpiCard
          testId="kpi-active-services"
          label="OS ativas"
          value={dashboard.active_services_count || 0}
          unit=""
          tone="info"
          hint={`${dashboard.technicians_count} técnicos`} />
        <KpiCard
          testId="kpi-days-of-supply"
          label="Dias de cobertura"
          value={daysOfSupply == null ? "—" : daysOfSupply}
          unit={daysOfSupply == null ? "" : "dias"}
          tone={daysOfSupply == null ? "info"
              : daysOfSupply >= 14 ? "good"
              : daysOfSupply >= 7 ? "warn" : "bad"}
          hint={daysOfSupply == null
            ? "Sem consumo recente para estimar"
            : `Baseado em ${dailyConsumption.toFixed(1)} ONT/dia`} />
        <KpiCard
          testId="kpi-withdrawal-rate"
          label="Eficiência retirada"
          value={`${rate}%`}
          unit=""
          tone={rateTone}
          progress={rate}
          hint={`${dashboard.effective_withdrawals || 0} / ${dashboard.expected_withdrawals || 0}`} />
      </div>

      {/* === Row 2: Movimento + Distribuição === */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)",
        gap: 14,
      }}>
        {/* Movimento últimos 14 dias */}
        <Card title={(
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            Movimento · 14 dias
          </span>
        )} data-testid="movement-trend-card">
          <MovementChart
            install={sparkInstalls}
            all={sparkAll}
          />
          <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap",
                          fontSize: 12, color: "#475569" }}>
            <Legend color="#10b981" label="Instalações" value={installs30} />
            <Legend color="#0ea5e9" label="Retiradas" value={withdrawals30} />
            <Legend color="#8b5cf6" label="Devoluções" value={returns30} />
          </div>
        </Card>

        {/* Distribuição por localização */}
        <Card title="Onde estão as ONTs" data-testid="location-distribution-card">
          <LocationBars items={locDist} total={totalOnts} />
        </Card>
      </div>

      {/* === Row 3: Stock por SKU + Activity feed === */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(0,1.6fr) minmax(0,1fr)",
        gap: 14,
      }}>
        <Card title="Estoque da Empresa · por insumo" data-testid="empresa-stock-card">
          <div style={{ display: "grid", gap: 10 }}>
            {consumables.map((c) => {
              const empVal = dashboard.empresa_stock?.[c.id] || 0;
              const techVal = dashboard.tech_rows.reduce(
                (s, t) => s + (t.stock?.[c.id] || 0), 0);
              const total = empVal + techVal;
              const empPct = total > 0 ? (empVal / total) * 100 : 0;
              const tone = empVal === 0 ? "bad" : empVal < 10 ? "warn" : "good";
              const toneColor = tone === "bad" ? "#dc2626"
                              : tone === "warn" ? "#d97706" : "#16a34a";
              return (
                <div key={c.id} style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  alignItems: "center", gap: 10,
                }}>
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between",
                                    alignItems: "center", marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>
                        {c.name}
                      </span>
                      <span style={{ fontSize: 11, color: "#64748b" }}>
                        {techVal} c/ téc.
                      </span>
                    </div>
                    <div style={{ height: 8, background: "#f1f5f9",
                                    borderRadius: 999, overflow: "hidden",
                                    display: "flex" }}>
                      <div style={{ width: `${empPct}%`,
                                      background: toneColor,
                                      transition: "width .35s ease" }} />
                      <div style={{ width: `${100 - empPct}%`,
                                      background: "#cbd5e1" }} />
                    </div>
                  </div>
                  <div style={{ textAlign: "right", minWidth: 84 }}>
                    <div style={{ fontSize: 18, fontWeight: 800,
                                    color: toneColor,
                                    fontVariantNumeric: "tabular-nums",
                                    lineHeight: 1 }}>
                      {empVal}
                    </div>
                    <div style={{ fontSize: 10, color: "#64748b",
                                    textTransform: "uppercase",
                                    fontWeight: 700, letterSpacing: 0.3 }}>
                      {c.unit} · estoque
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        <Card title="Movimentações recentes" data-testid="activity-feed-card">
          {recentActivity.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12, color: "#64748b",
                            textAlign: "center" }}>
              Nenhuma movimentação registrada.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {recentActivity.map((h, i) => {
                const tone = h.type === "instalacao" ? { bg: "#dcfce7", color: "#166534", ic: "↗" }
                  : h.type === "retirada" ? { bg: "#dbeafe", color: "#1e40af", ic: "↘" }
                  : h.type === "devolucao" ? { bg: "#fef3c7", color: "#92400e", ic: "↩" }
                  : { bg: "#f1f5f9", color: "#475569", ic: "•" };
                return (
                  <div key={i} data-testid={`activity-row-${i}`}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "auto 1fr auto",
                          alignItems: "center", gap: 8,
                          padding: "6px 8px", borderRadius: 8,
                          background: i % 2 === 0 ? "transparent" : "#f8fafc",
                        }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: "50%",
                      background: tone.bg, color: tone.color,
                      display: "grid", placeItems: "center",
                      fontSize: 12, fontWeight: 800,
                    }}>{tone.ic}</span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12, color: "#0f172a",
                                      overflow: "hidden",
                                      textOverflow: "ellipsis",
                                      whiteSpace: "nowrap" }}>
                        {h.description}
                      </div>
                      <div style={{ fontSize: 10, color: "#94a3b8" }}>
                        {h.user || "Sistema"} · {fmtDate(h.date)}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {/* === Row 3.5: Estoque por Praça === */}
      <PracaStockCard />

      {/* === Row 4: Ranking técnicos === */}
      <Card title={(
        <span>Estoque por técnico</span>
      )} data-testid="tech-rows-card">
        {dashboard.tech_rows.length === 0 ? (
          <div style={{ color: "#64748b" }}>Nenhum técnico ativo.</div>
        ) : (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))",
            gap: 10,
          }}>
            {dashboard.tech_rows.map((t) => {
              const ontTone = t.tech_onts === 0 ? "#94a3b8"
                : t.tech_onts >= 3 ? "#10b981" : "#d97706";
              return (
                <div key={t.id} data-testid={`tech-row-${t.id}`}
                      style={{
                        background: "#fff",
                        border: "1px solid #e2e8f0",
                        borderRadius: 12, padding: 12,
                        borderLeft: `4px solid ${ontTone}`,
                      }}>
                  <div style={{ display: "flex", justifyContent: "space-between",
                                    alignItems: "center", marginBottom: 8, gap: 6 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 800,
                                      color: "#0f172a",
                                      overflow: "hidden",
                                      textOverflow: "ellipsis",
                                      whiteSpace: "nowrap" }}>
                        {t.name}
                      </div>
                      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                        ↗ {t.installed_month}{" "}
                        <span style={{ opacity: 0.6 }}>inst.</span>
                        {" · ↘ "}{t.withdrawals}{" "}
                        <span style={{ opacity: 0.6 }}>retir.</span>
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      <div style={{ fontSize: 22, fontWeight: 800,
                                      color: ontTone, lineHeight: 1,
                                      fontVariantNumeric: "tabular-nums" }}>
                        {t.tech_onts}
                      </div>
                      <div style={{ fontSize: 9, color: "#64748b",
                                      textTransform: "uppercase",
                                      fontWeight: 700, letterSpacing: 0.3 }}>
                        ONTs
                      </div>
                    </div>
                  </div>
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit,minmax(82px,1fr))",
                    gap: 4,
                  }}>
                    {/* ONT/ONU como item de destaque no início (clicável:
                        abre popover com lista de MACs daquele técnico). */}
                    <button
                      type="button"
                      data-testid={`tech-row-${t.id}-ont`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setPopoverTechId(popoverTechId === t.id ? null : t.id);
                      }}
                      title={t.tech_onts === 0
                        ? "Sem ONT — clique pra fechar"
                        : "Clique para ver MACs"}
                      style={{
                        background: t.tech_onts === 0 ? "#f1f5f9" : "#ecfdf5",
                        padding: "4px 6px",
                        borderRadius: 6, fontSize: 10,
                        color: t.tech_onts === 0 ? "#64748b" : "#065f46",
                        border: t.tech_onts === 0
                          ? "1px dashed #cbd5e1"
                          : "1px solid #6ee7b7",
                        display: "flex", justifyContent: "space-between",
                        alignItems: "center", fontWeight: 700,
                        cursor: t.tech_onts > 0 ? "pointer" : "default",
                        position: "relative",
                      }}
                    >
                      <span>ONT</span>
                      <strong style={{
                        color: t.tech_onts === 0 ? "#94a3b8" : "#065f46",
                      }}>{t.tech_onts}</strong>
                      {popoverTechId === t.id && (ontsByTech[t.id] || []).length > 0 && (
                        <div
                          onClick={(e) => e.stopPropagation()}
                          data-testid={`tech-row-${t.id}-ont-popover`}
                          style={{
                            position: "absolute",
                            top: "calc(100% + 4px)",
                            left: 0,
                            zIndex: 50,
                            minWidth: 260,
                            maxHeight: 280,
                            overflowY: "auto",
                            background: "white",
                            border: "1px solid #cbd5e1",
                            borderRadius: 10,
                            boxShadow: "0 8px 24px rgba(15,23,42,.15)",
                            padding: 10,
                            textAlign: "left",
                          }}
                        >
                          <div style={{
                            fontSize: 11, fontWeight: 800,
                            textTransform: "uppercase",
                            color: "#475569", marginBottom: 8,
                            display: "flex", justifyContent: "space-between",
                          }}>
                            <span>MACs com {t.name}</span>
                            <span style={{ color: "#10b981" }}>{(ontsByTech[t.id] || []).length}</span>
                          </div>
                          {(ontsByTech[t.id] || []).map((o) => {
                            const fromClient = o.status === "retirada_com_tecnico";
                            const macHist = historyByMac[o.mac] || [];
                            const isOpen = expandedMac === o.mac;
                            return (
                              <div key={o.mac}
                                    style={{
                                      borderBottom: "1px solid #f1f5f9",
                                    }}>
                                <div
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setExpandedMac(isOpen ? null : o.mac);
                                  }}
                                  style={{
                                    padding: "5px 6px",
                                    display: "flex", justifyContent: "space-between",
                                    alignItems: "center", gap: 6, flexWrap: "wrap",
                                    cursor: "pointer",
                                    background: isOpen ? "#f0f9ff" : "transparent",
                                  }}>
                                  <span style={{
                                    fontFamily: "monospace",
                                    fontWeight: 700, fontSize: 11,
                                    color: "#0f172a",
                                  }}>
                                    {isOpen ? "▾" : "▸"} {o.mac}
                                  </span>
                                  <div style={{ display: "flex", gap: 4,
                                                  alignItems: "center",
                                                  marginLeft: "auto" }}>
                                    <span title={fromClient
                                      ? `Veio do cliente${o.client_name ? `: ${o.client_name}` : ""}`
                                      : "Veio do estoque/praça"}
                                            style={{
                                              fontSize: 10, fontWeight: 700,
                                              padding: "2px 6px", borderRadius: 4,
                                              background: fromClient
                                                ? "#fef3c7" : "#dbeafe",
                                              color: fromClient
                                                ? "#92400e" : "#1e40af",
                                            }}>
                                      {fromClient ? "↩️ Cliente" : "Praça"}
                                    </span>
                                    <span style={{
                                      fontSize: 10, color: "#64748b",
                                      background: "#f1f5f9",
                                      padding: "2px 6px", borderRadius: 4,
                                    }}>{o.model || "ONT"}</span>
                                  </div>
                                </div>
                                {isOpen && (
                                  <div data-testid={`mac-timeline-${o.mac}`}
                                        style={{
                                          background: "#f8fafc",
                                          padding: "8px 10px 8px 22px",
                                          borderLeft: "2px solid #3b82f6",
                                          marginLeft: 8, marginBottom: 4,
                                          borderRadius: 4,
                                        }}>
                                    <div style={{ fontSize: 9, fontWeight: 800,
                                                    textTransform: "uppercase",
                                                    color: "#64748b",
                                                    marginBottom: 4 }}>
                                      Histórico ({macHist.length})
                                    </div>
                                    {macHist.length === 0 && (
                                      <div style={{ fontSize: 10,
                                                      color: "#94a3b8",
                                                      fontStyle: "italic" }}>
                                        Sem histórico registrado
                                      </div>
                                    )}
                                    {macHist.slice(0, 8).map((h, i) => {
                                      const dt = (h.created_at || h.date || "");
                                      const dStr = dt
                                        ? new Date(dt).toLocaleString("pt-BR",
                                          { day: "2-digit", month: "2-digit",
                                              hour: "2-digit", minute: "2-digit" })
                                        : "—";
                                      const icon = {
                                        compra: "",
                                        transferencia: "",
                                        instalacao: "",
                                        retirada: "↩️",
                                        movimentacao: "↪",
                                      }[h.type] || "•";
                                      return (
                                        <div key={i} style={{
                                          fontSize: 10, color: "#475569",
                                          marginBottom: 3, lineHeight: 1.3,
                                        }}>
                                          <strong style={{ color: "#0f172a" }}>{icon} {dStr}</strong>
                                          {" — "}{(h.description || "").slice(0, 90)}
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </button>
                    {consumables.map((c) => {
                      const qty = t.stock?.[c.id] || 0;
                      // Insumos de rede (fibras 06/12/24FO) só aparecem em
                      // técnicos que efetivamente têm saldo (técnicos de rede).
                      // Mantém o card limpo para técnicos comuns.
                      if (c.category === "rede" && qty === 0) return null;
                      const lc = qty === 0 ? "#94a3b8"
                              : qty < 3 ? "#d97706" : "#16a34a";
                      return (
                        <div key={c.id} style={{
                          background: "#f8fafc", padding: "4px 6px",
                          borderRadius: 6, fontSize: 10, color: "#64748b",
                          display: "flex", justifyContent: "space-between",
                          alignItems: "center",
                        }} title={c.name}>
                          <span style={{ overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap",
                                          maxWidth: 60 }}>{c.name}</span>
                          <strong style={{ color: lc,
                                              fontVariantNumeric: "tabular-nums" }}>
                            {qty}
                          </strong>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

// --- helpers visuais do Dashboard ---
function AlertCard({ tone, icon, title, detail }) {
  const tones = {
    bad: { bg: "#fef2f2", border: "#fca5a5", color: "#991b1b" },
    warn: { bg: "#fffbeb", border: "#fcd34d", color: "#92400e" },
    info: { bg: "#eff6ff", border: "#93c5fd", color: "#1e3a8a" },
  };
  const t = tones[tone] || tones.info;
  return (
    <div style={{
      padding: 12, borderRadius: 10, background: t.bg,
      border: `1px solid ${t.border}`, color: t.color,
      display: "flex", gap: 10, alignItems: "flex-start",
    }}>
      <div style={{ fontSize: 18, lineHeight: 1 }}>{icon}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 800 }}>{title}</div>
        <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2,
                        lineHeight: 1.4 }}>{detail}</div>
      </div>
    </div>
  );
}

function KpiCard({ testId, label, value, unit, tone = "info", delta,
                     sparkline, sparkColor, progress, hint }) {
  const tones = {
    good: { bar: "#10b981", text: "#0f172a", chip: "#dcfce7", chipC: "#15803d" },
    warn: { bar: "#d97706", text: "#0f172a", chip: "#fef3c7", chipC: "#a16207" },
    bad:  { bar: "#dc2626", text: "#0f172a", chip: "#fee2e2", chipC: "#b91c1c" },
    info: { bar: "#0ea5e9", text: "#0f172a", chip: "#dbeafe", chipC: "#1e40af" },
  };
  const t = tones[tone] || tones.info;
  return (
    <div data-testid={testId} style={{
      background: "#fff", borderRadius: 14, padding: 14,
      border: "1px solid #e2e8f0",
      boxShadow: "0 1px 2px rgba(15,23,42,.04)",
      borderTop: `3px solid ${t.bar}`,
      display: "flex", flexDirection: "column", gap: 6,
      minHeight: 110,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", gap: 8 }}>
        <div style={{ fontSize: 10.5, fontWeight: 800, color: "#64748b",
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
          {label}
        </div>
        {delta != null && (
          <span style={{
            background: delta >= 0 ? "#dcfce7" : "#fee2e2",
            color: delta >= 0 ? "#15803d" : "#b91c1c",
            fontSize: 10.5, fontWeight: 800,
            padding: "2px 6px", borderRadius: 999,
            fontVariantNumeric: "tabular-nums",
          }}>
            {delta >= 0 ? "↑" : "↓"} {Math.abs(delta)}%
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "baseline",
                      gap: 4, marginTop: 2 }}>
        <span style={{ fontSize: 28, fontWeight: 800, color: t.text,
                          fontVariantNumeric: "tabular-nums",
                          lineHeight: 1 }}>{value}</span>
        {unit && <span style={{ fontSize: 12, color: "#94a3b8",
                                    fontWeight: 600 }}>{unit}</span>}
      </div>
      {sparkline && (
        <Sparkline values={sparkline} color={sparkColor || t.bar} />
      )}
      {progress != null && (
        <div style={{ height: 6, background: "#f1f5f9", borderRadius: 999,
                          overflow: "hidden", marginTop: 4 }}>
          <div style={{ width: `${Math.min(100, progress)}%`,
                          height: "100%", background: t.bar,
                          transition: "width .35s ease" }} />
        </div>
      )}
      {hint && (
        <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: "auto",
                          lineHeight: 1.3 }}>{hint}</div>
      )}
    </div>
  );
}

function Sparkline({ values = [], color = "#0ea5e9", height = 30 }) {
  if (!values || !values.length) return null;
  if (!values.some((v) => v > 0)) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(1, max - min);
  const w = 100, h = height;
  const step = w / Math.max(1, values.length - 1);
  const points = values.map((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
         style={{ width: "100%", height, marginTop: 4 }}>
      <polyline points={points} fill="none" stroke={color}
                strokeWidth="1.6" strokeLinejoin="round"
                strokeLinecap="round" />
      <polyline
        points={`0,${h} ${points} ${w},${h}`}
        fill={color} fillOpacity="0.08" stroke="none" />
    </svg>
  );
}

function MovementChart({ install = [], all = [] }) {
  const maxV = Math.max(...install, ...all, 1);
  const w = 100, h = 100;
  const step = w / Math.max(1, install.length - 1);
  const lineFor = (arr) => arr.map((v, i) =>
    `${i * step},${h - (v / maxV) * (h - 6) - 3}`).join(" ");
  return (
    <div style={{ width: "100%" }}>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
           style={{ width: "100%", height: 130 }}>
        {/* grid */}
        {[0.25, 0.5, 0.75].map((p) => (
          <line key={p} x1={0} y1={h * p} x2={w} y2={h * p}
                stroke="#e2e8f0" strokeWidth="0.3"
                strokeDasharray="1 1.5" />
        ))}
        {/* all (background area) */}
        <polyline
          points={`0,${h} ${lineFor(all)} ${w},${h}`}
          fill="#0ea5e9" fillOpacity="0.08" stroke="none" />
        <polyline points={lineFor(all)} fill="none" stroke="#0ea5e9"
                  strokeWidth="0.7" strokeLinejoin="round" />
        {/* installs (foreground bold) */}
        <polyline points={lineFor(install)} fill="none" stroke="#10b981"
                  strokeWidth="1.4" strokeLinejoin="round"
                  strokeLinecap="round" />
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between",
                       fontSize: 9.5, color: "#94a3b8", marginTop: 2 }}>
        <span>14d atrás</span><span>hoje</span>
      </div>
    </div>
  );
}

function Legend({ color, label, value }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: 3,
                        background: color, display: "inline-block" }} />
      <span style={{ fontWeight: 700, color: "#0f172a" }}>{value}</span>
      <span style={{ opacity: 0.7 }}>{label}</span>
    </div>
  );
}

function LocationBars({ items, total }) {
  if (total === 0) {
    return (
      <div style={{ padding: 16, textAlign: "center",
                       fontSize: 12, color: "#64748b" }}>
        Nenhuma ONT cadastrada.
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", height: 14, borderRadius: 6,
                       overflow: "hidden",
                       border: "1px solid #f1f5f9" }}
           data-testid="location-stacked-bar">
        {items.map((i) => (
          <div key={i.key} style={{
            width: `${total > 0 ? (i.count / total) * 100 : 0}%`,
            background: i.color,
            transition: "width .35s ease",
          }} title={`${i.label}: ${i.count}`} />
        ))}
      </div>
      {items.map((i) => {
        const pct = total > 0 ? Math.round((i.count / total) * 100) : 0;
        return (
          <div key={i.key} data-testid={`loc-row-${i.key}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto",
                  alignItems: "center", gap: 8,
                }}>
            <span style={{ width: 10, height: 10, borderRadius: 3,
                              background: i.color }} />
            <span style={{ fontSize: 12, color: "#0f172a" }}>
              {i.label}
            </span>
            <span style={{ fontSize: 12, fontWeight: 800, color: "#0f172a",
                              fontVariantNumeric: "tabular-nums" }}>
              {i.count}
              <span style={{ opacity: 0.5, marginLeft: 4,
                                fontWeight: 500 }}>· {pct}%</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ============================================================
// ONTs
// ============================================================
function OntsSection({ onts, technicians, reload }) {
  const [filter, setFilter] = useState("");
  const [locFilter, setLocFilter] = useState("all");
  const [showAdd, setShowAdd] = useState(false);
  // Modo seleção pra transferência em lote
  const [transferMode, setTransferMode] = useState(false);
  const [selectedMacs, setSelectedMacs] = useState({});
  const [bulkTechId, setBulkTechId] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  // iter201 — Rastreabilidade ponta a ponta (SN → NF de origem)
  const [traceIdent, setTraceIdent] = useState(null);

  const filtered = useMemo(() => {
    const q = filter.toLowerCase();
    return onts.filter((o) => {
      // iter197 — busca por SN primeiro (campo prevalente), depois MAC/modelo/cliente
      // iter247 fix: ONT zumbi vinda de `lousa_retirada_troca_photo` pode
      // ter mac=null (stub aguardando revisão humana). Sem o `|| ""` o
      // useMemo quebra e derruba toda a tela do Estoque.
      const sn = (o.scan_sn || o.sn || "").toLowerCase();
      const txt = !q || sn.includes(q) || (o.mac || "").toLowerCase().includes(q)
        || (o.model || "").toLowerCase().includes(q)
        || (o.client_name || "").toLowerCase().includes(q);
      const loc = locFilter === "all" || o.location_type === locFilter;
      return txt && loc;
    });
  }, [onts, filter, locFilter]);

  const techMap = useMemo(() => Object.fromEntries(technicians.map((t) => [t.id, t.name])), [technicians]);

  const selectableMacs = useMemo(
    () => filtered.filter((o) => o.location_type === "empresa").map((o) => o.mac),
    [filtered],
  );
  const selectedCount = Object.values(selectedMacs).filter(Boolean).length;
  const allSelected = selectableMacs.length > 0
    && selectableMacs.every((m) => selectedMacs[m]);

  const toggleMac = (mac) =>
    setSelectedMacs((s) => ({ ...s, [mac]: !s[mac] }));
  const toggleAll = () => {
    if (allSelected) setSelectedMacs({});
    else {
      const next = {};
      selectableMacs.forEach((m) => { next[m] = true; });
      setSelectedMacs(next);
    }
  };

  const startTransferMode = () => {
    setTransferMode(true);
    setSelectedMacs({});
    setBulkTechId(technicians[0]?.id || "");
  };
  const cancelTransferMode = () => {
    setTransferMode(false);
    setSelectedMacs({});
  };

  const confirmBulkTransfer = async () => {
    const macs = Object.entries(selectedMacs).filter(([, v]) => v).map(([m]) => m);
    if (!macs.length) {
      await window.alert("Selecione pelo menos uma ONT.");
      return;
    }
    if (!bulkTechId) {
      await window.alert("Selecione o técnico de destino.");
      return;
    }
    const techName = techMap[bulkTechId] || "técnico";
    if (!await window.confirm(
      `Transferir ${macs.length} ONT(s) para ${techName}?`)) return;
    setBulkBusy(true);
    try {
      const results = await Promise.allSettled(
        macs.map((mac) => api.stokOntTransfer(mac, bulkTechId)),
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const fail = results.length - ok;
      await window.alert(
        `✓ ${ok} ONT(s) transferida(s)` + (fail ? ` · ${fail} falha(s)` : ""));
      cancelTransferMode();
      await reload();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBulkBusy(false);
    }
  };

  const editModel = asyncCall(async (mac, current) => {
    const novo = await window.prompt("Novo modelo:", current);
    if (!novo || novo === current) return;
    await api.stokOntEdit(mac, novo);
  }, reload, "Erro ao editar");

  const returnToCompany = asyncCall(async (mac) => {
    if (!await window.confirm(`Devolver ONT ${mac} para a empresa?`)) return;
    await api.stokOntReturn(mac);
  }, reload, "Erro ao devolver");

  return (
    <Card
      title={`ONTs (${onts.length})`}
      action={
        <div style={{ display: "flex", gap: 8 }}>
          {!transferMode ? (
            <>
              <button data-testid="ont-add-btn" style={btnPrimary} onClick={() => setShowAdd(true)}>+ Adicionar ONTs</button>
              <button data-testid="ont-transfer-btn" style={btnSec} onClick={startTransferMode}>↗ Transferir</button>
            </>
          ) : (
            <>
              <span data-testid="ont-bulk-counter" style={{
                padding: "8px 14px", borderRadius: 10, background: "#dbeafe",
                color: "#1e40af", fontWeight: 800, fontSize: 13,
              }}>
                {selectedCount} selecionada(s)
              </span>
              <button data-testid="ont-bulk-cancel" style={btnSec}
                       onClick={cancelTransferMode} disabled={bulkBusy}>
                ✕ Cancelar
              </button>
            </>
          )}
        </div>
      }
    >
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input
          data-testid="ont-filter-input"
          style={{ ...inputStyle, flex: 1, minWidth: 220 }}
          placeholder="Buscar SN, MAC, modelo ou cliente…"
          value={filter} onChange={(e) => setFilter(e.target.value)}
        />
        <select data-testid="ont-loc-filter" style={{ ...inputStyle, width: 200 }} value={locFilter} onChange={(e) => setLocFilter(e.target.value)}>
          <option value="all">Todas as localizações</option>
          <option value="empresa">Estoque empresa</option>
          <option value="tecnico">Com técnico</option>
          <option value="cliente">Instaladas</option>
        </select>
      </div>

      {transferMode && (
        <div data-testid="ont-bulk-banner" style={{
          marginBottom: 12, padding: "10px 14px", borderRadius: 10,
          background: "#eff6ff", border: "1px solid #bfdbfe",
          color: "#1e40af", fontSize: 12, fontWeight: 600,
          display: "flex", justifyContent: "space-between", alignItems: "center",
          gap: 10, flexWrap: "wrap",
        }}>
          <span>
            ↗ Marque as ONTs disponíveis pra transferir.{" "}
            {selectableMacs.length > 0 && (
              <button onClick={toggleAll}
                       data-testid="ont-bulk-toggle-all"
                       style={{
                         marginLeft: 8, padding: "2px 8px", borderRadius: 6,
                         background: "white", border: "1px solid #93c5fd",
                         color: "#1e40af", fontWeight: 700, fontSize: 11,
                         cursor: "pointer",
                       }}>
                {allSelected ? "Desmarcar tudo" : "Marcar todas as disponíveis"}
              </button>
            )}
          </span>
        </div>
      )}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              {transferMode && <th style={{ padding: 10, width: 36 }}></th>}
              <th style={{ padding: 10 }}>SN <span style={{ fontSize: 9, fontWeight: 500, color: "#64748b" }}>· MAC</span></th>
              <th style={{ padding: 10 }}>Modelo</th>
              <th style={{ padding: 10 }}>Local</th>
              <th style={{ padding: 10 }}>Status</th>
              <th style={{ padding: 10, textAlign: "right" }}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={transferMode ? 6 : 5} style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Nenhuma ONT encontrada.</td></tr>
            ) : filtered.map((o) => {
              const isSelectable = o.location_type === "empresa";
              const isChecked = !!selectedMacs[o.mac];
              const localLabel = o.location_type === "empresa" ? "Empresa"
                : o.location_type === "tecnico" ? (techMap[o.location_id] || "Técnico desconhecido")
                : o.location_type === "cliente" ? `Cliente: ${o.client_name || o.location_id}`
                : o.location_type;
              return (
                <tr key={o.mac}
                     style={{ borderTop: "1px solid #e2e8f0",
                                background: transferMode && isChecked ? "#eff6ff" : undefined,
                                cursor: transferMode && isSelectable ? "pointer" : undefined }}
                     onClick={transferMode && isSelectable ? () => toggleMac(o.mac) : undefined}
                     data-testid={`ont-row-${o.mac}`}>
                  {transferMode && (
                    <td style={{ padding: 10, textAlign: "center" }}>
                      {isSelectable ? (
                        <input type="checkbox"
                                checked={isChecked}
                                onChange={() => toggleMac(o.mac)}
                                onClick={(e) => e.stopPropagation()}
                                data-testid={`ont-checkbox-${o.mac}`}
                                style={{ width: 18, height: 18, cursor: "pointer" }} />
                      ) : (
                        <span style={{ color: "#cbd5e1", fontSize: 14 }}>—</span>
                      )}
                    </td>
                  )}
                  {/* iter197 — SN prevalente (MAC pequeno em segunda linha) */}
                  <td style={{ padding: 10 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div data-testid={`ont-sn-${o.mac}`}
                            style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 800, color: "#0f172a" }}>
                        {o.scan_sn || o.sn || (
                          /^(SN-|AUTOSN_|MANUAL-)/i.test(o.mac || "")
                            ? <span style={{ color: "#dc2626" }}>— sem SN —</span>
                            : <span style={{ color: "#94a3b8", fontStyle: "italic" }}>SN não informado</span>
                        )}
                      </div>
                      <button
                        type="button"
                        title="Rastreabilidade: ver de qual nota fiscal esta ONT veio"
                        data-testid={`trace-btn-${o.mac}`}
                        onClick={() => setTraceIdent(o.scan_sn || o.mac)}
                        style={{ background: "none", border: 0, cursor: "pointer",
                                  padding: 2, fontSize: 14, opacity: 0.6 }}>
                        
                      </button>
                    </div>
                    {!/^(SN-|AUTOSN_|MANUAL-)/i.test(o.mac || "") && o.mac && (
                      <div style={{ fontFamily: "monospace", fontSize: 10,
                                      color: "#64748b", marginTop: 1 }}>
                        MAC: {o.mac}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: 10 }}>{o.model}</td>
                  <td style={{ padding: 10 }}>{localLabel}</td>
                  <td style={{ padding: 10 }}><StatusPill status={o.status} /></td>
                  <td style={{ padding: 10, textAlign: "right" }}>
                    {!transferMode && o.location_type === "empresa" && (
                      <button style={btnGhost} onClick={() => editModel(o.mac, o.model)} data-testid={`ont-edit-${o.mac}`}>✏️ Editar</button>
                    )}
                    {!transferMode && o.location_type === "tecnico" && (
                      <button style={btnGhost} onClick={() => returnToCompany(o.mac)} data-testid={`ont-return-${o.mac}`}>↩ Devolver</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {transferMode && (
        <div data-testid="ont-bulk-actionbar" style={{
          position: "sticky", bottom: 0, marginTop: 12,
          padding: 14, background: "white",
          border: "1px solid #cbd5e1", borderRadius: 12,
          boxShadow: "0 -4px 14px rgba(0,0,0,0.06)",
          display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
        }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label style={{ fontSize: 11, color: "#64748b", fontWeight: 700,
                              textTransform: "uppercase", letterSpacing: 0.4 }}>
              Transferir para o técnico:
            </label>
            <select data-testid="ont-bulk-tech-select"
                      value={bulkTechId}
                      onChange={(e) => setBulkTechId(e.target.value)}
                      style={{ ...inputStyle, marginTop: 4 }}>
              <option value="">— Selecione um técnico —</option>
              {technicians.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
          <button data-testid="ont-bulk-confirm" style={{
            ...btnPrimary, padding: "14px 22px", fontSize: 14,
            opacity: (bulkBusy || selectedCount === 0) ? 0.5 : 1,
          }} disabled={bulkBusy || selectedCount === 0}
              onClick={confirmBulkTransfer}>
            {bulkBusy ? "Transferindo…" : `↗ Transferir ${selectedCount} ONT(s)`}
          </button>
        </div>
      )}

      <AddOntsDialog open={showAdd} onClose={() => setShowAdd(false)} onDone={reload} technicians={technicians} />

      {/* iter201 — Modal de Rastreabilidade (SN → NF de origem + histórico) */}
      {traceIdent && (
        <OntTraceabilityModal ident={traceIdent}
                                onClose={() => setTraceIdent(null)} />
      )}
    </Card>
  );
}

function AddOntsDialog({ open, onClose, onDone, technicians = [] }) {
  const [model, setModel] = useState("");
  const [snsText, setSnsText] = useState("");
  // iter215bc — destino do cadastro: empresa OR técnico específico
  const [destination, setDestination] = useState(""); // "" = empresa
  const submit = asyncCall(async () => {
    const list = snsText.split(/[\s,;\n]+/).map((s) => s.trim()).filter(Boolean);
    if (!model.trim()) return await window.alert("Informe o modelo.");
    if (list.length === 0) return await window.alert("Informe pelo menos 1 SN.");
    // iter215bc — passa technician_id se destino for um técnico
    const techId = destination || undefined;
    const result = await api.stokOntsBulk(
      model.trim(),
      list.map((sn) => ({ sn: sn.toUpperCase() })),
      techId,
    );
    // Mensagem de sucesso EXPLÍCITA com destino (corrige confusão antiga
    // do bug "cadastrei mas não aparece no estoque do técnico")
    await window.alert(
      `✓ ${result.inserted} ONT(s) cadastrada(s)\n\n`
      + `Destino: ${result.destination_name || "Estoque da empresa"}\n\n`
      + (techId
          ? `As ONTs JÁ ESTÃO no estoque do técnico. `
            + `Ele pode usá-las direto na próxima OS.`
          : `As ONTs estão no estoque da EMPRESA. `
            + `Para enviar a um técnico, use "↗ Transferir".`)
    );
    setModel(""); setSnsText(""); setDestination("");
    onClose();
  }, onDone, "Erro ao cadastrar ONTs");
  return (
    <Modal open={open} onClose={onClose} title="Adicionar ONTs" data-testid="ont-add-dialog"
      footer={<>
        <button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="ont-add-submit">Cadastrar</button>
      </>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Modelo</label>
        <input data-testid="ont-add-model" style={inputStyle} value={model} onChange={(e) => setModel(e.target.value)} placeholder="ZTE F670L, Huawei HG8245H, etc." />
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Destino do cadastro</label>
        <select data-testid="ont-add-destination" style={inputStyle}
          value={destination}
          onChange={(e) => setDestination(e.target.value)}>
          <option value="">Estoque da empresa (precisa transferir depois)</option>
          {technicians.map((t) => (
            <option key={t.id} value={t.id}>
              Direto no estoque de: {t.name}
            </option>
          ))}
        </select>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
          Escolha um técnico para que as ONTs entrem direto no estoque dele,
          sem precisar de transferência manual.
        </div>
      </div>
      <div>
        <label style={labelStyle}>SN — Número de Série (1 por linha)</label>
        <textarea data-testid="ont-add-macs" style={{ ...inputStyle, height: 140, fontFamily: "monospace" }} value={snsText} onChange={(e) => setSnsText(e.target.value)} placeholder="HUAW48F1AB2C3D&#10;ZTEG48F1ABCD01" />
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
          ️ A base é obrigatória pelo SN (impresso na etiqueta). O MAC
          é preenchido automaticamente quando o SmartOLT aprovisionar.
        </div>
      </div>
    </Modal>
  );
}

function TransferOntDialog({ open, onClose, onDone, technicians }) {
  const [mac, setMac] = useState("");
  const [techId, setTechId] = useState("");
  const submit = asyncCall(async () => {
    if (!mac.trim() || !techId) return await window.alert("MAC e técnico são obrigatórios.");
    await api.stokOntTransfer(mac.trim(), techId);
    setMac(""); setTechId(""); onClose();
  }, onDone, "Erro ao transferir");
  return (
    <Modal open={open} onClose={onClose} title="↗ Transferir ONT para técnico" data-testid="ont-transfer-dialog"
      footer={<>
        <button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="ont-transfer-submit">Transferir</button>
      </>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>MAC da ONT</label>
        <input data-testid="ont-transfer-mac" style={inputStyle} value={mac} onChange={(e) => setMac(e.target.value)} placeholder="AA:BB:CC:DD:EE:FF" />
      </div>
      <div>
        <label style={labelStyle}>Técnico de destino</label>
        <select data-testid="ont-transfer-tech" style={inputStyle} value={techId} onChange={(e) => setTechId(e.target.value)}>
          <option value="">Selecione…</option>
          {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
    </Modal>
  );
}

// ============================================================
// Insumos
// ============================================================
function InsumosSection({ consumables, technicians, stock, reload }) {
  const [showPurchase, setShowPurchase] = useState(false);
  const [showQuickPurchase, setShowQuickPurchase] = useState(false);
  const [transferMode, setTransferMode] = useState(false);
  const [bulkTechId, setBulkTechId] = useState("");
  const [bulkQty, setBulkQty] = useState({}); // {consumable_id: qty}
  const [bulkBusy, setBulkBusy] = useState(false);

  const startTransferMode = () => {
    setTransferMode(true);
    setBulkQty({});
    setBulkTechId(technicians[0]?.id || "");
  };
  const cancelTransferMode = () => {
    setTransferMode(false);
    setBulkQty({});
  };
  const setQty = (cid, v) =>
    setBulkQty((s) => ({ ...s, [cid]: v }));

  const itemsToTransfer = Object.entries(bulkQty)
    .filter(([, q]) => parseInt(q, 10) > 0)
    .map(([cid, q]) => ({ cid, qty: parseInt(q, 10) }));
  const totalItems = itemsToTransfer.reduce((s, it) => s + it.qty, 0);

  const confirmBulkTransfer = async () => {
    if (itemsToTransfer.length === 0) {
      await window.alert("Informe ao menos 1 item.");
      return;
    }
    if (!bulkTechId) {
      await window.alert("Selecione o técnico.");
      return;
    }
    // Valida estoque empresa
    const tooMuch = itemsToTransfer.find(
      (it) => it.qty > (stock.empresa?.[it.cid] || 0),
    );
    if (tooMuch) {
      const cName = consumables.find((c) => c.id === tooMuch.cid)?.name || tooMuch.cid;
      await window.alert(`Estoque insuficiente de ${cName} (${stock.empresa?.[tooMuch.cid] || 0} disp.)`);
      return;
    }
    const techName = technicians.find((t) => t.id === bulkTechId)?.name || "técnico";
    if (!await window.confirm(
      `Transferir ${itemsToTransfer.length} insumos (${totalItems} unidades) para ${techName}?`,
    )) return;
    setBulkBusy(true);
    try {
      const results = await Promise.allSettled(
        itemsToTransfer.map((it) =>
          api.stokConsumableTransfer(it.cid, it.qty, bulkTechId),
        ),
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const fail = results.length - ok;
      await window.alert(
        `✓ ${ok} insumo(s) transferido(s)` + (fail ? ` · ${fail} falha(s)` : ""));
      cancelTransferMode();
      await reload();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <Card
      title="Insumos (consumíveis)"
      action={
        <div style={{ display: "flex", gap: 8 }}>
          {!transferMode ? (
            <>
              <button data-testid="cons-quick-purchase-btn"
                       style={{ ...btnPrimary,
                                  background: "linear-gradient(135deg,#16a34a,#15803d)",
                                  marginRight: 6 }}
                       title="1 clique compra a embalagem padrão de qualquer insumo"
                       onClick={() => setShowQuickPurchase(true)}>Compra Rápida</button>
              <button data-testid="cons-purchase-btn" style={btnPrimary}
                       onClick={() => setShowPurchase(true)}>+ Compra</button>
              <button data-testid="cons-transfer-btn" style={btnSec}
                       onClick={startTransferMode}>↗ Transferir</button>
            </>
          ) : (
            <>
              <span data-testid="cons-bulk-counter" style={{
                padding: "8px 14px", borderRadius: 10, background: "#dbeafe",
                color: "#1e40af", fontWeight: 800, fontSize: 13,
              }}>
                {itemsToTransfer.length} itens · {totalItems} unid.
              </span>
              <button data-testid="cons-bulk-cancel" style={btnSec}
                       onClick={cancelTransferMode} disabled={bulkBusy}>
                ✕ Cancelar
              </button>
            </>
          )}
        </div>
      }
    >
      {transferMode && (
        <div data-testid="cons-bulk-banner" style={{
          marginBottom: 12, padding: "10px 14px", borderRadius: 10,
          background: "#eff6ff", border: "1px solid #bfdbfe",
          color: "#1e40af", fontSize: 12, fontWeight: 600,
        }}>
          ↗ Informe a quantidade na linha <strong>Empresa</strong>{" "}
          para cada insumo a transferir.
        </div>
      )}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Local</th>
              {consumables.map((c) => <th key={c.id} style={{ padding: 10, textAlign: "right" }}>{c.name} ({c.unit})</th>)}
            </tr>
          </thead>
          <tbody>
            <tr style={{ borderTop: "1px solid #e2e8f0", background: "#f1f5f9" }}>
              <td style={{ padding: 10, fontWeight: 800 }}>Empresa</td>
              {consumables.map((c) => {
                const avail = stock.empresa?.[c.id] || 0;
                return (
                  <td key={c.id} style={{ padding: 10, textAlign: "right",
                                              fontFamily: "monospace" }}>
                    {transferMode ? (
                      <div style={{ display: "flex", alignItems: "center",
                                       justifyContent: "flex-end", gap: 6 }}>
                        <span style={{ fontSize: 10, color: "#64748b" }}>
                          disp {avail}
                        </span>
                        <input
                          type="number" min="0" max={avail}
                          data-testid={`cons-bulk-qty-${c.id}`}
                          value={bulkQty[c.id] || ""}
                          onChange={(e) => setQty(c.id, e.target.value)}
                          style={{
                            width: 70, padding: "6px 8px",
                            borderRadius: 6, border: "1px solid #cbd5e1",
                            fontFamily: "monospace", fontSize: 13,
                            textAlign: "right",
                            background: bulkQty[c.id] > 0 ? "#dbeafe" : "white",
                          }}
                          placeholder="0"
                        />
                      </div>
                    ) : (
                      <span style={{ fontWeight: 700 }}>{avail}</span>
                    )}
                  </td>
                );
              })}
            </tr>
            {technicians.map((t) => (
              <tr key={t.id} style={{ borderTop: "1px solid #e2e8f0",
                                          background: transferMode && t.id === bulkTechId ? "#ecfdf5" : undefined }}>
                <td style={{ padding: 10 }}>
                  {transferMode && t.id === bulkTechId && <span></span>}
                  {t.name}
                </td>
                {consumables.map((c) => {
                  const v = stock[t.id]?.[c.id] || 0;
                  const isNeg = v < 0;
                  return (
                    <td key={c.id}
                          data-testid={`cons-cell-${t.id}-${c.id}`}
                          style={{ padding: 10, textAlign: "right",
                                       fontFamily: "monospace",
                                       fontWeight: isNeg ? 800 : 400,
                                       color: isNeg ? "#dc2626" : undefined,
                                       background: isNeg ? "#fef2f2" : undefined }}
                          title={isNeg ? `Quebra: ${Math.abs(v)} ${c.unit} consumidos além do saldo` : undefined}>
                      {v}
                      {isNeg && <span style={{ fontSize: 9, marginLeft: 2 }}></span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {transferMode && (
        <div data-testid="cons-bulk-actionbar" style={{
          position: "sticky", bottom: 0, marginTop: 12,
          padding: 14, background: "white",
          border: "1px solid #cbd5e1", borderRadius: 12,
          boxShadow: "0 -4px 14px rgba(0,0,0,0.06)",
          display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
        }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label style={{ fontSize: 11, color: "#64748b", fontWeight: 700,
                              textTransform: "uppercase", letterSpacing: 0.4 }}>
              Transferir para o técnico:
            </label>
            <select data-testid="cons-bulk-tech-select"
                      value={bulkTechId}
                      onChange={(e) => setBulkTechId(e.target.value)}
                      style={{ ...inputStyle, marginTop: 4 }}>
              <option value="">— Selecione um técnico —</option>
              {technicians.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
          <button data-testid="cons-bulk-confirm" style={{
            ...btnPrimary, padding: "14px 22px", fontSize: 14,
            opacity: (bulkBusy || itemsToTransfer.length === 0) ? 0.5 : 1,
          }} disabled={bulkBusy || itemsToTransfer.length === 0}
              onClick={confirmBulkTransfer}>
            {bulkBusy ? "Transferindo…" : `↗ Transferir ${totalItems} unid.`}
          </button>
        </div>
      )}

      <ConsumablePurchaseDialog open={showPurchase} onClose={() => setShowPurchase(false)} onDone={reload} consumables={consumables} technicians={technicians} />
      <QuickPurchaseDialog open={showQuickPurchase}
                              onClose={() => setShowQuickPurchase(false)}
                              onDone={reload} consumables={consumables} />
    </Card>
  );
}

function QuickPurchaseDialog({ open, onClose, onDone, consumables }) {
  const [busy, setBusy] = useState(false);
  const [pendingId, setPendingId] = useState(null);
  const [msg, setMsg] = useState(null);

  const buy = async (item, packs) => {
    if (busy) return;
    setBusy(true); setPendingId(item.id); setMsg(null);
    try {
      await api.stokConsumablePurchase(item.id, packs);
      const total = packs * item.pack_qty;
      setMsg({ type: "ok", text: `+${packs} ${item.pack_label}(s) = ${total} ${item.unit} de ${item.name}` });
      onDone?.();
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); setPendingId(null); }
  };

  return (
    <Modal open={open} onClose={onClose}
           title="Compra Rápida — 1 clique"
           data-testid="quick-purchase-dialog"
           footer={<button style={btnSec} onClick={onClose}>Fechar</button>}>
      <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
        Cada botão registra a compra da embalagem padrão direto no estoque <strong>Empresa</strong>.
        Use quando o saldo dos técnicos está zerado/negativo e você precisa repor rápido.
      </div>
      {msg && (
        <div style={{
          padding: "8px 12px", borderRadius: 8, marginBottom: 12,
          fontSize: 12, fontWeight: 600,
          background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
          color: msg.type === "ok" ? "#166534" : "#991b1b",
          border: `1px solid ${msg.type === "ok" ? "#86efac" : "#fca5a5"}`,
        }}>{msg.text}</div>
      )}
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                       gap: 10 }}>
        {consumables.map((c) => (
          <div key={c.id} data-testid={`quick-row-${c.id}`}
                style={{
                  border: "1px solid #e2e8f0", borderRadius: 10, padding: 12,
                  background: pendingId === c.id ? "#dbeafe" : "#f8fafc",
                }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
              {c.name}
            </div>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>
              {c.pack_label} = {c.pack_qty} {c.unit}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {[1, 2, 5].map((n) => (
                <button key={n} type="button" disabled={busy}
                        data-testid={`quick-buy-${c.id}-${n}`}
                        onClick={() => buy(c, n)}
                        style={{
                          flex: 1, minWidth: 56, padding: "8px 6px",
                          borderRadius: 8, border: 0,
                          background: busy && pendingId === c.id
                            ? "#94a3b8"
                            : "linear-gradient(135deg,#16a34a,#15803d)",
                          color: "#fff", fontSize: 12, fontWeight: 700,
                          cursor: busy ? "wait" : "pointer",
                        }}>
                  +{n} {n === 1 ? c.pack_label : c.pack_label + "s"}
                  <div style={{ fontSize: 9, fontWeight: 500, opacity: 0.85 }}>
                    {n * c.pack_qty} {c.unit}
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}


function ConsumablePurchaseDialog({ open, onClose, onDone, consumables, technicians = [] }) {
  const [cid, setCid] = useState("");
  const [qty, setQty] = useState(1);
  // iter215bd — destino opcional: empresa (default) ou técnico direto
  const [destination, setDestination] = useState("");
  const item = consumables.find((c) => c.id === cid);
  const total = item ? qty * item.pack_qty : 0;
  const submit = asyncCall(async () => {
    if (!cid || qty <= 0) return await window.alert("Selecione insumo e informe quantidade.");
    const result = await api.stokConsumablePurchase(
      cid, parseInt(qty, 10), destination || undefined);
    await window.alert(
      `✓ ${result.added} ${item?.unit || "un"} adicionado(s)\n\n`
      + `Destino: ${result.destination_name || "Estoque da empresa"}\n\n`
      + (destination
          ? `O insumo JÁ ESTÁ no estoque do técnico. `
            + `Ele pode usar direto na próxima OS.`
          : `O insumo está no estoque da EMPRESA. `
            + `Para enviar a um técnico, use "↗ Transferir".`)
    );
    setCid(""); setQty(1); setDestination(""); onClose();
  }, onDone, "Erro na compra");
  return (
    <Modal open={open} onClose={onClose} title="Registrar compra" data-testid="cons-purchase-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="cons-purchase-submit">Registrar</button></>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Insumo</label>
        <select data-testid="cons-purchase-id" style={inputStyle} value={cid} onChange={(e) => setCid(e.target.value)}>
          <option value="">Selecione…</option>
          {consumables.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.pack_label} = {c.pack_qty} {c.unit})</option>)}
        </select>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Destino do cadastro</label>
        <select data-testid="cons-purchase-destination" style={inputStyle}
          value={destination}
          onChange={(e) => setDestination(e.target.value)}>
          <option value="">Estoque da empresa (precisa transferir depois)</option>
          {technicians.map((t) => (
            <option key={t.id} value={t.id}>
              Direto no estoque de: {t.name}
            </option>
          ))}
        </select>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
          Escolha um técnico para que o insumo entre direto no estoque dele.
        </div>
      </div>
      <div>
        <label style={labelStyle}>Quantidade ({item?.pack_label || "pacotes"})</label>
        <input data-testid="cons-purchase-qty" type="number" min="1" style={inputStyle} value={qty} onChange={(e) => setQty(e.target.value)} />
      </div>
      {item && total > 0 && (
        <div style={{ marginTop: 12, padding: 10, background: "#dbeafe", color: "#1e40af", borderRadius: 8, fontSize: 13 }}>
          Total: <strong>{total} {item.unit}</strong>
        </div>
      )}
    </Modal>
  );
}

function ConsumableTransferDialog({ open, onClose, onDone, consumables, technicians }) {
  const [cid, setCid] = useState("");
  const [qty, setQty] = useState(0);
  const [techId, setTechId] = useState("");
  const submit = asyncCall(async () => {
    if (!cid || qty <= 0 || !techId) return await window.alert("Preencha todos os campos.");
    await api.stokConsumableTransfer(cid, parseInt(qty, 10), techId);
    setCid(""); setQty(0); setTechId(""); onClose();
  }, onDone, "Erro na transferência");
  return (
    <Modal open={open} onClose={onClose} title="↗ Transferir insumo para técnico" data-testid="cons-transfer-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="cons-transfer-submit">Transferir</button></>}
    >
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Insumo</label>
        <select data-testid="cons-transfer-id" style={inputStyle} value={cid} onChange={(e) => setCid(e.target.value)}>
          <option value="">Selecione…</option>
          {consumables.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Quantidade</label>
        <input data-testid="cons-transfer-qty" type="number" min="1" style={inputStyle} value={qty} onChange={(e) => setQty(e.target.value)} />
      </div>
      <div>
        <label style={labelStyle}>Técnico</label>
        <select data-testid="cons-transfer-tech" style={inputStyle} value={techId} onChange={(e) => setTechId(e.target.value)}>
          <option value="">Selecione…</option>
          {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
    </Modal>
  );
}

// ============================================================
// Serviços (OS)
// ============================================================
const SERVICE_TYPES = ["instalacao", "reparo", "troca", "retirada", "ponto_adicional"];

function ServicosSection({ services, technicians, consumables, reload }) {
  const [showCreate, setShowCreate] = useState(false);
  const [closing, setClosing] = useState(null); // service object
  const techMap = useMemo(() => Object.fromEntries(technicians.map((t) => [t.id, t.name])), [technicians]);
  return (
    <Card
      title={`Serviços (${services.length})`}
      action={<button data-testid="svc-create-btn" style={btnPrimary} onClick={() => setShowCreate(true)}>+ Nova OS</button>}
    >
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 10 }}>OS</th>
              <th style={{ padding: 10 }}>Tipo</th>
              <th style={{ padding: 10 }}>Cliente</th>
              <th style={{ padding: 10 }}>Técnico</th>
              <th style={{ padding: 10 }}>Status</th>
              <th style={{ padding: 10 }}>Aberta em</th>
              <th style={{ padding: 10, textAlign: "right" }}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {services.length === 0 ? (
              <tr><td colSpan={7} style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Nenhuma OS cadastrada.</td></tr>
            ) : services.map((s) => (
              <tr key={s.id} style={{ borderTop: "1px solid #e2e8f0" }} data-testid={`svc-row-${s.id}`}>
                <td style={{ padding: 10, fontFamily: "monospace", fontWeight: 700 }}>{s.id}</td>
                <td style={{ padding: 10 }}>
                  {s.type}
                  {s.auto_opened && <span title="Auto-aberta pela Lousa" style={{ marginLeft: 4, fontSize: 10, color: "#64748b" }}></span>}
                  {s.auto_closed && <span title="Auto-fechada pela Lousa" style={{ marginLeft: 4, fontSize: 10, color: "#15803d" }}>✓auto</span>}
                </td>
                <td style={{ padding: 10 }}>{s.client_name}</td>
                <td style={{ padding: 10 }}>{techMap[s.technician_id] || s.technician_id}</td>
                <td style={{ padding: 10 }}>
                  <StatusPill status={s.status} />
                  {s.error_reason && (
                    <div style={{ fontSize: 10, color: "#991b1b", marginTop: 2, maxWidth: 220 }}>
                      {s.error_reason}
                    </div>
                  )}
                </td>
                <td style={{ padding: 10, fontSize: 12, color: "#64748b" }}>{fmtDate(s.created_at)}</td>
                <td style={{ padding: 10, textAlign: "right" }}>
                  {(s.status === "ativo" || s.status === "erro_estoque") && (
                    <button style={btnGhost} onClick={() => setClosing(s)} data-testid={`svc-close-${s.id}`}>
                      {s.status === "erro_estoque" ? "Resolver" : "✓ Fechar"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CreateServiceDialog open={showCreate} onClose={() => setShowCreate(false)} onDone={reload} technicians={technicians} />
      <CloseServiceDialog service={closing} onClose={() => setClosing(null)} onDone={reload} consumables={consumables} />
    </Card>
  );
}

function CreateServiceDialog({ open, onClose, onDone, technicians }) {
  const [data, setData] = useState({ type: "instalacao", client_id: "", client_name: "", technician_id: "", reason: "" });
  const submit = asyncCall(async () => {
    if (!data.client_id || !data.client_name || !data.technician_id) return await window.alert("Preencha cliente, ID e técnico.");
    await api.stokServiceCreate(data);
    setData({ type: "instalacao", client_id: "", client_name: "", technician_id: "", reason: "" });
    onClose();
  }, onDone, "Erro ao criar OS");
  return (
    <Modal open={open} onClose={onClose} title="Nova ordem de serviço" data-testid="svc-create-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="svc-create-submit">Abrir OS</button></>}
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginBottom: 10 }}>
        <div>
          <label style={labelStyle}>Tipo</label>
          <select data-testid="svc-create-type" style={inputStyle} value={data.type} onChange={(e) => setData({ ...data, type: e.target.value })}>
            {SERVICE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Técnico</label>
          <select data-testid="svc-create-tech" style={inputStyle} value={data.technician_id} onChange={(e) => setData({ ...data, technician_id: e.target.value })}>
            <option value="">Selecione…</option>
            {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={labelStyle}>ID do cliente</label>
        <input data-testid="svc-create-client-id" style={inputStyle} value={data.client_id} onChange={(e) => setData({ ...data, client_id: e.target.value })} placeholder="Ex.: 1234 ou CPF" />
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={labelStyle}>Nome do cliente</label>
        <input data-testid="svc-create-client-name" style={inputStyle} value={data.client_name} onChange={(e) => setData({ ...data, client_name: e.target.value })} />
      </div>
      <div>
        <label style={labelStyle}>Motivo (opcional)</label>
        <input data-testid="svc-create-reason" style={inputStyle} value={data.reason} onChange={(e) => setData({ ...data, reason: e.target.value })} />
      </div>
    </Modal>
  );
}

function CloseServiceDialog({ service, onClose, onDone, consumables }) {
  const [mac, setMac] = useState("");
  const [items, setItems] = useState({});
  const [tag, setTag] = useState("instalacao");
  const [portInfo, setPortInfo] = useState(null); // { current_port, free_ports_same_cto, service_type }
  const [portSwap, setPortSwap] = useState(false);
  const [newPort, setNewPort] = useState("");

  useEffect(() => {
    setMac(""); setItems({}); setTag(service?.type || "instalacao");
    setPortInfo(null); setPortSwap(false); setNewPort("");
    if (!service?.id) return;
    let cancelled = false;
    api.stokClientCtoPort(service.id)
      .then((d) => { if (!cancelled) setPortInfo(d); })
      .catch(() => { /* opcional — segue sem porta */ });
    return () => { cancelled = true; };
  }, [service]);

  if (!service) return null;
  const needsMac = ["instalacao", "troca", "retirada"].includes(service.type);
  const hasCurrentPort = !!portInfo?.current_port;
  const isRetirada = service.type === "retirada";
  const isInstallOrMaint = ["instalacao", "reparo", "troca", "ponto_adicional"].includes(service.type);

  const submit = asyncCall(async () => {
    const used_items = Object.entries(items).filter(([, q]) => +q > 0).map(([consumable_id, q]) => ({ consumable_id, quantity: parseInt(q, 10) }));
    if (needsMac && !mac.trim()) return await window.alert("Informe o MAC da ONT.");
    if (isInstallOrMaint && hasCurrentPort && portSwap && !newPort) {
      return await window.alert("Selecione a nova porta da CTO.");
    }
    const payload = {
      ont_mac: mac.trim() || null,
      used_items,
      tag: tag || service.type,
      port_swap: !!(isInstallOrMaint && hasCurrentPort && portSwap),
      new_port_number: (isInstallOrMaint && hasCurrentPort && portSwap && newPort)
        ? parseInt(newPort, 10) : null,
    };
    await api.stokServiceClose(service.id, payload);
    onClose();
  }, onDone, "Erro ao fechar OS");

  return (
    <Modal open={!!service} onClose={onClose} title={`Fechar ${service.id} — ${service.client_name}`} data-testid="svc-close-dialog"
      footer={<><button style={btnSec} onClick={onClose}>Cancelar</button>
        <button style={btnPrimary} onClick={submit} data-testid="svc-close-submit">Confirmar fechamento</button></>}
    >
      {needsMac && (
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>MAC da ONT</label>
          <input data-testid="svc-close-mac" style={inputStyle} value={mac} onChange={(e) => setMac(e.target.value)} placeholder="AA:BB:CC:DD:EE:FF" />
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
            {service.type === "retirada" ? "MAC vinculado ao cliente." : "MAC do estoque do técnico responsável."}
          </div>
        </div>
      )}

      {/* Porta da CTO — só aparece se cliente já tem porta vinculada */}
      {hasCurrentPort && (
        <div data-testid="svc-close-cto-port" style={{
          marginBottom: 12, padding: 12, borderRadius: 10,
          background: isRetirada ? "#fef3c7" : "#f1f5f9",
          border: "1px solid " + (isRetirada ? "#fbbf24" : "#cbd5e1"),
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
            Cliente já vinculado à porta <strong>{portInfo.current_port.port_number}</strong>{" "}
            da CTO <strong>{portInfo.current_port.cto_name}</strong>
          </div>
          {isRetirada && (
            <div data-testid="svc-close-port-release-note" style={{ fontSize: 12, color: "#92400e" }}>
              ️ Esta porta será <strong>liberada automaticamente</strong> ao concluir a retirada.
            </div>
          )}
          {isInstallOrMaint && (
            <>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#0f172a", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  data-testid="svc-close-port-swap-toggle"
                  checked={portSwap}
                  onChange={(e) => { setPortSwap(e.target.checked); if (!e.target.checked) setNewPort(""); }}
                />
                Houve troca de porta?
              </label>
              {portSwap && (
                <div style={{ marginTop: 10 }}>
                  <label style={labelStyle}>Nova porta (livres na mesma CTO)</label>
                  <select
                    data-testid="svc-close-port-swap-select"
                    style={inputStyle}
                    value={newPort}
                    onChange={(e) => setNewPort(e.target.value)}
                  >
                    <option value="">Selecione…</option>
                    {(portInfo.free_ports_same_cto || []).map((p) => (
                      <option key={p.number} value={p.number}>Porta {p.number}</option>
                    ))}
                  </select>
                  {(portInfo.free_ports_same_cto || []).length === 0 && (
                    <div style={{ fontSize: 11, color: "#991b1b", marginTop: 4 }}>
                      Nenhuma porta livre nesta CTO. Libere uma porta primeiro.
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}

      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Tag</label>
        <input data-testid="svc-close-tag" style={inputStyle} value={tag} onChange={(e) => setTag(e.target.value)} placeholder="instalacao, reparo, etc." />
      </div>
      <div>
        <label style={labelStyle}>Insumos utilizados (opcional)</label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
          {consumables.map((c) => (
            <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 13, flex: 1 }}>{c.name}</span>
              <input
                data-testid={`svc-close-qty-${c.id}`}
                type="number" min="0" placeholder={c.unit}
                style={{ ...inputStyle, width: 100 }}
                value={items[c.id] || ""}
                onChange={(e) => setItems({ ...items, [c.id]: e.target.value })}
              />
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

// ============================================================
// Histórico
// ============================================================
function HistoricoSection({ history, reload }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const filtered = useMemo(() => {
    const qq = q.toLowerCase();
    return history.filter((h) => {
      const txt = !qq || (h.description || "").toLowerCase().includes(qq) || (h.user || "").toLowerCase().includes(qq);
      const t = !type || h.type === type;
      return txt && t;
    });
  }, [history, q, type]);
  const types = useMemo(() => Array.from(new Set(history.map((h) => h.type))).sort(), [history]);

  const downloadExport = async (format) => {
    try {
      const params = new URLSearchParams();
      params.set("format", format);
      if (type) params.set("type", type);
      if (q) params.set("q", q);
      const token = window.localStorage.getItem("ponto_token") || "";
      const url = `${process.env.REACT_APP_BACKEND_URL}/api/stok/history/export?${params.toString()}`;
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) {
        const err = await res.text();
        await window.alert(`Erro ao exportar: ${err}`);
        return;
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.download = `estoque_historico_${ts}.${format}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (e) {
      await window.alert(`Erro ao exportar: ${e.message}`);
    }
  };

  return (
    <Card
      title={`Histórico (${filtered.length})`}
      action={
        <div style={{ display: "flex", gap: 6 }}>
          <button style={btnGhost} onClick={() => downloadExport("csv")} data-testid="hist-export-csv">CSV</button>
          <button style={btnGhost} onClick={() => downloadExport("pdf")} data-testid="hist-export-pdf">PDF</button>
          <button style={btnGhost} onClick={reload} data-testid="hist-reload">⟳ Atualizar</button>
        </div>
      }
    >
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input
          data-testid="hist-search"
          style={{ ...inputStyle, flex: 1, minWidth: 220 }}
          placeholder="Buscar descrição ou usuário…" value={q} onChange={(e) => setQ(e.target.value)}
        />
        <select data-testid="hist-type-filter" style={{ ...inputStyle, width: 220 }} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Todos os tipos</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", textAlign: "left" }}>
              <th style={{ padding: 10 }}>Data</th>
              <th style={{ padding: 10 }}>Tipo</th>
              <th style={{ padding: 10 }}>Tag</th>
              <th style={{ padding: 10 }}>Descrição</th>
              <th style={{ padding: 10 }}>Usuário</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={5} style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Sem registros.</td></tr>
            ) : filtered.map((h) => (
              <tr key={h.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                <td style={{ padding: 10, fontSize: 12, color: "#64748b", whiteSpace: "nowrap" }}>{fmtDate(h.date)}</td>
                <td style={{ padding: 10, fontSize: 12 }}>{h.type}</td>
                <td style={{ padding: 10, fontSize: 12 }}>{h.tag}</td>
                <td style={{ padding: 10 }}>{h.description}</td>
                <td style={{ padding: 10, fontSize: 12, color: "#64748b" }}>{h.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ============================================================
// Clientes — ONUs em uso (SmartOLT) com fabricante via IA
// ============================================================
const _th = { padding: "8px 10px", fontSize: 11, fontWeight: 700,
              color: "var(--text-secondary)", textTransform: "uppercase",
              letterSpacing: "0.06em", textAlign: "left",
              borderBottom: "1px solid var(--border-default)" };
const _td = { padding: "10px", fontSize: 12, verticalAlign: "middle" };


// Componente compacto de KPI usado no ClientesSection (linha 1529+).
// Mantido leve e isolado pra não acoplar com KpiCard mais ornamentado.
function Metric({ label, value, hint }) {
  return (
    <div style={{
      background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 10,
      padding: "10px 12px",
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b",
                     textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a",
                     marginTop: 2 }}>
        {value}
      </div>
      {hint && (
        <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
          {hint}
        </div>
      )}
    </div>
  );
}


function ClientesSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("");
  const [manufFilter, setManufFilter] = useState("all");
  const [identifying, setIdentifying] = useState(false);
  // iter163 — modal de histórico do equipamento
  const [historyClient, setHistoryClient] = useState(null);
  // iter170 — modal de retirada manual
  const [manualWithdrawClient, setManualWithdrawClient] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      // identify_manufacturer_max=0 → resposta rápida (só cache + KNOWN_PREFIXES).
      // Para identificar prefixos novos, usuário clica em "Identificar tudo".
      setData(await api.stokClientes(0));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);

  const identifyAll = async () => {
    if (!await window.confirm("Forçar descoberta de fabricantes via IA para TODAS as ONUs ainda desconhecidas?\n\nA IA Gemini será chamada para cada prefixo de SN não cacheado. Pode demorar 1-3 minutos dependendo do volume.")) return;
    setIdentifying(true);
    try {
      const r = await api.stokClientesIdentifyAll(false);
      await window.alert(`Descoberta concluída:\n\n• ${r.new_manufacturers_found} novos fabricantes encontrados\n• ${r.prefixes_tested} prefixos testados via IA\n• ${r.total_prefixes_unknown_before} eram desconhecidos antes`);
      await reload();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setIdentifying(false);
    }
  };

  useEffect(() => { reload(); }, [reload]);

  const items = useMemo(() => {
    if (!data) return [];
    const q = filter.trim().toLowerCase();
    return data.items.filter((it) => {
      if (manufFilter !== "all" && (it.manufacturer || "Desconhecido") !== manufFilter) return false;
      if (!q) return true;
      return [it.client_name, it.sn, it.mac, it.olt_name].filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [data, filter, manufFilter]);

  const signalColor = (txt) => {
    if (!txt) return { bg: "var(--bg-surface-2)", color: "var(--text-muted)" };
    const s = String(txt).toLowerCase();
    if (s.includes("very good") || s.includes("excelente")) return { bg: "var(--success-soft)", color: "var(--success-soft-fg)" };
    if (s.includes("good") || s.includes("bom")) return { bg: "var(--info-soft)", color: "var(--info-soft-fg)" };
    if (s.includes("acceptable") || s.includes("regular")) return { bg: "var(--warning-soft)", color: "var(--warning-soft-fg)" };
    return { bg: "var(--danger-soft)", color: "var(--danger-soft-fg)" };
  };

  if (loading && !data) return <Card>Carregando clientes do SmartOLT… <span style={{ fontSize: 11, color: "#94a3b8" }}>(timeout duro: 10s)</span></Card>;
  if (err) return <Card><div style={{ color: "#dc2626" }}>Erro: {err}</div></Card>;
  if (!data) return null;

  return (
    <>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 10, marginBottom: 14,
      }}>
        <Metric label="Clientes" value={data.total.toLocaleString("pt-BR")} />
        <Metric label="Identificados (IA)" value={`${data.identified}/${data.total}`}
                hint={`${Math.round(100 * data.identified / Math.max(1, data.total))}% reconhecidos`} />
        {Object.entries(data.by_manufacturer).slice(0, 3).map(([k, v]) => (
          <Metric key={k} label={k} value={v.toLocaleString("pt-BR")}
                  hint={`${Math.round(100 * v / Math.max(1, data.total))}%`} />
        ))}
      </div>

      <Card title={`Clientes ativos (${items.length} de ${data.total})`}
            subtitle="ONUs em uso pegas via API do SmartOLT — fabricante identificado por prefixo de SN ou IA (Gemini)."
            data-testid="clientes-card"
            action={
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={identifyAll} disabled={loading || identifying}
                        data-testid="clientes-identify-all"
                        className="btn btn-accent btn-sm"
                        title="Roda IA Gemini em todos os prefixos de SN ainda desconhecidos">
                  {identifying ? "Descobrindo via IA…" : "Forçar descoberta IA"}
                </button>
                <button onClick={reload} disabled={loading || identifying}
                        data-testid="clientes-reload"
                        className="btn btn-secondary btn-sm">
                  {loading ? "Atualizando…" : "Atualizar"}
                </button>
              </div>
            }>
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input className="input" data-testid="clientes-search" value={filter}
                 onChange={(e) => setFilter(e.target.value)}
                 placeholder="Buscar por cliente, SN, MAC, OLT…"
                 style={{ flex: 1, minWidth: 220 }} />
          <select className="input" data-testid="clientes-manuf-filter"
                  value={manufFilter} onChange={(e) => setManufFilter(e.target.value)}
                  style={{ width: 230 }}>
            <option value="all">Todos os fabricantes</option>
            {Object.keys(data.by_manufacturer).map((k) => (
              <option key={k} value={k}>{k} ({data.by_manufacturer[k]})</option>
            ))}
          </select>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "var(--bg-surface-2)" }}>
                <th style={_th}>Cliente</th>
                <th style={_th}>Número de série</th>
                <th style={_th}>Marca / Modelo</th>
                <th style={_th}>OLT / Slot / PON</th>
                <th style={_th}>Sinal</th>
                <th style={_th}>Porta CTO</th>
                <th style={_th}>Instalado por</th>
                <th style={_th}>Retirado por</th>
                <th style={_th}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 500).map((it) => {
                const sig = signalColor(it.signal_text);
                const ident = !!it.manufacturer;
                return (
                  <tr key={it.smartolt_external_id || `${it.sn || ""}-${it.mac || ""}`}
                      style={{ borderBottom: "1px solid var(--border-default)" }}
                      data-testid={`cliente-row-${it.sn || it.mac}`}>
                    <td style={_td}>
                      <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{it.client_name}</div>
                      {it.mac && <div className="mono" data-mono style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>MAC: {it.mac}</div>}
                    </td>
                    <td style={_td} className="mono" data-mono>{it.sn || "—"}</td>
                    <td style={_td}>
                      <span className={`pill pill--${ident ? "accent" : "neutral"}`}
                            style={{ fontWeight: 600 }}>
                        {it.manufacturer || "Desconhecido"}
                      </span>
                      {it.model && <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>{it.model}</div>}
                    </td>
                    <td style={_td} className="mono" data-mono>
                      {it.olt_name || "—"}
                      {it.board && <span style={{ color: "var(--text-muted)" }}> · slot {it.board}/pon {it.port}</span>}
                    </td>
                    <td style={_td}>
                      <span className="pill" style={{ background: sig.bg, color: sig.color, fontWeight: 600 }}>
                        {it.signal_text || "—"}
                      </span>
                    </td>
                    <td style={_td}>
                      {it.cto_name ? (
                        <div>
                          <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                            {it.cto_name}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                            porta {it.cto_port_number}
                            {it.port_changes > 0 && (
                              <span className="pill pill--warning"
                                    style={{ marginLeft: 6, fontSize: 9, padding: "1px 6px" }}
                                    title={`${it.port_changes} mudança(s) de porta no histórico`}>
                                {it.port_changes}× trocada
                              </span>
                            )}
                          </div>
                        </div>
                      ) : <span style={{ color: "var(--text-muted)" }}>—</span>}
                    </td>
                    <td style={_td}>
                      {it.installed_by ? (
                        <div>
                          <div style={{ fontWeight: 600 }}>{it.installed_by}</div>
                          {it.installed_at && (
                            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                              {new Date(it.installed_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
                            </div>
                          )}
                        </div>
                      ) : <span style={{ color: "var(--text-muted)" }}>—</span>}
                    </td>
                    <td style={_td}>
                      {it.withdrawn_by ? (
                        <div>
                          <div style={{ fontWeight: 600, color: "#b91c1c" }}>{it.withdrawn_by}</div>
                          {it.withdrawn_at && (
                            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                              {new Date(it.withdrawn_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
                            </div>
                          )}
                        </div>
                      ) : <span style={{ color: "var(--text-muted)" }}>—</span>}
                    </td>
                    <td style={_td}>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        <button className="btn btn-secondary btn-sm"
                                  data-testid={`cliente-history-btn-${it.sn || it.mac}`}
                                  onClick={() => setHistoryClient({
                                    client_id: it.client_id,
                                    client_name: it.client_name,
                                  })}>
                          Ver
                        </button>
                        <button className="btn btn-sm"
                                  data-testid={`cliente-manual-withdraw-btn-${it.sn || it.mac}`}
                                  title="Registrar retirada manual (sem OS)"
                                  onClick={() => setManualWithdrawClient(it)}
                                  style={{
                                    background: "linear-gradient(135deg,#dc2626,#991b1b)",
                                    color: "#fff", border: 0, padding: "4px 10px",
                                    borderRadius: 6, fontSize: 11, fontWeight: 700,
                                    cursor: "pointer",
                                  }}>
                          Retirar
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {items.length > 500 && (
            <div style={{ padding: 8, fontSize: 11, color: "var(--text-muted)", textAlign: "center" }}>
              Mostrando 500 de {items.length} resultados — use o filtro para refinar.
            </div>
          )}
        </div>
      </Card>
      {historyClient && (
        <ClientEquipmentHistoryModal
          client={historyClient}
          onClose={() => setHistoryClient(null)} />
      )}
      {manualWithdrawClient && (
        <ManualWithdrawDialog
          client={manualWithdrawClient}
          onClose={() => setManualWithdrawClient(null)}
          onDone={() => { setManualWithdrawClient(null); reload(); }} />
      )}
    </>
  );
}


// ============================================================
// Botão de RESET destrutivo — visível apenas para Auditor
// (zera ONTs, insumos e/ou histórico de lançamentos)
// ============================================================
function AuditorResetButton({ onDone }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [resetOnts, setResetOnts] = useState(true);
  const [resetInsumos, setResetInsumos] = useState(true);
  const [resetHistory, setResetHistory] = useState(true);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const submit = async () => {
    setErr(""); setBusy(true);
    try {
      const r = await api.stokAdminReset({
        confirm: confirm,
        reset_onts: resetOnts,
        reset_insumos: resetInsumos,
        reset_history: resetHistory,
      });
      setResult(r);
      onDone?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao zerar.");
    } finally { setBusy(false); }
  };

  return (
    <>
      <button data-testid="auditor-reset-btn"
              onClick={() => { setOpen(true); setConfirm(""); setResult(null); setErr(""); }}
              style={{
                padding: "8px 14px", borderRadius: 8, border: 0,
                background: "linear-gradient(135deg,#dc2626,#991b1b)",
                color: "#fff", fontSize: 13, fontWeight: 800, cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 6,
              }}>
        ️ Zerar estoque e lançamentos
      </button>
      {open && (
        <div data-testid="auditor-reset-modal"
              style={{
                position: "fixed", inset: 0, zIndex: 9999,
                background: "rgba(15,23,42,0.7)",
                display: "flex", alignItems: "center", justifyContent: "center",
                padding: 20,
              }}>
          <div style={{
            background: "#fff", borderRadius: 12, padding: 22,
            width: "min(94vw, 520px)",
            boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
          }}>
            <div style={{ fontSize: 17, fontWeight: 800, color: "#991b1b",
                            marginBottom: 8 }}>
              ️ Zerar Estoque · Ação Destrutiva
            </div>
            {!result && (
              <>
                <div style={{ fontSize: 13, color: "#475569",
                                lineHeight: 1.5, marginBottom: 14 }}>
                  Esta ação <b>apaga permanentemente</b> os dados selecionados
                  na <b>sua empresa</b>. Pode ser usada para um <i>reset
                  controlado</i> antes de um inventário completo.
                  <br /><br />
                  O log da ação fica registrado em <code>stok_admin_log</code>
                  com seu e-mail e horário — não é apagado mesmo com{" "}
                  <i>“Apagar histórico”</i> marcado.
                </div>

                <div style={{ display: "flex", flexDirection: "column",
                                gap: 6, marginBottom: 12,
                                padding: 12, background: "#fef2f2",
                                border: "1px solid #fecaca", borderRadius: 8 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                    <input type="checkbox" checked={resetOnts}
                            data-testid="reset-onts-chk"
                            onChange={(e) => setResetOnts(e.target.checked)} />
                    Apagar todas as ONTs (estoque + alocadas)
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                    <input type="checkbox" checked={resetInsumos}
                            data-testid="reset-insumos-chk"
                            onChange={(e) => setResetInsumos(e.target.checked)} />
                    Apagar todos os insumos
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                    <input type="checkbox" checked={resetHistory}
                            data-testid="reset-history-chk"
                            onChange={(e) => setResetHistory(e.target.checked)} />
                    Apagar histórico de lançamentos
                  </label>
                </div>

                <label style={{ fontSize: 12, fontWeight: 700, color: "#475569" }}>
                  Para confirmar, digite{" "}
                  <code style={{ background: "#fef2f2",
                                   padding: "2px 6px", borderRadius: 4,
                                   color: "#991b1b" }}>ZERAR ESTOQUE</code>
                </label>
                <input type="text" value={confirm}
                        data-testid="reset-confirm-input"
                        onChange={(e) => setConfirm(e.target.value)}
                        placeholder="ZERAR ESTOQUE"
                        style={{
                          width: "100%", marginTop: 6, padding: "10px 12px",
                          border: "2px solid #fecaca", borderRadius: 8,
                          fontFamily: "monospace", fontSize: 14,
                          boxSizing: "border-box",
                        }} />

                {err && (
                  <div style={{ color: "#dc2626", fontSize: 12, marginTop: 8 }}>
                    {err}
                  </div>
                )}

                <div style={{ display: "flex", gap: 8, marginTop: 18,
                                justifyContent: "flex-end" }}>
                  <button onClick={() => setOpen(false)}
                          data-testid="reset-cancel-btn"
                          style={{ ...btnSec, padding: "8px 14px" }}>
                    Cancelar
                  </button>
                  <button data-testid="reset-confirm-btn"
                          onClick={submit}
                          disabled={busy || confirm.trim().toUpperCase() !== "ZERAR ESTOQUE"
                                       || !(resetOnts || resetInsumos || resetHistory)}
                          style={{
                            padding: "8px 16px", borderRadius: 8, border: 0,
                            background: (busy || confirm.trim().toUpperCase() !== "ZERAR ESTOQUE")
                              ? "#fca5a5"
                              : "linear-gradient(135deg,#dc2626,#991b1b)",
                            color: "#fff", fontSize: 13, fontWeight: 800,
                            cursor: busy ? "wait" : "pointer",
                          }}>
                    {busy ? "Zerando…" : "️ Confirmar e zerar"}
                  </button>
                </div>
              </>
            )}
            {result && (
              <div data-testid="reset-result">
                <div style={{ background: "#ecfdf5", border: "1px solid #10b981",
                                padding: 12, borderRadius: 8, marginBottom: 12 }}>
                  <div style={{ fontWeight: 800, color: "#065f46", marginBottom: 6 }}>
                    ✅ Reset concluído
                  </div>
                  <div style={{ fontSize: 12, color: "#065f46", lineHeight: 1.6 }}>
                    ONTs apagadas: <b>{result.deleted?.onts || 0}</b> · Insumos: <b>{result.deleted?.insumos || 0}</b> · Histórico: <b>{result.deleted?.history || 0}</b>
                    <br /> Log ID: <code style={{ fontSize: 11 }}>{result.log_id}</code>
                  </div>
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button onClick={() => { setOpen(false); setConfirm(""); setResult(null); }}
                          style={{ ...btnSec, padding: "8px 14px" }}>
                    Fechar
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}


// ============================================================
// Painel principal
// ============================================================
export default function EstoquePanel({ currentUser }) {
  const [tab, setTab] = useState(() => {
    try {
      const ss = typeof window !== "undefined"
        ? window.sessionStorage.getItem("subtab:estoque") : null;
      if (ss) {
        window.sessionStorage.removeItem("subtab:estoque");
        return ss;
      }
    } catch {}
    return "dashboard";
  });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [data, setData] = useState({ onts: [], technicians: [], services: [], history: [], stock: {}, dashboard: null, consumables: [], pracas: [] });

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      // Promise.allSettled garante que 1 endpoint falhando não derruba
      // toda a UI; cada resultado é tratado individualmente.
      const results = await Promise.allSettled([
        api.stokOnts(), api.stokTechnicians(), api.stokServices(),
        api.stokHistory(), api.stokStock(), api.stokDashboard(),
        api.stokCatalog(), api.finFiliaisList(true),
      ]);
      const [onts, technicians, services, history, stock, dashboard, catalog, pracas] =
        results.map((r) => (r.status === "fulfilled" ? r.value : null));
      // Coleta erros mas filtra 403 (gate de role) — esses não devem
      // poluir a UI dos non-auditors.
      const errors = results
        .filter((r) => r.status === "rejected")
        .map((r) => r.reason)
        .filter((e) => e?.response?.status !== 403);
      if (errors.length) {
        const first = errors[0];
        setErr(first?.response?.data?.detail || first?.message || "");
      }
      setData({
        onts: onts || [],
        technicians: technicians || [],
        services: services || [],
        history: history || [],
        stock: stock || {},
        dashboard: dashboard || null,
        consumables: catalog?.consumables || [],
        pracas: pracas || [],
      });
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div data-testid="estoque-panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", color: "#0f172a" }}>Estoque · Fibra Óptica</h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>ONTs, insumos e ordens de serviço integrados aos técnicos da Lousa.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {(currentUser?.role || "").toLowerCase() === "auditor" && (
            <>
              <GranularResetButton
                technicians={data.technicians}
                pracas={data.pracas}
                consumables={data.consumables}
                onDone={reload} />
              <AuditorResetButton onDone={reload} />
            </>
          )}
          <button data-testid="estoque-reload" style={btnSec} onClick={reload} disabled={loading}>{loading ? "Carregando…" : "⟳ Recarregar"}</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 4, padding: 4, background: "#f1f5f9", borderRadius: 12, marginBottom: 14, overflowX: "auto" }}>
        {SUB_TABS.map((s) => (
          <button
            key={s.id}
            data-testid={`estoque-tab-${s.id}`}
            onClick={() => setTab(s.id)}
            style={{
              padding: "8px 14px", border: "none", borderRadius: 8,
              background: tab === s.id ? "white" : "transparent",
              color: tab === s.id ? "#0f172a" : "#475569",
              fontWeight: 700, fontSize: 13, cursor: "pointer", whiteSpace: "nowrap",
              boxShadow: tab === s.id ? "0 1px 3px rgba(0,0,0,.08)" : "none",
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {err && !/auditor/i.test(err) && (
        <Card><div style={{ color: "#dc2626" }}>Erro: {err}</div></Card>
      )}

      {tab === "dashboard" && (
        <>
          {(currentUser?.role || "").toLowerCase() === "auditor" && (
            <ShrinkageReportCard />
          )}
          <DashboardSection dashboard={data.dashboard} consumables={data.consumables} history={data.history || []} onts={data.onts || []} />
        </>
      )}
      {tab === "onts" && <OntsSection onts={data.onts} technicians={data.technicians} reload={reload} />}
      {tab === "insumos" && <InsumosSection consumables={data.consumables} technicians={data.technicians} stock={data.stock} reload={reload} />}
      {tab === "clientes" && <ClientesSection />}
      {tab === "smartolt-historico" && <SmartoltHistoryPanel />}
      {tab === "servicos" && <ServicosSection services={data.services} technicians={data.technicians} consumables={data.consumables} reload={reload} />}
      {tab === "balanco" && <BalancoTab
        pracas={(data.pracas || []).map((p) => ({ id: p.id, name: p.name }))}
        techs={(data.technicians || []).map((t) => ({ id: t.id, name: t.name }))}
        consumablesCatalog={data.consumables}
        currentUser={currentUser} />}
      {tab === "historico" && <HistoricoSection history={data.history} reload={reload} />}
      {tab === "transfers" && <StokTransfersPanel />}
      {tab === "ai-review" && <StokAiReviewPanel />}
      {tab === "defeitos" && <DefectiveOntsPanel />}
      {tab === "duplicados" && <OntDuplicateAlertsPanel />}
      {tab === "saude" && <StokHealthDashboard onNavigate={setTab} />}
      {tab === "audit-sn" && <WithdrawSnAuditPanel />}
      {tab === "lotes" && <OntBatchHistoryPanel />}
      {tab === "compras" && <CentralComprasPanel currentUser={currentUser} embedded />}
    </div>
  );
}
