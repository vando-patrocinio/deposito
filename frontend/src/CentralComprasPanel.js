/**
 * CentralComprasPanel — Lançamento de compras de material por praça.
 *
 * Fluxo:
 *   COMPRA → ENTRADA NO ESTOQUE (Praça + responsável) → TÉCNICO → CLIENTE
 *
 * - Almoxarifes veem apenas a própria praça (backend filtra)
 * - Gestores/admins veem TUDO e podem CONFIRMAR a entrada no estoque
 * - Upload de PDF/imagem/planilha → IA Claude extrai e preenche o form
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import TransferToTechPanel from "@/TransferToTechPanel";
import InvoiceConsolidatedPanel from "@/InvoiceConsolidatedPanel";

const TYPE_META = {
  ont: { label: "ONT", emoji: "📡", color: "#0ea5e9" },
  insumo: { label: "Insumo", emoji: "🔌", color: "#10b981" },
  equipamento: { label: "Equipamento", emoji: "🛠️", color: "#8b5cf6" },
  ferramenta: { label: "Ferramenta", emoji: "🔧", color: "#f59e0b" },
  outros: { label: "Outros", emoji: "📦", color: "#64748b" },
};

const EMPTY_FORM = {
  type: "ont",
  praca_id: "",
  responsible_collaborator_id: "",
  tool_recipient_collaborator_id: "",  // técnico que recebe as ferramentas
  supplier_name: "",
  invoice_number: "",
  invoice_date: "",
  total_value: "",
  items: [{ description: "", quantity: 1, unit: "un", unit_price: "",
             macs: "", type: "ont" }],
  notes: "",
  file_url: "",
  file_name: "",
};

function StatusPill({ status }) {
  const map = {
    pending: { bg: "#fef3c7", fg: "#92400e", label: "Pendente" },
    confirmed: { bg: "#d1fae5", fg: "#065f46", label: "Confirmada" },
  };
  const m = map[status] || map.pending;
  return (
    <span style={{
      fontSize: 10, fontWeight: 800, padding: "3px 9px",
      borderRadius: 999, background: m.bg, color: m.fg,
      letterSpacing: ".04em",
    }}>{m.label}</span>
  );
}

function TypeBadge({ type }) {
  const m = TYPE_META[type] || TYPE_META.outros;
  return (
    <span style={{
      fontSize: 11, fontWeight: 800, padding: "3px 10px",
      borderRadius: 999, background: m.color + "22", color: m.color,
    }}>{m.emoji} {m.label}</span>
  );
}

function PurchaseForm({ refs, isWarehouseKeeper, userPracaId, onCreated }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");
  const [aiNote, setAiNote] = useState("");
  const fileRef = useRef(null);

  // Almoxarife: força a praça dele
  useEffect(() => {
    if (isWarehouseKeeper && userPracaId && form.praca_id !== userPracaId) {
      setForm((f) => ({ ...f, praca_id: userPracaId }));
    }
  }, [isWarehouseKeeper, userPracaId]); // eslint-disable-line

  function set(k, v) { setForm((p) => ({ ...p, [k]: v })); }
  function setItem(i, k, v) {
    setForm((p) => ({
      ...p, items: p.items.map((it, idx) => idx === i ? { ...it, [k]: v } : it),
    }));
  }
  function addItem() {
    setForm((p) => ({ ...p, items: [...p.items, { description: "", quantity: 1, unit: "un", unit_price: "", macs: "", type: p.type }] }));
  }
  function removeItem(i) {
    setForm((p) => ({ ...p, items: p.items.filter((_, idx) => idx !== i) }));
  }

  async function onFile(file) {
    if (!file) return;
    setUploading(true); setErr(""); setAiNote("");
    try {
      const r = await api.purchasesUploadExtract(file);
      // iter204 — Merge TODOS os drafts (multi-tipo) em uma única form.
      // O backend retorna `drafts[]` (1 por tipo) + `draft` (dominante).
      // Antes usávamos só `r.draft` e perdíamos itens de outros tipos.
      const allDrafts = (r.drafts && r.drafts.length) ? r.drafts : [r.draft || {}];
      const meta = r.draft || allDrafts[0] || {};
      const next = { ...form };
      if (meta.type) next.type = meta.type;
      if (meta.supplier_name) next.supplier_name = meta.supplier_name;
      if (meta.invoice_number) next.invoice_number = meta.invoice_number;
      if (meta.invoice_date) next.invoice_date = meta.invoice_date;
      // Soma os total_value de TODOS os drafts (NF completa)
      const totalSum = allDrafts.reduce(
        (s, d) => s + (parseFloat(d.total_value) || 0), 0);
      if (totalSum > 0) next.total_value = totalSum;
      else if (meta.total_value) next.total_value = meta.total_value;
      // Mescla itens de TODOS os drafts, preservando o type de cada item
      const allItems = [];
      const typeCounts = {};
      for (const d of allDrafts) {
        const items = (d.items || []);
        for (const it of items) {
          const t = it.type || d.type || "outros";
          typeCounts[t] = (typeCounts[t] || 0) + 1;
          allItems.push({
            description: it.description || "",
            quantity: it.quantity || 1,
            unit: it.unit || "un",
            unit_price: it.unit_price || "",
            macs: (it.macs || []).join(", "),
            // iter211s — preservar SNs detectados pela IA + Vision pass + regex
            sns: (it.sns || []).filter(Boolean),
            type: t,
          });
        }
      }
      if (allItems.length) next.items = allItems;
      next.file_name = r.file_name || file.name;
      setForm(next);
      // Mensagem detalhada: quantos itens e quantos lançamentos serão criados
      const conf = Math.round((meta.confidence || 0) * 100);
      const breakdown = Object.entries(typeCounts)
        .map(([t, n]) => `${n} ${t}`).join(" · ");
      const nDrafts = allDrafts.length;
      const lancamentos = nDrafts > 1
        ? ` → ${nDrafts} lançamentos automáticos (1 por tipo)`
        : "";
      setAiNote(
        `✅ IA extraiu (conf ${conf}%): ${allItems.length} item(ns)` +
        (breakdown ? ` [${breakdown}]` : "") + lancamentos +
        (meta.reason ? ` · ${meta.reason}` : "")
      );
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function submit() {
    setErr(""); setBusy(true);
    try {
      if (!form.praca_id) throw new Error("Selecione a praça");
      if (!form.responsible_collaborator_id) throw new Error("Selecione o responsável");

      // Separa itens por tipo: ferramentas vão por outro fluxo
      const validItems = form.items.filter((it) => (it.description || "").trim());
      const toolItems = validItems.filter((it) => it.type === "ferramenta");
      const stockItems = validItems.filter((it) => it.type !== "ferramenta");

      if (toolItems.length > 0 && !form.tool_recipient_collaborator_id) {
        throw new Error("Selecione o técnico que receberá as ferramentas (romaneio)");
      }

      // 1) Compras de insumos/ONT/equipamento/outros → fluxo padrão de compras
      //    iter204 — Agrupa itens por TYPE e cria 1 lançamento por grupo.
      //    Ex: NF com 10 ONTs + 50m drop + 5 splitters → 2 lançamentos
      //    (1 tipo=ont com as ONTs, 1 tipo=insumo com drop+splitters).
      let createdPurchases = 0;
      if (stockItems.length > 0) {
        const groups = {};
        for (const it of stockItems) {
          const t = (it.type || form.type || "outros");
          (groups[t] = groups[t] || []).push(it);
        }
        const groupTypes = Object.keys(groups);
        for (const t of groupTypes) {
          const groupItems = groups[t];
          // Total proporcional: soma dos (quantity × unit_price) deste grupo
          let groupTotal = 0;
          for (const it of groupItems) {
            const q = parseFloat(it.quantity) || 0;
            const p = parseFloat(it.unit_price) || 0;
            groupTotal += q * p;
          }
          const payload = {
            type: t,
            praca_id: form.praca_id,
            responsible_collaborator_id: form.responsible_collaborator_id,
            supplier_name: form.supplier_name || null,
            invoice_number: form.invoice_number || null,
            invoice_date: form.invoice_date || null,
            // Se a NF tinha 1 só tipo, usa o total da form; senão proporcional
            total_value: groupTypes.length === 1
              ? (form.total_value ? parseFloat(form.total_value) : null)
              : (groupTotal > 0 ? Math.round(groupTotal * 100) / 100 : null),
            notes: (form.notes || "") +
              (groupTypes.length > 1
                ? ` · split ${createdPurchases + 1}/${groupTypes.length} (auto-iter204)`
                : ""),
            file_name: form.file_name || null,
            items: groupItems.map((it) => ({
              description: it.description,
              quantity: parseFloat(it.quantity) || 1,
              unit: it.unit || null,
              unit_price: it.unit_price ? parseFloat(it.unit_price) : null,
              type: it.type || null,
              macs: it.type === "ont" && it.macs
                ? it.macs.split(/[\s,;]+/).filter(Boolean) : null,
              // iter211s — propaga SNs lidos pela IA pra criação de ONTs
              sns: it.type === "ont" ? (it.sns || []) : null,
            })),
          };
          await api.purchasesCreate(payload);
          createdPurchases += 1;
        }
      }

      // 2) Ferramentas → cria asset por item para o técnico (gera custódia)
      let createdToolsCount = 0;
      if (toolItems.length > 0) {
        const recipient = form.tool_recipient_collaborator_id;
        for (const it of toolItems) {
          const qty = parseInt(it.quantity, 10) || 1;
          await api.assetCreate({
            collaborator_id: recipient,
            category: "ferramenta",
            item: it.description,
            qty,
            unit_value_brl: it.unit_price ? parseFloat(it.unit_price) : null,
            notes: `Origem: NF ${form.invoice_number || "—"} · ${form.supplier_name || "—"}`,
          });
          createdToolsCount += qty;
        }
        // Abre o romaneio para assinatura digital em nova aba
        const url = api.assetRomaneioUrl(recipient, true);
        window.open(url, "_blank", "noopener,noreferrer");
      }

      setForm({ ...EMPTY_FORM, praca_id: form.praca_id });
      const stockMsg = createdPurchases > 0
        ? (createdPurchases === 1
            ? `${stockItems.length} item(ns) em 1 lançamento de estoque`
            : `${stockItems.length} item(ns) em ${createdPurchases} lançamentos (split por tipo)`)
        : "";
      const toolMsg = createdToolsCount > 0
        ? `${createdToolsCount} ferramenta(s) transferida(s) ao técnico · romaneio aberto p/ assinatura`
        : "";
      setAiNote([stockMsg, toolMsg].filter(Boolean).join(" · ") || "Lançado.");
      onCreated?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  const filteredCollabs = (refs.collaborators || []).filter((c) => {
    if (!form.praca_id) return true;
    // Prioriza almoxarifes daquela praça, mas mostra todos
    return true;
  });

  return (
    <div data-testid="purchase-form"
         style={{ background: "white", border: "1px solid #e2e8f0",
                   borderRadius: 14, padding: 22 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "baseline", marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "#0f172a" }}>
          📥 Lançar Nova Compra
        </h3>
        <div style={{ fontSize: 12, color: "#64748b" }}>
          Anexe NF/foto/planilha — a IA preenche, ou preencha manual.
        </div>
      </div>

      {/* Upload + IA */}
      <div style={{ marginBottom: 18, padding: 14, background: "#f0fdf4",
                     border: "1px dashed #10b981", borderRadius: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <div style={{ fontSize: 13, color: "#065f46", fontWeight: 600 }}>
            🤖 Anexar arquivo (PDF, foto JPG/PNG, XLS, DOCX) — Claude Sonnet 4.5 lê e preenche
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.PDF,.jpg,.jpeg,.png,.webp,.xls,.xlsx,.doc,.docx"
            disabled={uploading}
            onChange={(e) => onFile(e.target.files?.[0])}
            data-testid="purchase-file-input"
            style={{ fontSize: 12 }}
          />
        </div>
        {uploading && <div style={{ marginTop: 6, fontSize: 12, color: "#065f46" }}>⏳ IA lendo o arquivo…</div>}
        {aiNote && <div style={{ marginTop: 6, fontSize: 12, color: "#065f46" }}>{aiNote}</div>}
        {form.file_name && (
          <div style={{ marginTop: 6, fontSize: 11, color: "#475569" }}>
            Anexado: <strong>{form.file_name}</strong>
          </div>
        )}
      </div>

      {/* Campos principais */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
        <Field label="Tipo padrão (novos itens)">
          <select value={form.type} onChange={(e) => set("type", e.target.value)}
                  data-testid="purchase-type"
                  style={inputStyle}>
            {Object.entries(TYPE_META).map(([id, m]) =>
              <option key={id} value={id}>{m.emoji} {m.label}</option>)}
          </select>
        </Field>
        <Field label="Praça destino">
          <select
            value={form.praca_id}
            onChange={(e) => set("praca_id", e.target.value)}
            disabled={isWarehouseKeeper}
            data-testid="purchase-praca"
            style={inputStyle}
          >
            <option value="">Selecione…</option>
            {(refs.pracas || []).map((p) =>
              <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Responsável recebedor">
          <select value={form.responsible_collaborator_id}
                  onChange={(e) => set("responsible_collaborator_id", e.target.value)}
                  data-testid="purchase-responsible"
                  style={inputStyle}>
            <option value="">Selecione…</option>
            {filteredCollabs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.cargo === "almoxarife" ? "📦 " : ""}{c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Fornecedor">
          <input value={form.supplier_name}
                  list="purchase-suppliers-list"
                  onChange={(e) => set("supplier_name", e.target.value)}
                  data-testid="purchase-supplier"
                  style={inputStyle}
                  placeholder="Digite ou escolha (cria novo se não existir)" />
          <datalist id="purchase-suppliers-list">
            {(refs.suppliers || []).map((s) => (
              <option key={s.id} value={s.name}>
                {s.document || s.cnpj || ""}
              </option>
            ))}
          </datalist>
          {form.supplier_name && !(refs.suppliers || []).some(
            (s) => s.name.toLowerCase() === form.supplier_name.toLowerCase()) && (
            <div style={{ fontSize: 11, color: "#0369a1", marginTop: 4 }}>
              ℹ️ Fornecedor novo — será cadastrado automaticamente ao salvar.
            </div>
          )}
        </Field>
        <Field label="Nº NF">
          <input value={form.invoice_number}
                  onChange={(e) => set("invoice_number", e.target.value)}
                  style={inputStyle} placeholder="12345" />
        </Field>
        <Field label="Data NF">
          <input type="date" value={form.invoice_date}
                  onChange={(e) => set("invoice_date", e.target.value)}
                  style={inputStyle} />
        </Field>
        <Field label="Valor total (R$)">
          <input type="number" step="0.01"
                  value={form.total_value}
                  onChange={(e) => set("total_value", e.target.value)}
                  style={inputStyle} />
        </Field>
      </div>

      {/* Itens */}
      <div style={{ marginTop: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "baseline", marginBottom: 6 }}>
          <strong style={{ fontSize: 13, color: "#0f172a" }}>
            Itens
            <span style={{ fontSize: 11, color: "#64748b", fontWeight: 500, marginLeft: 8 }}>
              · escolha o tipo de cada item (ferramenta gera romaneio)
            </span>
          </strong>
          <button onClick={addItem}
                  data-testid="purchase-add-item"
                  style={btnSecondary}>+ item</button>
        </div>
        {form.items.map((it, i) => {
          const itType = it.type || form.type;
          const isOnt = itType === "ont";
          const isTool = itType === "ferramenta";
          return (
            <div key={i} style={{
              display: "grid",
              gridTemplateColumns: isOnt
                ? "120px 2fr 60px 60px 90px 2fr 28px"
                : "120px 2fr 60px 60px 90px 28px",
              gap: 6, marginBottom: 6, alignItems: "center",
            }}>
              <select value={itType}
                      data-testid={`purchase-item-type-${i}`}
                      onChange={(e) => setItem(i, "type", e.target.value)}
                      style={{
                        ...inputStyle,
                        background: isTool ? "#fef3c7" : "white",
                        borderColor: isTool ? "#f59e0b" : "#e2e8f0",
                        fontWeight: isTool ? 700 : 400,
                      }}>
                {Object.entries(TYPE_META).map(([id, m]) =>
                  <option key={id} value={id}>{m.emoji} {m.label}</option>)}
              </select>
              <input value={it.description}
                      onChange={(e) => setItem(i, "description", e.target.value)}
                      placeholder={isOnt ? "Modelo (ex: HG6145D)"
                        : isTool ? "Ex.: alicate de crimpagem, OTDR…"
                        : "Descrição"}
                      style={inputStyle} />
              <input type="number" value={it.quantity}
                      onChange={(e) => setItem(i, "quantity", e.target.value)}
                      style={inputStyle} placeholder="qtd" />
              <input value={it.unit}
                      onChange={(e) => setItem(i, "unit", e.target.value)}
                      style={inputStyle} placeholder="un" />
              <input type="number" step="0.01" value={it.unit_price}
                      onChange={(e) => setItem(i, "unit_price", e.target.value)}
                      style={inputStyle} placeholder="R$" />
              {isOnt && (
                <div style={{ display: "flex", flexDirection: "column",
                                gap: 4 }}>
                  <input value={it.macs}
                          onChange={(e) => setItem(i, "macs", e.target.value)}
                          placeholder="MACs (opcional)"
                          style={{ ...inputStyle, fontSize: 11 }} />
                  {/* iter211s — mostra SNs detectados pela IA */}
                  {(it.sns || []).length > 0 && (
                    <details style={{ fontSize: 10 }}>
                      <summary style={{
                        cursor: "pointer", color: "#16a34a",
                        fontWeight: 700, fontSize: 11,
                      }}>
                        🏷️ {(it.sns || []).length} SN(s) lido(s) pela IA
                      </summary>
                      <div style={{
                        marginTop: 4, padding: 6,
                        background: "#f0fdf4", border: "1px solid #86efac",
                        borderRadius: 4, maxHeight: 130, overflowY: "auto",
                        fontFamily: "monospace", fontSize: 10,
                        color: "#14532d", lineHeight: 1.5,
                      }}>
                        {(it.sns || []).map((sn, j) => (
                          <div key={j}>
                            <span style={{ color: "#64748b" }}>
                              {String(j + 1).padStart(2, "0")}.
                            </span>{" "}{sn}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                  {isOnt && (it.sns || []).length === 0 && (
                    <div style={{ fontSize: 10, color: "#ef4444",
                                    fontWeight: 700 }}>
                      ⚠️ Nenhum SN detectado — anexe foto melhor ou
                      use 🔄 Reprocessar SNs após salvar
                    </div>
                  )}
                </div>
              )}
              <button onClick={() => removeItem(i)}
                      style={{ ...btnSecondary, padding: "4px 6px" }}>×</button>
            </div>
          );
        })}

        {/* Seletor de técnico — só aparece quando há itens "ferramenta" */}
        {form.items.some((it) => it.type === "ferramenta") && (
          <div data-testid="purchase-tool-recipient-box"
                style={{ marginTop: 10, padding: 12,
                          background: "#fef3c7", border: "1.5px solid #f59e0b",
                          borderRadius: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#92400e",
                            marginBottom: 6 }}>
              🔧 Ferramentas detectadas — transferência para o técnico
            </div>
            <Field label="Técnico recebedor (gera romaneio para assinatura)">
              <select value={form.tool_recipient_collaborator_id}
                      data-testid="purchase-tool-recipient"
                      onChange={(e) => set("tool_recipient_collaborator_id", e.target.value)}
                      style={inputStyle}>
                <option value="">Selecione o técnico…</option>
                {(refs.collaborators || []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.cargo === "almoxarife" ? "📦 " : "👷 "}{c.name}
                  </option>
                ))}
              </select>
            </Field>
            <div style={{ fontSize: 11, color: "#92400e", marginTop: 4 }}>
              Ao confirmar, cada ferramenta será cadastrada como pertence do técnico
              e o <b>romaneio</b> abre em nova aba para assinatura digital.
            </div>
          </div>
        )}
      </div>

      <Field label="Observações">
        <textarea value={form.notes}
                   onChange={(e) => set("notes", e.target.value)}
                   rows={2} style={{ ...inputStyle, resize: "vertical" }} />
      </Field>

      {err && (
        <div style={{ marginTop: 10, padding: "8px 12px", background: "#fee2e2",
                       border: "1px solid #ef4444", borderRadius: 8,
                       fontSize: 12, color: "#991b1b" }}>{err}</div>
      )}

      <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={() => setForm(EMPTY_FORM)}
                style={btnSecondary}>Limpar</button>
        <button onClick={submit} disabled={busy}
                data-testid="purchase-submit"
                style={{ ...btnPrimary, opacity: busy ? 0.6 : 1 }}>
          {busy ? "Salvando…" : "📥 Lançar compra"}
        </button>
      </div>
    </div>
  );
}

const inputStyle = {
  padding: "7px 10px", fontSize: 13, border: "1px solid #e2e8f0",
  borderRadius: 6, background: "white", color: "#0f172a", width: "100%",
};

const btnPrimary = {
  padding: "8px 16px", background: "#0f172a", color: "white",
  border: "none", borderRadius: 8, cursor: "pointer",
  fontWeight: 700, fontSize: 13,
};
const btnSecondary = {
  padding: "7px 14px", background: "#f1f5f9", color: "#0f172a",
  border: "1px solid #cbd5e1", borderRadius: 8, cursor: "pointer",
  fontWeight: 600, fontSize: 12,
};

function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginTop: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                     letterSpacing: ".04em", color: "#64748b", marginBottom: 4 }}>
        {label}
      </div>
      {children}
    </label>
  );
}

function PurchasesList({ data, canConfirm, onReload }) {
  const [busy, setBusy] = useState("");

  async function confirm(id) {
    // iter211u — Resumo claro do que vai virar estoque
    const p = data.items.find((x) => x.id === id);
    let prompt_msg = "Confirmar entrada no estoque?";
    if (p && p.type === "ont") {
      const sns_total = (p.items || []).reduce(
        (acc, it) => acc + (it.sns?.length || 0), 0);
      const qty_total = (p.items || []).reduce(
        (acc, it) => acc + (parseInt(it.quantity, 10) || 0), 0);
      prompt_msg = `Confirmar entrada no estoque?\n\n`
        + `Esta compra vai cadastrar ${sns_total} ONT(s) com SN no estoque `
        + `da empresa, disponíveis para transferir aos colaboradores.`;
      if (sns_total < qty_total) {
        prompt_msg += `\n\n⚠️ ATENÇÃO: a NF declara ${qty_total} unidades, mas `
          + `só ${sns_total} têm SN preenchido. As ${qty_total - sns_total} `
          + `restantes ficarão sem SN — você pode editar depois.`;
      }
    }
    if (!window.confirm(prompt_msg)) return;
    setBusy(id);
    try {
      const r = await api.purchasesConfirm(id);
      window.alert(`✅ Confirmada. ${r.items_imported} item(s) gravados. ${r.macs_imported ? `MACs novos: ${r.macs_imported}.` : ""} ${(r.notes || []).join(" | ")}`);
      onReload?.();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(""); }
  }
  async function del(id) {
    if (!window.confirm("Excluir esta compra?")) return;
    setBusy(id);
    try {
      await api.purchasesDelete(id);
      onReload?.();
    } catch (e) {
      window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(""); }
  }

  if (!data?.items?.length) {
    return (
      <div data-testid="purchases-empty"
            style={{ padding: 28, textAlign: "center", color: "#94a3b8",
                       background: "white", border: "1px dashed #cbd5e1",
                       borderRadius: 12 }}>
        Nenhuma compra registrada ainda. Use o formulário acima.
      </div>
    );
  }

  return (
    <div style={{ background: "white", border: "1px solid #e2e8f0",
                    borderRadius: 14, padding: 18 }}>
      <h3 style={{ margin: 0, marginBottom: 12, fontSize: 15,
                     fontWeight: 800, color: "#0f172a" }}>
        Histórico de Compras ({data.items.length})
      </h3>
      {data.items.map((p) => (
        <div key={p.id}
              data-testid={`purchase-row-${p.id}`}
              style={{ borderTop: "1px solid #f1f5f9", padding: "12px 0" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10,
                          flexWrap: "wrap", marginBottom: 4 }}>
            <TypeBadge type={p.type} />
            <strong style={{ fontSize: 14 }}>{p.supplier_name || "—"}</strong>
            <span style={{ fontSize: 11, color: "#64748b" }}>
              {p.invoice_number ? `NF ${p.invoice_number}` : ""}
              {p.invoice_date ? ` · ${new Date(p.invoice_date).toLocaleDateString("pt-BR")}` : ""}
            </span>
            <StatusPill status={p.status} />
            {p.total_value && (
              <span style={{ marginLeft: "auto", fontWeight: 700, color: "#065f46" }}>
                R$ {Number(p.total_value).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: "#475569" }}>
            📦 <strong>{p.praca_name}</strong> · 👤 {p.responsible_name}
            {p.file_name && <> · 📎 {p.file_name}</>}
          </div>
          {p.items?.length > 0 && (
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
              {p.items.map((it, i) =>
                `${it.quantity}× ${it.description}${it.sns?.length ? ` (${it.sns.length} SNs)` : (it.macs?.length ? ` (${it.macs.length} MACs)` : "")}`
              ).join(" · ")}
            </div>
          )}
          {/* iter211u — Antes da confirmação, mostra lista completa de SNs/ONTs */}
          {p.type === "ont" && p.status === "pending"
            && (p.items || []).some((it) => (it.sns || []).length > 0) && (
            <details open data-testid={`purchase-sns-preview-${p.id}`}
                       style={{ marginTop: 8 }}>
              <summary style={{
                cursor: "pointer", fontSize: 12, fontWeight: 800,
                color: "#16a34a", padding: "6px 8px",
                background: "#f0fdf4", border: "1px solid #86efac",
                borderRadius: 6, listStyle: "none",
              }}>
                ▼ 🏷️ ONTs a serem cadastradas ({(p.items || [])
                  .reduce((acc, it) => acc + (it.sns?.length || 0), 0)})
              </summary>
              <div style={{
                marginTop: 6, padding: 10,
                background: "#f0fdf4", border: "1px solid #86efac",
                borderRadius: 6, maxHeight: 240, overflowY: "auto",
              }}>
                {(p.items || []).map((it, i) => {
                  if (!(it.sns || []).length) return null;
                  return (
                    <div key={i} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 11, fontWeight: 700,
                                      color: "#14532d", marginBottom: 4 }}>
                        📦 {it.description} · {it.sns.length} unidade(s)
                      </div>
                      <div style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
                        gap: 4, fontFamily: "monospace", fontSize: 10,
                        color: "#0f172a",
                      }}>
                        {it.sns.map((sn, j) => (
                          <div key={j} style={{
                            padding: "3px 6px", background: "#fff",
                            border: "1px solid #d1fae5", borderRadius: 4,
                          }}>
                            <span style={{ color: "#64748b" }}>
                              {String(j + 1).padStart(2, "0")}
                            </span>{" "}
                            <strong>{sn}</strong>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
                <div style={{
                  marginTop: 8, padding: 6, background: "#fef3c7",
                  borderRadius: 4, fontSize: 11, color: "#92400e",
                  fontWeight: 600,
                }}>
                  ⚠️ Confirme só se todos os SNs estiverem corretos.
                  Após confirmar, cada SN vira uma ONT no estoque.
                </div>
              </div>
            </details>
          )}
          {p.type === "ont" && p.status === "pending"
            && !(p.items || []).some((it) => (it.sns || []).length > 0) && (
            <div data-testid={`purchase-no-sns-${p.id}`}
                  style={{
                    marginTop: 8, padding: 8,
                    background: "#fef2f2", border: "1px solid #fca5a5",
                    borderRadius: 6, fontSize: 11, color: "#991b1b",
                    fontWeight: 600,
                  }}>
              ⚠️ Esta compra de ONT está SEM SNs detectados.
              Confirme só se quiser cadastrar manualmente depois — ou
              clique em "📸 Reler NF (foto)" abaixo.
            </div>
          )}
          {p.notes && <div style={{ fontSize: 11, color: "#475569", marginTop: 4, fontStyle: "italic" }}>{p.notes}</div>}
          {p.status === "confirmed" && p.items_imported !== undefined && (
            <div style={{ fontSize: 11, color: "#065f46", marginTop: 4 }}>
              ✅ {p.items_imported} item(s) gravados no estoque
            </div>
          )}
          <div style={{ marginTop: 8, display: "flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}>
            {p.status === "pending" && canConfirm && (
              <button onClick={() => confirm(p.id)}
                      disabled={busy === p.id}
                      data-testid={`purchase-confirm-${p.id}`}
                      style={{ ...btnPrimary, padding: "4px 12px", fontSize: 11 }}>
                {busy === p.id ? "..." : "✓ Confirmar entrada no estoque"}
              </button>
            )}
            {/* iter211o — Reprocessar SNs (anexar SNs faltantes) */}
            {p.type === "ont" && canConfirm && (
              <>
                <button data-testid={`purchase-reprocess-img-${p.id}`}
                  onClick={() => {
                    const inp = document.createElement("input");
                    inp.type = "file";
                    inp.accept = "image/*";
                    inp.capture = "environment";
                    inp.onchange = async (ev) => {
                      const f = ev.target.files?.[0];
                      if (!f) return;
                      try {
                        const r = await api.purchasesReprocessFromImage(p.id, f);
                        await window.alert(
                          r.message
                          + `\n\nSNs encontrados: ${r.candidates_found || 0}`
                          + `\nAdicionados: ${r.inserted}`
                          + `\nJá existiam: ${r.already_existed || 0}`,
                        );
                        onReload?.();
                      } catch (e) {
                        await window.alert("Erro: "
                          + (e?.response?.data?.detail || e.message));
                      }
                    };
                    inp.click();
                  }}
                  style={{
                    padding: "4px 10px", fontSize: 11, fontWeight: 700,
                    background: "#2563eb", color: "#fff",
                    border: 0, borderRadius: 6, cursor: "pointer",
                  }}>
                  📸 Reler NF (foto)
                </button>
                <button data-testid={`purchase-reprocess-${p.id}`}
                  onClick={async () => {
                    const raw = await window.prompt(
                      "Cole aqui os SNs que faltam — um por linha "
                      + "(ou vírgula). Se não passar nada, o sistema usa "
                      + "regex no texto da NF.",
                      "");
                    if (raw === null || raw === undefined) return;
                    // iter211t — window.prompt pode ser sobrescrito por
                    // dialog custom que devolve objeto. Coage pra string.
                    const rawStr = typeof raw === "string"
                      ? raw
                      : (raw && typeof raw === "object" && "value" in raw
                          ? String(raw.value || "")
                          : String(raw || ""));
                    const extra_sns = rawStr
                      .split(/[\s,;\n]+/)
                      .map((s) => s.trim().toUpperCase())
                      .filter(Boolean);
                    try {
                      const r = await api.purchasesReprocessSns(p.id,
                        extra_sns.length ? { extra_sns } : {});
                      await window.alert(
                        `${r.inserted} ONT(s) adicionadas. `
                        + `${r.already_existed || 0} já existiam.`);
                      onReload?.();
                    } catch (e) {
                      await window.alert("Erro: "
                        + (e?.response?.data?.detail || e.message));
                    }
                  }}
                  style={{
                    padding: "4px 10px", fontSize: 11, fontWeight: 700,
                    background: "#fbbf24", color: "#78350f",
                    border: 0, borderRadius: 6, cursor: "pointer",
                  }}>
                  🔄 Reprocessar SNs
                </button>
              </>
            )}
            {p.status === "pending" && (
              <button onClick={() => del(p.id)}
                      disabled={busy === p.id}
                      style={{ ...btnSecondary, padding: "4px 10px", fontSize: 11 }}>
                Excluir
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function CentralComprasPanel({ currentUser }) {
  const [refs, setRefs] = useState({ pracas: [], collaborators: [], types: [] });
  const [data, setData] = useState({ items: [], is_warehouse_keeper: false, user_praca_id: null });
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const [r, l] = await Promise.all([
        api.purchasesRefs(), api.purchasesList(),
      ]);
      setRefs(r);
      setData(l);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  const canConfirm = useMemo(() =>
    !!currentUser && (
      currentUser.is_super_admin ||
      ["administrador", "gestor"].includes(currentUser.role)
    ), [currentUser]);

  if (loading) {
    return <div style={{ padding: 22, color: "#64748b" }}>Carregando…</div>;
  }
  if (err) {
    return <div style={{ padding: 22, color: "#991b1b" }}>{err}</div>;
  }

  return (
    <div style={{ padding: 24 }} data-testid="central-compras-panel">
      <div style={{ marginBottom: 22 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 900, color: "#0f172a" }}>
          📥 Central de Compras
        </h2>
        <div style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
          Fluxo: <strong>Compra → Entrada no estoque (Praça + responsável) → Técnico → Cliente</strong>
        </div>
        {data.is_warehouse_keeper && (
          <div style={{ marginTop: 10, padding: "10px 14px",
                         background: "#dbeafe", border: "1px solid #3b82f6",
                         borderRadius: 8, fontSize: 12, color: "#1e40af" }}>
            📦 Você é almoxarife: vê e lança somente a sua praça.
            Após lançar, um gestor precisa <strong>confirmar a entrada</strong> no estoque.
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 18 }}>
        <PurchaseForm refs={refs}
                       isWarehouseKeeper={data.is_warehouse_keeper}
                       userPracaId={data.user_praca_id}
                       onCreated={load} />
        <PurchasesList data={data}
                        canConfirm={canConfirm}
                        onReload={load} />
      </div>

      {/* Transferência praça → técnico (visível para gestores/admin) */}
      {canConfirm && <TransferToTechPanel pracas={refs.pracas || []} />}

      {/* iter203 — Visão consolidada por Nota Fiscal */}
      <div style={{ marginTop: 22 }}>
        <InvoiceConsolidatedPanel />
      </div>
    </div>
  );
}
