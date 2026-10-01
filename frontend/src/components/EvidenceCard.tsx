'use client';

import React from 'react';
import type { EvidenceItem } from '@/lib/types';

/**
 * A single verified source.
 *
 * The user must be able to answer "why are you telling me this?" from what is
 * on screen: what claim the source supports, where it came from, what kind of
 * source it is, how current it is, how authoritative, and whether anything
 * contradicts it.
 *
 * Only concise, user-facing evidence summaries are shown — never model
 * reasoning.
 */

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  verified_strongly_supported: {
    label: 'Strongly supported',
    className:
      'text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-500/30',
  },
  partially_supported: {
    label: 'Partially supported',
    className:
      'text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/40 border-blue-500/30',
  },
  conflicting: {
    label: 'Sources disagree',
    className:
      'text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 border-amber-500/30',
  },
  unverified: {
    label: 'Unverified',
    className:
      'text-muted-foreground bg-muted border-border',
  },
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  official_government: 'Government source',
  official_organization: 'Official organisation',
  news: 'News report',
  academic: 'Academic',
  company: 'Company page',
  local_business: 'Local listing',
  community: 'Community content',
  blog: 'Blog',
  forum: 'Forum',
  unknown: 'Unclassified',
};

function scoreLabel(score?: number): string {
  if (score === undefined || score === null) return 'Not scored';
  if (score >= 0.85) return 'High';
  if (score >= 0.6) return 'Medium';
  return 'Low';
}

function ScoreRow({ label, score }: { label: string; score?: number }) {
  if (score === undefined || score === null) return null;
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-muted-foreground w-20 shrink-0">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden" aria-hidden="true">
        <div
          className="h-full rounded-full bg-primary/70"
          style={{ width: `${Math.round(Math.min(1, Math.max(0, score)) * 100)}%` }}
        />
      </div>
      <span className="text-[11px] text-muted-foreground w-12 text-right">
        {scoreLabel(score)}
      </span>
    </div>
  );
}

export default function EvidenceCard({ evidence }: { evidence: EvidenceItem }) {
  const status = STATUS_LABELS[evidence.status ?? 'unverified'] ?? STATUS_LABELS.unverified;
  const sourceType = SOURCE_TYPE_LABELS[evidence.source_type ?? 'unknown'] ?? 'Unclassified';
  const hasConflicts = (evidence.contradictions?.length ?? 0) > 0;

  return (
    <div className="border border-border rounded-xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-1 min-w-0 flex-1">
          <h3 className="text-sm font-medium text-foreground leading-snug">
            {evidence.source_title || evidence.domain}
          </h3>
          <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
            <span>{sourceType}</span>
            {evidence.domain && (
              <>
                <span aria-hidden="true">·</span>
                <span className="font-mono">{evidence.domain}</span>
              </>
            )}
          </div>
        </div>
        <span
          className={`text-[11px] font-medium px-2 py-0.5 rounded border shrink-0 ${status.className}`}
        >
          {status.label}
        </span>
      </div>

      {evidence.claim_supported && (
        <div className="space-y-1">
          <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            What this source supports
          </p>
          <p className="text-sm text-foreground/90 leading-relaxed bg-muted/20 p-2.5 rounded-lg border border-border/40">
            {evidence.claim_supported}
          </p>
        </div>
      )}

      {evidence.why_this_source_matters && (
        <p className="text-xs text-muted-foreground leading-relaxed">
          <span className="font-medium text-foreground">Why this matters: </span>
          {evidence.why_this_source_matters}
        </p>
      )}

      <details className="group">
        <summary className="cursor-pointer text-xs text-primary hover:underline list-none">
          How we rated this source
        </summary>
        <div className="pt-2.5 space-y-1.5">
          <ScoreRow label="Authority" score={evidence.authority} />
          <ScoreRow label="Relevance" score={evidence.relevance} />
          <ScoreRow label="Freshness" score={evidence.freshness} />
          <ScoreRow label="Overall" score={evidence.confidence_score} />
          <p className="text-[11px] text-muted-foreground leading-relaxed pt-1">
            Authority reflects the kind of source (government portals rank highest).
            Freshness reflects how current the information appears. Overall combines
            both with how directly the source answers your question.
          </p>
        </div>
      </details>

      {hasConflicts && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 space-y-1.5">
          <p className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">
            Sources disagree on this
          </p>
          {evidence.contradictions!.map((c, i) => (
            <p key={i} className="text-xs text-muted-foreground leading-relaxed">
              {c.difference}{' '}
              <span className="text-foreground/80">
                ({c.source_a} vs {c.source_b})
              </span>
            </p>
          ))}
          <p className="text-[11px] text-amber-800 dark:text-amber-300">
            Where sources conflict, trust the official government page over the others.
          </p>
        </div>
      )}

      {evidence.url && (
        <a
          href={evidence.url}
          target="_blank"
          rel="noreferrer"
          className="inline-block text-xs text-primary hover:underline font-medium"
          aria-label={`Open source: ${evidence.source_title || evidence.domain}`}
        >
          Read the source →
        </a>
      )}
    </div>
  );
}
