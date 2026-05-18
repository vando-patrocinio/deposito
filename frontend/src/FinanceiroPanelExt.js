import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, inputStyle } from "@/ui";
import {
  Plus, Pencil, Trash2, CheckCircle2, AlertCircle, Calendar,
  ArrowUp, ArrowDown, DollarSign, RotateCcw,
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ComposedChart, Line,
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
                  onSaved={() => { setEditing(null); reload(); }}
                  onRefsChanged={loadRefs} />
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

function BillForm({ initial, refs, onClose, onSaved, onRefsChanged }) {
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
  // Parcelamento (só pra nova conta)
  const [installments, setInstallments] = useState(1);
  const [periodDays, setPeriodDays] = useState(30);
  const [recurrent, setRecurrent] = useState(false);
  // Inline create modals
  const [creatingSupplier, setCreatingSupplier] = useState(false);
  const [creatingCategory, setCreatingCategory] = useState(false);

  const totalAmount = Number(form.amount) || 0;
  const parcelValue = recurrent ? totalAmount
    : (installments > 1 ? totalAmount / installments : totalAmount);
  const lastDate = (() => {
    if (!form.due_date || installments <= 1) return null;
    const d = new Date(form.due_date + "T12:00:00");
    d.setDate(d.getDate() + periodDays * (installments - 1));
    return d.toLocaleDateString("pt-BR");
  })();

  async function save() {
    setBusy(true); setErr("");
    try {
      const payload = { ...form, amount: Number(form.amount) };
      if (!isEdit && installments > 1) {
        payload.installments_count = installments;
        payload.installments_period_days = periodDays;
        payload.installments_recurrent = recurrent;
      }
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
        <Field label={installments > 1 ? "1º Vencimento *" : "Vencimento *"}>
          <input style={inputStyle} type="date" value={form.due_date}
                 onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                 data-testid="bill-fld-due-date" />
        </Field>
      </div>

      {/* Parcelamento — só pra nova conta */}
      {!isEdit && (
        <div data-testid="bill-installments-box"
              style={{
                marginTop: 4, padding: 10, borderRadius: 8,
                background: "rgba(99,102,241,0.06)",
                border: "1px solid rgba(99,102,241,0.25)",
              }}>
          <div style={{ display: "grid",
                          gridTemplateColumns: "auto 1fr 1fr",
                          gap: 10, alignItems: "end" }}>
            <Field label="Parcelas">
              <input style={{ ...inputStyle, width: 80 }} type="number"
                       min="1" max="60" value={installments}
                       onChange={(e) => setInstallments(Math.max(1, Number(e.target.value) || 1))}
                       data-testid="bill-fld-installments" />
            </Field>
            <Field label="Intervalo (dias)">
              <input style={inputStyle} type="number" min="1" max="365"
                       value={periodDays}
                       disabled={installments <= 1}
                       onChange={(e) => setPeriodDays(Math.max(1, Number(e.target.value) || 30))}
                       data-testid="bill-fld-period-days" />
            </Field>
            <Field label=" ">
              <label style={{
                display: "flex", gap: 6, alignItems: "center",
                fontSize: 12, color: "#475569", padding: "8px 0",
              }}>
                <input type="checkbox" checked={recurrent}
                         disabled={installments <= 1}
                         onChange={(e) => setRecurrent(e.target.checked)}
                         data-testid="bill-fld-recurrent" />
                Mesmo valor cada (recorrência)
              </label>
            </Field>
          </div>
          {installments > 1 && (
            <div style={{ marginTop: 8, padding: 8,
                            background: "#fff", borderRadius: 6,
                            fontSize: 11.5, color: "#475569",
                            border: "1px solid #e2e8f0" }}
                  data-testid="bill-installments-summary">
              <strong>
                {installments}× de R${" "}
                {parcelValue.toLocaleString("pt-BR", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </strong>
              {!recurrent && (
                <> — total R$ {totalAmount.toLocaleString("pt-BR",
                  { minimumFractionDigits: 2 })}</>
              )}
              {recurrent && (
                <> — total R$ {(parcelValue * installments).toLocaleString("pt-BR",
                  { minimumFractionDigits: 2 })} ({installments} cobranças)</>
              )}
              {lastDate && (
                <span style={{ marginLeft: 8, color: "#64748b" }}>
                  · última: {lastDate}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      <Field label="Fornecedor">
        <div style={{ display: "flex", gap: 6 }}>
          <select style={{ ...inputStyle, flex: 1 }} value={form.supplier_id}
                  onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}
                  data-testid="bill-fld-supplier">
            <option value="">— Nenhum —</option>
            {refs.suppliers.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <button type="button"
                    onClick={() => setCreatingSupplier(true)}
                    data-testid="bill-supplier-new-btn"
                    style={inlineCreateBtnStyle}
                    title="Criar fornecedor">+</button>
        </div>
      </Field>
      <Field label="Categoria">
        <div style={{ display: "flex", gap: 6 }}>
          <select style={{ ...inputStyle, flex: 1 }} value={form.category_id}
                  onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                  data-testid="bill-fld-category">
            <option value="">— Nenhuma —</option>
            {refs.categories.filter((c) => c.kind !== "income")
                            .map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <button type="button"
                    onClick={() => setCreatingCategory(true)}
                    data-testid="bill-category-new-btn"
                    style={inlineCreateBtnStyle}
                    title="Criar categoria">+</button>
        </div>
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
      {creatingSupplier && (
        <InlineCreate
          title="Novo fornecedor"
          fields={[
            { key: "name", label: "Nome *", required: true },
            { key: "tax_id", label: "CNPJ/CPF" },
            { key: "phone", label: "Telefone" },
            { key: "email", label: "Email" },
            { key: "notes", label: "Notas", multiline: true },
          ]}
          onClose={() => setCreatingSupplier(false)}
          onCreated={async (created) => {
            await onRefsChanged?.();
            setForm((s) => ({ ...s, supplier_id: created.id }));
            setCreatingSupplier(false);
          }}
          endpoint="/financeiro/suppliers"
        />
      )}
      {creatingCategory && (
        <InlineCreate
          title="Nova categoria"
          fields={[
            { key: "name", label: "Nome *", required: true },
            { key: "kind", label: "Tipo *",
              options: [
                { value: "expense", label: "Despesa" },
                { value: "income", label: "Receita" },
                { value: "both", label: "Ambos" },
              ], defaultValue: "expense", required: true },
            { key: "color", label: "Cor (hex)", placeholder: "#6366f1" },
          ]}
          onClose={() => setCreatingCategory(false)}
          onCreated={async (created) => {
            await onRefsChanged?.();
            setForm((s) => ({ ...s, category_id: created.id }));
            setCreatingCategory(false);
          }}
          endpoint="/financeiro/categories"
        />
      )}
    </Modal>
  );
}

const inlineCreateBtnStyle = {
  width: 34, height: 34, border: "1px solid #cbd5e1",
  background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
  color: "#fff", borderRadius: 6, cursor: "pointer",
  fontSize: 18, fontWeight: 700, flexShrink: 0,
};

function InlineCreate({ title, fields, onClose, onCreated, endpoint }) {
  const [form, setForm] = useState(() => {
    const init = {};
    fields.forEach((f) => { init[f.key] = f.defaultValue || ""; });
    return init;
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const canSave = fields.filter((f) => f.required)
    .every((f) => String(form[f.key] || "").trim().length > 0);

  async function save() {
    setBusy(true); setErr("");
    try {
      const payload = {};
      fields.forEach((f) => {
        if (form[f.key]) payload[f.key] = form[f.key];
      });
      const r = await api._client.post(endpoint, payload).then((x) => x.data);
      onCreated(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} title={title} testId="inline-create-modal">
      {fields.map((f) => (
        <Field key={f.key} label={f.label}>
          {f.options ? (
            <select style={inputStyle} value={form[f.key]}
                      onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      data-testid={`inline-fld-${f.key}`}>
              <option value="">—</option>
              {f.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          ) : f.multiline ? (
            <textarea style={{ ...inputStyle, minHeight: 60, resize: "vertical" }}
                        value={form[f.key]}
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                        data-testid={`inline-fld-${f.key}`} />
          ) : (
            <input style={inputStyle} value={form[f.key]}
                     placeholder={f.placeholder || ""}
                     onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                     data-testid={`inline-fld-${f.key}`} />
          )}
        </Field>
      ))}
      {err && <ErrBox msg={err} />}
      <ModalActions onClose={onClose} onSave={save} busy={busy || !canSave}
                    testId="inline-save-btn" />
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
              <Chip label="Média/dia entradas"
                    value={fmtMoney((data.totals.income || 0)
                      / Math.max(1, data.series?.length || 1))}
                    color="#10b981" />
              <Chip label="Média/dia saídas"
                    value={fmtMoney((data.totals.expense || 0)
                      / Math.max(1, data.series?.length || 1))}
                    color="#ef4444" />
            </div>
            <div style={{ height: 320, marginTop: 6 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={(() => {
                  const series = data.series || [];
                  const n = series.length || 1;
                  const avgIncome = series.reduce((s, x) =>
                    s + (Number(x.income) || 0), 0) / n;
                  const avgExpense = series.reduce((s, x) =>
                    s + (Number(x.expense) || 0), 0) / n;
                  return series.map((x) => ({
                    ...x,
                    avg_income: avgIncome,
                    avg_expense: avgExpense,
                  }));
                })()}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }}
                          tickFormatter={(v) => `R$${v}`} />
                  <Tooltip formatter={(v, name) => {
                    if (name?.toString().includes("Média")) {
                      return [fmtMoney(v), name];
                    }
                    return fmtMoney(v);
                  }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="income" name="Entradas" fill="#16a34a"
                          radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expense" name="Saídas" fill="#dc2626"
                          radius={[4, 4, 0, 0]} />
                  <Line type="monotone" dataKey="avg_income"
                          name="Média Entradas" stroke="#10b981"
                          strokeWidth={2} strokeDasharray="6 3"
                          dot={false} activeDot={false} />
                  <Line type="monotone" dataKey="avg_expense"
                          name="Média Saídas" stroke="#ef4444"
                          strokeWidth={2} strokeDasharray="6 3"
                          dot={false} activeDot={false} />
                </ComposedChart>
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
  const [paying, setPaying] = useState(null);  // invoice obj sendo marcado como pago
  const [filter, setFilter] = useState("all"); // "all" | "open" | "paid"

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
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          {[
            { v: "all", l: "Todas" },
            { v: "open", l: "Em aberto" },
            { v: "paid", l: "Pagas" },
          ].map((f) => (
            <button key={f.v}
                    data-testid={`receivables-filter-${f.v}`}
                    onClick={() => setFilter(f.v)}
                    style={{
                      padding: "6px 12px", borderRadius: 8, fontSize: 12,
                      fontWeight: 700, cursor: "pointer",
                      border: "1px solid #e2e8f0",
                      background: filter === f.v ? "#0f172a" : "white",
                      color: filter === f.v ? "white" : "#475569",
                    }}>
              {f.l}
            </button>
          ))}
        </div>
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
                  {["Cliente", "Documento", "Venc.", "Valor", "Pago", "Status", "Ações"]
                  .map((h, i) => (
                    <th key={i} style={{
                      padding: "10px 14px",
                      textAlign: (i >= 3 && i <= 5) ? "right" : "left",
                      fontSize: 11, fontWeight: 700, color: "#475569",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {invoices
                  .filter((inv) => filter === "all"
                    || (filter === "paid" && inv.status === "paid")
                    || (filter === "open" && inv.status !== "paid"))
                  .map((inv) => (
                  <tr key={inv.id} style={{ borderTop: "1px solid #f1f5f9" }}
                      data-testid={`receivables-invoice-row-${inv.id}`}>
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
                                  fontSize: 11 }}>
                      <InvoiceStatusBadge inv={inv} />
                    </td>
                    <td style={{ padding: "6px 12px", textAlign: "right" }}>
                      {inv.status !== "paid" ? (
                        <button
                          data-testid={`receivables-mark-paid-${inv.id}`}
                          onClick={() => setPaying(inv)}
                          style={{
                            padding: "4px 10px", borderRadius: 6,
                            border: "1px solid #16a34a",
                            background: "#16a34a", color: "white",
                            fontSize: 11, fontWeight: 700, cursor: "pointer",
                            display: "inline-flex", alignItems: "center", gap: 4,
                          }}>
                          <DollarSign size={11} /> Marcar paga
                        </button>
                      ) : (
                        <button
                          data-testid={`receivables-unmark-paid-${inv.id}`}
                          onClick={() => unmarkPaid(inv)}
                          title="Reverter para 'em aberto' (apenas local — não desfaz no Atlaz)"
                          style={{
                            padding: "4px 10px", borderRadius: 6,
                            border: "1px solid #cbd5e1",
                            background: "white", color: "#475569",
                            fontSize: 11, fontWeight: 600, cursor: "pointer",
                            display: "inline-flex", alignItems: "center", gap: 4,
                          }}>
                          <RotateCcw size={11} /> Reverter
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {paying && (
        <MarkInvoicePaidModal
          invoice={paying}
          onClose={() => setPaying(null)}
          onSaved={async (msg) => { setPaying(null); setSyncMsg(msg); await reload(); }}
        />
      )}
    </div>
  );

  async function unmarkPaid(inv) {
    if (!window.confirm("Reverter esta fatura para 'em aberto'? Isso só afeta o registro local — não desfaz a baixa no Atlaz.")) {
      return;
    }
    try {
      await api._client.post(`/atlaz-financeiro/invoices/${inv.id}/unmark-paid`);
      setSyncMsg("Fatura revertida para 'em aberto' localmente.");
      await reload();
    } catch (e) {
      setSyncMsg("Erro: " + (e?.response?.data?.detail || e.message));
    }
  }
}

function InvoiceStatusBadge({ inv }) {
  const map = {
    paid: { bg: "#dcfce7", fg: "#166534", label: "Paga" },
    open: { bg: "#fef3c7", fg: "#92400e", label: "Em aberto" },
    overdue: { bg: "#fee2e2", fg: "#991b1b", label: "Vencida" },
    cancelled: { bg: "#f1f5f9", fg: "#475569", label: "Cancelada" },
  };
  const m = map[inv.status] || { bg: "#f1f5f9", fg: "#475569", label: inv.status || "—" };
  return (
    <span style={{
      padding: "3px 9px", borderRadius: 999,
      background: m.bg, color: m.fg,
      fontWeight: 700, fontSize: 10, letterSpacing: 0.3,
      display: "inline-flex", alignItems: "center", gap: 4,
    }}>
      {m.label}
      {inv.paid_source === "smartprov" && (
        <span title={`Marcada no SmartProv${inv.paid_by_user_name ? " por " + inv.paid_by_user_name : ""}`}
              style={{ opacity: 0.7 }}>· SP</span>
      )}
      {inv.paid_pushed_to_atlaz === true && (
        <span title={`Sincronizada com Atlaz via /${inv.paid_atlaz_endpoint}`}
              style={{ color: "#16a34a" }}>✓</span>
      )}
      {inv.paid_pushed_to_atlaz === false && inv.paid_source === "smartprov" && (
        <span title={`Push pra Atlaz falhou: ${inv.paid_atlaz_last_error || "desconhecido"}`}
              style={{ color: "#dc2626" }}>!</span>
      )}
    </span>
  );
}

function MarkInvoicePaidModal({ invoice, onClose, onSaved }) {
  const [form, setForm] = useState({
    paid_amount: invoice.amount || 0,
    paid_date: new Date().toISOString().slice(0, 10),
    paid_method: "manual",
    paid_note: "",
    push_to_atlaz: true,
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true); setError("");
    try {
      const r = await api._client.post(
        `/atlaz-financeiro/invoices/${invoice.id}/mark-paid`,
        {
          ...form,
          paid_amount: Number(form.paid_amount),
        },
      ).then((r) => r.data);
      setResult(r);
      // Mensagem de sumário
      const pushed = r.atlaz_push?.ok;
      const attempted = r.atlaz_push?.attempted;
      const summary = pushed
        ? `Fatura marcada como paga · push pra Atlaz OK via /${r.atlaz_push.endpoint}`
        : attempted
          ? "Fatura marcada como paga LOCAL · Atlaz não respondeu (provável endpoint inexistente)"
          : "Fatura marcada como paga LOCAL (token Atlaz não configurado ou push desativado)";
      // Espera 1.5s pra usuário ver o feedback no modal antes de fechar
      setTimeout(() => onSaved(summary), 1800);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal onClose={onClose} title={`Marcar como Paga · ${invoice.subscriber_name || invoice.external_id}`}
           testId="receivables-mark-paid-modal">
      <div style={{ display: "grid", gap: 12, padding: 18, minWidth: 480 }}>
        <div style={{ fontSize: 13, color: "#475569", padding: 10,
                       background: "#f8fafc", borderRadius: 8, border: "1px solid #e2e8f0" }}>
          <strong>Fatura Atlaz:</strong> {invoice.external_id}<br />
          <strong>Vencimento:</strong> {invoice.due_date || "—"}<br />
          <strong>Valor original:</strong> {fmtMoney(invoice.amount)}
        </div>

        <Field label="Valor pago (R$)">
          <input type="number" step="0.01" style={inputStyle}
                 data-testid="mark-paid-amount"
                 value={form.paid_amount}
                 onChange={(e) => setForm({ ...form, paid_amount: e.target.value })} />
        </Field>
        <Field label="Data do pagamento">
          <input type="date" style={inputStyle}
                 data-testid="mark-paid-date"
                 value={form.paid_date}
                 onChange={(e) => setForm({ ...form, paid_date: e.target.value })} />
        </Field>
        <Field label="Método (informativo)">
          <select style={inputStyle}
                  data-testid="mark-paid-method"
                  value={form.paid_method}
                  onChange={(e) => setForm({ ...form, paid_method: e.target.value })}>
            <option value="manual">Manual (caixa, recibo)</option>
            <option value="pix">PIX</option>
            <option value="boleto">Boleto liquidado</option>
            <option value="cartao">Cartão</option>
            <option value="transferencia">Transferência</option>
            <option value="dinheiro">Dinheiro</option>
          </select>
        </Field>
        <Field label="Observação (opcional)">
          <input type="text" style={inputStyle}
                 data-testid="mark-paid-note"
                 placeholder="Ex: recebido em mãos pela técnica X"
                 value={form.paid_note}
                 onChange={(e) => setForm({ ...form, paid_note: e.target.value })} />
        </Field>

        <label style={{ display: "flex", alignItems: "center", gap: 8,
                         padding: 10, background: "#eff6ff", borderRadius: 8,
                         border: "1px solid #bfdbfe", fontSize: 12, color: "#1e40af" }}>
          <input type="checkbox"
                 data-testid="mark-paid-push-atlaz"
                 checked={form.push_to_atlaz}
                 onChange={(e) => setForm({ ...form, push_to_atlaz: e.target.checked })} />
          <span><strong>Tentar dar baixa no Atlaz também</strong> (best-effort — se a API não suportar,
            a fatura fica como paga apenas localmente)</span>
        </label>

        {error && (
          <div style={{ padding: 10, borderRadius: 8, background: "#fee2e2",
                         color: "#991b1b", fontSize: 12 }}>
            {error}
          </div>
        )}
        {result && (
          <div style={{ padding: 10, borderRadius: 8,
                         background: result.atlaz_push?.ok ? "#dcfce7" : "#fef3c7",
                         color: result.atlaz_push?.ok ? "#166534" : "#92400e",
                         fontSize: 12 }}>
            {result.atlaz_push?.ok ? (
              <>✓ Pago localmente · <strong>Atlaz atualizado</strong> via
                <code> /{result.atlaz_push.endpoint}</code></>
            ) : result.atlaz_push?.attempted ? (
              <>✓ Pago localmente · Atlaz <strong>não confirmou</strong> a baixa
                ({result.atlaz_push.total_attempts || 0} endpoints testados,
                nenhum retornou success=true). A fatura voltará a "open"
                no próximo sync se o Atlaz não tiver registrado o pagamento.</>
            ) : (
              <>✓ Pago localmente (push para Atlaz desativado ou sem token).</>
            )}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancelar
          </Button>
          <Button onClick={submit} disabled={busy}
                  data-testid="mark-paid-confirm-btn">
            <CheckCircle2 size={14} /> {busy ? "Salvando…" : "Confirmar baixa"}
          </Button>
        </div>
      </div>
    </Modal>
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
