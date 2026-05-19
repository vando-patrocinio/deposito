import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Button, Card, Field, inputStyle } from "@/ui";
import {
  TrendingUp, FileText, Wallet, CreditCard, Tag, Truck,
  Plus, Pencil, Trash2, Search, DollarSign, Inbox, RefreshCw,
  Upload, Building2, BarChart3,
} from "lucide-react";
import { BillsTab, CashFlowTab, ReceivablesTab } from "@/FinanceiroPanelExt";
import ReportsTab from "@/FinanceiroReportsTab";
import ReadjustmentTab from "@/FinanceiroReadjustmentTab";
import BankImportTab from "@/BankImportTab";

/**
 * Painel Financeiro — Aba principal com 6 sub-abas.
 * Acesso restrito a: super_admin (administrador) e financeiro.
 *
 * Sub-abas:
 *   • Fluxo de Caixa   (PLACEHOLDER — Fase 3)
 *   • Contas a Pagar   (PLACEHOLDER — Fase 3)
 *   • Caixa            (CRUD)
 *   • Método Cobrança  (CRUD)
 *   • Categoria        (CRUD)
 *   • Fornecedor       (CRUD)
 */
const SUBTABS = [
  { id: "fluxo", label: "Fluxo de Caixa", icon: TrendingUp, phase: 3 },
  { id: "pagar", label: "Contas a Pagar", icon: FileText, phase: 3 },
  { id: "receber", label: "Recebimentos", icon: Inbox, phase: 4 },
  { id: "relatorios", label: "Relatórios", icon: BarChart3, phase: 2 },
  { id: "import", label: "Importar Extrato", icon: Upload, phase: 3 },
  { id: "reajuste", label: "Reajuste", icon: RefreshCw, phase: 2 },
  { id: "caixa", label: "Caixa", icon: Wallet, phase: 2 },
  { id: "metodo", label: "Método de Cobrança", icon: CreditCard, phase: 2 },
  { id: "categoria", label: "Categoria", icon: Tag, phase: 2 },
  { id: "fornecedor", label: "Fornecedor", icon: Truck, phase: 2 },
  { id: "filial", label: "Filial", icon: Building2, phase: 2 },
];

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
  });

export default function FinanceiroPanel() {
  const [active, setActive] = useState("fluxo");
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    api.finSummary().then(setSummary).catch(() => setSummary(null));
  }, [active]);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700,
                     color: "var(--text-primary)",
                     letterSpacing: "-0.02em", margin: 0 }}>
          Financeiro
        </h1>
        {summary && (
          <div style={{ display: "flex", gap: 14 }}>
            <SummaryChip label="Saldo total"
                         value={fmtMoney(summary.total_balance)}
                         highlight />
            <SummaryChip label="Caixas" value={summary.cash_accounts} />
            <SummaryChip label="Fornec." value={summary.suppliers} />
            <SummaryChip label="Categ." value={summary.categories} />
          </div>
        )}
      </div>

      {/* Sub-abas */}
      <div role="tablist" style={{
        display: "flex", gap: 4, padding: 4,
        background: "#f1f5f9", borderRadius: 10, flexWrap: "wrap",
      }} data-testid="fin-subtabs">
        {SUBTABS.map((t) => {
          const Ico = t.icon;
          const isActive = active === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              data-testid={`fin-tab-${t.id}`}
              onClick={() => setActive(t.id)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "8px 14px", borderRadius: 8,
                background: isActive ? "#fff" : "transparent",
                color: isActive ? "#0f172a" : "#64748b",
                fontWeight: isActive ? 700 : 500, fontSize: 13,
                border: "none", cursor: "pointer",
                boxShadow: isActive ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              }}>
              <Ico size={14} />
              {t.label}
            </button>
          );
        })}
      </div>

      {active === "fluxo" && <CashFlowTab />}
      {active === "pagar" && <BillsTab />}
      {active === "receber" && <ReceivablesTab />}
      {active === "relatorios" && <ReportsTab />}
      {active === "import" && <BankImportTab />}
      {active === "reajuste" && <ReadjustmentTab />}
      {active === "caixa" && <CashAccountsTab />}
      {active === "metodo" && <PaymentMethodsTab />}
      {active === "categoria" && <CategoriesTab />}
      {active === "fornecedor" && <SuppliersTab />}
      {active === "filial" && <FiliaisTab />}
    </div>
  );
}

function SummaryChip({ label, value, highlight }) {
  return (
    <div style={{
      padding: "8px 14px", borderRadius: 10,
      background: highlight ? "#ecfdf5" : "#f8fafc",
      border: `1px solid ${highlight ? "#a7f3d0" : "#e2e8f0"}`,
    }}>
      <div style={{ fontSize: 10, color: "#64748b",
                    textTransform: "uppercase", fontWeight: 700,
                    letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700,
                    color: highlight ? "#047857" : "#0f172a" }}>
        {value}
      </div>
    </div>
  );
}

function ComingSoon({ title }) {
  return (
    <Card title={title}>
      <div style={{ textAlign: "center", padding: "40px 20px",
                    color: "#64748b" }}>
        <DollarSign size={32} style={{ opacity: 0.4 }} />
        <p style={{ margin: "12px 0 4px", fontSize: 14, fontWeight: 600,
                    color: "#0f172a" }}>
          Em construção (Fase 3)
        </p>
        <p style={{ margin: 0, fontSize: 12 }}>
          Configure primeiro Categorias, Fornecedores, Caixas e Métodos de Cobrança.
        </p>
      </div>
    </Card>
  );
}

// =========================================================================
// Generic CRUD Tab Component
// =========================================================================
function CrudTab({ title, columns, fields, listApi, createApi, updateApi,
                  deleteApi, testIdPrefix, extraHeader }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null); // null=fechado, {}=novo, {...}=editando

  async function reload() {
    setLoading(true);
    try { setItems(await listApi()); }
    finally { setLoading(false); }
  }
  useEffect(() => { reload(); }, []);
  // Permite refresh externo via evento — ex: após sincronizar filiais do Atlaz
  useEffect(() => {
    const handler = () => reload();
    window.addEventListener("fin-filiais-synced", handler);
    return () => window.removeEventListener("fin-filiais-synced", handler);
  }, []);

  const filtered = useMemo(() => {
    if (!search) return items;
    const q = search.toLowerCase();
    return items.filter((i) =>
      JSON.stringify(i).toLowerCase().includes(q));
  }, [items, search]);

  async function onDelete(item) {
    if (!await window.confirm(`Excluir "${item.name}"?`)) return;
    await deleteApi(item.id);
    reload();
  }

  return (
    <Card title={title}>
      {extraHeader}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 14, gap: 10,
                    flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 200px", maxWidth: 360 }}>
          <Search size={14} style={{
            position: "absolute", left: 10, top: "50%",
            transform: "translateY(-50%)", color: "#94a3b8",
          }} />
          <input
            placeholder="Buscar..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ ...inputStyle, paddingLeft: 32 }}
            data-testid={`${testIdPrefix}-search`}
          />
        </div>
        <Button onClick={() => setEditing({})}
                data-testid={`${testIdPrefix}-new-btn`}>
          <Plus size={14} /> Novo
        </Button>
      </div>

      {loading ? (
        <div style={{ color: "#94a3b8" }}>Carregando…</div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: "center", padding: 30, color: "#94a3b8",
                      fontSize: 13 }}>
          Nenhum registro. Clique em <strong>Novo</strong> para criar.
        </div>
      ) : (
        <div style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                      overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse",
                          fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                {columns.map((c) => (
                  <th key={c.key} style={{
                    padding: "10px 14px", textAlign: c.align || "left",
                    fontSize: 11, fontWeight: 700, color: "#475569",
                    textTransform: "uppercase", letterSpacing: 0.4,
                  }}>
                    {c.label}
                  </th>
                ))}
                <th style={{ padding: "10px 14px", textAlign: "right",
                             fontSize: 11, color: "#475569",
                             textTransform: "uppercase", fontWeight: 700 }}>
                  Ações
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id} style={{ borderTop: "1px solid #f1f5f9" }}
                    data-testid={`${testIdPrefix}-row-${item.id}`}>
                  {columns.map((c) => (
                    <td key={c.key} style={{
                      padding: "10px 14px",
                      textAlign: c.align || "left",
                      color: "#0f172a",
                    }}>
                      {c.render ? c.render(item) : (item[c.key] ?? "—")}
                    </td>
                  ))}
                  <td style={{ padding: "8px 14px", textAlign: "right",
                               whiteSpace: "nowrap" }}>
                    <Button variant="ghost" size="sm"
                            onClick={() => setEditing(item)}
                            data-testid={`${testIdPrefix}-edit-${item.id}`}>
                      <Pencil size={12} />
                    </Button>
                    <Button variant="ghost" size="sm"
                            onClick={() => onDelete(item)}
                            data-testid={`${testIdPrefix}-del-${item.id}`}>
                      <Trash2 size={12} color="#dc2626" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing !== null && (
        <CrudModal
          title={title}
          fields={fields}
          initial={editing}
          onClose={() => setEditing(null)}
          onSave={async (data) => {
            if (editing.id) await updateApi(editing.id, data);
            else await createApi(data);
            setEditing(null);
            reload();
          }}
          testIdPrefix={testIdPrefix}
        />
      )}
    </Card>
  );
}

function CrudModal({ title, fields, initial, onClose, onSave, testIdPrefix }) {
  const [form, setForm] = useState(() => {
    const f = {};
    fields.forEach((fl) => {
      f[fl.key] = initial?.[fl.key] ?? fl.default ?? (fl.type === "boolean" ? true : "");
    });
    return f;
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    setBusy(true); setErr("");
    try {
      const payload = { ...form };
      fields.forEach((fl) => {
        if (fl.type === "number") payload[fl.key] = Number(payload[fl.key] || 0);
      });
      await onSave(payload);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div onClick={onClose}
         style={{
           position: "fixed", inset: 0, zIndex: 1000,
           background: "rgba(2,6,23,0.7)",
           display: "grid", placeItems: "center", padding: 20,
         }}
         data-testid={`${testIdPrefix}-modal`}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "#fff", borderRadius: 14,
             padding: 24, maxWidth: 540, width: "100%",
             boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
             maxHeight: "90vh", overflowY: "auto",
           }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700,
                       color: "#0f172a" }}>
            {initial?.id ? "Editar" : "Novo"} — {title}
          </h3>
          <button onClick={onClose} style={{
            background: "transparent", border: "none", fontSize: 24,
            color: "#94a3b8", cursor: "pointer", padding: 0,
          }}>×</button>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {fields.map((fl) => (
            <Field key={fl.key} label={fl.label + (fl.required ? " *" : "")}>
              {fl.type === "boolean" ? (
                <label style={{ display: "flex", alignItems: "center",
                                gap: 8, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={!!form[fl.key]}
                    onChange={(e) =>
                      setForm({ ...form, [fl.key]: e.target.checked })}
                    style={{ width: 18, height: 18 }}
                    data-testid={`${testIdPrefix}-fld-${fl.key}`}
                  />
                  <span style={{ fontSize: 13, color: "#475569" }}>
                    {form[fl.key] ? "Sim" : "Não"}
                  </span>
                </label>
              ) : fl.type === "select" ? (
                <select
                  value={form[fl.key] || ""}
                  onChange={(e) => setForm({ ...form, [fl.key]: e.target.value })}
                  style={inputStyle}
                  data-testid={`${testIdPrefix}-fld-${fl.key}`}>
                  {fl.options.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              ) : fl.type === "textarea" ? (
                <textarea
                  value={form[fl.key] || ""}
                  onChange={(e) => setForm({ ...form, [fl.key]: e.target.value })}
                  style={{ ...inputStyle, minHeight: 80, resize: "vertical" }}
                  data-testid={`${testIdPrefix}-fld-${fl.key}`}
                />
              ) : (
                <input
                  type={fl.type === "number" ? "number" : "text"}
                  step={fl.step}
                  value={form[fl.key] ?? ""}
                  placeholder={fl.placeholder || ""}
                  onChange={(e) => setForm({ ...form, [fl.key]: e.target.value })}
                  style={inputStyle}
                  data-testid={`${testIdPrefix}-fld-${fl.key}`}
                />
              )}
              {fl.hint && (
                <small style={{ color: "#94a3b8", fontSize: 11 }}>{fl.hint}</small>
              )}
            </Field>
          ))}
        </div>

        {err && (
          <div style={{ marginTop: 12, padding: 10,
                        background: "#fee2e2", color: "#991b1b",
                        borderRadius: 8, fontSize: 12 }}>
            {err}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 18,
                      justifyContent: "flex-end" }}>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancelar
          </Button>
          <Button onClick={save} disabled={busy}
                  data-testid={`${testIdPrefix}-save-btn`}>
            {busy ? "Salvando…" : "Salvar"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// =========================================================================
// CATEGORIAS
// =========================================================================
function CategoriesTab() {
  return (
    <CrudTab
      title="Categorias Financeiras"
      testIdPrefix="fin-cat"
      columns={[
        { key: "name", label: "Nome" },
        { key: "kind", label: "Tipo",
          render: (r) => ({ expense: "Despesa", income: "Receita",
                            both: "Ambos" }[r.kind] || r.kind) },
        { key: "color", label: "Cor",
          render: (r) => r.color
            ? <span style={{
                display: "inline-block", width: 16, height: 16,
                borderRadius: 4, background: r.color,
                border: "1px solid #cbd5e1",
              }} />
            : "—" },
        { key: "active", label: "Ativa",
          render: (r) => r.active ? "✓" : "—" },
      ]}
      fields={[
        { key: "name", label: "Nome", required: true },
        { key: "kind", label: "Tipo", type: "select", default: "expense",
          options: [
            { value: "expense", label: "Despesa" },
            { value: "income", label: "Receita" },
            { value: "both", label: "Ambos" },
          ] },
        { key: "color", label: "Cor (hex)", placeholder: "#3b82f6" },
        { key: "active", label: "Ativa", type: "boolean", default: true },
      ]}
      listApi={() => api.finCategoriesList()}
      createApi={api.finCategoryCreate}
      updateApi={api.finCategoryUpdate}
      deleteApi={api.finCategoryDelete}
    />
  );
}

// =========================================================================
// FORNECEDORES
// =========================================================================
function SuppliersTab() {
  return (
    <CrudTab
      title="Fornecedores"
      testIdPrefix="fin-sup"
      columns={[
        { key: "name", label: "Nome" },
        { key: "document", label: "CPF/CNPJ" },
        { key: "phone", label: "Telefone" },
        { key: "email", label: "E-mail" },
        { key: "active", label: "Ativo",
          render: (r) => r.active ? "✓" : "—" },
      ]}
      fields={[
        { key: "name", label: "Nome / Razão Social", required: true },
        { key: "document", label: "CPF / CNPJ" },
        { key: "email", label: "E-mail" },
        { key: "phone", label: "Telefone" },
        { key: "address", label: "Endereço", type: "textarea" },
        { key: "notes", label: "Observações", type: "textarea" },
        { key: "active", label: "Ativo", type: "boolean", default: true },
      ]}
      listApi={() => api.finSuppliersList()}
      createApi={api.finSupplierCreate}
      updateApi={api.finSupplierUpdate}
      deleteApi={api.finSupplierDelete}
    />
  );
}

// =========================================================================
// MÉTODOS DE COBRANÇA
// =========================================================================
function PaymentMethodsTab() {
  return (
    <CrudTab
      title="Métodos de Cobrança"
      testIdPrefix="fin-pm"
      columns={[
        { key: "name", label: "Nome" },
        { key: "kind", label: "Tipo",
          render: (r) => ({ pix: "PIX", boleto: "Boleto", card: "Cartão",
                            cash: "Dinheiro", transfer: "Transferência",
                            other: "Outro" }[r.kind] || r.kind) },
        { key: "fee_percent", label: "Taxa %",
          render: (r) => `${(r.fee_percent ?? 0).toFixed(2)}%` },
        { key: "settle_days", label: "D+",
          render: (r) => `D+${r.settle_days ?? 0}` },
        { key: "active", label: "Ativo",
          render: (r) => r.active ? "✓" : "—" },
      ]}
      fields={[
        { key: "name", label: "Nome", required: true,
          placeholder: "PIX Banco Itaú" },
        { key: "kind", label: "Tipo", type: "select", default: "pix",
          options: [
            { value: "pix", label: "PIX" },
            { value: "boleto", label: "Boleto" },
            { value: "card", label: "Cartão" },
            { value: "cash", label: "Dinheiro" },
            { value: "transfer", label: "Transferência" },
            { value: "other", label: "Outro" },
          ] },
        { key: "fee_percent", label: "Taxa (%)", type: "number",
          step: "0.01", default: 0,
          hint: "Taxa cobrada por transação" },
        { key: "settle_days", label: "Dias p/ liquidação (D+)",
          type: "number", default: 0 },
        { key: "active", label: "Ativo", type: "boolean", default: true },
      ]}
      listApi={() => api.finPaymentMethodsList()}
      createApi={api.finPaymentMethodCreate}
      updateApi={api.finPaymentMethodUpdate}
      deleteApi={api.finPaymentMethodDelete}
    />
  );
}

// =========================================================================
// CAIXA / CONTA BANCÁRIA
// =========================================================================
function CashAccountsTab() {
  return (
    <CrudTab
      title="Caixas e Contas Bancárias"
      testIdPrefix="fin-ca"
      columns={[
        { key: "name", label: "Nome" },
        { key: "kind", label: "Tipo",
          render: (r) => ({ bank: "Conta Bancária", cash: "Caixa Físico",
                            wallet: "Carteira Digital",
                            other: "Outro" }[r.kind] || r.kind) },
        { key: "bank_name", label: "Banco" },
        { key: "current_balance", label: "Saldo Atual", align: "right",
          render: (r) => fmtMoney(r.current_balance) },
        { key: "active", label: "Ativo",
          render: (r) => r.active ? "✓" : "—" },
      ]}
      fields={[
        { key: "name", label: "Nome", required: true,
          placeholder: "Conta Corrente Itaú" },
        { key: "kind", label: "Tipo", type: "select", default: "bank",
          options: [
            { value: "bank", label: "Conta Bancária" },
            { value: "cash", label: "Caixa Físico" },
            { value: "wallet", label: "Carteira Digital" },
            { value: "other", label: "Outro" },
          ] },
        { key: "bank_name", label: "Banco" },
        { key: "agency", label: "Agência" },
        { key: "account_number", label: "Conta" },
        { key: "opening_balance", label: "Saldo Inicial (R$)",
          type: "number", step: "0.01", default: 0 },
        { key: "current_balance", label: "Saldo Atual (R$)",
          type: "number", step: "0.01", default: 0,
          hint: "Atualizado automaticamente por lançamentos" },
        { key: "active", label: "Ativo", type: "boolean", default: true },
      ]}
      listApi={() => api.finCashAccountsList()}
      createApi={api.finCashAccountCreate}
      updateApi={api.finCashAccountUpdate}
      deleteApi={api.finCashAccountDelete}
    />
  );
}

// =========================================================================
// FILIAIS (Phase 1 — apenas nome + ativo + técnico padrão)
// =========================================================================
function FiliaisTab() {
  const [collabs, setCollabs] = useState([]);
  useEffect(() => {
    api.listCollaborators().then((list) => {
      // Apenas técnicos ativos pra evitar lista enorme com inativos
      setCollabs((list || []).filter((c) => c.active !== false));
    }).catch(() => setCollabs([]));
  }, []);

  const collabOptions = useMemo(() => [
    { value: "", label: "— Sem técnico padrão —" },
    ...collabs.map((c) => ({ value: c.id, label: c.name })),
  ], [collabs]);
  const collabName = useMemo(() => {
    const m = {};
    collabs.forEach((c) => { m[c.id] = c.name; });
    return m;
  }, [collabs]);

  return (
    <CrudTab
      title="Filiais"
      testIdPrefix="fin-fil"
      columns={[
        { key: "name", label: "Nome" },
        { key: "default_collaborator_id", label: "Técnico padrão",
          render: (r) => r.default_collaborator_id && collabName[r.default_collaborator_id]
            ? <span style={{
                padding: "2px 8px", borderRadius: 999,
                background: "#ecfdf5", color: "#047857",
                fontSize: 11, fontWeight: 600,
              }}>👤 {collabName[r.default_collaborator_id]}</span>
            : <span style={{ color: "#cbd5e1", fontSize: 11 }}>—</span> },
        { key: "active", label: "Ativa",
          render: (r) => r.active ? "✓" : "—" },
      ]}
      fields={[
        { key: "name", label: "Nome da filial", required: true,
          placeholder: "Ex.: Matriz Centro, Filial Norte..." },
        { key: "default_collaborator_id", label: "Técnico padrão",
          type: "select", options: collabOptions,
          hint: "Ao escolher esta filial em uma Nova conta, o técnico é copiado automaticamente." },
        { key: "active", label: "Ativa", type: "boolean", default: true },
      ]}
      listApi={() => api.finFiliaisList()}
      createApi={api.finFilialCreate}
      updateApi={api.finFilialUpdate}
      deleteApi={api.finFilialDelete}
      extraHeader={<MappingSummaryCard collabName={collabName} />}
    />
  );
}

function MappingSummaryCard({ collabName }) {
  const [filiais, setFiliais] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  async function load() {
    api.finFiliaisList(true).then(setFiliais).catch(() => setFiliais([]));
  }
  useEffect(() => { load(); }, []);

  async function syncFromAtlaz() {
    if (syncing) return;
    if (!await window.confirm(
      "Importar filiais do mapeamento Atlaz (Configurações → Atlaz)?\n\n" +
      "• Filiais com mesmo nome NÃO serão duplicadas\n" +
      "• O técnico padrão será atualizado se mudou\n" +
      "• Filiais locais que não existem no Atlaz são mantidas")) return;
    setSyncing(true);
    try {
      const r = await api.finFiliaisSyncAtlaz();
      setSyncResult(r);
      await load();
      // Refresh page state so the CrudTab list refetches
      window.dispatchEvent(new CustomEvent("fin-filiais-synced"));
    } catch (e) {
      await window.alert("Falha ao importar: " + (e?.response?.data?.detail || e.message));
    } finally { setSyncing(false); }
  }

  const mapped = filiais.filter((f) => f.default_collaborator_id);
  return (
    <div data-testid="fin-fil-mapping-summary" style={{
      padding: "12px 14px", marginBottom: 12,
      background: "linear-gradient(135deg, #f0fdf4, #ecfdf5)",
      border: "1px solid #bbf7d0", borderRadius: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7,
                       fontSize: 12.5, fontWeight: 700, color: "#047857",
                       marginBottom: filiais.length ? 8 : 0,
                       justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <Building2 size={14} />
          <span>Mapeamento Filial → Técnico padrão</span>
          <span style={{ fontSize: 10.5, color: "#10b981",
                            fontWeight: 600, fontFamily: "ui-monospace, monospace" }}>
            · {mapped.length}/{filiais.length} configurada{filiais.length === 1 ? "" : "s"}
          </span>
        </div>
        <button
          onClick={syncFromAtlaz}
          disabled={syncing}
          data-testid="fin-fil-sync-atlaz-btn"
          title="Importa as filiais cadastradas em Configurações → Atlaz → Mapeamento"
          style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 7,
            background: "white", color: "#047857",
            border: "1px solid #6ee7b7",
            fontSize: 11, fontWeight: 700,
            cursor: syncing ? "wait" : "pointer",
            opacity: syncing ? 0.6 : 1,
          }}
        >
          <RefreshCw size={11} style={{
            animation: syncing ? "dlgSpin 1s linear infinite" : "none",
          }} />
          {syncing ? "Importando..." : "Importar do Atlaz"}
        </button>
      </div>
      <style>{`
        @keyframes dlgSpin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
      {syncResult && (
        <div data-testid="fin-fil-sync-result" style={{
          padding: "6px 10px", borderRadius: 6,
          background: "white", border: "1px dashed #bbf7d0",
          color: "#047857", fontSize: 11, fontWeight: 600,
          marginBottom: 8,
        }}>
          {syncResult.created > 0 && <span>✓ {syncResult.created} criada(s) </span>}
          {syncResult.updated > 0 && <span>· {syncResult.updated} atualizada(s) </span>}
          {syncResult.skipped > 0 && <span>· {syncResult.skipped} já existente(s)</span>}
          {syncResult.message && <span>{syncResult.message}</span>}
        </div>
      )}
      {filiais.length === 0 ? (
        <div style={{ fontSize: 11.5, color: "#15803d", fontStyle: "italic" }}>
          Nenhuma filial cadastrada. Clique em "Importar do Atlaz" pra trazer todas
          as filiais já configuradas em Sistema → Configurações → Atlaz.
        </div>
      ) : mapped.length === 0 ? (
        <div style={{ fontSize: 11.5, color: "#15803d", fontStyle: "italic" }}>
          Nenhum mapeamento ainda. Edite uma filial e selecione o técnico padrão.
        </div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {mapped.map((f) => (
            <span key={f.id} style={{
              padding: "4px 10px", borderRadius: 999,
              background: "white", color: "#047857",
              fontSize: 11, fontWeight: 600,
              border: "1px solid #bbf7d0",
              display: "inline-flex", alignItems: "center", gap: 5,
            }}>
              🏢 {f.name}
              <span style={{ color: "#94a3b8" }}>→</span>
              👤 {collabName[f.default_collaborator_id] || "(técnico removido)"}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}


