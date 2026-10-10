'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { motion } from 'framer-motion';

import { apiGet, apiPost } from '@/lib/api';
import VoiceInput from '@/components/VoiceInput';
import DemoScenarios, { type DemoScenario } from '@/components/DemoScenarios';
import { ALL_INDIAN_REGIONS, composeLocation } from '@/lib/india';
import type { CaseRecord, Situation } from '@/lib/types';

const CATEGORIES = [
  { id: 'domestic_violence', label: 'Domestic abuse & violence', group: 'safety', starter: 'I am experiencing abuse or threats at home and need support resources and legal options.' },
  { id: 'stalking', label: 'Stalking & unwanted tracking', group: 'safety', starter: 'Someone is following me, monitoring my devices, or sending unwanted threatening messages.' },
  { id: 'online_harassment', label: 'Online harassment & cyber threats', group: 'safety', starter: 'Someone is repeatedly harassing or threatening me through social media or private messages.' },
  { id: 'workplace_harassment', label: 'Workplace harassment (POSH)', group: 'safety', starter: 'I am experiencing inappropriate conduct or harassment at work and want to understand my POSH rights.' },
  { id: 'safety', label: 'I feel unsafe right now', group: 'safety', starter: 'I am currently in an unsafe situation and need immediate safety steps and emergency guidance.' },
  { id: 'legal_information', label: 'Legal rights & information', group: 'general', starter: 'I need clear, factual legal guidance regarding my rights and legal procedures.' },
  { id: 'housing', label: 'Housing or rental dispute', group: 'general', starter: 'My landlord is withholding my security deposit or violating tenancy agreements.' },
  { id: 'consumer', label: 'Consumer complaint', group: 'general', starter: 'A business or seller refused to honor a warranty or provide a lawful refund.' },
  { id: 'other', label: 'Something else', group: 'general', starter: '' },
];

export default function Home() {
  const router = useRouter();
  const inputSectionRef = useRef<HTMLDivElement>(null);

  const [situationText, setSituationText] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('domestic_violence');
  const [city, setCity] = useState('');
  const [stateRegion, setStateRegion] = useState('');

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [step, setStep] = useState<'input' | 'understanding' | 'researching'>('input');
  const [analysis, setAnalysis] = useState<Situation | null>(null);
  const [analysisFailed, setAnalysisFailed] = useState(false);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [researchError, setResearchError] = useState<string | null>(null);

  /** Whether live search is actually configured on the server answering us. */
  const [serpapiUp, setSerpapiUp] = useState<boolean | null>(null);

  useEffect(() => {
    apiGet<{ integrations?: Record<string, boolean> }>('/health').then((r) => {
      if (r.ok) setSerpapiUp(Boolean(r.data.integrations?.serpapi));
    });
  }, []);

  // Pre-fill the box when arriving from a link that carries a starter.
  useEffect(() => {
    const starter = new URLSearchParams(window.location.search).get('starter');
    if (starter) {
      setSituationText(starter);
      inputSectionRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, []);

  const scrollToInput = (catId?: string, starter?: string) => {
    if (catId) setSelectedCategory(catId);
    if (starter && (!situationText || situationText.trim().length < 15)) {
      setSituationText(starter);
    }
    inputSectionRef.current?.scrollIntoView({ behavior: 'smooth' });
    document.getElementById('situation-textarea')?.focus();
  };

  const handleQuickExit = () => {
    window.location.replace('https://www.google.com');
  };

  /**
   * Which demo scenario, if any, produced the text currently in the box.
   * Cleared the moment the user edits it: once she has changed the words it is
   * her situation, not a sample, and must not be filed as one.
   */
  const [demoScenarioId, setDemoScenarioId] = useState<string | null>(null);

  const applyDemoScenario = (scenario: DemoScenario) => {
    setSituationText(scenario.situation_text);
    setSelectedCategory(scenario.category);
    setDemoScenarioId(scenario.id);
    if (scenario.location) {
      const [cityPart, statePart] = scenario.location.split(',').map((p) => p.trim());
      if (statePart) {
        setCity(cityPart);
        setStateRegion(statePart);
      } else {
        setStateRegion(cityPart);
      }
    }
    document
      .getElementById('situation-textarea')
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  /**
   * Arriving from `/project` with `?situation=<id>`.
   *
   * This only fills the box. Nothing is submitted, no case is created, and the
   * user still reads the text, edits it if she wants to, and presses the same
   * Continue button as anyone else. An unrecognised id simply does nothing.
   */
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get('situation');
    if (!wanted) return;

    let cancelled = false;
    apiGet<{ scenarios: DemoScenario[] }>('/api/v2/demo/scenarios').then((result) => {
      if (cancelled || !result.ok) return;
      const match = result.data.scenarios.find((s) => s.id === wanted);
      if (match) applyDemoScenario(match);
    });
    return () => {
      cancelled = true;
    };
    // Runs once on arrival; `applyDemoScenario` only touches setState.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (situationText.trim().length < 10) return;

    setIsSubmitting(true);
    setErrorMessage(null);
    setAnalysisFailed(false);

    const location = composeLocation({ city, state: stateRegion });

    // Identity comes from the session on the server; the browser does not
    // get to say who owns this case.
    const created = await apiPost<CaseRecord>('/api/v2/cases', {
      situation_text: situationText,
      category: selectedCategory,
      location: location ? { display_name: location } : null,
      // Server-validated against the known scenarios; an unknown value simply
      // produces an ordinary case.
      demo_scenario_id: demoScenarioId,
    });

    if (!created.ok) {
      setErrorMessage(
        `${created.error.message} Your words are still here below — nothing has been lost.`,
      );
      setIsSubmitting(false);
      return;
    }

    setCaseId(created.data.id);
    setStep('understanding');

    const analysed = await apiPost<Situation>('/api/v2/cases/analyze', {
      situation_text: situationText,
      category: selectedCategory,
    });

    if (analysed.ok) {
      setAnalysis(analysed.data);
    } else {
      // Show the user's own words back rather than fabricating a summary.
      setAnalysisFailed(true);
      setAnalysis({
        case_summary: situationText,
        category: selectedCategory,
        known_facts: [],
      });
    }
    setIsSubmitting(false);
  };

  const startResearch = async () => {
    if (!caseId) return;
    setStep('researching');
    setResearchError(null);

    // Research can legitimately take a while; allow for it rather than
    // timing out and telling the user it failed when it did not.
    const result = await apiPost(`/api/v2/research/${caseId}/run`, undefined, 180_000);

    if (result.ok) {
      router.push(`/cases/${caseId}`);
    } else {
      setResearchError(result.error.message);
    }
  };

  // ─────────────────────────────────────────────────────────────
  // STEP 2: UNDERSTANDING CONFIRMATION
  // ─────────────────────────────────────────────────────────────
  if (step === 'understanding' && analysis) {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] bg-background flex flex-col items-center justify-center p-4 sm:p-8">
        <div className="w-full max-w-2xl bg-card border border-border rounded-2xl p-6 sm:p-8 space-y-6 shadow-sm">
          <div className="space-y-2 border-b border-border/60 pb-5">
            <span className="inline-flex items-center gap-2.5 text-xs uppercase tracking-[0.16em] font-semibold text-primary before:block before:h-px before:w-6 before:bg-primary/60 before:content-['']">
              Step 1 of 2 · Understanding Your Situation
            </span>
            <h1 className="font-serif text-2xl sm:text-3xl text-foreground font-normal">
              Before we search, here is what we understood.
            </h1>
            <p className="text-sm text-muted-foreground leading-relaxed">
              We extract only explicit facts so your research and safety plan are based on truth, not assumptions.
            </p>
          </div>

          {analysisFailed && (
            <div className="p-3 rounded-xl border border-amber-500/40 bg-amber-500/5 text-xs text-amber-800 dark:text-amber-300 leading-relaxed">
              We could not analyse this automatically just now, so your own words are shown
              below unchanged. You can still continue — research will run on what you wrote.
            </div>
          )}

          <div className="space-y-4 text-sm leading-relaxed">
            <div className="p-4 rounded-xl bg-muted/40 border border-border/60 space-y-1.5">
              <span className="text-xs font-semibold text-foreground uppercase tracking-wider">
                {analysisFailed ? 'What you told us' : 'Summary'}
              </span>
              <p className="text-foreground">{analysis.case_summary || situationText}</p>
            </div>

            {(analysis.known_facts?.length ?? 0) > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  What we understood as fact
                </span>
                <ul className="space-y-1.5 pl-4 list-disc text-muted-foreground">
                  {analysis.known_facts!.map((fact, idx) => (
                    <li key={idx} className="text-foreground/90">{fact}</li>
                  ))}
                </ul>
              </div>
            )}

            {(analysis.questions_to_ask?.length ?? 0) > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Things that would help us help you
                </span>
                <ul className="space-y-1.5 pl-4 list-disc text-muted-foreground">
                  {analysis.questions_to_ask!.map((q, idx) => (
                    <li key={idx}>{q}</li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">
                  You can add these later — you do not have to answer anything now.
                </p>
              </div>
            )}
          </div>

          <div className="pt-4 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => setStep('input')}
              className="text-xs text-muted-foreground hover:text-foreground order-2 sm:order-1 transition-colors"
            >
              ← Edit your situation text
            </button>
            <button
              type="button"
              onClick={startResearch}
              className="w-full sm:w-auto px-6 py-3 bg-primary text-primary-foreground font-medium rounded-xl hover:bg-primary/90 transition-colors shadow-sm order-1 sm:order-2"
            >
              Begin verified research →
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────
  // STEP 3: RESEARCH PROGRESS
  // ─────────────────────────────────────────────────────────────
  if (step === 'researching') {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] bg-background flex flex-col items-center justify-center p-4">
        <div className="w-full max-w-lg bg-card border border-border rounded-2xl p-8 space-y-8 shadow-sm">
          {!researchError ? (
            <>
              <div className="space-y-2 text-center">
                <span className="inline-flex items-center gap-2.5 text-xs uppercase tracking-[0.16em] font-semibold text-primary before:block before:h-px before:w-6 before:bg-primary/60 before:content-['']">
                  Step 2 of 2 · Live research and verification
                </span>
                <h1 className="font-serif text-2xl sm:text-3xl text-foreground font-normal">
                  HerWay is researching your situation.
                </h1>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Checking official government sources, helplines and — if you gave a
                  location — centres near you.
                </p>
              </div>

              {/* An indeterminate indicator. We deliberately do not animate
                  through named steps: we cannot see the backend's progress, and
                  ticking stages off on a timer would be showing the user
                  research that may not have happened. */}
              <div className="py-4 space-y-4">
                <div
                  className="h-1.5 w-full rounded-full bg-muted overflow-hidden"
                  role="progressbar"
                  aria-label="Researching"
                >
                  <div className="h-full w-1/3 rounded-full bg-primary animate-[herway-indeterminate_1.4s_ease-in-out_infinite]" />
                </div>
                <p className="text-sm text-center text-foreground">
                  This usually takes under a minute.
                </p>
              </div>

              <p className="text-xs text-center text-muted-foreground border-t border-border/60 pt-4 leading-relaxed">
                You can leave this page — your case is already saved and will be waiting in
                <strong className="text-foreground"> My cases</strong>.
              </p>
            </>
          ) : (
            <div className="space-y-6 text-center">
              <div className="w-12 h-12 rounded-full bg-rose-100 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 flex items-center justify-center mx-auto text-xl" aria-hidden="true">
                !
              </div>
              <div className="space-y-2">
                <h1 className="text-xl font-semibold text-foreground">Research did not finish</h1>
                <p className="text-sm text-muted-foreground leading-relaxed">{researchError}</p>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Your case has been saved. You can open it now and try research again from
                  there whenever you want.
                </p>
              </div>
              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <button
                  type="button"
                  onClick={() => void startResearch()}
                  className="px-5 py-2.5 bg-primary text-primary-foreground text-sm font-medium rounded-xl hover:bg-primary/90 transition-colors"
                >
                  Try again
                </button>
                {caseId && (
                  <button
                    type="button"
                    onClick={() => router.push(`/cases/${caseId}`)}
                    className="px-5 py-2.5 border border-border text-foreground text-sm font-medium rounded-xl hover:bg-muted transition-colors"
                  >
                    Open my case
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground border-t border-border/60 pt-4">
                If you need help right now: <a href="tel:112" className="text-primary font-semibold hover:underline">112</a> for emergencies,{' '}
                <a href="tel:181" className="text-primary font-semibold hover:underline">181</a> for the women helpline.
              </p>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────
  // STEP 1: PREMIUM EDITORIAL HOMEPAGE
  // ─────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col selection:bg-primary/20">

      {/* ── Urgent Help Bar (Discrete, Not Aggressive) ────────── */}
      {/* The first thing on the page, so it carries the brand colour rather
          than sitting in grey — but muted enough that it does not shout at
          someone who is not in danger. Numbers are set large in Playfair
          because the number is the useful part; the label is not. */}
      <aside
        className="w-full border-b border-primary/15 bg-primary/[0.055] px-4 py-3 sm:px-8"
        aria-label="Immediate Emergency Help"
      >
        <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <p className="flex items-center gap-2.5 text-xs text-muted-foreground">
            <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
              <span className="absolute inline-flex h-full w-full rounded-full bg-primary/60 motion-safe:animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
            </span>
            <span className="font-medium text-foreground">In immediate danger?</span>
            <span className="hidden sm:inline">These lines answer 24/7, anywhere in India.</span>
          </p>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            {[
              { n: '112', label: 'Emergency' },
              { n: '181', label: 'Women helpline' },
              { n: '1091', label: 'Women police' },
            ].map((line) => (
              <a
                key={line.n}
                href={`tel:${line.n}`}
                className="group flex items-baseline gap-1.5 transition-colors hover:text-primary"
              >
                <span className="font-serif text-lg leading-none text-foreground transition-colors group-hover:text-primary">
                  {line.n}
                </span>
                <span className="text-[11px] text-muted-foreground transition-colors group-hover:text-primary">
                  {line.label}
                </span>
              </a>
            ))}
          </div>
        </div>
      </aside>

      {/* ── THE OPENING ──────────────────────────────────────────
          There is no marketing hero above this any more.

          What was there was the standard arrangement: eyebrow, headline,
          paragraph, two buttons, a row of ticks, an image — six things
          competing, and a "Tell HerWay what happened ↓" button whose entire
          job was to scroll past itself to this form.

          Nobody arrives here browsing. They arrive with something that has
          happened to them. So the page opens with the question and the place
          to answer it, and the pitch is simply gone. The headline spans the
          full width; underneath, the writing surface takes the larger column
          and the illustration sits quietly beside it. */}
      <section
        id="tell-herway"
        ref={inputSectionRef}
        className="px-4 sm:px-8 pt-10 sm:pt-14 pb-16 sm:pb-20 border-b border-border/60 scroll-mt-14"
      >
        <div className="mx-auto max-w-6xl">
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.22, 0.61, 0.36, 1] }}
            className="max-w-3xl"
          >
            <h1 className="font-serif text-[2.5rem] font-normal leading-[1.05] tracking-tight text-foreground sm:text-6xl lg:text-7xl">
              You don&apos;t have to figure
              <br className="hidden sm:block" /> it out{' '}
              <span className="italic text-primary">alone.</span>
            </h1>
            <p className="mt-5 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg">
              Tell us what&apos;s happening. HerWay looks up the current law, helplines
              and nearby help in India, and shows you where every answer came from.
            </p>
          </motion.div>

          <div className="mt-10 grid grid-cols-1 gap-8 lg:mt-12 lg:grid-cols-12 lg:gap-10">
            <div className="space-y-6 lg:col-span-7">

          {/* The category list used to be its own section immediately above
              this one — two templated blocks doing the same job, asking you to
              start twice. Folded in here as an optional way in, so there is one
              place to begin instead of two. */}
          <details className="group rounded-xl border border-border/70 bg-muted/20">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm text-muted-foreground transition-colors hover:text-foreground">
              <span>
                Not sure how to start?{' '}
                <span className="text-foreground">Pick something close instead.</span>
              </span>
              <span
                aria-hidden
                className="shrink-0 text-xs text-muted-foreground transition-transform duration-200 group-open:rotate-180"
              >
                ▾
              </span>
            </summary>
            <div className="border-t border-border/70 p-3">
            {/* Category list.
                Rows rather than a card grid. Eight identical bordered rectangles
                read as filler — the eye skims them as one block and lands on
                none. As rows with a hairline between, each one is a line in a
                list you actually read, and the safety entries can carry a
                coloured rule without the whole grid turning into a traffic
                light. */}
            <div className="overflow-hidden rounded-xl border border-border/80 bg-card">
              {CATEGORIES.slice(0, 8).map((cat, index) => {
                const selected = selectedCategory === cat.id;
                const isSafety = cat.group === 'safety';
                return (
                  <button
                    key={cat.id}
                    type="button"
                    onClick={() => scrollToInput(cat.id, cat.starter)}
                    className={`group relative flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors duration-150 sm:px-5 ${
                      index !== 0 ? 'border-t border-border/60' : ''
                    } ${selected ? 'bg-primary/[0.07]' : 'hover:bg-muted/50'}`}
                  >
                    {/* Accent rule. Grows from the top edge on hover, so the row
                        you are pointing at is unmistakable without it jumping. */}
                    <span
                      aria-hidden
                      className={`absolute left-0 top-0 w-[3px] transition-all duration-200 ${
                        isSafety ? 'bg-primary' : 'bg-muted-foreground/40'
                      } ${selected ? 'h-full' : 'h-0 group-hover:h-full'}`}
                    />

                    {/* Index. Playfair numerals give the list an editorial spine
                        and make eight rows scannable by position. */}
                    <span
                      className={`w-6 shrink-0 font-serif text-base tabular-nums transition-colors ${
                        selected ? 'text-primary' : 'text-muted-foreground/50 group-hover:text-primary/70'
                      }`}
                    >
                      {String(index + 1).padStart(2, '0')}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium leading-snug text-foreground">
                        {cat.label}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-muted-foreground">
                        {isSafety ? 'Safety priority' : 'Information & options'}
                      </span>
                    </span>

                    <span
                      aria-hidden
                      className={`shrink-0 text-base transition-all duration-200 ${
                        selected
                          ? 'translate-x-0 text-primary opacity-100'
                          : '-translate-x-1 text-primary opacity-0 group-hover:translate-x-0 group-hover:opacity-100'
                      }`}
                    >
                      →
                    </span>
                  </button>
                );
              })}
            </div>
            </div>
          </details>

          {errorMessage && (
            <div className="p-4 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-800 dark:text-rose-300 text-sm">
              {errorMessage}
            </div>
          )}

          {/* The primary action of the whole product, so it gets a surface of
              its own rather than sitting loose on the page background. The
              rose rule along the top ties it to the brand without another
              coloured panel. */}
          <form
            onSubmit={handleSubmit}
            className="relative space-y-5 overflow-hidden rounded-2xl border border-border/80 bg-card p-5 elevate-1 sm:p-7"
          >
            <span
              aria-hidden
              className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-primary via-primary/70 to-transparent"
            />
            {/* Category selection */}
            <div className="space-y-1.5">
              <label htmlFor="category-select" className="text-xs font-medium text-muted-foreground">
                Category
              </label>
              <select
                id="category-select"
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-input bg-card text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors cursor-pointer"
              >
                {CATEGORIES.map((cat) => (
                  <option key={cat.id} value={cat.id}>
                    {cat.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Main Situation Input */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="situation-textarea" className="text-xs font-medium text-muted-foreground">
                  Your situation description
                </label>
                {/* Turns amber until the minimum is met, so the requirement is
                    visible while typing rather than only on submit. */}
                <span
                  className={`text-[11px] tabular-nums transition-colors ${
                    situationText.length === 0
                      ? 'text-muted-foreground'
                      : situationText.length < 10
                        ? 'text-amber-600 dark:text-amber-400'
                        : 'text-emerald-600 dark:text-emerald-400'
                  }`}
                >
                  {situationText.length < 10
                    ? `${situationText.length} / 10 characters`
                    : `${situationText.length} characters`}
                </span>
              </div>
              <textarea
                id="situation-textarea"
                rows={7}
                value={situationText}
                onChange={(e) => {
                  setSituationText(e.target.value);
                  // Once she has changed the words it is her situation, not a
                  // demo, and must not be filed as one.
                  if (demoScenarioId) setDemoScenarioId(null);
                }}
                placeholder="You can start anywhere — what happened, when it started, or just how it has been feeling."
                className="custom-scrollbar w-full resize-y rounded-xl border border-input bg-background p-4 text-[15px] leading-relaxed text-foreground transition-all placeholder:text-muted-foreground/60 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              {/* Dictation. Typing out what happened is hardest exactly when
                  you are most upset, and harder again if you think in Hindi and
                  the box expects English. Runs entirely in the browser. */}
              <VoiceInput
                onTranscript={(text) =>
                  setSituationText((prev) => (prev ? `${prev} ${text}` : text))
                }
              />

              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Plain words are enough — in English, Hindi or a mix of both. You do not
                need the right legal terms, and you can leave out anything you would
                rather not write down.
              </p>

              {/* Shortcuts, directly under the box they fill. */}
              <div className="pt-2">
                <DemoScenarios onPick={applyDemoScenario} />
              </div>
            </div>

            {/* Location — optional, never assumed */}
            <div className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                Where are you? (optional — helps us find One Stop Centres, women police
                stations and legal aid near you)
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <input
                  id="location-city"
                  type="text"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  placeholder="City or district"
                  aria-label="City or district"
                  autoComplete="address-level2"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-input bg-card text-foreground text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
                />
                <select
                  id="location-state"
                  value={stateRegion}
                  onChange={(e) => setStateRegion(e.target.value)}
                  aria-label="State or Union Territory"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-input bg-card text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors cursor-pointer"
                >
                  <option value="">State or Union Territory</option>
                  {ALL_INDIAN_REGIONS.map((region) => (
                    <option key={region} value={region}>
                      {region}
                    </option>
                  ))}
                </select>
              </div>
              <p className="text-[11px] text-muted-foreground">
                If you leave this blank, HerWay will show national resources and will not
                guess where you are.
              </p>
            </div>

            {/* Actions and an accurate privacy note */}
            <div className="pt-2 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <p className="text-xs text-muted-foreground text-left leading-relaxed max-w-sm">
                <strong className="text-foreground">Privacy:</strong> what you write is saved to
                your case so you can come back to it, and is never shared or posted publicly.
                Searches are sent without your name or contact details.{' '}
                <Link href="/privacy" className="text-primary hover:underline">
                  What this does and does not protect
                </Link>
              </p>

              <button
                type="submit"
                disabled={isSubmitting || situationText.trim().length < 10}
                className="w-full sm:w-auto px-8 py-3.5 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground font-medium text-sm rounded-xl transition-all shadow-sm whitespace-nowrap"
              >
                {isSubmitting ? 'Saving your case…' : 'Continue →'}
              </button>
            </div>
          </form>

          {/* Three things worth knowing before you type, and the line saying
              where the lookups come from. Deliberately quiet — this is a
              footer note, not a claim. */}
          <div className="space-y-3 rounded-xl border border-border/70 bg-muted/20 px-4 py-3">
            <ul className="flex flex-col gap-2 text-[11px] text-muted-foreground sm:flex-row sm:flex-wrap sm:gap-x-5">
              {[
                'Every answer links to its source',
                'Private by default — no account needed',
                'Press ESC to leave instantly',
              ].map((item) => (
                <li key={item} className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="h-1 w-1 shrink-0 rounded-full bg-muted-foreground/60"
                  />
                  {item}
                </li>
              ))}
            </ul>

            <p className="flex items-center gap-1.5 border-t border-border/60 pt-2.5 text-[11px] text-muted-foreground">
              {/* Read from /health, so this reflects the server actually
                  answering rather than what the code hopes is configured. */}
              {serpapiUp !== null && (
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    serpapiUp ? 'bg-emerald-500' : 'bg-amber-500'
                  }`}
                />
              )}
              Live search by SerpApi · Google Search, Maps, News
              {serpapiUp === false && (
                <span className="text-amber-700 dark:text-amber-400">
                  — not configured on this server
                </span>
              )}
            </p>
          </div>
            </div>

            {/* The illustration, now a companion to the form rather than a
                competitor to the headline. It carries the three things HerWay
                will actually do with what you write — which is more use beside
                an empty textarea than a row of ticks under a slogan was. */}
            <motion.aside
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.14, duration: 0.45, ease: [0.22, 0.61, 0.36, 1] }}
              className="lg:col-span-5"
            >
              <div className="overflow-hidden rounded-2xl border border-border/80 bg-card elevate-2">
                <div className="relative aspect-[4/3] w-full bg-muted/40 lg:aspect-[4/5]">
                  <Image
                    src="/images/haven-hero.jpg"
                    alt="Editorial illustration of a woman: calm strength, quiet resilience, dignity"
                    fill
                    priority
                    sizes="(max-width: 1024px) 100vw, 420px"
                    className="object-cover object-center"
                  />
                </div>

                <ul className="divide-y divide-border/60">
                  {[
                    ['Private', 'Nothing you write is posted publicly, ever.'],
                    ['Sourced', 'Every claim links to where it came from.'],
                    ['Current', 'Looked up now, not recalled from training data.'],
                  ].map(([label, detail]) => (
                    <li key={label} className="flex gap-3 px-4 py-3">
                      <span className="w-16 shrink-0 font-serif text-sm text-primary">
                        {label}
                      </span>
                      <span className="text-xs leading-relaxed text-muted-foreground">
                        {detail}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </motion.aside>
          </div>
        </div>
      </section>

      {/* ── STORYTELLING: From Confusion to a Clearer Next Step ─ */}
      <section className="px-4 sm:px-8 py-20 sm:py-28 bg-muted/15">
        <div className="max-w-6xl mx-auto space-y-14">
          <div className="space-y-3">
            <span className="inline-flex items-center gap-2.5 text-xs uppercase tracking-[0.16em] font-semibold text-primary before:block before:h-px before:w-6 before:bg-primary/60 before:content-['']">
              How it works
            </span>
            <h2 className="font-serif text-3xl sm:text-4xl text-foreground font-normal tracking-tight">
              From confusion to a clearer next step.
            </h2>
            <p className="text-sm sm:text-base text-muted-foreground max-w-2xl leading-relaxed">
              Generic advice can be dangerous when safety is involved. Here is the sequence
              HerWay actually runs, and what you get to see at each stage.
            </p>
          </div>

          {/* A sequence, drawn as one.
              Four separate bordered columns described a process but did not
              look like one — nothing connected step 1 to step 2. A single rule
              running behind the numbers does, and the steps reveal in order as
              you scroll so the eye travels the way the process does. */}
          <ol className="relative grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-4">
            {/* The connecting line, behind the markers. Fades at the end rather
                than stopping dead, because the process continues past step 4. */}
            <span
              aria-hidden
              className="absolute left-0 right-0 top-[7px] hidden h-px bg-gradient-to-r from-primary/40 via-primary/25 to-transparent lg:block"
            />

            {[
              {
                title: 'Tell us what happened',
                body: 'Speak freely in plain words without needing legal terminology. HerWay separates objective facts from uncertainties.',
              },
              {
                title: 'Live, targeted research',
                body: 'We query current statutes (PWDVA, POSH, IPC/BNS), national portals, and physical crisis desks specific to your location.',
              },
              {
                title: 'You can see every source',
                body: 'Each recommendation links to where it came from, and each resource is labelled by how far we could check it — official government page, likely official, or an unverified listing you should confirm first.',
              },
              {
                title: 'Actionable safety plan',
                body: 'Practical steps organised by urgency: right now, next 24 hours, evidence preservation, and ongoing follow-up.',
              },
            ].map((step, index) => (
              <motion.li
                key={step.title}
                initial={{ opacity: 0, y: 14 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '0px 0px -80px 0px' }}
                transition={{ delay: index * 0.08, duration: 0.3, ease: [0.22, 0.61, 0.36, 1] }}
                className="relative space-y-3 pt-6"
              >
                {/* Marker sits on the line. The ring is the page background so
                    the rule appears to pass behind it. */}
                <span
                  aria-hidden
                  className="absolute left-0 top-1 block h-3 w-3 rounded-full border-2 border-primary bg-background ring-4 ring-background"
                />
                <span className="block font-serif text-sm tabular-nums text-primary">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <h3 className="font-serif text-lg font-normal text-foreground">{step.title}</h3>
                <p className="text-xs leading-relaxed text-muted-foreground sm:text-sm">
                  {step.body}
                </p>
              </motion.li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── RESEARCH VISUALIZATION: Trust & Verification ─────── */}
      <section className="px-4 sm:px-8 py-16 sm:py-24 border-y border-border/60">
        <div className="max-w-4xl mx-auto space-y-10">
          <div className="space-y-2">
            <span className="inline-flex items-center gap-2.5 text-xs uppercase tracking-[0.16em] font-semibold text-primary before:block before:h-px before:w-6 before:bg-primary/60 before:content-['']">
              Where answers come from
            </span>
            <h2 className="font-serif text-3xl sm:text-4xl text-foreground font-normal tracking-tight">
              Current information, not yesterday&apos;s answer.
            </h2>
            <p className="text-sm sm:text-base text-muted-foreground max-w-2xl leading-relaxed">
              Helpline numbers move, offices close, procedures get amended. HerWay looks them
              up when you ask rather than repeating what a model memorised.
            </p>
          </div>

          {/* The three provenance levels the product actually uses.
              This was four cards with emerald / blue / amber / purple badges —
              colours chosen for variety, carrying no meaning, which is the
              surest sign a UI was assembled rather than designed. Worse, one
              card promised "Verified Nearby Locations", which is the opposite
              of what HerWay does: a map listing is never presented as checked.
              These now mirror `ResourceVerification` in the backend, so the
              page describes the real system and the colour means something. */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {[
              {
                tier: 'Official source',
                dot: 'bg-emerald-500',
                ring: 'group-hover:border-emerald-500/40',
                title: 'A government page said so',
                body: 'Statutory provisions and helplines traced to PWDVA 2005, POSH Act 2013, NCW, NALSA or a .gov.in / .nic.in page we can link you to.',
              },
              {
                tier: 'Likely official',
                dot: 'bg-sky-500',
                ring: 'group-hover:border-sky-500/40',
                title: 'Strong signals, not confirmed',
                body: 'A listing that looks like a One Stop Centre or Mahila Thana — the name and domain line up, but we could not reach an official page saying so.',
              },
              {
                tier: 'Unverified listing',
                dot: 'bg-amber-500',
                ring: 'group-hover:border-amber-500/40',
                title: 'Found, and shown as found',
                body: 'A public map result. It does not confirm the place is open, operating or suitable. Call before you travel — HerWay will say this every time.',
              },
            ].map((level, index) => (
              <motion.div
                key={level.tier}
                initial={{ opacity: 0, y: 14 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '0px 0px -60px 0px' }}
                transition={{ delay: index * 0.07, duration: 0.3, ease: [0.22, 0.61, 0.36, 1] }}
                className={`group space-y-2.5 rounded-xl border border-border/80 bg-card p-5 transition-colors ${level.ring}`}
              >
                <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className={`h-1.5 w-1.5 rounded-full ${level.dot}`} aria-hidden />
                  {level.tier}
                </span>
                <h3 className="font-serif text-base font-normal text-foreground">{level.title}</h3>
                <p className="text-xs leading-relaxed text-muted-foreground">{level.body}</p>
              </motion.div>
            ))}
          </div>

          <p className="max-w-2xl text-xs leading-relaxed text-muted-foreground">
            Every resource HerWay shows you carries one of these three labels. Nothing is
            presented as checked when it was not.
          </p>
        </div>
      </section>

      {/* ── ORIGINAL HERWAY FEATURES (Secondary & Clean) ───────── */}
      <section id="editorial-support" className="px-4 sm:px-8 py-12 sm:py-16 border-b border-border/60">
        <div className="max-w-5xl mx-auto space-y-6">
          <div className="space-y-2">
            <span className="inline-flex items-center gap-2.5 text-xs uppercase tracking-[0.16em] font-semibold text-primary before:block before:h-px before:w-6 before:bg-primary/60 before:content-['']">
              Everything else
            </span>
            <h2 className="font-serif text-2xl sm:text-3xl text-foreground font-normal tracking-tight">
              What you can do here.
            </h2>
          </div>

          {/* Was a row of "Need legal information? → LawBot" questions, which
              asked you to read five prompts before finding the one that
              applied. Tiles name the thing and say what it does. */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[
              { href: '/discover', icon: '📍', name: 'Find places', line: 'One Stop Centres, women police stations and legal aid near you.' },
              { href: '/lawbot', icon: '⚖️', name: 'LawBot', line: 'Your rights and options under Indian law, answered from sources.' },
              { href: '/safety-center', icon: '🛡️', name: 'Safety Center', line: 'Your own plan, trusted contacts and check-ins in one place.' },
              { href: '/therapybot', icon: '💬', name: 'Talk to Niva', line: 'Someone to talk to when the first thing you need is not a procedure.' },
              { href: '/community', icon: '👥', name: 'Community', line: 'Others working through similar situations, kept apart from your cases.' },
              { href: '/discreet-message', icon: '🖼️', name: 'Discreet message', line: 'Hide a message inside a photo. Concealment, not encryption.' },
            ].map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="group rounded-xl border border-border/80 bg-card p-4 transition-colors elevate-1 hover:border-primary/40"
              >
                <div className="flex items-center gap-2.5">
                  <span aria-hidden className="text-base">
                    {item.icon}
                  </span>
                  <h3 className="flex-1 text-sm font-medium text-foreground">{item.name}</h3>
                  <span
                    aria-hidden
                    className="shrink-0 -translate-x-1 text-primary opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100"
                  >
                    →
                  </span>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  {item.line}
                </p>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ── EDITORIAL FOOTER ─────────────────────────────────── */}
      <footer className="px-4 sm:px-8 py-12 bg-background border-t border-border/80">
        <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-start md:items-center justify-between gap-8 text-xs text-muted-foreground">
          <div className="space-y-1.5 max-w-sm">
            <div className="flex items-center gap-2">
              <span className="w-5 h-5 rounded bg-primary text-primary-foreground font-bold text-xs flex items-center justify-center">
                HW
              </span>
              <span className="font-semibold text-sm text-foreground">HerWay</span>
            </div>
            <p className="text-muted-foreground leading-relaxed">
              A private, trauma-informed intelligence platform helping women navigate difficult situations with verified facts and safety plans.
            </p>
          </div>

          <div className="flex items-center gap-6 flex-wrap">
            <Link href="/cases" className="hover:text-foreground transition-colors">
              My Cases
            </Link>
            <Link href="/lawbot" className="hover:text-foreground transition-colors">
              LawBot
            </Link>
            <Link href="/therapybot" className="hover:text-foreground transition-colors">
              Talk to Niva
            </Link>
            <Link href="/community" className="hover:text-foreground transition-colors">
              Community
            </Link>
            <Link href="/discreet-message" className="hover:text-foreground transition-colors">
              Discreet message
            </Link>
            <button
              type="button"
              onClick={handleQuickExit}
              className="px-3 py-1 bg-primary text-primary-foreground rounded-md font-semibold text-[11px] hover:bg-primary/90 transition-colors"
            >
              Quick Exit (ESC)
            </button>
          </div>
        </div>
      </footer>

    </div>
  );
}
