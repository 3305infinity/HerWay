'use client';

import { useEffect } from 'react';

/**
 * Registers the offline-helplines service worker.
 *
 * Registration is deferred until after load so it never competes with the
 * first paint, and it is skipped entirely in development — a service worker
 * caching `_next/static` across hot reloads is a reliable way to serve stale
 * chunks and produce `ChunkLoadError`, which this project has lost enough time
 * to already.
 *
 * See `public/sw.js` for what is and is not cached, and why.
 */
export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return;
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;

    const register = () => {
      navigator.serviceWorker.register('/sw.js').catch((error) => {
        // Non-fatal: the app works, it just has no offline fallback.
        console.warn('Offline helplines unavailable:', error);
      });
    };

    if (document.readyState === 'complete') register();
    else window.addEventListener('load', register, { once: true });
  }, []);

  return null;
}
