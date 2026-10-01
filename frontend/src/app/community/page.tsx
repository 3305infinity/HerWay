'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ExternalLink, Plus, Search, Shield, Sparkles } from 'lucide-react';
import { cleanText } from '@/lib/utils';
import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/States';
import { apiGet, apiPost } from '@/lib/api';
import type { CaseRecord } from '@/lib/types';

interface CommunityPost {
  _id: string;
  Name?: string;
  Location?: string;
  'Severity of domestic violence'?: string;
  'Nature of domestic violence'?: string;
  'Frequency of domestic violence'?: string;
  'Relationship with perpetrator'?: string;
  'Culprit details'?: string;
  'Other info'?: string;
  status?: string;
  createdAt?: string;
}

export default function CommunityPage() {
  const router = useRouter();
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSeverity, setSelectedSeverity] = useState<string>('all');
  const [creatingCaseForId, setCreatingCaseForId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [caseError, setCaseError] = useState<string | null>(null);

  const loadPosts = React.useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);

    const result = await apiGet<CommunityPost[]>('/api/getPosts');
    if (result.ok && Array.isArray(result.data)) {
      setPosts(result.data);
    } else {
      // A failed fetch must not look like an empty community.
      setLoadError(
        result.ok ? 'The community feed came back in an unexpected form.' : result.error.message,
      );
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    void loadPosts();
  }, [loadPosts]);

  const handleCreateCaseFromPost = async (post: CommunityPost) => {
    setCreatingCaseForId(post._id);
    setCaseError(null);

    const situationSummary = [
      post['Nature of domestic violence'] ? `Situation: ${cleanText(post['Nature of domestic violence'])}` : '',
      post['Severity of domestic violence'] ? `Severity: ${cleanText(post['Severity of domestic violence'])}` : '',
      post['Other info'] ? `Details: ${cleanText(post['Other info'])}` : '',
    ]
      .filter(Boolean)
      .join('. ');

    const text = situationSummary || 'Seeking guidance based on a shared community experience.';

    // Routed through the Next proxy. The old relative call had no matching
    // route, so this button 404'd and dropped the user on the homepage with
    // nothing carried over.
    const result = await apiPost<CaseRecord>('/api/v2/cases', {
      situation_text: text,
      category: 'domestic_violence',
      location: post.Location ? { display_name: cleanText(post.Location) } : null,
      title: `Started from a community post`,
    });

    if (result.ok) {
      router.push(`/cases/${result.data.id}`);
      return;
    }

    // Fall back to the intake form with the text preserved — the homepage
    // now actually reads this parameter.
    setCaseError(`${result.error.message} Taking you to the start page with your text kept.`);
    setCreatingCaseForId(null);
    router.push(`/?starter=${encodeURIComponent(text)}`);
  };

  const filteredPosts = posts.filter((p) => {
    const textToMatch = [
      p.Name,
      p.Location,
      p['Nature of domestic violence'],
      p['Other info'],
      p['Severity of domestic violence'],
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();

    const matchesSearch = !searchQuery.trim() || textToMatch.includes(searchQuery.toLowerCase().trim());

    const severity = (p['Severity of domestic violence'] || '').toLowerCase();
    const matchesSeverity =
      selectedSeverity === 'all' ||
      (selectedSeverity === 'high' && (severity.includes('high') || severity.includes('very high'))) ||
      (selectedSeverity === 'medium' && severity.includes('medium')) ||
      (selectedSeverity === 'low' && severity.includes('low'));

    return matchesSearch && matchesSeverity;
  });

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-background flex flex-col">
      {/* ── Emergency Help Strip ── */}
      <div className="bg-rose-900/10 border-b border-rose-500/20 px-4 py-2">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-rose-800 dark:text-rose-300">
          <span className="flex items-center gap-1.5 font-medium">
            <Shield size={14} /> In immediate danger? Official 24/7 helplines:
          </span>
          <div className="flex items-center gap-4 font-mono font-medium">
            <a href="tel:112" className="hover:underline">112 (Police & Emergency)</a>
            <a href="tel:181" className="hover:underline">181 (Women in Distress)</a>
            <a href="tel:1091" className="hover:underline">1091 (Women Helpline)</a>
          </div>
        </div>
      </div>

      {/* ── Hero / Header ── */}
      <div className="border-b border-border bg-muted/15 py-10 px-4 sm:px-6">
        <div className="max-w-5xl mx-auto space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <span className="text-xs uppercase tracking-wider font-semibold text-primary">
                Safe Community Space
              </span>
              <h1 className="font-serif text-3xl sm:text-4xl text-foreground font-normal tracking-tight">
                Anonymous Shared Experiences
              </h1>
              <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
                You are not alone. Read experiences shared anonymously by women navigating difficult situations.
                All identifiers are protected. You can also share your story or launch a private safety case.
              </p>
            </div>

            <div className="flex items-center gap-3 shrink-0">
              <Link
                href="/create-post"
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary text-primary-foreground text-sm font-medium rounded-xl hover:bg-primary/90 transition-colors shadow-sm"
              >
                <Plus size={16} />
                <span>Share Anonymously</span>
              </Link>
            </div>
          </div>

          {/* Quick links banner */}
          <div className="flex flex-wrap items-center gap-3 pt-2 text-xs text-muted-foreground">
            <span>Looking for immediate support?</span>
            <Link href="/therapybot" className="text-primary hover:underline font-medium inline-flex items-center gap-1">
              💜 Talk to Niva
            </Link>
            <span aria-hidden="true">·</span>
            <Link href="/lawbot" className="text-primary hover:underline font-medium inline-flex items-center gap-1">
              ⚖️ Consult LawBot
            </Link>
            <span aria-hidden="true">·</span>
            <Link href="/cases" className="text-primary hover:underline font-medium inline-flex items-center gap-1">
              📂 My Safety Cases
            </Link>
          </div>
        </div>
      </div>

      {/* ── Filters & Search ── */}
      <div className="border-b border-border px-4 sm:px-6 py-4 bg-card/60 backdrop-blur">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="relative w-full sm:w-80">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search experiences, keywords..."
              className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-input bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary"
            />
          </div>

          <div className="flex items-center gap-2 overflow-x-auto w-full sm:w-auto">
            <span className="text-xs text-muted-foreground whitespace-nowrap">Filter:</span>
            {[
              { id: 'all', label: 'All Posts' },
              { id: 'high', label: 'High Severity' },
              { id: 'medium', label: 'Medium Severity' },
              { id: 'low', label: 'Low Severity' },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSelectedSeverity(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                  selectedSeverity === tab.id
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted/60 text-muted-foreground hover:text-foreground hover:bg-muted'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Community Posts Grid ── */}
      <div className="max-w-5xl mx-auto w-full p-4 sm:p-6 flex-1">
        {caseError && (
          <div className="mb-4">
            <InlineError message={caseError} onDismiss={() => setCaseError(null)} />
          </div>
        )}

        {isLoading ? (
          <LoadingState label="Loading shared experiences" rows={4} />
        ) : loadError ? (
          <ErrorState
            title="We could not load the community feed"
            message={loadError}
            onRetry={() => void loadPosts()}
          />
        ) : filteredPosts.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredPosts.map((post) => {
              const severity = cleanText(post['Severity of domestic violence'] || '');
              const isHigh = severity.toLowerCase().includes('high');
              const isMedium = severity.toLowerCase().includes('medium');

              return (
                <div
                  key={post._id}
                  className="rounded-2xl border border-border bg-card p-5 flex flex-col justify-between gap-4 hover:border-primary/50 transition-all shadow-sm group"
                >
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="space-y-0.5">
                        <span className="text-xs font-medium text-foreground">
                          {post.Name ? cleanText(post.Name) : 'Anonymous Sister'}
                        </span>
                        {post.Location && (
                          <p className="text-[11px] text-muted-foreground">
                            📍 {cleanText(post.Location)}
                          </p>
                        )}
                      </div>

                      {severity && (
                        <span
                          className={`text-[11px] font-semibold px-2 py-0.5 rounded-full capitalize ${
                            isHigh
                              ? 'bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300'
                              : isMedium
                              ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300'
                              : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300'
                          }`}
                        >
                          {severity}
                        </span>
                      )}
                    </div>

                    {post['Nature of domestic violence'] && (
                      <p className="text-xs font-medium text-foreground/90 line-clamp-2">
                        {cleanText(post['Nature of domestic violence'])}
                      </p>
                    )}

                    {post['Other info'] && (
                      <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
                        {cleanText(post['Other info'])}
                      </p>
                    )}
                  </div>

                  <div className="pt-3 border-t border-border/60 flex items-center justify-between gap-2 flex-wrap text-xs">
                    <Link
                      href={`/post/${post._id}`}
                      className="text-primary hover:underline font-medium inline-flex items-center gap-1"
                    >
                      <span>Read full post</span>
                      <ExternalLink size={12} />
                    </Link>

                    <button
                      type="button"
                      disabled={creatingCaseForId === post._id}
                      onClick={() => handleCreateCaseFromPost(post)}
                      className="px-3 py-1.5 rounded-lg border border-primary/30 text-primary hover:bg-primary/10 transition-colors inline-flex items-center gap-1.5 font-medium disabled:opacity-50"
                      title="Create a personal guided case based on this situation"
                    >
                      <Sparkles size={12} />
                      <span>
                        {creatingCaseForId === post._id ? 'Creating case…' : 'Start case from this'}
                      </span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            title={
              searchQuery || selectedSeverity !== 'all'
                ? 'No posts matched your filters'
                : 'No experiences shared yet'
            }
            message={
              searchQuery || selectedSeverity !== 'all'
                ? 'Try different words, or clear the filters to see everything.'
                : 'Be the first to share an anonymous experience and help other women.'
            }
          >
            <div className="flex items-center justify-center gap-2 flex-wrap">
              {(searchQuery || selectedSeverity !== 'all') && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('');
                    setSelectedSeverity('all');
                  }}
                  className="inline-flex items-center gap-2 px-4 py-2 border border-border text-foreground text-xs font-medium rounded-xl hover:bg-muted transition-colors"
                >
                  Clear filters
                </button>
              )}
              <Link
                href="/create-post"
                className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground text-xs font-medium rounded-xl hover:bg-primary/90 transition-colors"
              >
                <Plus size={14} />
                <span>Share anonymously</span>
              </Link>
            </div>
          </EmptyState>
        )}
      </div>
    </div>
  );
}
