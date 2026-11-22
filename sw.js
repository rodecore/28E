// Retira el service worker de 28E y las páginas guardadas en su caché.
self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames.filter((name) => name.startsWith('28e-')).map((name) => caches.delete(name)));
    await self.clients.claim();
    await self.registration.unregister();
  })());
});
