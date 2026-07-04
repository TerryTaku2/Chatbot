/* ============================================================
   T-Tech Connect — Service Worker
   ============================================================ */

const CACHE = 'ttech-v1';

const PRECACHE = [
  '/accommodation/offline',
  '/accommodation/static/css/landlord.css',
  '/accommodation/static/css/dashboard.css',
  '/accommodation/static/css/login.css',
  '/accommodation/static/css/browse.css',
  '/accommodation/static/css/for_tenants.css',
  '/accommodation/static/js/login.js',
  '/accommodation/static/images/logo.png',
  '/accommodation/static/images/icon-192.png',
  '/accommodation/static/images/icon-512.png',
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

  /* Skip: non-GET, API calls, Socket.IO */
  if (
    request.method !== 'GET' ||
    url.pathname.startsWith('/accommodation/api/') ||
    url.pathname.startsWith('/socket.io/') ||
    url.pathname.startsWith('/accommodation/auth/')
  ) return;

  /* Static assets — cache first, then network */
  if (url.pathname.startsWith('/accommodation/static/')) {
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

  /* HTML pages — network first, fall back to cache, then offline */
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
