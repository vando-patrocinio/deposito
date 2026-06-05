/*
osDraftStorage.js — Auto-save local de OS em execução (iter211ad)

Quando o técnico está executando uma OS na Lousa Mobile e o app crashar,
recarregar ou perder rede, NÃO podemos perder os dados que ele já preencheu
(sinal, fotos, observações, drop usado, etc.).

Estratégia:
  • Cada OS aberta tem uma chave: `osdraft:<ticket_id>:<collaborator_id>`
  • A cada mudança no formulário, salvamos no localStorage (debounce 600ms).
  • Ao abrir uma OS, restauramos o que estiver salvo PRA AQUELE TICKET.
  • Ao finalizar com sucesso, limpamos o draft.
  • Photos são salvas como dataUrls — pode estourar quota do localStorage
    (~5MB por origem). Por isso comprimimos as fotos previamente e, se
    o save falhar, tentamos sem as fotos como degradação graceful.

API:
  saveDraft(ticketId, collabId, form)     → void (debounced internamente)
  loadDraft(ticketId, collabId)           → form | null
  clearDraft(ticketId, collabId)          → void
  listDrafts()                            → [{ ticketId, collabId, savedAt, size }]
  cleanupOldDrafts(maxAgeMs = 7d)         → void (chamar no mount)
*/

const PREFIX = "osdraft:";
const VERSION = 1;

function key(ticketId, collabId) {
  return `${PREFIX}${collabId || "anon"}:${ticketId}`;
}

let saveTimer = null;
let lastForm = null;

function _writeNow(k, payload) {
  const json = JSON.stringify(payload);
  try {
    localStorage.setItem(k, json);
    return true;
  } catch (e) {
    // Tenta novamente sem fotos pra caber na quota.
    try {
      const slim = {
        ...payload,
        form: { ...payload.form, fotos: [] },
        _droppedPhotos: true,
      };
      localStorage.setItem(k, JSON.stringify(slim));
      // eslint-disable-next-line no-console
      console.warn("[osDraftStorage] quota cheia — draft salvo SEM fotos.", e);
      return true;
    } catch (e2) {
      // eslint-disable-next-line no-console
      console.warn("[osDraftStorage] falha total no save:", e2);
      return false;
    }
  }
}

/**
 * Salva o form atual da OS no localStorage (debounce 600ms).
 */
export function saveDraft(ticketId, collabId, form) {
  if (!ticketId) return;
  lastForm = form;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    if (!lastForm) return;
    const payload = {
      v: VERSION,
      ticketId,
      collabId,
      form: lastForm,
      savedAt: new Date().toISOString(),
    };
    _writeNow(key(ticketId, collabId), payload);
  }, 600);
}

/**
 * Carrega o draft salvo daquela OS+colaborador (ou null se nenhum).
 */
export function loadDraft(ticketId, collabId) {
  if (!ticketId) return null;
  try {
    const raw = localStorage.getItem(key(ticketId, collabId));
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (obj?.v !== VERSION) return null;
    return obj;  // { form, savedAt, _droppedPhotos? }
  } catch {
    return null;
  }
}

/**
 * Remove o draft (chamado após finalize com sucesso ou descarte explícito).
 */
export function clearDraft(ticketId, collabId) {
  if (!ticketId) return;
  try { localStorage.removeItem(key(ticketId, collabId)); } catch { /* */ }
}

/**
 * Lista todos os drafts salvos pra debug ou painel de recuperação.
 */
export function listDrafts() {
  const out = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k || !k.startsWith(PREFIX)) continue;
      const raw = localStorage.getItem(k);
      if (!raw) continue;
      try {
        const obj = JSON.parse(raw);
        out.push({
          ticketId: obj.ticketId,
          collabId: obj.collabId,
          savedAt: obj.savedAt,
          size: raw.length,
          droppedPhotos: !!obj._droppedPhotos,
        });
      } catch { /* skip */ }
    }
  } catch { /* */ }
  return out;
}

/**
 * Apaga drafts mais antigos que `maxAgeMs` (default 7 dias).
 */
export function cleanupOldDrafts(maxAgeMs = 7 * 24 * 3600 * 1000) {
  const cutoff = Date.now() - maxAgeMs;
  try {
    const toDelete = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k || !k.startsWith(PREFIX)) continue;
      const raw = localStorage.getItem(k);
      if (!raw) continue;
      try {
        const obj = JSON.parse(raw);
        if (new Date(obj.savedAt).getTime() < cutoff) toDelete.push(k);
      } catch { toDelete.push(k); }
    }
    toDelete.forEach((k) => { try { localStorage.removeItem(k); } catch { /* */ } });
    return toDelete.length;
  } catch { return 0; }
}
