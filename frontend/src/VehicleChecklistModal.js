import React, { useEffect, useMemo, useRef, useState } from "react";
import { Car, Plus, Printer, Trash2, X, CheckCircle2, AlertTriangle, Minus, FileText, Image as ImageIcon, Upload } from "lucide-react";
import { api } from "@/api";
import { Button } from "@/ui";
import VehicleSilhouette, { VIEW_KEYS, VIEW_LABELS, DAMAGE_TYPES } from "@/VehicleSilhouettes";

const STATUS_BTN = {
  ok:      { label: "OK",      icon: CheckCircle2, bg: "var(--success-soft)",   fg: "var(--success-soft-fg)", active: "#16a34a" },
  defeito: { label: "Defeito", icon: AlertTriangle, bg: "var(--danger-soft)",    fg: "var(--danger-soft-fg)",  active: "#dc2626" },
  na:      { label: "N/A",     icon: Minus,         bg: "var(--bg-surface-2)",   fg: "var(--text-secondary)",  active: "#475569" },
};

function pctColor(p) {
  if (p >= 95) return "var(--success-soft-fg)";
  if (p >= 80) return "var(--warning-soft-fg)";
  return "var(--danger-soft-fg)";
}

export default function VehicleChecklistModal({ collaborator, onClose }) {
  const [tab, setTab] = useState("new"); // new | history
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  // form state
  const [plate, setPlate] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [year, setYear] = useState("");
  const [kmI, setKmI] = useState("");
  const [route, setRoute] = useState("");
  const [items, setItems] = useState([]);
  const [notes, setNotes] = useState("");
  const [marks, setMarks] = useState([]);          // damage marks
  const [pendingMark, setPendingMark] = useState(null); // {x, y, view} sendo definida
  const [attachments, setAttachments] = useState([]);   // [{kind, label, data_url}]
  const fileInputRef = useRef(null);

  useEffect(() => {
    let alive = true;
    api.vehicleChecklistTemplate().then((r) => {
      if (!alive) return;
      setItems(r.items.map((it) => ({ ...it, status: "ok", notes: "" })));
    }).catch(() => { /* ignore */ });
    return () => { alive = false; };
  }, []);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const r = await api.vehicleChecklistList({ collaborator_id: collaborator.id, limit: 50 });
      setHistory(r.items || []);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (tab === "history") loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const setItemStatus = (idx, status) => {
    setItems((prev) => prev.map((it, i) => {
      if (i !== idx) return it;
      // Limpa notas ao sair de "defeito" para evitar dados invisíveis no payload
      const notes = status === "defeito" ? it.notes : "";
      return { ...it, status, notes };
    }));
  };
  const setItemNotes = (idx, val) => {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, notes: val } : it)));
  };

  const grouped = useMemo(() => {
    const g = {};
    items.forEach((it, idx) => {
      g[it.cat] = g[it.cat] || [];
      g[it.cat].push({ ...it, _idx: idx });
    });
    return g;
  }, [items]);

  const conformity = useMemo(() => {
    const total = items.filter((it) => it.status !== "na").length;
    const ok = items.filter((it) => it.status === "ok").length;
    const defects = items.filter((it) => it.status === "defeito").length;
    const pct = total > 0 ? +(100 * ok / total).toFixed(1) : 100;
    return { total, ok, defects, pct };
  }, [items]);

  async function submit() {
    if (!plate.trim()) { alert("Informe a placa do veículo."); return; }
    setBusy(true);
    try {
      const created = await api.vehicleChecklistCreate({
        collaborator_id: collaborator.id,
        plate: plate.toUpperCase().trim(),
        vehicle_brand: brand || null,
        vehicle_model: model || null,
        vehicle_year: year ? Number(year) : null,
        km_initial: kmI ? Number(kmI) : null,
        route: route || null,
        items,
        damage_marks: marks,
        attachments,
        general_notes: notes || null,
      });
      // Open PDF in new tab
      window.open(api.vehicleChecklistPdfUrl(created.id), "_blank");
      // Switch to history
      setTab("history");
      // reset form
      setItems((prev) => prev.map((it) => ({ ...it, status: "ok", notes: "" })));
      setPlate(""); setBrand(""); setModel(""); setYear(""); setKmI(""); setRoute(""); setNotes("");
      setMarks([]); setAttachments([]); setPendingMark(null);
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  }

  // ---- Damage marks handlers ----
  const handleAddMark = (point) => {
    // Mostra um small popover para escolher o tipo + descrição
    setPendingMark({ ...point, code: "D", notes: "", ord: marks.length + 1 });
  };

  const confirmMark = () => {
    if (!pendingMark) return;
    setMarks((prev) => [...prev, { ...pendingMark, ord: prev.length + 1 }]);
    setPendingMark(null);
  };

  const cancelMark = () => setPendingMark(null);

  const removeMark = (idx) => {
    setMarks((prev) => prev.filter((_, i) => i !== idx)
                          .map((m, i) => ({ ...m, ord: i + 1 })));
  };

  // ---- Attachments handlers ----
  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      alert("Apenas imagens são aceitas.");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      alert("Arquivo muito grande (máximo 8MB).");
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const data_url = ev.target.result;
      setAttachments((prev) => [...prev, {
        kind: "paper_checklist",
        label: file.name,
        data_url,
      }]);
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  const removeAttachment = (idx) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  };

  async function removeChecklist(id) {
    if (!confirm("Remover este checklist permanentemente?")) return;
    await api.vehicleChecklistDelete(id);
    loadHistory();
  }

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(11,18,32,.55)",
      backdropFilter: "blur(4px)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} className="surface" style={{
        width: "100%", maxWidth: 1080, maxHeight: "92vh", padding: 0,
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          padding: "18px 22px", borderBottom: "1px solid var(--border-default)",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 38, height: 38, borderRadius: 10,
              background: "var(--accent-soft)", color: "var(--accent-soft-fg)",
              display: "grid", placeItems: "center",
            }}>
              <Car size={20} strokeWidth={1.75} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, letterSpacing: "-0.018em" }}>
                Checklist Veicular
              </h2>
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                Inspeção pré-jornada · {collaborator.name}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="btn btn-ghost btn-icon btn-sm" data-testid="vchk-close">
            <X size={16} strokeWidth={1.75} />
          </button>
        </div>

        {/* Tabs */}
        <div style={{ padding: "0 22px", borderBottom: "1px solid var(--border-default)", display: "flex", gap: 4 }}>
          {[
            { id: "new", label: "Novo checklist", icon: Plus },
            { id: "history", label: "Histórico", icon: FileText },
          ].map((t) => {
            const Ico = t.icon;
            const active = tab === t.id;
            return (
              <button key={t.id} onClick={() => setTab(t.id)}
                      data-testid={`vchk-tab-${t.id}`}
                      className="btn btn-ghost"
                      style={{
                        height: 42, padding: "0 12px", borderRadius: 0,
                        borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
                        color: active ? "var(--accent-soft-fg)" : "var(--text-secondary)",
                        fontWeight: 600,
                      }}>
                <Ico size={14} strokeWidth={1.75} /> {t.label}
              </button>
            );
          })}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: 22 }}>
          {tab === "new" && (
            <>
              {/* Identificação */}
              <div style={{
                display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: 12, marginBottom: 18,
              }}>
                <Field label="Placa *">
                  <input className="input" data-testid="vchk-plate" value={plate}
                         onChange={(e) => setPlate(e.target.value.toUpperCase())}
                         placeholder="ABC-1D23" maxLength={10} />
                </Field>
                <Field label="Marca">
                  <input className="input" data-testid="vchk-brand" value={brand}
                         onChange={(e) => setBrand(e.target.value)}
                         placeholder="Fiat" />
                </Field>
                <Field label="Modelo">
                  <input className="input" data-testid="vchk-model" value={model}
                         onChange={(e) => setModel(e.target.value)}
                         placeholder="Strada" />
                </Field>
                <Field label="Ano">
                  <input className="input" data-testid="vchk-year" type="number" value={year}
                         onChange={(e) => setYear(e.target.value)}
                         placeholder="2023" />
                </Field>
                <Field label="KM inicial">
                  <input className="input" data-testid="vchk-km" type="number" value={kmI}
                         onChange={(e) => setKmI(e.target.value)}
                         placeholder="28430" />
                </Field>
                <Field label="Rota / finalidade">
                  <input className="input" data-testid="vchk-route" value={route}
                         onChange={(e) => setRoute(e.target.value)}
                         placeholder="Centro - Bairro Industrial" />
                </Field>
              </div>

              {/* Conformity bar */}
              <div className="surface-soft" data-testid="vchk-conformity" style={{
                padding: "12px 16px", marginBottom: 16,
                display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap",
              }}>
                <div>
                  <div className="eyebrow">Conformidade prevista</div>
                  <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.02em",
                                color: pctColor(conformity.pct) }}>
                    {conformity.pct}%
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  <span className="pill pill--success">{conformity.ok} OK</span>
                  <span className="pill pill--danger">{conformity.defects} defeito(s)</span>
                  <span className="pill pill--neutral">{conformity.total} aplicáveis</span>
                </div>
                <div style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-muted)" }}>
                  {items.length} itens no template (CONTRAN)
                </div>
              </div>

              {/* Items grouped */}
              {Object.entries(grouped).map(([cat, list]) => (
                <div key={cat} style={{ marginBottom: 18 }}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
                    paddingBottom: 6, borderBottom: "1px solid var(--border-default)",
                  }}>
                    <span className="pill pill--accent" style={{ fontSize: 10, letterSpacing: "0.06em",
                                                                  fontWeight: 700, textTransform: "uppercase" }}>{cat}</span>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{list.length} ite{list.length > 1 ? "ns" : "m"}</span>
                  </div>
                  {list.map((it) => (
                    <div key={it._idx} className="vchk-item" data-testid={`vchk-row-${it._idx}`} style={{
                      display: "grid", gridTemplateColumns: "1fr auto",
                      gap: 8, padding: "8px 0", borderBottom: "1px dashed var(--border-default)",
                      alignItems: "center",
                    }}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500 }}>
                          {it.name}
                        </div>
                        {it.status === "defeito" && (
                          <input className="input" data-testid={`vchk-notes-${it._idx}`}
                                 value={it.notes}
                                 onChange={(e) => setItemNotes(it._idx, e.target.value)}
                                 placeholder="Descreva o defeito (obrigatório)"
                                 style={{ marginTop: 6, height: 30, fontSize: 12 }} />
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 4 }}>
                        {Object.entries(STATUS_BTN).map(([key, cfg]) => {
                          const sel = it.status === key;
                          const Ico = cfg.icon;
                          return (
                            <button
                              key={key}
                              onClick={() => setItemStatus(it._idx, key)}
                              data-testid={`vchk-${key}-${it._idx}`}
                              className="btn btn-sm"
                              style={{
                                background: sel ? cfg.active : cfg.bg,
                                color: sel ? "#fff" : cfg.fg,
                                border: `1px solid ${sel ? cfg.active : "transparent"}`,
                                fontWeight: 600,
                                minWidth: 70,
                              }}
                            >
                              <Ico size={12} strokeWidth={2} /> {cfg.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ))}

              {/* Diagrama de Avarias */}
              <div style={{ marginTop: 22, marginBottom: 18 }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 8, marginBottom: 10,
                  paddingBottom: 6, borderBottom: "1px solid var(--border-default)",
                }}>
                  <span className="pill pill--accent" style={{
                    fontSize: 10, letterSpacing: "0.06em", fontWeight: 700, textTransform: "uppercase",
                  }}>Diagrama de avarias</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    Clique nas silhuetas para marcar danos · {marks.length} marca(s)
                  </span>
                </div>

                <div style={{
                  display: "grid", gap: 10,
                  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                }}>
                  {VIEW_KEYS.map((v) => (
                    <div key={v} style={{ position: "relative" }}>
                      <div style={{
                        fontSize: 11, fontWeight: 700, color: "var(--text-secondary)",
                        textTransform: "uppercase", letterSpacing: "0.06em",
                        marginBottom: 4, display: "flex", justifyContent: "space-between",
                      }}>
                        <span>{VIEW_LABELS[v]}</span>
                        {marks.filter((m) => m.view === v).length > 0 && (
                          <span style={{ color: "var(--danger-soft-fg)" }}>
                            {marks.filter((m) => m.view === v).length} avaria(s)
                          </span>
                        )}
                      </div>
                      <VehicleSilhouette
                        view={v}
                        marks={marks.map((m, i) => ({ ...m, ord: i + 1 }))}
                        onAddMark={handleAddMark}
                        height={140}
                      />
                    </div>
                  ))}
                </div>

                {/* Pending mark editor */}
                {pendingMark && (
                  <div data-testid="vchk-mark-editor" className="surface" style={{
                    marginTop: 12, padding: 14, border: "2px solid var(--accent)",
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>
                      Nova marca em <span style={{ color: "var(--accent-soft-fg)" }}>{VIEW_LABELS[pendingMark.view]}</span>
                    </div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                      {Object.entries(DAMAGE_TYPES).map(([code, info]) => {
                        const sel = pendingMark.code === code;
                        return (
                          <button
                            key={code}
                            onClick={() => setPendingMark({ ...pendingMark, code })}
                            data-testid={`vchk-mark-code-${code}`}
                            className="btn btn-sm"
                            style={{
                              background: sel ? info.color : "var(--bg-surface-2)",
                              color: sel ? "#fff" : info.color,
                              borderColor: info.color, fontWeight: 700,
                              minWidth: 80,
                            }}
                          >
                            <span style={{ fontWeight: 800, marginRight: 4 }}>{code}</span> {info.label}
                          </button>
                        );
                      })}
                    </div>
                    <input className="input" data-testid="vchk-mark-notes"
                           value={pendingMark.notes}
                           onChange={(e) => setPendingMark({ ...pendingMark, notes: e.target.value })}
                           placeholder="Descreva (opcional)"
                           style={{ marginBottom: 10 }} />
                    <div style={{ display: "flex", gap: 8 }}>
                      <Button onClick={confirmMark} variant="accent" data-testid="vchk-mark-confirm">
                        Adicionar marca
                      </Button>
                      <Button onClick={cancelMark} variant="ghost" data-testid="vchk-mark-cancel">
                        Cancelar
                      </Button>
                    </div>
                  </div>
                )}

                {/* Lista de marks */}
                {marks.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                      <thead>
                        <tr style={{ background: "var(--bg-surface-2)" }}>
                          <th style={th}>#</th>
                          <th style={th}>Vista</th>
                          <th style={th}>Tipo</th>
                          <th style={th}>Descrição</th>
                          <th style={th}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {marks.map((m, i) => (
                          <tr key={i} data-testid={`vchk-mark-row-${i}`} style={{ borderBottom: "1px solid var(--border-default)" }}>
                            <td style={td}>
                              <span style={{
                                display: "inline-grid", placeItems: "center",
                                width: 22, height: 22, borderRadius: "50%",
                                background: DAMAGE_TYPES[m.code]?.color || "#dc2626",
                                color: "#fff", fontWeight: 700, fontSize: 11,
                              }}>{i + 1}</span>
                            </td>
                            <td style={td}>{VIEW_LABELS[m.view]}</td>
                            <td style={td}>
                              <span className="pill" style={{
                                background: (DAMAGE_TYPES[m.code]?.color || "#dc2626") + "22",
                                color: DAMAGE_TYPES[m.code]?.color, fontWeight: 700,
                              }}>{m.code} · {DAMAGE_TYPES[m.code]?.label}</span>
                            </td>
                            <td style={td}>{m.notes || <span style={{ color: "var(--text-muted)" }}>—</span>}</td>
                            <td style={td}>
                              <button onClick={() => removeMark(i)}
                                      data-testid={`vchk-mark-remove-${i}`}
                                      className="btn btn-ghost btn-sm btn-icon">
                                <Trash2 size={12} strokeWidth={1.75} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Anexos / Upload de fotos */}
              <div style={{ marginBottom: 18 }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 8, marginBottom: 10,
                  paddingBottom: 6, borderBottom: "1px solid var(--border-default)",
                }}>
                  <span className="pill pill--accent" style={{
                    fontSize: 10, letterSpacing: "0.06em", fontWeight: 700, textTransform: "uppercase",
                  }}>Anexos</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    Foto do checklist em papel ou registros de avarias · {attachments.length} arquivo(s)
                  </span>
                </div>

                <input ref={fileInputRef} type="file" accept="image/*"
                       onChange={handleFile} style={{ display: "none" }}
                       data-testid="vchk-file-input" />
                <Button onClick={() => fileInputRef.current?.click()}
                        variant="secondary" data-testid="vchk-attach-btn">
                  <Upload size={14} strokeWidth={1.75} /> Anexar foto / scan
                </Button>

                {attachments.length > 0 && (
                  <div style={{
                    marginTop: 12, display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                  }}>
                    {attachments.map((att, i) => (
                      <div key={i} data-testid={`vchk-att-${i}`} style={{
                        position: "relative", borderRadius: 8,
                        border: "1px solid var(--border-default)",
                        background: "var(--bg-surface)", overflow: "hidden",
                      }}>
                        <img src={att.data_url} alt={att.label}
                             style={{ width: "100%", height: 110, objectFit: "cover" }} />
                        <div style={{ padding: "6px 8px", fontSize: 10,
                                       color: "var(--text-secondary)",
                                       borderTop: "1px solid var(--border-default)",
                                       display: "flex", justifyContent: "space-between",
                                       alignItems: "center", gap: 4 }}>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                                          whiteSpace: "nowrap", flex: 1 }}>
                            {att.label || "anexo"}
                          </span>
                          <button onClick={() => removeAttachment(i)}
                                  data-testid={`vchk-att-remove-${i}`}
                                  className="btn btn-ghost btn-icon" style={{ height: 22, width: 22 }}>
                            <Trash2 size={11} strokeWidth={1.75} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Notes */}
              <Field label="Observações gerais">
                <textarea className="input" data-testid="vchk-general-notes"
                          value={notes} onChange={(e) => setNotes(e.target.value)}
                          placeholder="Ex: veículo em bom estado, próxima revisão em 5.000 km."
                          style={{ minHeight: 70 }} />
              </Field>
            </>
          )}

          {tab === "history" && (
            <>
              {historyLoading && <div style={{ color: "var(--text-secondary)" }}>Carregando…</div>}
              {!historyLoading && history.length === 0 && (
                <div className="surface-soft" style={{ padding: 28, textAlign: "center",
                                                        color: "var(--text-secondary)" }}>
                  Nenhum checklist veicular registrado para este colaborador ainda.
                </div>
              )}
              {!historyLoading && history.length > 0 && (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: "var(--bg-surface-2)" }}>
                      <th style={th}>Data</th>
                      <th style={th}>Placa</th>
                      <th style={th}>Veículo</th>
                      <th style={th}>KM</th>
                      <th style={{ ...th, textAlign: "center" }}>Conformidade</th>
                      <th style={th}>Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => {
                      const c = h.conformity || {};
                      return (
                        <tr key={h.id} data-testid={`vchk-hist-${h.id}`} style={{ borderBottom: "1px solid var(--border-default)" }}>
                          <td style={td}>
                            <div className="mono">{(h.created_at || "").slice(0, 10)}</div>
                            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{(h.created_at || "").slice(11, 16)}</div>
                          </td>
                          <td style={td}><span className="mono" style={{ fontWeight: 700 }}>{h.plate}</span></td>
                          <td style={td}>
                            {[h.vehicle_brand, h.vehicle_model].filter(Boolean).join(" ") || "—"}
                            {h.vehicle_year && <span style={{ color: "var(--text-muted)" }}> · {h.vehicle_year}</span>}
                          </td>
                          <td style={td} className="mono">{h.km_initial ? `${Number(h.km_initial).toLocaleString("pt-BR")}` : "—"}</td>
                          <td style={{ ...td, textAlign: "center" }}>
                            <span style={{
                              fontSize: 14, fontWeight: 700,
                              color: pctColor(c.pct ?? 100),
                            }}>{c.pct ?? 100}%</span>
                            {c.defeitos > 0 && (
                              <span className="pill pill--danger" style={{ marginLeft: 6, fontSize: 10 }}>
                                {c.defeitos} def
                              </span>
                            )}
                          </td>
                          <td style={td}>
                            <div style={{ display: "flex", gap: 6 }}>
                              <a href={api.vehicleChecklistPdfUrl(h.id)} target="_blank" rel="noopener noreferrer"
                                 className="btn btn-secondary btn-sm"
                                 data-testid={`vchk-pdf-${h.id}`}>
                                <Printer size={12} strokeWidth={1.75} /> PDF
                              </a>
                              <button onClick={() => removeChecklist(h.id)}
                                      className="btn btn-ghost btn-sm btn-icon"
                                      data-testid={`vchk-del-${h.id}`}
                                      title="Remover">
                                <Trash2 size={13} strokeWidth={1.75} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {tab === "new" && (
          <div style={{
            padding: "12px 22px", borderTop: "1px solid var(--border-default)",
            background: "var(--bg-surface-2)", display: "flex", alignItems: "center", gap: 12,
          }}>
            <span style={{ fontSize: 11, color: "var(--text-muted)", flex: 1 }}>
              Ao salvar, o PDF do checklist será gerado automaticamente.
            </span>
            <Button onClick={onClose} variant="ghost" data-testid="vchk-cancel">Cancelar</Button>
            <Button onClick={submit} disabled={busy || !plate.trim()}
                    variant="accent" data-testid="vchk-submit">
              <Plus size={14} strokeWidth={1.75} /> {busy ? "Salvando…" : "Salvar e gerar PDF"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "block" }}>
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

const th = { padding: "8px 10px", textAlign: "left", fontSize: 11,
             color: "var(--text-secondary)", fontWeight: 700,
             textTransform: "uppercase", letterSpacing: "0.06em",
             borderBottom: "1px solid var(--border-default)" };
const td = { padding: "10px", verticalAlign: "middle" };
