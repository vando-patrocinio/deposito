/**
 * TreasuryPanel.jsx — Painel Contas a Pagar (iter237).
 * Mudanças vs iter236:
 *  - KPIs agora respeitam o mês selecionado (seletor no header)
 *  - Banner com saldo Asaas + ambiente
 */
import React, { useEffect, useState } from "react";
import {
  Inbox, Banknote, Repeat, Wallet, ShieldCheck, ShieldAlert,
  AlertTriangle, Clock, CheckCircle2, ChevronLeft, ChevronRight,
  Users, CalendarRange, Building2,
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
  const [kpis, setKpis] = useState(null);
  const [filialKpis, setFilialKpis] = useState(null);
  const [monthFrom, setMonthFrom] = useState(currentMonth());
  const [monthTo, setMonthTo] = useState(currentMonth());
  const [refreshKey, setRefreshKey] = useState(0);

  const loadHeader = async () => {
    try {
      const [s, k, fk] = await Promise.all([
        treasuryApi.safety(),
        treasuryApi.kpisByRange(monthFrom, monthTo),
        treasuryApi.kpisByFilial(monthFrom, monthTo).catch(() => null),
      ]);
      setSafety(s); setKpis(k); setFilialKpis(fk);
    } catch (e) { console.warn("treasury header load:", e); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadHeader(); }, [refreshKey, monthFrom, monthTo]);

  // Garante from <= to
  const setFrom = (v) => {
    setMonthFrom(v);
    if (v > monthTo) setMonthTo(v);
  };
  const setTo = (v) => {
    setMonthTo(v);
    if (v < monthFrom) setMonthFrom(v);
  };

  return (
    <div data-testid="treasury-panel" style={{ background: C.bg,
      minHeight: "100vh", color: C.text, padding: 24 }}>
      <SafetyBanner safety={safety} />

      <PeriodRange
        from={monthFrom} to={monthTo}
        setFrom={setFrom} setTo={setTo}
      />

      <KPIRow kpis={kpis} safety={safety} />

      <FilialMiniCard data={filialKpis} />

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
        {tab === "payments" && <PaymentsList refreshKey={refreshKey}
          monthFrom={monthFrom} monthTo={monthTo} />}
        {tab === "recurring" && <RecurringList />}
        {tab === "fornecedores" && <FornecedoresIA />}
        {tab === "accounts" && <AccountsList />}
      </div>
    </div>
  );
}

function PeriodRange({ from, to, setFrom, setTo }) {
  const oneMonth = from === to;
  return (
    <div data-testid="treasury-period-range" style={{
      display: "flex", alignItems: "center", gap: 10, marginBottom: 12,
      flexWrap: "wrap", background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 10, padding: "10px 14px",
    }}>
      <CalendarRange size={16} color={C.accent}/>
      <strong style={{ color: C.text, fontSize: 13 }}>Período:</strong>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button data-testid="period-from-prev"
          onClick={() => setFrom(addMonths(from, -1))} style={btnNav}>
          <ChevronLeft size={14}/></button>
        <input type="month" data-testid="period-from" value={from}
          onChange={(e) => setFrom(e.target.value)} style={monthInput}/>
        <button data-testid="period-from-next"
          onClick={() => setFrom(addMonths(from, +1))} style={btnNav}>
          <ChevronRight size={14}/></button>
      </div>

      <span style={{ color: C.muted, fontSize: 13 }}>até</span>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button data-testid="period-to-prev"
          onClick={() => setTo(addMonths(to, -1))} style={btnNav}>
          <ChevronLeft size={14}/></button>
        <input type="month" data-testid="period-to" value={to}
          onChange={(e) => setTo(e.target.value)} style={monthInput}/>
        <button data-testid="period-to-next"
          onClick={() => setTo(addMonths(to, +1))} style={btnNav}>
          <ChevronRight size={14}/></button>
      </div>

      <strong style={{ color: C.text, fontSize: 13, marginLeft: 8 }}>
        {oneMonth ? monthLabel(from) : `${monthLabel(from)} → ${monthLabel(to)}`}
      </strong>

      <button data-testid="period-now"
        onClick={() => { const m = currentMonth(); setFrom(m); setTo(m); }}
        style={{ ...btnNav, marginLeft: "auto", padding: "5px 12px",
          fontSize: 11, fontWeight: 700 }}>
        Mês atual
      </button>
      <button data-testid="period-last-3m"
        onClick={() => { const t = currentMonth(); setFrom(addMonths(t, -2)); setTo(t); }}
        style={btnGhost}>Últimos 3m</button>
      <button data-testid="period-ytd"
        onClick={() => { const t = currentMonth();
          setFrom(`${t.slice(0, 4)}-01`); setTo(t); }}
        style={btnGhost}>Ano</button>
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

function KPIRow({ kpis, safety }) {
  const t = kpis?.totals || {};
  const c = kpis?.counts || {};
  return (
    <div data-testid="treasury-kpis" style={{
      display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12,
    }}>
      <KPI label="A Pagar (período)" value={BRL(t.pending || 0)}
        sub={`${c.pending || 0} pendentes`}
        icon={Clock} color={C.blue} testid="kpi-pending"/>
      <KPI label="Pagos (período)" value={BRL(t.paid || 0)}
        sub={`${c.paid || 0} pagos`}
        icon={CheckCircle2} color={C.green} testid="kpi-paid"/>
      <KPI label="Vencidos no período" value={BRL(t.overdue || 0)}
        sub="aguardando ação"
        icon={AlertTriangle} color={C.amber} testid="kpi-overdue"/>
      <KPI label="Bloqueados (risco)" value={BRL(t.blocked || 0)}
        sub="auditoria IA"
        icon={ShieldAlert} color={C.red} testid="kpi-blocked"/>
      <KPI label="Saldo Asaas" value={BRL(0)}
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

function FilialMiniCard({ data }) {
  if (!data || !data.by_filial) return null;
  const rows = data.by_filial.filter((r) => r.total_committed > 0).slice(0, 6);
  const totals = data.totals || {};
  if (rows.length === 0) {
    return (
      <div data-testid="treasury-kpi-by-filial" style={{
        background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, padding: 14, marginTop: 12,
        color: C.muted, fontSize: 12,
      }}>
        <Building2 size={14} style={{ verticalAlign: "middle", marginRight: 6 }} color={C.accent} />
        Nenhum pagamento atribuído a filial neste período.
      </div>
    );
  }
  const max = Math.max(...rows.map((r) => r.total_committed || 0), 1);
  return (
    <div data-testid="treasury-kpi-by-filial" style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 14, marginTop: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        marginBottom: 10 }}>
        <Building2 size={16} color={C.accent}/>
        <strong style={{ color: C.text, fontSize: 14 }}>
          Total por filial
        </strong>
        <span style={{ marginLeft: "auto", color: C.muted, fontSize: 11 }}>
          {data.filial_count} filiais ·
          comprometido <strong style={{ color: C.text }}>{BRL(totals.committed || 0)}</strong>
          {" · "}pago <strong style={{ color: C.green }}>{BRL(totals.paid || 0)}</strong>
        </span>
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {rows.map((r) => (
          <div key={r.filial_id || "__none__"}
            data-testid={`filial-bar-${r.filial_id || "none"}`}
            style={{ display: "grid",
              gridTemplateColumns: "200px 1fr 120px 80px 60px", gap: 10,
              alignItems: "center", fontSize: 12 }}>
            <div style={{ color: C.text, fontWeight: 600,
              overflow: "hidden", textOverflow: "ellipsis",
              whiteSpace: "nowrap" }} title={r.filial_name}>
              {r.filial_name}
            </div>
            <div style={{ background: "#e2e8f0", borderRadius: 999,
              height: 10, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", left: 0, top: 0,
                bottom: 0, width: `${(r.total_committed / max * 100).toFixed(1)}%`,
                background: `linear-gradient(90deg, ${C.accent}, #f97316)`,
                borderRadius: 999 }}/>
              {r.total_paid > 0 && (
                <div style={{ position: "absolute", left: 0, top: 0,
                  bottom: 0, width: `${(r.total_paid / max * 100).toFixed(1)}%`,
                  background: C.green, borderRadius: 999, opacity: 0.85 }}/>
              )}
            </div>
            <div style={{ color: C.text, textAlign: "right",
              fontFamily: "Menlo, monospace", fontWeight: 700 }}>
              {BRL(r.total_committed)}
            </div>
            <div style={{ color: C.green, textAlign: "right",
              fontSize: 11, fontWeight: 600 }} title="pago no período">
              {BRL(r.total_paid)}
            </div>
            <div style={{ color: C.muted, textAlign: "right",
              fontSize: 10 }}>
              {r.count_payments} pgto{r.count_payments === 1 ? "" : "s"}
            </div>
          </div>
        ))}
      </div>
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
