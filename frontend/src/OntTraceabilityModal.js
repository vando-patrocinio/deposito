/* OntTraceabilityModal — iter201 — Rastreabilidade ponta a ponta da ONT.
 *
 *   - Recebe um SN ou MAC (ident)
 *   - Chama /api/stok/onts/traceability/{ident}
 *   - Mostra: dados atuais + nota fiscal de origem + histórico
 *
 * Padrão dismissible (iter198): mousedown tracking + ESC + guard temporal.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { Loader2, X, Package, FileText, History, MapPin } from "lucide-react";

const PILL_STATUS = {
  disponivel: { bg: "#dcfce7", fg: "#166534", label: "Disponível" },
  instalada: { bg: "#dbeafe", fg: "#1e40af", label: "Instalada (cliente)" },
  retirada_com_tecnico: { bg: "#fef3c7", fg: "#92400e", label: "Com o técnico (retirada)" },
  defeito_devolver_empresa: { bg: "#fee2e2", fg: "#991b1b", label: "Defeito — devolver" },
  pendente_aprovacao_gestor: { bg: "#ede9fe", fg: "#6b21a8", label: "Pendente aprovação" },
};

const ACTION_LABELS = {
  install: "Instalação",
  withdraw: "Retirada",
  swap: "Troca",
  port_link: "Porta CTO vinculada",
  port_unlink: "❌ Porta CTO desvinculada",
};

function fmtDT(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR",
      { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

function fmtBRL(v) {
  if (v == null) return "—";
  return Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export default function OntTraceabilityModal({ ident, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [openedAt] = useState(() => Date.now());
  const mouseDownOnBackdropRef = useRef(false);

  const tryClose = useCallback(() => {
    if (Date.now() - openedAt < 350) return;
    onClose?.();
  }, [openedAt, onClose]);

  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") tryClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tryClose]);

  useEffect(() => {
    if (!ident) return;
    let alive = true;
    setLoading(true); setErr("");
    api.stokOntTraceability(ident)
      .then((r) => { if (alive) setData(r); })
      .catch((e) => {
        if (alive) setErr(e?.response?.data?.detail || e.message);
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [ident]);

  const ont = data?.ont;
  const purchase = data?.purchase;
  const history = data?.history || [];
  const statusPill = ont ? PILL_STATUS[ont.status] || {
    bg: "#f1f5f9", fg: "#475569", label: ont.status || "?" } : null;

  return (
    <div data-testid="ont-traceability-modal"
          onMouseDown={(e) => {
            mouseDownOnBackdropRef.current = e.target === e.currentTarget;
          }}
          onMouseUp={(e) => {
            if (mouseDownOnBackdropRef.current && e.target === e.currentTarget) tryClose();
            mouseDownOnBackdropRef.current = false;
          }}
          style={{ position: "fixed", inset: 0, zIndex: 9999,
                    background: "rgba(15,23,42,0.7)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 20 }}>
      <div onMouseDown={(e) => e.stopPropagation()}
            onMouseUp={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
            style={{ background: "#fff", borderRadius: 14,
                      width: "min(95vw, 720px)", maxHeight: "92vh",
                      display: "flex", flexDirection: "column",
                      overflow: "hidden",
                      boxShadow: "0 20px 60px rgba(0,0,0,0.35)" }}>
        {/* Header */}
        <div style={{ padding: 18, borderBottom: "1px solid #e2e8f0",
                        display: "flex", justifyContent: "space-between",
                        alignItems: "flex-start", gap: 12,
                        background: "linear-gradient(135deg,#0f172a,#1e293b)",
                        color: "white" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 10, fontWeight: 700,
                            textTransform: "uppercase", letterSpacing: 0.6,
                            opacity: 0.7, marginBottom: 4 }}>
              Rastreabilidade da ONT
            </div>
            <div style={{ fontSize: 20, fontWeight: 900, fontFamily: "monospace" }}>
              {ont?.sn || ident}
            </div>
            {ont?.mac && !/^(SN-|AUTOSN_|MANUAL-)/i.test(ont.mac) && (
              <div style={{ fontSize: 11, opacity: 0.7, fontFamily: "monospace",
                              marginTop: 2 }}>
                MAC: {ont.mac}
              </div>
            )}
          </div>
          <button onClick={tryClose}
                  data-testid="trace-close"
                  style={{ background: "rgba(255,255,255,0.15)", border: 0,
                            color: "white", cursor: "pointer", padding: 6,
                            borderRadius: 8 }}>
            <X size={20} />
          </button>
        </div>

        {/* iter201b — Botão "Exportar PDF" */}
        {ont && !loading && (
          <div style={{ padding: "10px 18px", background: "#f8fafc",
                          borderBottom: "1px solid #e2e8f0",
                          display: "flex", justifyContent: "flex-end" }}>
            <button
              data-testid="trace-export-pdf"
              onClick={async () => {
                try {
                  const resp = await api._client.get(
                    `/stok/onts/traceability/${encodeURIComponent(ident)}/pdf`,
                    { responseType: "blob" });
                  const blob = new Blob([resp.data], { type: "application/pdf" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `rastreabilidade_${(ont.sn || ident)
                    .replace(/[^a-zA-Z0-9_-]/g, "_")}.pdf`;
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                  URL.revokeObjectURL(url);
                } catch (e) {
                  window.alert("Falha ao gerar PDF: " +
                    (e?.response?.data?.detail || e.message));
                }
              }}
              style={{
                padding: "6px 14px", background: "#0f172a", color: "white",
                fontSize: 12, fontWeight: 700, borderRadius: 6, border: 0,
                cursor: "pointer", display: "inline-flex", gap: 6,
                alignItems: "center",
              }}>
              Exportar relatório PDF
            </button>
          </div>
        )}

        {/* Body */}
        <div style={{ padding: 18, overflowY: "auto", flex: 1 }}>
          {loading && (
            <div style={{ display: "flex", alignItems: "center", gap: 10,
                          color: "#64748b", padding: 20, justifyContent: "center" }}>
              <Loader2 size={18} className="animate-spin" /> Carregando rastreabilidade…
            </div>
          )}

          {err && (
            <div data-testid="trace-error"
                  style={{ background: "#fee2e2", color: "#991b1b",
                            padding: 14, borderRadius: 10, fontSize: 13 }}>
              {err}
            </div>
          )}

          {/* === 1) LOCALIZAÇÃO ATUAL === */}
          {ont && (
            <Section icon={<MapPin size={16} />} title="Onde está agora">
              <div style={{ display: "grid",
                              gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <Field label="Status">
                  {statusPill && (
                    <span data-testid="trace-status"
                          style={{ padding: "3px 10px", borderRadius: 999,
                                    background: statusPill.bg, color: statusPill.fg,
                                    fontSize: 11, fontWeight: 800 }}>
                      {statusPill.label}
                    </span>
                  )}
                </Field>
                <Field label="Modelo">{ont.model || "—"}</Field>
                <Field label="Localização">
                  <strong>{
                    ont.location_type === "empresa" ? "Estoque da empresa"
                    : ont.location_type === "tecnico" ? `${ont.location_name || "Técnico"}`
                    : ont.location_type === "cliente" ? `${ont.location_name || ont.withdrawn_from_client_name || "Cliente"}`
                    : ont.location_type || "—"
                  }</strong>
                </Field>
                <Field label="Cadastrada em">{fmtDT(ont.created_at)}</Field>
              </div>
            </Section>
          )}

          {/* === 2) NOTA FISCAL DE ORIGEM === */}
          {ont && (
            <Section icon={<FileText size={16} />}
                      title="Nota fiscal de origem" defaultOpen>
              {purchase ? (
                <div data-testid="trace-purchase"
                      style={{ background: "#eff6ff",
                                border: "1.5px solid #93c5fd",
                                padding: 14, borderRadius: 10 }}>
                  <div style={{ display: "grid",
                                  gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <Field label="Fornecedor">
                      <strong>{purchase.supplier_name || "—"}</strong>
                    </Field>
                    <Field label="Nº NF">
                      <span style={{ fontFamily: "monospace", fontWeight: 700 }}>
                        {purchase.invoice_number || "—"}
                      </span>
                    </Field>
                    <Field label="Data NF">{purchase.invoice_date || "—"}</Field>
                    <Field label="Valor total">
                      <strong>{fmtBRL(purchase.total_value)}</strong>
                    </Field>
                    <Field label="Praça">{purchase.praca_name || "—"}</Field>
                    <Field label="Responsável recebedor">
                      {purchase.responsible_name || "—"}
                    </Field>
                    {purchase.file_name && (
                      <Field label="Arquivo" colSpan={2}>
                        {purchase.file_name}
                      </Field>
                    )}
                    {purchase.notes && (
                      <Field label="Observações" colSpan={2}>
                        {purchase.notes}
                      </Field>
                    )}
                  </div>
                  <div style={{ marginTop: 10, paddingTop: 10,
                                  borderTop: "1px dashed #93c5fd",
                                  fontSize: 11, color: "#1e40af" }}>
                    ✅ Confirmada em <strong>{fmtDT(purchase.confirmed_at)}</strong>
                  </div>
                </div>
              ) : (
                <div data-testid="trace-no-purchase"
                      style={{ background: "#fef3c7", border: "1px solid #fde68a",
                                color: "#92400e", padding: 12, borderRadius: 10,
                                fontSize: 13 }}>
                  ️ Esta ONT não foi vinculada a nenhuma nota fiscal
                  (cadastrada manualmente em massa ou vinda de migração).
                </div>
              )}
            </Section>
          )}

          {/* === 3) HISTÓRICO DE EVENTOS === */}
          <Section icon={<History size={16} />}
                    title={`Histórico (${history.length} evento${history.length !== 1 ? "s" : ""})`}>
            {history.length === 0 ? (
              <div style={{ color: "#94a3b8", fontSize: 13, fontStyle: "italic" }}>
                Nenhum evento registrado ainda.
              </div>
            ) : (
              <div style={{ borderLeft: "2px solid #cbd5e1", paddingLeft: 14,
                              marginLeft: 4 }}>
                {history.map((h, i) => (
                  <div key={i} data-testid={`trace-history-${i}`}
                        style={{ position: "relative", marginBottom: 14,
                                  paddingBottom: 14,
                                  borderBottom: i < history.length - 1 ? "1px dashed #e2e8f0" : "none" }}>
                    <div style={{ position: "absolute", left: -19, top: 2,
                                    width: 10, height: 10, borderRadius: "50%",
                                    background: "#0f172a",
                                    boxShadow: "0 0 0 3px white" }} />
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                      {ACTION_LABELS[h.action] || h.action}
                    </div>
                    <div style={{ fontSize: 11, color: "#64748b", marginTop: 1 }}>
                      {fmtDT(h.created_at)}
                      {h.client_name && <> · Cliente: <strong>{h.client_name}</strong></>}
                      {h.cto_name && <> · CTO: <strong>{h.cto_name}</strong></>}
                      {h.cto_port_number && <> Porta {h.cto_port_number}</>}
                    </div>
                    {h.actor_name && (
                      <div style={{ fontSize: 11, color: "#475569", marginTop: 3 }}>
                        Por: <strong>{h.actor_name}</strong>
                        {h.actor_email && <span style={{ opacity: 0.7 }}> ({h.actor_email})</span>}
                      </div>
                    )}
                    {h.notes && (
                      <div style={{ fontSize: 11, color: "#475569", marginTop: 3,
                                      fontStyle: "italic" }}>
                        “{h.notes}”
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* === 4) PROCEDÊNCIA RETIRADA (se for ONT retirada) === */}
          {ont?.withdrawn_from_client_name && (
            <Section icon={<Package size={16} />} title="Procedência (última retirada)">
              <div style={{ background: "#fef3c7", padding: 12,
                              borderRadius: 10, fontSize: 13 }}>
                Esta ONT foi retirada do cliente{" "}
                <strong>{ont.withdrawn_from_client_name}</strong>
                {ont.withdrawn_by_name && <> por <strong>{ont.withdrawn_by_name}</strong></>}
                {ont.withdrawn_at && <> em <strong>{fmtDT(ont.withdrawn_at)}</strong></>}.
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ icon, title, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                      fontSize: 11, fontWeight: 800, color: "#475569",
                      textTransform: "uppercase", letterSpacing: 0.5,
                      marginBottom: 8 }}>
        {icon} {title}
      </div>
      {children}
    </div>
  );
}

function Field({ label, children, colSpan }) {
  return (
    <div style={{ gridColumn: colSpan === 2 ? "span 2" : undefined }}>
      <div style={{ fontSize: 9, fontWeight: 700, color: "#94a3b8",
                      textTransform: "uppercase", letterSpacing: 0.4,
                      marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 13, color: "#0f172a" }}>{children}</div>
    </div>
  );
}
