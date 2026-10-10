'use client';

/**
 * Demonstration scenarios.
 *
 * Picking one fills the ordinary situation box with its text and scrolls to
 * it. It does **not** submit anything, call a special endpoint, or render a
 * mock result — the user still reads what was written, can edit it, and
 * presses the same Continue button as anyone else. Everything downstream is
 * the real pipeline.
 *
 * That constraint is the whole point. A demo that short-circuits to a prepared
 * screen proves nothing about whether the product works; this proves the
 * product works, using text someone else wrote.
 *
 * Collapsed by default so the page still opens with a blank box and the
 * question — someone arriving with a real situation should not have to scroll
 * past four fictional ones to reach it.
 */

import React from 'react';
import { apiGet } from '@/lib/api';

export type DemoScenario = {
  id: string;
  title: string;
  summary: string;
  situation_text: string;
  category: string;
  location: string | null;
  demonstrates: string[];
  expected_engines: string[];
  urgency_hint: string;
  is_demo: boolean;
  disclaimer: string;
};

const ENGINE_LABELS: Record<string, string> = {
  google: 'Google Search',
  google_news: 'Google News',
  google_maps: 'Google Maps',
};

export default function DemoScenarios({
  onPick,
}: {
  /** Fills the intake box. Never submits — the user decides that. */
  onPick: (scenario: DemoScenario) => void;
}) {
  const [scenarios, setScenarios] = React.useState<DemoScenario[] | null>(null);
  const [open, setOpen] = React.useState(false);
  const [expanded, setExpanded] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open || scenarios) return;
    let cancelled = false;
    apiGet<{ scenarios: DemoScenario[] }>('/api/v2/demo/scenarios').then((result) => {
      if (!cancelled && result.ok) setScenarios(result.data.scenarios);
    });
    return () => {
      cancelled = true;
    };
  }, [open, scenarios]);

  return (
    <div className="rounded-xl border border-border/70 bg-muted/20">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm transition-colors hover:bg-muted/40"
      >
        <span className="text-muted-foreground">
          Not sure what to write?{' '}
          <span className="text-foreground">Start from an example situation.</span>
        </span>
        <span
          aria-hidden
          className={`shrink-0 text-xs text-muted-foreground transition-transform duration-200 ${
            open ? 'rotate-180' : ''
          }`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="border-t border-border/70 p-3">
          <p className="mb-3 px-1 text-[11px] leading-relaxed text-muted-foreground">
            Written examples, not real cases. Pick one and its text fills the box
            below — you can edit it, and the research that follows is real.
          </p>

          {!scenarios && (
            <div className="space-y-2" aria-label="Loading scenarios">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton h-16 w-full rounded-lg" />
              ))}
            </div>
          )}

          <ul className="space-y-2">
            {scenarios?.map((scenario) => {
              const isOpen = expanded === scenario.id;
              return (
                <li
                  key={scenario.id}
                  className="overflow-hidden rounded-lg border border-border/70 bg-card transition-colors hover:border-primary/40"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2 p-3">
                    <div className="min-w-0 flex-1">
                      <h4 className="text-sm font-medium text-foreground">
                        {scenario.title}
                      </h4>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                        {scenario.summary}
                      </p>

                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        {scenario.expected_engines.map((engine) => (
                          <span
                            key={engine}
                            className="rounded border border-border/70 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                            // "Likely", because the planner decides at run time
                            // and the research trail shows what actually ran.
                            title="The planner will likely use this engine — the research trail shows what actually ran"
                          >
                            {ENGINE_LABELS[engine] ?? engine}
                          </span>
                        ))}
                        {scenario.location && (
                          <span className="text-[10px] text-muted-foreground">
                            · {scenario.location}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : scenario.id)}
                        className="text-[11px] text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                      >
                        {isOpen ? 'Hide' : 'Read it'}
                      </button>
                      <button
                        type="button"
                        onClick={() => onPick(scenario)}
                        className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                      >
                        Try this
                      </button>
                    </div>
                  </div>

                  {isOpen && (
                    <div className="border-t border-border/60 bg-muted/30 p-3">
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground">
                        {scenario.situation_text}
                      </p>
                      {scenario.demonstrates.length > 0 && (
                        <>
                          <p className="mt-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            What to watch for
                          </p>
                          <ul className="mt-1 space-y-0.5">
                            {scenario.demonstrates.map((item) => (
                              <li
                                key={item}
                                className="text-[11px] leading-relaxed text-muted-foreground"
                              >
                                · {item}
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
