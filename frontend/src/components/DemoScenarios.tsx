'use client';

/**
 * Quick-start chips under the writing box.
 *
 * Picking one fills the ordinary situation box with its text and sets the
 * location. It does **not** submit anything, call a special endpoint, or render
 * a prepared result — the user still reads what was written, can edit it, and
 * presses the same Continue button as anyone else. Everything downstream is the
 * real pipeline.
 *
 * This replaced an expandable panel that explained itself at length before
 * showing anything. A row of chips is what the rest of the product does when it
 * offers a shortcut, and it does not ask the reader to open a disclosure before
 * they can start.
 *
 * Two rows, scrolling sideways, so ten shortcuts never push the writing surface
 * down the page. If the list cannot be fetched the row simply does not render —
 * there is no local copy of the text to fall back on, and inventing one would
 * put words in the box that no situation actually produced.
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

/**
 * Chip wording — shorter and more spoken than the stored titles, which are
 * written to read as headings. Anything without an entry falls back to its own
 * title rather than being hidden.
 */
const CHIP_LABELS: Record<string, string> = {
  late_night_travel: 'Travelling late alone',
  workplace_harassment: 'Harassment at work',
  online_blackmail: 'Blackmail online',
  unfamiliar_area: 'Unfamiliar area',
  domestic_violence_exit: 'Need to leave home',
  stalking_ex: 'Being followed or stalked',
  fir_refused: "Police won't register FIR",
  campus_harassment: 'Campus harassment',
  dowry_pressure: 'Dowry pressure',
  new_city_housing: 'Moving to a new city',
};

export default function DemoScenarios({
  onPick,
}: {
  /** Fills the intake box. Never submits — the user decides that. */
  onPick: (scenario: DemoScenario) => void;
}) {
  const [scenarios, setScenarios] = React.useState<DemoScenario[] | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    apiGet<{ scenarios: DemoScenario[] }>('/api/v2/demo/scenarios').then((result) => {
      if (cancelled) return;
      if (result.ok) setScenarios(result.data.scenarios);
      else setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">Quick start</p>

      {/* Two rows that scroll sideways rather than wrapping into four. The
          writing box stays the tallest thing in view at every width. */}
      <div className="custom-scrollbar -mx-1 grid auto-cols-max grid-flow-col grid-rows-2 gap-2 overflow-x-auto px-1 pb-1">
        {!scenarios
          ? [0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="skeleton h-8 w-36 rounded-full" aria-hidden />
            ))
          : scenarios.map((scenario) => (
              <button
                key={scenario.id}
                type="button"
                onClick={() => onPick(scenario)}
                title={scenario.summary}
                className="whitespace-nowrap rounded-full border border-border/80 bg-card px-3.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:bg-primary/[0.06] hover:text-foreground"
              >
                {CHIP_LABELS[scenario.id] ?? scenario.title}
              </button>
            ))}
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Fills the box above so you can edit it before continuing. Nothing is sent
        until you press Continue.
      </p>
    </div>
  );
}
