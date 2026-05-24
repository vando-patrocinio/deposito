import React, { useRef, useState } from "react";
import { api } from "@/api";
import { Upload, FileText, X, Check, AlertTriangle } from "lucide-react";

/**
 * Importer de extrato CSV TicketLog/Edenred.
 * Fluxo: arquivo → preview (dry_run) → confirmação → criação efetiva.
 */
export default function TicketLogImporter({ onClose, onSuccess }) {
  const fileRef = useRef(null);
  const [filename, setFilename] = useState("");
  const [delimiter, setDelimiter] = useState(";");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [csvContent, setCsvContent] = useState("");

  async function readFile(file) {
    if (!file) return;
    setFilename(file.name);
    setErr(""); setPreview(null);
    const text = await file.text();
    setCsvContent(text);
    await runPreview(text, delimiter);
  }

  async function runPreview(content, delim) {
    setBusy(true); setErr("");
    try {
      const r = await api.fleetFuelImportCsv(content,
        { delimiter: delim, dry_run: true });
      setPreview(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  async function confirmImport() {
    if (!preview || !csvContent) return;
    if (!window.confirm(
      `Confirmar importação de ${preview.total_entries_to_create} lançamento(s) ` +
      `(${preview.total_rows_parsed} transações da TicketLog)?\n\n` +
      `⚠ Lançamentos serão criados agrupados por veículo × mês.`
    )) return;
    setBusy(true); setErr("");
    try {
      const r = await api.fleetFuelImportCsv(csvContent,
        { delimiter, dry_run: false });
      alert(`✅ ${r.created} lançamento(s) criados com sucesso!`);
      onSuccess && onSuccess();
      onClose();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  return (
    <div data-testid="ticketlog-importer" onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
                 zIndex: 1100, display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 14, padding: 0,
        width: "min(96vw, 820px)", maxHeight: "92vh", overflow: "hidden",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{
          background: "linear-gradient(135deg,#f59e0b,#d97706)",
          color: "white", padding: "16px 22px",
          display: "flex", alignItems: "center", gap: 14,
        }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12,
            background: "rgba(255,255,255,0.2)",
            display: "grid", placeItems: "center",
          }}>
            <FileText size={22} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 800 }}>
              Importar extrato TicketLog
            </div>
            <div style={{ fontSize: 12, opacity: 0.9, marginTop: 2 }}>
              Edenred CSV — agrupa transações por veículo × mês automaticamente
            </div>
          </div>
          <button data-testid="tlimp-close-btn" onClick={onClose}
            style={{ background: "transparent", border: "none",
                       color: "white", cursor: "pointer", fontSize: 24,
                       lineHeight: 1, padding: "0 4px" }}>×</button>
        </div>

        {/* Body */}
        <div style={{ padding: 18, overflowY: "auto", flex: 1 }}>
          {!preview ? (
            <>
              <div style={{ background: "#eff6ff", border: "1px solid #bfdbfe",
                              padding: 12, borderRadius: 10, marginBottom: 14,
                              fontSize: 13, color: "#1e40af", lineHeight: 1.5 }}>
                <strong>📋 Como obter o CSV:</strong><br/>
                1. Acesse <a href="https://plataforma.ticketlog.com.br/home"
                              target="_blank" rel="noreferrer"
                              style={{ color: "#1d4ed8", fontWeight: 700 }}>
                  plataforma.ticketlog.com.br
                </a><br/>
                2. Vá em <em>Relatórios → Transações</em><br/>
                3. Selecione o período desejado<br/>
                4. Clique em <em>Exportar → CSV</em>
              </div>

              <div style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 12, fontWeight: 700, color: "#475569",
                                  display: "block", marginBottom: 4 }}>
                  Separador do CSV
                </label>
                <select value={delimiter}
                  data-testid="tlimp-delimiter"
                  onChange={(e) => setDelimiter(e.target.value)}
                  className="input" style={{ maxWidth: 200 }}>
                  <option value=";">Ponto-e-vírgula (padrão TicketLog)</option>
                  <option value=",">Vírgula</option>
                  <option value="\t">Tab</option>
                </select>
              </div>

              <div
                onClick={() => fileRef.current?.click()}
                style={{
                  border: "2px dashed #cbd5e1", borderRadius: 12,
                  padding: 36, textAlign: "center", cursor: "pointer",
                  background: "#f8fafc",
                  transition: "background .15s",
                }}
                onMouseOver={(e) => { e.currentTarget.style.background = "#f1f5f9"; }}
                onMouseOut={(e) => { e.currentTarget.style.background = "#f8fafc"; }}>
                <Upload size={36} style={{ color: "#94a3b8", marginBottom: 8 }} />
                <div style={{ fontSize: 15, fontWeight: 700, color: "#0f172a" }}>
                  {filename || "Clique para selecionar o CSV"}
                </div>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                  Arquivo .csv exportado da plataforma TicketLog
                </div>
                <input ref={fileRef} type="file" accept=".csv,.txt"
                  data-testid="tlimp-file-input"
                  style={{ display: "none" }}
                  onChange={(e) => readFile(e.target.files?.[0])} />
              </div>

              {busy && (
                <div style={{ marginTop: 12, color: "#0369a1", fontSize: 13,
                                textAlign: "center" }}>
                  Lendo CSV…
                </div>
              )}
              {err && (
                <div style={{ marginTop: 12, background: "#fee2e2",
                                color: "#991b1b", padding: 10, borderRadius: 8,
                                fontSize: 13 }}>
                  {err}
                </div>
              )}
            </>
          ) : (
            <>
              <div style={{ display: "flex", gap: 10, marginBottom: 16,
                              flexWrap: "wrap" }}>
                <StatPill testid="tlimp-rows-parsed" label="Transações lidas"
                  value={preview.total_rows_parsed} color="#0ea5e9" />
                <StatPill testid="tlimp-to-create" label="Lançamentos a criar"
                  value={preview.total_entries_to_create} color="#10b981" />
                <StatPill testid="tlimp-unmatched"
                  label={`Placa(s) não cadastrada(s)`}
                  value={preview.unmatched_count} color="#f59e0b" />
              </div>

              {preview.unmatched_count > 0 && (
                <div style={{ background: "#fef3c7", border: "1px solid #fcd34d",
                                padding: 12, borderRadius: 10, marginBottom: 14,
                                fontSize: 13, color: "#92400e" }}>
                  <AlertTriangle size={14} style={{ verticalAlign: "middle" }} />{" "}
                  <strong>{preview.unmatched_count} placa(s)</strong> do extrato
                  não estão cadastradas no sistema e <em>serão ignoradas</em>:{" "}
                  <code style={{ background: "white", padding: "1px 5px",
                                    borderRadius: 4, fontSize: 12 }}>
                    {preview.unmatched_placas.join(", ")}
                  </code>
                  {preview.unmatched_count > preview.unmatched_placas.length &&
                    <> …</>}
                  <div style={{ marginTop: 6, fontSize: 11 }}>
                    Cadastre essas placas em <em>Frota → Veículos → Novo</em>
                    {" "}antes de re-importar para incluí-las.
                  </div>
                </div>
              )}

              {preview.anomalies && preview.anomalies.total_flagged > 0 && (
                <div data-testid="tlimp-anomalies-block" style={{
                  background: "linear-gradient(135deg,#fef2f2,#fff7ed)",
                  border: "1px solid #fca5a5", borderLeft: "4px solid #dc2626",
                  padding: 12, borderRadius: 10, marginBottom: 14,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8,
                                  marginBottom: 8 }}>
                    <AlertTriangle size={16} style={{ color: "#dc2626" }} />
                    <strong style={{ color: "#991b1b", fontSize: 14 }}>
                      🚨 {preview.anomalies.total_flagged} transação(ões) suspeita(s) detectada(s)
                    </strong>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                                  marginBottom: 10, fontSize: 11 }}>
                    {Object.entries(preview.anomalies.summary).map(([k, v]) => (
                      <span key={k} style={{
                        background: "white", padding: "3px 8px",
                        borderRadius: 999, fontWeight: 700,
                        border: "1px solid #fecaca", color: "#991b1b",
                      }}>
                        {{
                          preco_alto: "💸 Preço alto",
                          volume_alto: "⛽ Volume alto",
                          abastecimento_duplo: "🔁 Duplo mesmo dia",
                          km_retrograde: "↩️ KM regrediu",
                        }[k] || k}: {v}
                      </span>
                    ))}
                  </div>
                  <details style={{ marginTop: 4 }}>
                    <summary style={{ cursor: "pointer", color: "#991b1b",
                                         fontSize: 12, fontWeight: 700 }}>
                      Ver detalhes das transações sinalizadas
                    </summary>
                    <div style={{ display: "grid", gap: 4, marginTop: 8,
                                    maxHeight: 200, overflow: "auto" }}>
                      {preview.anomalies.transactions.map((t, i) => (
                        <div key={i}
                          data-testid={`tlimp-anomaly-${i}`}
                          style={{
                            padding: 8, background: "white",
                            border: "1px solid #fecaca", borderRadius: 6,
                            fontSize: 11,
                          }}>
                          <div style={{ display: "flex", gap: 6, alignItems: "center",
                                          marginBottom: 4 }}>
                            <strong style={{ fontFamily: "ui-monospace,monospace",
                                                color: "#0f172a" }}>
                              {t.placa}
                            </strong>
                            <span style={{ color: "#64748b" }}>{t.data}</span>
                            <span style={{ color: "#dc2626", fontWeight: 700,
                                              marginLeft: "auto" }}>
                              R$ {(t.valor_total || 0).toFixed(2)}
                            </span>
                          </div>
                          <div style={{ color: "#64748b", fontSize: 10 }}>
                            {t.posto} {t.combustivel && `· ${t.combustivel}`}
                            {t.litros && ` · ${t.litros}L`}
                            {t.motorista && ` · ${t.motorista}`}
                          </div>
                          <div style={{ marginTop: 4, display: "flex",
                                          gap: 4, flexWrap: "wrap" }}>
                            {t.alerts.map((a, j) => (
                              <span key={j} style={{
                                padding: "2px 7px", borderRadius: 4,
                                fontSize: 10, fontWeight: 700,
                                background: a.severity === "high" ? "#fee2e2"
                                  : a.severity === "medium" ? "#fef3c7" : "#e0f2fe",
                                color: a.severity === "high" ? "#991b1b"
                                  : a.severity === "medium" ? "#a16207" : "#0c4a6e",
                              }}>
                                {a.msg}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                  <div style={{ marginTop: 8, fontSize: 11, color: "#7f1d1d",
                                  fontStyle: "italic" }}>
                    💡 Estes alertas não bloqueiam a importação — investigue depois
                    no histórico de combustível.
                  </div>
                </div>
              )}

              <h4 style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 800,
                            color: "#475569", textTransform: "uppercase",
                            letterSpacing: 0.5 }}>
                Preview · {preview.preview.length} grupo(s)
              </h4>
              <div style={{ display: "grid", gap: 6, marginBottom: 14,
                              maxHeight: 280, overflow: "auto" }}>
                {preview.preview.map((g, i) => (
                  <div key={i} data-testid={`tlimp-prev-${i}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "auto 1fr auto auto",
                      gap: 10, alignItems: "center", padding: "8px 10px",
                      background: "#f8fafc", border: "1px solid #e2e8f0",
                      borderRadius: 8, fontSize: 12,
                    }}>
                    <span style={{ fontFamily: "ui-monospace,monospace",
                                      fontWeight: 700, color: "#0f172a" }}>
                      {g.placa}
                    </span>
                    <span style={{ color: "#64748b" }}>
                      {g.month_ref} · {g.transactions} transação(ões)
                      {g.litros > 0 && ` · ${g.litros} L`}
                    </span>
                    <span style={{ fontWeight: 700, color: "#dc2626",
                                      whiteSpace: "nowrap" }}>
                      R$ {g.valor_total.toFixed(2)}
                    </span>
                    <span style={{ color: "#0ea5e9", fontWeight: 700, fontSize: 11 }}>
                      <Check size={11} />
                    </span>
                  </div>
                ))}
              </div>

              {preview.errors.length > 0 && (
                <details style={{ marginBottom: 14, fontSize: 12 }}>
                  <summary style={{ cursor: "pointer", color: "#dc2626",
                                       fontWeight: 700 }}>
                    {preview.errors.length} aviso(s) ao parsear
                  </summary>
                  <ul style={{ marginTop: 6, paddingLeft: 18,
                                  color: "#7f1d1d", fontSize: 11 }}>
                    {preview.errors.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </details>
              )}

              {err && (
                <div style={{ marginBottom: 12, background: "#fee2e2",
                                color: "#991b1b", padding: 10, borderRadius: 8,
                                fontSize: 13 }}>
                  {err}
                </div>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <button data-testid="tlimp-reset-btn"
                  onClick={() => { setPreview(null); setFilename(""); setCsvContent(""); }}
                  style={{ padding: "10px 16px",
                             background: "white", border: "1px solid #e2e8f0",
                             borderRadius: 8, fontWeight: 600, cursor: "pointer" }}>
                  ← Outro arquivo
                </button>
                <button data-testid="tlimp-confirm-btn"
                  onClick={confirmImport}
                  disabled={busy || preview.total_entries_to_create === 0}
                  style={{ padding: "10px 22px", flex: 1,
                             background: preview.total_entries_to_create > 0
                               ? "#10b981" : "#94a3b8",
                             color: "white", border: "none", borderRadius: 8,
                             fontWeight: 800, cursor: busy ? "wait" : "pointer" }}>
                  {busy ? "Importando…" :
                    `✅ Confirmar — criar ${preview.total_entries_to_create} lançamento(s)`}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatPill({ testid, label, value, color }) {
  return (
    <div data-testid={testid} style={{
      flex: 1, minWidth: 130, background: "white",
      border: `1px solid ${color}33`, borderTop: `3px solid ${color}`,
      borderRadius: 10, padding: 10,
    }}>
      <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color, marginTop: 2 }}>
        {value}
      </div>
    </div>
  );
}
