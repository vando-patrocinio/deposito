/**
 * WallpaperConfigCard — Card para administrador subir/trocar o papel de
 * parede do chat WhatsApp. Salva no backend (`aihub_settings.wa_chat_wallpaper`)
 * como data URL base64.
 *
 * Aparece na sub-aba "Configuração" do Atendimento IA.
 */
import React, { useEffect, useRef, useState } from "react";
import { Image as ImageIcon, Upload, Trash2, Check } from "lucide-react";
import { api } from "@/api";

const DEFAULT_FALLBACK = "/wa-wallpaper-ligo.png?v=3";
const MAX_BYTES = 5 * 1024 * 1024;  // 5 MB

export default function WallpaperConfigCard() {
  const [current, setCurrent] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [updatedBy, setUpdatedBy] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [savedAt, setSavedAt] = useState(null);
  const fileRef = useRef(null);

  async function load() {
    try {
      const r = await api.waBaileysGetWallpaper();
      setCurrent(r.image_data_url || null);
      setUpdatedAt(r.updated_at || null);
      setUpdatedBy(r.updated_by || null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }
  useEffect(() => { load(); }, []);

  async function handleFile(file) {
    if (!file) return;
    if (!/^image\//.test(file.type)) {
      setErr("Arquivo precisa ser uma imagem (PNG, JPG, WEBP).");
      return;
    }
    if (file.size > MAX_BYTES) {
      setErr(`Imagem grande demais (${(file.size / 1024 / 1024).toFixed(1)} MB). Limite: 5 MB.`);
      return;
    }
    setBusy(true); setErr("");
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => resolve(fr.result);
        fr.onerror = () => reject(new Error("Falha ao ler arquivo"));
        fr.readAsDataURL(file);
      });
      await api.waBaileysSetWallpaper(dataUrl);
      setCurrent(dataUrl);
      setSavedAt(new Date().toISOString());
      setTimeout(() => setSavedAt(null), 3000);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  async function handleRemove() {
    if (!confirm("Remover o papel de parede customizado e voltar ao padrão Ligo?")) return;
    setBusy(true); setErr("");
    try {
      await api.waBaileysSetWallpaper(null);
      setCurrent(null);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  }

  const previewUrl = current || DEFAULT_FALLBACK;
  return (
    <div data-testid="wa-wallpaper-config" style={{
      padding: 20, borderRadius: 12,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      marginBottom: 16,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                      marginBottom: 14 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 8,
          background: "linear-gradient(135deg, #25d366, #128c7e)",
          color: "#fff", display: "grid", placeItems: "center",
        }}>
          <ImageIcon size={18} strokeWidth={2.2} />
        </div>
        <div>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700,
                        color: "var(--text-primary)" }}>
            Papel de parede do chat WhatsApp
          </h3>
          <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
            Substitua o fundo padrão por uma imagem da sua empresa. Aparece para
            todos os atendentes no Atendimento IA.
          </p>
        </div>
        {savedAt && (
          <span style={{
            marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 4,
            padding: "4px 10px", borderRadius: 999,
            background: "rgba(22,163,74,.12)", color: "#15803d",
            fontSize: 11, fontWeight: 700,
          }}>
            <Check size={12} /> Salvo
          </span>
        )}
      </div>

      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14,
      }}>
        {/* Preview */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.5,
                          marginBottom: 6 }}>
            Pré-visualização
          </div>
          <div style={{
            position: "relative",
            height: 200, borderRadius: 8, overflow: "hidden",
            backgroundColor: "#efeae2",
            backgroundImage: `url("${previewUrl}")`,
            backgroundRepeat: "repeat",
            backgroundSize: current ? "cover" : "auto",
            backgroundBlendMode: "multiply",
            border: "1px solid var(--border-default)",
          }}>
            {/* Bolhas de exemplo pra mostrar como vai ficar */}
            <div style={{ position: "absolute", left: 18, top: 16,
                            background: "#fff", padding: "6px 10px",
                            borderRadius: "8px 8px 8px 2px",
                            fontSize: 11, color: "#0b1220",
                            boxShadow: "0 1px 1px rgba(11,20,26,.13)" }}>
              Olá! Aqui é a Isabella 👋
            </div>
            <div style={{ position: "absolute", right: 18, top: 64,
                            background: "#d9fdd3", padding: "6px 10px",
                            borderRadius: "8px 8px 2px 8px",
                            fontSize: 11, color: "#0b1220",
                            boxShadow: "0 1px 1px rgba(11,20,26,.13)" }}>
              Oi, quero saber sobre o plano de 600 MB
            </div>
            <div style={{ position: "absolute", left: 18, top: 110,
                            background: "#fff", padding: "6px 10px",
                            borderRadius: "8px 8px 8px 2px",
                            fontSize: 11, color: "#0b1220",
                            boxShadow: "0 1px 1px rgba(11,20,26,.13)" }}>
              Claro! Posso te ajudar.
            </div>
          </div>
          <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 6 }}>
            {current
              ? <>Customizado{updatedAt
                  ? ` · atualizado ${new Date(updatedAt).toLocaleString("pt-BR")}`
                  : ""}{updatedBy ? ` por ${updatedBy}` : ""}</>
              : "Usando o padrão Ligo"}
          </div>
        </div>

        {/* Ações */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            Ações
          </div>
          <input ref={fileRef} type="file" accept="image/*"
                 onChange={(e) => handleFile(e.target.files?.[0])}
                 style={{ display: "none" }} data-testid="wa-wallpaper-file-input" />
          <button onClick={() => fileRef.current?.click()} disabled={busy}
                  data-testid="wa-wallpaper-upload-btn"
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    justifyContent: "center",
                    padding: "10px 14px", borderRadius: 8,
                    background: "linear-gradient(135deg, #25d366, #128c7e)",
                    color: "#fff", border: "none", cursor: "pointer",
                    fontWeight: 700, fontSize: 12.5,
                    boxShadow: "0 1px 3px rgba(18,140,126,.3)",
                  }}>
            <Upload size={14} strokeWidth={2.4} />
            {busy ? "Enviando..." : (current ? "Trocar imagem" : "Subir imagem")}
          </button>
          {current && (
            <button onClick={handleRemove} disabled={busy}
                    data-testid="wa-wallpaper-remove-btn"
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      justifyContent: "center",
                      padding: "8px 14px", borderRadius: 8,
                      background: "transparent",
                      color: "#dc2626", border: "1px solid rgba(220,38,38,.3)",
                      cursor: "pointer",
                      fontWeight: 600, fontSize: 12,
                    }}>
              <Trash2 size={13} /> Voltar ao padrão Ligo
            </button>
          )}
          <ul style={{ margin: 0, padding: "0 0 0 16px", color: "var(--text-muted)",
                        fontSize: 11, lineHeight: 1.6 }}>
            <li>PNG, JPG ou WEBP. Limite 5 MB.</li>
            <li>Recomendado: textura/padrão repetível, 600×600px ou maior.</li>
            <li>Aplica-se a todas as conversas da sua empresa.</li>
          </ul>
          {err && (
            <div style={{ padding: 8, borderRadius: 6,
                            background: "rgba(239,68,68,.08)",
                            color: "#dc2626", fontSize: 11, fontWeight: 600 }}>
              {err}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
