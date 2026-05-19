/* ============================================================================
 * BoletoPdfPreviewCard — Pré-visualização + troca do logo do PDF do boleto
 *
 * Permite ao gestor:
 *  1. Ver como o PDF Ligo Fibra está saindo (preview ao vivo)
 *  2. Trocar o logo (upload PNG/JPG, max 2 MB)
 *  3. Reverter para o logo padrão (do site oficial)
 * ========================================================================== */
import React, { useEffect, useRef, useState } from "react";
import { api, API } from "@/api";
import {
  FileText, Upload, RefreshCw, Trash2, Image as ImageIcon,
  Loader2, CheckCircle2, AlertCircle,
} from "lucide-react";

const Card = ({ children, style = {}, ...rest }) => (
  <div
    {...rest}
    style={{
      background: "var(--bg-surface, #fff)",
      border: "1px solid var(--border-default, #e2e8f0)",
      borderRadius: 14,
      padding: 16,
      ...style,
    }}>
    {children}
  </div>
);

export default function BoletoPdfPreviewCard() {
  const [logoInfo, setLogoInfo] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [msg, setMsg] = useState(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  const loadLogo = async () => {
    try {
      const info = await api.boletoLogoGet();
      setLogoInfo(info);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  const loadPreview = async () => {
    setPreviewLoading(true);
    try {
      const blob = await api.boletoPreviewPngBlob();
      // Revoke anterior pra não vazar memória
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally { setPreviewLoading(false); }
  };

  const downloadPdf = async () => {
    try {
      const blob = await api.boletoPreviewBlob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "Boleto Ligo Preview.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 500);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  useEffect(() => {
    loadLogo();
    loadPreview();
    return () => { if (previewUrl) URL.revokeObjectURL(previewUrl); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFile = async (file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      setMsg({ kind: "err", text: `Arquivo grande (${(file.size / 1024).toFixed(0)}KB). Máx 2 MB.` });
      return;
    }
    if (!/^image\/(png|jpe?g|webp)$/i.test(file.type)) {
      setMsg({ kind: "err", text: "Use PNG, JPEG ou WebP." });
      return;
    }
    setUploading(true);
    setMsg(null);
    try {
      const data_url = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result);
        r.onerror = reject;
        r.readAsDataURL(file);
      });
      await api.boletoLogoSet(data_url);
      setMsg({ kind: "ok", text: "Logo atualizado!" });
      await loadLogo();
      await loadPreview();
      setTimeout(() => setMsg(null), 3500);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally { setUploading(false); }
  };

  const handleRevert = async () => {
    if (!await window.confirm("Voltar para o logo padrão Ligo Fibra?")) return;
    try {
      await api.boletoLogoDelete();
      setMsg({ kind: "ok", text: "Logo padrão restaurado." });
      await loadLogo();
      await loadPreview();
      setTimeout(() => setMsg(null), 3500);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  return (
    <Card data-testid="boleto-pdf-preview-card">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 9,
          background: "linear-gradient(135deg,#6A1B9A,#00BF9E)",
          display: "grid", placeItems: "center",
        }}>
          <FileText size={18} color="white" strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--text-primary)" }}>
            PDF do Boleto Branded
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            Pré-visualize como o PDF chega ao cliente e troque o logo se quiser
          </div>
        </div>
        <button
          onClick={loadPreview}
          disabled={previewLoading}
          data-testid="boleto-preview-refresh-btn"
          style={btnGhost}
          title="Recarregar preview"
        >
          <RefreshCw size={14} className={previewLoading ? "spin" : ""} />
          Atualizar
        </button>
        <button
          onClick={downloadPdf}
          data-testid="boleto-preview-download-btn"
          style={btnGhost}
          title="Baixar PDF completo"
        >
          <FileText size={14} /> Baixar PDF
        </button>
      </div>

      {/* Layout: preview + painel de logo lado a lado */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.5fr) minmax(220px, 1fr)",
        gap: 14,
      }}>
        {/* PREVIEW PDF */}
        <div style={{
          border: "1px solid var(--border-default)",
          borderRadius: 10,
          overflow: "hidden",
          background: "#f1f5f9",
          minHeight: 480,
          display: "grid", placeItems: "center",
        }}>
          {previewLoading && !previewUrl ? (
            <div style={{ color: "var(--text-muted)", fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
              <Loader2 size={16} className="spin" /> Gerando preview…
            </div>
          ) : previewUrl ? (
            <div style={{ width: "100%", padding: 12, background: "#e2e8f0", display: "grid", placeItems: "center" }}>
              <img
                data-testid="boleto-preview-img"
                src={previewUrl}
                alt="Pré-visualização do boleto PDF"
                onError={(ev) => {
                  // Evita "Script error." cross-origin no overlay do CRA
                  ev.currentTarget.onerror = null;
                  ev.currentTarget.style.display = "none";
                  setMsg({ kind: "err",
                            text: "Não foi possível carregar a imagem de pré-visualização." });
                }}
                style={{
                  maxWidth: "100%",
                  maxHeight: 720,
                  width: "auto",
                  boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
                  borderRadius: 4,
                  background: "white",
                }}
              />
            </div>
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
              Sem preview disponível
            </div>
          )}
        </div>

        {/* PAINEL DE LOGO */}
        <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)", marginBottom: 6 }}>
              <ImageIcon size={12} style={{ verticalAlign: "middle", marginRight: 4 }} />
              Logo do PDF
            </div>
            <div style={{
              border: "1px dashed var(--border-default)",
              borderRadius: 10,
              padding: 12,
              background: "var(--bg-elevated)",
              display: "grid", placeItems: "center",
              minHeight: 100,
            }}>
              {logoInfo?.custom && logoInfo?.image_data_url ? (
                <img src={logoInfo.image_data_url}
                  alt="logo customizado"
                  style={{ maxWidth: "100%", maxHeight: 80, objectFit: "contain" }} />
              ) : (
                <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 11 }}>
                  Logo padrão Ligo Fibra<br />(do site oficial)
                </div>
              )}
            </div>
            {logoInfo?.custom && (
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
                {logoInfo.size_bytes ? `${(logoInfo.size_bytes / 1024).toFixed(0)} KB` : ""}
                {logoInfo.updated_at && ` · ${new Date(logoInfo.updated_at).toLocaleDateString("pt-BR")}`}
                {logoInfo.updated_by && ` · ${logoInfo.updated_by}`}
              </div>
            )}
          </div>

          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            ref={fileRef}
            style={{ display: "none" }}
            onChange={(e) => handleFile(e.target.files?.[0])}
          />

          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            data-testid="boleto-logo-upload-btn"
            style={btnPrimary}
          >
            {uploading ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
            {uploading ? "Enviando…" : (logoInfo?.custom ? "Substituir logo" : "Subir logo customizado")}
          </button>

          {logoInfo?.custom && (
            <button
              onClick={handleRevert}
              data-testid="boleto-logo-revert-btn"
              style={btnDanger}
            >
              <Trash2 size={14} /> Voltar ao logo padrão
            </button>
          )}

          <div style={{
            fontSize: 10.5, color: "var(--text-muted)", lineHeight: 1.5,
            padding: "8px 10px", borderRadius: 6,
            background: "rgba(106,27,154,.06)",
            border: "1px solid rgba(106,27,154,.15)",
          }}>
            💡 <b>Recomendado:</b> PNG com fundo transparente, proporção horizontal (3:1), mínimo 300x100px. Máx 2 MB.
          </div>
        </div>
      </div>

      {msg && (
        <div style={{
          marginTop: 10, padding: "8px 12px", borderRadius: 8,
          background: msg.kind === "ok" ? "rgba(16,185,129,.12)" : "rgba(220,38,38,.12)",
          color: msg.kind === "ok" ? "#047857" : "#b91c1c",
          fontSize: 12, display: "flex", alignItems: "center", gap: 6,
        }}>
          {msg.kind === "ok" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {msg.text}
        </div>
      )}
    </Card>
  );
}

const btnPrimary = {
  padding: "9px 14px", border: 0, borderRadius: 8,
  background: "linear-gradient(135deg,#6A1B9A,#00BF9E)",
  color: "white", fontSize: 12, fontWeight: 700,
  cursor: "pointer",
  display: "inline-flex", alignItems: "center", gap: 6, justifyContent: "center",
};
const btnDanger = {
  padding: "8px 14px", border: "1px solid rgba(220,38,38,.3)",
  background: "transparent", color: "#dc2626",
  borderRadius: 8, fontSize: 12, fontWeight: 600,
  cursor: "pointer",
  display: "inline-flex", alignItems: "center", gap: 6, justifyContent: "center",
};
const btnGhost = {
  padding: "6px 12px", border: "1px solid var(--border-default)",
  background: "transparent", color: "var(--text-primary)",
  borderRadius: 8, fontSize: 11, fontWeight: 600,
  cursor: "pointer",
  display: "inline-flex", alignItems: "center", gap: 4,
};
