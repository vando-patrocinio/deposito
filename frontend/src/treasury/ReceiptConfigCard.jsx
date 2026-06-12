/**
 * ReceiptConfigCard.jsx — iter239
 * Card de configuração do COMPROVANTE WhatsApp enviado automaticamente
 * para fornecedores após pagamento.
 *
 * Permite:
 *   - Editar texto do template (com placeholders: {payee_name}, {amount}, etc)
 *   - Editar assinatura final
 *   - Subir um PDF/PNG/JPG (logo/template branded) que vai junto da mensagem
 *   - Ligar/desligar anexo
 *   - Pré-visualizar o resultado renderizado
 */
import React, { useEffect, useRef, useState } from "react";
import {
  FileText, Upload, Trash2, Save, Eye, RotateCcw, Paperclip,
  CheckCircle2, AlertCircle,
} from "lucide-react";
import { treasuryApi, C } from "./api";

const PLACEHOLDERS = [
  "{payee_name}", "{document}", "{amount}", "{method}",
  "{datetime}", "{transaction_id}", "{description}",
  "{category}", "{signature}",
];

export default function ReceiptConfigCard() {
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);
  const [preview, setPreview] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const fileInputRef = useRef(null);

  const load = async () => {
    setLoading(true); setErr(null);
    try {
      const c = await treasuryApi.getReceiptConfig();
      setCfg(c);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true); setErr(null); setOk(null);
    try {
      await treasuryApi.updateReceiptConfig({
        template_text: cfg.template_text,
        signature: cfg.signature,
        attach_pdf: !!cfg.attach_pdf,
      });
      setOk("Template salvo.");
      setTimeout(() => setOk(null), 2500);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setSaving(false); }
  };

  const upload = async (file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setErr("Arquivo excede 5MB."); return;
    }
    setUploading(true); setErr(null); setOk(null);
    try {
      await treasuryApi.uploadReceiptPdf(file);
      setOk(`Anexo "${file.name}" enviado.`);
      await load();
      setTimeout(() => setOk(null), 2500);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setUploading(false); }
  };

  const removePdf = async () => {
    if (!window.confirm("Remover o PDF/logo anexado?")) return;
    try {
      await treasuryApi.deleteReceiptPdf();
      await load();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  };

  const doPreview = async () => {
    setShowPreview(true); setPreview(null);
    try {
      const r = await treasuryApi.previewReceiptConfig();
      setPreview(r);
    } catch (e) { setPreview({ text: `Erro: ${e?.response?.data?.detail || e.message}` }); }
  };

  const insertPlaceholder = (ph) => {
    setCfg((s) => ({ ...s, template_text: (s.template_text || "") + " " + ph }));
  };

  if (loading) {
    return <div data-testid="receipt-config-loading"
      style={{ ...card, color: C.muted, padding: 16 }}>Carregando configuração...</div>;
  }
  if (!cfg) return null;

  return (
    <div data-testid="receipt-config-card" style={card}>
      <div style={header}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <FileText size={16} color={C.accent}/>
          <strong style={{ color: C.text, fontSize: 14 }}>
            Comprovante automático via WhatsApp
          </strong>
          <span style={{ background: cfg.is_default ? "#fef3c7" : "#dcfce7",
            color: cfg.is_default ? "#92400e" : "#166534",
            fontSize: 10, padding: "2px 8px", borderRadius: 10,
            fontWeight: 700, textTransform: "uppercase" }}>
            {cfg.is_default ? "Padrão SmartProv" : "Customizado"}
          </span>
        </div>
        <button data-testid="btn-preview-receipt" onClick={doPreview}
          style={btnGhost}><Eye size={13}/> Preview</button>
      </div>

      <div style={{ color: C.muted, fontSize: 12, marginBottom: 12 }}>
        Define a mensagem e o anexo que vão automaticamente para todo fornecedor
        com WhatsApp + auto-comprovante ativos, sempre que um pagamento for
        marcado como <strong>pago</strong>.
      </div>

      {/* Placeholders shortcut */}
      <div style={{ marginBottom: 10 }}>
        <div style={lbl}>Variáveis disponíveis (clique para inserir):</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {PLACEHOLDERS.map((ph) => (
            <button key={ph} data-testid={`btn-ph-${ph.replace(/[{}]/g, "")}`}
              onClick={() => insertPlaceholder(ph)} style={chip}>{ph}</button>
          ))}
        </div>
      </div>

      <label style={lbl}>Mensagem (template):</label>
      <textarea data-testid="input-template-text" value={cfg.template_text || ""}
        onChange={(e) => setCfg({ ...cfg, template_text: e.target.value })}
        rows={9} style={textarea} spellCheck={false}/>

      <label style={lbl}>Assinatura final:</label>
      <input data-testid="input-signature" value={cfg.signature || ""}
        onChange={(e) => setCfg({ ...cfg, signature: e.target.value })}
        style={input}/>

      {/* Anexo */}
      <div style={{ marginTop: 14, padding: 12, background: C.cardSoft,
        borderRadius: 8, border: `1px dashed ${C.border}` }}>
        <div style={{ display: "flex", alignItems: "center",
          justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Paperclip size={13} color={C.muted}/>
            <strong style={{ fontSize: 12, color: C.text }}>
              Anexo branded (PDF, PNG ou JPG · até 5MB)
            </strong>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 6,
            fontSize: 12, color: C.text, cursor: "pointer" }}>
            <input type="checkbox" data-testid="toggle-attach-pdf"
              checked={!!cfg.attach_pdf}
              onChange={(e) => setCfg({ ...cfg, attach_pdf: e.target.checked })}
              disabled={!cfg.has_pdf}/>
            Enviar anexo junto
          </label>
        </div>
        {cfg.has_pdf ? (
          <div data-testid="receipt-pdf-info" style={{ display: "flex",
            justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: 12, color: C.text }}>
              <FileText size={12} style={{ verticalAlign: "middle",
                marginRight: 4, color: C.accent }}/>
              <strong>{cfg.pdf_filename}</strong>
              <span style={{ color: C.muted, marginLeft: 8 }}>
                {Math.round((cfg.pdf_size_bytes || 0) / 1024)} KB ·{" "}
                {cfg.pdf_mimetype}
              </span>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button data-testid="btn-replace-pdf"
                onClick={() => fileInputRef.current?.click()}
                style={btnGhost}><RotateCcw size={12}/> Trocar</button>
              <button data-testid="btn-remove-pdf" onClick={removePdf}
                style={{ ...btnGhost, color: C.red, borderColor: "#fecaca" }}>
                <Trash2 size={12}/> Remover
              </button>
            </div>
          </div>
        ) : (
          <button data-testid="btn-upload-pdf"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            style={{ ...btnPrimary, width: "100%", justifyContent: "center" }}>
            <Upload size={13}/>
            {uploading ? "Enviando..." : "Subir PDF/PNG/JPG"}
          </button>
        )}
        <input ref={fileInputRef} type="file"
          data-testid="input-receipt-file"
          accept="application/pdf,image/png,image/jpeg"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
            e.target.value = "";
          }}/>
      </div>

      {err && (
        <div data-testid="receipt-config-err" style={errBox}>
          <AlertCircle size={13}/> {err}
        </div>
      )}
      {ok && (
        <div data-testid="receipt-config-ok" style={okBox}>
          <CheckCircle2 size={13}/> {ok}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button data-testid="btn-save-receipt-config" onClick={save}
          disabled={saving} style={{ ...btnPrimary, flex: 1, justifyContent: "center" }}>
          <Save size={13}/> {saving ? "Salvando..." : "Salvar template"}
        </button>
      </div>

      {showPreview && (
        <PreviewOverlay text={preview?.text}
          hasPdf={preview?.has_pdf} pdfName={preview?.pdf_filename}
          onClose={() => setShowPreview(false)}/>
      )}
    </div>
  );
}

function PreviewOverlay({ text, hasPdf, pdfName, onClose }) {
  return (
    <div data-testid="receipt-preview-overlay" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.55)",
      zIndex: 9100, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 20,
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: C.card, borderRadius: 14, width: 420,
        maxWidth: "92vw", padding: 18, border: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 12 }}>
          <strong style={{ color: C.text, fontSize: 14 }}>
            Preview do comprovante
          </strong>
          <button onClick={onClose} data-testid="btn-close-preview"
            style={{ background: "transparent", border: 0, color: C.muted,
              fontSize: 22, cursor: "pointer", lineHeight: 1 }}>×</button>
        </div>
        <div style={{ background: "#dcf8c6", padding: 12, borderRadius: 12,
          fontFamily: "Menlo, monospace", fontSize: 12, color: "#0f172a",
          whiteSpace: "pre-wrap", maxHeight: 320, overflowY: "auto" }}>
          {text || "Carregando preview..."}
        </div>
        {hasPdf && (
          <div style={{ marginTop: 10, padding: 10, background: C.cardSoft,
            borderRadius: 8, fontSize: 12, color: C.muted,
            display: "flex", alignItems: "center", gap: 6 }}>
            <Paperclip size={12}/> Anexo: <strong style={{ color: C.text }}>
            {pdfName}</strong>
          </div>
        )}
      </div>
    </div>
  );
}

const card = { background: C.card, border: `1px solid ${C.border}`,
  borderRadius: 12, padding: 16, marginBottom: 14 };
const header = { display: "flex", justifyContent: "space-between",
  alignItems: "center", marginBottom: 8 };
const lbl = { display: "block", color: C.muted, fontSize: 11,
  fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4,
  marginBottom: 4, marginTop: 8 };
const input = { width: "100%", padding: "8px 10px", borderRadius: 8,
  border: `1px solid ${C.border}`, background: "#fff", color: C.text,
  fontSize: 13, fontFamily: "inherit" };
const textarea = { ...input, minHeight: 160, resize: "vertical",
  fontFamily: "Menlo, monospace", fontSize: 12, lineHeight: 1.55 };
const btnPrimary = { background: C.accent, color: "white", border: 0,
  borderRadius: 8, padding: "8px 14px", fontWeight: 700, fontSize: 13,
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 };
const btnGhost = { background: "transparent", color: C.text,
  border: `1px solid ${C.border}`, borderRadius: 6, padding: "5px 10px",
  fontSize: 11, cursor: "pointer", display: "inline-flex",
  alignItems: "center", gap: 4 };
const chip = { background: "#eef2ff", color: "#3730a3", border: 0,
  borderRadius: 999, padding: "3px 8px", fontSize: 11, cursor: "pointer",
  fontFamily: "Menlo, monospace" };
const errBox = { background: "#fee2e2", color: "#991b1b", padding: 10,
  borderRadius: 8, marginTop: 12, fontSize: 12, display: "flex",
  alignItems: "center", gap: 6 };
const okBox = { background: "#dcfce7", color: "#166534", padding: 10,
  borderRadius: 8, marginTop: 12, fontSize: 12, display: "flex",
  alignItems: "center", gap: 6 };
