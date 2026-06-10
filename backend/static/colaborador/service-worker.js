// Ligo Colaborador — Service Worker (v3, 2026-06-10)
// Corrige: addAll all-or-nothing, falta de network-first pra HTML, falta de versionamento.
const CACHE_NAME = 'ligo-colaborador-v3-2026-06-10';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

// INSTALL — tolerante a falha (cada asset isoladamente; se algum 404 não derruba SW)
self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await Promise.allSettled(ASSETS.map(a => cache.add(a).catch(() => null)));
    self.skipWaiting();
  })());
});

// ACTIVATE — limpa caches antigos (versões anteriores) e assume clientes ativos
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

// FETCH — network-first pra HTML (sempre tenta atualizar); cache-first pro resto.
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  const isHTML = req.mode === 'navigate'
    || (req.headers.get('accept') || '').includes('text/html');

  if (isHTML) {
    // HTML: sempre tenta rede; cai pro cache só se offline.
    e.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE_NAME);
        cache.put(req, fresh.clone()).catch(() => {});
        return fresh;
      } catch (_) {
        const cached = await caches.match(req)
          || await caches.match('./index.html');
        return cached || new Response('Offline', { status: 503 });
      }
    })());
    return;
  }

  // Outros assets: cache-first; rede em background atualiza.
  e.respondWith((async () => {
    const cached = await caches.match(req);
    if (cached) return cached;
    try {
      const fresh = await fetch(req);
      const cache = await caches.open(CACHE_NAME);
      cache.put(req, fresh.clone()).catch(() => {});
      return fresh;
    } catch (_) {
      return new Response('', { status: 503 });
    }
  })());
});

// MESSAGE — permite skipWaiting forçado se o app pedir (ao detectar tela travada).
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});
