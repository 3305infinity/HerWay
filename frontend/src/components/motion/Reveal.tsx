'use client';

/**
 * Motion primitives.
 *
 * Three components cover almost every case in the app, so individual pages
 * never import framer-motion directly and the timing stays consistent:
 *
 *   <Reveal>        one element arriving
 *   <Stagger>       a list whose children settle in order
 *   <StaggerItem>   a child of Stagger
 *
 * All of them honour `prefers-reduced-motion` through the `MotionConfig` in the
 * root layout. None of them should wrap emergency UI — see `INSTANT` in
 * `lib/motion.ts` for why.
 */

import React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';

import { fadeUp, stagger, staggerImmediate, viewportOnce } from '@/lib/motion';

type RevealProps = {
  children: React.ReactNode;
  /** Hold the reveal briefly — use sparingly, and never above the fold. */
  delay?: number;
  /**
   * Reveal when scrolled into view rather than on mount. Default is on mount,
   * because most of this app is short pages where scroll reveal would mean
   * content appearing to be missing.
   */
  whenInView?: boolean;
  className?: string;
  as?: 'div' | 'section' | 'li' | 'article' | 'header';
} & Omit<HTMLMotionProps<'div'>, 'children' | 'variants' | 'initial' | 'animate'>;

export function Reveal({
  children,
  delay = 0,
  whenInView = false,
  className,
  as = 'div',
  ...rest
}: RevealProps) {
  const Component = motion[as] as typeof motion.div;

  const animationProps = whenInView
    ? { whileInView: 'visible' as const, viewport: viewportOnce }
    : { animate: 'visible' as const };

  return (
    <Component
      initial="hidden"
      variants={fadeUp}
      transition={delay ? { delay } : undefined}
      className={className}
      {...animationProps}
      {...rest}
    >
      {children}
    </Component>
  );
}

type StaggerProps = {
  children: React.ReactNode;
  className?: string;
  /** Skip the small entrance delay — for lists appearing after a user action. */
  immediate?: boolean;
  whenInView?: boolean;
  as?: 'div' | 'ul' | 'ol' | 'section';
};

export function Stagger({
  children,
  className,
  immediate = false,
  whenInView = false,
  as = 'div',
}: StaggerProps) {
  const Component = motion[as] as typeof motion.div;

  const animationProps = whenInView
    ? { whileInView: 'visible' as const, viewport: viewportOnce }
    : { animate: 'visible' as const };

  return (
    <Component
      initial="hidden"
      variants={immediate ? staggerImmediate : stagger}
      className={className}
      {...animationProps}
    >
      {children}
    </Component>
  );
}

type StaggerItemProps = {
  children: React.ReactNode;
  className?: string;
  as?: 'div' | 'li' | 'article';
};

export function StaggerItem({ children, className, as = 'div' }: StaggerItemProps) {
  const Component = motion[as] as typeof motion.div;
  return (
    <Component variants={fadeUp} className={className}>
      {children}
    </Component>
  );
}
