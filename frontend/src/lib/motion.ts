/**
 * Shared motion vocabulary.
 *
 * The governing constraint
 * ------------------------
 * Someone opening HerWay may be frightened, in a hurry, or holding a phone
 * they do not want anyone to see over their shoulder. That rules out most of
 * what "nice animation" usually means:
 *
 * - **Nothing bouncy.** Springy overshoot reads as playful. A woman checking
 *   whether a shelter is open does not need playful.
 * - **Nothing slow.** Every duration here is under 400ms. Motion that makes
 *   someone wait is motion that is in the way.
 * - **Nothing that delays access.** Emergency numbers, Quick Exit and the
 *   safety banner render immediately and never animate in. They are excluded
 *   from every variant in this file by convention — see `INSTANT`.
 * - **Nothing that moves far.** Travel is 8–16px. Large sweeps draw the eye of
 *   anyone else in the room.
 *
 * What remains is motion that explains structure: things that belong together
 * arrive together, things that replace each other cross-fade, and a list that
 * loads settles in order so the eye can follow it.
 *
 * Reduced motion
 * --------------
 * Framer Motion's `MotionConfig reducedMotion="user"` is set once in the root
 * layout, so every `animate` here automatically collapses to an opacity change
 * when the OS asks for reduced motion. Do not hand-roll that per component.
 */

import type { Transition, Variants } from 'framer-motion';

/**
 * Standard easing — a gentle decelerate. Matches the CSS `--ease-calm` token
 * in globals.css so JS- and CSS-driven motion feel like one system.
 */
export const EASE_CALM = [0.22, 0.61, 0.36, 1] as const;

/** Slightly sharper, for things leaving rather than arriving. */
export const EASE_EXIT = [0.4, 0, 1, 1] as const;

export const DURATION = {
  /** Hovers, focus rings, colour changes. */
  fast: 0.16,
  /** The default for content arriving. */
  base: 0.28,
  /** Page-level transitions and larger panels. */
  slow: 0.38,
} as const;

export const transition: Transition = {
  duration: DURATION.base,
  ease: EASE_CALM,
};

/**
 * For anything that must be usable the instant it exists: emergency numbers,
 * Quick Exit, helpline banners, error states that matter.
 *
 * Spread this instead of a variant. It is deliberately not "a fast animation" —
 * it is no animation at all.
 */
export const INSTANT = {
  initial: false,
  animate: { opacity: 1 },
  transition: { duration: 0 },
} as const;

/* ---------------------------------------------------------------------- */
/* Variants                                                               */
/* ---------------------------------------------------------------------- */

/** Content arriving: a short rise with the fade. */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition },
  exit: { opacity: 0, y: -6, transition: { duration: DURATION.fast, ease: EASE_EXIT } },
};

/** For panels that slide in from the side — drawers, detail views. */
export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 16 },
  visible: { opacity: 1, x: 0, transition: { duration: DURATION.slow, ease: EASE_CALM } },
  exit: { opacity: 0, x: 16, transition: { duration: DURATION.fast, ease: EASE_EXIT } },
};

export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -16 },
  visible: { opacity: 1, x: 0, transition: { duration: DURATION.slow, ease: EASE_CALM } },
  exit: { opacity: 0, x: -16, transition: { duration: DURATION.fast, ease: EASE_EXIT } },
};

/** A plain cross-fade, for content replacing other content in place. */
export const fade: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition },
  exit: { opacity: 0, transition: { duration: DURATION.fast } },
};

/**
 * Parent for a list. Children using `fadeUp` settle one after another.
 *
 * 55ms is deliberately short. A long stagger looks considered on a marketing
 * page and feels broken on a page someone is scanning for a phone number.
 */
export const stagger: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.055, delayChildren: 0.04 },
  },
};

/** Same, with no entrance delay — for lists that appear after an action. */
export const staggerImmediate: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.045 } },
};

/* ---------------------------------------------------------------------- */
/* Interaction                                                            */
/* ---------------------------------------------------------------------- */

/**
 * Press feedback. Scale only, and barely — on a phone held low this should be
 * felt more than seen.
 */
export const press = {
  whileTap: { scale: 0.98 },
  transition: { duration: DURATION.fast, ease: EASE_CALM },
} as const;

/** A card lifting slightly on hover. Pointer devices only; see `usePointerFine`. */
export const lift = {
  whileHover: { y: -2 },
  transition: { duration: DURATION.fast, ease: EASE_CALM },
} as const;

/* ---------------------------------------------------------------------- */
/* Scroll reveal                                                          */
/* ---------------------------------------------------------------------- */

/**
 * Viewport config for `whileInView`.
 *
 * `once: true` matters here beyond performance: content that re-animates every
 * time it scrolls back into view is distracting, and on a safety page it reads
 * as the page being unstable.
 *
 * The negative bottom margin starts the reveal slightly before the element is
 * fully on screen, so it has settled by the time it is actually being read.
 */
export const viewportOnce = { once: true, margin: '0px 0px -80px 0px' } as const;
