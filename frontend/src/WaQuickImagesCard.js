/* WaQuickImagesCard — gerencia até 5 imagens "rápidas" do WhatsApp.
   As imagens ficam disponíveis no botão "Imagens Rápidas" do header do chat.
*/
import React, { useEffect, useRef, useState } from "react";
import { ImagePlus, Trash2, AlertCircle, CheckCircle2, X } from "lucide-react";
import { api } from "@/api";
import { Card } from "@/ui";

const TOKEN_KEY = "ponto_token";

export default function WaQuickImagesCard() {
  const [items, setItems] = useState([]);
  const [max, setMax] = useState(5);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState({ msg: "", type: "" });
  const [label, setLabel] = useState("");
  const fileRef = useRef(null);

  async function reload() {
    try {
      const r = await api._client.get("/whatsapp-baileys/quick-images");
      setItems(r.data.items || []);
      setMax(r.data.max || 5);
    } catch (e) {
      setStatus({ msg: e?.response?.data?.detail || e.message, type: "error" });
    }
  }
  useEffect(() => { reload(); }, []);

  async function upload(file) {
    if (!file) return;
    if (items.length >= max) {
      setStatus({ msg: `Limite de ${max} imagens. Remova uma primeiro.`, type: "error" });
      return;
    }
    setUploading(true);
    setStatus({ msg: "", type: "" });
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("label", label || file.name.slice(0, 60));
      await api._client.post("/whatsapp-baileys/quick-images", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setLabel("");
      if (fileRef.current) fileRef.current.value = "";
      setStatus({ msg: "Imagem adicionada com sucesso.", type: "ok" });
      await reload();
    } catch (e) {
      setStatus({ msg: e?.response?.data?.detail || e.message, type: "error" });
    } finally {
      setUploading(false);
    }
  }

  async function remove(id) {
    if (!await window.confirm("Remover esta imagem rápida?")) return;
    try {
      await api._client.delete(`/whatsapp-baileys/quick-images/${id}`);
      await reload();
    } catch (e) {
      setStatus({ msg: e?.response?.data?.detail || e.message, type: "error" });
    }
  }

  const token = window.localStorage.getItem(TOKEN_KEY) || "";
  const baseUrl = process.env.REACT_APP_BACKEND_URL || "";

  return (
    <Card style={{ padding: 0 }} data-testid="wa-quick-images-card">
      <div style={{ padding: 16, borderBottom: "1px solid #e2e8f0",
                     display: "flex", alignItems: "center", gap: 10 }}>
        <ImagePlus size={20} style={{ color: "#7c3aed" }} />
        <div style={{ flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#0f172a" }}>
            Imagens Rápidas ({items.length}/{max})
          </h3>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b" }}>
            Imagens prontas para o atendente enviar com um clique pelo ícone{" "}
            <strong>“Imagens Rápidas”</strong> no cabeçalho do chat.
          </p>
        </div>
      </div>

      <div style={{ padding: 16 }}>
        {/* Upload */}
        <div style={{ padding: 14, borderRadius: 10,
                       background: "#faf5ff", border: "1px dashed #c4b5fd",
                       marginBottom: 14 }}>
          <input type="text" value={label}
                 placeholder="Nome/descrição (opcional)"
                 onChange={(e) => setLabel(e.target.value)}
                 data-testid="wa-qi-label"
                 style={inputStyle} />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <input ref={fileRef} type="file" accept="image/*"
                   data-testid="wa-qi-file"
                   disabled={uploading || items.length >= max}
                   onChange={(e) => upload(e.target.files?.[0])}
                   style={{ flex: 1, fontSize: 12 }} />
          </div>
          {items.length >= max && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#7c3aed" }}>
              Limite atingido. Remova uma imagem para adicionar outra.
            </div>
          )}
        </div>

        {/* Thumbnails */}
        {items.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center",
                         color: "#94a3b8", fontSize: 13 }}>
            Nenhuma imagem cadastrada ainda.
          </div>
        ) : (
          <div style={{ display: "grid",
                         gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                         gap: 12 }}>
            {items.map((it) => (
              <div key={it.id} style={{
                border: "1px solid #e2e8f0", borderRadius: 10,
                overflow: "hidden", background: "white",
              }} data-testid={`wa-qi-item-${it.id}`}>
                <div style={{
                  aspectRatio: "16/10", background: "#f1f5f9",
                  backgroundImage: `url("${baseUrl}${it.url}?t=${encodeURIComponent(token)}")`,
                  backgroundSize: "cover", backgroundPosition: "center",
                }} />
                <div style={{ padding: 8, display: "flex",
                               justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 11, color: "#475569",
                                  fontWeight: 600, overflow: "hidden",
                                  textOverflow: "ellipsis", whiteSpace: "nowrap",
                                  maxWidth: 130 }}
                         title={it.label}>
                    {it.label || "(sem nome)"}
                  </span>
                  <button onClick={() => remove(it.id)}
                           data-testid={`wa-qi-delete-${it.id}`}
                           style={{
                             border: "none", background: "transparent",
                             cursor: "pointer", color: "#dc2626",
                             padding: 4, borderRadius: 6,
                           }}
                           title="Remover">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {status.msg && (
        <div style={{
          padding: 12, borderTop: "1px solid #e2e8f0",
          background: status.type === "ok" ? "#dcfce7" : "#fee2e2",
          color: status.type === "ok" ? "#166534" : "#991b1b",
          fontSize: 12, fontWeight: 600,
          display: "flex", alignItems: "center", gap: 6,
        }}>
          {status.type === "ok" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {status.msg}
          <X size={14} style={{ marginLeft: "auto", cursor: "pointer" }}
              onClick={() => setStatus({ msg: "", type: "" })} />
        </div>
      )}
    </Card>
  );
}

const inputStyle = {
  width: "100%", padding: 8, borderRadius: 6,
  border: "1px solid #cbd5e1", fontSize: 13, fontFamily: "inherit",
};
