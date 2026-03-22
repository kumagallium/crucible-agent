// Crucible Agent Service Worker
// PWA「ホームに追加」を有効にするための最小構成
// オフラインキャッシュは行わない（常にサーバーから最新を取得）

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
