import React, { useEffect, useState } from "react";
import { api, client } from "@/api";
import {
  UserCircle, Search, Plus, Save, X, Trash2, Edit2, Upload,
  ChevronLeft, ChevronRight, ChevronDown, ChevronUp, History,
  Filter, Download, Printer, Mail, MessageCircle, RefreshCw, Phone,
} from "lucide-react";
import WifiStatusCard from "./WifiStatusCard";

const STATUS_OPTIONS = [
  "ATIVO", "BLOQUEADO", "SUSPENSO", "CANCELADO",
  "EM_INSTALACAO", "AGUARDANDO_VIABILIDADE", "SEM_VIABILIDADE",
  "PROSPECT", "INADIMPLENTE",
];

const STATUS_COLORS = {
  ATIVO: "success", BLOQUEADO: "danger", SUSPENSO: "warning",
  CANCELADO: "neutral", INADIMPLENTE: "danger",
  EM_INSTALACAO: "info", AGUARDANDO_VIABILIDADE: "info",
  SEM_VIABILIDADE: "warning", PROSPECT: "neutral",
};

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const EMPTY_FILTERS = {
  name: "", email: "", phone: "", document: "",
  street: "", number: "", district: "", city: "", state: "", zip_code: "",
  complement: "", external_code: "",
  branch: "", billing_method: "", contract_status: "", status: "",
  // iter215ay — Filtros de rede (advanced)
  olt: "", cto: "", cto_port: "", vlan: "",
  pppoe: "", sn: "", mac: "",
};

export default function SubscribersPanel() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [pages, setPages] = useState(1);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [draftFilters, setDraftFilters] = useState(EMPTY_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [advOpen, setAdvOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [historyOf, setHistoryOf] = useState(null);
  const [showImport, setShowImport] = useState(false);
  const [showNoPlan, setShowNoPlan] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkAction, setBulkAction] = useState("");

  const load = async (overrides = {}) => {
    setBusy(true);
    const params = { ...filters, page, page_size: pageSize, ...overrides };
    // Remove empties
    Object.keys(params).forEach((k) => {
      if (params[k] === "" || params[k] == null) delete params[k];
    });
    try {
      const r = await api.subscribersList(params);
      setItems(r.items || []);
      setTotal(r.total || 0);
      setPages(r.pages || 1);
    } finally { setBusy(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [page, pageSize, filters]);

  const apply = () => {
    setFilters(draftFilters);
    setPage(1);
  };
  const clearFilters = () => {
    setDraftFilters(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setPage(1);
  };

  const newSub = () => setEditing({
    name: "", status: "ATIVO", contracts_count: 0,
    phones: [{ raw_number: "", is_primary: true, is_whatsapp: true }],
    addresses: [{ is_primary: true }], tags: [],
  });

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleSelectAll = () => {
    if (selected.size === items.length) setSelected(new Set());
    else setSelected(new Set(items.map((s) => s.id)));
  };

  const runBulk = async () => {
    if (!bulkAction) { await window.alert("Selecione uma ação."); return; }
    if (selected.size === 0) { await window.alert("Selecione ao menos um assinante."); return; }
    if (bulkAction === "export") {
      const ids = Array.from(selected);
      const rows = items.filter((s) => ids.includes(s.id));
      const csv = [
        "nome,status,plano,telefone,filial,vencimento,endereco",
        ...rows.map((s) => [
          s.name, s.status, s.plan_name || "", s.primary_phone || "",
          s.branch || "", s.due_day || "", s.primary_address_summary || "",
        ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")),
      ].join("\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `assinantes_${Date.now()}.csv`; a.click();
      URL.revokeObjectURL(url);
    } else if (bulkAction === "print") {
      window.print();
    }
  };

  if (editing) return <SubscriberEditor data={editing} setData={setEditing}
    onSaved={() => { setEditing(null); load(); }}
    onCancel={() => setEditing(null)} />;
  if (historyOf) return <SubscriberHistory subscriber={historyOf}
    onClose={() => setHistoryOf(null)} />;
  if (showImport) return <CsvImporter onClose={() => { setShowImport(false); load(); }} />;
  if (showNoPlan) return <NoPlanReport
    onClose={() => { setShowNoPlan(false); load(); }} />;

  const allChecked = items.length > 0 && selected.size === items.length;

  return (
    <div data-testid="subscribers-panel" style={{ padding: "0 4px" }}>
      <div style={{ marginBottom: 14, display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="page-title" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <UserCircle size={24} strokeWidth={1.75} /> Assinantes
          </h1>
        </div>
      </div>

      {/* Filtros expansíveis */}
      <div className="surface" style={{ borderRadius: 12, marginBottom: 14, overflow: "hidden" }}>
        <button onClick={() => setFiltersOpen(!filtersOpen)}
          data-testid="subs-toggle-filters"
          style={{
            width: "100%", padding: "12px 16px", border: "none",
            background: "var(--bg-surface-2)",
            display: "flex", alignItems: "center", justifyContent: "space-between",
            cursor: "pointer", fontWeight: 700, fontSize: 14, color: "var(--text-primary)",
          }}>
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Filter size={14} /> Filtro de pesquisa
          </span>
          {filtersOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {filtersOpen && (
          <div style={{ padding: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
              <FilterField label="Nome/Apelido" value={draftFilters.name}
                onChange={(v) => setDraftFilters({ ...draftFilters, name: v })}
                testid="sf-name" />
              <FilterField label="E-mails" value={draftFilters.email}
                onChange={(v) => setDraftFilters({ ...draftFilters, email: v })} />
              <FilterField label="Telefones" value={draftFilters.phone}
                onChange={(v) => setDraftFilters({ ...draftFilters, phone: v })}
                testid="sf-phone" />
              <FilterField label="CPF/CNPJ/RG/IE" value={draftFilters.document}
                onChange={(v) => setDraftFilters({ ...draftFilters, document: v })} />
              <FilterField label="Rua" value={draftFilters.street}
                onChange={(v) => setDraftFilters({ ...draftFilters, street: v })} />
              <FilterField label="Número" value={draftFilters.number}
                onChange={(v) => setDraftFilters({ ...draftFilters, number: v })} />
              <FilterField label="Bairro" value={draftFilters.district}
                onChange={(v) => setDraftFilters({ ...draftFilters, district: v })} />
              <FilterField label="Cidade" value={draftFilters.city}
                onChange={(v) => setDraftFilters({ ...draftFilters, city: v })} />
              <FilterField label="Estado (UF)" value={draftFilters.state}
                onChange={(v) => setDraftFilters({ ...draftFilters, state: v.toUpperCase() })} />
              <FilterField label="CEP" value={draftFilters.zip_code}
                onChange={(v) => setDraftFilters({ ...draftFilters, zip_code: v })} />
              <FilterField label="Complemento" value={draftFilters.complement}
                onChange={(v) => setDraftFilters({ ...draftFilters, complement: v })} />
              <FilterField label="ID do Assinante" value={draftFilters.external_code}
                onChange={(v) => setDraftFilters({ ...draftFilters, external_code: v })} />
              <FilterDropdown label="Filial" value={draftFilters.branch}
                onChange={(v) => setDraftFilters({ ...draftFilters, branch: v })}
                options={[{ value: "", label: "Todas" }]} />
              <FilterDropdown label="Método de cobrança" value={draftFilters.billing_method}
                onChange={(v) => setDraftFilters({ ...draftFilters, billing_method: v })}
                options={[
                  { value: "", label: "Todos" },
                  { value: "boleto", label: "Boleto" },
                  { value: "pix", label: "Pix" },
                  { value: "cartao", label: "Cartão" },
                  { value: "carne", label: "Carnê" },
                ]} />
              <FilterDropdown label="Status do contrato" value={draftFilters.contract_status}
                onChange={(v) => setDraftFilters({ ...draftFilters, contract_status: v })}
                options={[
                  { value: "", label: "Todos" },
                  { value: "ATIVO", label: "Ativo" },
                  { value: "BLOQUEADO", label: "Bloqueado" },
                  { value: "SUSPENSO", label: "Suspenso" },
                  { value: "CANCELADO", label: "Cancelado" },
                ]} />
              <FilterDropdown label="Status do assinante" value={draftFilters.status}
                onChange={(v) => setDraftFilters({ ...draftFilters, status: v })}
                options={[
                  { value: "", label: "Todos" },
                  ...STATUS_OPTIONS.map((s) => ({ value: s, label: s })),
                ]} />
            </div>

            {/* iter215ay — Filtros avançados de REDE (OLT/CTO/PPPoE/SN/MAC) */}
            {advOpen && (
              <div data-testid="subs-adv-filters"
                    style={{ marginTop: 14, paddingTop: 14,
                              borderTop: "1px solid var(--border)",
                              display: "grid", gap: 10,
                              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                <FilterField label="OLT" value={draftFilters.olt}
                  testid="filter-olt"
                  onChange={(v) => setDraftFilters({ ...draftFilters,
                      olt: v })} />
                <FilterField label="CTO" value={draftFilters.cto}
                  testid="filter-cto"
                  onChange={(v) => setDraftFilters({ ...draftFilters,
                      cto: v })} />
                <FilterField label="Porta CTO" value={draftFilters.cto_port}
                  testid="filter-cto-port"
                  onChange={(v) => setDraftFilters({ ...draftFilters,
                      cto_port: v })} />
                <FilterField label="VLAN" value={draftFilters.vlan}
                  testid="filter-vlan"
                  onChange={(v) => setDraftFilters({ ...draftFilters,
                      vlan: v })} />
                <FilterField label="PPPoE" value={draftFilters.pppoe}
                  testid="filter-pppoe"
                  onChange={(v) => setDraftFilters({ ...draftFilters,
                      pppoe: v })} />
                <FilterField label="SN da ONT" value={draftFilters.sn}
                  testid="filter-sn"
                  onChange={(v) => setDraftFilters({ ...draftFilters,
                      sn: v.toUpperCase() })} />
                <FilterField label="MAC da ONT" value={draftFilters.mac}
                  testid="filter-mac"
                  onChange={(v) => setDraftFilters({ ...draftFilters,
                      mac: v.toUpperCase() })} />
              </div>
            )}

            <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
              <button className="btn btn-ghost btn-sm"
                onClick={() => setAdvOpen(!advOpen)}
                data-testid="subs-toggle-advanced">
                {advOpen ? "Ocultar" : "Mostrar"} filtros avançados
              </button>
              <div style={{ flex: 1 }} />
              <button className="btn btn-ghost btn-sm" onClick={clearFilters}
                data-testid="subs-clear-filters">
                Limpar
              </button>
              <button className="btn btn-primary btn-sm" onClick={apply}
                data-testid="subs-apply-filter">
                <Search size={13} /> Aplicar filtro
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Subscribers found + bulk actions */}
      <div className="surface" style={{
        padding: "12px 16px", borderRadius: 12, marginBottom: 12,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 12,
      }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>
          Assinantes encontrados:{" "}
          <span style={{ color: "var(--accent)", fontSize: 18 }} data-testid="subs-count">
            {total.toLocaleString("pt-BR")}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ToolIcon icon={Download} title="Exportar"
            onClick={() => { setBulkAction("export"); runBulk(); }} />
          <ToolIcon icon={Printer} title="Imprimir"
            onClick={() => { setBulkAction("print"); runBulk(); }} />
          <ToolIcon icon={Mail} title="E-mail" disabled />
          <ToolIcon icon={MessageCircle} title="WhatsApp" disabled />
          <ToolIcon icon={RefreshCw} title="Atualizar" onClick={() => load()} />

          <select value={bulkAction} onChange={(e) => setBulkAction(e.target.value)}
            className="input" data-testid="subs-bulk-action"
            style={{ minWidth: 200 }}>
            <option value="">Selecione uma ação</option>
            <option value="export">Exportar selecionados (CSV)</option>
            <option value="print">Imprimir página atual</option>
          </select>
          <button className="btn btn-secondary btn-sm" onClick={runBulk}
            data-testid="subs-bulk-run">
            Executar
          </button>
          <button className="btn btn-secondary btn-sm" onClick={() => setShowImport(true)}
            data-testid="subs-import-btn">
            <Upload size={13} /> Importar CSV
          </button>
          <button className="btn btn-secondary btn-sm"
            data-testid="subs-no-plan-btn"
            title="Lista clientes ATIVOS sem plano e permite vincular em lote"
            onClick={() => setShowNoPlan(true)}>
            Sem plano
          </button>
          <button className="btn btn-secondary btn-sm"
            data-testid="subs-backfill-cto-btn"
            title="Varre OS finalizadas e popula CTO/porta dos cadastros sem essa info"
            onClick={async () => {
              const dry = await api.subscribersBackfillCtoPorts(true);
              const msg = `Preview (dry-run):\n\n`
                + `• Tickets varridos: ${dry.scanned_tickets}\n`
                + `• Assinantes únicos: ${dry.unique_subscribers}\n`
                + `• Já estavam OK: ${dry.already_ok}\n`
                + `• Vai sincronizar: ${dry.would_sync}\n\n`
                + `Aplicar agora?`;
              if (!window.confirm(msg)) return;
              const r = await api.subscribersBackfillCtoPorts(false);
              window.alert(
                `Backfill concluído!\n\n`
                + `• Sincronizados: ${r.synced}\n`
                + `• Erros: ${r.errors_count}\n`
                + `Atualize a página pra ver os cartões preenchidos.`
              );
            }}>
            Backfill CTO
          </button>
          <button className="btn btn-primary btn-sm" onClick={newSub}
            data-testid="subs-new-btn">
            <Plus size={13} /> Novo assinante
          </button>
        </div>
      </div>

      {/* Tabela densa */}
      <div className="surface" style={{ padding: 0, borderRadius: 12, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--bg-surface-2)", textAlign: "left" }}>
              <th style={thStyle}>
                <input type="checkbox" checked={allChecked}
                  onChange={toggleSelectAll}
                  data-testid="subs-check-all"
                  style={{ accentColor: "var(--accent)" }} />
              </th>
              <th style={thStyle}>Nome</th>
              <th style={thStyle}>Filial</th>
              <th style={thStyle}>Contratos</th>
              <th style={thStyle}>Venc.</th>
              <th style={thStyle}>Endereço</th>
              <th style={thStyle}>Telefone</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {busy && items.length === 0 && (
              <tr><td colSpan={9} style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
                Carregando…
              </td></tr>
            )}
            {!busy && items.length === 0 && (
              <tr><td colSpan={9} style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
                Nenhum assinante encontrado.
              </td></tr>
            )}
            {items.map((s) => (
              <tr key={s.id} data-testid={`sub-row-${s.id}`}
                style={{ borderTop: "1px solid var(--border-default)" }}>
                <td style={tdStyle}>
                  <input type="checkbox"
                    checked={selected.has(s.id)}
                    onChange={() => toggleSelect(s.id)}
                    data-testid={`sub-check-${s.id}`}
                    style={{ accentColor: "var(--accent)" }} />
                </td>
                <td style={tdStyle}>
                  <button onClick={async () => setEditing(await api.subscribersGet(s.id))}
                    style={{
                      background: "none", border: "none", color: "var(--accent)",
                      fontWeight: 600, cursor: "pointer", padding: 0,
                      textAlign: "left", fontSize: 13,
                    }}
                    data-testid={`sub-name-${s.id}`}>
                    {s.name}
                  </button>
                  {s.nickname && (
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {s.nickname}
                    </div>
                  )}
                </td>
                <td style={tdStyle}>{s.branch || "—"}</td>
                <td style={{ ...tdStyle, textAlign: "center" }}>{s.contracts_count ?? 0}</td>
                <td style={{ ...tdStyle, textAlign: "center" }}>{s.due_day || "—"}</td>
                <td style={{ ...tdStyle, maxWidth: 240, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {s.primary_address_summary || "—"}
                </td>
                <td className="mono" style={tdStyle}>{s.primary_phone || "—"}</td>
                <td style={tdStyle}>
                  <span className={`pill pill--${STATUS_COLORS[s.status] || "neutral"}`}
                    style={{ fontSize: 11 }}>
                    {s.status}
                  </span>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: "flex", gap: 4 }}>
                    <button onClick={async () => setEditing(await api.subscribersGet(s.id))}
                      className="btn btn-ghost btn-sm" data-testid={`sub-edit-${s.id}`}>
                      <Edit2 size={12} />
                    </button>
                    <button onClick={() => setHistoryOf(s)}
                      className="btn btn-ghost btn-sm" data-testid={`sub-history-${s.id}`}>
                      <History size={12} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Paginação */}
      {pages > 1 && (
        <div style={{ display: "flex", justifyContent: "space-between",
          alignItems: "center", padding: "14px 4px", flexWrap: "wrap", gap: 8 }}>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            Página {page} de {pages} · {total.toLocaleString("pt-BR")} no total
          </div>
          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <select value={pageSize} onChange={(e) => { setPageSize(parseInt(e.target.value, 10)); setPage(1); }}
              className="input" style={{ width: 90 }}>
              {PAGE_SIZE_OPTIONS.map((n) => <option key={n} value={n}>{n}/pág</option>)}
            </select>
            <button className="btn btn-ghost btn-sm" disabled={page <= 1}
              onClick={() => setPage(page - 1)} data-testid="subs-prev-page">
              <ChevronLeft size={14} />
            </button>
            <span style={{ padding: "0 8px", fontWeight: 700 }}>{page}</span>
            <button className="btn btn-ghost btn-sm" disabled={page >= pages}
              onClick={() => setPage(page + 1)} data-testid="subs-next-page">
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function FilterField({ label, value, onChange, testid }) {
  return (
    <div>
      <label style={fieldLabelStyle}>{label}</label>
      <input className="input" value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
        style={{ width: "100%" }} />
    </div>
  );
}

function NetRow({ label, value, testid, mono = false }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                    gap: 12 }}>
      <span style={{ color: "#475569", fontWeight: 600 }}>{label}:</span>
      <span data-testid={testid}
             style={{ color: value ? "#0f172a" : "#94a3b8",
                        fontWeight: value ? 800 : 500,
                        fontFamily: mono ? "monospace" : "inherit",
                        textAlign: "right" }}>
        {value || "—"}
      </span>
    </div>
  );
}

// iter215aw — Style padrão pra inputs read-only nos cards de info
const readonlyInputStyle = {
  background: "var(--bg-surface-2)",
  color: "var(--text-muted)",
  cursor: "not-allowed",
};

// iter215aw — Cor do sinal por faixa GPON
function signalColor(s) {
  if (s == null || s === "—") return "var(--text-muted)";
  const v = parseFloat(s);
  if (isNaN(v)) return "var(--text-muted)";
  if (v >= -23) return "#15803d"; // excelente
  if (v >= -27) return "#a16207"; // atenção
  return "#b91c1c"; // crítico
}




function FilterDropdown({ label, value, onChange, options }) {
  return (
    <div>
      <label style={fieldLabelStyle}>{label}</label>
      <select className="input" value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: "100%" }}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function ToolIcon({ icon: Icon, title, onClick, disabled }) {
  return (
    <button onClick={onClick} disabled={disabled} title={title}
      className="btn btn-ghost btn-sm"
      style={{ padding: 6, opacity: disabled ? 0.4 : 1 }}>
      <Icon size={14} />
    </button>
  );
}

const fieldLabelStyle = {
  display: "block", fontSize: 10, fontWeight: 700, color: "var(--text-secondary)",
  textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3,
  lineHeight: 1.25, minHeight: 26,
};
const thStyle = {
  padding: "10px 12px", fontSize: 12, fontWeight: 700,
  color: "var(--text-secondary)", textTransform: "uppercase",
  letterSpacing: 0.4, borderBottom: "1px solid var(--border-default)",
};
const tdStyle = {
  padding: "10px 12px", fontSize: 13, color: "var(--text-primary)",
};

/* ============================================================
   Editor
============================================================ */
function SubscriberEditor({ data, setData, onSaved, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [nicknameEditable, setNicknameEditable] = useState(false);
  const [plansList, setPlansList] = useState([]);
  /* Validação CPF/CNPJ: tag "Válido"/"Inválido" abaixo do campo */
  const [docValidation, setDocValidation] = useState(null);
  /* Lookup CEP: auto-preenche rua/bairro/cidade/UF */
  const [cepBusy, setCepBusy] = useState(false);
  const [cepError, setCepError] = useState(null);
  const set = (k, v) => setData((p) => ({ ...p, [k]: v }));

  /* Debounce de validação de documento (CPF/CNPJ) — 400ms após o usuário parar */
  useEffect(() => {
    const raw = (data.document || "").trim();
    if (!raw) { setDocValidation(null); return; }
    const digits = raw.replace(/\D/g, "");
    if (digits.length !== 11 && digits.length !== 14) {
      setDocValidation(null); return;
    }
    const t = setTimeout(() => {
      api.utilsValidateDocument(digits)
        .then(setDocValidation)
        .catch(() => setDocValidation(null));
    }, 400);
    return () => clearTimeout(t);
  }, [data.document]);

  /* REGRA: apelido auto-preenche com primeiro nome.
     Só fica editável depois de DUPLO-CLIQUE no campo. */
  const autoNickname = ((data.name || "").trim().split(/\s+/)[0] || "");
  const nicknameDisplay = data.nickname || autoNickname;

  /* Carrega planos da aba Planos para o dropdown */
  useEffect(() => {
    api.plansList({ active: true })
      .then((r) => setPlansList(r.items || []))
      .catch(() => setPlansList([]));
  }, []);

  /* iter215av — Carrega info de rede (OLT/CTO/porta/VLAN/PPPoE) */
  const [networkInfo, setNetworkInfo] = useState(null);
  useEffect(() => {
    if (!data.id) { setNetworkInfo(null); return; }
    let alive = true;
    api.subscribersNetworkInfo(data.id)
      .then((r) => { if (alive) setNetworkInfo(r); })
      .catch(() => { if (alive) setNetworkInfo(null); });
    return () => { alive = false; };
  }, [data.id]);

  /* iter215ba — Preview de reajuste (IPCA com cascata para clientes vencidos) */
  const [readjPreview, setReadjPreview] = useState(null);
  const [readjModal, setReadjModal] = useState(false);
  const [readjBusy, setReadjBusy] = useState(false);
  const [readjReloadKey, setReadjReloadKey] = useState(0);
  useEffect(() => {
    if (!data.id || !data.installation_date || !data.plan_price) {
      setReadjPreview(null); return;
    }
    let alive = true;
    client.get(`/financeiro/reajuste/preview/${data.id}`)
      .then((r) => { if (alive) setReadjPreview(r.data); })
      .catch(() => { if (alive) setReadjPreview(null); });
    return () => { alive = false; };
  }, [data.id, data.installation_date, data.plan_price,
       data.readjustment_index, data.last_readjustment_at, readjReloadKey]);

  const applyReadjustment = async () => {
    if (!data.id || readjBusy) return;
    setReadjBusy(true);
    try {
      const resp = await client.post(
        `/financeiro/reajuste/apply/${data.id}?force=true`, {});
      const r = resp.data;
      if (r.applied) {
        setData((d) => ({ ...d, plan_price: r.final_price }));
        setReadjReloadKey((k) => k + 1);
        setReadjModal(false);
      } else {
        alert(`Reajuste não aplicado: ${r.reason || "erro desconhecido"}`);
      }
    } catch (e) {
      alert(`Erro ao aplicar reajuste: ${e?.response?.data?.detail || e?.message || e}`);
    } finally {
      setReadjBusy(false);
    }
  };

  const onPickPlan = (planId) => {
    const p = plansList.find((x) => x.id === planId);
    setData((d) => ({
      ...d,
      plan_id: planId || null,
      plan_name: p?.name || null,
      plan_speed: p?.speed_label || null,
      plan_price: p?.monthly_price ?? null,
    }));
  };

  const save = async () => {
    if (!data.name || data.name.length < 2) {
      await window.alert("Nome obrigatório."); return;
    }
    setBusy(true);
    try {
      const cleaned = {
        ...data,
        phones: (data.phones || []).filter((p) => p.raw_number && p.raw_number.length >= 8),
        addresses: (data.addresses || []).filter((a) => a.street || a.district || a.city),
      };
      if (data.id) await api.subscribersUpdate(data.id, cleaned);
      else await api.subscribersCreate(cleaned);
      onSaved();
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const del = async () => {
    if (!data.id || !await window.confirm(`Excluir assinante ${data.name}?`)) return;
    setBusy(true);
    try { await api.subscribersDelete(data.id); onSaved(); }
    catch (e) { await window.alert("Erro: " + (e?.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };

  const addPhone = () => set("phones", [
    ...(data.phones || []),
    /* REGRA: todo telefone é PRINCIPAL e VINCULANTE — usado pra match
       em chamadas e WhatsApp inbound. Sem checkbox, sem escolha. */
    { raw_number: "", is_whatsapp: true, is_primary: true },
  ]);
  const updPhone = (i, k, v) => {
    const next = [...(data.phones || [])];
    next[i] = { ...next[i], [k]: v };
    // Garante invariante: is_primary sempre true (mesmo se algo seto false)
    next.forEach((p) => { p.is_primary = true; });
    set("phones", next);
  };
  const delPhone = (i) => set("phones", (data.phones || []).filter((_, idx) => idx !== i));
  const updAddr = (k, v) => set("addresses", [{ ...(data.addresses?.[0] || {}), [k]: v, is_primary: true }]);
  const addr = (data.addresses?.[0]) || {};

  /* Lookup ViaCEP: ao digitar 8 dígitos, busca e preenche os campos. */
  const lookupCep = async (rawCep) => {
    const digits = (rawCep || "").replace(/\D/g, "");
    if (digits.length !== 8) return;
    setCepBusy(true); setCepError(null);
    try {
      const r = await api.utilsLookupCep(digits);
      set("addresses", [{
        ...(data.addresses?.[0] || {}),
        zip_code: digits,
        street: r.logradouro || (data.addresses?.[0]?.street || ""),
        district: r.bairro || (data.addresses?.[0]?.district || ""),
        city: r.cidade || (data.addresses?.[0]?.city || ""),
        state: r.uf || (data.addresses?.[0]?.state || ""),
        is_primary: true,
      }]);
    } catch (e) {
      setCepError(e?.response?.data?.detail || "CEP não encontrado");
    } finally {
      setCepBusy(false);
    }
  };

  return (
    <div data-testid="sub-editor" className="surface" style={{ padding: 22, borderRadius: 14 }}>
      <h3 style={{ margin: "0 0 16px", fontSize: 17, fontWeight: 700 }}>
        {data.id ? `Editar: ${data.name}` : "Novo assinante"}
      </h3>

      {data.id && (
        <WifiStatusCard subscriberId={data.id}
                         subscriberName={data.name}
                         canManage={true} />
      )}

      {/* iter215av — Layout em 3 linhas (best practice ISP):
          1) PLANO/COMERCIAL: o que o cliente contratou (plano/velocidade/valor)
          2) REDE: onde ele está conectado (OLT/porta OLT/CTO/porta CTO/VLAN)
          3) EQUIPAMENTO: identidade do dispositivo (PPPoE/SN/MAC/sinal) */}
      {data.id && (
        <>
          {/* LINHA 1 — Comercial + Sinal (4 cols iguais) */}
          <div data-testid="sub-plan-row"
                style={{ display: "grid", gap: 12,
                          gridTemplateColumns: "repeat(4, 1fr)",
                          marginBottom: 12 }}>
            <Field label="Plano contratado">
              <input className="input" readOnly disabled
                data-testid="plan-card-name"
                value={data.plan_name || "—"}
                style={readonlyInputStyle} />
            </Field>
            <Field label="Velocidade do plano">
              <input className="input" readOnly disabled
                data-testid="plan-card-speed"
                value={data.plan_speed || "—"}
                style={readonlyInputStyle} />
            </Field>
            <Field label="Valor mensal">
              <input className="input" readOnly disabled
                data-testid="plan-card-price"
                value={data.plan_price != null
                  ? new Intl.NumberFormat("pt-BR", { style: "currency",
                                                       currency: "BRL" })
                      .format(data.plan_price)
                  : "—"}
                style={readonlyInputStyle} />
            </Field>
            <Field label="Sinal (1490 nm)">
              <input className="input" readOnly disabled
                data-testid="net-card-signal"
                value={networkInfo?.network?.signal_dbm
                  ? `${networkInfo.network.signal_dbm} dBm`
                  : "—"}
                style={{ ...readonlyInputStyle,
                          fontFamily: "monospace",
                          color: signalColor(networkInfo?.network?.signal_dbm),
                          fontWeight: 700 }} />
            </Field>
          </div>

          {/* LINHA 2 — Localização na rede (4 cols iguais) */}
          <div data-testid="sub-network-row"
                style={{ display: "grid", gap: 12,
                          gridTemplateColumns: "repeat(4, 1fr)",
                          marginBottom: 12 }}>
            <Field label="OLT">
              <input className="input" readOnly disabled
                data-testid="net-card-olt"
                value={networkInfo?.network?.olt_name || "—"}
                style={readonlyInputStyle} />
            </Field>
            <Field label="Porta OLT">
              <input className="input" readOnly disabled
                data-testid="net-card-olt-port"
                title="Formato: board/port/onu"
                value={networkInfo?.network?.porta_olt || "—"}
                style={{ ...readonlyInputStyle,
                          fontFamily: "monospace" }} />
            </Field>
            <Field label="CTO">
              <input className="input" readOnly disabled
                data-testid="net-card-cto"
                value={networkInfo?.network?.cto_name || "—"}
                style={readonlyInputStyle} />
            </Field>
            <Field label="Porta CTO">
              <input className="input" readOnly disabled
                data-testid="net-card-cto-port"
                value={networkInfo?.network?.port_number ?? "—"}
                style={readonlyInputStyle} />
            </Field>
          </div>

          {/* LINHA 3 — Equipamento (VLAN + PPPoE + SN + MAC) */}
          <div data-testid="sub-equip-row"
                style={{ display: "grid", gap: 12,
                          gridTemplateColumns: "repeat(4, 1fr)",
                          marginBottom: 12 }}>
            <Field label="VLAN">
              <input className="input" readOnly disabled
                data-testid="net-card-vlan"
                value={networkInfo?.network?.vlan ?? "—"}
                style={{ ...readonlyInputStyle,
                          fontFamily: "monospace" }} />
            </Field>
            <Field label="PPPoE">
              <input className="input" readOnly disabled
                data-testid="net-card-pppoe"
                value={networkInfo?.network?.pppoe_user
                  || data.pppoe_user || "—"}
                style={{ ...readonlyInputStyle,
                          fontFamily: "monospace" }} />
            </Field>
            <Field label="SN da ONT">
              <input className="input" readOnly disabled
                data-testid="net-card-sn"
                value={networkInfo?.network?.sn || "—"}
                style={{ ...readonlyInputStyle,
                          fontFamily: "monospace",
                          textTransform: "uppercase" }} />
            </Field>
            <Field label="MAC da ONT">
              <input className="input" readOnly disabled
                data-testid="net-card-mac"
                value={networkInfo?.network?.mac || "—"}
                style={{ ...readonlyInputStyle,
                          fontFamily: "monospace",
                          textTransform: "uppercase" }} />
            </Field>
          </div>
        </>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1.5fr 1fr 1fr", gap: 12, alignItems: "end" }}>
        <Field label="Nome completo *">
          <input className="input" value={data.name || ""} onChange={(e) => set("name", e.target.value)}
            data-testid="sub-name" />
        </Field>
        <Field label="Apelido" hint="Dê dois cliques para editar o apelido">
          {/* REGRA: auto-preenche com primeiro nome. Só editável após
              double-click. Visual: read-only = fundo cinza claro. */}
          <input className="input"
            data-testid="sub-nickname"
            readOnly={!nicknameEditable}
            onDoubleClick={() => setNicknameEditable(true)}
            onBlur={() => {
              setNicknameEditable(false);
              // Se ficou vazio, volta pro auto-derivado
              if (!data.nickname?.trim()) set("nickname", "");
            }}
            value={nicknameEditable ? (data.nickname || "") : nicknameDisplay}
            onChange={(e) => set("nickname", e.target.value)}
            title={nicknameEditable
              ? "Editando apelido — clique fora para salvar"
              : "Dê dois cliques para editar o apelido"}
            style={{
              background: nicknameEditable ? undefined : "var(--bg-surface-2)",
              cursor: nicknameEditable ? "text" : "pointer",
              fontWeight: nicknameEditable ? 400 : 600,
            }} />
        </Field>
        <Field label="ID do Assinante" hint="Código gerado automaticamente pelo sistema">
          {/* REGRA: external_code é gerado pelo backend. Aqui é apenas
              read-only. Em criação, mostra "ASS-(novo)". */}
          <input className="input"
            data-testid="sub-external-code"
            readOnly disabled
            value={data.external_code || "ASS- (gerado ao salvar)"}
            title="Código do assinante gerado automaticamente pelo sistema"
            style={{
              background: "var(--bg-surface-2)",
              color: "var(--text-muted)",
              cursor: "not-allowed",
              fontFamily: "ui-monospace, monospace",
              fontWeight: 700,
            }} />
        </Field>
        <Field label="Filial">
          <input className="input" value={data.branch || ""}
            onChange={(e) => set("branch", e.target.value)}
            placeholder="LIGO RIO" />
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12, alignItems: "end" }}>
        <Field label="CPF/CNPJ">
          <input className="input" value={data.document || ""}
            onChange={(e) => set("document", e.target.value)} data-testid="sub-document" />
          {docValidation && (
            <div data-testid="sub-document-validation"
              style={{
                marginTop: 4, fontSize: 11, fontWeight: 600,
                display: "inline-flex", alignItems: "center", gap: 4,
                padding: "2px 8px", borderRadius: 999,
                background: docValidation.valid
                  ? "rgba(34, 197, 94, 0.12)" : "rgba(239, 68, 68, 0.12)",
                color: docValidation.valid ? "#16a34a" : "#dc2626",
                border: `1px solid ${docValidation.valid
                  ? "rgba(34, 197, 94, 0.30)" : "rgba(239, 68, 68, 0.30)"}`,
              }}>
              <span>{docValidation.valid ? "✓" : "✗"}</span>
              <span>{docValidation.type.toUpperCase()} {docValidation.valid ? "Válido" : "Inválido"}</span>
              {docValidation.valid && docValidation.formatted && (
                <span style={{ opacity: 0.75, fontWeight: 400 }}>· {docValidation.formatted}</span>
              )}
            </div>
          )}
        </Field>
        <Field label="RG/IE">
          <input className="input" value={data.rg_ie || ""}
            onChange={(e) => set("rg_ie", e.target.value)} />
        </Field>
        <Field label="Status">
          <select className="input" value={data.status || "ATIVO"}
            onChange={(e) => set("status", e.target.value)}>
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="E-mail">
          <input className="input" type="email" value={data.email || ""}
            onChange={(e) => set("email", e.target.value)} />
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr", gap: 12, alignItems: "end" }}>
        <Field label="Plano contratado" hint="Escolha o plano cadastrado na aba Planos">
          {/* REGRA: o plano vem da aba Planos. Não é digitado.
              Ao escolher, o backend salva snapshot de name/speed/price.
              Reajuste anual de inflação fica no plano (não duplicado aqui). */}
          <select className="input"
            data-testid="sub-plan-select"
            value={data.plan_id || ""}
            onChange={(e) => onPickPlan(e.target.value)}>
            <option value="">— Sem plano —</option>
            {plansList.map((p) => (
              <option key={p.id} value={p.id}>
                {`${p.name} · ${p.speed_label || ""} · ${new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(p.monthly_price || 0)}/mês`}
              </option>
            ))}
          </select>
          {plansList.length === 0 && (
            <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
              Nenhum plano cadastrado. Vá em <strong>Clientes → Planos</strong> para criar.
            </div>
          )}
        </Field>
        <Field label="Velocidade do plano">
          <input className="input" readOnly disabled
            value={data.plan_speed || "—"}
            style={{ background: "var(--bg-surface-2)",
                      color: "var(--text-muted)",
                      cursor: "not-allowed" }} />
        </Field>
        <Field label="Valor mensal (R$)">
          <input className="input" readOnly disabled
            value={data.plan_price != null
              ? new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(data.plan_price)
              : "—"}
            style={{ background: "var(--bg-surface-2)",
                      color: "var(--text-muted)",
                      cursor: "not-allowed" }} />
        </Field>
        <Field label="Contratos">
          <input className="input" type="number" min="0" value={data.contracts_count || 0}
            onChange={(e) => set("contracts_count", parseInt(e.target.value, 10) || 0)} />
        </Field>
        <Field label="Vencimento (dia)">
          <input className="input" type="number" min="1" max="31" value={data.due_day || ""}
            onChange={(e) => set("due_day", parseInt(e.target.value, 10) || null)} />
        </Field>
      </div>

      {/* Reajuste anual — campos financeiros */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, alignItems: "end" }}>
        <Field label="Data de instalação" hint="Define a data-base do reajuste anual">
          <input className="input" type="date"
            data-testid="sub-installation-date"
            value={(data.installation_date || "").slice(0, 10)}
            onChange={(e) => {
              const v = e.target.value;
              set("installation_date", v ? new Date(v).toISOString() : null);
            }} />
        </Field>
        <Field label="Índice de reajuste">
          <select className="input"
            data-testid="sub-readjustment-index"
            value={data.readjustment_index || "IPCA"}
            onChange={(e) => set("readjustment_index", e.target.value)}>
            <option value="IPCA">IPCA — Inflação oficial (IBGE)</option>
            <option value="IST">IST — Índice de Telecom (BCB)</option>
            <option value="IGP-M">IGP-M — FGV</option>
          </select>
        </Field>
        <Field label="Próximo reajuste">
          {data.installation_date ? (() => {
            // Cálculo client-side simples: base + N anos > hoje
            const base = data.last_readjustment_at || data.installation_date;
            const baseDate = new Date(base);
            const today = new Date();
            const nextDate = new Date(baseDate);
            let pendingCount = 0;
            while (nextDate <= today) {
              nextDate.setFullYear(nextDate.getFullYear() + 1);
              pendingCount += 1;
              if (pendingCount > 30) break;
            }
            // Se já tem next > today logo de cara, pendingCount=1 mas
            // só conta como pendente se ANTES de avançar já estava vencido.
            // Reajusta: pending = qtas viradas vencidas (não conta a futura).
            const firstAnniv = new Date(baseDate);
            firstAnniv.setFullYear(firstAnniv.getFullYear() + 1);
            const isOverdue = firstAnniv <= today;
            const pending = isOverdue ? pendingCount : 0;
            // nextDate agora é a primeira virada > hoje
            const displayNext = isOverdue
              ? new Date(firstAnniv) : new Date(nextDate);

            return (
              <div data-testid="sub-readjustment-card"
                style={{
                  padding: "6px 10px",
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: 6,
                  fontSize: 12,
                  color: "#0f172a",
                }}>
                <div style={{ display: "flex", alignItems: "center",
                                gap: 6, flexWrap: "wrap" }}>
                  <span data-testid="sub-next-readjustment">
                    {displayNext.toLocaleDateString("pt-BR")}
                  </span>
                  {isOverdue && (
                    <span style={{
                      padding: "1px 6px", borderRadius: 4,
                      background: "#fef2f2", color: "#dc2626",
                      fontSize: 10, fontWeight: 700,
                    }}>VENCIDO</span>
                  )}
                  {pending > 1 && (
                    <span data-testid="sub-pending-count" style={{
                      padding: "1px 6px", borderRadius: 4,
                      background: "#fef3c7", color: "#92400e",
                      fontSize: 10, fontWeight: 700,
                    }}>
                      {pending} pendentes
                    </span>
                  )}
                </div>
                {readjPreview && readjPreview.is_due && (
                  <div style={{ fontSize: 10, color: "#64748b",
                                  marginTop: 2 }}>
                    Cascata IPCA: +{readjPreview.accumulated_pct_total
                      .toFixed(2)}% · R$ {readjPreview.current_price
                      .toFixed(2)} → R$ {readjPreview.new_price.toFixed(2)}
                  </div>
                )}
                {readjPreview && readjPreview.is_due && (
                  <button type="button"
                    data-testid="sub-apply-readjustment-btn"
                    onClick={() => setReadjModal(true)}
                    style={{
                      marginTop: 6,
                      padding: "4px 10px",
                      fontSize: 11, fontWeight: 700,
                      background: "#4b1d7a", color: "#fff",
                      border: "none", borderRadius: 4,
                      cursor: "pointer",
                    }}>
                    Aplicar reajuste agora
                  </button>
                )}
                {isOverdue && !readjPreview && !data.plan_price && (
                  <div style={{ fontSize: 10, color: "#92400e",
                                  marginTop: 2 }}>
                    Defina um plano para calcular o valor do reajuste
                  </div>
                )}
                {!isOverdue && data.last_readjustment_pct != null && (
                  <div style={{ fontSize: 10, color: "#64748b",
                                  marginTop: 2 }}>
                    Último: +{data.last_readjustment_pct.toFixed(2)}%
                  </div>
                )}
              </div>
            );
          })() : (
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Defina a data de instalação primeiro
            </div>
          )}
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, alignItems: "end" }}>
        <Field label="Método de cobrança">
          <select className="input" value={data.billing_method || ""}
            onChange={(e) => set("billing_method", e.target.value)}>
            <option value="">—</option>
            <option value="boleto">Boleto</option>
            <option value="pix">Pix</option>
            <option value="cartao">Cartão</option>
            <option value="carne">Carnê</option>
          </select>
        </Field>
        <Field label="Status do contrato">
          <select className="input" value={data.contract_status || ""}
            onChange={(e) => set("contract_status", e.target.value)}>
            <option value="">—</option>
            <option value="ATIVO">Ativo</option>
            <option value="BLOQUEADO">Bloqueado</option>
            <option value="SUSPENSO">Suspenso</option>
            <option value="CANCELADO">Cancelado</option>
          </select>
        </Field>
        <Field label="Tags (vírgula)">
          <input className="input" value={(data.tags || []).join(", ")}
            onChange={(e) => set("tags", e.target.value.split(",").map((t) => t.trim()).filter(Boolean))} />
        </Field>
      </div>

      <Field label="Telefones — TODOS são principais e vinculam o assinante a chamadas/WhatsApp">
        <div style={{
          padding: "8px 12px", borderRadius: 8, marginBottom: 8,
          background: "rgba(13,148,136,.08)",
          border: "1px dashed rgba(13,148,136,.35)",
          fontSize: 11, color: "#0d9488", fontWeight: 600,
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <Phone size={12} strokeWidth={2} />
          Regra: cada telefone cadastrado vincula automaticamente este
          assinante a quem entrar em contato (WhatsApp ou ligação) por aquele número.
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {(data.phones || []).map((p, i) => (
            <div key={i} style={{
              display: "grid", gridTemplateColumns: "2fr 1fr auto auto",
              gap: 8, alignItems: "center", padding: 8,
              border: "1px solid var(--border-default)", borderRadius: 8,
            }}>
              <input className="input" placeholder="Ex.: 21998176526"
                value={p.raw_number || ""}
                onChange={(e) => updPhone(i, "raw_number", e.target.value)}
                data-testid={`sub-phone-${i}`} />
              <input className="input" placeholder="Rótulo (ex.: Pessoal, Esposa)"
                value={p.label || ""} onChange={(e) => updPhone(i, "label", e.target.value)} />
              <span style={{
                padding: "3px 9px", borderRadius: 999,
                background: "rgba(34,197,94,.15)", color: "#15803d",
                fontSize: 9, fontWeight: 800, letterSpacing: 0.4,
                whiteSpace: "nowrap",
              }}>PRINCIPAL · VINCULA</span>
              <button onClick={() => delPhone(i)} className="btn btn-ghost btn-sm"
                style={{ color: "var(--danger)" }}>
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          <button onClick={addPhone} className="btn btn-secondary btn-sm" type="button"
            data-testid="sub-add-phone">
            <Plus size={13} /> Adicionar telefone
          </button>
        </div>
      </Field>

      <Field label="Endereço primário">
        <div style={{ display: "grid", gridTemplateColumns: "3fr 1fr 2fr", gap: 8, marginBottom: 8 }}>
          <input className="input" placeholder="Rua / Logradouro"
            value={addr.street || ""} onChange={(e) => updAddr("street", e.target.value)} />
          <input className="input" placeholder="Número"
            value={addr.number || ""} onChange={(e) => updAddr("number", e.target.value)} />
          <input className="input" placeholder="Complemento"
            value={addr.complement || ""} onChange={(e) => updAddr("complement", e.target.value)} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1.5fr 0.5fr 1fr", gap: 8 }}>
          <input className="input" placeholder="Bairro"
            value={addr.district || ""} onChange={(e) => updAddr("district", e.target.value)} />
          <input className="input" placeholder="Cidade"
            value={addr.city || ""} onChange={(e) => updAddr("city", e.target.value)} />
          <input className="input" placeholder="UF" maxLength={2}
            value={addr.state || ""} onChange={(e) => updAddr("state", e.target.value.toUpperCase())} />
          <input className="input" placeholder="CEP"
            data-testid="sub-address-cep"
            value={addr.zip_code || ""}
            onChange={(e) => {
              const v = e.target.value;
              updAddr("zip_code", v);
              // Auto-lookup quando completa 8 dígitos
              if (v.replace(/\D/g, "").length === 8) lookupCep(v);
            }}
            onBlur={(e) => lookupCep(e.target.value)}
            disabled={cepBusy} />
        </div>
        {cepBusy && (
          <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-muted)" }}>
            Consultando CEP…
          </div>
        )}
        {cepError && (
          <div data-testid="sub-cep-error"
            style={{ marginTop: 4, fontSize: 11, color: "#dc2626" }}>
            {cepError}
          </div>
        )}
      </Field>

      <Field label="Observações internas">
        <textarea className="input" rows={3} value={data.notes || ""}
          onChange={(e) => set("notes", e.target.value)} />
      </Field>

      <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "space-between" }}>
        <div>
          {data.id && (
            <button className="btn btn-ghost" onClick={del} disabled={busy}
              style={{ color: "var(--danger)" }} data-testid="sub-delete">
              <Trash2 size={13} /> Excluir
            </button>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost" onClick={onCancel}>
            <X size={14} /> Cancelar
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy}
            data-testid="sub-save">
            <Save size={14} /> {busy ? "Salvando…" : "Salvar"}
          </button>
        </div>
      </div>

      {/* iter215ba — Modal de confirmação do Reajuste IPCA */}
      {readjModal && readjPreview && (
        <ReadjustmentModal
          preview={readjPreview}
          busy={readjBusy}
          onConfirm={applyReadjustment}
          onClose={() => setReadjModal(false)} />
      )}
    </div>
  );
}

function SubscriberHistory({ subscriber, onClose }) {
  const [history, setHistory] = useState(null);
  useEffect(() => { api.subscribersHistory(subscriber.id).then(setHistory); }, [subscriber]);

  return (
    <div className="surface" style={{ padding: 22, borderRadius: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>
          Histórico — {subscriber.name}
        </h3>
        <button className="btn btn-ghost" onClick={onClose}>
          <X size={14} /> Fechar
        </button>
      </div>
      {!history && <div style={{ padding: 20, textAlign: "center" }}>Carregando…</div>}
      {history && (
        <>
          <h4 style={{ fontSize: 14, marginTop: 12 }}>Chamadas ({history.calls.length})</h4>
          {history.calls.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 8 }}>
              Sem chamadas registradas.
            </div>
          ) : history.calls.map((c) => (
            <div key={c.id} style={{
              padding: 10, border: "1px solid var(--border-default)",
              borderRadius: 8, marginBottom: 8, fontSize: 12,
            }}>
              <strong>{c.direction || "?"}</strong> · {c.status} · {c.started_at}
              {c.agent_name && <> · agente: {c.agent_name}</>}
              {c.summary && <div style={{ marginTop: 4 }}>{c.summary}</div>}
            </div>
          ))}
          <h4 style={{ fontSize: 14, marginTop: 16 }}>Conversas IA ({history.sessions.length})</h4>
          {history.sessions.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 8 }}>
              Sem conversas registradas.
            </div>
          ) : history.sessions.map((s) => (
            <div key={s.session_id} style={{
              padding: 10, border: "1px solid var(--border-default)",
              borderRadius: 8, marginBottom: 8, fontSize: 12,
            }}>
              <strong className="mono">{s.session_id.slice(-12)}</strong>
              · {s.msg_count} msgs · {s.last_at}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function CsvImporter({ onClose }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      setResult(await api.subscribersImport(fd));
    } catch (e) {
      setResult({ error: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="surface" style={{ padding: 22, borderRadius: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
        <h3 style={{ margin: 0 }}>Importar assinantes (CSV)</h3>
        <button className="btn btn-ghost" onClick={onClose}><X size={14} /></button>
      </div>
      <div style={{
        background: "var(--info-soft)", color: "var(--info-soft-fg)",
        padding: 12, borderRadius: 8, fontSize: 12, marginBottom: 14,
      }}>
        <strong>Colunas esperadas (PT-BR):</strong>
        <code style={{ display: "block", marginTop: 4, fontSize: 11 }}>
          nome, documento, codigo_externo, telefone_principal, telefone_2, email, status, plano, velocidade, valor, endereco, numero, bairro, cidade, estado, cep, observacoes, tags
        </code>
      </div>
      <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0])}
        data-testid="sub-csv-input" style={{ marginBottom: 12 }} />
      {result && (
        <div style={{
          padding: 12, marginBottom: 12, borderRadius: 8,
          background: result.error ? "var(--danger-soft)" : "var(--success-soft)",
          color: result.error ? "var(--danger-soft-fg)" : "var(--success-soft-fg)",
        }}>
          {result.error ? `Erro: ${result.error}` : (
            <>
              <strong>{result.created}</strong> criados ·
              <strong> {result.updated}</strong> atualizados ·
              <strong> {result.errors?.length || 0}</strong> erros ·
              <strong> {result.conflicts?.length || 0}</strong> conflitos
            </>
          )}
        </div>
      )}
      <button className="btn btn-primary" onClick={submit} disabled={!file || busy}
        data-testid="sub-csv-submit">
        <Upload size={13} /> {busy ? "Importando…" : "Importar"}
      </button>
    </div>
  );
}

function Field({ label, children, hint }) {
  // iter215az — flex column + label com flex:1 garante que o INPUT
  // fica sempre alinhado na base do cell, independente da altura do label.
  // Combinado com `alignItems: "end"` no grid pai, elimina lacunas verticais.
  return (
    <label style={{ display: "flex", flexDirection: "column",
                     marginTop: 10, marginBottom: 4, minWidth: 0 }}
      title={hint || undefined}>
      <div style={{ ...fieldLabelStyle, flex: 1 }}>{label}</div>
      {children}
    </label>
  );
}


/* iter215ba — Modal de confirmação para Aplicar Reajuste IPCA em cascata */
function ReadjustmentModal({ preview, busy, onConfirm, onClose }) {
  const fmtBRL = (v) => new Intl.NumberFormat("pt-BR", {
    style: "currency", currency: "BRL",
  }).format(v);
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(15,23,42,0.55)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 16,
    }}
      onClick={onClose} data-testid="readjustment-modal-backdrop">
      <div onClick={(e) => e.stopPropagation()}
        data-testid="readjustment-modal"
        style={{
          background: "#fff", borderRadius: 12, maxWidth: 640, width: "100%",
          maxHeight: "90vh", overflow: "auto",
          boxShadow: "0 20px 50px rgba(0,0,0,0.25)",
        }}>
        <div style={{
          padding: "16px 20px",
          borderBottom: "1px solid #e2e8f0",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700,
                         color: "#4b1d7a" }}>
            Aplicar reajuste — {preview.index_name}
          </h3>
          <button className="btn btn-ghost btn-sm" onClick={onClose}
            data-testid="readjustment-modal-close">
            <X size={14} />
          </button>
        </div>

        <div style={{ padding: 20 }}>
          <div style={{ fontSize: 12, color: "#475569", marginBottom: 12 }}>
            Você está prestes a aplicar{" "}
            <strong>{preview.pending_count} virada{preview.pending_count > 1 ? "s" : ""} de reajuste</strong>{" "}
            em cascata para <strong>{preview.name}</strong>. Cada virada usa o{" "}
            {preview.index_name} acumulado dos 12 meses anteriores à data-base.
          </div>

          <div style={{
            border: "1px solid #e2e8f0", borderRadius: 8,
            background: "#f8fafc", padding: 0, marginBottom: 16,
          }}>
            <table style={{ width: "100%", fontSize: 12,
                              borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                  <th style={{ padding: "8px 10px", fontWeight: 700,
                                 color: "#475569" }}>Virada</th>
                  <th style={{ padding: "8px 10px", fontWeight: 700,
                                 color: "#475569" }}>%</th>
                  <th style={{ padding: "8px 10px", fontWeight: 700,
                                 color: "#475569", textAlign: "right" }}>De</th>
                  <th style={{ padding: "8px 10px", fontWeight: 700,
                                 color: "#475569", textAlign: "right" }}>Para</th>
                </tr>
              </thead>
              <tbody>
                {(preview.cascade || []).map((step, i) => (
                  <tr key={i}
                    data-testid={`readjustment-step-${i}`}
                    style={{ borderTop: "1px solid #e2e8f0" }}>
                    <td style={{ padding: "8px 10px" }}>
                      {new Date(step.anniversary).toLocaleDateString("pt-BR")}
                    </td>
                    <td style={{ padding: "8px 10px",
                                   color: "#237a4b", fontWeight: 700 }}>
                      +{step.accumulated_pct.toFixed(2)}%
                    </td>
                    <td style={{ padding: "8px 10px", textAlign: "right",
                                   color: "#64748b" }}>
                      {fmtBRL(step.from_price)}
                    </td>
                    <td style={{ padding: "8px 10px", textAlign: "right",
                                   fontWeight: 700 }}>
                      {fmtBRL(step.to_price)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{
            background: "#fef9c3", border: "1px solid #fde68a",
            borderRadius: 8, padding: "10px 12px", fontSize: 12,
            color: "#92400e", marginBottom: 16,
          }}>
            <strong>Resumo:</strong> R$ {preview.current_price.toFixed(2)} →{" "}
            <strong>{fmtBRL(preview.new_price)}</strong>{" "}
            (+{preview.accumulated_pct_total.toFixed(2)}% acumulado)
          </div>

          <div style={{ display: "flex", gap: 8,
                          justifyContent: "flex-end" }}>
            <button className="btn btn-ghost" onClick={onClose}
              disabled={busy}
              data-testid="readjustment-cancel">
              Cancelar
            </button>
            <button
              onClick={onConfirm} disabled={busy}
              data-testid="readjustment-confirm"
              style={{
                padding: "8px 16px", fontSize: 13, fontWeight: 700,
                background: "#4b1d7a", color: "#fff",
                border: "none", borderRadius: 6,
                cursor: busy ? "wait" : "pointer",
                opacity: busy ? 0.6 : 1,
              }}>
              {busy ? "Aplicando…" : `Aplicar ${preview.pending_count} reajuste${preview.pending_count > 1 ? "s" : ""}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* iter215bb — Painel "Clientes sem plano" com bulk-assign */
function NoPlanReport({ onClose }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [branchFilter, setBranchFilter] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [plans, setPlans] = useState([]);
  const [planId, setPlanId] = useState("");
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const params = branchFilter
      ? { params: { branch: branchFilter, limit: 1000 } }
      : { params: { limit: 1000 } };
    client.get("/subscribers/reports/no-plan", params)
      .then((r) => { if (alive) { setData(r.data); setLoading(false); } })
      .catch(() => { if (alive) { setData(null); setLoading(false); } });
    return () => { alive = false; };
  }, [branchFilter]);

  useEffect(() => {
    api.plansList({ active: true })
      .then((r) => setPlans(r.items || []))
      .catch(() => setPlans([]));
  }, []);

  const items = data?.items || [];
  const allChecked = items.length > 0 && selected.size === items.length;
  const toggleAll = () => {
    if (allChecked) setSelected(new Set());
    else setSelected(new Set(items.map((it) => it.id)));
  };
  const toggleOne = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const applyBulk = async () => {
    if (!planId) {
      alert("Selecione um plano antes de aplicar.");
      return;
    }
    if (selected.size === 0) {
      alert("Selecione ao menos um cliente.");
      return;
    }
    const plan = plans.find((p) => p.id === planId);
    const msg = `Vincular o plano "${plan?.name}" `
      + `(R$ ${plan?.monthly_price?.toFixed(2)}/mês) a `
      + `${selected.size} cliente(s)?`;
    if (!window.confirm(msg)) return;
    setApplying(true);
    try {
      const r = await client.post("/subscribers/bulk-assign-plan", {
        subscriber_ids: Array.from(selected),
        plan_id: planId,
        only_without_plan: true,
      });
      const res = r.data;
      alert(`Sucesso!\n\n• Encontrados: ${res.matched}\n`
            + `• Atualizados: ${res.modified}\n\n`
            + `Esses clientes agora têm plan_price e o reajuste IPCA `
            + `pode ser calculado automaticamente.`);
      setSelected(new Set());
      const reload = await client.get("/subscribers/reports/no-plan",
        { params: { limit: 1000, ...(branchFilter
                                       ? { branch: branchFilter } : {}) } });
      setData(reload.data);
    } catch (e) {
      alert(`Erro: ${e?.response?.data?.detail || e?.message || e}`);
    } finally {
      setApplying(false);
    }
  };

  return (
    <div data-testid="no-plan-report" style={{ padding: "0 4px" }}>
      <div style={{ marginBottom: 18, display: "flex",
                      justifyContent: "space-between", alignItems: "center" }}>
        <h1 className="page-title" style={{ margin: 0 }}>
          Clientes sem plano vinculado
        </h1>
        <button className="btn btn-ghost btn-sm" onClick={onClose}
          data-testid="no-plan-close">
          <X size={14} /> Voltar
        </button>
      </div>

      <div className="surface" style={{
        padding: 16, borderRadius: 12, marginBottom: 16,
      }}>
        <div style={{ fontSize: 12, color: "#475569", marginBottom: 8 }}>
          Esses são clientes <strong>ATIVOS</strong> sem
          <code style={{ background: "#f1f5f9", padding: "1px 6px",
                          borderRadius: 4, margin: "0 4px" }}>
            plan_price
          </code>
          definido. Sem isso o motor de reajuste IPCA não consegue
          calcular o valor da próxima virada. Vincule um plano em lote
          pra regularizar o cadastro.
        </div>

        {loading && <div style={{ padding: 16 }}>Carregando…</div>}

        {!loading && data && (
          <>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: 12, marginBottom: 16,
            }}>
              <div style={{
                background: "#fef3c7", border: "1px solid #fde68a",
                borderRadius: 8, padding: 12,
              }}>
                <div style={{ fontSize: 10, fontWeight: 700,
                                color: "#92400e",
                                textTransform: "uppercase",
                                letterSpacing: 0.4 }}>
                  Total sem plano
                </div>
                <div style={{ fontSize: 24, fontWeight: 800,
                                color: "#78350f", marginTop: 2 }}
                  data-testid="no-plan-total">
                  {data.count}
                </div>
              </div>
              {(data.by_branch || []).slice(0, 4).map((b) => (
                <div key={b.branch}
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: 8, padding: 12, cursor: "pointer",
                  }}
                  onClick={() => setBranchFilter(
                    branchFilter === b.branch ? "" : b.branch)}
                  data-testid={`no-plan-branch-${b.branch}`}>
                  <div style={{ fontSize: 10, fontWeight: 700,
                                  color: "#64748b",
                                  textTransform: "uppercase",
                                  letterSpacing: 0.4 }}>
                    {b.branch}
                    {branchFilter === b.branch && (
                      <span style={{ marginLeft: 4, color: "#4b1d7a" }}>
                        ✓
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 700,
                                  color: "#0f172a", marginTop: 2 }}>
                    {b.count}
                  </div>
                </div>
              ))}
            </div>

            <div style={{
              display: "flex", gap: 8, alignItems: "center",
              padding: "10px 12px",
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: 8, marginBottom: 12,
            }}>
              <strong style={{ fontSize: 12 }}>Vincular em lote:</strong>
              <select className="input"
                data-testid="no-plan-select-plan"
                value={planId}
                onChange={(e) => setPlanId(e.target.value)}
                style={{ minWidth: 280, fontSize: 12 }}>
                <option value="">— Escolha um plano —</option>
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {`${p.name} · ${p.speed_label || ""} · `
                     + new Intl.NumberFormat("pt-BR",
                                              { style: "currency",
                                                  currency: "BRL" })
                       .format(p.monthly_price || 0)}
                  </option>
                ))}
              </select>
              <button
                data-testid="no-plan-apply-btn"
                disabled={applying || selected.size === 0 || !planId}
                onClick={applyBulk}
                style={{
                  padding: "6px 14px", fontSize: 12, fontWeight: 700,
                  background: "#4b1d7a", color: "#fff",
                  border: "none", borderRadius: 6,
                  cursor: applying ? "wait" : "pointer",
                  opacity: applying || selected.size === 0 || !planId
                    ? 0.5 : 1,
                }}>
                {applying ? "Aplicando…"
                  : `Aplicar a ${selected.size} selecionado(s)`}
              </button>
              {branchFilter && (
                <button className="btn btn-ghost btn-sm"
                  onClick={() => setBranchFilter("")}
                  data-testid="no-plan-clear-filter">
                  Limpar filtro
                </button>
              )}
            </div>

            <div style={{ maxHeight: 540, overflow: "auto",
                            border: "1px solid #e2e8f0",
                            borderRadius: 8 }}>
              <table style={{ width: "100%", borderCollapse: "collapse",
                                fontSize: 12 }}>
                <thead style={{ position: "sticky", top: 0,
                                  background: "#f1f5f9", zIndex: 1 }}>
                  <tr>
                    <th style={{ padding: "10px 12px", textAlign: "left" }}>
                      <input type="checkbox" checked={allChecked}
                        onChange={toggleAll}
                        data-testid="no-plan-select-all" />
                    </th>
                    <th style={{ padding: "10px 12px", textAlign: "left",
                                   color: "#475569" }}>Nome</th>
                    <th style={{ padding: "10px 12px", textAlign: "left",
                                   color: "#475569" }}>Filial</th>
                    <th style={{ padding: "10px 12px", textAlign: "left",
                                   color: "#475569" }}>ID</th>
                    <th style={{ padding: "10px 12px", textAlign: "left",
                                   color: "#475569" }}>Instalação</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.id}
                      data-testid={`no-plan-row-${it.id}`}
                      style={{ borderTop: "1px solid #e2e8f0" }}>
                      <td style={{ padding: "8px 12px" }}>
                        <input type="checkbox"
                          checked={selected.has(it.id)}
                          onChange={() => toggleOne(it.id)} />
                      </td>
                      <td style={{ padding: "8px 12px",
                                     fontWeight: 600 }}>
                        {it.name || "—"}
                      </td>
                      <td style={{ padding: "8px 12px" }}>
                        {it.branch || "—"}
                      </td>
                      <td style={{ padding: "8px 12px",
                                     fontFamily: "monospace",
                                     fontSize: 11, color: "#64748b" }}>
                        {it.external_code || "—"}
                      </td>
                      <td style={{ padding: "8px 12px",
                                     color: "#64748b" }}>
                        {it.installation_date
                          ? new Date(it.installation_date)
                              .toLocaleDateString("pt-BR")
                          : "—"}
                      </td>
                    </tr>
                  ))}
                  {items.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{
                        padding: 24, textAlign: "center",
                        color: "#64748b",
                      }}>
                        Nenhum cliente sem plano encontrado.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

