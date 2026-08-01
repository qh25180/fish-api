/**
 * QHAPI Service Worker
 * 策略：仅缓存静态资源（/static/，离线可用）；页面与 API 一律走网络
 * （页面含 token 注入、API 需实时数据，不能缓存，否则导致旧 JS/卡顿）。
 */
const CACHE_NAME = 'qhapi-v2';
const STATIC_ASSETS = [
  '/static/css/reader.css',
  '/static/css/index.css',
  '/static/css/pages.css',
  '/static/css/search.css',
  '/static/js/qhapi.js',
  '/static/js/search.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// 安装：预缓存静态资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting())
  );
});

// 激活：清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// 请求拦截：仅处理 /static/ 资源，页面与 API 不拦截
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 仅同源 GET 且路径以 /static/ 开头
  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  if (!url.pathname.startsWith('/static/')) return;

  // 静态资源：缓存优先，回退网络
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((resp) => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return resp;
      });
    })
  );
});
