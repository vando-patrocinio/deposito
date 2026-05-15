import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, inputStyle } from "@/ui";
import {
  Plus, Pencil, Trash2, CheckCircle2, AlertCircle, Calendar,
  ArrowUp, ArrowDown,
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend,
} from "recharts";
import AnalyticsChart from "@/FinanceiroAnalyticsChart";

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
  });

// =========================================================================
// CONTAS A PAGAR
// =========================================================================
export function BillsTab() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState({ status: "" });
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [paying, setPaying] = useState(null);
  const [refs, setRefs] = useState({ suppliers: [], categories: [],
                                       payment_methods: [], cash_accounts: [] });

  async function reload() {
    setLoading(true);
    try {
      const params = filter.status ? `?status=${filter.status}` : "";
      const r = await api._client.get(`/financeiro/bills${params}`)
                          .then((r) => r.data);
      setItems(r);
    } finally { setLoading(false); }
  }
  async function loadRefs() {
    const [s, c, pm, ca] = await Promise.all([
      api.finSuppliersList(true), api.finCategoriesList(true),
      api.finPaymentMethodsList(true), api.finCashAccountsList(true),
    ]);
    setRefs({ suppliers: s, categories: c, payment_methods: pm,
              cash_accounts: ca });
  }
  useEffect(() => { reload(); }, [filter.status]); // eslint-disable-line
  useEffect(() => { loadRefs(); }, []);

  async function onDelete(b) {
    if (!window.confirm(`Excluir "${b.description}"? Estorna a movimentação se já paga.`))
      return;
    await api._client.delete(`/financeiro/bills/${b.id}`);
    reload();
    loadRefs();
  }

  const totals = useMemo(() => ({
    pending: items.filter((b) => b.status === "pending")
                  .reduce((s, b) => s + (b.amount || 0), 0),
    overdue: items.filter((b) => b.status === "overdue")
                  .reduce((s, b) => s + (b.amount || 0), 0),
    paid: items.filter((b) => b.status === "paid")
                .reduce((s, b) => s + (b.paid_amount || b.amount || 0), 0),
  }), [items]);

  return (
    <Card title="Contas a Pagar">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8,
                    marginBottom: 14, justifyContent: "space-between",
                    alignItems: "center" }}>
        <div style={{ display: "flex", gap: 8 }}>
          {[
            { v: "", l: "Todas" },
            { v: "pending", l: "Pendentes" },
            { v: "overdue", l: "Vencidas" },
            { v: "paid", l: "Pagas" },
            { v: "cancelled", l: "Canceladas" },
          ].map((f) => (
            <button key={f.v}
              onClick={() => setFilter({ status: f.v })}
              data-testid={`bills-filter-${f.v || "all"}`}
              style={{
                padding: "6px 12px", borderRadius: 8,
                background: filter.status === f.v ? "#0f172a" : "#f1f5f9",
                color: filter.status === f.v ? "#fff" : "#64748b",
                fontSize: 12, fontWeight: 600, border: "none",
                cursor: "pointer",
              }}>
              {f.l}
            </button>
          ))}
        </div>
        <Button onClick={() => setEditing({})}
                data-testid="bills-new-btn">
          <Plus size={14} /> Nova conta
        </Button>
      </div>
      <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(3,1fr)",
                    gap: 10, marginBottom: 14 }}>
        <Chip label="Pendentes" value={fmtMoney(totals.pending)}
              color="#64748b" />
        <Chip label="Vencidas" value={fmtMoney(totals.overdue)}
              color="#dc2626" />
        <Chip label="Pagas" value={fmtMoney(totals.paid)}
              color="#16a34a" />
      </div>

      {loading ? <Loading /> : items.length === 0 ? (
        <Empty msg="Nenhuma conta. Clique em 'Nova conta'." />
      ) : (
        <BillsTable items={items} refs={refs}
                    onEdit={setEditing} onPay={setPaying}
                    onDelete={onDelete} />
      )}

      {editing !== null && (
        <BillForm initial={editing} refs={refs}
                  onClose={() => setEditing(null)}
                  onSaved={() => { setEditing(null); reload(); }} />
      )}
      {paying !== null && (
        <PayBillForm bill={paying} refs={refs}
                     onClose={() => setPaying(null)}
                     onSaved={() => { setPaying(null); reload(); loadRefs(); }} />
      )}
    </Card>
  );
}

function BillsTable({ items, refs, onEdit, onPay, onDelete }) {
  const supById = Object.fromEntries(refs.suppliers.map((s) => [s.id, s.name]));
  return (
    <div style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                  overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse",
                      fontSize: 13 }}>
        <thead>
          <tr style={{ background: "#f8fafc" }}>
            {["Descrição", "Vencimento", "Fornecedor", "Valor", "Status", ""]
              .map((h, i) => (
              <th key={i} style={{
                padding: "10px 14px", textAlign: i === 3 ? "right" : "left",
                fontSize: 11, fontWeight: 700, color: "#475569",
                textTransform: "uppercase", letterSpacing: 0.4,
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.id} style={{ borderTop: "1px solid #f1f5f9" }}
                data-testid={`bill-row-${b.id}`}>
              <td style={{ padding: "10px 14px" }}>{b.description}</td>
              <td style={{ padding: "10px 14px",
                            color: b.status === "overdue" ? "#dc2626" : "#0f172a" }}>
                {b.due_date}
              </td>
              <td style={{ padding: "10px 14px", color: "#64748b" }}>
                {supById[b.supplier_id] || "—"}
              </td>
              <td style={{ padding: "10px 14px", textAlign: "right",
                            fontWeight: 600 }}>
                {fmtMoney(b.amount)}
              </td>
              <td style={{ padding: "10px 14px" }}>
                <BillStatusBadge status={b.status} />
              </td>
              <td style={{ padding: "8px 10px", textAlign: "right",
                            whiteSpace: "nowrap" }}>
                {b.status !== "paid" && b.status !== "cancelled" && (
                  <Button variant="ghost" size="sm"
                          onClick={() => onPay(b)}
                          data-testid={`bill-pay-${b.id}`}>
                    <CheckCircle2 size={12} color="#16a34a" />
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => onEdit(b)}
                        data-testid={`bill-edit-${b.id}`}>
                  <Pencil size={12} />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => onDelete(b)}
                        data-testid={`bill-del-${b.id}`}>
                  <Trash2 size={12} color="#dc2626" />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BillStatusBadge({ status }) {
  const map = {
    pending: { bg: "#fef9c3", fg: "#854d0e", label: "Pendente" },
    overdue: { bg: "#fee2e2", fg: "#991b1b", label: "Vencida" },
    paid: { bg: "#dcfce7", fg: "#166534", label: "Paga" },
    cancelled: { bg: "#f1f5f9", fg: "#64748b", label: "Cancelada" },
  };
  const s = map[status] || map.pending;
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 999,
      background: s.bg, color: s.fg, fontSize: 11, fontWeight: 700,
    }}>{s.label}</span>
  );
}

function BillForm({ initial, refs, onClose, onSaved }) {
  const isEdit = !!initial?.id;
  const [form, setForm] = useState({
    description: initial?.description || "",
    amount: initial?.amount || "",
    due_date: initial?.due_date || new Date().toISOString().slice(0, 10),
    supplier_id: initial?.supplier_id || "",
    category_id: initial?.category_id || "",
    payment_method_id: initial?.payment_method_id || "",
    cash_account_id: initial?.cash_account_id || "",
    document_number: initial?.document_number || "",
    notes: initial?.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    setBusy(true); setErr("");
    try {
      const payload = { ...form, amount: Number(form.amount) };
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "") delete payload[k];
      });
      if (isEdit) {
        await api._client.put(`/financeiro/bills/${initial.id}`, payload);
      } else {
        await api._client.post(`/financeiro/bills`, payload);
      }
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} title={isEdit ? "Editar conta" : "Nova conta"}
           testId="bill-modal">
      <Field label="Descrição *">
        <input style={inputStyle} value={form.description}
               onChange={(e) => setForm({ ...form, description: e.target.value })}
               data-testid="bill-fld-description" />
      </Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Valor (R$) *">
          <input style={inputStyle} type="number" step="0.01"
                 value={form.amount}
                 onChange={(e) => setForm({ ...form, amount: e.target.value })}
                 data-testid="bill-fld-amount" />
        </Field>
        <Field label="Vencimento *">
          <input style={inputStyle} type="date" value={form.due_date}
                 onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                 data-testid="bill-fld-due-date" />
        </Field>
      </div>
      <Field label="Fornecedor">
        <select style={inputStyle} value={form.supplier_id}
                onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}
                data-testid="bill-fld-supplier">
          <option value="">— Nenhum —</option>
          {refs.suppliers.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </Field>
      <Field label="Categoria">
        <select style={inputStyle} value={form.category_id}
                onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
          <option value="">— Nenhuma —</option>
          {refs.categories.filter((c) => c.kind !== "income")
                          .map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </Field>
      <Field label="Nº Documento">
        <input style={inputStyle} value={form.document_number}
               onChange={(e) => setForm({ ...form, document_number: e.target.value })} />
      </Field>
      <Field label="Notas">
        <textarea style={{ ...inputStyle, minHeight: 70, resize: "vertical" }}
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </Field>
      {err && <ErrBox msg={err} />}
      <ModalActions onClose={onClose} onSave={save} busy={busy}
                    testId="bill-save-btn" />
    </Modal>
  );
}

function PayBillForm({ bill, refs, onClose, onSaved }) {
  const [form, setForm] = useState({
    cash_account_id: bill.cash_account_id
      || (refs.cash_accounts[0]?.id || ""),
    payment_method_id: bill.payment_method_id || "",
    paid_amount: bill.amount,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function pay() {
    setBusy(true); setErr("");
    try {
      await api._client.post(`/financeiro/bills/${bill.id}/pay`, {
        ...form, paid_amount: Number(form.paid_amount),
      });
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }
  return (
    <Modal onClose={onClose} title={`Pagar: ${bill.description}`}
           testId="pay-modal">
      <Field label="Conta caixa *">
        <select style={inputStyle} value={form.cash_account_id}
                onChange={(e) => setForm({ ...form, cash_account_id: e.target.value })}
                data-testid="pay-fld-cash-account">
          <option value="">— Selecione —</option>
          {refs.cash_accounts.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({fmtMoney(c.current_balance)})
            </option>
          ))}
        </select>
      </Field>
      <Field label="Método">
        <select style={inputStyle} value={form.payment_method_id}
                onChange={(e) => setForm({ ...form, payment_method_id: e.target.value })}>
          <option value="">— Nenhum —</option>
          {refs.payment_methods.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </Field>
      <Field label="Valor pago (R$)">
        <input style={inputStyle} type="number" step="0.01"
               value={form.paid_amount}
               onChange={(e) => setForm({ ...form, paid_amount: e.target.value })}
               data-testid="pay-fld-amount" />
      </Field>
      {err && <ErrBox msg={err} />}
      <ModalActions onClose={onClose} onSave={pay} busy={busy}
                    saveLabel="Confirmar pagamento"
                    testId="pay-confirm-btn" />
    </Modal>
  );
}

// =========================================================================
// FLUXO DE CAIXA — gráfico + lançamentos
// =========================================================================
export function CashFlowTab() {
  const [period, setPeriod] = useState(30);
  const [data, setData] = useState(null);
  const [moves, setMoves] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [refs, setRefs] = useState({ cash_accounts: [], categories: [],
                                       suppliers: [], payment_methods: [] });

  async function reload() {
    setLoading(true);
    const now = new Date();
    const from = new Date(now); from.setDate(from.getDate() - period);
    const fromStr = from.toISOString().slice(0, 10);
    const toStr = now.toISOString().slice(0, 10);
    try {
      const [cf, ms] = await Promise.all([
        api._client.get(`/financeiro/cashflow?from_date=${fromStr}&to_date=${toStr}`)
                  .then((r) => r.data),
        api._client.get(`/financeiro/movements?from_date=${fromStr}&to_date=${toStr}&limit=100`)
                  .then((r) => r.data),
      ]);
      setData(cf); setMoves(ms);
    } finally { setLoading(false); }
  }
  useEffect(() => { reload(); }, [period]); // eslint-disable-line
  useEffect(() => {
    Promise.all([
      api.finCashAccountsList(true), api.finCategoriesList(true),
      api.finSuppliersList(true), api.finPaymentMethodsList(true),
    ]).then(([ca, cat, sp, pm]) =>
      setRefs({ cash_accounts: ca, categories: cat,
                suppliers: sp, payment_methods: pm }));
  }, []);

  async function onDelete(m) {
    if (m.reference_type === "bill") {
      window.alert("Estorne pela conta a pagar.");
      return;
    }
    if (!window.confirm("Excluir lançamento? Saldo é estornado.")) return;
    await api._client.delete(`/financeiro/movements/${m.id}`);
    reload();
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <AnalyticsChart />
      <Card title="Fluxo de Caixa">
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 10 }}>
          <div style={{ display: "flex", gap: 6 }}>
            {[7, 30, 90].map((p) => (
              <button key={p} onClick={() => setPeriod(p)}
                data-testid={`cashflow-period-${p}`}
                style={{
                  padding: "6px 12px", borderRadius: 8,
                  background: period === p ? "#0f172a" : "#f1f5f9",
                  color: period === p ? "#fff" : "#64748b",
                  fontSize: 12, fontWeight: 600,
                  border: "none", cursor: "pointer",
                }}>{p}d</button>
            ))}
          </div>
          <Button onClick={() => setAdding(true)}
                  data-testid="mov-new-btn">
            <Plus size={14} /> Lançamento
          </Button>
        </div>
        {loading || !data ? <Loading /> : (
          <>
            <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(4,1fr)",
                          gap: 10, marginBottom: 14 }}>
              <Chip label="Saldo atual"
                    value={fmtMoney(data.current_balance)}
                    color="#0f172a" highlight />
              <Chip label="Entradas" value={fmtMoney(data.totals.income)}
                    color="#16a34a" icon={ArrowUp} />
              <Chip label="Saídas" value={fmtMoney(data.totals.expense)}
                    color="#dc2626" icon={ArrowDown} />
              <Chip label="Resultado" value={fmtMoney(data.totals.net)}
                    color={data.totals.net >= 0 ? "#16a34a" : "#dc2626"} />
            </div>
            <div style={{ height: 280, marginTop: 6 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }}
                          tickFormatter={(v) => `R$${v}`} />
                  <Tooltip formatter={(v) => fmtMoney(v)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="income" name="Entradas" fill="#16a34a" />
                  <Bar dataKey="expense" name="Saídas" fill="#dc2626" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </Card>

      <Card title="Últimos lançamentos">
        {moves.length === 0 ? (
          <Empty msg="Nenhum lançamento no período." />
        ) : (
          <div style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                        overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f8fafc" }}>
                  {["Data", "Tipo", "Descrição", "Valor", ""].map((h, i) => (
                    <th key={i} style={{
                      padding: "10px 14px",
                      textAlign: i === 3 ? "right" : "left",
                      fontSize: 11, fontWeight: 700, color: "#475569",
                      textTransform: "uppercase", letterSpacing: 0.4,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {moves.map((m) => (
                  <tr key={m.id} style={{ borderTop: "1px solid #f1f5f9" }}
                      data-testid={`mov-row-${m.id}`}>
                    <td style={{ padding: "10px 14px" }}>{m.date}</td>
                    <td style={{ padding: "10px 14px" }}>
                      {m.type === "income"
                        ? <span style={{ color: "#16a34a", fontWeight: 600 }}>
                            <ArrowUp size={12} /> Entrada
                          </span>
                        : <span style={{ color: "#dc2626", fontWeight: 600 }}>
                            <ArrowDown size={12} /> Saída
                          </span>}
                    </td>
                    <td style={{ padding: "10px 14px" }}>{m.description}</td>
                    <td style={{ padding: "10px 14px", textAlign: "right",
                                  fontWeight: 600,
                                  color: m.type === "income" ? "#16a34a" : "#dc2626" }}>
                      {fmtMoney(m.amount)}
                    </td>
                    <td style={{ padding: "8px 14px", textAlign: "right" }}>
                      <Button variant="ghost" size="sm"
                              onClick={() => onDelete(m)}
                              data-testid={`mov-del-${m.id}`}>
                        <Trash2 size={12} color="#dc2626" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {adding && <MovementForm refs={refs}
        onClose={() => setAdding(false)}
        onSaved={() => { setAdding(false); reload(); }} />}
    </div>
  );
}

function MovementForm({ refs, onClose, onSaved }) {
  const [form, setForm] = useState({
    type: "income", date: new Date().toISOString().slice(0, 10),
    amount: "", cash_account_id: refs.cash_accounts[0]?.id || "",
    description: "", category_id: "", payment_method_id: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function save() {
    setBusy(true); setErr("");
    try {
      const payload = { ...form, amount: Number(form.amount) };
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "") delete payload[k];
      });
      await api._client.post(`/financeiro/movements`, payload);
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }
  return (
    <Modal onClose={onClose} title="Novo lançamento" testId="mov-modal">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Tipo *">
          <select style={inputStyle} value={form.type}
                  onChange={(e) => setForm({ ...form, type: e.target.value })}
                  data-testid="mov-fld-type">
            <option value="income">Entrada</option>
            <option value="expense">Saída</option>
          </select>
        </Field>
        <Field label="Data *">
          <input style={inputStyle} type="date" value={form.date}
                 onChange={(e) => setForm({ ...form, date: e.target.value })} />
        </Field>
      </div>
      <Field label="Valor *">
        <input style={inputStyle} type="number" step="0.01"
               value={form.amount}
               onChange={(e) => setForm({ ...form, amount: e.target.value })}
               data-testid="mov-fld-amount" />
      </Field>
      <Field label="Conta caixa *">
        <select style={inputStyle} value={form.cash_account_id}
                onChange={(e) => setForm({ ...form, cash_account_id: e.target.value })}
                data-testid="mov-fld-cash-account">
          {refs.cash_accounts.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({fmtMoney(c.current_balance)})
            </option>
          ))}
        </select>
      </Field>
      <Field label="Descrição *">
        <input style={inputStyle} value={form.description}
               onChange={(e) => setForm({ ...form, description: e.target.value })}
               data-testid="mov-fld-description" />
      </Field>
      <Field label="Categoria">
        <select style={inputStyle} value={form.category_id}
                onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
          <option value="">— Nenhuma —</option>
          {refs.categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </Field>
      {err && <ErrBox msg={err} />}
      <ModalActions onClose={onClose} onSave={save} busy={busy}
                    testId="mov-save-btn" />
    </Modal>
  );
}

// =========================================================================
// RECEBIMENTOS (Atlaz Financeiro)
// =========================================================================
export function ReceivablesTab() {
  const [stats, setStats] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [busy, setBusy] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");
  const [probe, setProbe] = useState(null);

  async function reload() {
    const [s, inv] = await Promise.all([
      api._client.get("/atlaz-financeiro/stats").then((r) => r.data),
      api._client.get("/atlaz-financeiro/invoices?limit=200")
                .then((r) => r.data).catch(() => ({ items: [], total: 0 })),
    ]);
    setStats(s); setInvoices(inv.items || []);
  }
  useEffect(() => { reload(); }, []);

  async function syncNow() {
    setBusy(true); setSyncMsg("");
    try {
      const r = await api._client.post("/atlaz-financeiro/sync-now")
                              .then((r) => r.data);
      setSyncMsg(
        `Endpoints OK: ${r.endpoints_ok.join(", ") || "nenhum"} · ` +
        `inseridos: ${r.inserted} · atualizados: ${r.updated}` +
        (r.errors?.length ? ` · erros: ${r.errors.length}` : "")
      );
      reload();
    } catch (e) {
      setSyncMsg("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }

  async function runProbe() {
    setBusy(true);
    try {
      const r = await api._client.get("/atlaz-financeiro/probe")
                              .then((r) => r.data);
      setProbe(r);
    } catch (e) {
      setSyncMsg("Erro probe: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card title="Recebimentos dos Assinantes (Atlaz)">
        <p style={{ color: "#64748b", fontSize: 13, marginTop: 0 }}>
          Sincroniza cobranças, boletos e pagamentos da API Atlaz V2.
          Configure o token em <strong>Configurações → Conexões → Atlaz V2</strong>.
        </p>
        <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
          <Button onClick={syncNow} disabled={busy}
                  data-testid="receivables-sync-btn">
            <Calendar size={14} /> {busy ? "Sincronizando…" : "Sincronizar agora"}
          </Button>
          <Button variant="secondary" onClick={runProbe} disabled={busy}
                  data-testid="receivables-probe-btn">
            <AlertCircle size={14} /> Testar endpoints
          </Button>
          {stats?.last_sync && (
            <span style={{ fontSize: 12, color: "#64748b",
                            alignSelf: "center" }}>
              Última sync: {new Date(stats.last_sync).toLocaleString("pt-BR")}
            </span>
          )}
        </div>
        {syncMsg && (
          <div style={{ padding: 10, borderRadius: 8,
                        background: syncMsg.startsWith("Erro")
                          ? "#fee2e2" : "#dcfce7",
                        color: syncMsg.startsWith("Erro")
                          ? "#991b1b" : "#166534",
                        fontSize: 12, marginBottom: 10 }}>
            {syncMsg}
          </div>
        )}
        {probe && (
          <div style={{ padding: 12, background: "#f8fafc",
                        border: "1px solid #e2e8f0", borderRadius: 8,
                        marginBottom: 10, fontSize: 12 }}>
            <strong>Resultado do probe:</strong>
            <ul style={{ margin: "6px 0", paddingLeft: 18 }}>
              {probe.endpoints.map((e) => (
                <li key={e.endpoint}
                    style={{ color: e.available ? "#166534" : "#991b1b" }}>
                  /{e.endpoint} — HTTP {e.http_status}
                  {e.available ? " ✓" : ` ✗ ${e.error || ""}`}
                </li>
              ))}
            </ul>
          </div>
        )}

        {stats && (
          <div style={{ display: "grid",
                        gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
            <Chip label="Total" value={stats.total_invoices} />
            {Object.entries(stats.by_status || {}).slice(0, 3).map(([st, v]) => (
              <Chip key={st} label={st}
                    value={`${v.count}  ·  ${fmtMoney(v.amount)}`} />
            ))}
          </div>
        )}
      </Card>

      <Card title="Faturas">
        {invoices.length === 0 ? (
          <Empty msg="Nenhuma fatura sincronizada ainda." />
        ) : (
          <div style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                        overflow: "hidden", maxHeight: 500,
                        overflowY: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f8fafc",
                              position: "sticky", top: 0 }}>
                  {["Cliente", "Documento", "Venc.", "Valor", "Pago", "Status"]
                  .map((h, i) => (
                    <th key={i} style={{
                      padding: "10px 14px",
                      textAlign: (i >= 3) ? "right" : "left",
                      fontSize: 11, fontWeight: 700, color: "#475569",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {invoices.map((inv) => (
                  <tr key={inv.id} style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "8px 14px" }}>
                      {inv.subscriber_name || "—"}
                    </td>
                    <td style={{ padding: "8px 14px", color: "#64748b",
                                  fontFamily: "monospace" }}>
                      {inv.subscriber_document || "—"}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {inv.due_date || "—"}
                    </td>
                    <td style={{ padding: "8px 14px", textAlign: "right",
                                  fontWeight: 600 }}>
                      {fmtMoney(inv.amount)}
                    </td>
                    <td style={{ padding: "8px 14px", textAlign: "right",
                                  color: "#16a34a" }}>
                      {inv.amount_paid ? fmtMoney(inv.amount_paid) : "—"}
                    </td>
                    <td style={{ padding: "8px 14px", textAlign: "right",
                                  fontSize: 11, color: "#64748b" }}>
                      {inv.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// =========================================================================
// Helpers visuais reusáveis
// =========================================================================
function Modal({ children, onClose, title, testId }) {
  return (
    <div onClick={onClose} data-testid={testId}
         style={{
           position: "fixed", inset: 0, zIndex: 1000,
           background: "rgba(2,6,23,0.7)",
           display: "grid", placeItems: "center", padding: 20,
         }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "#fff", borderRadius: 14, padding: 24,
             maxWidth: 540, width: "100%",
             maxHeight: "92vh", overflowY: "auto",
             boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
           }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700,
                        color: "#0f172a" }}>{title}</h3>
          <button onClick={onClose} style={{
            background: "transparent", border: "none", fontSize: 24,
            color: "#94a3b8", cursor: "pointer", padding: 0,
          }}>×</button>
        </div>
        <div style={{ display: "grid", gap: 12 }}>{children}</div>
      </div>
    </div>
  );
}

function ModalActions({ onClose, onSave, busy, testId, saveLabel = "Salvar" }) {
  return (
    <div style={{ display: "flex", gap: 10, marginTop: 6,
                  justifyContent: "flex-end" }}>
      <Button variant="secondary" onClick={onClose} disabled={busy}>
        Cancelar
      </Button>
      <Button onClick={onSave} disabled={busy} data-testid={testId}>
        {busy ? "Salvando…" : saveLabel}
      </Button>
    </div>
  );
}

function Chip({ label, value, color = "#0f172a", highlight, icon: Ico }) {
  return (
    <div style={{
      padding: "10px 14px", borderRadius: 10,
      background: highlight ? "#ecfdf5" : "#f8fafc",
      border: `1px solid ${highlight ? "#a7f3d0" : "#e2e8f0"}`,
    }}>
      <div style={{ fontSize: 10, color: "#64748b",
                    textTransform: "uppercase", fontWeight: 700,
                    letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, color,
                    display: "flex", alignItems: "center", gap: 6 }}>
        {Ico && <Ico size={14} />}
        {value}
      </div>
    </div>
  );
}

function Loading() {
  return <div style={{ color: "#94a3b8", padding: 20 }}>Carregando…</div>;
}
function Empty({ msg }) {
  return <div style={{ textAlign: "center", padding: 30,
                        color: "#94a3b8", fontSize: 13 }}>{msg}</div>;
}
function ErrBox({ msg }) {
  return <div style={{ marginTop: 8, padding: 10, background: "#fee2e2",
                        color: "#991b1b", borderRadius: 8, fontSize: 12 }}>
    {msg}
  </div>;
}
