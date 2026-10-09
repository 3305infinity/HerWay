'use client';

/**
 * "Did this work?" — a small anonymous report on a listed resource.
 *
 * HerWay can say a number came from an official page. It cannot say whether
 * anyone picks up, whether the office moved, or whether the shelter is still
 * taking people. Only the women who tried know that, and today that knowledge
 * is lost the moment they close the tab.
 *
 * Two things the UI has to get right:
 *
 * 1. **Say it is anonymous, before they tap.** Reporting on a shelter implies
 *    you contacted one. If someone cannot tell what is being recorded, the
 *    honest choice is not to tap — so the reassurance goes above the buttons,
 *    not in a tooltip.
 * 2. **Never let counts read as verification.** "4 people said this did not
 *    connect" is a report from the public, not a check by HerWay, and the
 *    wording says so.
 *
 * Deliberately collapsed by default: a row of judgement buttons under every
 * listing would turn a page someone is scanning for a phone number into a
 * survey.
 */

import React from 'react';
import { apiGet, apiPost } from '@/lib/api';

type Counts = Record<string, number>;

type FeedbackSummary = {
  reports: number;
  counts: Counts;
  last_seen: string | null;
  is_community_reported: boolean;
  note: string;
};

type Outcome = { value: string; label: string };

/** Mirrors `OUTCOMES` in backend/services/resource_feedback.py. Used until the
 *  options endpoint answers, so the control is usable immediately. */
const FALLBACK_OUTCOMES: Outcome[] = [
  { value: 'worked', label: 'Reached someone who could help' },
  { value: 'no_answer', label: 'Nobody answered' },
  { value: 'wrong_number', label: 'Number is wrong or disconnected' },
  { value: 'moved', label: 'Address or office has changed' },
  { value: 'not_relevant', label: 'Not the right kind of help' },
];

const POSITIVE = 'worked';

export default function ResourceFeedback({
  phone,
  url,
  name,
}: {
  phone?: string | null;
  url?: string | null;
  name?: string | null;
}) {
  const [open, setOpen] = React.useState(false);
  const [outcomes, setOutcomes] = React.useState<Outcome[]>(FALLBACK_OUTCOMES);
  const [summary, setSummary] = React.useState<FeedbackSummary | null>(null);
  const [submitted, setSubmitted] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const identifier = React.useMemo(() => {
    const params = new URLSearchParams();
    if (phone) params.set('phone', phone);
    else if (url) params.set('url', url);
    else if (name) params.set('name', name);
    return params.toString();
  }, [phone, url, name]);

  // Existing counts are fetched only when the panel is opened. Doing it on
  // mount would fire one request per listing on every search.
  React.useEffect(() => {
    if (!open || !identifier || summary) return;
    let cancelled = false;

    apiGet<FeedbackSummary>(`/api/v2/resources/feedback?${identifier}`).then((result) => {
      if (!cancelled && result.ok) setSummary(result.data);
    });
    apiGet<{ outcomes: Outcome[] }>('/api/v2/resources/feedback-options').then((result) => {
      if (!cancelled && result.ok && result.data.outcomes?.length) {
        setOutcomes(result.data.outcomes);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [open, identifier, summary]);

  async function report(outcome: string) {
    setBusy(true);
    setError(null);
    const result = await apiPost<FeedbackSummary>('/api/v2/resources/feedback', {
      outcome,
      phone: phone ?? null,
      url: url ?? null,
      name: name ?? null,
    });
    setBusy(false);

    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setSummary(result.data);
    setSubmitted(true);
  }

  if (!identifier) return null;

  const negativeReports = summary
    ? Object.entries(summary.counts)
        .filter(([key]) => key !== POSITIVE)
        .reduce((total, [, value]) => total + value, 0)
    : 0;

  return (
    <div className="mt-3 border-t border-border/60 pt-2.5">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-[11px] text-muted-foreground underline-offset-4 transition-colors hover:text-primary hover:underline"
        >
          Did this work for you?
        </button>
      ) : submitted ? (
        <div className="space-y-1">
          <p className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
            Thank you — recorded anonymously.
          </p>
          {summary && summary.reports > 0 && (
            <p className="text-[11px] text-muted-foreground">
              {summary.counts[POSITIVE] ?? 0} reached someone · {negativeReports} had a
              problem. {summary.note}
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {/* Reassurance first. Someone deciding whether to tap needs to know
              what is recorded before they do, not after. */}
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Anonymous — counted against this listing, not against you. HerWay does not
            record who reported what.
          </p>

          <div className="flex flex-wrap gap-1.5">
            {outcomes.map((outcome) => (
              <button
                key={outcome.value}
                type="button"
                disabled={busy}
                onClick={() => report(outcome.value)}
                className={`rounded-md border px-2 py-1 text-[11px] transition-colors disabled:opacity-50 ${
                  outcome.value === POSITIVE
                    ? 'border-emerald-500/40 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-400'
                    : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'
                }`}
              >
                {outcome.label}
              </button>
            ))}
          </div>

          {summary && summary.reports > 0 && (
            <p className="text-[11px] text-muted-foreground">
              {summary.reports} previous report(s). {summary.note}
            </p>
          )}

          {error && (
            <p role="alert" className="text-[11px] text-amber-600 dark:text-amber-400">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-[11px] text-muted-foreground underline-offset-4 hover:underline"
          >
            Close
          </button>
        </div>
      )}
    </div>
  );
}
