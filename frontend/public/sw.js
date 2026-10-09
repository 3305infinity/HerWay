/*
 * HerWay service worker — offline emergency numbers.
 *
 * Why this exists
 * ---------------
 * A woman with no data left, no credit, or no signal still needs 112 and 181.
 * Those numbers do not change and do not need a network to be useful — but a
 * web app normally shows a browser error page instead of them. This worker
 * makes the helplines the offline fallback, so losing connectivity degrades to
 * the most important screen rather than to nothing.
 *
 * What it deliberately does NOT cache
 * -----------------------------------
 * This is a domestic-violence product. A cache is a file on disk that someone
 * else may look through. So:
 *
 *   - **No API responses.** Anything under /api/ is never cached, in either
 *     direction. Case contents, chat replies, safety plans and search results
 *     never touch disk through this worker.
 *   - **No HTML pages.** Visiting /cases or /safety-center leaves nothing
 *     behind here. Caching them would mean a cached copy of her safety plan
 *     survives on the device after she closes the tab.
 *   - **Only static build assets and the offline card.** Those contain no user
 *     content.
 *
 * The cost is that the app does not work offline beyond the helplines. That is
 * the right trade: the alternative is a privacy hole, and an offline case
 * workspace is not what someone needs when they have no signal.
 */

const CACHE = 'herway-offline-v1';
const OFFLINE_URL = '/offline.html';

// Only the offline card is precached. Everything else is fetched live.
const PRECACHE = [OFFLINE_URL];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      // Take over immediately so the first offline visit is already covered.
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Never touch the API. Not read, not written, not cached.
  if (url.pathname.startsWith('/api/')) return;

  // Cross-origin requests are left entirely alone.
  if (url.origin !== self.location.origin) return;

  // Navigations: always try the network, fall back to the offline card.
  // Never serve a cached page — see the note above about disk residue.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL)),
    );
    return;
  }

  // Static build assets: cache-first, since they are content-hashed and
  // contain nothing personal.
  if (url.pathname.startsWith('/_next/static/') || url.pathname.startsWith('/images/')) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});

/**
 * Lets the page clear everything this worker stored — wired to a control on
 * /privacy, so "remove what HerWay kept on this device" is something a user
 * can actually do rather than a claim.
 */
self.addEventListener('message', (event) => {
  if (event.data === 'herway:purge') {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k)))));
  }
});
