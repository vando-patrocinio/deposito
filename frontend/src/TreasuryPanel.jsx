/**
 * TreasuryPanel.jsx — Painel Contas a Pagar (iter237).
 * Mudanças vs iter236:
 *  - KPIs agora respeitam o mês selecionado (seletor no header)
 *  - Banner com saldo Asaas + ambiente
 */
import React, { useEffect, useState } from "react";
import {
  Inbox, Banknote, Repeat, Wallet, ShieldCheck, ShieldAlert,
  TrendingDown, AlertTriangle, Clock, CheckCircle2, ChevronLeft, ChevronRight,
  Users,
} from "lucide-react";
import InboxDDA from "./treasury/InboxDDA";
import PaymentsList from "./treasury/PaymentsList";
import RecurringList from "./treasury/RecurringList";
import AccountsList from "./treasury/AccountsList";
import FornecedoresIA from "./treasury/FornecedoresIA";
import {
  treasuryApi, C, BRL, monthLabel, currentMonth, addMonths,
} from "./treasury/api";

const TABS = [
  { id: "dda", label: "Inbox DDA", icon: Inbox },
  { id: "payments", label: "A Pagar", icon: Banknote },
  { id: "recurring", label: "Recorrências", icon: Repeat },
  { id: "fornecedores", label: "Fornecedores IA", icon: Users },
  { id: "accounts", label: "Contas", icon: Wallet },
];

export default function TreasuryPanel() {
  const [tab, setTab] = useState("dda");
  const [safety, setSafety] = useState(null);
  const [kpisMonth, setKpisMonth] = useState(null);
  const [month, setMonth] = useState(currentMonth());
  const [refreshKey, setRefreshKey] = useState(0);

  const loadHeader = async () => {
    try {
      const [s, k] = await Promise.all([
        treasuryApi.safety(),
        treasuryApi.kpisByMonth(month),
      ]);
      setSafety(s); setKpisMonth(k);
    } catch (e) { console.warn("treasury header load:", e); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadHeader(); }, [refreshKey, month]);

  return (
    <div data-testid="treasury-panel" style={{ background: C.bg,
      minHeight: "100vh", color: C.text, padding: 24 }}>
      <SafetyBanner safety={safety} />

      {/* Seletor de mês KPIs */}
      <div data-testid="kpi-month-selector" style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 12, gap: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button data-testid="kpi-month-prev"
            onClick={() => setMonth(addMonths(month, -1))}
            style={btnNav}><ChevronLeft size={14}/></button>
          <input type="month" data-testid="kpi-month-input" value={month}
            onChange={(e) => setMonth(e.target.value)} style={monthInput}/>
          <button data-testid="kpi-month-next"
            onClick={() => setMonth(addMonths(month, +1))}
            style={btnNav}><ChevronRight size={14}/></button>
          <strong style={{ color: C.text, marginLeft: 6, fontSize: 13 }}>
            KPIs de {monthLabel(month)}
          </strong>
        </div>
        <button data-testid="kpi-month-now"
          onClick={() => setMonth(currentMonth())} style={btnGhost}>
          Mês atual
        </button>
      </div>

      <KPIRow kpisMonth={kpisMonth} safety={safety} />

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
        {tab === "fornecedores" && <FornecedoresIA />}
        {tab === "accounts" && <AccountsList />}
      </div>
    </div>
  );
}

function SafetyBanner({ safety }) {
  if (!safety) return null;
  const isProd = safety.is_production;
  const ready = safety.prod_ready;
  const bg = isProd ? (ready ? "#064e3b" : "#7c2d12") : "#1e3a8a";
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

function KPIRow({ kpisMonth, safety }) {
  const t = kpisMonth?.totals || {};
  const c = kpisMonth?.counts || {};
  return (
    <div data-testid="treasury-kpis" style={{
      display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12,
    }}>
      <KPI label="A Pagar (mês)" value={BRL(t.pending || 0)}
        sub={`${c.pending || 0} pendentes`}
        icon={Clock} color={C.blue} testid="kpi-pending"/>
      <KPI label="Pagos (mês)" value={BRL(t.paid || 0)}
        sub={`${c.paid || 0} pagos`}
        icon={CheckCircle2} color={C.green} testid="kpi-paid"/>
      <KPI label="Vencidos no mês" value={BRL(t.overdue || 0)}
        sub="aguardando ação"
        icon={AlertTriangle} color={C.amber} testid="kpi-overdue"/>
      <KPI label="Bloqueados (risco)" value={BRL(t.blocked || 0)}
        sub="auditoria IA"
        icon={ShieldAlert} color={C.red} testid="kpi-blocked"/>
      <KPI label="Saldo Asaas" value={BRL(0)}  /* preenchido por endpoint dedicado */
        sub={safety?.environment ? safety.environment.toUpperCase() : "—"}
        icon={Wallet} color={C.green} testid="kpi-saldo"/>
    </div>
  );
}

function KPI({ label, value, sub, icon: Icon, color, testid }) {
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
      {sub && <div style={{ color: C.muted, fontSize: 11, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

const monthInput = { padding: "5px 8px", fontSize: 13, borderRadius: 6,
  border: `1px solid ${C.border}`, background: C.card, color: C.text };
const btnNav = { background: C.cardSoft, color: C.text,
  border: `1px solid ${C.border}`, borderRadius: 6, padding: "5px 8px",
  cursor: "pointer", display: "inline-flex", alignItems: "center" };
const btnGhost = { background: "transparent", color: C.text,
  border: `1px solid ${C.border}`, borderRadius: 8, padding: "6px 12px",
  fontSize: 12, cursor: "pointer" };
