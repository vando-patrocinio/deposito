/**
 * treasury/api.js — helpers compartilhados pelos sub-componentes.
 * Centraliza todas as chamadas HTTP do módulo Tesouraria.
 */
import { client } from "@/api";

export const BRL = (v) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" })
    .format(Number(v || 0));

export const DateBR = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("pt-BR");
  } catch {
    return iso.slice(0, 10);
  }
};

export const DateTimeBR = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
};

const MONTH_NAMES_PT = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];
export const monthLabel = (ym) => {
  if (!ym) return "—";
  const [y, m] = ym.split("-");
  return `${MONTH_NAMES_PT[parseInt(m, 10) - 1]} ${y}`;
};
export const currentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
export const addMonths = (ym, delta) => {
  const [y, m] = ym.split("-").map(Number);
  const dt = new Date(y, m - 1 + delta, 1);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
};
export const monthOf = (iso) => {
  if (!iso) return "—";
  return iso.slice(0, 7);
};

export const treasuryApi = {
  // segurança/saldo
  safety: () => client.get("/treasury/safety").then((r) => r.data),
  balance: () => client.get("/treasury/balance").then((r) => r.data),
  kpis: () => client.get("/treasury/kpis").then((r) => r.data),

  // payees
  listPayees: () => client.get("/treasury/payees").then((r) => r.data),
  createPayee: (body) => client.post("/treasury/payees", body).then((r) => r.data),
  updatePayee: (id, body) => client.patch(`/treasury/payees/${id}`, body).then((r) => r.data),
  deletePayee: (id) => client.delete(`/treasury/payees/${id}`).then((r) => r.data),

  // payments
  listPayments: (params) => client.get("/treasury/payments",
      { params: params || {} }).then((r) => r.data),
  getPayment: (id) => client.get(`/treasury/payments/${id}`).then((r) => r.data),
  createPayment: (body) => client.post("/treasury/payments", body).then((r) => r.data),
  approve: (id, reason) => client.post(`/treasury/payments/${id}/approve`,
      { reason }).then((r) => r.data),
  cancel: (id, reason) => client.post(`/treasury/payments/${id}/cancel`,
      { reason }).then((r) => r.data),
  send: (id) => client.post(`/treasury/payments/${id}/send`).then((r) => r.data),
  aiReview: (id) => client.post(`/treasury/payments/${id}/ai-review`).then((r) => r.data),
  getDecision: (id) => client.get(`/treasury/payments/${id}/decision`).then((r) => r.data),
  toggleAutoEligible: (id, eligible) => client.post(
      `/treasury/payments/${id}/auto-eligible`, { eligible }).then((r) => r.data),
  markPaidManual: (id, note) => client.post(
      `/treasury/payments/${id}/mark-paid-manual`, { note }).then((r) => r.data),
  kpisByMonth: (month) => client.get("/treasury/kpis-by-month",
      { params: month ? { month } : {} }).then((r) => r.data),

  // comprovante WhatsApp
  receiptPreview: (id) => client.get(`/treasury/payments/${id}/receipt-preview`)
      .then((r) => r.data),
  sendReceipt: (id, phone) => client.post(`/treasury/payments/${id}/send-receipt`,
      { phone }).then((r) => r.data),

  // boleto
  simulateBill: (body) => client.post("/treasury/bill/simulate", body).then((r) => r.data),

  // accounts
  listAccounts: () => client.get("/treasury/accounts").then((r) => r.data),
  createAccount: (body) => client.post("/treasury/accounts", body).then((r) => r.data),
  setDefaultAccount: (id) => client.post(`/treasury/accounts/${id}/set-default`)
      .then((r) => r.data),
  deleteAccount: (id) => client.delete(`/treasury/accounts/${id}`).then((r) => r.data),

  // DDA
  listDDA: (status) => client.get("/treasury/dda/inbox",
      { params: status ? { status } : {} }).then((r) => r.data),
  createDDA: (body) => client.post("/treasury/dda/inbox", body).then((r) => r.data),
  approveDDA: (id) => client.post(`/treasury/dda/${id}/approve`).then((r) => r.data),
  rejectDDA: (id, reason) => client.post(`/treasury/dda/${id}/reject`,
      null, { params: { reason } }).then((r) => r.data),

  // recurring
  listRecurring: () => client.get("/treasury/recurring").then((r) => r.data),
  createRecurring: (body) => client.post("/treasury/recurring", body).then((r) => r.data),
  cancelRecurring: (id) => client.post(`/treasury/recurring/${id}/cancel`)
      .then((r) => r.data),
};

export const C = {
  bg: "#f8fafc", card: "#ffffff", cardSoft: "#f1f5f9",
  border: "#e2e8f0", accent: "#ff6b1a", accent2: "#a855f7",
  text: "#0f172a", muted: "#64748b",
  green: "#10b981", amber: "#f59e0b", red: "#ef4444", blue: "#3b82f6",
};

export const STATUS_META = {
  draft: { label: "Rascunho", color: C.muted },
  pending_human_approval: { label: "Aguarda CTO", color: C.amber },
  approved: { label: "Aprovado", color: C.blue },
  sent_to_bank: { label: "Enviado", color: C.blue },
  paid: { label: "Pago", color: C.green },
  blocked_risk: { label: "Bloqueado", color: C.red },
  failed: { label: "Falhou", color: C.red },
  cancelled: { label: "Cancelado", color: C.muted },
};
