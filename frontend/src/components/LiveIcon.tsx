'use client';
import React from 'react';
import { Player } from '@lordicon/react';

import ICON from '../assets/liveicon.json';

/**
 * The animated "live" glyph, kept in its own module so that `LiveTitle` can
 * load it with `next/dynamic({ ssr: false })`.
 *
 * `@lordicon/react` depends on `lottie-web`, which reaches for `document` while
 * its module body is evaluated. Importing it anywhere in a server-rendered tree
 * threw `ReferenceError: document is not defined` on every request. Next
 * recovered by falling back to client rendering, so the page still returned
 * 200 and the only trace was a stack trace in the server log — but the server
 * render was thrown away each time.
 *
 * The ref lives here rather than in `LiveTitle` because `next/dynamic` does not
 * forward refs to the wrapped component.
 */
function LiveIcon() {
  const playerRef = React.useRef<Player>(null);

  React.useEffect(() => {
    playerRef.current?.playFromBeginning();
  }, []);

  return (
    <Player
      ref={playerRef}
      icon={ICON}
      onComplete={() => playerRef.current?.playFromBeginning()}
    />
  );
}

export default LiveIcon;
