'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useUser } from '@clerk/nextjs';

interface CaseItem {
  id: string;
  _id?: string;
  title: string;
  category: string;
  status: string;
  situation_text: string;
  updated_at: string;
  created_at: string;
  action_plan?: {
    actions?: Array<{ title: string; completed?: boolean }>;
    immediate_actions?: Array<{ title: string; completed?: boolean }>;
  };
}

const STATUS_STYLES: Record<string, string> = {
  active: 'text-emerald-700 bg-emerald-50 dark:bg-emerald-900/30 dark:text-emerald-400',
  paused: 'text-amber-700 bg-amber-50 dark:bg-amber-900/30 dark:text-amber-400',
  resolved: 'text-blue-700 bg-blue-50 dark:bg-blue-900/30 dark:text-blue-400',
  archived: 'text-muted-foreground bg-muted',
};

function formatCategory(cat: string) {
  return cat
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (l) => l.toUpperCase());
}

function timeAgo(dateStr: string) {
  const date = new Date(dateStr);
  const diff = Date.now() - date.getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export default function MyCasesPage() {
  const { user, isLoaded } = useUser();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<string>('all');

  useEffect(() => {
    async function fetchCases() {
      try {
        const userId = user?.id || 'anonymous';
        const res = await fetch(`${API_BASE}/api/v2/cases?user_id=${userId}`);
        if (res.ok) setCases(await res.json());
      } catch (err) {
        console.error('Failed to fetch cases:', err);
      } finally {
        setLoading(false);
      }
    }
    if (isLoaded) fetchCases();
  }, [user, isLoaded]);

  const updateStatus = async (caseId: string, newStatus: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v2/cases/${caseId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      if (res.ok) {
        setCases((prev) =>
          prev.map((c) => ((c.id || c._id) === caseId ? { ...c, status: newStatus } : c))
        );
      }
    } catch (err) {
      console.error('Failed to update status:', err);
    }
  };

  const TABS = ['all', 'active', 'paused', 'resolved', 'archived'] as const;
  const filteredCases = cases.filter((c) => {
    if (activeTab === 'all') return c.status !== 'archived';
    return c.status === activeTab;
  });

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-background">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">

        {/* Page header */}
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-2 border-b border-border">
          <div>
            <h1 className="text-2xl sm:text-3xl font-semibold text-foreground">My Cases</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Your ongoing situations, action plans, and resources.
            </p>
          </div>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors self-start sm:self-auto"
          >
            + New case
          </Link>
        </div>

        {/* Filter tabs */}
        <div
          className="flex items-center gap-1 border-b border-border"
          role="tablist"
          aria-label="Filter cases by status"
        >
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              suppressHydrationWarning
              role="tab"
              aria-selected={activeTab === tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px ${
                activeTab === tab
                  ? 'border-primary text-primary font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab}
              {tab === 'all' && cases.filter((c) => c.status !== 'archived').length > 0 && (
                <span className="ml-1.5 text-xs text-muted-foreground">
                  ({cases.filter((c) => c.status !== 'archived').length})
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Cases list */}
        {loading ? (
          <div className="space-y-3" aria-busy="true" aria-label="Loading cases">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 bg-muted/50 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : filteredCases.length === 0 ? (
          <div className="text-center py-16 space-y-4">
            <p className="text-muted-foreground">
              {cases.length === 0
                ? "You don't have any saved cases yet."
                : `No ${activeTab} cases found.`}
            </p>
            {cases.length === 0 ? (
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
              >
                Start with HerWay →
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => setActiveTab('all')}
                className="inline-flex items-center gap-1.5 px-4 py-2 border border-border text-foreground text-sm font-medium rounded-lg hover:bg-muted transition-colors"
              >
                View all cases
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {filteredCases.map((c) => {
              const cid = c.id || c._id || '';
              const allActions = c.action_plan?.actions || c.action_plan?.immediate_actions || [];
              const completedCount = allActions.filter((a) => a.completed).length;
              const totalActions = allActions.length;
              const progress = totalActions > 0 ? (completedCount / totalActions) * 100 : 0;

              return (
                <div
                  key={cid}
                  className="bg-card border border-border rounded-xl p-5 hover:border-border/80 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start justify-between gap-4">
                    {/* Main content */}
                    <div className="flex-1 min-w-0 space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
                          {formatCategory(c.category || 'Dispute')}
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
                        {c.title || 'Untitled case'}
                      </h2>

                      <p className="text-sm text-muted-foreground line-clamp-1 leading-relaxed">
                        {c.situation_text}
                      </p>

                      {/* Progress */}
                      {totalActions > 0 && (
                        <div className="flex items-center gap-3">
                          <div className="haven-progress-bar flex-1 max-w-32">
                            <div className="haven-progress-fill" style={{ width: `${progress}%` }} />
                          </div>
                          <span className="text-xs text-muted-foreground shrink-0">
                            {completedCount} of {totalActions} steps done
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex flex-col items-end gap-2 shrink-0">
                      <Link
                        href={`/cases/${cid}`}
                        className="px-3.5 py-1.5 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors whitespace-nowrap"
                      >
                        Open →
                      </Link>
                      <select
                        value={c.status || 'active'}
                        onChange={(e) => updateStatus(cid, e.target.value)}
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
