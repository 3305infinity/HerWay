'use client';

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useUser } from '@clerk/nextjs';
import ResearchTrailDrawer from '@/components/ResearchTrailDrawer';

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

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

// ── Helper: Safety phase config ──────────────────────────────
const PHASES = [
  {
    key: 'right_now_actions',
    label: 'Right now',
    description: 'Do these first — before anything else.',
    color: 'text-red-700 dark:text-red-400',
    dotColor: 'bg-red-500',
    checkColor: 'accent-red-600',
  },
  {
    key: 'next_24h_actions',
    label: 'Next 24 hours',
    description: 'Safe practical steps when you have a moment.',
    color: 'text-amber-700 dark:text-amber-400',
    dotColor: 'bg-amber-500',
    checkColor: 'accent-amber-600',
  },
  {
    key: 'document_safe_actions',
    label: 'If safe to document',
    description: 'Only if you can do so privately and safely.',
    color: 'text-blue-700 dark:text-blue-400',
    dotColor: 'bg-blue-500',
    checkColor: 'accent-blue-600',
  },
  {
    key: 'support_network_actions',
    label: 'Support network',
    description: 'Reach out to people and organisations who can help.',
    color: 'text-purple-700 dark:text-purple-400',
    dotColor: 'bg-purple-500',
    checkColor: 'accent-purple-600',
  },
  {
    key: 'formal_options_actions',
    label: 'Formal and legal options',
    description: 'When you are ready to take formal steps.',
    color: 'text-emerald-700 dark:text-emerald-400',
    dotColor: 'bg-emerald-500',
    checkColor: 'accent-emerald-600',
  },
  {
    key: 'ongoing_actions',
    label: 'Ongoing',
    description: 'Things to revisit over time.',
    color: 'text-muted-foreground',
    dotColor: 'bg-muted-foreground/50',
    checkColor: 'accent-primary',
  },
] as const;

export default function CaseWorkspacePage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useUser();
  const caseId = params?.id as string;

  const [caseData, setCaseData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Drawer & Chat states
  const [isTrailOpen, setIsTrailOpen] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState<Array<{ role: string; content: string }>>([]);
  const [isChatLoading, setIsChatLoading] = useState(false);

  // Tabs for the main content area
  const [activeTab, setActiveTab] = useState<'plan' | 'evidence' | 'resources'>('plan');

  // Resource search
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchingResources, setIsSearchingResources] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);

  // Sidebar collapse on mobile
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const loadCase = async () => {
    if (!caseId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const url = user?.id
        ? `${API_BASE}/api/v2/cases/${caseId}?user_id=${user.id}`
        : `${API_BASE}/api/v2/cases/${caseId}`;
      const res = await fetch(url);
      if (res.status === 403) {
        setLoadError("You do not have access to this case. Please sign in with the account that created it.");
        return;
      }
      if (res.status === 404) {
        setLoadError("Case not found. It may have been archived or removed.");
        return;
      }
      if (!res.ok) {
        setLoadError("Unable to load case details right now. Please check your connection and try again.");
        return;
      }
      const data = await res.json();
      setCaseData(data);
      if (data.conversation) setChatHistory(data.conversation);
    } catch (err) {
      console.error('Failed to load case:', err);
      setLoadError("Unable to connect to Haven servers. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadCase(); }, [caseId, user?.id]);

  const toggleSafetyAction = async (actionId: string, currentStatus: string) => {
    if (!caseData?.safety_plan) return;
    const newStatus = currentStatus === 'completed' ? 'todo' : 'completed';
    const updateList = (list: any[]) =>
      (list || []).map((a: any) =>
        a.id === actionId
          ? { ...a, status: newStatus, completed_at: newStatus === 'completed' ? new Date().toISOString() : null }
          : a
      );
    const updatedPlan = {
      ...caseData.safety_plan,
      actions: updateList(caseData.safety_plan.actions),
      right_now_actions: updateList(caseData.safety_plan.right_now_actions),
      next_24h_actions: updateList(caseData.safety_plan.next_24h_actions),
      document_safe_actions: updateList(caseData.safety_plan.document_safe_actions),
      support_network_actions: updateList(caseData.safety_plan.support_network_actions),
      formal_options_actions: updateList(caseData.safety_plan.formal_options_actions),
      ongoing_actions: updateList(caseData.safety_plan.ongoing_actions),
    };
    setCaseData({ ...caseData, safety_plan: updatedPlan });
    try {
      const url = user?.id
        ? `${API_BASE}/api/v2/cases/${caseId}/actions/${actionId}?user_id=${user.id}`
        : `${API_BASE}/api/v2/cases/${caseId}/actions/${actionId}`;
      await fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
    } catch (err) {
      console.error('Failed to toggle safety action:', err);
    }
  };

  const toggleStandardAction = async (actionId: string, currentCompleted: boolean) => {
    if (!caseData?.action_plan) return;
    const newStatus = !currentCompleted ? 'completed' : 'todo';
    const updatedActions = (caseData.action_plan.actions || []).map((act: any) =>
      act.id === actionId ? { ...act, completed: !currentCompleted, status: newStatus } : act
    );
    setCaseData({ ...caseData, action_plan: { ...caseData.action_plan, actions: updatedActions } });
    try {
      const url = user?.id
        ? `${API_BASE}/api/v2/cases/${caseId}/actions/${actionId}?user_id=${user.id}`
        : `${API_BASE}/api/v2/cases/${caseId}/actions/${actionId}`;
      await fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
    } catch (err) {
      console.error('Failed to update action:', err);
    }
  };

  const handleSearchMoreResources = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsSearchingResources(true);
    try {
      const res = await fetch(`${API_BASE}/api/v2/cases/${caseId}/safety-plan/research-more`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: searchQuery.trim(),
          location: caseData?.situation?.location || caseData?.location_context || '',
          vertical: 'maps',
        }),
      });
      if (res.ok) {
        setSearchQuery('');
        await loadCase();
      }
    } catch (err) {
      console.error('Resource search error:', err);
    } finally {
      setIsSearchingResources(false);
    }
  };

  const handleSendChat = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatMessage.trim()) return;
    const userMsg = chatMessage.trim();
    setChatMessage('');
    setChatHistory((prev) => [...prev, { role: 'user', content: userMsg }]);
    setIsChatLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v2/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_id: caseId, message: userMsg, history: chatHistory }),
      });
      if (res.ok) {
        const data = await res.json();
        setChatHistory((prev) => [...prev, { role: 'assistant', content: data.reply }]);
        if (data.plan_adapted || data.safety_plan) await loadCase();
      }
    } catch (err) {
      console.error('Chat error:', err);
    } finally {
      setIsChatLoading(false);
    }
  };

  // ── Loading & error states ─────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="w-6 h-6 border-2 border-border border-t-primary rounded-full animate-spin mx-auto" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">Loading your case…</p>
        </div>
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6 space-y-4 text-center max-w-md mx-auto">
        <p className="text-foreground font-medium text-base">
          {loadError || "Case not found."}
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
          <button
            type="button"
            suppressHydrationWarning
            onClick={loadCase}
            className="w-full sm:w-auto px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
          >
            Retry
          </button>
          <button
            type="button"
            suppressHydrationWarning
            onClick={() => router.push('/cases')}
            className="w-full sm:w-auto px-4 py-2 bg-secondary text-secondary-foreground text-sm font-medium rounded-lg hover:bg-secondary/80 transition-colors border border-border"
          >
            Back to my cases
          </button>
        </div>
      </div>
    );
  }

  const category = (caseData.category || '').toLowerCase();
  const isSafetyMode =
    WOMEN_SAFETY_CATEGORIES.some((c) => category.includes(c)) || !!caseData.safety_plan;
  const situation = caseData.situation || {};
  const evidenceList = caseData.evidence || [];
  const actionPlan = caseData.action_plan || {};
  const safetyPlan = caseData.safety_plan || null;
  const localResources = caseData.local_resources || [];
  const trace = caseData.research_trace || [];
  const assessment = safetyPlan?.assessment || null;
  const allResources = safetyPlan?.matched_resources || localResources;

  const totalSafetyActions = safetyPlan?.actions?.length || 0;
  const completedSafetyActions =
    safetyPlan?.actions?.filter((a: any) => a.status === 'completed').length || 0;

  const totalStdActions = actionPlan.actions?.length || 0;
  const completedStdActions = actionPlan.actions?.filter((a: any) => a.completed).length || 0;

  return (
    <div className="min-h-screen bg-background flex flex-col">

      {/* ── Emergency helpline strip (safety cases only) ─────── */}
      {isSafetyMode && (
        <div className="bg-red-700 dark:bg-red-900 text-white px-4 py-2.5">
          <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs">
            <span className="font-medium">Emergency contacts</span>
            <div className="flex items-center gap-4 font-mono font-semibold flex-wrap">
              <a href="tel:112" className="hover:underline" aria-label="Call 112 Emergency">
                112 Emergency
              </a>
              <a href="tel:181" className="hover:underline" aria-label="Call 181 Women Helpline">
                181 Women Helpline
              </a>
              <a href="tel:1091" className="hover:underline" aria-label="Call 1091 Women Police">
                1091 Women Police
              </a>
            </div>
          </div>
        </div>
      )}

      {/* ── Page header ───────────────────────────────────────── */}
      <header className="border-b border-border bg-background px-4 sm:px-6 py-4 sticky top-14 z-40">
        <div className="max-w-5xl mx-auto flex items-start sm:items-center justify-between gap-4">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
              <button
                onClick={() => router.push('/cases')}
                className="hover:text-foreground transition-colors"
              >
                My Cases
              </button>
              <span aria-hidden="true">/</span>
              <span className="capitalize">
                {(caseData.category || 'dispute').replace(/_/g, ' ')}
              </span>
              {safetyPlan?.updated_at && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>
                    Updated{' '}
                    {new Date(safetyPlan.updated_at).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </>
              )}
            </div>
            <h1 className="text-lg sm:text-xl font-semibold text-foreground leading-tight">
              {caseData.title || 'Case Workspace'}
            </h1>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {safetyPlan?.updates_history?.length > 0 && (
              <button
                onClick={() => setShowHistoryModal(true)}
                className="px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
                aria-label={`View ${safetyPlan.updates_history.length} plan updates`}
              >
                Plan updated ({safetyPlan.updates_history.length})
              </button>
            )}
            <button
              onClick={() => setIsTrailOpen(true)}
              className="px-3 py-1.5 text-xs text-muted-foreground bg-muted/50 hover:bg-muted border border-border rounded-lg transition-colors"
              aria-label="See how Haven researched this case"
            >
              How we researched this
            </button>
            <button
              onClick={() => setIsChatOpen(true)}
              className="px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              aria-label="Open Haven assistant"
            >
              Ask Haven
            </button>
          </div>
        </div>
      </header>

      {/* ── Plan-updated banner ───────────────────────────────── */}
      {safetyPlan?.updates_history?.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200 dark:border-amber-800 px-4 sm:px-6 py-3">
          <div className="max-w-5xl mx-auto flex items-start justify-between gap-4 text-xs">
            <p className="text-amber-800 dark:text-amber-300">
              <span className="font-semibold">Plan updated:</span>{' '}
              {safetyPlan.updates_history[safetyPlan.updates_history.length - 1].why_plan_changed}
            </p>
            <button
              onClick={() => setShowHistoryModal(true)}
              className="text-amber-700 dark:text-amber-300 font-medium hover:underline shrink-0"
            >
              View changes →
            </button>
          </div>
        </div>
      )}

      {/* ── Main content ──────────────────────────────────────── */}
      <div className="flex-1 max-w-5xl mx-auto w-full px-4 sm:px-6 py-6 sm:py-8">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-8">

          {/* Primary column */}
          <div className="space-y-6 min-w-0">

            {/* Situation summary */}
            <div className="space-y-2">
              <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Situation
              </h2>
              <p className="text-sm text-foreground leading-relaxed">
                {situation.case_summary || caseData.situation_text}
              </p>
              {situation.user_goal && (
                <p className="text-sm text-muted-foreground">
                  <span className="font-medium text-foreground">Goal:</span>{' '}
                  {situation.user_goal}
                </p>
              )}
            </div>

            {/* Safety assessment — collapsible indicators, not a grid of 10 boxes */}
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
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-muted-foreground" aria-hidden="true">
                    <path d="M2 4L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </summary>
                <div className="px-5 pb-5 pt-3 border-t border-border/50 space-y-3">
                  <div className="space-y-1.5">
                    {[
                      { key: 'immediate_safety_concern', label: 'Immediate danger' },
                      { key: 'threats_present', label: 'Threats present' },
                      { key: 'escalating_behavior', label: 'Escalating pattern' },
                      { key: 'repeated_harassment', label: 'Recurring harassment' },
                      { key: 'digital_safety_concern', label: 'Device or digital risk' },
                      { key: 'financial_dependence', label: 'Financial control' },
                      { key: 'presence_of_dependents', label: 'Children or dependents involved' },
                      { key: 'workplace_harassment', label: 'Workplace or POSH related' },
                      { key: 'safe_place_available', label: 'Safe place identified' },
                      { key: 'support_available', label: 'Support network available' },
                    ]
                      .filter((item) => assessment[item.key] !== undefined)
                      .map((item) => (
                        <div key={item.key} className="flex items-start gap-2.5 text-sm">
                          <span
                            className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                              assessment[item.key]
                                ? item.key === 'safe_place_available' || item.key === 'support_available'
                                  ? 'bg-emerald-500'
                                  : 'bg-red-500'
                                : 'bg-muted-foreground/20'
                            }`}
                            aria-hidden="true"
                          />
                          <span className={assessment[item.key] ? 'text-foreground' : 'text-muted-foreground/60'}>
                            {item.label}
                            {assessment[item.key] && assessment.indicator_justifications?.[item.key] && (
                              <span className="text-muted-foreground font-normal">
                                {' — '}
                                <em>{assessment.indicator_justifications[item.key]}</em>
                              </span>
                            )}
                          </span>
                        </div>
                      ))}
                  </div>
                  {assessment.critical_safety_notes?.length > 0 && (
                    <div className="pt-2 border-t border-border/50 space-y-1">
                      <p className="text-xs font-medium text-red-700 dark:text-red-400">Important notes</p>
                      <ul className="space-y-1">
                        {assessment.critical_safety_notes.map((note: string, idx: number) => (
                          <li key={idx} className="text-sm text-muted-foreground leading-relaxed">
                            {note}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </details>
            )}

            {/* Tab bar */}
            <div className="border-b border-border" role="tablist">
              {([
                { id: 'plan', label: isSafetyMode ? 'Safety plan' : 'Action plan', count: isSafetyMode ? `${completedSafetyActions}/${totalSafetyActions}` : `${completedStdActions}/${totalStdActions}` },
                { id: 'evidence', label: 'Sources', count: evidenceList.length > 0 ? String(evidenceList.length) : undefined },
                { id: 'resources', label: 'Resources', count: allResources.length > 0 ? String(allResources.length) : undefined },
              ] as const).map((tab) => (
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

            {/* ── TAB: Safety / Action Plan ────────────────────── */}
            {activeTab === 'plan' && (
              <div className="space-y-8">
                {safetyPlan ? (
                  PHASES.map((phase) => {
                    const actions = safetyPlan[phase.key] || [];
                    if (actions.length === 0) return null;
                    const doneCount = actions.filter((a: any) => a.status === 'completed').length;
                    return (
                      <div key={phase.key} className="space-y-1">
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full ${phase.dotColor} shrink-0`} aria-hidden="true" />
                            <h3 className={`text-sm font-semibold ${phase.color}`}>
                              {phase.label}
                            </h3>
                          </div>
                          <span className="text-xs text-muted-foreground">
                            {doneCount}/{actions.length}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground mb-3 ml-4">{phase.description}</p>

                        {/* Actions as checklist rows, not individual cards */}
                        <div className="ml-4 border border-border/60 rounded-xl overflow-hidden divide-y divide-border/60">
                          {actions.map((act: any) => (
                            <label
                              key={act.id}
                              className={`flex items-start gap-3 px-4 py-3.5 cursor-pointer hover:bg-muted/20 transition-colors ${
                                act.status === 'completed' ? 'bg-muted/10' : 'bg-card'
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={act.status === 'completed'}
                                onChange={() => toggleSafetyAction(act.id, act.status)}
                                className={`mt-0.5 w-4 h-4 rounded border-input ${phase.checkColor} cursor-pointer shrink-0`}
                                aria-label={`Mark "${act.title}" as ${act.status === 'completed' ? 'incomplete' : 'complete'}`}
                              />
                              <div className="flex-1 min-w-0 space-y-0.5">
                                <p className={`text-sm font-medium leading-snug ${
                                  act.status === 'completed'
                                    ? 'line-through text-muted-foreground'
                                    : 'text-foreground'
                                }`}>
                                  {act.title}
                                </p>
                                {act.description && (
                                  <p className={`text-xs leading-relaxed ${
                                    act.status === 'completed' ? 'text-muted-foreground/60' : 'text-muted-foreground'
                                  }`}>
                                    {act.description}
                                  </p>
                                )}
                                {act.safety_caveat && (
                                  <p className="text-xs text-red-600 dark:text-red-400 font-medium">
                                    ⚠ {act.safety_caveat}
                                  </p>
                                )}
                                {/* Evidence links — subtle */}
                                {act.evidence_ids?.length > 0 && (
                                  <div className="flex items-center gap-1 flex-wrap pt-0.5">
                                    {act.evidence_ids.slice(0, 2).map((eid: string) => {
                                      const ev = evidenceList.find((e: any) => e.id === eid);
                                      return ev?.url ? (
                                        <a
                                          key={eid}
                                          href={ev.url}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="text-[10px] text-primary hover:underline"
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          Source ↗
                                        </a>
                                      ) : null;
                                    })}
                                  </div>
                                )}
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    );
                  })
                ) : (
                  /* Standard (non-safety) action plan */
                  <div className="border border-border/60 rounded-xl overflow-hidden divide-y divide-border/60">
                    {(actionPlan.actions || []).length === 0 ? (
                      <div className="p-6 text-center text-sm text-muted-foreground">
                        No actions generated yet.
                      </div>
                    ) : (
                      (actionPlan.actions || []).map((act: any) => (
                        <label
                          key={act.id}
                          className={`flex items-start gap-3 px-4 py-3.5 cursor-pointer hover:bg-muted/20 transition-colors ${
                            act.completed ? 'bg-muted/10' : 'bg-card'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={!!act.completed}
                            onChange={() => toggleStandardAction(act.id, !!act.completed)}
                            className="mt-0.5 w-4 h-4 rounded border-input accent-primary cursor-pointer shrink-0"
                            aria-label={`Mark "${act.title}" as ${act.completed ? 'incomplete' : 'complete'}`}
                          />
                          <div className="flex-1 min-w-0 space-y-0.5">
                            <p className={`text-sm font-medium leading-snug ${
                              act.completed ? 'line-through text-muted-foreground' : 'text-foreground'
                            }`}>
                              {act.title}
                            </p>
                            {act.description && (
                              <p className="text-xs text-muted-foreground leading-relaxed">
                                {act.description}
                              </p>
                            )}
                          </div>
                        </label>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── TAB: Evidence / Sources ──────────────────────── */}
            {activeTab === 'evidence' && (
              <div className="space-y-4">
                {evidenceList.length === 0 ? (
                  <div className="py-12 text-center space-y-3 bg-card border border-border rounded-xl p-6">
                    <p className="text-sm text-muted-foreground">
                      We couldn&apos;t verify enough information to make a reliable recommendation.
                    </p>
                    <div>
                      <button
                        type="button"
                        suppressHydrationWarning
                        onClick={() => setIsChatOpen(true)}
                        className="px-4 py-2 text-xs font-medium text-primary hover:bg-primary/10 border border-primary/20 rounded-lg transition-colors"
                      >
                        Search again
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="text-xs text-muted-foreground">
                      These sources were retrieved and verified by Haven.
                    </p>
                    <div className="space-y-3">
                      {evidenceList.map((ev: any, idx: number) => (
                        <div
                          key={ev.id || idx}
                          className="border border-border rounded-xl p-4 space-y-2 hover:border-border/80 transition-colors"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="space-y-1 flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <h3 className="text-sm font-medium text-foreground leading-snug">
                                  {ev.source_title || ev.title || ev.domain}
                                </h3>
                                {ev.source_type && (
                                  <span className="text-[11px] font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded capitalize">
                                    {(ev.source_type || '').replace(/_/g, ' ')}
                                  </span>
                                )}
                              </div>
                              {ev.domain && (
                                <p className="text-xs text-muted-foreground font-mono">{ev.domain}</p>
                              )}
                            </div>
                            {ev.url && (
                              <a
                                href={ev.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs text-primary hover:underline shrink-0 font-medium"
                                aria-label={`Open source: ${ev.source_title || ev.domain}`}
                              >
                                View source →
                              </a>
                            )}
                          </div>
                          {(ev.claim_supported || ev.claim) && (
                            <p className="text-sm text-foreground/90 leading-relaxed bg-muted/20 p-2.5 rounded-lg border border-border/40">
                              &ldquo;{ev.claim_supported || ev.claim}&rdquo;
                            </p>
                          )}
                          {ev.why_this_source_matters && (
                            <p className="text-xs text-muted-foreground italic">
                              Why this matters: {ev.why_this_source_matters}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ── TAB: Resources ───────────────────────────────── */}
            {activeTab === 'resources' && (
              <div className="space-y-4">
                {/* Search for more */}
                <form onSubmit={handleSearchMoreResources} className="flex gap-2">
                  <input
                    type="text"
                    suppressHydrationWarning
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search for nearby shelters, clinics, legal aid, or police cells…"
                    aria-label="Search for nearby resources"
                    className="flex-1 px-3.5 py-2 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
                  />
                  <button
                    type="submit"
                    suppressHydrationWarning
                    disabled={isSearchingResources || !searchQuery.trim()}
                    className="px-4 py-2 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground text-sm font-medium rounded-lg transition-colors shrink-0"
                  >
                    {isSearchingResources ? (
                      <span className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin block" aria-hidden="true" />
                    ) : 'Search'}
                  </button>
                </form>

                {allResources.length === 0 ? (
                  <div className="py-12 text-center space-y-3 bg-card border border-border rounded-xl p-6">
                    <p className="text-sm text-muted-foreground">
                      We couldn&apos;t find a suitable nearby resource for this location.
                    </p>
                    <div>
                      <button
                        type="button"
                        suppressHydrationWarning
                        onClick={() => {
                          const inputEl = document.querySelector('input[aria-label="Search for nearby resources"]') as HTMLInputElement;
                          if (inputEl) { inputEl.focus(); }
                        }}
                        className="px-4 py-2 text-xs font-medium text-primary hover:bg-primary/10 border border-primary/20 rounded-lg transition-colors"
                      >
                        Try another area
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {allResources.map((res: any, idx: number) => (
                      <div
                        key={res.id || idx}
                        className="border border-border rounded-xl p-4 space-y-2 hover:border-border/80 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="space-y-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h3 className="text-sm font-semibold text-foreground">{res.name}</h3>
                              {res.is_verified_gov_or_ngo ? (
                                <span className="text-[11px] font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded">
                                  ✓ Verified Resource
                                </span>
                              ) : (
                                <span className="text-[11px] font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 px-2 py-0.5 rounded">
                                  Source needs verification
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                              {res.category && (
                                <span className="capitalize">{res.category.replace(/_/g, ' ')}</span>
                              )}
                              {res.source_domain && (
                                <>
                                  <span aria-hidden="true">·</span>
                                  <span className="font-mono">{res.source_domain}</span>
                                </>
                              )}
                              {res.retrieved_at && (
                                <>
                                  <span aria-hidden="true">·</span>
                                  <span>Retrieved {new Date(res.retrieved_at).toLocaleDateString()}</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="space-y-1 text-sm pt-1">
                          {res.address && (
                            <a
                              href={`https://maps.google.com/?q=${encodeURIComponent(res.name + ' ' + res.address)}`}
                              target="_blank"
                              rel="noreferrer"
                              className="flex items-start gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
                              aria-label={`Get directions to ${res.name}`}
                            >
                              <span className="mt-0.5 shrink-0" aria-hidden="true">📍</span>
                              <span className="hover:underline">{res.address}</span>
                            </a>
                          )}
                          {res.phone && (
                            <a
                              href={`tel:${res.phone.replace(/[^0-9+]/g, '')}`}
                              className="flex items-center gap-1.5 text-primary font-mono font-semibold hover:underline"
                              aria-label={`Call ${res.name} at ${res.phone}`}
                            >
                              <span aria-hidden="true">📞</span>
                              {res.phone}
                            </a>
                          )}
                          {res.operating_hours && (
                            <p className="text-muted-foreground text-xs flex items-center gap-1.5">
                              <span aria-hidden="true">🕒</span>
                              {res.operating_hours}
                            </p>
                          )}
                          {res.url && (
                            <a
                              href={res.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs text-primary hover:underline font-medium block pt-0.5"
                              aria-label={`Visit ${res.name} website`}
                            >
                              Visit website →
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Sidebar: Situation details (desktop) ─────────── */}
          <aside className="hidden lg:block space-y-6">
            {/* Progress summary */}
            <div className="haven-card space-y-3">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Progress
              </h3>
              {isSafetyMode ? (
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-foreground">{completedSafetyActions} steps done</span>
                    <span className="text-muted-foreground">{totalSafetyActions} total</span>
                  </div>
                  <div className="haven-progress-bar">
                    <div
                      className="haven-progress-fill"
                      style={{ width: `${totalSafetyActions > 0 ? (completedSafetyActions / totalSafetyActions) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-foreground">{completedStdActions} steps done</span>
                    <span className="text-muted-foreground">{totalStdActions} total</span>
                  </div>
                  <div className="haven-progress-bar">
                    <div
                      className="haven-progress-fill"
                      style={{ width: `${totalStdActions > 0 ? (completedStdActions / totalStdActions) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Ask Haven CTA */}
            <div className="haven-card space-y-3">
              <h3 className="text-sm font-medium text-foreground">Ask Haven</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                If your situation changes, or you have questions, Haven can update your plan.
              </p>
              <button
                onClick={() => setIsChatOpen(true)}
                className="w-full py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium rounded-lg transition-colors"
                aria-label="Open Haven assistant chat"
              >
                Ask a question
              </button>
            </div>

            {/* Research trail link */}
            {trace.length > 0 && (
              <button
                onClick={() => setIsTrailOpen(true)}
                className="w-full text-left haven-card hover:border-border/80 transition-colors space-y-1"
                aria-label="See how Haven researched this case"
              >
                <h3 className="text-sm font-medium text-foreground">How we researched this</h3>
                <p className="text-xs text-muted-foreground">
                  {trace.length} search{trace.length !== 1 ? 'es' : ''} · {evidenceList.length} sources verified
                </p>
                <p className="text-xs text-primary font-medium">View research trail →</p>
              </button>
            )}
          </aside>
        </div>
      </div>

      {/* ── Ask Haven Drawer ────────────────────────────────── */}
      {isChatOpen && (
        <div
          className="fixed inset-y-0 right-0 w-full sm:w-[420px] bg-background border-l border-border shadow-2xl z-50 flex flex-col"
          role="dialog"
          aria-modal="true"
          aria-label="Ask Haven assistant"
        >
          <div className="p-4 border-b border-border flex items-center justify-between">
            <div className="space-y-0.5">
              <h3 className="text-sm font-semibold text-foreground">Ask Haven</h3>
              <p className="text-xs text-muted-foreground">Your plan can be updated based on new information.</p>
            </div>
            <button
              onClick={() => setIsChatOpen(false)}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              aria-label="Close assistant"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </button>
          </div>

          <div className="flex-1 p-4 overflow-y-auto custom-scrollbar space-y-3">
            {chatHistory.length === 0 && (
              <div className="p-4 bg-muted/30 rounded-lg space-y-2">
                <p className="text-sm font-medium text-foreground">What you can ask Haven:</p>
                <ul className="space-y-1 text-sm text-muted-foreground">
                  <li>"He found out I called a lawyer — what should I do?"</li>
                  <li>"Is there a women's shelter near me that accepts pets?"</li>
                  <li>"How do I safely save text messages as evidence?"</li>
                </ul>
              </div>
            )}
            {chatHistory.map((msg, idx) => (
              <div
                key={idx}
                className={`max-w-[85%] px-4 py-3 rounded-xl text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground ml-auto'
                    : 'bg-muted text-foreground mr-auto border border-border'
                }`}
              >
                {msg.content}
              </div>
            ))}
            {isChatLoading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="w-4 h-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" aria-hidden="true" />
                Haven is thinking…
              </div>
            )}
          </div>

          <form onSubmit={handleSendChat} className="p-4 border-t border-border flex gap-2">
            <input
              type="text"
              value={chatMessage}
              onChange={(e) => setChatMessage(e.target.value)}
              placeholder="Ask a question or describe what's changed…"
              aria-label="Message to Haven assistant"
              className="flex-1 px-3.5 py-2.5 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
            />
            <button
              type="submit"
              disabled={isChatLoading || !chatMessage.trim()}
              className="px-4 py-2.5 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground text-sm font-medium rounded-lg transition-colors shrink-0"
              aria-label="Send message"
            >
              Send
            </button>
          </form>
        </div>
      )}

      {/* ── Plan History Modal ────────────────────────────────── */}
      {showHistoryModal && safetyPlan?.updates_history && (
        <div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Plan update history"
        >
          <div className="bg-card border border-border rounded-xl max-w-lg w-full shadow-2xl flex flex-col max-h-[80vh]">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <h3 className="text-base font-semibold text-foreground">Plan updates</h3>
              <button
                onClick={() => setShowHistoryModal(false)}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                aria-label="Close update history"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              </button>
            </div>
            <div className="overflow-y-auto custom-scrollbar p-5 space-y-4">
              {safetyPlan.updates_history.map((upd: any, idx: number) => (
                <div key={upd.update_id || idx} className="space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-foreground">{upd.why_plan_changed}</p>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {new Date(upd.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  {upd.what_changed?.length > 0 && (
                    <ul className="space-y-1">
                      {upd.what_changed.map((c: string, i: number) => (
                        <li key={i} className="text-xs text-muted-foreground flex items-start gap-2">
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-muted-foreground/40 shrink-0" aria-hidden="true" />
                          {c}
                        </li>
                      ))}
                    </ul>
                  )}
                  {upd.new_recommended_steps?.length > 0 && (
                    <div className="pl-3 border-l-2 border-primary/30 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">New steps added:</p>
                      {upd.new_recommended_steps.map((s: string, i: number) => (
                        <p key={i} className="text-xs text-foreground">{s}</p>
                      ))}
                    </div>
                  )}
                  {idx < safetyPlan.updates_history.length - 1 && (
                    <hr className="border-border/50 mt-3" />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Research Trail Drawer */}
      <ResearchTrailDrawer
        isOpen={isTrailOpen}
        onClose={() => setIsTrailOpen(false)}
        category={caseData.category}
        trace={trace}
        evidenceCount={evidenceList.length}
        actionCount={isSafetyMode ? totalSafetyActions : totalStdActions}
      />
    </div>
  );
}
