'use client';

import React from 'react';

/**
 * Shared loading / empty / error / partial-success states.
 *
 * Every screen uses these so no surface can silently show a spinner forever,
 * a blank page, or an empty list that is really a failed request.
 */

export function LoadingState({
  label = 'Loading…',
  rows = 3,
}: {
  label?: string;
  rows?: number;
}) {
  return (
    <div className="space-y-3" role="status" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-20 rounded-xl bg-muted/50 animate-pulse" aria-hidden="true" />
      ))}
    </div>
  );
}

export function ErrorState({
  title = 'That did not load',
  message,
  onRetry,
  retryLabel = 'Try again',
  children,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5 space-y-3 text-center"
    >
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <p className="text-sm text-muted-foreground leading-relaxed">{message}</p>
      <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            {retryLabel}
          </button>
        )}
        {children}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  message,
  children,
}: {
  title: string;
  message: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-8 text-center space-y-3">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <p className="text-sm text-muted-foreground leading-relaxed max-w-md mx-auto">
        {message}
      </p>
      {children && <div className="pt-1">{children}</div>}
    </div>
  );
}

/**
 * Shown when part of a result is missing. HerWay must never present a partial
 * research run as a complete one — e.g. web sources found but the nearby-centre
 * search failed.
 */
export function PartialResultNotice({
  messages,
  onRetry,
}: {
  messages: string[];
  onRetry?: () => void;
}) {
  if (messages.length === 0) return null;
  return (
    <div
      role="status"
      className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 space-y-2"
    >
      <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">
        Some of this research did not finish
      </p>
      <ul className="space-y-1">
        {messages.map((m, i) => (
          <li key={i} className="text-xs text-muted-foreground leading-relaxed flex gap-2">
            <span aria-hidden="true" className="mt-1.5 h-1 w-1 rounded-full bg-amber-500 shrink-0" />
            <span>{m}</span>
          </li>
        ))}
      </ul>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="text-xs font-medium text-amber-800 dark:text-amber-300 hover:underline"
        >
          Retry research →
        </button>
      )}
    </div>
  );
}

/** Inline banner for a failed action inside an otherwise working screen. */
export function InlineError({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2.5"
    >
      <p className="text-xs text-rose-800 dark:text-rose-300 leading-relaxed">{message}</p>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-rose-700 dark:text-rose-300 hover:opacity-70"
        >
          ✕
        </button>
      )}
    </div>
  );
}
