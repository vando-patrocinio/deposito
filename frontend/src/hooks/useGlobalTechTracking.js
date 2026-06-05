/* useGlobalTechTracking — Hook que faz watchPosition + envio de pings
   independente da tela aberta. Roda no CollaboratorApp inteiro.

   Quando o técnico está com o app aberto (qualquer aba: Lousa, OS,
   Cadastro Rede, Mapa, etc.), o GPS é amostrado e pings são enviados
   ao backend (`/tech-tracking/public/ping/{collab_id}`).

   iter162 — 28/05/2026
*/
import { useEffect, useRef } from "react";
import { api } from "@/api";

export default function useGlobalTechTracking(collabId) {
  const watchRef = useRef(null);
  const lastPingRef = useRef({ ts: 0, pos: null });

  useEffect(() => {
    if (!collabId) return undefined;
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      return undefined;
    }
    watchRef.current = navigator.geolocation.watchPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const acc = pos.coords.accuracy || null;
        // iter226 — em carro em movimento (especialmente sob 5G/WiFi
        // indoor) accuracy oscila muito e passava de 100m com frequência,
        // fazendo o tracker NUNCA enviar ping. Subimos pra 400m e
        // marcamos o ping como "low_accuracy" — assim o backend ainda
        // grava e o LiveMap mostra (mesmo que com indicador de baixa
        // precisão). Acima de 400m provavelmente é geoloc por torre
        // celular e ai sim descartamos.
        if (acc && acc > 400) return;
        const now = Date.now();
        let dist = 0;
        if (lastPingRef.current.pos) {
          const R = 6371000;
          const [lLat, lLng] = lastPingRef.current.pos;
          const φ1 = lLat * Math.PI / 180;
          const φ2 = lat * Math.PI / 180;
          const dφ = (lat - lLat) * Math.PI / 180;
          const dλ = (lng - lLng) * Math.PI / 180;
          const a = Math.sin(dφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(dλ/2)**2;
          dist = 2 * R * Math.asin(Math.sqrt(a));
        }
        const sinceLast = now - lastPingRef.current.ts;
        // Hold heartbeat: send at least every 60s mesmo parado
        if (lastPingRef.current.pos
            && dist < 8 && sinceLast < 60000) return;
        lastPingRef.current = { ts: now, pos: [lat, lng] };
        try {
          await api._client.post(
            `/tech-tracking/public/ping/${collabId}`,
            { lat, lng, accuracy: acc,
              speed: pos.coords.speed, heading: pos.coords.heading });
        } catch { /* offline-tolerant */ }
      },
      () => {},
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
    );
    return () => {
      if (watchRef.current != null) {
        try { navigator.geolocation.clearWatch(watchRef.current); }
        catch { /* */ }
      }
    };
  }, [collabId]);
}
