'use client';
import React from 'react';
import dynamic from 'next/dynamic';

/**
 * Loaded on the client only — see the note in `LiveIcon` for why. `ssr: false`
 * has to be declared from a client component, which is why this wrapper exists
 * rather than the dashboard page doing the dynamic import itself.
 *
 * The placeholder reserves the icon's space so the heading does not shift when
 * the animation arrives.
 */
const LiveIcon = dynamic(() => import('./LiveIcon'), {
  ssr: false,
  loading: () => <div className="w-8 h-8" aria-hidden />,
});

function LiveTitle() {
  return (
    <div className="flex items-center gap-3">
      <h1 className="font-bold text-xl tracking-wide">Live Updates</h1>
      <div className="mt-2">
        <LiveIcon />
      </div>
    </div>
  );
}

export default LiveTitle;
