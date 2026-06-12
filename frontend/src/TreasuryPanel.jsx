/**
 * TreasuryPanel.jsx — Painel Contas a Pagar (iter236).
 * Reformado com base nas melhores práticas Bill.com / Conta Azul / Tipalti:
 *   - Header com KPIs principais (saldo, vencidos, vencem hoje, pagos)
 *   - Banner de ambiente (sandbox/produção + kill-switch)
 *   - Tabs: Inbox DDA | A Pagar | Recorrências | Contas
 *
 * Ações disponíveis a partir das tabs:
 *   - Aprovar / Rejeitar boleto DDA → vira pagamento agendado
 *   - Criar pagamento manual (Pix por chave/telefone OU boleto)
 *   - Criar recorrência (início/fim/valor total → N parcelas auto)
 *   - Enviar comprovante WhatsApp ("by SmartProv")
 *   - Definir conta padrão
 */
import React, { useEffect, useState } from "react";
import {
  Inbox, Banknote, Repeat, Wallet, ShieldCheck, ShieldAlert,
  TrendingDown, AlertTriangle, Clock,
} from "lucide-react";
import InboxDDA from "./treasury/InboxDDA";
import PaymentsList from "./treasury/PaymentsList";
import RecurringList from "./treasury/RecurringList";
import AccountsList from "./treasury/AccountsList";
import { treasuryApi, C, BRL } from "./treasury/api";

const TABS = [
  { id: "dda", label: "Inbox DDA", icon: Inbox },
  { id: "payments", label: "A Pagar", icon: Banknote },
  { id: "recurring", label: "Recorrências", icon: Repeat },
  { id: "accounts", label: "Contas", icon: Wallet },
];

export default function TreasuryPanel() {
  const [tab, setTab] = useState("dda");
  const [safety, setSafety] = useState(null);
  const [kpis, setKpis] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadHeader = async () => {
    try {
      const [s, k] = await Promise.all([
        treasuryApi.safety(),
        treasuryApi.kpis(),
      ]);
      setSafety(s); setKpis(k);
    } catch (e) { console.warn("treasury header load:", e); }
  };
  useEffect(() => { loadHeader(); }, [refreshKey]);

  return (
    <div data-testid="treasury-panel" style={{ background: C.bg,
      minHeight: "100vh", color: C.text, padding: 24 }}>
      {/* Banner segurança */}
      <SafetyBanner safety={safety} />

      {/* KPIs */}
      <KPIRow kpis={kpis} safety={safety} />

      {/* Tabs */}
      <div data-testid="treasury-tabs"
        style={{ display: "flex", gap: 6, marginTop: 20, marginBottom: 0,
          borderBottom: `1px solid ${C.border}` }}>
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button key={t.id} data-testid={`treasury-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              style={{
                padding: "12px 18px", border: 0, cursor: "pointer",
                background: "transparent",
                color: active ? C.accent : C.muted,
                fontWeight: 700, fontSize: 14,
                borderBottom: `2px solid ${active ? C.accent : "transparent"}`,
                display: "inline-flex", alignItems: "center", gap: 8,
                marginBottom: -1,
              }}>
              <Icon size={16}/> {t.label}
            </button>
          );
        })}
      </div>

      <div style={{ background: C.bg }}>
        {tab === "dda" && <InboxDDA onPaymentCreated={() => setRefreshKey((k) => k + 1)} />}
        {tab === "payments" && <PaymentsList refreshKey={refreshKey} />}
        {tab === "recurring" && <RecurringList />}
        {tab === "accounts" && <AccountsList />}
      </div>
    </div>
  );
}

function SafetyBanner({ safety }) {
  if (!safety) return null;
  const isProd = safety.is_production;
  const ready = safety.prod_ready;
  const bg = isProd
    ? (ready ? "#064e3b" : "#7c2d12")
    : "#1e3a8a";
  const Icon = (isProd && ready) ? ShieldCheck : ShieldAlert;
  const label = isProd
    ? (ready ? "PRODUÇÃO ATIVA" : "PRODUÇÃO — KILL-SWITCH DESLIGADO")
    : "HOMOLOGAÇÃO / SANDBOX";
  return (
    <div data-testid="treasury-safety-banner" style={{
      background: bg, color: "white", padding: "10px 16px", borderRadius: 10,
      fontSize: 12, display: "flex", alignItems: "center", gap: 10,
      marginBottom: 16,
    }}>
      <Icon size={16}/>
      <strong>{label}</strong>
      <span style={{ opacity: .8 }}>·</span>
      <span>Auto-aprovação até {BRL(safety.auto_approval_max_brl)}</span>
      <span style={{ opacity: .8 }}>·</span>
      <span>Acima de {BRL(safety.human_required_above_brl)} exige CTO</span>
      {!safety.has_asaas_key && (
        <span style={{ marginLeft: "auto", background: "#7f1d1d",
          padding: "2px 8px", borderRadius: 6 }}>
          ASAAS_API_KEY ausente
        </span>
      )}
    </div>
  );
}

function KPIRow({ kpis, safety }) {
  if (!kpis) return null;
  const saldo = (kpis.saldo_asaas && typeof kpis.saldo_asaas === "object")
    ? (kpis.saldo_asaas.balance ?? 0) : (kpis.saldo_asaas ?? 0);
  return (
    <div data-testid="treasury-kpis" style={{
      display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12,
    }}>
      <KPI label="Saldo Asaas" value={BRL(safety?.has_asaas_key ? saldo : 0)}
        icon={Wallet} color={C.green} testid="kpi-saldo"/>
      <KPI label="Próximos 7 dias" value={BRL(kpis.outflow_forecast?.["7d"] || 0)}
        icon={Clock} color={C.blue} testid="kpi-7d"/>
      <KPI label="Aguarda CTO" value={BRL(kpis.pending_approval || 0)}
        icon={AlertTriangle} color={C.amber} testid="kpi-pending"/>
      <KPI label="Pagos hoje" value={BRL(kpis.today_paid || 0)}
        icon={TrendingDown} color={C.green} testid="kpi-paid"/>
      <KPI label="Bloqueados (risco)" value={BRL(kpis.blocked_risk || 0)}
        icon={ShieldAlert} color={C.red} testid="kpi-blocked"/>
    </div>
  );
}

function KPI({ label, value, icon: Icon, color, testid }) {
  return (
    <div data-testid={testid} style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 6 }}>
        <span style={{ color: C.muted, fontSize: 11, textTransform: "uppercase",
          letterSpacing: 0.6, fontWeight: 600 }}>{label}</span>
        <Icon size={14} color={color}/>
      </div>
      <div style={{ color: C.text, fontSize: 20, fontWeight: 800 }}>{value}</div>
    </div>
  );
}
