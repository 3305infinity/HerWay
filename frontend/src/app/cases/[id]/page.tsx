'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';

import ResearchTrailDrawer from '@/components/ResearchTrailDrawer';
import EvidenceCard from '@/components/EvidenceCard';
import ResourceCard from '@/components/ResourceCard';
import LocationPrompt from '@/components/LocationPrompt';
import {
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  PartialResultNotice,
} from '@/components/States';
import { apiGet, apiPatch, apiPost, type ApiError } from '@/lib/api';
import { formatIndianDateTime } from '@/lib/india';
import type {
  CaseRecord,
  ChatReply,
  MatchedResource,
  SafetyActionItem,
} from '@/lib/types';

const WOMEN_SAFETY_CATEGORIES = [
  'domestic_violence',
  'sexual_harassment',
  'stalking',
  'online_harassment',
  'threats',
  'coercive_control',
  'unsafe_relationship',
  'workplace_harassment',
  'other_women_safety',
  'safety',
];

const PHASES = [
  {
    key: 'right_now_actions',
    label: 'Right now',
    description: 'Do these first — before anything else.',
    color: 'text-red-700 dark:text-red-400',
    dotColor: 'bg-red-500',
  },
  {
    key: 'next_24h_actions',
    label: 'Next 24 hours',
    description: 'Safe practical steps when you have a moment.',
    color: 'text-amber-700 dark:text-amber-400',
    dotColor: 'bg-amber-500',
  },
  {
    key: 'document_safe_actions',
    label: 'If safe to document',
    description: 'Only if you can do this privately and safely.',
    color: 'text-blue-700 dark:text-blue-400',
    dotColor: 'bg-blue-500',
  },
  {
    key: 'support_network_actions',
    label: 'Support network',
    description: 'People and organisations who can help.',
    color: 'text-purple-700 dark:text-purple-400',
    dotColor: 'bg-purple-500',
  },
  {
    key: 'formal_options_actions',
    label: 'Formal and legal options',
    description: 'For when you are ready. These are options, not obligations.',
    color: 'text-emerald-700 dark:text-emerald-400',
    dotColor: 'bg-emerald-500',
  },
  {
    key: 'ongoing_actions',
    label: 'Ongoing',
    description: 'Things to revisit over time.',
    color: 'text-muted-foreground',
    dotColor: 'bg-muted-foreground/50',
  },
] as const;

type TabId = 'plan' | 'evidence' | 'resources' | 'community';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  failed?: boolean;
}

export default function CaseWorkspacePage() {
  const params = useParams();
  const router = useRouter();
  const caseId = params?.id as string;

  const [caseData, setCaseData] = useState<CaseRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<ApiError | null>(null);

  const [isTrailOpen, setIsTrailOpen] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const [activeTab, setActiveTab] = useState<TabId>('plan');

  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchingResources, setIsSearchingResources] = useState(false);
  const [resourceNotice, setResourceNotice] = useState<string | null>(null);
  const [resourceError, setResourceError] = useState<string | null>(null);
  const [showHistoryModal, setShowHistoryModal] = useState(false);

  const [communityPosts, setCommunityPosts] = useState<Array<Record<string, unknown>>>([]);
  const [isLoadingCommunity, setIsLoadingCommunity] = useState(false);
  const [communityLoaded, setCommunityLoaded] = useState(false);
  const [communityError, setCommunityError] = useState<string | null>(null);

  const [isRetryingResearch, setIsRetryingResearch] = useState(false);
  const [researchError, setResearchError] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  const [showLocationPrompt, setShowLocationPrompt] = useState(false);

  // ── Load ────────────────────────────────────────────────────
  const loadCase = useCallback(async () => {
    if (!caseId) return;
    setLoading(true);
    setLoadError(null);

    const result = await apiGet<CaseRecord>(`/api/v2/cases/${caseId}`);
    if (result.ok) {
      setCaseData(result.data);
      if (result.data.conversation?.length) {
        setChatHistory(
          result.data.conversation.map((m) => ({
            role: m.role === 'user' ? 'user' : 'assistant',
            content: m.content,
          })),
        );
      }
    } else {
      setLoadError(result.error);
    }
    setLoading(false);
  }, [caseId]);

  useEffect(() => {
    void loadCase();
  }, [loadCase]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, isChatLoading]);

  // ── Actions ─────────────────────────────────────────────────
  const toggleAction = async (actionId: string, nextStatus: string) => {
    if (!caseData) return;
    setActionError(null);

    const snapshot = caseData;
    const updateList = (list?: SafetyActionItem[]) =>
      (list ?? []).map((a) =>
        a.id === actionId
          ? {
              ...a,
              status: nextStatus,
              completed_at: nextStatus === 'completed' ? new Date().toISOString() : null,
            }
          : a,
      );

    // Optimistic update, reverted if the server rejects it.
    if (caseData.safety_plan) {
      const plan = caseData.safety_plan;
      setCaseData({
        ...caseData,
        safety_plan: {
          ...plan,
          actions: updateList(plan.actions),
          right_now_actions: updateList(plan.right_now_actions),
          next_24h_actions: updateList(plan.next_24h_actions),
          document_safe_actions: updateList(plan.document_safe_actions),
          support_network_actions: updateList(plan.support_network_actions),
          formal_options_actions: updateList(plan.formal_options_actions),
          ongoing_actions: updateList(plan.ongoing_actions),
        },
      });
    } else if (caseData.action_plan) {
      setCaseData({
        ...caseData,
        action_plan: {
          ...caseData.action_plan,
          actions: (caseData.action_plan.actions ?? []).map((a) =>
            a.id === actionId
              ? { ...a, status: nextStatus, completed: nextStatus === 'completed' }
              : a,
          ),
        },
      });
    }

    const result = await apiPatch(`/api/v2/cases/${caseId}/actions/${actionId}`, {
      status: nextStatus,
    });

    if (!result.ok) {
      // Never leave a tick on screen that was not saved.
      setCaseData(snapshot);
      setActionError(`${result.error.message} Your step was not saved.`);
    }
  };

  const retryResearch = async () => {
    setIsRetryingResearch(true);
    setResearchError(null);

    const result = await apiPost(`/api/v2/research/${caseId}/run`, undefined, 180_000);
    if (result.ok) {
      await loadCase();
    } else {
      setResearchError(result.error.message);
    }
    setIsRetryingResearch(false);
  };

  const handleSearchMoreResources = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = searchQuery.trim();
    if (!query) return;

    const location = caseData?.situation?.location || caseData?.location_context || '';
    if (!location) {
      setShowLocationPrompt(true);
      return;
    }

    setIsSearchingResources(true);
    setResourceError(null);
    setResourceNotice(null);

    const result = await apiPost<{ message: string; new_resources_added: number }>(
      `/api/v2/cases/${caseId}/safety-plan/research-more`,
      { query, location, vertical: 'maps' },
    );

    if (result.ok) {
      setSearchQuery('');
      setResourceNotice(result.data.message);
      if (result.data.new_resources_added > 0) await loadCase();
    } else {
      setResourceError(result.error.message);
    }
    setIsSearchingResources(false);
  };

  const saveLocation = async (location: string) => {
    const result = await apiPatch(`/api/v2/cases/${caseId}`, { location_context: location });
    if (result.ok) {
      setShowLocationPrompt(false);
      await loadCase();
    } else {
      setResourceError(result.error.message);
    }
  };

  const sendChat = async (e?: React.FormEvent, customMsg?: string) => {
    if (e) e.preventDefault();
    const userMsg = (customMsg ?? chatMessage).trim();
    if (!userMsg || isChatLoading) return;

    setChatMessage('');
    setChatError(null);
    setChatHistory((prev) => [...prev, { role: 'user', content: userMsg }]);
    setIsChatLoading(true);

    const result = await apiPost<ChatReply>('/api/v2/chat', {
      case_id: caseId,
      message: userMsg,
      history: chatHistory.filter((m) => !m.failed).slice(-12),
    });

    if (result.ok) {
      setChatHistory((prev) => [...prev, { role: 'assistant', content: result.data.reply }]);
      if (result.data.community_posts?.length) {
        setCommunityPosts(result.data.community_posts);
        setCommunityLoaded(true);
      }
      if (result.data.plan_adapted) await loadCase();
    } else {
      // Say the message failed. Do not invent a reply.
      setChatError(result.error.message);
      setChatHistory((prev) => [
        ...prev,
        {
          role: 'assistant',
          content:
            'I could not answer that just now. Nothing you wrote has been lost. ' +
            'If this is urgent, call 112, or 181 for the women helpline.',
          failed: true,
        },
      ]);
    }
    setIsChatLoading(false);
  };

  const loadCommunityPosts = useCallback(async () => {
    if (communityLoaded || !caseData) return;
    setIsLoadingCommunity(true);
    setCommunityError(null);

    const query = caseData.situation?.case_summary || caseData.situation_text || '';
    const result = await apiPost<ChatReply>('/api/v2/chat', {
      case_id: caseId,
      message: `Find similar community posts for: ${query.slice(0, 200)}`,
      history: [],
    });

    if (result.ok) {
      setCommunityPosts(result.data.community_posts ?? []);
    } else {
      setCommunityError(result.error.message);
    }
    setIsLoadingCommunity(false);
    setCommunityLoaded(true);
  }, [caseId, caseData, communityLoaded]);

  useEffect(() => {
    if (activeTab === 'community' && !communityLoaded && caseData) {
      void loadCommunityPosts();
    }
  }, [activeTab, communityLoaded, caseData, loadCommunityPosts]);

  // ── Loading / error ─────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] max-w-3xl mx-auto w-full p-6 space-y-4">
        <p className="text-sm text-muted-foreground">Loading your case…</p>
        <LoadingState label="Loading your case" rows={4} />
      </div>
    );
  }

  if (!caseData) {
    const is403 = loadError?.status === 403;
    const is404 = loadError?.status === 404;
    return (
      <div className="min-h-[calc(100vh-3.5rem)] flex items-center justify-center p-6">
        <div className="max-w-md w-full">
          <ErrorState
            title={
              is403
                ? 'This case is not yours to open'
                : is404
                ? 'We could not find that case'
                : 'That case did not load'
            }
            message={
              is403
                ? 'This case belongs to a different account or browser session. If you created it while signed in, sign in with that account.'
                : is404
                ? 'It may have been archived, or the link may be incomplete.'
                : (loadError?.message ?? 'Please check your connection and try again.')
            }
            onRetry={loadError?.retryable ? () => void loadCase() : undefined}
          >
            <button
              type="button"
              onClick={() => router.push('/cases')}
              className="px-4 py-2 rounded-lg border border-border text-foreground text-sm font-medium hover:bg-muted transition-colors"
            >
              Back to my cases
            </button>
          </ErrorState>
        </div>
      </div>
    );
  }

  // ── Derived ─────────────────────────────────────────────────
  const category = (caseData.category || '').toLowerCase();
  const isSafetyMode =
    WOMEN_SAFETY_CATEGORIES.some((c) => category.includes(c)) || !!caseData.safety_plan;
  const situation = caseData.situation;
  const evidenceList = caseData.evidence ?? [];
  const actionPlan = caseData.action_plan;
  const safetyPlan = caseData.safety_plan;
  const trace = caseData.research_trace ?? [];
  const degradations = caseData.research_degradations ?? [];
  const assessment = safetyPlan?.assessment;

  const localAsMatched: MatchedResource[] = (caseData.local_resources ?? []).map((r, i) => ({
    id: r.id ?? `local_${i}`,
    name: r.name,
    category: r.type ?? 'support',
    phone: r.phone,
    address: r.address,
    url: r.website,
    operating_hours: r.hours,
    rating: r.rating,
    verification: r.verification,
    verification_note: r.verification_note,
    notes: r.relevance_reason,
    source_domain: r.source_domain,
    retrieved_at: r.retrieved_at,
  }));
  const allResources: MatchedResource[] =
    safetyPlan?.matched_resources?.length ? safetyPlan.matched_resources : localAsMatched;

  const totalSafetyActions = safetyPlan?.actions?.length ?? 0;
  const completedSafetyActions =
    safetyPlan?.actions?.filter((a) => a.status === 'completed').length ?? 0;
  const totalStdActions = actionPlan?.actions?.length ?? 0;
  const completedStdActions =
    actionPlan?.actions?.filter((a) => a.completed).length ?? 0;

  const hasNoResearch = trace.length === 0 && evidenceList.length === 0;
  const knownLocation = situation?.location || caseData.location_context || null;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {isSafetyMode && (
        <div className="bg-red-700 dark:bg-red-900 text-white px-4 py-2.5">
          <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs">
            <span className="font-medium">In danger right now?</span>
            <div className="flex items-center gap-4 font-mono font-semibold flex-wrap">
              <a href="tel:112" className="hover:underline">112 Emergency</a>
              <a href="tel:181" className="hover:underline">181 Women Helpline</a>
              <a href="tel:1091" className="hover:underline">1091 Women Police</a>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <header className="border-b border-border bg-background px-4 sm:px-6 py-4 sticky top-14 z-40">
        <div className="max-w-5xl mx-auto flex items-start sm:items-center justify-between gap-4 flex-wrap">
          <div className="space-y-0.5 min-w-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
              <button
                onClick={() => router.push('/cases')}
                className="hover:text-foreground transition-colors"
              >
                My cases
              </button>
              <span aria-hidden="true">/</span>
              <span className="capitalize">
                {(caseData.category || 'case').replace(/_/g, ' ')}
              </span>
              {caseData.updated_at && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>Updated {formatIndianDateTime(caseData.updated_at)}</span>
                </>
              )}
            </div>
            <h1 className="text-lg sm:text-xl font-semibold text-foreground leading-tight">
              {caseData.title || 'Case workspace'}
            </h1>
          </div>

          <div className="flex items-center gap-2 shrink-0 flex-wrap">
            {(safetyPlan?.updates_history?.length ?? 0) > 0 && (
              <button
                onClick={() => setShowHistoryModal(true)}
                className="px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
              >
                Plan updated ({safetyPlan!.updates_history!.length})
              </button>
            )}
            {isSafetyMode && (
              <Link
                href={`/therapybot?case_id=${caseId}`}
                className="px-3 py-1.5 text-xs font-medium text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-700 rounded-lg hover:bg-purple-100 dark:hover:bg-purple-900/40 transition-colors whitespace-nowrap"
              >
                Talk to Niva
              </Link>
            )}
            <Link
              href={`/lawbot?case_id=${caseId}`}
              className="px-3 py-1.5 text-xs font-medium text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors whitespace-nowrap"
            >
              Legal help
            </Link>
            <Link
              href="/discreet-message"
              className="px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors whitespace-nowrap hidden sm:inline-flex"
            >
              Discreet message
            </Link>
            <button
              onClick={() => setIsTrailOpen(true)}
              className="px-3 py-1.5 text-xs text-muted-foreground bg-muted/50 hover:bg-muted border border-border rounded-lg transition-colors"
            >
              How we researched this
            </button>
            <button
              onClick={() => setIsChatOpen(true)}
              className="px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              Ask HerWay
            </button>
          </div>
        </div>
      </header>

      <div className="flex-1 max-w-5xl mx-auto w-full px-4 sm:px-6 py-6 sm:py-8">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-8">
          <div className="space-y-6 min-w-0">
            {/* Honest reporting of incomplete research */}
            {degradations.length > 0 && (
              <PartialResultNotice
                messages={degradations.map((d) => d.user_message)}
                onRetry={isRetryingResearch ? undefined : () => void retryResearch()}
              />
            )}

            {researchError && (
              <InlineError message={researchError} onDismiss={() => setResearchError(null)} />
            )}
            {actionError && (
              <InlineError message={actionError} onDismiss={() => setActionError(null)} />
            )}

            {hasNoResearch && (
              <EmptyState
                title="No research has been run on this case yet"
                message="HerWay has not yet searched for verified resources or built a plan for this situation."
              >
                <button
                  type="button"
                  onClick={() => void retryResearch()}
                  disabled={isRetryingResearch}
                  className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  {isRetryingResearch ? 'Researching…' : 'Run research now'}
                </button>
              </EmptyState>
            )}

            {/* Situation */}
            <div className="space-y-2">
              <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Situation
              </h2>
              <p className="text-sm text-foreground leading-relaxed">
                {situation?.case_summary || caseData.situation_text}
              </p>
              {situation?.user_goal && (
                <p className="text-sm text-muted-foreground">
                  <span className="font-medium text-foreground">Goal:</span> {situation.user_goal}
                </p>
              )}
              {!knownLocation && (
                <button
                  type="button"
                  onClick={() => setShowLocationPrompt(true)}
                  className="text-xs text-primary hover:underline font-medium"
                >
                  Add your city or district to find support near you →
                </button>
              )}
            </div>

            {/* Safety assessment */}
            {assessment && isSafetyMode && (
              <details className="border border-border rounded-xl overflow-hidden">
                <summary className="flex items-center justify-between px-5 py-3.5 cursor-pointer hover:bg-muted/30 transition-colors list-none">
                  <div className="flex items-center gap-2.5">
                    <h3 className="text-sm font-medium text-foreground">Safety assessment</h3>
                    <span className="text-xs text-muted-foreground">
                      {[
                        assessment.immediate_safety_concern && 'Immediate concern',
                        assessment.threats_present && 'Threats',
                        assessment.escalating_behavior && 'Escalating',
                      ]
                        .filter(Boolean)
                        .slice(0, 2)
                        .join(' · ') || 'Review indicators'}
                    </span>
                  </div>
                  <span aria-hidden="true" className="text-muted-foreground text-xs">▾</span>
                </summary>
                <div className="px-5 pb-5 pt-3 border-t border-border/50 space-y-3">
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {assessment.context_summary}
                  </p>
                  <div className="space-y-1.5">
                    {(
                      [
                        ['immediate_safety_concern', 'Immediate danger'],
                        ['threats_present', 'Threats present'],
                        ['escalating_behavior', 'Escalating pattern'],
                        ['repeated_harassment', 'Recurring harassment'],
                        ['digital_safety_concern', 'Device or digital risk'],
                        ['financial_dependence', 'Financial control'],
                        ['presence_of_dependents', 'Children or dependents involved'],
                        ['workplace_harassment', 'Workplace or POSH related'],
                        ['safe_place_available', 'Safe place identified'],
                        ['support_available', 'Support network available'],
                      ] as const
                    ).map(([key, label]) => {
                      const active = Boolean(assessment[key]);
                      const positive = key === 'safe_place_available' || key === 'support_available';
                      return (
                        <div key={key} className="flex items-start gap-2.5 text-sm">
                          <span
                            className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                              active
                                ? positive
                                  ? 'bg-emerald-500'
                                  : 'bg-red-500'
                                : 'bg-muted-foreground/20'
                            }`}
                            aria-hidden="true"
                          />
                          <span className={active ? 'text-foreground' : 'text-muted-foreground/60'}>
                            {label}
                            {active && assessment.indicator_justifications?.[key] && (
                              <span className="text-muted-foreground font-normal">
                                {' — '}
                                <em>{assessment.indicator_justifications[key]}</em>
                              </span>
                            )}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {(assessment.critical_safety_notes?.length ?? 0) > 0 && (
                    <div className="pt-2 border-t border-border/50 space-y-1">
                      <p className="text-xs font-medium text-red-700 dark:text-red-400">
                        Important
                      </p>
                      <ul className="space-y-1">
                        {assessment.critical_safety_notes!.map((note, i) => (
                          <li key={i} className="text-sm text-muted-foreground leading-relaxed">
                            {note}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </details>
            )}

            {/* Tabs */}
            <div className="border-b border-border" role="tablist">
              {(
                [
                  {
                    id: 'plan' as const,
                    label: isSafetyMode ? 'Safety plan' : 'Action plan',
                    count: isSafetyMode
                      ? `${completedSafetyActions}/${totalSafetyActions}`
                      : `${completedStdActions}/${totalStdActions}`,
                  },
                  {
                    id: 'evidence' as const,
                    label: 'Sources',
                    count: evidenceList.length ? String(evidenceList.length) : undefined,
                  },
                  {
                    id: 'resources' as const,
                    label: 'Resources',
                    count: allResources.length ? String(allResources.length) : undefined,
                  },
                  {
                    id: 'community' as const,
                    label: 'Community',
                    count: communityPosts.length ? String(communityPosts.length) : undefined,
                  },
                ]
              ).map((tab) => (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors ${
                    activeTab === tab.id
                      ? 'border-primary text-primary font-medium'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {tab.label}
                  {tab.count && (
                    <span className="ml-1.5 text-xs text-muted-foreground">({tab.count})</span>
                  )}
                </button>
              ))}
            </div>

            {/* Plan tab */}
            {activeTab === 'plan' && (
              <div className="space-y-8">
                {safetyPlan ? (
                  <>
                    {PHASES.map((phase) => {
                      const actions = (safetyPlan[phase.key] ?? []) as SafetyActionItem[];
                      if (actions.length === 0) return null;
                      const doneCount = actions.filter((a) => a.status === 'completed').length;
                      return (
                        <div key={phase.key} className="space-y-1">
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2">
                              <span className={`w-2 h-2 rounded-full ${phase.dotColor} shrink-0`} aria-hidden="true" />
                              <h3 className={`text-sm font-semibold ${phase.color}`}>{phase.label}</h3>
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {doneCount}/{actions.length}
                            </span>
                          </div>
                          <p className="text-xs text-muted-foreground mb-3 ml-4">{phase.description}</p>

                          <div className="ml-4 border border-border/60 rounded-xl overflow-hidden divide-y divide-border/60">
                            {actions.map((act) => (
                              <label
                                key={act.id}
                                className={`flex items-start gap-3 px-4 py-3.5 cursor-pointer hover:bg-muted/20 transition-colors ${
                                  act.status === 'completed' ? 'bg-muted/10' : 'bg-card'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={act.status === 'completed'}
                                  onChange={() =>
                                    void toggleAction(
                                      act.id,
                                      act.status === 'completed' ? 'todo' : 'completed',
                                    )
                                  }
                                  className="mt-0.5 w-4 h-4 rounded border-input accent-primary cursor-pointer shrink-0"
                                  aria-label={`Mark "${act.title}" as ${
                                    act.status === 'completed' ? 'not done' : 'done'
                                  }`}
                                />
                                <div className="flex-1 min-w-0 space-y-0.5">
                                  <p
                                    className={`text-sm font-medium leading-snug ${
                                      act.status === 'completed'
                                        ? 'line-through text-muted-foreground'
                                        : 'text-foreground'
                                    }`}
                                  >
                                    {act.title}
                                  </p>
                                  {act.description && (
                                    <p className="text-xs text-muted-foreground leading-relaxed">
                                      {act.description}
                                    </p>
                                  )}
                                  {act.safety_caveat && (
                                    <p className="text-xs text-red-600 dark:text-red-400 font-medium">
                                      {act.safety_caveat}
                                    </p>
                                  )}
                                  {(act.evidence_ids?.length ?? 0) > 0 && (
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.preventDefault();
                                        setActiveTab('evidence');
                                      }}
                                      className="text-[11px] text-primary hover:underline"
                                    >
                                      Why this step? See the source →
                                    </button>
                                  )}
                                </div>
                              </label>
                            ))}
                          </div>
                        </div>
                      );
                    })}

                    {(safetyPlan.things_to_avoid?.length ?? 0) > 0 && (
                      <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 space-y-1.5">
                        <p className="text-xs font-semibold text-red-700 dark:text-red-400">
                          Please avoid
                        </p>
                        <ul className="space-y-1">
                          {safetyPlan.things_to_avoid!.map((t, i) => (
                            <li key={i} className="text-sm text-muted-foreground leading-relaxed">
                              {t}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {safetyPlan.disclaimer && (
                      <p className="text-xs text-muted-foreground leading-relaxed border-t border-border pt-4">
                        {safetyPlan.disclaimer}
                      </p>
                    )}
                  </>
                ) : (actionPlan?.actions?.length ?? 0) > 0 ? (
                  <>
                    <div className="border border-border/60 rounded-xl overflow-hidden divide-y divide-border/60">
                      {actionPlan!.actions!.map((act) => (
                        <label
                          key={act.id}
                          className={`flex items-start gap-3 px-4 py-3.5 cursor-pointer hover:bg-muted/20 transition-colors ${
                            act.completed ? 'bg-muted/10' : 'bg-card'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={Boolean(act.completed)}
                            onChange={() =>
                              void toggleAction(act.id, act.completed ? 'todo' : 'completed')
                            }
                            className="mt-0.5 w-4 h-4 rounded border-input accent-primary cursor-pointer shrink-0"
                            aria-label={`Mark "${act.title}" as ${act.completed ? 'not done' : 'done'}`}
                          />
                          <div className="flex-1 min-w-0 space-y-0.5">
                            <p
                              className={`text-sm font-medium leading-snug ${
                                act.completed ? 'line-through text-muted-foreground' : 'text-foreground'
                              }`}
                            >
                              {act.title}
                            </p>
                            {act.description && (
                              <p className="text-xs text-muted-foreground leading-relaxed">
                                {act.description}
                              </p>
                            )}
                          </div>
                        </label>
                      ))}
                    </div>
                    {actionPlan?.disclaimer && (
                      <p className="text-xs text-muted-foreground leading-relaxed border-t border-border pt-4">
                        {actionPlan.disclaimer}
                      </p>
                    )}
                  </>
                ) : (
                  !hasNoResearch && (
                    <EmptyState
                      title="No plan was produced"
                      message="HerWay researched this case but could not build a step-by-step plan from what it found. The sources it did verify are in the Sources tab."
                    >
                      <button
                        type="button"
                        onClick={() => void retryResearch()}
                        disabled={isRetryingResearch}
                        className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                      >
                        {isRetryingResearch ? 'Researching…' : 'Try research again'}
                      </button>
                    </EmptyState>
                  )
                )}
              </div>
            )}

            {/* Evidence tab */}
            {activeTab === 'evidence' && (
              <div className="space-y-4">
                {evidenceList.length === 0 ? (
                  <EmptyState
                    title="No sources were verified"
                    message="HerWay only shows information it has been able to check against a source. Nothing here was verified, so nothing is shown — rather than filling the gap with guesswork."
                  >
                    <button
                      type="button"
                      onClick={() => void retryResearch()}
                      disabled={isRetryingResearch}
                      className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                      {isRetryingResearch ? 'Researching…' : 'Search again'}
                    </button>
                  </EmptyState>
                ) : (
                  <>
                    <p className="text-xs text-muted-foreground">
                      These are the sources behind the recommendations in your plan. Open any one to
                      check it yourself.
                    </p>
                    <div className="space-y-3">
                      {evidenceList.map((ev, idx) => (
                        <EvidenceCard key={ev.id || idx} evidence={ev} />
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Resources tab */}
            {activeTab === 'resources' && (
              <div className="space-y-4">
                <form onSubmit={handleSearchMoreResources} className="flex gap-2">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search for shelters, legal aid, women police stations…"
                    aria-label="Search for nearby resources"
                    className="flex-1 px-3.5 py-2 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
                  />
                  <button
                    type="submit"
                    disabled={isSearchingResources || !searchQuery.trim()}
                    className="px-4 py-2 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground text-sm font-medium rounded-lg transition-colors shrink-0"
                  >
                    {isSearchingResources ? 'Searching…' : 'Search'}
                  </button>
                </form>

                {knownLocation ? (
                  <p className="text-xs text-muted-foreground">
                    Searching near <span className="font-medium text-foreground">{knownLocation}</span>.{' '}
                    <button
                      type="button"
                      onClick={() => setShowLocationPrompt(true)}
                      className="text-primary hover:underline"
                    >
                      Change
                    </button>
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    HerWay does not know where you are and will not guess.{' '}
                    <button
                      type="button"
                      onClick={() => setShowLocationPrompt(true)}
                      className="text-primary hover:underline font-medium"
                    >
                      Enter your city or district
                    </button>{' '}
                    to find nearby support.
                  </p>
                )}

                {resourceError && (
                  <InlineError message={resourceError} onDismiss={() => setResourceError(null)} />
                )}
                {resourceNotice && (
                  <p className="text-xs text-muted-foreground border border-border rounded-lg px-3 py-2">
                    {resourceNotice}
                  </p>
                )}

                {allResources.length === 0 ? (
                  <EmptyState
                    title="No support services found yet"
                    message={
                      knownLocation
                        ? `We did not find services near ${knownLocation}. The national helplines are always available: 112 for emergencies, 181 for the women helpline.`
                        : 'Add your city or district above and HerWay will look for One Stop Centres, women police stations and legal aid near you.'
                    }
                  />
                ) : (
                  <div className="space-y-3">
                    {allResources.map((res, idx) => (
                      <ResourceCard key={res.id || idx} resource={res} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Community tab */}
            {activeTab === 'community' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div>
                    <h2 className="text-sm font-medium text-foreground">Shared experiences</h2>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Situations others have shared anonymously. Contact details are never shown.
                    </p>
                  </div>
                  <Link href="/community" className="text-xs text-primary hover:underline font-medium shrink-0">
                    Browse all →
                  </Link>
                </div>

                {isLoadingCommunity ? (
                  <LoadingState label="Finding similar experiences" rows={3} />
                ) : communityError ? (
                  <ErrorState
                    message={communityError}
                    onRetry={() => {
                      setCommunityLoaded(false);
                      setCommunityError(null);
                    }}
                  />
                ) : communityPosts.length > 0 ? (
                  <div className="space-y-3">
                    {communityPosts.map((post, idx) => {
                      const id = typeof post._id === 'string' ? post._id : undefined;
                      const name = typeof post.Name === 'string' ? post.Name : 'Anonymous';
                      const loc = typeof post.Location === 'string' ? post.Location : undefined;
                      const info =
                        typeof post['Other info'] === 'string' ? post['Other info'] : undefined;
                      return (
                        <div key={id ?? idx} className="border border-border rounded-xl p-4 space-y-2">
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-xs font-medium text-foreground">{name}</span>
                              {loc && <span className="text-[11px] text-muted-foreground">{loc}</span>}
                            </div>
                            {id && (
                              <Link
                                href={`/post/${id}`}
                                className="text-xs text-primary hover:underline font-medium"
                              >
                                Read post →
                              </Link>
                            )}
                          </div>
                          {info && (
                            <p className="text-xs text-foreground/80 leading-relaxed">{info}</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <EmptyState
                    title="No similar posts found"
                    message="That does not mean no one has been through this. You can share your own experience anonymously to connect with others."
                  >
                    <Link
                      href="/create-post"
                      className="inline-flex px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
                    >
                      Share anonymously →
                    </Link>
                  </EmptyState>
                )}
              </div>
            )}
          </div>

          {/* Sidebar */}
          <aside className="hidden lg:block space-y-6">
            <div className="haven-card space-y-3">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Progress
              </h3>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-foreground">
                    {isSafetyMode ? completedSafetyActions : completedStdActions} steps done
                  </span>
                  <span className="text-muted-foreground">
                    {isSafetyMode ? totalSafetyActions : totalStdActions} total
                  </span>
                </div>
                <div className="haven-progress-bar">
                  <div
                    className="haven-progress-fill"
                    style={{
                      width: `${
                        isSafetyMode
                          ? totalSafetyActions > 0
                            ? (completedSafetyActions / totalSafetyActions) * 100
                            : 0
                          : totalStdActions > 0
                          ? (completedStdActions / totalStdActions) * 100
                          : 0
                      }%`,
                    }}
                  />
                </div>
              </div>
            </div>

            <div className="haven-card space-y-3">
              <h3 className="text-sm font-medium text-foreground">Ask HerWay</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                If anything changes, tell HerWay and your plan can be updated.
              </p>
              <button
                onClick={() => setIsChatOpen(true)}
                className="w-full py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium rounded-lg transition-colors"
              >
                Ask a question
              </button>
            </div>

            {trace.length > 0 && (
              <button
                onClick={() => setIsTrailOpen(true)}
                className="w-full text-left haven-card hover:border-border/80 transition-colors space-y-1"
              >
                <h3 className="text-sm font-medium text-foreground">How we researched this</h3>
                <p className="text-xs text-muted-foreground">
                  {trace.length} search{trace.length !== 1 ? 'es' : ''} · {evidenceList.length} source
                  {evidenceList.length !== 1 ? 's' : ''} verified
                </p>
                <p className="text-xs text-primary font-medium">View research trail →</p>
              </button>
            )}
          </aside>
        </div>
      </div>

      {/* Ask HerWay drawer */}
      {isChatOpen && (
        <div
          className="fixed inset-y-0 right-0 w-full sm:w-[420px] bg-background border-l border-border shadow-2xl z-50 flex flex-col"
          role="dialog"
          aria-modal="true"
          aria-label="Ask HerWay"
        >
          <div className="p-4 border-b border-border flex items-center justify-between">
            <div className="space-y-0.5">
              <h3 className="text-sm font-semibold text-foreground">Ask HerWay</h3>
              <p className="text-xs text-muted-foreground">
                Tell HerWay what has changed and your plan can be updated.
              </p>
            </div>
            <button
              onClick={() => setIsChatOpen(false)}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 p-4 overflow-y-auto custom-scrollbar space-y-3">
            {chatHistory.length === 0 && (
              <div className="p-4 bg-muted/30 rounded-xl space-y-3">
                <p className="text-xs font-semibold text-foreground">You could ask:</p>
                <div className="grid grid-cols-1 gap-2">
                  {[
                    'What should I do first?',
                    'Why are you recommending this?',
                    'What if that does not work?',
                    'Find support near me.',
                    'Is this information current?',
                    'Help me write a complaint for the police.',
                  ].map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => void sendChat(undefined, q)}
                      className="text-left p-2.5 rounded-lg border border-border bg-card hover:border-primary/40 text-xs text-foreground transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {chatHistory.map((msg, idx) => (
              <div
                key={idx}
                className={`max-w-[85%] px-4 py-3 rounded-xl text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground ml-auto'
                    : msg.failed
                    ? 'bg-rose-500/10 border border-rose-500/30 text-foreground mr-auto'
                    : 'bg-muted text-foreground mr-auto border border-border'
                }`}
              >
                {msg.content}
              </div>
            ))}

            {isChatLoading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="w-4 h-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" aria-hidden="true" />
                HerWay is working on that…
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {chatError && (
            <div className="px-4 pb-2">
              <InlineError message={chatError} onDismiss={() => setChatError(null)} />
            </div>
          )}

          <form onSubmit={sendChat} className="p-4 border-t border-border flex gap-2">
            <input
              type="text"
              value={chatMessage}
              onChange={(e) => setChatMessage(e.target.value)}
              placeholder="Ask a question, or say what has changed…"
              aria-label="Message to HerWay"
              className="flex-1 px-3.5 py-2.5 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
            />
            <button
              type="submit"
              disabled={isChatLoading || !chatMessage.trim()}
              className="px-4 py-2.5 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground text-sm font-medium rounded-lg transition-colors shrink-0"
            >
              Send
            </button>
          </form>
        </div>
      )}

      {/* Plan history */}
      {showHistoryModal && safetyPlan?.updates_history && (
        <div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Plan update history"
        >
          <div className="bg-card border border-border rounded-xl max-w-lg w-full shadow-2xl flex flex-col max-h-[80vh]">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <h3 className="text-base font-semibold text-foreground">Why your plan changed</h3>
              <button
                onClick={() => setShowHistoryModal(false)}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <div className="overflow-y-auto custom-scrollbar p-5 space-y-4">
              {safetyPlan.updates_history.map((upd, idx) => (
                <div key={upd.update_id || idx} className="space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-foreground">{upd.why_plan_changed}</p>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {formatIndianDateTime(upd.timestamp)}
                    </span>
                  </div>
                  {(upd.what_changed?.length ?? 0) > 0 && (
                    <ul className="space-y-1">
                      {upd.what_changed!.map((c, i) => (
                        <li key={i} className="text-xs text-muted-foreground flex items-start gap-2">
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-muted-foreground/40 shrink-0" aria-hidden="true" />
                          {c}
                        </li>
                      ))}
                    </ul>
                  )}
                  {(upd.new_recommended_steps?.length ?? 0) > 0 && (
                    <div className="pl-3 border-l-2 border-primary/30 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">New steps added:</p>
                      {upd.new_recommended_steps!.map((s, i) => (
                        <p key={i} className="text-xs text-foreground">{s}</p>
                      ))}
                    </div>
                  )}
                  {idx < safetyPlan.updates_history!.length - 1 && (
                    <hr className="border-border/50 mt-3" />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <LocationPrompt
        isOpen={showLocationPrompt}
        currentLocation={knownLocation}
        onClose={() => setShowLocationPrompt(false)}
        onSave={saveLocation}
      />

      <ResearchTrailDrawer
        isOpen={isTrailOpen}
        onClose={() => setIsTrailOpen(false)}
        trace={trace}
        evidenceCount={evidenceList.length}
        degradations={degradations}
        locationUsed={caseData.research_location_used ?? knownLocation}
        hasPlan={Boolean(safetyPlan) || (actionPlan?.actions?.length ?? 0) > 0}
      />
    </div>
  );
}
