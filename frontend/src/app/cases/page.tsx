'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';

import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/States';
import { apiGet, apiPatch, type ApiError } from '@/lib/api';
import { timeAgo } from '@/lib/india';
import type { CaseRecord } from '@/lib/types';

const STATUS_STYLES: Record<string, string> = {
  active: 'text-emerald-700 bg-emerald-50 dark:bg-emerald-900/30 dark:text-emerald-400',
  paused: 'text-amber-700 bg-amber-50 dark:bg-amber-900/30 dark:text-amber-400',
  resolved: 'text-blue-700 bg-blue-50 dark:bg-blue-900/30 dark:text-blue-400',
  archived: 'text-muted-foreground bg-muted',
};

const TABS = ['all', 'active', 'paused', 'resolved', 'archived'] as const;

function formatCategory(cat: string) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}

export default function MyCasesPage() {
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]>('all');

  const fetchCases = useCallback(async () => {
    setLoading(true);
    setLoadError(null);

    // No user_id is sent: the backend resolves the owner from the session, so
    // a case list can never be redirected at someone else's account.
    const result = await apiGet<CaseRecord[]>('/api/v2/cases?limit=100');
    if (result.ok) {
      setCases(result.data);
    } else {
      setLoadError(result.error);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void fetchCases();
  }, [fetchCases]);

  const updateStatus = async (caseId: string, newStatus: string) => {
    setStatusError(null);
    const previous = cases;

    setCases((prev) =>
      prev.map((c) => (c.id === caseId ? { ...c, status: newStatus } : c)),
    );

    const result = await apiPatch(`/api/v2/cases/${caseId}`, { status: newStatus });
    if (!result.ok) {
      // Roll back rather than showing a status that was never saved.
      setCases(previous);
      setStatusError(`${result.error.message} The status was not changed.`);
    }
  };

  const filteredCases = cases.filter((c) =>
    activeTab === 'all' ? c.status !== 'archived' : c.status === activeTab,
  );
  const liveCount = cases.filter((c) => c.status !== 'archived').length;

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-background">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-2 border-b border-border">
          <div>
            <h1 className="text-2xl sm:text-3xl font-semibold text-foreground">My cases</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Your saved situations, plans and resources. Only you can see these.
            </p>
          </div>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors self-start sm:self-auto"
          >
            Start a new case
          </Link>
        </div>

        <div
          className="flex items-center gap-1 border-b border-border overflow-x-auto"
          role="tablist"
          aria-label="Filter cases by status"
        >
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px whitespace-nowrap ${
                activeTab === tab
                  ? 'border-primary text-primary font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab}
              {tab === 'all' && liveCount > 0 && (
                <span className="ml-1.5 text-xs text-muted-foreground">({liveCount})</span>
              )}
            </button>
          ))}
        </div>

        {statusError && (
          <InlineError message={statusError} onDismiss={() => setStatusError(null)} />
        )}

        {loading ? (
          <LoadingState label="Loading your cases" rows={3} />
        ) : loadError ? (
          <ErrorState
            title="We could not load your cases"
            message={loadError.message}
            onRetry={() => void fetchCases()}
          />
        ) : filteredCases.length === 0 ? (
          cases.length === 0 ? (
            <EmptyState
              title="You do not have any saved cases yet"
              message="When you tell HerWay what is happening, it saves a case so you can come back to it at any time."
            >
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
              >
                Start with HerWay →
              </Link>
            </EmptyState>
          ) : (
            <EmptyState
              title={`No ${activeTab} cases`}
              message="Try another filter to see the rest of your cases."
            >
              <button
                type="button"
                onClick={() => setActiveTab('all')}
                className="inline-flex items-center gap-1.5 px-4 py-2 border border-border text-foreground text-sm font-medium rounded-lg hover:bg-muted transition-colors"
              >
                View all cases
              </button>
            </EmptyState>
          )
        ) : (
          <div className="space-y-3">
            {filteredCases.map((c) => {
              const actions = c.action_plan?.actions ?? c.safety_plan?.actions ?? [];
              const completed = actions.filter(
                (a) =>
                  ('completed' in a && a.completed) ||
                  ('status' in a && a.status === 'completed'),
              ).length;
              const total = actions.length;
              const progress = total > 0 ? (completed / total) * 100 : 0;

              return (
                <div
                  key={c.id}
                  className="bg-card border border-border rounded-xl p-5 hover:border-border/80 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start justify-between gap-4 flex-wrap sm:flex-nowrap">
                    <div className="flex-1 min-w-0 space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
                          {formatCategory(c.category || 'case')}
                        </span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded capitalize ${
                            STATUS_STYLES[c.status] || STATUS_STYLES.archived
                          }`}
                        >
                          {c.status || 'active'}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {timeAgo(c.updated_at || c.created_at)}
                        </span>
                      </div>

                      <h2 className="text-base font-medium text-foreground leading-snug truncate">
                        {/* A case the user did not write needs to be
                            distinguishable from one she did — otherwise an
                            example in her own case list reads as a real report
                            she does not remember filing.

                            Softened from a loud uppercase DEMO chip to a quiet
                            label: still unambiguous, no longer shouting that
                            the product is a demo. */}
                        {c.is_demo && (
                          <span className="mr-2 align-middle text-[11px] font-normal text-muted-foreground">
                            Example ·
                          </span>
                        )}
                        {c.title?.replace(/^Example:\s*/, '') || 'Untitled case'}
                      </h2>

                      <p className="text-sm text-muted-foreground line-clamp-1 leading-relaxed">
                        {c.situation_text}
                      </p>

                      {total > 0 && (
                        <div className="flex items-center gap-3">
                          <div className="haven-progress-bar flex-1 max-w-32">
                            <div className="haven-progress-fill" style={{ width: `${progress}%` }} />
                          </div>
                          <span className="text-xs text-muted-foreground shrink-0">
                            {completed} of {total} steps done
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="flex flex-row sm:flex-col items-center sm:items-end gap-2 shrink-0">
                      <Link
                        href={`/cases/${c.id}`}
                        className="px-3.5 py-1.5 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors whitespace-nowrap"
                      >
                        Open →
                      </Link>
                      <select
                        value={c.status || 'active'}
                        onChange={(e) => void updateStatus(c.id, e.target.value)}
                        aria-label={`Change status for ${c.title || 'this case'}`}
                        className="text-xs bg-background border border-input rounded-md px-2 py-1 text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer"
                      >
                        <option value="active">Active</option>
                        <option value="paused">Paused</option>
                        <option value="resolved">Resolved</option>
                        <option value="archived">Archive</option>
                      </select>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
