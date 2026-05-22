/* WhatsAppShareCard — botão "Copiar link" + QR-code gerado on-the-fly
   do click-to-chat público da empresa. Pra colar no Instagram bio,
   adesivo de carro, camiseta, etc. */
import React, { useEffect, useState, useCallback } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api } from "@/api";
import { Card } from "@/ui";
import { Link2, Copy, MessageCircle, Download, Check } from "lucide-react";

export default function WhatsAppShareCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [phoneEdit, setPhoneEdit] = useState("");
  const [savedPhone, setSavedPhone] = useState(false);
  const [copied, setCopied] = useState(false);
  const [text, setText] = useState(
    "Olá! Quero saber mais sobre a Ligo 🚀",
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api._client.get(
        `/whatsapp-baileys/click-to-chat?text=${encodeURIComponent(text)}`,
      );
      setData(r.data);
      setPhoneEdit(r.data.phone || "");
    } catch (e) {
      setData(null);
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, [text]);

  useEffect(() => { load(); }, [load]);

  const copyLink = async () => {
    if (!data?.link) return;
    try {
      await navigator.clipboard.writeText(data.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      window.prompt("Copie o link:", data.link);
    }
  };

  const downloadQr = () => {
    const svg = document.querySelector(
      '[data-testid="wa-share-qr"] svg',
    );
    if (!svg) return;
    const xml = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([xml], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `wa-ligo-${(data?.phone || "qr")}.svg`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  };

  const savePhone = async () => {
    if (!phoneEdit) return;
    setError("");
    try {
      await api._client.put("/whatsapp-baileys/click-to-chat/phone", {
        phone: phoneEdit,
      });
      setSavedPhone(true);
      setTimeout(() => setSavedPhone(false), 1500);
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  };

  return (
    <Card data-testid="whatsapp-share-card"
          style={{ padding: 0, overflow: "hidden" }}>
      <div style={{
        padding: 16,
        background: "linear-gradient(135deg, #16a34a 0%, #15803d 100%)",
        color: "white", display: "flex", alignItems: "center", gap: 10,
      }}>
        <MessageCircle size={22} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 800 }}>
            Seu link de WhatsApp pra divulgar
          </div>
          <div style={{ fontSize: 11, opacity: 0.92, marginTop: 2 }}>
            Bio do Instagram, adesivo no carro, camiseta, QR no balcão…
          </div>
        </div>
      </div>

      <div style={{ padding: 16, display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 16, alignItems: "start" }}>
        <div style={{ display: "grid", gap: 10 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 800,
                              color: "#64748b", textTransform: "uppercase",
                              letterSpacing: 0.4 }}>
              Número de WhatsApp Business
            </label>
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <input data-testid="wa-share-phone-input"
                      value={phoneEdit}
                      onChange={(e) => setPhoneEdit(e.target.value)}
                      placeholder="5521999999999"
                      style={{
                        flex: 1, padding: "8px 10px", borderRadius: 6,
                        border: "1px solid #e2e8f0", fontSize: 13,
                        fontFamily: "JetBrains Mono, monospace",
                      }} />
              <button onClick={savePhone}
                      data-testid="wa-share-save-phone"
                      style={{
                        padding: "8px 14px", borderRadius: 6, border: 0,
                        background: savedPhone ? "#16a34a" : "#0f172a",
                        color: "white", fontSize: 12, fontWeight: 800,
                        cursor: "pointer", whiteSpace: "nowrap",
                      }}>
                {savedPhone ? "✓" : "Salvar"}
              </button>
            </div>
          </div>

          <div>
            <label style={{ fontSize: 11, fontWeight: 800,
                              color: "#64748b", textTransform: "uppercase",
                              letterSpacing: 0.4 }}>
              Mensagem pré-preenchida (opcional)
            </label>
            <textarea data-testid="wa-share-text"
                       value={text}
                       onChange={(e) => setText(e.target.value)}
                       rows={2}
                       style={{
                         width: "100%", marginTop: 6,
                         padding: "8px 10px", borderRadius: 6,
                         border: "1px solid #e2e8f0", fontSize: 13,
                         resize: "vertical", boxSizing: "border-box",
                       }} />
          </div>

          {error && (
            <div data-testid="wa-share-error" style={{
              padding: "8px 10px", borderRadius: 6,
              background: "#fef2f2", color: "#991b1b",
              fontSize: 12, fontWeight: 600,
            }}>{error}</div>
          )}

          {!loading && data?.link && (
            <>
              <div style={{ padding: "10px 12px", borderRadius: 8,
                              background: "#f0fdf4",
                              border: "1px solid #bbf7d0",
                              fontSize: 11, fontFamily: "JetBrains Mono, monospace",
                              wordBreak: "break-all",
                              color: "#166534" }}
                    data-testid="wa-share-link">
                {data.link}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={copyLink}
                        data-testid="wa-share-copy"
                        style={{
                          flex: 1, padding: "10px 14px", borderRadius: 8,
                          border: 0,
                          background: copied ? "#16a34a" : "#0f172a",
                          color: "white", fontSize: 12, fontWeight: 800,
                          cursor: "pointer",
                          display: "inline-flex", alignItems: "center",
                          justifyContent: "center", gap: 6,
                        }}>
                  {copied ? <><Check size={14} /> Copiado!</>
                    : <><Copy size={14} /> Copiar link</>}
                </button>
                <a href={data.link} target="_blank" rel="noreferrer"
                    data-testid="wa-share-open"
                    style={{
                      padding: "10px 14px", borderRadius: 8,
                      background: "#16a34a", color: "white",
                      fontSize: 12, fontWeight: 800, textDecoration: "none",
                      display: "inline-flex", alignItems: "center", gap: 6,
                    }}>
                  <Link2 size={14} /> Abrir
                </a>
              </div>
            </>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column",
                        alignItems: "center", gap: 8 }}>
          {loading ? (
            <div style={{ width: 200, height: 200,
                            background: "#f1f5f9", borderRadius: 12,
                            display: "grid", placeItems: "center",
                            color: "#94a3b8", fontSize: 12 }}>
              Carregando…
            </div>
          ) : data?.link ? (
            <>
              <div data-testid="wa-share-qr"
                    style={{
                      padding: 12, borderRadius: 12, background: "white",
                      border: "2px solid #16a34a",
                      boxShadow: "0 4px 12px rgba(22, 163, 74, .15)",
                    }}>
                <QRCodeSVG value={data.link}
                            size={180}
                            level="H"
                            includeMargin={false}
                            fgColor="#15803d" />
              </div>
              <button onClick={downloadQr}
                      data-testid="wa-share-download-qr"
                      style={{
                        padding: "6px 12px", borderRadius: 6,
                        border: "1px solid #16a34a", background: "white",
                        color: "#15803d", fontSize: 11, fontWeight: 800,
                        cursor: "pointer",
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}>
                <Download size={12} /> Baixar QR SVG
              </button>
              <div style={{ fontSize: 10, color: "#64748b",
                              textAlign: "center", maxWidth: 200,
                              lineHeight: 1.4 }}>
                Imprime e cola onde quiser. Quando o cliente apontar o
                celular, abre o WhatsApp direto com a Isabella.
              </div>
            </>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
