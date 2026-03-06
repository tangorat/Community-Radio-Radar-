const CACHE = 'radio-radar-v3';
const STATIC = [
  '/',
  '/manifest.json',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Don't cache API calls or audio streams
  const url = e.request.url;
  if (url.includes('/amrap') || url.includes('/charts') || url.includes('/scrape') || url.includes('stream')) {
    return;
  }

  e.respondWith(
    // Always try network first for the main HTML, fall back to cache
    fetch(e.request).then(res => {
      if (e.request.url.endsWith('/') || e.request.url.includes('community-radio-radar')) {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return res;
    }).catch(() => caches.match(e.request).then(cached => cached || caches.match('/')))
  );
});
