import React, { useCallback, useEffect, useState } from "react";
import { Button } from "@/ui";
import { api } from "@/api";

const CATEGORIES = [
  { id: "uniforme", label: "👕 Uniforme", color: "#0ea5e9" },
  { id: "epi", label: "🦺 EPI", color: "#f59e0b" },
  { id: "ferramenta", label: "🔧 Ferramenta", color: "#0d9488" },
  { id: "veiculo", label: "🚗 Veículo", color: "#dc2626" },
  { id: "eletronico", label: "📱 Eletrônico", color: "#16a34a" },
  { id: "outro", label: "📦 Outro", color: "#64748b" },
];

const STATUS_PILL = {
  ativo: { bg: "#dcfce7", color: "#166534", label: "Ativo" },
  devolvido: { bg: "#e2e8f0", color: "#475569", label: "Devolvido" },
  danificado: { bg: "#fef3c7", color: "#92400e", label: "Danificado" },
  perdido: { bg: "#fee2e2", color: "#991b1b", label: "Perdido" },
};

const EMPTY_FORM = {
  category: "uniforme", item: "", marca: "", modelo: "",
  tamanho: "", serial: "", qty: 1, unit_value_brl: "", notes: "",
};

export default function AssetsSection({ collaborator, onClose }) {
  const [data, setData] = useState({ items: [], summary: {} });
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [romaneioPdf, setRomaneioPdf] = useState(null); // { url, name } | null
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const reload = useCallback(async () => {
    try {
      setData(await api.assetsList(collaborator.id));
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    }
  }, [collaborator.id]);

  useEffect(() => { reload(); }, [reload]);

  const save = async () => {
    if (!form.item.trim()) {
      setMsg({ type: "err", text: "Item obrigatório." });
      return;
    }
    setBusy(true); setMsg(null);
    try {
      const payload = { ...form };
      if (payload.unit_value_brl === "" || payload.unit_value_brl == null) {
        delete payload.unit_value_brl;
      } else {
        payload.unit_value_brl = Number(payload.unit_value_brl);
      }
      if (editingId) {
        await api.assetUpdate(editingId, payload);
        setMsg({ type: "ok", text: "Atualizado." });
      } else {
        await api.assetCreate({ ...payload, collaborator_id: collaborator.id });
        setMsg({ type: "ok", text: "Item adicionado." });
      }
      setForm(EMPTY_FORM); setEditingId(null); setCreating(false);
      reload();
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const startEdit = (a) => {
    setEditingId(a.id);
    setForm({
      category: a.category || "outro", item: a.item || "",
      marca: a.marca || "", modelo: a.modelo || "",
      tamanho: a.tamanho || "", serial: a.serial || "",
      qty: a.qty || 1,
      unit_value_brl: a.unit_value_brl != null ? a.unit_value_brl : "",
      notes: a.notes || "", status: a.status,
    });
    setCreating(true);
  };

  const setStatus = async (a, status) => {
    if (a.status === status) return;
    if (!await window.confirm(`Marcar "${a.item}" como ${status}?`)) return;
    try {
      await api.assetUpdate(a.id, { status });
      reload();
    } catch (e) {
      await window.alert(e?.response?.data?.detail || e.message);
    }
  };

  const remove = async (a) => {
    if (!await window.confirm(`Remover "${a.item}" do cadastro?`)) return;
    try { await api.assetDelete(a.id); reload(); }
    catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
  };

  const openRomaneio = (onlyActive = false) => {
    // Abre PDF em modal interno com <iframe> (sem popup, sem nova aba).
    // Mostra loader, fecha modal anterior se houver.
    const url = api.assetRomaneioUrl(collaborator.id, onlyActive);
    const token = localStorage.getItem("ponto_token");
    setRomaneioPdf({ loading: true, url: null, name: "" });
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob);
        const safeName = (collaborator.name || "colaborador")
          .replace(/[^a-z0-9]+/gi, "_").toLowerCase();
        setRomaneioPdf({
          loading: false,
          url: blobUrl,
          name: `romaneio_${safeName}${onlyActive ? "_ativos" : ""}.pdf`,
          onlyActive,
        });
      })
      .catch(async (e) => {
        setRomaneioPdf(null);
        await window.alert("Falha ao gerar romaneio: " + (e?.message || e));
      });
  };

  const closeRomaneio = () => {
    if (romaneioPdf?.url) URL.revokeObjectURL(romaneioPdf.url);
    setRomaneioPdf(null);
  };

  const downloadCurrentRomaneio = () => {
    if (!romaneioPdf?.url) return;
    const a = document.createElement("a");
    a.href = romaneioPdf.url;
    a.download = romaneioPdf.name || "romaneio.pdf";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const fld = (key, label, opts = {}) => (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 11, color: "#475569", fontWeight: 700, marginBottom: 3 }}>{label}</div>
      <input data-testid={`asset-form-${key}`} value={form[key] || ""} {...opts}
             onChange={(e) => setForm({ ...form, [key]: opts.type === "number" ? Number(e.target.value) : e.target.value })}
             style={{ width: "100%", padding: "7px 10px", border: "1px solid #cbd5e1",
                      borderRadius: 8, fontSize: 13, boxSizing: "border-box" }} />
    </label>
  );

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 100,
      padding: 16, overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="assets-modal" style={{
        background: "#f8fafc", maxWidth: 1080, margin: "0 auto",
        borderRadius: 18, padding: 22, minHeight: "70vh",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: "#0f172a" }}>
              🎒 Checklist de {collaborator.name}
            </h2>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
              {data.summary.total || 0} item(ns) ·
              {' '}{data.summary.ativo || 0} ativos ·
              {' '}{data.summary.pending_signature || 0} pendentes de assinatura
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button variant="soft" onClick={() => openRomaneio(false)} data-testid="asset-print-all">
              📄 Romaneio (todos)
            </Button>
            <Button variant="soft" onClick={() => openRomaneio(true)} data-testid="asset-print-active">
              📄 Romaneio (só ativos)
            </Button>
            <Button onClick={onClose}>Fechar</Button>
          </div>
        </div>

        <Button onClick={() => { setCreating((v) => !v); setEditingId(null); setForm(EMPTY_FORM); }}
                data-testid="asset-create-toggle">
          {creating ? "Cancelar" : "+ Adicionar pertence"}
        </Button>

        {creating && (
          <div data-testid="asset-form" style={{
            marginTop: 12, padding: 16, background: "white",
            border: "1px solid #e2e8f0", borderRadius: 14,
          }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
              <label>
                <div style={{ fontSize: 11, color: "#475569", fontWeight: 700, marginBottom: 3 }}>Categoria *</div>
                <select data-testid="asset-form-category" value={form.category}
                        onChange={(e) => setForm({ ...form, category: e.target.value })}
                        style={{ width: "100%", padding: "7px 10px", border: "1px solid #cbd5e1",
                                 borderRadius: 8, fontSize: 13 }}>
                  {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
              </label>
              <div style={{ gridColumn: "span 3" }}>
                {fld("item", "Item *", { placeholder: "Ex.: Camisa polo, Multímetro, Capacete" })}
              </div>
              {fld("marca", "Marca")}
              {fld("modelo", "Modelo")}
              {fld("tamanho", "Tamanho", { placeholder: "P/M/G/40/41" })}
              {fld("qty", "Qtd", { type: "number", min: 1 })}
              {fld("unit_value_brl", "Valor unit. (R$)",
                   { type: "number", step: "0.01", min: 0, placeholder: "Ex.: 80.00" })}
              <div style={{ gridColumn: "span 4" }}>
                {fld("serial", "Nº série / patrimônio")}
              </div>
              <div style={{ gridColumn: "span 4" }}>
                <label>
                  <div style={{ fontSize: 11, color: "#475569", fontWeight: 700, marginBottom: 3 }}>Observações</div>
                  <textarea data-testid="asset-form-notes" value={form.notes || ""} rows={2}
                            onChange={(e) => setForm({ ...form, notes: e.target.value })}
                            style={{ width: "100%", padding: "7px 10px", border: "1px solid #cbd5e1",
                                     borderRadius: 8, fontSize: 13, fontFamily: "inherit" }} />
                </label>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Button onClick={save} disabled={busy} data-testid="asset-form-save">
                {busy ? "..." : (editingId ? "💾 Atualizar" : "💾 Adicionar")}
              </Button>
            </div>
          </div>
        )}

        {msg && (
          <div data-testid="asset-msg" style={{
            marginTop: 10, padding: 10, borderRadius: 8, fontSize: 12, fontWeight: 600,
            background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
            color: msg.type === "ok" ? "#166534" : "#7f1d1d",
          }}>{msg.text}</div>
        )}

        <div style={{ marginTop: 14, background: "white", borderRadius: 14,
                       border: "1px solid #e2e8f0", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                {["Categoria", "Item", "Marca/Modelo", "Tam.", "Qtd", "Valor", "Série",
                  "Entrega", "Status", "Assinatura", "Ações"].map((h) => (
                  <th key={h} style={{ padding: "8px 10px", textAlign: "left",
                                        fontSize: 10, fontWeight: 800, color: "#475569",
                                        textTransform: "uppercase" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 ? (
                <tr><td colSpan={11} style={{ padding: 28, textAlign: "center", color: "#64748b" }}>
                  Sem itens em custódia cadastrados ainda.
                </td></tr>
              ) : data.items.map((a) => {
                const cat = CATEGORIES.find((c) => c.id === a.category) || CATEGORIES[5];
                const st = STATUS_PILL[a.status] || STATUS_PILL.ativo;
                return (
                  <tr key={a.id} data-testid={`asset-row-${a.id}`}
                      style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 999,
                                      background: cat.color + "22", color: cat.color, fontWeight: 700 }}>
                        {cat.label}
                      </span>
                    </td>
                    <td style={{ padding: "8px 10px", fontWeight: 700 }}>{a.item}</td>
                    <td style={{ padding: "8px 10px" }}>
                      {[a.marca, a.modelo].filter(Boolean).join(" / ") || "—"}
                    </td>
                    <td style={{ padding: "8px 10px" }}>{a.tamanho || "—"}</td>
                    <td style={{ padding: "8px 10px" }}>{a.qty}</td>
                    <td style={{ padding: "8px 10px", fontWeight: 700, color: a.unit_value_brl ? "#0f172a" : "#94a3b8" }}>
                      {a.unit_value_brl != null
                        ? `R$ ${(a.unit_value_brl * (a.qty || 1)).toFixed(2).replace('.', ',')}`
                        : "—"}
                    </td>
                    <td style={{ padding: "8px 10px", fontFamily: "monospace", fontSize: 10 }}>
                      {a.serial || "—"}
                    </td>
                    <td style={{ padding: "8px 10px", fontSize: 11, color: "#64748b" }}>
                      {(a.delivered_at || "").slice(0, 10)}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{ padding: "2px 8px", borderRadius: 999,
                                      background: st.bg, color: st.color, fontWeight: 700, fontSize: 10 }}>
                        {st.label}
                      </span>
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      {a.signed_at
                        ? <span style={{ color: "#166534", fontWeight: 700, fontSize: 11 }}
                                title={`Assinado em ${a.signed_at}`}>✓ Assinado</span>
                        : <span style={{ color: "#92400e", fontWeight: 700, fontSize: 11 }}>⏳ Pendente</span>}
                    </td>
                    <td style={{ padding: "8px 10px", whiteSpace: "nowrap" }}>
                      <button onClick={() => startEdit(a)} data-testid={`asset-edit-${a.id}`}
                              style={btnIcon}>✏️</button>
                      {a.status === "ativo" && (
                        <button onClick={() => setStatus(a, "devolvido")}
                                data-testid={`asset-return-${a.id}`} title="Marcar como devolvido"
                                style={btnIcon}>↩️</button>
                      )}
                      <button onClick={() => remove(a)} data-testid={`asset-delete-${a.id}`}
                              style={{ ...btnIcon, color: "#dc2626" }}>🗑</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      {romaneioPdf && (
        <RomaneioPdfModal
          pdf={romaneioPdf}
          onClose={closeRomaneio}
          onDownload={downloadCurrentRomaneio}
        />
      )}
    </div>
  );
}

function RomaneioPdfModal({ pdf, onClose, onDownload }) {
  return (
    <div data-testid="romaneio-modal" onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.75)",
      zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center",
      padding: 12,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 12,
        width: "min(960px, 96vw)", height: "92vh",
        display: "flex", flexDirection: "column",
        boxShadow: "0 20px 60px rgba(0,0,0,.4)",
      }}>
        <div style={{
          padding: "12px 16px", borderBottom: "1px solid #e2e8f0",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          gap: 10, flexShrink: 0,
        }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, color: "#64748b",
              textTransform: "uppercase", letterSpacing: ".5px" }}>
              Termo de responsabilidade
            </div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
              {pdf.name || "Romaneio"}
            </h3>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {pdf.url && (
              <>
                <Button variant="soft" onClick={onDownload}
                          data-testid="romaneio-download-btn">
                  ↓ Baixar
                </Button>
                <Button variant="soft" onClick={async () => {
                  // Imprime usando a janela do iframe
                  const iframe = document.querySelector("[data-testid='romaneio-iframe']");
                  try {
                    iframe.contentWindow.focus();
                    iframe.contentWindow.print();
                  } catch (e) {
                    await window.alert("Use Ctrl+P para imprimir");
                  }
                }} data-testid="romaneio-print-btn">
                  🖨 Imprimir
                </Button>
              </>
            )}
            <Button onClick={onClose} data-testid="romaneio-close-btn">
              Fechar
            </Button>
          </div>
        </div>
        <div style={{ flex: 1, background: "#f8fafc", position: "relative" }}>
          {pdf.loading ? (
            <div style={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              flexDirection: "column", gap: 8, color: "#64748b",
            }}>
              <div style={{ fontSize: 28 }}>⏳</div>
              <div style={{ fontSize: 13, fontWeight: 700 }}>Gerando romaneio…</div>
              <div style={{ fontSize: 11, color: "#94a3b8" }}>Aguarde um instante.</div>
            </div>
          ) : pdf.url ? (
            <iframe
              data-testid="romaneio-iframe"
              src={pdf.url}
              title="Romaneio"
              style={{
                width: "100%", height: "100%",
                border: 0, background: "white",
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

const btnIcon = {
  padding: 4, border: 0, background: "transparent", cursor: "pointer",
  fontSize: 14, marginRight: 4,
};
