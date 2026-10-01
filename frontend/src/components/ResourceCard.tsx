'use client';

import React from 'react';
import type { MatchedResource, ResourceVerification } from '@/lib/types';
import { formatIndianDate, formatIndianPhone, telHref } from '@/lib/india';

/**
 * A support resource, labelled with exactly how much we actually know about it.
 *
 * Every resource used to carry a green "✓ Verified Resource" badge regardless
 * of provenance, including unchecked Google Maps pins. Someone in a crisis
 * travelling to a wrong address on the strength of that badge is a real harm,
 * so the three levels are now shown distinctly and the unverified case says so
 * in plain words.
 */

const VERIFICATION_STYLES: Record<
  ResourceVerification,
  { label: string; className: string }
> = {
  official_source: {
    label: 'Official government source',
    className:
      'text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-500/30',
  },
  likely_official: {
    label: 'Likely official — not confirmed',
    className:
      'text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/40 border-blue-500/30',
  },
  unverified_listing: {
    label: 'Unverified listing',
    className:
      'text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 border-amber-500/30',
  },
};

export default function ResourceCard({ resource }: { resource: MatchedResource }) {
  const verification = VERIFICATION_STYLES[resource.verification] ?? VERIFICATION_STYLES.unverified_listing;
  const phoneDisplay = formatIndianPhone(resource.phone);

  return (
    <div className="border border-border rounded-xl p-4 space-y-2.5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-1 min-w-0">
          <h3 className="text-sm font-semibold text-foreground">{resource.name}</h3>
          <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
            {resource.category && (
              <span className="capitalize">{resource.category.replace(/_/g, ' ')}</span>
            )}
            {resource.source_domain && (
              <>
                <span aria-hidden="true">·</span>
                <span className="font-mono">{resource.source_domain}</span>
              </>
            )}
            {resource.retrieved_at && (
              <>
                <span aria-hidden="true">·</span>
                <span>Researched {formatIndianDate(resource.retrieved_at)}</span>
              </>
            )}
          </div>
        </div>
        <span
          className={`text-[11px] font-medium px-2 py-0.5 rounded border shrink-0 ${verification.className}`}
        >
          {verification.label}
        </span>
      </div>

      <div className="space-y-1 text-sm">
        {resource.address && (
          <a
            href={`https://maps.google.com/?q=${encodeURIComponent(
              `${resource.name} ${resource.address}`,
            )}`}
            target="_blank"
            rel="noreferrer"
            className="flex items-start gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
            aria-label={`Open directions to ${resource.name}`}
          >
            <span aria-hidden="true" className="mt-0.5 shrink-0">
              📍
            </span>
            <span className="hover:underline">{resource.address}</span>
          </a>
        )}

        {phoneDisplay ? (
          <a
            href={telHref(resource.phone)}
            className="flex items-center gap-1.5 text-primary font-mono font-semibold hover:underline"
            aria-label={`Call ${resource.name} on ${phoneDisplay}`}
          >
            <span aria-hidden="true">📞</span>
            {phoneDisplay}
          </a>
        ) : (
          <p className="text-xs text-muted-foreground">No phone number listed.</p>
        )}

        {resource.operating_hours && (
          <p className="text-xs text-muted-foreground flex items-center gap-1.5">
            <span aria-hidden="true">🕒</span>
            {resource.operating_hours}
          </p>
        )}

        {resource.url && (
          <a
            href={resource.url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-primary hover:underline font-medium block pt-0.5"
          >
            {resource.verification === 'official_source'
              ? 'View the official page →'
              : 'View listing →'}
          </a>
        )}
      </div>

      {resource.notes && (
        <p className="text-xs text-muted-foreground leading-relaxed">{resource.notes}</p>
      )}

      {resource.verification_note && (
        <p
          className={`text-xs leading-relaxed ${
            resource.verification === 'unverified_listing'
              ? 'text-amber-800 dark:text-amber-300'
              : 'text-muted-foreground'
          }`}
        >
          {resource.verification_note}
        </p>
      )}
    </div>
  );
}
