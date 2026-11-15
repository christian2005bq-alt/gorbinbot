// v3 (live poll + FOMO profile 2026-11-14). Bumping this file makes phones install the new worker and drop old caches.
const VERSION = 'desk-v6-2026-11-14-picks';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  const keys = await caches.keys(); await Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)));
  await self.clients.claim();
})()));
self.addEventListener('push', e => {
  let d = {}; try { d = e.data.json(); } catch (_) { d = {title: 'Grok Bot · now', body: e.data ? e.data.text() : ''}; }
  e.waitUntil(self.registration.showNotification(d.title || 'Grok Bot · now', {body: d.body, icon: 'icons/icon-192.png', data: {url: d.url}}));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data && e.notification.data.url;  // exact links.coin_url string from the server
  if (url) e.waitUntil(clients.openWindow(url));
});
