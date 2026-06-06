/* LousaTvLinkModal — exibe o link público da Lousa para SmartTV.
 * Gestor pode copiar o link ou rotacionar o token (revoga o anterior).
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button } from "@/ui";

export default function LousaTvLinkModal({ onClose }) {
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);

  async function fetchToken() {
    setLoading(true);
    try {
      const r = await api._client.get("/lousa/tv-link");
      setToken(r.data.token);
      setErr("");
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }

  async function rotate() {
    if (!await window.confirm(
      "Rotacionar o token vai INVALIDAR o link atual. "
        + "Todas as SmartTVs conectadas ficarão sem dados até receberem o novo link. Continuar?",
    )) return;
    setLoading(true);
    try {
      const r = await api._client.post("/lousa/tv-link/rotate");
      setToken(r.data.token);
      setErr("");
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }

  useEffect(() => { fetchToken(); }, []);

  const url = token
    ? `${window.location.origin}/?portal=lousa-tv&t=${token}`
    : "";

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch { /* ignore */ }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
        display: "grid", placeItems: "center", zIndex: 200, padding: 20,
      }}>
      <div
        onClick={(e) => e.stopPropagation()}
        data-testid="lousa-tv-link-modal"
        style={{
          background: "white", borderRadius: 16, padding: 24,
          maxWidth: 540, width: "100%",
          boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
        }}>
        <h2 style={{ margin: 0, fontSize: 22 }}>Lousa TV — Link público</h2>
        <p style={{ marginTop: 8, color: "#475569", fontSize: 13, lineHeight: 1.5 }}>
          Abra este link em uma SmartTV (modo navegador) para exibir a Lousa em
          tempo real, somente leitura. O link é seguro: tem token único e
          atualiza a grade a cada 20 segundos.
        </p>

        {loading ? (
          <div style={{ padding: 20, textAlign: "center", color: "#64748b" }}>
            Carregando token…
          </div>
        ) : err ? (
          <div style={{
            background: "#fee2e2", border: "1px solid #fca5a5",
            color: "#991b1b", padding: 12, borderRadius: 10, fontSize: 13,
          }}>️ {err}</div>
        ) : (
          <>
            <label style={{ fontSize: 11, color: "#64748b",
                              fontWeight: 700, textTransform: "uppercase",
                              letterSpacing: 0.5, marginTop: 12, display: "block" }}>
              URL da SmartTV
            </label>
            <div style={{
              background: "#0f172a", color: "#e2e8f0",
              padding: 12, borderRadius: 10, fontSize: 12,
              wordBreak: "break-all", fontFamily: "monospace",
              marginTop: 6,
            }} data-testid="lousa-tv-link-url">
              {url}
            </div>

            <div style={{
              marginTop: 10, padding: 10, fontSize: 11,
              background: "#fef3c7", border: "1px solid #fcd34d",
              borderRadius: 8, color: "#78350f",
            }}>
              <strong>Segurança:</strong> não compartilhe esse link
              publicamente — qualquer pessoa com o token vê todas as bolhas
              em tempo real (somente leitura). Use o botão “Rotacionar” se
              suspeitar que o link vazou.
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              <Button
                data-testid="lousa-tv-copy-btn"
                onClick={copyUrl} style={{ flex: 1 }}>
                {copied ? "✓ Copiado!" : "Copiar URL"}
              </Button>
              <Button
                data-testid="lousa-tv-open-btn"
                variant="soft"
                onClick={() => window.open(url, "_blank")}
                style={{ flex: 1 }}>
                ↗ Abrir agora
              </Button>
              <Button
                data-testid="lousa-tv-rotate-btn"
                variant="soft"
                onClick={rotate}
                style={{ flex: 1, color: "#dc2626" }}>
                ⟲ Rotacionar
              </Button>
            </div>
          </>
        )}

        <Button
          variant="soft" onClick={onClose}
          data-testid="lousa-tv-close-btn"
          style={{ marginTop: 14, width: "100%" }}>
          Fechar
        </Button>
      </div>
    </div>
  );
}
