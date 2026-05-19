/**
 * BudgetPanel — módulo Comercial · Orçamento_IA
 *
 * Fluxo:
 *  1) Lista de orçamentos + KPIs no topo
 *  2) Botão "Novo orçamento" → form (nome + descrição) → upload CSV
 *  3) Botão "Analisar com IA" dispara Claude que estima 3 preços/item + média
 *  4) Drawer de revisão: tabela editável (override unitário) + sliders
 *     %ganho · %imposto · %mão-de-obra, recalculo automático dos totais
 *  5) Botão "Imprimir PDF" abre o romaneio em nova aba
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Calculator, Upload, Sparkles, Printer, Trash2, Plus, FileText,
  Loader2, X, Search, TrendingUp, DollarSign, Percent,
} from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/AuthContext";

const fmtMoney = (v) => `R$ ${Number(v || 0).toLocaleString("pt-BR", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})}`;

const statusBadge = (s) => {
  const map = {
    draft: { color: "#64748b", bg: "rgba(100,116,139,.15)", label: "Rascunho" },
    analyzed: { color: "#0d9488", bg: "rgba(13,148,136,.15)", label: "Analisado" },
    final: { color: "#16a34a", bg: "rgba(22,163,74,.15)", label: "Finalizado" },
  };
  return map[s] || map.draft;
};

export default function BudgetPanel() {
  const { token } = useAuth();
  const [budgets, setBudgets] = useState([]);
  const [kpis, setKpis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState(null); // budget aberto no drawer
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [list, k] = await Promise.all([api.budgetList(), api.budgetKpis()]);
      setBudgets(list.items || []);
      setKpis(k);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return budgets;
    return budgets.filter((b) =>
      (b.name || "").toLowerCase().includes(q) ||
      (b.description || "").toLowerCase().includes(q)
    );
  }, [budgets, search]);

  return (
    <div data-testid="budget-panel" style={{
      padding: "20px 24px", maxWidth: 1280, margin: "0 auto",
    }}>
      <header style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 18,
      }}>
        <div>
          <h2 style={{
            margin: 0, fontSize: 22, fontWeight: 700,
            color: "var(--text-primary)",
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <Calculator size={22} strokeWidth={2} style={{ color: "#0ea5e9" }} />
            Orçamento <span style={{
              fontSize: 11, padding: "3px 8px", borderRadius: 6,
              background: "linear-gradient(135deg,#0ea5e9,#22d3ee)",
              color: "#fff", fontWeight: 700, letterSpacing: 0.5,
            }}>IA</span>
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
            Sobe um CSV de itens, deixa a Orçamento_IA estimar 3 preços por item,
            ajusta % de ganho/imposto/mão-de-obra e imprime o romaneio.
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} data-testid="budget-new-btn"
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "10px 18px", borderRadius: 8,
                  background: "linear-gradient(180deg,#0ea5e9,#0284c7)",
                  color: "#fff", fontWeight: 700, fontSize: 13,
                  border: "none", cursor: "pointer",
                  boxShadow: "0 1px 3px rgba(2,132,199,.4)",
                }}>
          <Plus size={15} strokeWidth={2.5} /> Novo orçamento
        </button>
      </header>

      {/* KPIs */}
      {kpis && (
        <div data-testid="budget-kpis" style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))",
          gap: 12, marginBottom: 20,
        }}>
          <Kpi icon={FileText} label="Orçamentos" value={kpis.total}
                detail={`${kpis.draft} rasc. · ${kpis.analyzed} anal. · ${kpis.final} final`}
                color="#0ea5e9" />
          <Kpi icon={DollarSign} label="Valor total" value={fmtMoney(kpis.total_value)}
                detail={`Média: ${fmtMoney(kpis.avg_value)}`} color="#16a34a" />
          <Kpi icon={Percent} label="Margem média" value={`${kpis.avg_margin_pct}%`}
                detail="Configurado por orçamento" color="#a78bfa" />
          <Kpi icon={TrendingUp} label="Finalizados"
                value={`${kpis.final} / ${kpis.total}`}
                detail={kpis.total ? `${Math.round(kpis.final / kpis.total * 100)}% conversão` : "—"}
                color="#f59e0b" />
        </div>
      )}

      {/* Busca */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
        borderRadius: 8, background: "var(--bg-surface)",
        border: "1px solid var(--border-default)", marginBottom: 12, maxWidth: 360,
      }}>
        <Search size={14} style={{ color: "var(--text-muted)" }} />
        <input value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder="Buscar orçamento..."
               data-testid="budget-search-input"
               style={{
                 flex: 1, border: "none", outline: "none", background: "transparent",
                 fontSize: 13, color: "var(--text-primary)",
               }} />
      </div>

      {/* Lista */}
      {error && (
        <div data-testid="budget-error" style={{
          padding: 12, borderRadius: 8, background: "rgba(239,68,68,.1)",
          color: "#dc2626", marginBottom: 12, fontSize: 13,
        }}>
          {error}
        </div>
      )}
      {loading ? (
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}>
          <Loader2 size={28} style={{ animation: "wa-spin 1s linear infinite" }} />
        </div>
      ) : filtered.length === 0 ? (
        <div style={{
          padding: 40, textAlign: "center", color: "var(--text-muted)",
          background: "var(--bg-surface)", borderRadius: 10,
          border: "1px dashed var(--border-default)",
        }}>
          <Calculator size={40} strokeWidth={1.5} style={{ opacity: 0.4 }} />
          <p style={{ marginTop: 12, fontSize: 13 }}>
            Nenhum orçamento criado ainda. Clique em "Novo orçamento" para começar.
          </p>
        </div>
      ) : (
        <div data-testid="budget-list" style={{ display: "grid", gap: 8 }}>
          {filtered.map((b) => (
            <BudgetRow key={b.id} budget={b} onOpen={() => setEditing(b)}
                        onChanged={load} token={token} />
          ))}
        </div>
      )}

      {/* Modais */}
      {showCreate && (
        <CreateBudgetModal onClose={() => setShowCreate(false)} onCreated={(b) => {
          setShowCreate(false);
          setEditing(b);
          load();
        }} />
      )}
      {editing && (
        <BudgetDrawer budget={editing}
                       onClose={() => { setEditing(null); load(); }}
                       token={token}
                       onChanged={load} />
      )}
    </div>
  );
}

function Kpi({ icon: Ico, label, value, detail, color }) {
  return (
    <div data-testid={`budget-kpi-${label.toLowerCase().replace(/\s+/g, '-')}`}
         style={{
      padding: 14, borderRadius: 10,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${color}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        <Ico size={14} style={{ color }} />
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
                        textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)",
                    lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>{detail}</div>
    </div>
  );
}

function BudgetRow({ budget, onOpen, onChanged, token }) {
  const sb = statusBadge(budget.status);
  const totals = budget.totals || {};
  async function handleDelete(e) {
    e.stopPropagation();
    if (!await window.confirm(`Excluir "${budget.name}"?`)) return;
    try {
      await api.budgetDelete(budget.id);
      onChanged();
    } catch (err) {
      await window.alert(err?.response?.data?.detail || err.message);
    }
  }
  return (
    <button onClick={onOpen} data-testid={`budget-row-${budget.id}`}
            style={{
      display: "grid", gridTemplateColumns: "1fr auto auto auto auto",
      gap: 16, alignItems: "center",
      padding: "12px 16px", borderRadius: 10,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      cursor: "pointer", textAlign: "left", color: "var(--text-primary)",
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>{budget.name}</span>
          <span style={{
            padding: "2px 7px", borderRadius: 5, fontSize: 10, fontWeight: 700,
            background: sb.bg, color: sb.color,
          }}>{sb.label}</span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {budget.description || "Sem descrição"}
        </div>
      </div>
      <Stat label="Itens" value={(budget.items || []).length} />
      <Stat label="Margem" value={`${budget.margin_pct || 0}%`} />
      <Stat label="Total" value={fmtMoney(totals.final || 0)} bold />
      <button onClick={handleDelete} title="Excluir"
              data-testid={`budget-delete-${budget.id}`}
              style={{
                padding: 6, borderRadius: 6, border: "none",
                background: "transparent", cursor: "pointer",
                color: "var(--text-muted)",
              }}>
        <Trash2 size={14} />
      </button>
    </button>
  );
}

function Stat({ label, value, bold }) {
  return (
    <div style={{ textAlign: "right", minWidth: 70 }}>
      <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase",
                    letterSpacing: 0.4, fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: bold ? 14 : 12, fontWeight: bold ? 800 : 600,
                    color: "var(--text-primary)", marginTop: 2 }}>{value}</div>
    </div>
  );
}

/* ------- Create modal ------- */
function CreateBudgetModal({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(ev) {
    ev.preventDefault();
    if (name.trim().length < 2) { setErr("Nome muito curto"); return; }
    setBusy(true); setErr("");
    try {
      const b = await api.budgetCreate({ name: name.trim(), description });
      onCreated(b);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal onClose={onClose} title="Novo orçamento" testid="budget-create-modal">
      <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}>
          Nome
          <input value={name} onChange={(e) => setName(e.target.value)}
                  data-testid="budget-create-name"
                  placeholder='Ex: "Obra CTO-Centro · Expansão"' autoFocus
                  style={inputStyle} />
        </label>
        <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}>
          Descrição
          <textarea value={description} onChange={(e) => setDescription(e.target.value)}
                    data-testid="budget-create-desc"
                    placeholder="Detalhes do projeto (opcional)" rows={3}
                    style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }} />
        </label>
        {err && <div style={{ fontSize: 12, color: "#dc2626" }}>{err}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 6 }}>
          <button type="button" onClick={onClose} style={btnGhost}>Cancelar</button>
          <button type="submit" disabled={busy} data-testid="budget-create-submit"
                  style={btnPrimary}>
            {busy ? "Criando..." : "Criar e subir arquivo"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ------- Drawer com tabela editável ------- */
function BudgetDrawer({ budget: initial, onClose, onChanged, token }) {
  const [budget, setBudget] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef(null);

  const totals = budget.totals || {};

  async function refresh() {
    try {
      const b = await api.budgetGet(budget.id);
      setBudget(b);
    } catch (e) { setErr(e.message); }
  }

  async function handleUpload(file) {
    if (!file) return;
    setBusy(true); setErr("");
    try {
      const r = await api.budgetUploadCsv(budget.id, file);
      await refresh();
      if (r?.ready_to_print) {
        // Modo "Importar pronto" — orçamento já tem preços, abre PDF direto.
        const ok = await window.confirm(
          `✓ ${r.items_count} item(ns) extraído(s) — `
          + `${r.items_with_price} com preço já preenchido.\n\n`
          + "Abrir o PDF para imprimir agora?",
        );
        if (ok) window.open(api.budgetPdfUrl(budget.id), "_blank");
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  async function handleAnalyze() {
    if (!await window.confirm("A Orçamento_IA vai analisar os itens e estimar 3 preços por item. Pode levar até 30s. Continuar?")) return;
    setAnalyzing(true); setErr("");
    try {
      await api.budgetAnalyze(budget.id);
      await refresh();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setAnalyzing(false); }
  }

  async function handlePersist(patch) {
    setBusy(true);
    try {
      const b = await api.budgetUpdate(budget.id, patch);
      setBudget(b);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  async function handleItemPriceOverride(itemId, valueStr) {
    const value = valueStr === "" || valueStr === null ? null : parseFloat(valueStr);
    const items = (budget.items || []).map((it) =>
      it.id === itemId ? { ...it, id: it.id, manual_override: value } : { id: it.id }
    );
    await handlePersist({ items });
  }

  async function handlePriceChoice(itemId, choice) {
    // choice: "low" | "mid" | "high"
    // Trocar a opção também limpa o manual_override pra não conflitar.
    const items = (budget.items || []).map((it) =>
      it.id === itemId
        ? { ...it, id: it.id, price_choice: choice, manual_override: null }
        : { id: it.id }
    );
    await handlePersist({ items });
  }

  function openPdf() {
    const url = api.budgetPdfUrl(budget.id);
    // Abre em nova aba com Authorization no header via cookie temp:
    // Como o backend usa JWT bearer, precisamos GET com fetch + blob
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob);
        window.open(blobUrl, "_blank");
        setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
        refresh();  // atualiza status pra "final"
      })
      .catch((e) => setErr(`Erro ao gerar PDF: ${e.message}`));
  }

  const itemCount = (budget.items || []).length;
  const hasPrices = (budget.items || []).some((it) => (it.avg_price || 0) > 0);

  return (
    <div data-testid="budget-drawer" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.55)",
      backdropFilter: "blur(2px)", zIndex: 100,
      display: "flex", justifyContent: "flex-end",
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "min(960px, 96vw)", background: "var(--bg-surface)",
        height: "100vh", overflowY: "auto",
        boxShadow: "-8px 0 32px rgba(15,23,42,.3)",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{
          padding: "16px 22px", borderBottom: "1px solid var(--border-default)",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontSize: 11, color: "var(--text-muted)",
                            textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.5 }}>
              Orçamento
            </div>
            <h3 style={{ margin: "2px 0 0", fontSize: 18, fontWeight: 800,
                          color: "var(--text-primary)" }}>{budget.name}</h3>
          </div>
          <button onClick={onClose} data-testid="budget-drawer-close"
                  style={{
                    padding: 6, borderRadius: 6, border: "none",
                    background: "var(--bg-surface-2)", cursor: "pointer",
                    color: "var(--text-secondary)",
                  }}><X size={18} /></button>
        </div>

        {/* Toolbar */}
        <div style={{
          padding: "12px 22px", borderBottom: "1px solid var(--border-default)",
          display: "flex", gap: 8, flexWrap: "wrap",
        }}>
          <input ref={fileRef} type="file"
                 accept=".csv,.pdf,.docx,.txt,.png,.jpg,.jpeg,.webp,image/*"
                 onChange={(e) => handleUpload(e.target.files?.[0])}
                 style={{ display: "none" }} data-testid="budget-csv-input" />
          <button onClick={() => fileRef.current?.click()}
                  data-testid="budget-upload-btn" disabled={busy}
                  style={btnSecondary}
                  title="Sobe CSV, PDF, DOCX ou foto/print de orçamento — extrai itens E preços automaticamente">
            <Upload size={14} />
            {busy ? "Processando..." :
              `📤 Importar pronto (PDF/imagem/CSV)${itemCount > 0 ? " · substituir" : ""}`}
          </button>
          <button onClick={handleAnalyze}
                  disabled={analyzing || itemCount === 0}
                  data-testid="budget-analyze-btn"
                  style={{
                    ...btnPrimary,
                    background: analyzing
                      ? "var(--bg-surface-2)"
                      : "linear-gradient(180deg,#a78bfa,#7c3aed)",
                    opacity: itemCount === 0 ? 0.55 : 1,
                  }}>
            {analyzing
              ? <><Loader2 size={14} style={{ animation: "wa-spin 1s linear infinite" }} /> Analisando...</>
              : <><Sparkles size={14} /> Analisar com Orçamento_IA</>}
          </button>
          <button onClick={openPdf} disabled={!hasPrices}
                  data-testid="budget-print-btn"
                  style={{ ...btnSecondary, opacity: hasPrices ? 1 : 0.5 }}>
            <Printer size={14} /> Imprimir PDF
          </button>
          {budget.ai_model && (
            <span style={{
              marginLeft: "auto", padding: "6px 10px", borderRadius: 6,
              fontSize: 11, background: "rgba(124,58,237,.1)", color: "#7c3aed",
              fontWeight: 600,
            }}>IA: {budget.ai_model}</span>
          )}
        </div>

        {err && (
          <div style={{ padding: "10px 22px", color: "#dc2626", fontSize: 12,
                          background: "rgba(239,68,68,.08)" }}>
            {err}
          </div>
        )}

        {/* Tabela de itens */}
        <div style={{ padding: "16px 22px", flex: 1 }}>
          {itemCount === 0 ? (
            <div style={{
              padding: 40, textAlign: "center", color: "var(--text-muted)",
              border: "1px dashed var(--border-default)", borderRadius: 10,
            }}>
              <Upload size={36} strokeWidth={1.5} style={{ opacity: 0.4 }} />
              <p style={{ marginTop: 10, fontSize: 13 }}>
                Sobe um arquivo com a lista de itens — aceita <b>CSV</b>,
                <b> PDF</b> ou <b>DOCX</b>.
              </p>
              <p style={{ fontSize: 11, color: "var(--text-muted)" }}>
                CSV: colunas <code>item; qtde; unidade; especificacao</code>.
                PDF/DOCX: a Orçamento_IA extrai os itens automaticamente.
              </p>
            </div>
          ) : (
            <table data-testid="budget-items-table" style={{
              width: "100%", borderCollapse: "collapse", fontSize: 12,
            }}>
              <thead>
                <tr style={{ background: "var(--bg-surface-2)",
                                color: "var(--text-secondary)",
                                fontSize: 10, textTransform: "uppercase",
                                letterSpacing: 0.5, fontWeight: 700 }}>
                  <th style={{ padding: "8px 10px", textAlign: "left" }}>Item</th>
                  <th style={{ padding: "8px 10px", textAlign: "right" }}>Qtde</th>
                  <th style={{ padding: "8px 10px", textAlign: "left" }}>Unid</th>
                  <th style={{ padding: "8px 10px", textAlign: "left" }}>Preços IA — clique p/ escolher</th>
                  <th style={{ padding: "8px 10px", textAlign: "right" }}>Unit. usado</th>
                  <th style={{ padding: "8px 10px", textAlign: "right" }}>Subtotal</th>
                </tr>
              </thead>
              <tbody>
                {(budget.items || []).map((it) => {
                  const isManual = it.manual_override != null && it.manual_override !== "";
                  const choice = (it.price_choice || "mid").toLowerCase();
                  const choiceMap = { low: 0, mid: 1, high: 2 };
                  const selectedIdx = choiceMap[choice] ?? 1;
                  const unit = isManual
                              ? Number(it.manual_override)
                              : ((it.prices || [])[selectedIdx]?.value
                                  ?? Number(it.avg_price || 0));
                  const subtotal = unit * Number(it.qty || 0);
                  return (
                    <tr key={it.id} style={{ borderBottom: "1px solid var(--border-default)" }}>
                      <td style={{ padding: "10px" }}>
                        <div style={{ fontWeight: 600 }}>{it.name}</div>
                        {it.spec && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{it.spec}</div>}
                        {it.sources?.length > 0 && (
                          <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 2 }}>
                            Fonte: {it.sources.join(", ")} · conf: {it.confidence || "—"}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "10px", textAlign: "right" }}>{it.qty}</td>
                      <td style={{ padding: "10px" }}>{it.unit}</td>
                      <td style={{ padding: "10px" }}>
                        {(it.prices || []).length === 0
                          ? <span style={{ color: "var(--text-muted)" }}>—</span>
                          : (
                            <div style={{ display: "flex", gap: 4 }}>
                              {it.prices.map((p, idx) => {
                                const choiceKey = ["low", "mid", "high"][idx];
                                const isSelected = !isManual && choiceKey === choice;
                                return (
                                  <button
                                    key={idx} type="button"
                                    data-testid={`budget-price-choice-${it.id}-${choiceKey}`}
                                    title={`${p.label} · clique para usar este valor`}
                                    onClick={() => handlePriceChoice(it.id, choiceKey)}
                                    style={{
                                      padding: "3px 7px", borderRadius: 4, fontSize: 10,
                                      cursor: "pointer", fontWeight: isSelected ? 800 : 500,
                                      background: isSelected
                                        ? "linear-gradient(180deg,#0d9488,#0f766e)"
                                        : "var(--bg-surface-2)",
                                      color: isSelected ? "#fff" : "var(--text-secondary)",
                                      border: isSelected
                                        ? "1px solid #0f766e"
                                        : "1px solid var(--border-default)",
                                      boxShadow: isSelected
                                        ? "0 1px 2px rgba(13,148,136,.35)" : "none",
                                      transition: "all .12s",
                                    }}>
                                    {p.label[0]} {fmtMoney(p.value)}
                                  </button>
                                );
                              })}
                            </div>
                          )}
                      </td>
                      <td style={{ padding: "10px", textAlign: "right" }}>
                        <input
                          type="number" step="0.01" min="0"
                          data-testid={`budget-item-override-${it.id}`}
                          defaultValue={it.manual_override ?? ""}
                          placeholder={fmtMoney(unit)}
                          onBlur={(e) => {
                            const newVal = e.target.value;
                            const oldVal = it.manual_override ?? "";
                            if (String(newVal) !== String(oldVal)) {
                              handleItemPriceOverride(it.id, newVal);
                            }
                          }}
                          style={{
                            width: 90, padding: "5px 7px", borderRadius: 4,
                            border: isManual
                              ? "1px solid #f59e0b"
                              : "1px solid var(--border-default)",
                            fontSize: 11, textAlign: "right",
                            background: isManual
                              ? "rgba(245,158,11,.08)" : "var(--bg-surface)",
                            color: "var(--text-primary)",
                          }}
                        />
                      </td>
                      <td style={{ padding: "10px", textAlign: "right",
                                    fontWeight: 700, color: "var(--text-primary)" }}>
                        {fmtMoney(subtotal)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer com totais e sliders */}
        {itemCount > 0 && (
          <div style={{
            position: "sticky", bottom: 0,
            padding: "16px 22px", background: "var(--bg-surface-2)",
            borderTop: "1px solid var(--border-default)",
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24,
          }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
                              textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
                Configurações de cálculo
              </div>
              <PercentSlider label="% Ganho" value={budget.margin_pct || 0}
                              max={200}
                              testid="budget-margin-slider"
                              onChange={(v) => handlePersist({ margin_pct: v })} />
              <PercentSlider label="% Mão de obra" value={budget.labor_pct || 0}
                              max={200}
                              testid="budget-labor-slider"
                              onChange={(v) => handlePersist({ labor_pct: v })} />
              <PercentSlider label="% Imposto" value={budget.tax_pct || 0}
                              max={50}
                              testid="budget-tax-slider"
                              onChange={(v) => handlePersist({ tax_pct: v })} />
            </div>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
                              textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
                Resumo
              </div>
              <TotalRow label="Mão de obra"
                          value={fmtMoney(totals.labor_val || 0)} />
              <TotalRow label="TOTAL FINAL"
                          value={fmtMoney(totals.final || 0)}
                          testid="budget-total-final"
                          bold highlight divider />
              {/* Lucro provável = Total Final - Custo mais baixo. Só interno,
                  não vai pro PDF. */}
              <div data-testid="budget-expected-profit" style={{
                marginTop: 10, padding: 10, borderRadius: 8,
                background: "linear-gradient(135deg, rgba(22,163,74,.08), rgba(13,148,136,.08))",
                border: "1px solid rgba(22,163,74,.25)",
              }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#15803d",
                                textTransform: "uppercase", letterSpacing: 0.5,
                                marginBottom: 4 }}>
                  Lucro Provável <span style={{ fontWeight: 500, opacity: .7,
                                                  textTransform: "none" }}>
                    (orçamento − custo mais baixo)
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between",
                                alignItems: "baseline" }}>
                  <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                    Custo mais baixo: <strong>{fmtMoney(totals.min_cost || 0)}</strong>
                  </span>
                  <span style={{ fontSize: 18, fontWeight: 800, color: "#15803d" }}>
                    {fmtMoney(totals.expected_profit || 0)}
                    <span style={{ fontSize: 11, fontWeight: 600, marginLeft: 6,
                                    color: "#0d9488" }}>
                      ({(totals.expected_profit_pct || 0).toFixed(1)}%)
                    </span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PercentSlider({ label, value, max, onChange, testid }) {
  const [local, setLocal] = useState(value);
  useEffect(() => { setLocal(value); }, [value]);
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      fontSize: 11, color: "var(--text-secondary)", marginBottom: 4 }}>
        <span>{label}</span>
        <strong>{local.toFixed(1)}%</strong>
      </div>
      <input type="range" min={0} max={max} step={0.5}
              value={local}
              data-testid={testid}
              onChange={(e) => setLocal(parseFloat(e.target.value))}
              onMouseUp={(e) => onChange(parseFloat(e.target.value))}
              onTouchEnd={(e) => onChange(parseFloat(e.target.value))}
              style={{ width: "100%", accentColor: "#0ea5e9" }} />
    </div>
  );
}

function TotalRow({ label, value, bold, highlight, divider, testid }) {
  return (
    <div data-testid={testid} style={{
      display: "flex", justifyContent: "space-between",
      padding: "4px 0", borderTop: divider ? "1px solid var(--border-default)" : "none",
      marginTop: divider ? 6 : 0, paddingTop: divider ? 8 : 4,
      fontSize: highlight ? 16 : 12,
      fontWeight: bold ? 800 : 500,
      color: highlight ? "#0ea5e9" : "var(--text-primary)",
    }}>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}

/* ----- shared modal shell ----- */
function Modal({ title, onClose, children, testid }) {
  return (
    <div onClick={onClose} data-testid={testid} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.55)",
      backdropFilter: "blur(2px)", zIndex: 200,
      display: "grid", placeItems: "center",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg-surface)", borderRadius: 12,
        boxShadow: "0 12px 48px rgba(15,23,42,.4)",
        padding: 24, width: "min(480px, 92vw)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700,
                        color: "var(--text-primary)" }}>{title}</h3>
          <button onClick={onClose} style={{
            padding: 4, border: "none", background: "transparent",
            cursor: "pointer", color: "var(--text-muted)",
          }}><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

const inputStyle = {
  width: "100%", padding: "9px 11px", borderRadius: 6,
  border: "1px solid var(--border-default)", marginTop: 4,
  fontSize: 13, background: "var(--bg-surface)", color: "var(--text-primary)",
};
const btnPrimary = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "8px 14px", borderRadius: 6,
  background: "linear-gradient(180deg,#0ea5e9,#0284c7)",
  color: "#fff", fontWeight: 700, fontSize: 12,
  border: "none", cursor: "pointer",
};
const btnSecondary = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "8px 14px", borderRadius: 6,
  background: "var(--bg-surface-2)", color: "var(--text-primary)",
  fontWeight: 600, fontSize: 12,
  border: "1px solid var(--border-default)", cursor: "pointer",
};
const btnGhost = { ...btnSecondary, background: "transparent" };
