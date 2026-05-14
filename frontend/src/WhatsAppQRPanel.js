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
  const wasConnectedRef = React.useRef(false);
  const FAIL_THRESHOLD = 3;  // ~36s sem responder OK (12s × 3) → tela desconectada

  // Pede permissão de notificação na 1ª montagem (idempotente).
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      try { Notification.requestPermission(); } catch { /* ignore */ }
    }
  }, []);

  // Alerta sonoro + notificação browser quando perdeu conexão e precisa reescanear.
  const fireDisconnectAlert = () => {
    // Beep curto via Web Audio API (não requer arquivo MP3)
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) {
        const ctx = new Ctx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = "sine";
        osc.frequency.value = 880;          // primeiro tom
        gain.gain.value = 0.18;
        osc.start();
        // Segundo tom 150ms depois
        setTimeout(() => { osc.frequency.value = 660; }, 150);
        setTimeout(() => {
          gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.18);
          osc.stop(ctx.currentTime + 0.2);
          ctx.close().catch(() => {});
        }, 280);
      }
    } catch { /* sem áudio — segue silencioso */ }

    // Notificação do navegador (se permitida)
    try {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("WhatsApp desconectado", {
          body: "Escaneie o QR Code novamente para retomar o atendimento.",
          tag: "wa-disconnect",
          requireInteraction: false,
          silent: false,
        });
      }
    } catch { /* ignore */ }
  };

  const fetchState = useCallback(async () => {
    try {
      const r = await api.waBaileysQR();
      const st = r.status || "disconnected";
      setStatus(st);
      setErr(null);
      if (st === "connected") {
        setStickyConnected(true);
        wasConnectedRef.current = true;
        failsRef.current = 0;
      } else {
        failsRef.current += 1;
        if (failsRef.current >= FAIL_THRESHOLD) {
          // Só dispara alerta se já estava conectado antes (perda real, não 1º load)
          if (stickyConnected && wasConnectedRef.current) {
            fireDisconnectAlert();
          }
          setStickyConnected(false);
        }
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
      failsRef.current += 1;
      if (failsRef.current >= FAIL_THRESHOLD) {
        if (stickyConnected && wasConnectedRef.current) {
          fireDisconnectAlert();
        }
        setStickyConnected(false);
        setStatus("disconnected");
      }
    }
  }, [stickyConnected]);

  useEffect(() => {
    fetchState();
    // Quando desconectado/aguardando QR: poll RÁPIDO (1.5s) para mostrar o
    // chat assim que o WhatsApp conectar (~1s após escanear o QR).
    // Quando conectado e estável: 12s — economiza requests.
    const id = setInterval(fetchState, stickyConnected ? 12000 : 1500);
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
