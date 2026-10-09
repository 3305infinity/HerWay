'use client';

/**
 * Local discovery — find and compare nearby services.
 *
 * Deliberately plain about what it is: a view onto public listings. It shows
 * where every field came from and when it was fetched, labels anything the
 * source did not publish, and never tells the user a place is safe. Search
 * results cannot establish that, and a confident-looking verdict here would be
 * worse than no answer at all.
 *
 * Built on the existing conventions: `apiPost` from `@/lib/api` (which returns
 * a result rather than throwing), the shared Tailwind palette, and the same
 * card styling used by ResourceCard.
 */

import React from 'react';
import { motion } from 'framer-motion';

import { apiGet, apiPost } from '@/lib/api';
import { Reveal } from '@/components/motion/Reveal';
import ResourceFeedback from '@/components/ResourceFeedback';

type Category = { value: string; label: string };

type Resource = {
  name: string;
  category: string;
  address: string | null;
  phone: string | null;
  url: string | null;
  source_domain: string | null;
  rating: number | null;
  review_count: number | null;
  verification: string;
  verification_note: string;
  hours_text: string | null;
  retrieved_at: number;
  open_now_known: boolean;
};

type ResourcePayload = {
  resources: Resource[];
  success: boolean;
  failure_reason: string;
  location_used: string | null;
  found_nothing: boolean;
  from_cache: boolean;
  retrieved_at: number;
  disclaimer: string;
};

type ComparisonCell = { value: unknown; available: boolean; note: string };
type Comparison = {
  option_names: string[];
  fields_compared: string[];
  table: Record<string, Record<string, ComparisonCell>>;
  notes: string[];
  has_overall_ranking: boolean;
  basis: string;
};

/** Fallback list so the page still works if the categories call fails. */
const FALLBACK_CATEGORIES: Category[] = [
  { value: 'hospital', label: 'Hospital' },
  { value: 'clinic', label: 'Clinic' },
  { value: 'pharmacy', label: 'Pharmacy' },
  { value: 'police', label: 'Police' },
  { value: 'women_police', label: 'Women Police' },
  { value: 'one_stop_centre', label: 'One Stop Centre' },
  { value: 'shelter', label: 'Shelter' },
  { value: 'legal_aid', label: 'Legal Aid' },
  { value: 'transport_hub', label: 'Transport Hub' },
  { value: 'accommodation', label: 'Accommodation' },
  { value: 'counselling', label: 'Counselling' },
  { value: 'atm', label: 'ATM' },
];

function formatRetrieved(unixSeconds: number): string {
  if (!unixSeconds) return 'unknown';
  const date = new Date(unixSeconds * 1000);
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function VerificationBadge({ level, note }: { level: string; note: string }) {
  // Provenance, not a safety rating. The wording is chosen so none of these
  // can be read as "we checked this place and it is fine".
  const styles: Record<string, string> = {
    official_source: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
    likely_official: 'bg-sky-500/10 text-sky-700 dark:text-sky-400',
    unverified_listing: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
  };
  const labels: Record<string, string> = {
    official_source: 'Official source',
    likely_official: 'Likely official',
    unverified_listing: 'Unverified listing',
  };
  return (
    <span
      title={note}
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
        styles[level] ?? styles.unverified_listing
      }`}
    >
      {labels[level] ?? 'Unverified listing'}
    </span>
  );
}

function ResourceCardItem({ resource }: { resource: Resource }) {
  return (
    <li className="rounded-xl border border-border bg-card p-4 elevate-1 transition-all duration-150 hover:-translate-y-0.5 hover:border-primary/30 hover:elevate-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-semibold text-card-foreground">{resource.name}</h3>
        <VerificationBadge level={resource.verification} note={resource.verification_note} />
      </div>

      <dl className="mt-2 space-y-1 text-sm text-muted-foreground">
        <div>
          <dt className="sr-only">Address</dt>
          <dd>{resource.address ?? <span className="italic">Address not published</span>}</dd>
        </div>
        <div>
          <dt className="sr-only">Phone</dt>
          <dd>
            {resource.phone ? (
              <a href={`tel:${resource.phone}`} className="hover:underline">
                {resource.phone}
              </a>
            ) : (
              <span className="italic">No phone number published</span>
            )}
          </dd>
        </div>
        {resource.rating !== null && (
          <div>
            <dt className="sr-only">Rating</dt>
            <dd>
              {resource.rating}
              {resource.review_count ? ` from ${resource.review_count} reviews` : ''}{' '}
              <span className="text-xs">(customer experience, not safety)</span>
            </dd>
          </div>
        )}
      </dl>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {resource.url && (
          <a
            href={resource.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            Source{resource.source_domain ? `: ${resource.source_domain}` : ''}
          </a>
        )}
        <span>Retrieved {formatRetrieved(resource.retrieved_at)}</span>
        {/* Stated rather than implied: the provider does not tell us this. */}
        <span className="italic">Opening status unknown</span>
      </div>

      {/* The one thing search cannot tell us — whether it actually works.
          Anonymous; see ResourceFeedback. */}
      <ResourceFeedback phone={resource.phone} url={resource.url} name={resource.name} />
    </li>
  );
}

export default function DiscoverPage() {
  const [categories, setCategories] = React.useState<Category[]>(FALLBACK_CATEGORIES);
  const [category, setCategory] = React.useState('pharmacy');
  const [location, setLocation] = React.useState('');
  const [mode, setMode] = React.useState<'list' | 'compare'>('list');

  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [payload, setPayload] = React.useState<ResourcePayload | null>(null);
  const [comparison, setComparison] = React.useState<Comparison | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    apiGet<{ categories: Category[] }>('/api/v2/discover/categories').then((result) => {
      if (!cancelled && result.ok && result.data?.categories?.length) {
        setCategories(result.data.categories);
      }
      // On failure the fallback list stays — the page remains usable.
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function runSearch(event: React.FormEvent) {
    event.preventDefault();
    if (!location.trim()) {
      setError('Enter a city, locality or area. HerWay will not guess your location.');
      return;
    }

    setLoading(true);
    setError(null);
    setPayload(null);
    setComparison(null);

    if (mode === 'compare') {
      const result = await apiPost<{ resources: ResourcePayload; comparison: Comparison }>(
        '/api/v2/discover/compare',
        { category, location: location.trim(), priorities: [] },
      );
      setLoading(false);
      if (!result.ok) {
        setError(result.error.message);
        return;
      }
      setPayload(result.data!.resources);
      setComparison(result.data!.comparison);
      return;
    }

    const result = await apiPost<ResourcePayload>('/api/v2/discover/resources', {
      category,
      location: location.trim(),
    });
    setLoading(false);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setPayload(result.data!);
  }

  const providerFailed = payload && !payload.success;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <Reveal as="header" className="mb-7">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-primary">
          Local discovery
        </p>
        <h1 className="mt-2 font-serif text-3xl font-normal sm:text-4xl">
          Find places nearby
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
          Search public listings for services in an area you choose. HerWay shows you
          what the sources say and what they leave out — it cannot tell you whether a
          place is safe, and it will not pretend otherwise.
        </p>
      </Reveal>

      <form onSubmit={runSearch} className="mb-6 space-y-3 rounded-lg border border-border bg-card p-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-sm font-medium">What are you looking for?</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              {categories.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-sm font-medium">City, locality or area</span>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Kothrud, Pune"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              // No geolocation prompt: a place name is enough for this, and
              // asking for GPS would collect a sensitive signal for no benefit.
            />
          </label>
        </div>

        <fieldset className="flex flex-wrap items-center gap-4">
          <legend className="sr-only">Result format</legend>
          {(['list', 'compare'] as const).map((m) => (
            <label key={m} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="mode"
                checked={mode === m}
                onChange={() => setMode(m)}
              />
              {m === 'list' ? 'Show a list' : 'Compare side by side'}
            </label>
          ))}
        </fieldset>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60 sm:w-auto"
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </form>

      {/* Loading.
          Skeleton cards in the shape of the results, so the page does not jump
          when they land. A live search can take several seconds. */}
      {loading && (
        <div role="status" aria-label="Searching public listings" className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="skeleton h-4 w-40 rounded" />
                <div className="skeleton h-4 w-24 rounded" />
              </div>
              <div className="mt-3 space-y-2">
                <div className="skeleton h-3 w-3/4 rounded" />
                <div className="skeleton h-3 w-1/2 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Request-level error (network, rate limit, timeout) */}
      {error && !loading && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm"
        >
          <p className="font-medium">This search did not complete.</p>
          <p className="mt-1 text-muted-foreground">{error}</p>
          <p className="mt-2 text-muted-foreground">
            This is a problem on our side — it does not mean there is nothing near you.
            For urgent help call{' '}
            <a href="tel:112" className="text-primary hover:underline">
              112
            </a>
            , or{' '}
            <a href="tel:181" className="text-primary hover:underline">
              181
            </a>{' '}
            for the women helpline.
          </p>
        </div>
      )}

      {/* Provider failed — explicitly NOT "nothing found" */}
      {providerFailed && !loading && (
        <div
          role="alert"
          className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm"
        >
          <p className="font-medium">The search service did not respond.</p>
          <p className="mt-1 text-muted-foreground">
            We could not retrieve listings ({payload?.failure_reason}). This is not the
            same as finding nothing — please try again shortly.
          </p>
        </div>
      )}

      {/* Genuinely empty */}
      {payload?.found_nothing && !loading && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm">
          <p className="font-medium">No listings matched.</p>
          <p className="mt-1 text-muted-foreground">
            Nothing was published for that search in {payload.location_used}. Try a nearby
            area or a broader category. The women helpline on{' '}
            <a href="tel:181" className="text-primary hover:underline">
              181
            </a>{' '}
            can also refer you to local services.
          </p>
        </div>
      )}

      {/* Results */}
      {payload && payload.success && payload.resources.length > 0 && !loading && (
        <section aria-label="Search results">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>
              {payload.resources.length} listing(s) near {payload.location_used}
            </span>
            <span>
              Retrieved {formatRetrieved(payload.retrieved_at)}
              {payload.from_cache ? ' (from cache)' : ''}
            </span>
          </div>

          {comparison && (
            <div className="mb-5 overflow-x-auto rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">Side by side</h2>
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Field
                    </th>
                    {comparison.option_names.map((name) => (
                      <th key={name} scope="col" className="py-2 pr-3 font-medium">
                        {name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {comparison.fields_compared.map((field) => (
                    <tr key={field} className="border-b border-border/50">
                      <th scope="row" className="py-2 pr-3 font-normal text-muted-foreground">
                        {field.replace(/_/g, ' ')}
                      </th>
                      {comparison.option_names.map((name) => {
                        const cell = comparison.table[field]?.[name];
                        return (
                          <td key={name} className="py-2 pr-3">
                            {cell?.available ? (
                              String(cell.value)
                            ) : (
                              <span className="italic text-muted-foreground">
                                not published
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
                {comparison.notes.map((note) => (
                  <li key={note}>· {note}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Results settle in reading order. 45ms apart — enough to follow,
              short enough that a list of six is fully settled in under a third
              of a second. */}
          <ul className="space-y-3">
            {payload.resources.map((resource, i) => (
              <motion.div
                key={`${resource.name}-${i}`}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.045, duration: 0.28, ease: [0.22, 0.61, 0.36, 1] }}
              >
                <ResourceCardItem resource={resource} />
              </motion.div>
            ))}
          </ul>

          <p className="mt-4 rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
            {payload.disclaimer}
          </p>
        </section>
      )}
    </main>
  );
}
