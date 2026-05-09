/**
 * Fila offline para batidas de ponto.
 * 
 * Quando o GPS está indisponível ou o backend está fora do ar, a tentativa de
 * bater ponto é enfileirada localmente. Um worker tenta reenviar automaticamente
 * quando: (a) a geolocalização passa a estar disponível, OU (b) o navegador
 * volta a ficar online.
 * 
 * Storage: localStorage (key="ponto_offline_queue") como JSON array.
 * Capacidade: ~5MB → cabem 50+ selfies (cada ~80KB).
 */

const KEY = "ponto_offline_queue";

function read() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function write(items) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch (e) {
    console.warn("[offline-clock] localStorage cheio?", e);
  }
}

export function enqueue(item) {
  const items = read();
  items.push({
    id: `q-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    enqueued_at: new Date().toISOString(),
    ...item,
  });
  write(items);
  return items.length;
}

export function peekAll() {
  return read();
}

export function count() {
  return read().length;
}

export function remove(id) {
  write(read().filter((x) => x.id !== id));
}

export function clearAll() {
  write([]);
}

/** Worker que processa a fila. Recebe `sender(item) -> Promise<{ok}>` */
export async function flush(sender, { onProgress } = {}) {
  const items = read();
  if (!items.length) return { sent: 0, kept: 0 };
  let sent = 0;
  let kept = 0;
  for (const item of items) {
    try {
      await sender(item);
      remove(item.id);
      sent += 1;
      if (onProgress) onProgress({ sent, total: items.length });
    } catch (e) {
      console.warn("[offline-clock] reenvio falhou, mantendo na fila", item.id, e);
      kept += 1;
      // Para na primeira falha — provavelmente GPS/rede ainda offline
      break;
    }
  }
  return { sent, kept: kept + (items.length - sent - kept) };
}
