const CACHE_VERSION = "shopping-list-flet-v1";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

const APP_SHELL = [
  "./",
  "./index.html",
  "./manifest.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(APP_SHELL)).catch(() => null)
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys
        .filter((key) => !key.startsWith(CACHE_VERSION))
        .map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

function isFirebaseRequest(url) {
  return (
    url.hostname.includes("firebaseio.com") ||
    url.hostname.includes("firebaseapp.com") ||
    url.hostname.includes("googleapis.com") ||
    url.hostname.includes("gstatic.com") && url.pathname.includes("firebase")
  );
}

function isCacheableSameOriginGet(request) {
  const url = new URL(request.url);

  if (request.method !== "GET") return false;
  if (url.origin !== self.location.origin) return false;
  if (isFirebaseRequest(url)) return false;

  return true;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);

  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone()).catch(() => null);
      }
      return response;
    })
    .catch(() => cached);

  return cached || networkPromise;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (!isCacheableSameOriginGet(request)) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          caches.open(RUNTIME_CACHE).then((cache) => cache.put("./index.html", response.clone()));
          return response;
        })
        .catch(async () => {
          return await caches.match("./index.html") || await caches.match("./");
        })
    );
    return;
  }

  event.respondWith(staleWhileRevalidate(request));
});
