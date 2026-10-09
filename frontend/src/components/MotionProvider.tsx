'use client';

import { MotionConfig } from 'framer-motion';
import React from 'react';

import { EASE_CALM, DURATION } from '@/lib/motion';

/**
 * App-wide motion defaults.
 *
 * `reducedMotion="user"` is the important line: when the operating system asks
 * for reduced motion, Framer Motion drops transform and layout animations
 * across the entire app and keeps only opacity. That covers every component
 * without each one having to remember, and it pairs with the
 * `prefers-reduced-motion` block in globals.css which does the same for
 * CSS-driven animation.
 *
 * This is a client boundary wrapping the tree, so it must sit inside the body
 * rather than around `<html>`.
 */
export default function MotionProvider({ children }: { children: React.ReactNode }) {
  return (
    <MotionConfig
      reducedMotion="user"
      transition={{ duration: DURATION.base, ease: EASE_CALM }}
    >
      {children}
    </MotionConfig>
  );
}
