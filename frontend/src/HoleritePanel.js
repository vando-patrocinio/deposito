import React, { useEffect, useState } from "react";
import { Receipt, Upload, Download, Search, Calendar, User as UserIcon } from "lucide-react";
import { api } from "@/api";

/* =============================================================
   HoleritePanel — emissão e consulta de holerites
   Estrutura inicial (UI). Persistência mockada localStorage até
   o backend de Holerite ser construído (endpoint /api/holerites).
============================================================= */
const STORAGE_KEY = "smartprov_holerites_v1";

function loadLocal() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}
function saveLocal(items) {
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items)); } catch { /* ignore */ }
}

const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                  "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

export default function HoleritePanel() {
  const [items, setItems] = useState([]);
  const [collabs, setCollabs] = useState([]);
  const [filter, setFilter] = useState("");
  const [year, setYear] = useState(new Date().getFullYear());
  const [showUpload, setShowUpload] = useState(false);

  useEffect(() => {
    setItems(loadLocal());
    api.listCollaborators().then((data) => {
      setCollabs(Array.isArray(data) ? data : (data?.items || []));
    }).catch(() => setCollabs([]));
  }, []);

  function persist(next) {
    setItems(next);
    saveLocal(next);
  }

  function addHolerite(payload) {
    const next = [
      {
        id: `hol-${Date.now()}`,
        collab_id: payload.collab_id,
        collab_name: payload.collab_name,
        month: payload.month,
        year: payload.year,
        gross: parseFloat(payload.gross) || 0,
        net: parseFloat(payload.net) || 0,
        file_name: payload.file_name || null,
        file_data: payload.file_data || null, // base64
        created_at: new Date().toISOString(),
      },
      ...items,
    ];
    persist(next);
    setShowUpload(false);
  }

  function removeHolerite(id) {
    if (!window.confirm("Remover este holerite?")) return;
    persist(items.filter((h) => h.id !== id));
  }

  function downloadHolerite(h) {
    if (h.file_data) {
      const a = document.createElement("a");
      a.href = h.file_data;
      a.download = h.file_name || `holerite-${h.year}-${h.month}.pdf`;
      a.click();
    } else {
      window.alert("Sem arquivo PDF anexado.");
    }
  }

  const filtered = items.filter((h) => {
    if (year && h.year !== year) return false;
    if (filter && !`${h.collab_name}`.toLowerCase().includes(filter.toLowerCase())) return false;
    return true;
  });

  const totalGross = filtered.reduce((s, h) => s + (h.gross || 0), 0);
  const totalNet = filtered.reduce((s, h) => s + (h.net || 0), 0);
  const years = Array.from(new Set([year, ...items.map((h) => h.year)])).sort((a, b) => b - a);

  return (
    <div data-testid="holerite-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{
          width: 42, height: 42, borderRadius: 10,
          background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
          color: "#fff", display: "grid", placeItems: "center",
          boxShadow: "0 4px 12px rgba(99,102,241,.35)",
        }}>
          <Receipt size={20} strokeWidth={1.75} />
        </div>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, letterSpacing: "-0.02em" }}>
            Holerite
          </h2>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Emissão, consulta e arquivo de recibos de pagamento dos colaboradores.
          </div>
        </div>
        <span style={{ flex: 1 }} />
        <button onClick={() => setShowUpload(true)}
                data-testid="holerite-add-btn"
                style={btn("primary")}>
          <Upload size={14} /> Lançar holerite
        </button>
      </div>

      {/* KPIs */}
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
                       gap: 10 }}>
        <Kpi label="Holerites" value={filtered.length} accent="#6366f1" />
        <Kpi label="Bruto total" value={fmtBRL(totalGross)} accent="#10b981" />
        <Kpi label="Líquido total" value={fmtBRL(totalNet)} accent="#0ea5e9" />
        <Kpi label="Descontos" value={fmtBRL(totalGross - totalNet)}
             accent="#f59e0b" />
      </div>

      {/* Filtros */}
      <div className="surface" style={{
        padding: 12, borderRadius: 10,
        border: "1px solid var(--border-default)",
        display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
      }}>
        <div style={{ position: "relative", flex: 1, minWidth: 220 }}>
          <Search size={14} style={{ position: "absolute", left: 10, top: 10,
                                          color: "var(--text-muted)" }} />
          <input value={filter} onChange={(e) => setFilter(e.target.value)}
                 data-testid="holerite-filter"
                 placeholder="Filtrar por colaborador..."
                 style={{ ...input(), paddingLeft: 30 }} />
        </div>
        <select value={year} onChange={(e) => setYear(parseInt(e.target.value, 10))}
                data-testid="holerite-year"
                style={input(140)}>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      {/* Lista */}
      <div className="surface" data-testid="holerite-list" style={{
        padding: 0, borderRadius: 10,
        border: "1px solid var(--border-default)",
        overflow: "hidden",
      }}>
        {filtered.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center",
                          color: "var(--text-muted)", fontSize: 13 }}>
            <Receipt size={32} strokeWidth={1.25}
                     style={{ opacity: .4, marginBottom: 8 }} />
            <div style={{ fontWeight: 700, marginBottom: 4 }}>
              Nenhum holerite registrado{filter ? " com esse filtro" : ""}.
            </div>
            <div style={{ fontSize: 11 }}>
              Clique em <strong>Lançar holerite</strong> para começar.
            </div>
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "var(--bg-surface-2)" }}>
                <Th>Colaborador</Th>
                <Th>Mês/Ano</Th>
                <Th align="right">Bruto</Th>
                <Th align="right">Líquido</Th>
                <Th>Arquivo</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((h) => (
                <tr key={h.id} style={{ borderTop: "1px solid var(--border-default)" }}>
                  <Td>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <UserIcon size={13} color="var(--text-muted)" />
                      <strong>{h.collab_name || "—"}</strong>
                    </div>
                  </Td>
                  <Td>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <Calendar size={12} color="var(--text-muted)" />
                      {MONTHS[h.month - 1]}/{h.year}
                    </div>
                  </Td>
                  <Td align="right">{fmtBRL(h.gross)}</Td>
                  <Td align="right"><strong>{fmtBRL(h.net)}</strong></Td>
                  <Td>
                    {h.file_name ? (
                      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                        📎 {h.file_name.length > 24 ? h.file_name.slice(0, 22) + "…" : h.file_name}
                      </span>
                    ) : (
                      <span style={{ fontSize: 11, color: "var(--text-muted)",
                                        fontStyle: "italic" }}>—</span>
                    )}
                  </Td>
                  <Td align="right">
                    <button onClick={() => downloadHolerite(h)}
                            data-testid={`holerite-dl-${h.id}`}
                            style={btn("ghost", "xs")} disabled={!h.file_data}>
                      <Download size={11} /> PDF
                    </button>
                    <button onClick={() => removeHolerite(h.id)}
                            data-testid={`holerite-del-${h.id}`}
                            style={{ ...btn("ghost", "xs"),
                                       color: "#dc2626", marginLeft: 4 }}>
                      Excluir
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showUpload && (
        <UploadModal onClose={() => setShowUpload(false)}
                     onSubmit={addHolerite}
                     collabs={collabs} />
      )}
    </div>
  );
}

/* ----------------------- Upload modal ----------------------- */
function UploadModal({ onClose, onSubmit, collabs }) {
  const today = new Date();
  const [collabId, setCollabId] = useState("");
  const [collabName, setCollabName] = useState("");
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [year, setYear] = useState(today.getFullYear());
  const [gross, setGross] = useState("");
  const [net, setNet] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileData, setFileData] = useState("");
  const [busy, setBusy] = useState(false);

  function pickCollab(e) {
    const id = e.target.value;
    setCollabId(id);
    const c = collabs.find((x) => (x.id || x._id) === id);
    if (c) setCollabName(c.name || c.full_name || "");
  }

  function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      window.alert("Arquivo muito grande (limite 5MB).");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setFileName(file.name);
      setFileData(reader.result);
    };
    reader.readAsDataURL(file);
  }

  function submit() {
    if (!collabName) { window.alert("Informe o colaborador."); return; }
    if (!gross) { window.alert("Informe o valor bruto."); return; }
    setBusy(true);
    onSubmit({
      collab_id: collabId,
      collab_name: collabName,
      month, year, gross, net,
      file_name: fileName, file_data: fileData,
    });
    setBusy(false);
  }

  return (
    <div data-testid="holerite-upload-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.55)",
      display: "grid", placeItems: "center", zIndex: 1000,
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           style={{ width: 520, maxWidth: "92vw", maxHeight: "92vh",
                       overflowY: "auto", borderRadius: 12,
                       background: "var(--bg-surface)",
                       border: "1px solid var(--border-default)" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border-default)",
                          display: "flex", alignItems: "center", gap: 10 }}>
          <Upload size={18} color="#6366f1" />
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>Lançar holerite</h3>
        </div>
        <div style={{ padding: 20, display: "grid", gap: 12 }}>
          <Lbl>Colaborador</Lbl>
          {collabs.length > 0 ? (
            <select value={collabId} onChange={pickCollab}
                    data-testid="upload-collab"
                    style={input()}>
              <option value="">— Selecione —</option>
              {collabs.map((c) => (
                <option key={c.id || c._id} value={c.id || c._id}>
                  {c.name || c.full_name}
                </option>
              ))}
            </select>
          ) : (
            <input value={collabName} onChange={(e) => setCollabName(e.target.value)}
                   data-testid="upload-collab-name"
                   placeholder="Nome do colaborador"
                   style={input()} />
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <Lbl>Mês</Lbl>
              <select value={month} onChange={(e) => setMonth(parseInt(e.target.value, 10))}
                      data-testid="upload-month"
                      style={input()}>
                {MONTHS.map((m, i) =>
                  <option key={m} value={i + 1}>{m}</option>)}
              </select>
            </div>
            <div>
              <Lbl>Ano</Lbl>
              <input type="number" value={year}
                     onChange={(e) => setYear(parseInt(e.target.value, 10))}
                     data-testid="upload-year"
                     style={input()} />
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <Lbl>Valor bruto (R$)</Lbl>
              <input type="number" step="0.01" value={gross}
                     onChange={(e) => setGross(e.target.value)}
                     data-testid="upload-gross"
                     style={input()} placeholder="3500,00" />
            </div>
            <div>
              <Lbl>Valor líquido (R$)</Lbl>
              <input type="number" step="0.01" value={net}
                     onChange={(e) => setNet(e.target.value)}
                     data-testid="upload-net"
                     style={input()} placeholder="2890,50" />
            </div>
          </div>
          <Lbl>Arquivo PDF (opcional)</Lbl>
          <input type="file" accept="application/pdf,image/*"
                 onChange={handleFile}
                 data-testid="upload-file"
                 style={{ fontSize: 12 }} />
          {fileName && (
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              ✓ {fileName}
            </div>
          )}
        </div>
        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border-default)",
                          display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={btn("ghost")}>Cancelar</button>
          <button onClick={submit} disabled={busy}
                  data-testid="upload-submit"
                  style={btn("primary", "md", busy)}>
            {busy ? "Salvando..." : "Salvar holerite"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* -------- utilitários visuais -------- */
function Kpi({ label, value, accent }) {
  return (
    <div className="surface" style={{
      padding: 12, borderRadius: 10,
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${accent}`,
      background: "var(--bg-surface)",
    }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: ".05em" }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text-primary)",
                       marginTop: 4, letterSpacing: "-0.02em" }}>
        {value}
      </div>
    </div>
  );
}
function Th({ children, align = "left" }) {
  return <th style={{ padding: "10px 12px", textAlign: align, fontSize: 11,
                          fontWeight: 800, textTransform: "uppercase",
                          color: "var(--text-muted)", letterSpacing: ".05em" }}>
    {children}
  </th>;
}
function Td({ children, align = "left" }) {
  return <td style={{ padding: "10px 12px", textAlign: align,
                          fontSize: 13, color: "var(--text-primary)" }}>
    {children}
  </td>;
}
function Lbl({ children }) {
  return <label style={{ fontSize: 11, fontWeight: 800,
                              color: "var(--text-muted)",
                              textTransform: "uppercase",
                              letterSpacing: ".05em" }}>{children}</label>;
}
function input(width) {
  return {
    width: width || "100%", padding: "8px 10px",
    border: "1px solid var(--border-default)", borderRadius: 8,
    fontSize: 13, background: "var(--bg-surface)",
    color: "var(--text-primary)", outline: "none",
  };
}
function btn(variant = "primary", size = "md", disabled = false) {
  const sizes = {
    xs: { padding: "4px 8px", fontSize: 11 },
    md: { padding: "8px 14px", fontSize: 12 },
  };
  const base = {
    ...(sizes[size] || sizes.md),
    borderRadius: 8, fontWeight: 800,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.6 : 1,
    display: "inline-flex", alignItems: "center", gap: 5,
  };
  if (variant === "primary")
    return { ...base, border: "1px solid #6366f1", background: "#6366f1", color: "white" };
  return { ...base, border: "1px solid var(--border-default)",
              background: "var(--bg-surface)", color: "var(--text-primary)" };
}
function fmtBRL(v) {
  const n = Number(v || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
