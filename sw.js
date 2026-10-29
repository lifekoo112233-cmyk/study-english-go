// 앱 화면(index.html 등)을 저장해 두었다가, 인터넷이 없을 때 대신 보여주는 서비스 워커.
// 항상 인터넷에서 최신 파일을 먼저 받아오므로, 앱을 수정해서 올리면 바로 반영돼요.
const CACHE = 'dne-shell-v2';
const SHELL = ['./', 'index.html', 'manifest.json', 'icon-192.png', 'icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => Promise.allSettled(SHELL.map(u => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;                 // GitHub·번역 API 등 외부 요청은 그대로 통과
  if (url.pathname.includes('/data/')) return;                // 학습·단어 데이터는 앱이 직접 관리

  e.respondWith(
    fetch(req, { cache: 'no-cache' })
      .then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
        return res;
      })
      .catch(() => caches.match(req).then(r => r || caches.match('index.html')))
  );
});
