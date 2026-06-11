/**
 * TreasuryPanel.jsx — IA Tesoureira (Asaas Sandbox) — Painel CTO
 * Acessível via aba "Tesouraria IA" (apenas super_admin).
 *
 * Blocos:
 *   1. Banners de segurança (sandbox, auto-approval OFF, sem secrets)
 *   2. KPIs (8 cards)
 *   3. Tabs: Fila de aprovação · Histórico · Previsão de saída
 *   4. Modal de detalhe: decisão IA + auditoria timeline + ações
 *
 * Endpoints consumidos (todos REAIS, zero mocks):
 *   GET    /api/treasury/safety
 *   GET    /api/treasury/kpis
 *   GET    /api/treasury/payments?status_eq=
 *   GET    /api/treasury/payments/{id}
 *   GET    /api/treasury/payments/{id}/decision
 *   GET    /api/treasury/payments/{id}/audit
 *   POST   /api/treasury/payments/{id}/ai-review
 *   POST   /api/treasury/payments/{id}/approve
 *   POST   /api/treasury/payments/{id}/cancel
 *   POST   /api/treasury/payments/{id}/send
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { client } from "@/api";
import {
  AlertTriangle, CheckCircle2, Clock, ShieldCheck, ShieldAlert,
  XCircle, Send, RefreshCw, Eye, Brain, Activity,
  TrendingUp, Ban, Lock,
} from "lucide-react";

const COLORS = {
  bg: "#0f1419",
  card: "#1a1f2e",
  border: "#2a3142",
  accent: "#ff6b1a",
  accent2: "#a855f7",
  text: "#e5e7eb",
  muted: "#94a3b8",
  green: "#10b981",
  amber: "#f59e0b",
  red: "#ef4444",
  blue: "#3b82f6",
};

const STATUS_META = {
  draft: { label: "Rascunho", color: COLORS.muted, icon: Clock },
  pending_human_approval: { label: "Aguarda CTO", color: COLORS.amber, icon: AlertTriangle },
  approved: { label: "Aprovado", color: COLORS.blue, icon: CheckCircle2 },
  sent_to_bank: { label: "Enviado", color: COLORS.blue, icon: Send },
  paid: { label: "Pago", color: COLORS.green, icon: CheckCircle2 },
  blocked_risk: { label: "Bloqueado (risco)", color: COLORS.red, icon: Ban },
  failed: { label: "Falhou", color: COLORS.red, icon: XCircle },
  cancelled: { label: "Cancelado", color: COLORS.muted, icon: XCircle },
  scheduled: { label: "Agendado", color: COLORS.blue, icon: Clock },
};

const DECISION_META = {
  APPROVE_AUTO: { label: "Aprovação automática", color: COLORS.green },
  REQUIRE_HUMAN: { label: "Requer CTO", color: COLORS.amber },
  BLOCK: { label: "Bloqueado", color: COLORS.red },
};

function brl(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2,
  });
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const [y, m, d] = String(iso).slice(0, 10).split("-");
    return `${d}/${m}/${y}`;
  } catch { return iso; }
}

const Card = ({ children, style, ...rest }) => (
  <div {...rest} style={{
    background: COLORS.card, border: `1px solid ${COLORS.border}`,
    borderRadius: 12, padding: 16, ...style,
  }}>{children}</div>
);

const Button = ({ children, onClick, variant = "default", disabled, testid, style }) => {
  const colors = {
    default: { bg: COLORS.border, color: COLORS.text },
    primary: { bg: COLORS.accent, color: "#fff" },
    success: { bg: COLORS.green, color: "#fff" },
    danger: { bg: COLORS.red, color: "#fff" },
    ghost: { bg: "transparent", color: COLORS.muted },
  }[variant] || { bg: COLORS.border, color: COLORS.text };
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      disabled={disabled}
      style={{
        background: colors.bg, color: colors.color,
        border: variant === "ghost" ? `1px solid ${COLORS.border}` : "none",
        borderRadius: 8, padding: "8px 14px", fontWeight: 600,
        fontSize: 13, cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1, display: "inline-flex",
        alignItems: "center", gap: 6, transition: "filter 0.15s",
        ...style,
      }}
      onMouseEnter={(e) => { if (!disabled) e.currentTarget.style.filter = "brightness(1.15)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.filter = "none"; }}
    >
      {children}
    </button>
  );
};

const Pill = ({ children, color }) => (
  <span style={{
    display: "inline-flex", alignItems: "center", gap: 4,
    background: `${color}22`, color, border: `1px solid ${color}55`,
    borderRadius: 999, padding: "3px 10px", fontSize: 11, fontWeight: 700,
    textTransform: "uppercase", letterSpacing: "0.04em",
  }}>{children}</span>
);

const KpiCard = ({ label, value, sub, color = COLORS.accent, Icon, testid }) => (
  <Card style={{ borderLeft: `3px solid ${color}` }}>
    <div data-testid={testid} style={{
      display: "flex", justifyContent: "space-between", alignItems: "flex-start",
    }}>
      <div>
        <div style={{ fontSize: 11, color: COLORS.muted, textTransform: "uppercase",
                      letterSpacing: "0.08em", fontWeight: 700, marginBottom: 6 }}>
          {label}
        </div>
        <div style={{ fontSize: 22, fontWeight: 800, color: COLORS.text, lineHeight: 1.1 }}>
          {value}
        </div>
        {sub && <div style={{ fontSize: 11, color: COLORS.muted, marginTop: 6 }}>{sub}</div>}
      </div>
      {Icon && <Icon size={18} color={color} />}
    </div>
  </Card>
);

// ─────────────── MODAL DETALHE ───────────────
function PaymentDetailModal({ paymentId, onClose, onAction }) {
  const [payment, setPayment] = useState(null);
  const [decision, setDecision] = useState(null);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, d, a] = await Promise.all([
        client.get(`/treasury/payments/${paymentId}`).then((r) => r.data),
        client.get(`/treasury/payments/${paymentId}/decision`).then((r) => r.data),
        client.get(`/treasury/payments/${paymentId}/audit`).then((r) => r.data),
      ]);
      setPayment(p);
      setDecision(d?.decision || null);
      setAudit(a?.audit || []);
    } catch (e) {
      console.error("[treasury] detail load failed", e);
    } finally { setLoading(false); }
  }, [paymentId]);

  useEffect(() => { load(); }, [load]);

  const doAction = async (action) => {
    if (!payment) return;
    if (action === "approve") {
      const reason = window.prompt("Motivo da aprovação (opcional):") || "";
      if (reason === null) return;
      setBusy(action);
      try {
        await client.post(`/treasury/payments/${paymentId}/approve`, { reason });
      } finally { setBusy(""); }
    } else if (action === "cancel") {
      if (!window.confirm("Cancelar este pagamento? Esta ação é registrada na auditoria.")) return;
      setBusy(action);
      try { await client.post(`/treasury/payments/${paymentId}/cancel`); }
      finally { setBusy(""); }
    } else if (action === "send") {
      if (!window.confirm("Enviar este pagamento ao Asaas SANDBOX? Nenhum dinheiro real será movimentado.")) return;
      setBusy(action);
      try { await client.post(`/treasury/payments/${paymentId}/send`); }
      finally { setBusy(""); }
    } else if (action === "ai-review") {
      setBusy(action);
      try { await client.post(`/treasury/payments/${paymentId}/ai-review`); }
      finally { setBusy(""); }
    }
    await load();
    onAction && onAction();
  };

  const statusMeta = payment ? (STATUS_META[payment.status] || { label: payment.status, color: COLORS.muted }) : null;
  const decisionMeta = decision ? (DECISION_META[decision.decision] || { label: decision.decision, color: COLORS.muted }) : null;
  const StatusIcon = statusMeta?.icon || Clock;
  const canApprove = payment && ["pending_human_approval", "draft", "blocked_risk"].includes(payment.status);
  const canCancel = payment && !["paid", "cancelled", "failed"].includes(payment.status);
  const canSend = payment && payment.status === "approved";

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
        backdropFilter: "blur(4px)", zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
      }}
    >
      <div
        data-testid="treasury-payment-detail-modal"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: COLORS.bg, border: `1px solid ${COLORS.border}`,
          borderRadius: 16, width: "min(900px, 100%)", maxHeight: "90vh",
          overflow: "auto", padding: 24,
        }}
      >
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: COLORS.muted }}>Carregando…</div>
        ) : !payment ? (
          <div style={{ padding: 40, textAlign: "center", color: COLORS.red }}>Pagamento não encontrado.</div>
        ) : (
          <>
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "flex-start", marginBottom: 16, gap: 12 }}>
              <div>
                <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                              letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  {payment.payment_id}
                </div>
                <div style={{ fontSize: 20, fontWeight: 800, color: COLORS.text, marginTop: 4 }}>
                  {payment.payee_name || "—"}
                </div>
                <div style={{ fontSize: 12, color: COLORS.muted, marginTop: 2 }}>
                  {payment.payee_document} · {payment.pix_key_type}: {payment.pix_key}
                </div>
              </div>
              <button
                data-testid="treasury-modal-close"
                onClick={onClose}
                style={{ background: "transparent", border: `1px solid ${COLORS.border}`,
                         color: COLORS.text, borderRadius: 8, padding: "6px 10px",
                         cursor: "pointer", fontSize: 18 }}
              >×</button>
            </div>

            {/* Status + valor */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                          gap: 12, marginBottom: 20 }}>
              <Card>
                <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                              textTransform: "uppercase" }}>Valor</div>
                <div style={{ fontSize: 22, fontWeight: 800, color: COLORS.accent, marginTop: 4 }}>
                  {brl(payment.amount_brl)}
                </div>
              </Card>
              <Card>
                <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                              textTransform: "uppercase" }}>Vencimento</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: COLORS.text, marginTop: 4 }}>
                  {fmtDate(payment.scheduled_for)}
                </div>
                <div style={{ fontSize: 11, color: COLORS.muted, marginTop: 4 }}>
                  Categoria: {payment.category || "—"}
                </div>
              </Card>
              <Card>
                <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                              textTransform: "uppercase" }}>Status</div>
                <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
                  <StatusIcon size={16} color={statusMeta.color} />
                  <Pill color={statusMeta.color}>{statusMeta.label}</Pill>
                </div>
              </Card>
            </div>

            {payment.description && (
              <Card style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                              textTransform: "uppercase", marginBottom: 4 }}>Descrição</div>
                <div style={{ color: COLORS.text, fontSize: 13 }}>{payment.description}</div>
              </Card>
            )}

            {/* Decisão IA */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 12, color: COLORS.muted, fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: "0.06em",
                            marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <Brain size={14} /> Decisão da IA Tesoureira
              </div>
              {!decision ? (
                <Card>
                  <div style={{ color: COLORS.muted, fontSize: 13 }}>
                    Sem análise IA ainda. Clique em <strong>&quot;Rodar AI Review&quot;</strong> abaixo.
                  </div>
                </Card>
              ) : (
                <Card style={{ borderLeft: `3px solid ${decisionMeta.color}` }}>
                  <div style={{ display: "flex", justifyContent: "space-between",
                                alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                    <div>
                      <Pill color={decisionMeta.color}>{decisionMeta.label}</Pill>
                      <div style={{ marginTop: 8, fontSize: 13, color: COLORS.text }}>
                        {decision.explanation || "—"}
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: 10, color: COLORS.muted, fontWeight: 700,
                                    textTransform: "uppercase" }}>Risk score</div>
                      <div style={{ fontSize: 28, fontWeight: 800,
                                    color: decision.risk_score >= 60 ? COLORS.red
                                         : decision.risk_score >= 30 ? COLORS.amber
                                         : COLORS.green }}>
                        {decision.risk_score}
                      </div>
                    </div>
                  </div>
                  <div style={{ marginTop: 12, display: "grid",
                                gridTemplateColumns: "repeat(2, 1fr)", gap: 8, fontSize: 12 }}>
                    <div>
                      <span style={{ color: COLORS.muted }}>Saldo (antes): </span>
                      <span style={{ color: COLORS.text, fontWeight: 600 }}>
                        {brl(decision.saldo_before)}
                      </span>
                    </div>
                    <div>
                      <span style={{ color: COLORS.muted }}>Média histórica: </span>
                      <span style={{ color: COLORS.text, fontWeight: 600 }}>
                        {brl(decision.historical_average)}
                      </span>
                    </div>
                  </div>
                  {(decision.risk_reasons?.length || decision.anomaly_flags?.length) ? (
                    <div style={{ marginTop: 10 }}>
                      <div style={{ fontSize: 10, color: COLORS.muted, fontWeight: 700,
                                    textTransform: "uppercase", marginBottom: 4 }}>Sinais de risco</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {[...(decision.risk_reasons || []),
                          ...(decision.anomaly_flags || [])]
                          .filter((v, i, a) => a.indexOf(v) === i)
                          .map((r, i) => (
                            <Pill key={i} color={COLORS.amber}>{r}</Pill>
                          ))}
                      </div>
                    </div>
                  ) : null}
                </Card>
              )}
            </div>

            {/* Timeline auditoria */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 12, color: COLORS.muted, fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: "0.06em",
                            marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <Activity size={14} /> Auditoria (timeline)
              </div>
              <Card data-testid="treasury-audit-timeline">
                {audit.length === 0 ? (
                  <div style={{ color: COLORS.muted, fontSize: 13 }}>Sem eventos registrados.</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {audit.map((a, i) => (
                      <div key={a.id || i} style={{
                        display: "grid", gridTemplateColumns: "20px 1fr auto",
                        gap: 12, alignItems: "center",
                        paddingBottom: 10,
                        borderBottom: i < audit.length - 1 ? `1px solid ${COLORS.border}` : "none",
                      }}>
                        <div style={{
                          width: 10, height: 10, borderRadius: "50%",
                          background: a.action.includes("failed") || a.action.includes("blocked") ? COLORS.red
                                    : a.action.includes("approved") || a.action.includes("DONE") || a.action.includes("APPROVE") ? COLORS.green
                                    : a.action.includes("sent") ? COLORS.blue
                                    : COLORS.muted,
                        }} />
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>
                            {a.action}
                          </div>
                          <div style={{ fontSize: 11, color: COLORS.muted }}>
                            por {a.actor}
                          </div>
                        </div>
                        <div style={{ fontSize: 11, color: COLORS.muted }}>
                          {fmtDateTime(a.created_at)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>

            {/* Ações */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" }}>
              <Button variant="ghost" onClick={() => doAction("ai-review")}
                disabled={busy === "ai-review"} testid="treasury-action-ai-review">
                <Brain size={14} /> {busy === "ai-review" ? "Analisando…" : "Rodar AI Review"}
              </Button>
              {canApprove && (
                <Button variant="success" onClick={() => doAction("approve")}
                  disabled={!!busy} testid="treasury-action-approve">
                  <CheckCircle2 size={14} /> {busy === "approve" ? "Aprovando…" : "Aprovar"}
                </Button>
              )}
              {canSend && (
                <Button variant="primary" onClick={() => doAction("send")}
                  disabled={!!busy} testid="treasury-action-send">
                  <Send size={14} /> {busy === "send" ? "Enviando…" : "Enviar ao Asaas Sandbox"}
                </Button>
              )}
              {canCancel && (
                <Button variant="danger" onClick={() => doAction("cancel")}
                  disabled={!!busy} testid="treasury-action-cancel">
                  <Ban size={14} /> {busy === "cancel" ? "Cancelando…" : "Bloquear / Cancelar"}
                </Button>
              )}
            </div>

            {payment.last_error && (
              <Card style={{ marginTop: 16, borderLeft: `3px solid ${COLORS.red}` }}>
                <div style={{ fontSize: 11, color: COLORS.red, fontWeight: 700,
                              textTransform: "uppercase", marginBottom: 4 }}>
                  Último erro
                </div>
                <div style={{ fontSize: 12, color: COLORS.text, fontFamily: "monospace" }}>
                  {payment.last_error.message || JSON.stringify(payment.last_error)}
                </div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─────────────── PAGE ───────────────
export default function TreasuryPanel() {
  const [safety, setSafety] = useState(null);
  const [kpis, setKpis] = useState(null);
  const [payments, setPayments] = useState([]);
  const [tab, setTab] = useState("queue"); // queue | history | forecast
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadAll = useCallback(async () => {
    setRefreshing(true);
    try {
      const [s, k, p] = await Promise.all([
        client.get("/treasury/safety").then((r) => r.data),
        client.get("/treasury/kpis").then((r) => r.data),
        client.get("/treasury/payments", { params: { limit: 200 } }).then((r) => r.data),
      ]);
      setSafety(s);
      setKpis(k);
      setPayments(p?.payments || []);
    } catch (e) {
      console.error("[treasury] load failed", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const queueRows = useMemo(() =>
    payments.filter((p) =>
      ["pending_human_approval", "draft", "approved", "blocked_risk"].includes(p.status)
    ), [payments]);

  const historyRows = useMemo(() =>
    payments.filter((p) =>
      ["paid", "sent_to_bank", "failed", "cancelled"].includes(p.status)
    ), [payments]);

  if (loading) {
    return (
      <div style={{ padding: 40, color: COLORS.muted, textAlign: "center" }}
           data-testid="treasury-loading">
        Carregando IA Tesoureira…
      </div>
    );
  }

  return (
    <div data-testid="treasury-panel" style={{
      padding: "0 4px", display: "flex", flexDirection: "column", gap: 16,
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: COLORS.text,
                       letterSpacing: "-0.02em", margin: 0,
                       display: "flex", alignItems: "center", gap: 10 }}>
            <Brain size={26} color={COLORS.accent2} />
            IA Tesoureira
            <Pill color={COLORS.accent2}>SANDBOX</Pill>
          </h1>
          <div style={{ fontSize: 12, color: COLORS.muted, marginTop: 4 }}>
            Gateway Asaas Sandbox · Aprovação humana obrigatória · Zero dinheiro real
          </div>
        </div>
        <Button variant="ghost" onClick={loadAll} disabled={refreshing}
                testid="treasury-refresh-btn">
          <RefreshCw size={14} style={{
            animation: refreshing ? "spin 1s linear infinite" : "none",
          }} />
          Atualizar
        </Button>
      </div>

      {/* Banners de segurança */}
      {safety && (
        <Card data-testid="treasury-safety-banner" style={{
          borderLeft: `3px solid ${safety.auto_approval_enabled ? COLORS.red : COLORS.green}`,
        }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16,
                        alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <ShieldCheck size={16} color={COLORS.green} />
                <span style={{ fontSize: 12, color: COLORS.text }}>
                  Ambiente: <strong>{safety.environment?.toUpperCase()}</strong>
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {safety.auto_approval_enabled
                  ? <ShieldAlert size={16} color={COLORS.red} />
                  : <Lock size={16} color={COLORS.green} />}
                <span style={{ fontSize: 12, color: COLORS.text }}>
                  Auto-aprovação: <strong>
                    {safety.auto_approval_enabled ? "ON ⚠️" : "OFF"}
                  </strong>
                </span>
              </div>
              <div style={{ fontSize: 12, color: COLORS.muted }}>
                Auto-cap diário: <strong style={{ color: COLORS.text }}>
                  {brl(safety.daily_auto_cap_brl)}</strong> ·
                Acima de <strong style={{ color: COLORS.text }}>
                  {brl(safety.human_required_above_brl)}</strong> exige CTO ·
                Anomalia &gt; <strong style={{ color: COLORS.text }}>
                  {safety.anomaly_threshold_pct}%</strong>
              </div>
            </div>
            <Pill color={safety.has_asaas_key ? COLORS.green : COLORS.amber}>
              {safety.has_asaas_key ? "Asaas key OK" : "Asaas key não configurada"}
            </Pill>
          </div>
        </Card>
      )}

      {/* KPIs */}
      {kpis && (
        <div data-testid="treasury-kpis"
             style={{ display: "grid", gap: 12,
                      gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          <KpiCard label="Agendado hoje" value={brl(kpis.today_scheduled)}
            color={COLORS.blue} Icon={Clock} testid="kpi-today-scheduled" />
          <KpiCard label="Pago hoje" value={brl(kpis.today_paid)}
            color={COLORS.green} Icon={CheckCircle2} testid="kpi-today-paid" />
          <KpiCard label="Aguarda CTO" value={brl(kpis.pending_approval)}
            color={COLORS.amber} Icon={AlertTriangle} testid="kpi-pending" />
          <KpiCard label="Bloqueado (risco)" value={brl(kpis.blocked_risk)}
            color={COLORS.red} Icon={Ban} testid="kpi-blocked" />
          <KpiCard label="Falhou" value={brl(kpis.failed)}
            color={COLORS.red} Icon={XCircle} testid="kpi-failed" />
          <KpiCard label="Previsão 7d"
            value={brl(kpis.outflow_forecast?.["7d"])}
            color={COLORS.accent} Icon={TrendingUp} testid="kpi-forecast-7" />
          <KpiCard label="Previsão 15d"
            value={brl(kpis.outflow_forecast?.["15d"])}
            color={COLORS.accent} Icon={TrendingUp} testid="kpi-forecast-15" />
          <KpiCard label="Previsão 30d"
            value={brl(kpis.outflow_forecast?.["30d"])}
            color={COLORS.accent} Icon={TrendingUp} testid="kpi-forecast-30" />
        </div>
      )}

      {/* Saldo Asaas + breakdown */}
      {kpis && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                      gap: 12 }}>
          <Card>
            <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                          textTransform: "uppercase" }}>
              Saldo Asaas (sandbox)
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: COLORS.text, marginTop: 4 }}>
              {kpis.saldo_asaas?.ok
                ? brl(kpis.saldo_asaas?.balance || 0)
                : "Indisponível"}
            </div>
            <div style={{ fontSize: 11, color: COLORS.muted, marginTop: 4 }}>
              {kpis.saldo_asaas?.ok ? "Live API" : "ASAAS_API_KEY ausente"}
            </div>
          </Card>
          <Card>
            <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                          textTransform: "uppercase", marginBottom: 8 }}>
              Por categoria (pagos)
            </div>
            {Object.keys(kpis.by_category || {}).length === 0
              ? <div style={{ fontSize: 12, color: COLORS.muted }}>Sem dados</div>
              : Object.entries(kpis.by_category).slice(0, 5).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between",
                                       fontSize: 12, padding: "4px 0",
                                       borderBottom: `1px solid ${COLORS.border}` }}>
                  <span style={{ color: COLORS.muted }}>{k}</span>
                  <span style={{ color: COLORS.text, fontWeight: 600 }}>{brl(v)}</span>
                </div>
              ))}
          </Card>
          <Card>
            <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700,
                          textTransform: "uppercase", marginBottom: 8 }}>
              Por favorecido (pagos)
            </div>
            {Object.keys(kpis.by_payee || {}).length === 0
              ? <div style={{ fontSize: 12, color: COLORS.muted }}>Sem dados</div>
              : Object.entries(kpis.by_payee).slice(0, 5).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between",
                                       fontSize: 12, padding: "4px 0",
                                       borderBottom: `1px solid ${COLORS.border}` }}>
                  <span style={{ color: COLORS.muted }}>{k}</span>
                  <span style={{ color: COLORS.text, fontWeight: 600 }}>{brl(v)}</span>
                </div>
              ))}
          </Card>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, borderBottom: `1px solid ${COLORS.border}`,
                    paddingBottom: 4 }}>
        {[
          { id: "queue", label: `Fila de Aprovação (${queueRows.length})` },
          { id: "history", label: `Histórico (${historyRows.length})` },
          { id: "forecast", label: "Previsão de Saída" },
        ].map((t) => (
          <button
            key={t.id}
            data-testid={`treasury-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            style={{
              background: "transparent", border: "none",
              color: tab === t.id ? COLORS.accent : COLORS.muted,
              borderBottom: `2px solid ${tab === t.id ? COLORS.accent : "transparent"}`,
              padding: "10px 14px", cursor: "pointer", fontWeight: 700,
              fontSize: 13, marginBottom: -1,
            }}
          >{t.label}</button>
        ))}
      </div>

      {/* Conteúdo das tabs */}
      {tab === "queue" && (
        <PaymentsTable rows={queueRows} onOpen={setSelectedId} testid="treasury-queue-table" />
      )}
      {tab === "history" && (
        <PaymentsTable rows={historyRows} onOpen={setSelectedId} testid="treasury-history-table" />
      )}
      {tab === "forecast" && kpis && (
        <ForecastView forecast={kpis.outflow_forecast} payments={payments} />
      )}

      {selectedId && (
        <PaymentDetailModal
          paymentId={selectedId}
          onClose={() => setSelectedId(null)}
          onAction={loadAll}
        />
      )}

      <style>{`@keyframes spin { from {transform:rotate(0)} to {transform:rotate(360deg)} }`}</style>
    </div>
  );
}

// ─────────────── TABELA ───────────────
function PaymentsTable({ rows, onOpen, testid }) {
  if (!rows.length) {
    return (
      <Card data-testid={`${testid}-empty`}>
        <div style={{ color: COLORS.muted, textAlign: "center", padding: 20 }}>
          Nenhum pagamento nesta lista.
        </div>
      </Card>
    );
  }
  return (
    <Card data-testid={testid} style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead style={{ background: COLORS.bg }}>
            <tr>
              {["Favorecido", "Documento", "Valor", "Vencimento", "Categoria",
                "Status", "IA", "Risco", "Ações"].map((h) => (
                <th key={h} style={{
                  textAlign: "left", padding: "10px 14px", fontSize: 11,
                  fontWeight: 700, color: COLORS.muted, textTransform: "uppercase",
                  letterSpacing: "0.06em", borderBottom: `1px solid ${COLORS.border}`,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const s = STATUS_META[p.status] || { label: p.status, color: COLORS.muted };
              const d = p.ai_decision ? DECISION_META[p.ai_decision] : null;
              return (
                <tr key={p.payment_id} data-testid={`treasury-row-${p.payment_id}`}
                    style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                  <td style={{ padding: "12px 14px", color: COLORS.text, fontWeight: 600 }}>
                    {p.payee_name || "—"}
                  </td>
                  <td style={{ padding: "12px 14px", color: COLORS.muted, fontSize: 12 }}>
                    {p.payee_document || "—"}
                  </td>
                  <td style={{ padding: "12px 14px", color: COLORS.accent, fontWeight: 700 }}>
                    {brl(p.amount_brl)}
                  </td>
                  <td style={{ padding: "12px 14px", color: COLORS.text }}>
                    {fmtDate(p.scheduled_for)}
                  </td>
                  <td style={{ padding: "12px 14px", color: COLORS.muted, fontSize: 12 }}>
                    {p.category || "—"}
                  </td>
                  <td style={{ padding: "12px 14px" }}>
                    <Pill color={s.color}>{s.label}</Pill>
                  </td>
                  <td style={{ padding: "12px 14px" }}>
                    {d ? <Pill color={d.color}>{d.label}</Pill>
                       : <span style={{ color: COLORS.muted, fontSize: 11 }}>—</span>}
                  </td>
                  <td style={{ padding: "12px 14px", color: COLORS.text, fontWeight: 700 }}>
                    {p.ai_risk_score ?? "—"}
                  </td>
                  <td style={{ padding: "12px 14px" }}>
                    <Button variant="ghost" onClick={() => onOpen(p.payment_id)}
                            testid={`treasury-detail-${p.payment_id}`}
                            style={{ padding: "6px 10px", fontSize: 12 }}>
                      <Eye size={12} /> Detalhar
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ─────────────── PREVISÃO ───────────────
function ForecastView({ forecast, payments }) {
  const upcoming = (payments || [])
    .filter((p) => ["approved", "scheduled", "pending_human_approval"].includes(p.status))
    .sort((a, b) => (a.scheduled_for || "").localeCompare(b.scheduled_for || ""))
    .slice(0, 15);

  const max = Math.max(forecast?.["7d"] || 0, forecast?.["15d"] || 0,
                       forecast?.["30d"] || 0, 1);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}
         data-testid="treasury-forecast-view">
      <Card>
        <div style={{ fontSize: 12, color: COLORS.muted, fontWeight: 700,
                      textTransform: "uppercase", marginBottom: 12 }}>
          Saída prevista
        </div>
        {["7d", "15d", "30d"].map((k) => {
          const v = forecast?.[k] || 0;
          const pct = (v / max) * 100;
          return (
            <div key={k} style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                            fontSize: 12, marginBottom: 4 }}>
                <span style={{ color: COLORS.muted }}>Próximos {k}</span>
                <span style={{ color: COLORS.text, fontWeight: 700 }}>{brl(v)}</span>
              </div>
              <div style={{ height: 8, background: COLORS.border, borderRadius: 999 }}>
                <div style={{
                  height: "100%", width: `${pct}%`, background: COLORS.accent,
                  borderRadius: 999, transition: "width 0.3s",
                }} />
              </div>
            </div>
          );
        })}
      </Card>
      <Card>
        <div style={{ fontSize: 12, color: COLORS.muted, fontWeight: 700,
                      textTransform: "uppercase", marginBottom: 12 }}>
          Próximos vencimentos
        </div>
        {upcoming.length === 0
          ? <div style={{ color: COLORS.muted, fontSize: 13 }}>Sem pagamentos previstos.</div>
          : (
            <div style={{ maxHeight: 320, overflow: "auto" }}>
              {upcoming.map((p) => (
                <div key={p.payment_id} style={{
                  display: "flex", justifyContent: "space-between",
                  padding: "8px 0", borderBottom: `1px solid ${COLORS.border}`,
                  fontSize: 12,
                }}>
                  <div>
                    <div style={{ color: COLORS.text, fontWeight: 600 }}>{p.payee_name}</div>
                    <div style={{ color: COLORS.muted, fontSize: 11 }}>
                      {fmtDate(p.scheduled_for)} · {p.category || "—"}
                    </div>
                  </div>
                  <div style={{ color: COLORS.accent, fontWeight: 700 }}>
                    {brl(p.amount_brl)}
                  </div>
                </div>
              ))}
            </div>
          )}
      </Card>
    </div>
  );
}
