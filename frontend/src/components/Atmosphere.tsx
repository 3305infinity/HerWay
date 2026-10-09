'use client';

/**
 * The signature layer.
 *
 * The page was text and hairline rules on flat ivory — correct, calm, and
 * completely anonymous. You could not recognise it from a screenshot, which is
 * the actual problem to solve.
 *
 * Two layers do it, applied once at the root so every page inherits the same
 * atmosphere instead of each screen inventing its own:
 *
 * 1. **A warm wash.** Two very soft radial pools — rose above, plum below —
 *    that give the background somewhere to be light and somewhere to be deep.
 *    Flat ivory has no depth; this does, without becoming a gradient banner.
 *
 * 2. **Grain.** A fine SVG noise field at low opacity. This is the thing people
 *    will recognise. It reads as printed paper rather than a web surface, which
 *    is what makes it sit with Playfair instead of fighting it — and it is far
 *    less common than the blur-blob look that every AI-built site now has.
 *
 * Why not blobs or mesh gradients: they are the current default, so they would
 * make this look like everything else — the exact complaint. Grain is cheap
 * (one inline SVG, no image request), works in both themes, and does not
 * compete with content for attention.
 *
 * Both layers are `pointer-events-none` and `aria-hidden`, sit behind
 * everything at `-z-10`, and are `fixed` so they do not scroll — the texture
 * stays still while content moves over it, like ink on a page.
 */

import React from 'react';

/**
 * Fractal noise, inlined as a data URI so it costs no network request.
 * `baseFrequency` controls grain size — 0.8 is fine enough to read as paper
 * rather than as visible static.
 */
const GRAIN_SVG = `<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>
<filter id='n'>
  <feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/>
  <feColorMatrix type='saturate' values='0'/>
</filter>
<rect width='160' height='160' filter='url(%23n)' opacity='0.42'/>
</svg>`;

const GRAIN_URL = `url("data:image/svg+xml,${GRAIN_SVG.replace(/\n/g, '').replace(/#/g, '%23')}")`;

export default function Atmosphere() {
  return (
    <>
      {/* Warm wash. Rose settles toward the top where the headline sits, plum
          pools lower, so a long page is not one uniform field of colour. */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(1100px_640px_at_18%_-8%,hsl(348_70%_62%/0.10),transparent_62%),radial-gradient(900px_600px_at_88%_8%,hsl(280_45%_58%/0.09),transparent_58%),radial-gradient(1000px_700px_at_50%_108%,hsl(280_40%_50%/0.07),transparent_60%)] dark:bg-[radial-gradient(1100px_640px_at_18%_-8%,hsl(348_70%_52%/0.16),transparent_62%),radial-gradient(900px_600px_at_88%_8%,hsl(280_55%_46%/0.14),transparent_58%),radial-gradient(1000px_700px_at_50%_108%,hsl(280_50%_40%/0.12),transparent_60%)]"
      />

      {/* Grain. `mix-blend-overlay` lets it sit in the surface rather than as a
          grey film on top; in dark mode `soft-light` keeps it from lifting the
          blacks. Opacity is deliberately low — it should be felt, not seen. */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 opacity-[0.16] mix-blend-overlay dark:opacity-[0.09] dark:mix-blend-soft-light"
        style={{ backgroundImage: GRAIN_URL, backgroundRepeat: 'repeat' }}
      />
    </>
  );
}
