import React, { useCallback, useEffect, useState } from "react";
import { Loader2, AlertTriangle, Smartphone } from "lucide-react";
import { api } from "@/api";
import WhatsAppChatLayout from "@/WhatsAppChatLayout";

/* =============================================================
   Aba WhatsApp — agora mostra APENAS o chat (FocusChat).
   A configuração (QR code, número conectado, auto-reply) foi
   movida para a sub-aba "Instância".

   Quando não há conexão: mostra mensagem orientando ir pra Instância.
============================================================= */

export default function WhatsAppQRPanel() {
  const [status, setStatus] = useState("connecting");
  const [err, setErr] = useState(null);
  // "sticky connected": uma vez conectado, exige N falhas SEGUIDAS antes
  // de mostrar a tela de desconectado. Evita flicker em picos de latência.
  const [stickyConnected, setStickyConnected] = useState(false);
  const failsRef = React.useRef(0);
  const FAIL_THRESHOLD = 3;  // ~36s sem responder OK (12s × 3) → tela desconectada

  const fetchState = useCallback(async () => {
    try {
      const r = await api.waBaileysQR();
      const st = r.status || "disconnected";
      setStatus(st);
      setErr(null);
      if (st === "connected") {
        setStickyConnected(true);
        failsRef.current = 0;
      } else {
        failsRef.current += 1;
        // Só desativa o sticky se acumular falhas consecutivas
        if (failsRef.current >= FAIL_THRESHOLD) {
          setStickyConnected(false);
        }
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
      failsRef.current += 1;
      if (failsRef.current >= FAIL_THRESHOLD) {
        setStickyConnected(false);
        setStatus("disconnected");
      }
    }
  }, []);

  useEffect(() => {
    fetchState();
    const id = setInterval(fetchState, stickyConnected ? 12000 : 4000);
    return () => clearInterval(id);
  }, [fetchState, stickyConnected]);

  // Enquanto sticky=true, sempre mostra o chat — mesmo que um poll falhe.
  if (stickyConnected || status === "connected") {
    return <WhatsAppChatLayout />;
  }

  return (
    <div data-testid="wa-disconnected-state" style={{
      padding: 36, textAlign: "center",
      border: "1px solid var(--border-default)",
      borderRadius: 14, background: "var(--bg-surface)",
    }}>
      <div style={{
        width: 56, height: 56, borderRadius: 14,
        background: "var(--bg-surface-2)",
        margin: "0 auto 14px",
        display: "grid", placeItems: "center",
        color: "var(--text-muted)",
      }}>
        {status === "connecting" ? (
          <Loader2 size={26} style={{ animation: "spin 1.2s linear infinite" }} />
        ) : (
          <Smartphone size={26} strokeWidth={1.75} />
        )}
      </div>
      <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0,
                     color: "var(--text-primary)",
                     letterSpacing: "-0.012em" }}>
        {status === "connecting"
          ? "Verificando conexão..."
          : "WhatsApp não conectado"}
      </h3>
      <p style={{ fontSize: 12, color: "var(--text-secondary)",
                    margin: "8px auto 0", maxWidth: 420, lineHeight: 1.5 }}>
        {status === "connecting"
          ? "Aguarde um instante enquanto checamos o status da instância."
          : "Para começar a usar o WhatsApp, vá em "}
        {status !== "connecting" && (
          <strong style={{ color: "var(--text-primary)" }}>
            Atendimento → Instância
          </strong>
        )}
        {status !== "connecting" && " e conecte um número via QR Code."}
      </p>
      {err && (
        <div style={{
          marginTop: 12, padding: 10, borderRadius: 8, maxWidth: 420,
          margin: "12px auto 0",
          background: "rgba(220,38,38,.08)",
          border: "1px solid rgba(220,38,38,.25)",
          fontSize: 11, color: "#dc2626",
          display: "flex", gap: 6, alignItems: "center", justifyContent: "center",
        }}>
          <AlertTriangle size={12} /> {err}
        </div>
      )}
    </div>
  );
}
