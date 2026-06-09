/* Service Worker — SmartProv PWA
 *
 * Estratégia híbrida para evitar o bug de "preciso dar Ctrl+Shift+R
 * em produção pra ver as mudanças":
 *
 *   - index.html / navegação           → NETWORK-FIRST
 *       Sempre tenta buscar a versão mais nova online; só cai no cache se
 *       o usuário estiver offline. Garante que um redeploy fica visível
 *       imediatamente no próximo carregamento (sem ctrl+shift+R).
 *
 *   - /static/ (CRA gera com hash)     → CACHE-FIRST
 *       Como o nome do arquivo muda quando o conteúdo muda
 *       (ex: main.abc123.js → main.def456.js), pode cachear longamente.
 *
 *   - /api/...                         → NUNCA cacheia
 *
 *   - tiles OSM/Mapbox (z/x/y png)     → STALE-WHILE-REVALIDATE
 *       Cache separado "smartprov-tiles" com TTL longo. Permite mapas
 *       offline pro técnico que cadastra CTO/CE/Cabo no campo sem
 *       internet. Tile fica disponível depois que foi visto 1x online.
 *
 * Ao publicar uma versão NOVA, basta bumpar o CACHE_NAME abaixo. O
 * `activate` deleta caches antigos automaticamente.
 */
const CACHE_NAME = "smartprov-v5-2026-06-09";
const TILE_CACHE = "smartprov-tiles-v1";
// Hosts considerados "tiles de mapa" (cache long-term)
const TILE_HOSTS = [
  "tile.openstreetmap.org",
  "a.tile.openstreetmap.org",
  "b.tile.openstreetmap.org",
  "c.tile.openstreetmap.org",
  "tiles.openfreemap.org",
  "tile.openfreemap.org",
  "tile.opentopomap.org",
  "a.basemaps.cartocdn.com",
  "b.basemaps.cartocdn.com",
  "c.basemaps.cartocdn.com",
  "d.basemaps.cartocdn.com",
  "server.arcgisonline.com",
];

self.addEventListener("install", (event) => {
  // Ativa imediatamente sem esperar abas antigas fecharem
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(["/manifest.json"]).catch(() => {})
    )
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Limpa caches antigos (mas preserva o de tiles, exceto se mudar versão)
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k !== CACHE_NAME && k !== TILE_CACHE)
              .map((k) => caches.delete(k))
      );
      // Toma controle das abas abertas imediatamente
      await self.clients.claim();
    })()
  );
});

// Permite que o frontend force update + reload via postMessage
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Nunca cacheia chamadas de API
  if (url.pathname.startsWith("/api/")) return;

  // Tiles de mapas → STALE-WHILE-REVALIDATE (cache long-term)
  if (TILE_HOSTS.includes(url.hostname)) {
    event.respondWith(
      caches.open(TILE_CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        const fetchPromise = fetch(req).then((res) => {
          if (res && res.status === 200) {
            cache.put(req, res.clone()).catch(() => {});
          }
          return res;
        }).catch(() => cached);
        // Retorna o cache imediatamente se houver, mas faz revalidate
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Navegação / index.html → NETWORK-FIRST
  // (qualquer request de documento HTML, ou path raiz, ou index.html direto)
  const isNavigation =
    req.mode === "navigate" ||
    (req.destination === "" && req.headers.get("accept")?.includes("text/html")) ||
    url.pathname === "/" ||
    url.pathname.endsWith("/index.html");

  if (isNavigation) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          // atualiza cache em background
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put("/index.html", copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => caches.match("/index.html") || caches.match(req))
    );
    return;
  }

  // Static assets com hash (/static/...) → CACHE-FIRST
  // Outros recursos same-origin (manifest, ícones, etc) → CACHE-FIRST também
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req)
        .then((res) => {
          if (res && res.status === 200 && url.origin === self.location.origin) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => undefined);
    })
  );
});
