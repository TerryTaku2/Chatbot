/* ============================================================
   T-Tech Connect — Unified Service Worker
   Covers the whole app (shop, seller portal, accommodation) so
   there is exactly one installable PWA for the whole site.
   ============================================================ */

const CACHE = 'ttech-unified-v1';

const PRECACHE = [
  '/',
  '/shop',
  '/accommodation/offline',
  '/accommodation/static/images/logo.png',
  '/accommodation/static/images/icon-192.png',
];

/* ── Install: pre-cache shell assets ── */
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

/* ── Activate: purge old caches ── */
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

/* ── Fetch strategy ── */
self.addEventListener('fetch', e => {
  const { request } = e;
  const url = new URL(request.url);

  /* Skip: non-GET, API calls, webhook, Socket.IO */
  if (
    request.method !== 'GET' ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/accommodation/api/') ||
    url.pathname.startsWith('/webhook') ||
    url.pathname.startsWith('/webhooks/') ||
    url.pathname.startsWith('/socket.io/') ||
    url.pathname.startsWith('/admin') ||
    url.pathname.startsWith('/accommodation/admin') ||
    url.pathname.startsWith('/seller/')
  ) return;

  /* Static assets — cache first, then network */
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/accommodation/static/') || url.pathname.startsWith('/uploads/')) {
    e.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(res => {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(request, clone));
          return res;
        });
      })
    );
    return;
  }

  /* HTML pages — network first, fall back to cache, then offline page */
  e.respondWith(
    fetch(request)
      .then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(request, clone));
        }
        return res;
      })
      .catch(() =>
        caches.match(request)
          .then(cached => cached || caches.match('/accommodation/offline'))
      )
  );
});
