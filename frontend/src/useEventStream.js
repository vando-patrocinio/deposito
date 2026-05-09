/**
 * Hook SSE — conecta ao /api/events/stream e dispara callbacks por evento.
 * Reconecta automaticamente em desconexões com backoff exponencial.
 */
import { useEffect, useRef, useState } from "react";

export default function useEventStream({ onNotification, onConnect, onDisconnect, onEvent } = {}) {
  const [connected, setConnected] = useState(false);
  const [lastEventAt, setLastEventAt] = useState(null);
  const esRef = useRef(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    function connect() {
      if (cancelled) return;
      const token = (typeof window !== "undefined") && (localStorage.getItem("ponto_token") || "");
      if (!token) {
        // sem token → sem conexão (usuário não logado)
        return;
      }
      const base = process.env.REACT_APP_BACKEND_URL || "";
      const url = `${base}/api/events/stream?token=${encodeURIComponent(token)}`;
      try {
        const es = new EventSource(url);
        esRef.current = es;

        es.addEventListener("connected", () => {
          retryRef.current = 0;
          setConnected(true);
          if (onConnect) onConnect();
        });
        es.addEventListener("notification", (ev) => {
          setLastEventAt(Date.now());
          try {
            const data = JSON.parse(ev.data);
            if (onNotification) onNotification(data);
          } catch (e) {
            console.warn("[sse] parse fail", e);
          }
        });
        // Eventos genéricos do backend (ex.: atlaz_bubbles_synced, atlaz_technicians_synced)
        ["atlaz_bubbles_synced", "atlaz_technicians_synced"].forEach((evName) => {
          es.addEventListener(evName, (ev) => {
            setLastEventAt(Date.now());
            try {
              const data = JSON.parse(ev.data);
              if (onEvent) onEvent(evName, data);
            } catch (e) {
              console.warn("[sse] parse fail", evName, e);
            }
          });
        });
        es.addEventListener("ping", () => {
          // heartbeat — só atualiza timestamp
          setLastEventAt(Date.now());
        });
        es.onerror = () => {
          setConnected(false);
          if (onDisconnect) onDisconnect();
          es.close();
          // reconnect com backoff exponencial até 30s
          if (cancelled) return;
          retryRef.current = Math.min(retryRef.current + 1, 5);
          const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30000);
          timer = setTimeout(connect, delay);
        };
      } catch (e) {
        console.error("[sse] connect failed", e);
      }
    }

    connect();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (esRef.current) {
        try { esRef.current.close(); } catch {}
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { connected, lastEventAt };
}
