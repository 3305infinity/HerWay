'use client';

import React, { useState } from 'react';

import type { ResearchTraceEntry } from '@/lib/types';

export type TraceEntry = ResearchTraceEntry & { is_followup?: boolean };

export interface Degradation {
  stage: string;
  reason: string;
  user_message: string;
}

interface ResearchTrailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  trace: TraceEntry[];
  evidenceCount?: number;
  /** Parts of the research that did not complete. */
  degradations?: Degradation[];
  /** The location actually searched, or null if the user gave none. */
  locationUsed?: string | null;
  hasPlan?: boolean;
}

// Map engine names to human labels
function engineLabel(engine: string) {
  const e = engine.toLowerCase();
  if (e.includes('news')) return 'News';
  if (e.includes('map') || e.includes('local')) return 'Maps';
  return 'Web';
}

export default function ResearchTrailDrawer({
  isOpen,
  onClose,
  trace = [],
  evidenceCount = 0,
  degradations = [],
  locationUsed = null,
  hasPlan = false,
}: ResearchTrailDrawerProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  if (!isOpen) return null;

  const successCount = trace.filter((t) => t.success && !t.is_cached).length;
  const failedCount = trace.filter((t) => !t.success).length;
  const cachedCount = trace.filter((t) => t.is_cached).length;
  const totalMs = trace.reduce((acc, t) => acc + (t.time_taken_ms || 0), 0);

  // Each stage is marked done only from evidence that it actually ran. The
  // previous version ticked stages off purely from how many searches existed,
  // so a case where every search failed still displayed five green ticks.
  const journeySteps = [
    {
      key: 'understanding',
      label: 'Understanding your situation',
      done: trace.length > 0 || evidenceCount > 0 || hasPlan,
      note: '',
    },
    {
      key: 'searching',
      label: 'Searching official resources',
      done: trace.some((t) => engineLabel(t.engine) === 'Web' && t.success),
      note: trace.some((t) => engineLabel(t.engine) === 'Web' && !t.success)
        ? 'A web search did not complete'
        : '',
    },
    {
      key: 'local',
      label: 'Checking local support',
      done: trace.some((t) => engineLabel(t.engine) === 'Maps' && t.success),
      note: locationUsed
        ? trace.some((t) => engineLabel(t.engine) === 'Maps' && !t.success)
          ? 'The nearby-centre search did not complete'
          : ''
        : 'Skipped — no location provided',
    },
    {
      key: 'verifying',
      label: 'Comparing and verifying sources',
      done: evidenceCount > 0,
      note: evidenceCount === 0 ? 'No sources could be verified' : '',
    },
    {
      key: 'planning',
      label: 'Building your plan',
      done: hasPlan,
      note: hasPlan ? '' : 'No plan was produced',
    },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="How HerWay researched your situation"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-background h-full shadow-2xl flex flex-col border-l border-border">

        {/* Header */}
        <div className="p-5 border-b border-border flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-foreground">
              How HerWay researched this
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {successCount} search{successCount !== 1 ? 'es' : ''} · {evidenceCount} source
              {evidenceCount !== 1 ? 's' : ''} verified
              {cachedCount > 0 && ` · ${cachedCount} reused`}
              {failedCount > 0 && ` · ${failedCount} failed`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            aria-label="Close research trail"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto custom-scrollbar">

          {/* Research journey — simplified steps */}
          <div className="p-5 border-b border-border/50">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-4">
              Research journey
            </p>
            <div className="space-y-3">
              {journeySteps.map((step) => (
                <div key={step.key} className="flex items-start gap-3">
                  <div
                    className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
                      step.done ? 'bg-emerald-500' : 'bg-muted border-2 border-border'
                    }`}
                    aria-hidden="true"
                  >
                    {step.done && (
                      <svg width="9" height="9" viewBox="0 0 9 9" fill="none">
                        <path d="M1.5 4.5L3.5 6.5L7.5 2.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    )}
                  </div>
                  <div className="space-y-0.5">
                    <span className={`text-sm ${step.done ? 'text-foreground' : 'text-muted-foreground/60'}`}>
                      {step.label}
                    </span>
                    {step.note && (
                      <p className="text-[11px] text-amber-700 dark:text-amber-400">{step.note}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {degradations.length > 0 && (
            <div className="px-5 pb-5">
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 space-y-1.5">
                <p className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">
                  What is missing from this research
                </p>
                {degradations.map((d, i) => (
                  <p key={i} className="text-xs text-muted-foreground leading-relaxed">
                    {d.user_message}
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* Individual search details — collapsed by default */}
          {trace.length > 0 && (
            <div className="p-5">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Searches performed
              </p>
              <div className="space-y-2">
                {trace.map((entry, idx) => {
                  const isExpanded = expandedIndex === idx;
                  return (
                    <div key={entry.task_id || idx} className="border border-border rounded-lg overflow-hidden">
                      <button
                        className="w-full flex items-start justify-between gap-3 p-3 text-left hover:bg-muted/30 transition-colors"
                        onClick={() => setExpandedIndex(isExpanded ? null : idx)}
                        aria-expanded={isExpanded}
                      >
                        <div className="flex-1 min-w-0 space-y-0.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                              entry.is_cached
                                ? 'bg-muted text-muted-foreground'
                                : engineLabel(entry.engine) === 'Maps'
                                ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                                : engineLabel(entry.engine) === 'News'
                                ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                                : 'bg-primary/8 text-primary'
                            }`}>
                              {entry.is_cached ? 'Cached' : engineLabel(entry.engine)}
                            </span>
                            {entry.is_followup && (
                              <span className="text-[10px] text-muted-foreground">Follow-up</span>
                            )}
                          </div>
                          <p className="text-xs text-foreground font-medium leading-snug line-clamp-1">
                            {entry.why_searched || entry.query}
                          </p>
                          <p
                            className={`text-[11px] ${
                              entry.success ? 'text-muted-foreground' : 'text-amber-700 dark:text-amber-400'
                            }`}
                          >
                            {entry.is_cached
                              ? 'Reused an earlier identical search'
                              : entry.success
                              ? `${entry.results_found} result${entry.results_found !== 1 ? 's' : ''} · ${Math.round(entry.time_taken_ms)}ms`
                              : 'This search did not complete'}
                          </p>
                        </div>
                        <svg
                          width="12"
                          height="12"
                          viewBox="0 0 12 12"
                          fill="none"
                          className={`shrink-0 mt-1 text-muted-foreground transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                          aria-hidden="true"
                        >
                          <path d="M2 4L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      </button>

                      {/* Expanded detail */}
                      {isExpanded && (
                        <div className="px-3 pb-3 pt-0 space-y-2 border-t border-border/50 bg-muted/20">
                          <div className="pt-2 space-y-1">
                            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Query</p>
                            <p className="text-xs text-foreground font-mono break-all leading-relaxed">
                              {entry.query}
                            </p>
                          </div>
                          {entry.selected_urls && entry.selected_urls.length > 0 && (
                            <div className="space-y-1">
                              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                                Sources checked
                              </p>
                              <ul className="space-y-1">
                                {entry.selected_urls.slice(0, 3).map((url, uidx) => (
                                  <li key={uidx}>
                                    <a
                                      href={url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="text-xs text-primary hover:underline break-all"
                                    >
                                      {url.replace(/^https?:\/\//, '').split('/')[0]}
                                    </a>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {entry.error && (
                            <p className="text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
                              Why it failed: {entry.error}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {trace.length === 0 && (
            <div className="p-8 text-center">
              <p className="text-sm text-muted-foreground">
                No research performed yet for this case.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        {totalMs > 0 && (
          <div className="p-4 border-t border-border">
            <p className="text-xs text-muted-foreground text-center">
              Research completed in {(totalMs / 1000).toFixed(1)}s
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
