'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@clerk/nextjs';
import Link from 'next/link';

// Support categories for the intake form
const CATEGORIES = [
  { id: 'domestic_violence', label: 'Domestic violence or abuse', group: 'safety' },
  { id: 'stalking', label: 'Stalking or threats', group: 'safety' },
  { id: 'online_harassment', label: 'Online harassment or cyber stalking', group: 'safety' },
  { id: 'workplace_harassment', label: 'Workplace harassment (POSH)', group: 'safety' },
  { id: 'safety', label: 'I feel unsafe right now', group: 'safety' },
  { id: 'consumer', label: 'Consumer complaint', group: 'general' },
  { id: 'housing', label: 'Housing or rental issue', group: 'general' },
  { id: 'cyber', label: 'Financial fraud or cyber scam', group: 'general' },
  { id: 'employment', label: 'Employment issue', group: 'general' },
  { id: 'education', label: 'Education or college issue', group: 'general' },
  { id: 'other', label: 'Something else', group: 'general' },
];

// Quick-start prompts (no visible labels in UI — just pre-fills the form)
const QUICK_STARTS = [
  {
    id: 'safety',
    label: "I'm feeling unsafe right now",
    category: 'safety',
    starter: 'I am currently feeling unsafe and need immediate emergency guidance and safety steps.',
    urgency: 'critical',
  },
  {
    id: 'domestic_violence',
    label: 'Abuse or domestic violence',
    category: 'domestic_violence',
    starter: 'I am experiencing physical, verbal, or emotional abuse at home and need support resources and legal options.',
    urgency: 'high',
  },
  {
    id: 'stalking',
    label: 'Harassment or stalking',
    category: 'stalking',
    starter: 'Someone is following me, sending unwanted threats, or monitoring my movements without consent.',
    urgency: 'high',
  },
  {
    id: 'online_harassment',
    label: 'Online harassment',
    category: 'online_harassment',
    starter: 'I am being harassed online, non-consensual images or messages are being shared, or fake profiles were created.',
    urgency: 'high',
  },
  {
    id: 'workplace_harassment',
    label: 'Workplace harassment',
    category: 'workplace_harassment',
    starter: 'I am facing sexual harassment or retaliatory threats from a supervisor or colleague at my workplace.',
    urgency: 'high',
  },
  {
    id: 'legal_information',
    label: 'Legal information',
    category: 'legal_information',
    starter: 'I need clear, verified legal information regarding my rights, protective orders, or filing formal complaints.',
    urgency: 'medium',
  },
  {
    id: 'therapy_support',
    label: 'Someone to talk to',
    category: 'therapy_support',
    starter: '',
    urgency: 'medium',
    redirect: '/therapybot',
  },
  {
    id: 'something_else',
    label: 'Something else',
    category: 'consumer',
    starter: '',
    urgency: 'medium',
  },
];

const RESEARCH_STEPS = [
  'Understanding your situation',
  'Finding verified resources and helplines',
  'Checking legal acts and government portals',
  'Locating nearby support centres',
  'Building your personalised plan',
];

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export default function Home() {
  const router = useRouter();
  const { user } = useUser();

  const [situationText, setSituationText] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('domestic_violence');
  const [locationInput, setLocationInput] = useState('');
  const [selectedPill, setSelectedPill] = useState<string | null>(null);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [step, setStep] = useState<'input' | 'understanding' | 'researching'>('input');
  const [analysis, setAnalysis] = useState<any>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [researchError, setResearchError] = useState<boolean>(false);

  const handlePillClick = (pill: (typeof QUICK_STARTS)[0]) => {
    if (pill.redirect) {
      router.push(pill.redirect);
      return;
    }
    setSelectedPill(pill.id);
    setSelectedCategory(pill.category);
    if (pill.starter && (!situationText || situationText.trim().length < 15)) {
      setSituationText(pill.starter);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!situationText.trim() || situationText.trim().length < 10) return;

    setIsSubmitting(true);
    setErrorMessage(null);
    setStep('understanding');

    try {
      const createRes = await fetch(`${API_BASE}/api/v2/cases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: user?.id || 'anonymous',
          situation_text: situationText,
          category: selectedCategory,
          location: locationInput ? { display_name: locationInput } : null,
        }),
      });

      if (!createRes.ok) throw new Error('Could not create case');
      const newCase = await createRes.json();
      const newId = newCase.id || newCase._id;
      setCaseId(newId);

      try {
        const analyzeRes = await fetch(`${API_BASE}/api/v2/cases/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ situation_text: situationText }),
        });
        if (analyzeRes.ok) {
          setAnalysis(await analyzeRes.json());
        } else {
          setAnalysis({
            case_summary: situationText,
            known_facts: [situationText.slice(0, 120)],
            missing_information: [],
            questions_to_ask: [],
          });
        }
      } catch {
        setAnalysis({
          case_summary: situationText,
          known_facts: [situationText.slice(0, 120)],
          missing_information: [],
          questions_to_ask: [],
        });
      }
    } catch (err: any) {
      console.error('Case creation error:', err);
      setErrorMessage("We couldn't connect to Haven right now. Your text is saved below. Please try again.");
      setStep('input');
    } finally {
      setIsSubmitting(false);
    }
  };

  const startResearch = async () => {
    if (!caseId) return;
    setStep('researching');
    setResearchError(false);
    setCurrentStepIndex(0);

    let stepIdx = 0;
    const interval = setInterval(() => {
      stepIdx++;
      if (stepIdx < RESEARCH_STEPS.length - 1) {
        setCurrentStepIndex(stepIdx);
      }
    }, 2800);

    try {
      const res = await fetch(`${API_BASE}/api/v2/research/${caseId}/run`, { method: 'POST' });
      clearInterval(interval);
      if (res.ok) {
        setCurrentStepIndex(RESEARCH_STEPS.length - 1);
        setTimeout(() => router.push(`/cases/${caseId}`), 400);
      } else {
        setResearchError(true);
      }
    } catch {
      clearInterval(interval);
      setResearchError(true);
    }
  };

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-background flex flex-col items-center justify-center p-4 sm:p-8">
      <div className="w-full max-w-2xl">

        {/* ── STEP 1: Intake Form ─────────────────────────────── */}
        {step === 'input' && (
          <div className="haven-fadein space-y-8">

            {/* Hero */}
            <div className="space-y-3 text-center">
              <h1 className="text-4xl sm:text-5xl font-bold text-foreground tracking-tight">
                Haven
              </h1>
              <p className="text-lg sm:text-xl text-muted-foreground font-light leading-relaxed max-w-md mx-auto">
                A safe place to figure out what comes next.
              </p>
            </div>

            {/* Error banner if network/server issue occurred */}
            {errorMessage && (
              <div
                className="p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-center justify-between gap-3"
                role="alert"
              >
                <span>{errorMessage}</span>
                <button
                  type="button"
                  suppressHydrationWarning
                  onClick={() => setErrorMessage(null)}
                  className="p-1 rounded hover:bg-destructive/20 text-xs font-semibold"
                  aria-label="Dismiss error"
                >
                  ✕
                </button>
              </div>
            )}

            {/* Quick-start options */}
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground text-center">
                What brings you here?
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {QUICK_STARTS.map((pill) => (
                  <button
                    key={pill.id}
                    type="button"
                    suppressHydrationWarning
                    onClick={() => handlePillClick(pill)}
                    aria-pressed={selectedPill === pill.id}
                    className={`px-3.5 py-2 rounded-lg text-sm transition-colors border ${
                      selectedPill === pill.id
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background border-border text-muted-foreground hover:border-primary/40 hover:text-foreground hover:bg-muted/30'
                    }`}
                  >
                    {pill.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Form */}
            <form
              onSubmit={handleSubmit}
              className="space-y-5 bg-card border border-border rounded-xl p-6 sm:p-8 shadow-sm"
            >
              {/* Situation textarea */}
              <div className="space-y-1.5">
                <label
                  htmlFor="situation"
                  className="text-sm font-medium text-foreground flex items-center justify-between"
                >
                  <span>Describe what happened</span>
                  <span className="text-xs text-muted-foreground font-normal">Confidential</span>
                </label>
                <textarea
                  id="situation"
                  suppressHydrationWarning
                  value={situationText}
                  onChange={(e) => setSituationText(e.target.value)}
                  placeholder="Share what's happening. Include what you need help with — Haven will find verified resources and next steps for your situation."
                  rows={5}
                  required
                  minLength={10}
                  aria-required="true"
                  className="w-full p-4 rounded-lg border border-input bg-background text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors leading-relaxed resize-none"
                />
              </div>

              {/* Location + Category row */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label htmlFor="location" className="text-sm font-medium text-foreground">
                    Location
                    <span className="ml-1 text-xs text-muted-foreground font-normal">(for nearby resources)</span>
                  </label>
                  <input
                    id="location"
                    type="text"
                    suppressHydrationWarning
                    value={locationInput}
                    onChange={(e) => setLocationInput(e.target.value)}
                    placeholder="e.g. New Delhi, Mumbai"
                    className="w-full px-4 py-2.5 rounded-lg border border-input bg-background text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="category" className="text-sm font-medium text-foreground">
                    Category
                  </label>
                  <select
                    id="category"
                    suppressHydrationWarning
                    value={selectedCategory}
                    onChange={(e) => setSelectedCategory(e.target.value)}
                    className="w-full px-4 py-2.5 rounded-lg border border-input bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors cursor-pointer"
                  >
                    <optgroup label="Safety & Support">
                      {CATEGORIES.filter((c) => c.group === 'safety').map((cat) => (
                        <option key={cat.id} value={cat.id}>
                          {cat.label}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label="Other Situations">
                      {CATEGORIES.filter((c) => c.group === 'general').map((cat) => (
                        <option key={cat.id} value={cat.id}>
                          {cat.label}
                        </option>
                      ))}
                    </optgroup>
                  </select>
                </div>
              </div>

              {/* Submit */}
              <button
                type="submit"
                suppressHydrationWarning
                disabled={isSubmitting || situationText.trim().length < 10}
                className="w-full py-3.5 bg-primary hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed text-primary-foreground font-semibold text-sm rounded-lg transition-colors flex items-center justify-center gap-2"
                aria-busy={isSubmitting}
              >
                {isSubmitting ? (
                  <>
                    <span className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" aria-hidden="true" />
                    <span>Analyzing your situation…</span>
                  </>
                ) : (
                  'Tell Haven what happened'
                )}
              </button>
            </form>

            {/* Secondary links */}
            <div className="flex flex-wrap justify-center items-center gap-6 text-sm text-muted-foreground">
              <Link href="/lawbot" className="hover:text-foreground transition-colors">
                Legal questions
              </Link>
              <span className="text-border" aria-hidden="true">·</span>
              <Link href="/therapybot" className="hover:text-foreground transition-colors">
                Talk to Haven
              </Link>
              <span className="text-border" aria-hidden="true">·</span>
              <Link href="/create-post" className="hover:text-foreground transition-colors">
                Community
              </Link>
            </div>
          </div>
        )}

        {/* ── STEP 2: Haven's understanding ───────────────────── */}
        {step === 'understanding' && (
          <div className="haven-fadein space-y-6">
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="w-2 h-2 rounded-full bg-emerald-500" aria-hidden="true" />
                <span>Situation understood</span>
              </div>
              <h2 className="text-2xl font-semibold text-foreground">
                Here's what Haven understood
              </h2>
            </div>

            {analysis ? (
              <div className="bg-card border border-border rounded-xl p-6 space-y-5 shadow-sm">
                {/* Case summary */}
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    Summary
                  </p>
                  <p className="text-sm text-foreground leading-relaxed">
                    {analysis.case_summary || situationText}
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                  {/* Known facts */}
                  {(analysis.known_facts || []).length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-emerald-700 dark:text-emerald-400 uppercase tracking-wider">
                        What we know
                      </p>
                      <ul className="space-y-1">
                        {(analysis.known_facts || []).slice(0, 4).map((fact: string, idx: number) => (
                          <li key={idx} className="text-sm text-muted-foreground flex items-start gap-2">
                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" aria-hidden="true" />
                            {fact}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Questions */}
                  {(analysis.missing_information || analysis.questions_to_ask || []).length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-amber-700 dark:text-amber-400 uppercase tracking-wider">
                        Haven may ask
                      </p>
                      <ul className="space-y-1">
                        {(analysis.missing_information || analysis.questions_to_ask || []).slice(0, 3).map((q: string, idx: number) => (
                          <li key={idx} className="text-sm text-muted-foreground flex items-start gap-2">
                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0" aria-hidden="true" />
                            {q}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between gap-4 pt-3 border-t border-border">
                  <button
                    type="button"
                    suppressHydrationWarning
                    onClick={() => setStep('input')}
                    className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    ← Edit
                  </button>
                  <button
                    type="button"
                    suppressHydrationWarning
                    onClick={startResearch}
                    className="px-6 py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold text-sm rounded-lg shadow-sm transition-colors flex items-center gap-2"
                  >
                    Find support & resources →
                  </button>
                </div>
              </div>
            ) : (
              <div className="bg-card border border-border rounded-xl p-8 text-center">
                <div className="flex justify-center mb-3">
                  <span className="w-5 h-5 border-2 border-muted-foreground/30 border-t-primary rounded-full animate-spin" aria-hidden="true" />
                </div>
                <p className="text-sm text-muted-foreground">Understanding your situation…</p>
              </div>
            )}
          </div>
        )}

        {/* ── STEP 3: Researching ──────────────────────────────── */}
        {step === 'researching' && (
          <div className="haven-fadein space-y-6 max-w-md mx-auto text-center">
            <div className="space-y-2">
              <h2 className="text-2xl font-semibold text-foreground">
                Finding resources for you
              </h2>
              <p className="text-sm text-muted-foreground">
                Haven is searching verified sources, helplines, and support centres.
              </p>
            </div>

            {researchError ? (
              <div className="bg-card border border-border rounded-xl p-6 text-center space-y-4 shadow-sm" role="alert">
                <p className="text-sm text-foreground leading-relaxed">
                  We couldn&apos;t complete the live research right now. Your saved case is safe.
                </p>
                <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
                  <button
                    type="button"
                    suppressHydrationWarning
                    onClick={startResearch}
                    className="w-full sm:w-auto px-5 py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium rounded-lg transition-colors"
                  >
                    Try research again
                  </button>
                  <button
                    type="button"
                    suppressHydrationWarning
                    onClick={() => router.push(`/cases/${caseId}`)}
                    className="w-full sm:w-auto px-5 py-2.5 bg-secondary hover:bg-secondary/80 text-secondary-foreground text-sm font-medium rounded-lg transition-colors border border-border"
                  >
                    Open case workspace →
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Visual pulse indicator */}
                <div className="flex justify-center py-2" aria-hidden="true">
                  <span className="w-6 h-6 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
                </div>

                {/* Step list — shows current real stage */}
                <div className="text-left space-y-2.5 bg-card border border-border rounded-xl p-4 shadow-sm" aria-live="polite">
                  {RESEARCH_STEPS.map((label, idx) => (
                    <div
                      key={idx}
                      className={`flex items-center gap-2.5 text-sm transition-colors ${
                        idx < currentStepIndex
                          ? 'text-muted-foreground'
                          : idx === currentStepIndex
                          ? 'text-foreground font-medium'
                          : 'text-muted-foreground/40'
                      }`}
                    >
                      {idx < currentStepIndex ? (
                        <span className="w-4 h-4 rounded-full bg-emerald-500 flex items-center justify-center text-white shrink-0" aria-hidden="true">
                          <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                            <path d="M1.5 4L3 5.5L6.5 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </span>
                      ) : idx === currentStepIndex ? (
                        <span className="w-4 h-4 rounded-full border-2 border-primary flex items-center justify-center shrink-0" aria-hidden="true">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                        </span>
                      ) : (
                        <span className="w-4 h-4 rounded-full border-2 border-border shrink-0" aria-hidden="true" />
                      )}
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
