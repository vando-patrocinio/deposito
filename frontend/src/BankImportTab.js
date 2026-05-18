/*
BankImportTab.js — Sub-aba "Importar Extrato" do Financeiro.

Fluxo:
  1) Upload do arquivo OFX/CSV do Sicoob.
  2) IA Claude Sonnet 4.5 classifica entradas/saídas e sugere fornecedor/categoria.
  3) Padrões aprendidos (CPF/CNPJ + nomenclatura) preenchem automaticamente nas
     próximas importações — economiza chamadas LLM e mantém consistência.
  4) Gestor revisa a tabela editável e confirma — gera fin_cash_movements.
*/
import React, { useEffect, useState, useRef } from "react";
import { api } from "@/api";
import { Card, Button } from "@/ui";
import {
  Upload, Brain, Database, CheckCircle2, AlertCircle, Trash2,
  Loader2, FileText, History as HistoryIcon, ArrowUp, ArrowDown,
  ChevronDown, ChevronRight,
} from "lucide-react";
import { KpiCard, AlertCard } from "@/components/Dashboard2026";

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL" });
const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso + (iso.length === 10 ? "T12:00:00" : ""))
      .toLocaleDateString("pt-BR");
  } catch { return iso; }
};

const SOURCE_BADGE = {
  ai:      { bg: "#ede9fe", color: "#6d28d9", icon: Brain,
              label: "IA Claude" },
  memory:  { bg: "#dbeafe", color: "#1e40af", icon: Database,
              label: "Aprendido" },
  manual:  { bg: "#f1f5f9", color: "#475569", icon: AlertCircle,
              label: "Manual" },
};

export default function BankImportTab() {
  const [staging, setStaging] = useState(null);
  const [items, setItems] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [refs, setRefs] = useState({
    cash_accounts: [], suppliers: [], categories: [],
  });
  const [cashAccountId, setCashAccountId] = useState("");
  const [history, setHistory] = useState([]);
  const [memory, setMemory] = useState([]);
  const [showMemory, setShowMemory] = useState(false);
  const fileRef = useRef(null);

  async function loadRefs() {
    const [ca, sp, cat] = await Promise.all([
      api.finCashAccountsList(true),
      api.finSuppliersList(true),
      api.finCategoriesList(true),
    ]);
    setRefs({ cash_accounts: ca, suppliers: sp, categories: cat });
    if (ca[0] && !cashAccountId) setCashAccountId(ca[0].id);
  }
  async function loadHistory() {
    try {
      const h = await api.bankImportHistory(20);
      setHistory(h.items || []);
    } catch (e) { /* silent */ }
  }
  async function loadMemory() {
    try {
      const m = await api.bankImportMemory(200);
      setMemory(m.items || []);
    } catch (e) { /* silent */ }
  }
  useEffect(() => { loadRefs(); loadHistory(); loadMemory(); }, []);

  async function onUpload(file) {
    setErr(""); setOk(""); setUploading(true);
    try {
      const r = await api.bankImportUpload(file);
      setStaging(r);
      setItems((r.items || []).map((it) => ({ ...it, _skip: it.duplicate })));
      // Alerta amigável quando IA falhou (todas as não-duplicadas/não-memória ficaram 'manual')
      const nonDup = (r.items || []).filter((it) => !it.duplicate);
      const aiOrMem = nonDup.filter((it) =>
        it.source === "ai" || it.source === "memory");
      if (nonDup.length > 0 && aiOrMem.length === 0) {
        setErr(
          "A IA não conseguiu classificar (provavelmente sem créditos ou "
          + "instabilidade). Você ainda pode classificar manualmente abaixo.",
        );
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setUploading(false); }
  }

  function updateItem(idx, patch) {
    setItems((arr) => arr.map((it) => it.idx === idx ? { ...it, ...patch } : it));
  }

  async function onConfirm() {
    if (!cashAccountId) { setErr("Selecione a conta caixa de destino."); return; }
    setErr(""); setConfirming(true);
    try {
      const payload = {
        staging_id: staging.staging_id,
        items: items.map((it) => ({
          idx: it.idx,
          type: it.type,
          date: it.date,
          amount: it.amount,
          description: it.description,
          cash_account_id: cashAccountId,
          supplier_id: it.supplier_id || null,
          category_id: it.category_id || null,
          skip: !!it._skip || it.duplicate,
        })),
      };
      const r = await api.bankImportConfirm(payload);
      setOk(`✓ ${r.created} lançamento(s) gerado(s). ${r.skipped} ignorado(s).`);
      setStaging(null); setItems([]);
      if (fileRef.current) fileRef.current.value = "";
      loadHistory(); loadMemory();
      setTimeout(() => setOk(""), 4500);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setConfirming(false); }
  }

  const newCount = items.filter((it) => !it.duplicate && !it._skip).length;
  const incomeSum = items.filter(
    (it) => !it.duplicate && !it._skip && it.type === "income")
    .reduce((s, it) => s + Number(it.amount || 0), 0);
  const expenseSum = items.filter(
    (it) => !it.duplicate && !it._skip && it.type === "expense")
    .reduce((s, it) => s + Number(it.amount || 0), 0);
  const aiCount = items.filter((it) => it.source === "ai").length;
  const memCount = items.filter((it) => it.source === "memory").length;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {/* Header / upload */}
      <Card title={(
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Upload size={16} /> Importar Extrato Bancário (Sicoob)
        </span>
      )}
        data-testid="bank-import-upload-card">
        <div style={{ display: "grid",
                        gridTemplateColumns: "1fr auto", gap: 12,
                        alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 13, color: "#475569", lineHeight: 1.5 }}>
              Envie o arquivo <strong>OFX</strong> ou <strong>CSV</strong>
              {" "}exportado do Sicoob. A IA Claude Sonnet 4.5 classifica cada
              transação como entrada/saída e sugere fornecedor + categoria.
              Padrões aprendidos por CPF/CNPJ aceleram as próximas importações.
            </div>
            <div style={{ marginTop: 6, fontSize: 11.5, color: "#64748b" }}>
              💡 Sicoob → Internet Banking → Extrato → Exportar OFX
            </div>
          </div>
          <div>
            <input ref={fileRef} type="file" accept=".ofx,.OFX,.csv,.CSV"
                    data-testid="bank-import-file-input"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) onUpload(f);
                    }}
                    disabled={uploading}
                    style={{ fontSize: 12 }} />
          </div>
        </div>
        {uploading && (
          <div data-testid="bank-import-uploading"
                style={{ marginTop: 10, padding: 10,
                          background: "#dbeafe", borderRadius: 8,
                          fontSize: 12, color: "#1e40af",
                          display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Loader2 size={14} className="animate-spin" />
            Processando arquivo · IA classificando transações…
          </div>
        )}
        {err && (
          <div data-testid="bank-import-err"
                style={{ marginTop: 10, padding: 10,
                          background: "#fee2e2", borderRadius: 8,
                          color: "#991b1b", fontSize: 12 }}>
            ⚠ {typeof err === "string" ? err : "Erro"}
          </div>
        )}
        {ok && (
          <div data-testid="bank-import-ok"
                style={{ marginTop: 10, padding: 10,
                          background: "#dcfce7", borderRadius: 8,
                          color: "#15803d", fontSize: 12 }}>
            {ok}
          </div>
        )}
      </Card>

      {/* Preview/staging */}
      {staging && items.length > 0 && (
        <>
          {/* KPIs do staging */}
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))",
                          gap: 12 }}>
            <KpiCard testId="bi-kpi-new"
              label="Novas transações" value={newCount}
              tone="info"
              hint={`${staging.total} no total · ${staging.duplicate_count} duplicada(s)`} />
            <KpiCard testId="bi-kpi-income"
              label="Entradas" value={fmtMoney(incomeSum)} tone="good" />
            <KpiCard testId="bi-kpi-expense"
              label="Saídas" value={fmtMoney(expenseSum)} tone="bad" />
            <KpiCard testId="bi-kpi-ai"
              label="Classificadas por IA" value={aiCount}
              tone="info"
              hint={`${memCount} via memória aprendida`}
              icon={<Brain size={11} />} />
          </div>

          {staging.duplicate_count > 0 && (
            <AlertCard tone="info" icon="🔁"
              testId="bi-alert-duplicates"
              title={`${staging.duplicate_count} transação(ões) já existem no caixa`}
              detail="Foram marcadas para ignorar (caixinha desmarcada). Você pode reativar manualmente." />
          )}

          {/* Tabela editável */}
          <Card title="Revisar e confirmar transações"
                action={(
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <label style={{ fontSize: 12, color: "#64748b" }}>
                      Conta caixa:
                    </label>
                    <select value={cashAccountId}
                              onChange={(e) => setCashAccountId(e.target.value)}
                              data-testid="bi-cash-account-select"
                              style={{ padding: "6px 10px",
                                        border: "1px solid #cbd5e1",
                                        borderRadius: 6, fontSize: 12 }}>
                      <option value="">Selecione…</option>
                      {refs.cash_accounts.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                    <Button onClick={onConfirm}
                              data-testid="bi-confirm-btn"
                              disabled={confirming || !cashAccountId
                                              || newCount === 0}>
                      {confirming ? (<><Loader2 size={14}
                        className="animate-spin" /> Confirmando…</>)
                       : (<><CheckCircle2 size={14} /> Confirmar {newCount} lançamento{newCount !== 1 ? "s" : ""}</>)}
                    </Button>
                  </div>
                )}>
            <div style={{ overflowX: "auto" }}
                 data-testid="bi-items-table">
              <table style={{ width: "100%", borderCollapse: "collapse",
                                fontSize: 12.5 }}>
                <thead>
                  <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                    <th style={th}></th>
                    <th style={th}>Data</th>
                    <th style={th}>Descrição</th>
                    <th style={th}>Tipo</th>
                    <th style={{ ...th, textAlign: "right" }}>Valor</th>
                    <th style={th}>Fornecedor</th>
                    <th style={th}>Categoria</th>
                    <th style={th}>Origem</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => {
                    const src = SOURCE_BADGE[it.source] || SOURCE_BADGE.manual;
                    const IconSrc = src.icon;
                    const isDup = it.duplicate;
                    const isSkip = it._skip;
                    return (
                      <tr key={it.idx}
                          data-testid={`bi-row-${it.idx}`}
                          style={{
                            borderTop: "1px solid #f1f5f9",
                            opacity: isSkip ? 0.4 : 1,
                            background: isDup ? "#fef3c7" : "transparent",
                          }}>
                        <td style={td}>
                          <input type="checkbox"
                            data-testid={`bi-check-${it.idx}`}
                            checked={!isSkip}
                            onChange={(e) =>
                              updateItem(it.idx, { _skip: !e.target.checked })} />
                        </td>
                        <td style={td}>{fmtDate(it.date)}</td>
                        <td style={{ ...td, maxWidth: 280 }}>
                          <div style={{ fontWeight: 600, color: "#0f172a" }}>
                            {it.description}
                          </div>
                          {it.doc && (
                            <div style={{ fontSize: 10, color: "#64748b",
                                              fontFamily: "monospace",
                                              marginTop: 2 }}>
                              {it.doc.length === 11 ? "CPF" : "CNPJ"} {it.doc}
                            </div>
                          )}
                          {it.reason && (
                            <div style={{ fontSize: 10, color: "#94a3b8",
                                              marginTop: 2, fontStyle: "italic" }}>
                              💡 {it.reason}
                            </div>
                          )}
                        </td>
                        <td style={td}>
                          <select value={it.type}
                                    data-testid={`bi-type-${it.idx}`}
                                    onChange={(e) =>
                                      updateItem(it.idx, { type: e.target.value })}
                                    style={{
                                      padding: "4px 6px", fontSize: 11,
                                      border: "1px solid #cbd5e1",
                                      borderRadius: 4,
                                      background: it.type === "income"
                                        ? "#dcfce7" : "#fee2e2",
                                      color: it.type === "income"
                                        ? "#15803d" : "#b91c1c",
                                      fontWeight: 700,
                                    }}>
                            <option value="income">↑ Entrada</option>
                            <option value="expense">↓ Saída</option>
                          </select>
                        </td>
                        <td style={{ ...td, textAlign: "right",
                                      fontWeight: 700, fontFamily: "monospace",
                                      color: it.type === "income"
                                        ? "#15803d" : "#b91c1c" }}>
                          {fmtMoney(it.amount)}
                        </td>
                        <td style={td}>
                          <select value={it.supplier_id || ""}
                                    data-testid={`bi-supplier-${it.idx}`}
                                    onChange={(e) =>
                                      updateItem(it.idx,
                                        { supplier_id: e.target.value || null })}
                                    style={selectStyle}>
                            <option value="">—</option>
                            {refs.suppliers.map((s) => (
                              <option key={s.id} value={s.id}>{s.name}</option>
                            ))}
                          </select>
                        </td>
                        <td style={td}>
                          <select value={it.category_id || ""}
                                    data-testid={`bi-category-${it.idx}`}
                                    onChange={(e) =>
                                      updateItem(it.idx,
                                        { category_id: e.target.value || null })}
                                    style={selectStyle}>
                            <option value="">—</option>
                            {refs.categories
                              .filter((c) => !c.type || c.type === it.type)
                              .map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                              ))}
                          </select>
                        </td>
                        <td style={td}>
                          <span style={{
                            display: "inline-flex", alignItems: "center", gap: 4,
                            padding: "2px 8px", borderRadius: 999,
                            background: src.bg, color: src.color,
                            fontSize: 10, fontWeight: 700,
                          }}>
                            <IconSrc size={10} /> {src.label}
                            {it.confidence > 0 && (
                              <span style={{ opacity: 0.7 }}>
                                {Math.round(it.confidence * 100)}%
                              </span>
                            )}
                          </span>
                          {isDup && (
                            <div style={{ fontSize: 9, color: "#a16207",
                                              fontWeight: 700, marginTop: 2 }}>
                              ⚠ Já no caixa
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {/* Padrões aprendidos */}
      <Card title={(
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6,
                          cursor: "pointer" }}
              onClick={() => setShowMemory((v) => !v)}>
          {showMemory ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Database size={14} /> Padrões aprendidos pela IA ({memory.length})
        </span>
      )}>
        <div style={{ fontSize: 11.5, color: "#64748b", marginBottom: 8 }}>
          Cada confirmação ensina a IA a reconhecer o mesmo CPF/CNPJ + descrição
          nas próximas importações — sem precisar chamar o LLM de novo.
        </div>
        {showMemory && (
          <div style={{ overflowX: "auto" }} data-testid="bi-memory-table">
            {memory.length === 0 ? (
              <div style={{ padding: 14, fontSize: 12, color: "#94a3b8",
                              textAlign: "center" }}>
                Nenhum padrão aprendido ainda — confirme algumas importações para
                a IA começar a memorizar.
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse",
                                fontSize: 12 }}>
                <thead>
                  <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                    <th style={th}>CPF/CNPJ</th>
                    <th style={th}>Padrão</th>
                    <th style={th}>Tipo</th>
                    <th style={th}>Fornecedor</th>
                    <th style={th}>Categoria</th>
                    <th style={{ ...th, textAlign: "center" }}>Aplicado</th>
                    <th style={th}></th>
                  </tr>
                </thead>
                <tbody>
                  {memory.map((m) => {
                    const sup = refs.suppliers.find(
                      (s) => s.id === m.supplier_id);
                    const cat = refs.categories.find(
                      (c) => c.id === m.category_id);
                    return (
                      <tr key={m.id}
                          data-testid={`bi-memory-row-${m.id}`}
                          style={{ borderTop: "1px solid #f1f5f9" }}>
                        <td style={{ ...td, fontFamily: "monospace",
                                      fontSize: 11 }}>
                          {m.doc || "—"}
                        </td>
                        <td style={{ ...td, maxWidth: 240, fontSize: 11,
                                      color: "#475569" }}>
                          {m.key}
                        </td>
                        <td style={td}>
                          {m.type === "income" ? (
                            <span style={{ color: "#15803d", fontWeight: 600 }}>
                              <ArrowUp size={11} /> Entrada
                            </span>
                          ) : (
                            <span style={{ color: "#b91c1c", fontWeight: 600 }}>
                              <ArrowDown size={11} /> Saída
                            </span>
                          )}
                        </td>
                        <td style={td}>{sup?.name || "—"}</td>
                        <td style={td}>{cat?.name || "—"}</td>
                        <td style={{ ...td, textAlign: "center",
                                      fontWeight: 700, color: "#0ea5e9" }}>
                          {m.hit_count}×
                        </td>
                        <td style={td}>
                          <button
                            data-testid={`bi-memory-del-${m.id}`}
                            onClick={async () => {
                              if (!window.confirm("Apagar este padrão?")) return;
                              await api.bankImportMemoryDelete(m.id);
                              loadMemory();
                            }}
                            style={{ border: "none", background: "transparent",
                                      cursor: "pointer", color: "#dc2626" }}>
                            <Trash2 size={12} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </Card>

      {/* Histórico */}
      <Card title={(
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <HistoryIcon size={14} /> Histórico de importações ({history.length})
        </span>
      )}>
        {history.length === 0 ? (
          <div style={{ padding: 14, fontSize: 12, color: "#94a3b8",
                          textAlign: "center" }}>
            Nenhuma importação concluída ainda.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 12 }} data-testid="bi-history-table">
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={th}>Data</th>
                <th style={th}>Arquivo</th>
                <th style={{ ...th, textAlign: "center" }}>Total</th>
                <th style={{ ...th, textAlign: "center" }}>Importados</th>
                <th style={{ ...th, textAlign: "center" }}>Ignorados</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}
                    data-testid={`bi-history-row-${h.id}`}
                    style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={td}>
                    {h.created_at ? new Date(h.created_at)
                      .toLocaleString("pt-BR",
                        { dateStyle: "short", timeStyle: "short" }) : "—"}
                  </td>
                  <td style={{ ...td, fontFamily: "monospace", fontSize: 11 }}>
                    <FileText size={11}
                      style={{ verticalAlign: "middle", marginRight: 4 }} />
                    {h.file_name || "—"}
                  </td>
                  <td style={{ ...td, textAlign: "center" }}>{h.total}</td>
                  <td style={{ ...td, textAlign: "center",
                                color: "#15803d", fontWeight: 700 }}>
                    {h.created_count}
                  </td>
                  <td style={{ ...td, textAlign: "center", color: "#94a3b8" }}>
                    {h.skipped_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

const th = {
  padding: "8px 10px", fontSize: 10.5, fontWeight: 800,
  color: "#475569", textTransform: "uppercase", letterSpacing: 0.4,
  borderBottom: "1px solid #e2e8f0",
};
const td = {
  padding: "8px 10px", verticalAlign: "middle",
};
const selectStyle = {
  padding: "4px 6px", fontSize: 11, border: "1px solid #e2e8f0",
  borderRadius: 4, background: "#fff", minWidth: 110,
};
