/* utils/geo.js — Hybrid geolocation (GPS + rede)
 *
 * Browser nativo já mistura GPS + Wi-Fi + cell tower, mas o flag
 * `enableHighAccuracy` muda o trade-off:
 *   - true  → prioriza GPS (preciso ~5-10m, lento, gasta bateria)
 *   - false → prioriza rede (impreciso 50-500m, instantâneo, leve)
 *
 * Esta utility faz HÍBRIDO REAL:
 *   1. Lança DUAS requisições em paralelo (network rápido + GPS lento)
 *   2. Retorna o PRIMEIRO fix com accuracy < cutoff (default 25m)
 *   3. Se nenhum chegar < cutoff até o timeout, devolve o melhor disponível
 *   4. Continua refinando em background até accuracy < 10m ou stop()
 *
 * Uso típico:
 *   const fix = await getBestPosition({ cutoffM: 25, timeoutMs: 8000 });
 *   // → { lat, lng, accuracy, source: "gps" | "network", elapsed_ms }
 *
 *   const stop = watchBestPosition((fix) => { ... }, { cutoffM: 10 });
 *   // chama callback a cada melhoria; stop() para o watcher.
 */

const isSupported = () =>
  typeof navigator !== "undefined" && !!navigator.geolocation;

function _normalize(pos, source) {
  return {
    lat: pos.coords.latitude,
    lng: pos.coords.longitude,
    accuracy: pos.coords.accuracy,
    altitude: pos.coords.altitude || null,
    heading: pos.coords.heading || null,
    speed: pos.coords.speed || null,
    source,                              // "gps" | "network"
    timestamp: pos.timestamp,
  };
}

/**
 * Pega a MELHOR posição em até `timeoutMs` ms.
 * Dispara GPS (alta) + rede (baixa) em paralelo. Resolve assim que
 * obtém um fix com accuracy <= cutoffM, ou no timeout devolve o melhor
 * disponível.
 */
export function getBestPosition({
  cutoffM = 25,
  timeoutMs = 10000,
  maxAgeMs = 5000,
} = {}) {
  return new Promise((resolve, reject) => {
    if (!isSupported()) {
      reject(new Error("Geolocalização não suportada"));
      return;
    }
    let best = null;
    let resolved = false;
    const t0 = Date.now();

    const finish = (val, err) => {
      if (resolved) return;
      resolved = true;
      if (val) {
        val.elapsed_ms = Date.now() - t0;
        resolve(val);
      } else if (err) {
        reject(err);
      } else {
        reject(new Error("Sem fix"));
      }
    };

    const consider = (val) => {
      if (!val) return;
      if (!best || val.accuracy < best.accuracy) best = val;
      if (val.accuracy <= cutoffM) finish(val);
    };

    // GPS — alta precisão, lento
    navigator.geolocation.getCurrentPosition(
      (pos) => consider(_normalize(pos, "gps")),
      () => { /* falha silenciosa — rede pode resolver */ },
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: maxAgeMs },
    );

    // Rede — rápido, impreciso. Usado pra "primeira luz" e fallback.
    navigator.geolocation.getCurrentPosition(
      (pos) => consider(_normalize(pos, "network")),
      () => { /* falha silenciosa */ },
      { enableHighAccuracy: false, timeout: Math.min(timeoutMs, 4000),
        maximumAge: 60000 },
    );

    // Timeout: devolve o melhor que tiver, ou erro
    setTimeout(() => {
      if (best) finish(best);
      else finish(null, new Error(
        `Sem GPS nem rede em ${timeoutMs}ms`,
      ));
    }, timeoutMs);
  });
}

/**
 * Observa posição continuamente e chama `onUpdate` a cada MELHORIA
 * de accuracy (ou se posição mudou > 5m).
 *
 * Retorna função `stop()`.
 *
 * Combinação:
 *   - watchPosition com high accuracy (GPS contínuo)
 *   - Single network fix imediato pra "primeira luz" se GPS demorar.
 */
export function watchBestPosition(onUpdate, {
  cutoffM = 10,
  movementThresholdM = 5,
  onError = null,
} = {}) {
  if (!isSupported()) {
    onError?.(new Error("Geolocalização não suportada"));
    return () => {};
  }
  let last = null;
  let watchId = null;

  const fire = (val) => {
    if (!last) {
      last = val;
      onUpdate(val);
      return;
    }
    // Reportamos melhoria SE accuracy melhorou OU mexeu > threshold
    const accBetter = val.accuracy < last.accuracy * 0.7;
    const movedM = _haversine(last, val);
    if (accBetter || movedM >= movementThresholdM) {
      last = val;
      onUpdate(val);
    }
  };

  // 1. Single network fix (primeira luz <2s)
  navigator.geolocation.getCurrentPosition(
    (pos) => fire(_normalize(pos, "network")),
    () => { /* silent */ },
    { enableHighAccuracy: false, timeout: 4000, maximumAge: 60000 },
  );

  // 2. Continuous high-accuracy GPS watch
  try {
    watchId = navigator.geolocation.watchPosition(
      (pos) => fire(_normalize(pos, "gps")),
      (err) => { onError?.(err); },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 2000 },
    );
  } catch (e) {
    onError?.(e);
  }

  return () => {
    if (watchId != null) {
      try { navigator.geolocation.clearWatch(watchId); }
      catch { /* ignore */ }
    }
  };
}

// Distância Haversine em metros
function _haversine(a, b) {
  if (!a || !b) return Infinity;
  const R = 6371000;
  const toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const s = Math.sin(dLat / 2) ** 2
              + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * R * Math.asin(Math.sqrt(s));
}

export default { getBestPosition, watchBestPosition };
