import React, { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/api";
import WhatsAppChatLayout from "@/WhatsAppChatLayout";
import WhatsAppInstancePanel from "@/WhatsAppInstancePanel";

/* =============================================================
   Aba WhatsApp — chat principal com fallback automático para o
   painel de Instância (QR Code) quando desconectado.
   Nada de mensagens "vá em Atendimento → Instância" — a UI
   apresenta o QR code direto pra reconexão imediata.
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

  // Estado "verificando" inicial — só enquanto não temos resposta
  if (status === "connecting" && !err) {
    return (
      <div data-testid="wa-checking-state" style={{
        padding: 36, textAlign: "center",
        border: "1px solid var(--border-default)",
        borderRadius: 14, background: "var(--bg-surface)",
      }}>
        <Loader2 size={26} style={{ animation: "spin 1.2s linear infinite", color: "var(--text-muted)" }} />
        <p style={{ marginTop: 12, fontSize: 13, color: "var(--text-secondary)" }}>
          Verificando conexão WhatsApp…
        </p>
      </div>
    );
  }

  // Desconectado / erro → exibe o painel de Instância (QR Code) direto
  return <WhatsAppInstancePanel />;
}
