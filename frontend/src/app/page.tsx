'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';

import { apiPost } from '@/lib/api';
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
            <span className="text-xs uppercase tracking-wider font-semibold text-primary">
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
                <span className="text-xs uppercase tracking-wider font-semibold text-primary">
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
      <aside
        className="w-full border-b border-border/80 bg-muted/40 py-2.5 px-4 sm:px-8"
        aria-label="Immediate Emergency Help"
      >
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2.5 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-primary shrink-0" aria-hidden="true" />
            <span className="font-medium text-foreground">In immediate danger?</span>
            <span>Emergency helplines are available 24/7 across India & international lines:</span>
          </div>
          <div className="flex items-center gap-4 flex-wrap font-mono text-[11px] font-semibold text-foreground">
            <a href="tel:112" className="hover:text-primary transition-colors underline-offset-4 hover:underline">
              112 (National Emergency)
            </a>
            <span aria-hidden="true" className="opacity-40">·</span>
            <a href="tel:181" className="hover:text-primary transition-colors underline-offset-4 hover:underline">
              181 (Women Helpline)
            </a>
            <span aria-hidden="true" className="opacity-40">·</span>
            <a href="tel:1091" className="hover:text-primary transition-colors underline-offset-4 hover:underline">
              1091 (Women Police)
            </a>
          </div>
        </div>
      </aside>

      {/* ── HERO SECTION: Editorial Asymmetry ────────────────── */}
      <section className="relative px-4 sm:px-8 pt-10 sm:pt-16 pb-16 sm:pb-24 border-b border-border/60">
        <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 items-center">

          {/* Left Column: Editorial Headline & Restrained Copy (7 cols) */}
          <div className="lg:col-span-7 space-y-6 sm:space-y-8">
            <div className="space-y-3">
              <span className="inline-block text-[11px] tracking-[0.2em] font-medium text-primary uppercase">
                HerWay · Women&apos;s Safety &amp; Resource Intelligence
              </span>

              <h1 className="font-serif text-4xl sm:text-6xl lg:text-[4.25rem] font-normal leading-[1.08] tracking-tight text-foreground">
                You don&apos;t have to figure it out{' '}
                <span className="italic font-normal text-primary">alone.</span>
              </h1>
            </div>

            <p className="text-base sm:text-lg text-muted-foreground leading-relaxed max-w-xl font-normal">
              When something doesn&apos;t feel right, HerWay helps you understand what is happening,
              find trustworthy current resources, and figure out safer next steps.
            </p>

            {/* Hero CTAs */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-2">
              <button
                type="button"
                onClick={() => scrollToInput()}
                className="px-6 py-3.5 bg-primary text-primary-foreground font-medium text-sm rounded-xl hover:bg-primary/90 transition-all shadow-sm flex items-center justify-center gap-2 group"
              >
                <span>Tell HerWay what happened</span>
                <span className="transition-transform group-hover:translate-y-0.5">↓</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  const el = document.getElementById('editorial-support');
                  el?.scrollIntoView({ behavior: 'smooth' });
                }}
                className="px-5 py-3.5 border border-border/80 text-foreground font-medium text-sm rounded-xl hover:bg-muted/60 transition-colors flex items-center justify-center"
              >
                Explore support options →
              </button>
            </div>

            {/* What HerWay actually does — claims we can stand behind */}
            <div className="pt-2 flex items-center gap-6 text-xs text-muted-foreground flex-wrap">
              <span className="flex items-center gap-1.5">
                <span className="text-emerald-500 font-bold">✓</span> Private — never posted publicly
              </span>
              <span className="flex items-center gap-1.5">
                <span className="text-emerald-500 font-bold">✓</span> Official Indian government sources first
              </span>
              <span className="flex items-center gap-1.5">
                <span className="text-emerald-500 font-bold">✓</span> Every claim shows its source
              </span>
            </div>
          </div>

          {/* Right Column: Fine Art Editorial Illustration (5 cols) */}
          <div className="lg:col-span-5 flex justify-center lg:justify-end">
            <div className="relative w-full max-w-md">
              {/* Archival border & soft shadow frame */}
              <div className="relative rounded-2xl overflow-hidden border border-border/80 bg-card shadow-lg p-2.5 transition-transform hover:scale-[1.01] duration-500">
                <div className="relative aspect-[4/3] sm:aspect-[3/4] w-full rounded-xl overflow-hidden bg-muted/40">
                  <Image
                    src="/images/haven-hero.jpg"
                    alt="Editorial fine-art illustration representing a woman of calm strength, quiet resilience, and dignity"
                    fill
                    priority
                    sizes="(max-width: 768px) 100vw, (max-width: 1200px) 45vw, 480px"
                    className="object-cover object-center"
                  />
                </div>

                <div className="pt-3 px-2 pb-1 text-center">
                  <p className="font-serif italic text-xs text-muted-foreground leading-normal">
                    &ldquo;A safe, judgment-free space to find your footing and know your rights.&rdquo;
                  </p>
                </div>
              </div>
            </div>
          </div>

        </div>
      </section>

      {/* ── SECTION: "You Can Come Here With Anything" ───────── */}
      <section className="px-4 sm:px-8 py-14 sm:py-20 border-b border-border/60 bg-muted/20">
        <div className="max-w-5xl mx-auto space-y-8">
          <div className="space-y-2">
            <span className="text-xs uppercase tracking-wider font-semibold text-primary">
              Where to start
            </span>
            <h2 className="font-serif text-2xl sm:text-4xl text-foreground font-normal tracking-tight">
              Some problems are difficult to explain.
            </h2>
            <p className="text-sm sm:text-base text-muted-foreground max-w-2xl leading-relaxed">
              Whether it started with a single uncomfortable interaction or years of quiet control,
              HerWay meets you where you are. Select a context or write freely below.
            </p>
          </div>

          {/* Asymmetric Interactive Category Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
            {CATEGORIES.slice(0, 8).map((cat) => (
              <button
                key={cat.id}
                type="button"
                onClick={() => scrollToInput(cat.id, cat.starter)}
                className={`text-left p-4 rounded-xl border transition-all flex flex-col justify-between gap-3 group ${
                  selectedCategory === cat.id
                    ? 'border-primary bg-primary/8 text-foreground'
                    : 'border-border/80 bg-card hover:border-primary/50 text-foreground'
                }`}
              >
                <div className="space-y-1">
                  <h3 className="text-sm font-medium leading-snug group-hover:text-primary transition-colors">
                    {cat.label}
                  </h3>
                  <span className="text-[11px] text-muted-foreground capitalize">
                    {cat.group === 'safety' ? 'Safety priority' : 'Information & options'}
                  </span>
                </div>
                <span className="text-xs text-primary font-medium flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  Begin here →
                </span>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ── PRIMARY PRODUCT ACTION: What Happened? ───────────── */}
      <section
        id="tell-herway"
        ref={inputSectionRef}
        className="px-4 sm:px-8 py-16 sm:py-24 border-b border-border/60 scroll-mt-14"
      >
        <div className="max-w-3xl mx-auto space-y-8">
          <div className="space-y-2 text-center sm:text-left">
            <span className="text-xs uppercase tracking-wider font-semibold text-primary">
              Interactive Intake
            </span>
            <h2 className="font-serif text-3xl sm:text-4xl text-foreground font-normal tracking-tight">
              What happened?
            </h2>
            <p className="text-sm sm:text-base text-muted-foreground leading-relaxed">
              Describe your situation in your own words. We will analyze the facts, search verified
              resources, and build your personalized next steps.
            </p>
          </div>

          {errorMessage && (
            <div className="p-4 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-800 dark:text-rose-300 text-sm">
              {errorMessage}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
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
                <span className="text-[11px] text-muted-foreground">
                  {situationText.length} characters (minimum 10)
                </span>
              </div>
              <textarea
                id="situation-textarea"
                rows={6}
                value={situationText}
                onChange={(e) => setSituationText(e.target.value)}
                placeholder="Tell HerWay what you're dealing with..."
                className="w-full p-4 rounded-xl border border-input bg-card text-foreground text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-all leading-relaxed custom-scrollbar resize-y"
              />
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
        </div>
      </section>

      {/* ── STORYTELLING: From Confusion to a Clearer Next Step ─ */}
      <section className="px-4 sm:px-8 py-16 sm:py-24 border-b border-border/60 bg-muted/15">
        <div className="max-w-5xl mx-auto space-y-12">
          <div className="space-y-3">
            <span className="text-xs uppercase tracking-wider font-semibold text-primary">
              The Process
            </span>
            <h2 className="font-serif text-3xl sm:text-4xl text-foreground font-normal tracking-tight">
              From confusion to a clearer next step.
            </h2>
            <p className="text-sm sm:text-base text-muted-foreground max-w-2xl leading-relaxed">
              When trauma or safety risks are present, generic advice is dangerous. HerWay runs a
              disciplined, verifiable sequence.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            <div className="space-y-3 border-t border-border/80 pt-4">
              <span className="font-mono text-xs font-semibold text-primary">01</span>
              <h3 className="font-serif text-lg text-foreground font-normal">Tell us what happened</h3>
              <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
                Speak freely in plain words without needing legal terminology. HerWay separates objective
                facts from uncertainties.
              </p>
            </div>

            <div className="space-y-3 border-t border-border/80 pt-4">
              <span className="font-mono text-xs font-semibold text-primary">02</span>
              <h3 className="font-serif text-lg text-foreground font-normal">Live, targeted research</h3>
              <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
                We query current statutes (PWDVA, POSH, IPC/BNS), national portals, and physical crisis
                desks specific to your location.
              </p>
            </div>

            <div className="space-y-3 border-t border-border/80 pt-4">
              <span className="font-mono text-xs font-semibold text-primary">03</span>
              <h3 className="font-serif text-lg text-foreground font-normal">You can see every source</h3>
              <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
                Each recommendation links to where it came from, and each resource is
                labelled by how far we could check it — official government page, likely
                official, or an unverified listing you should confirm first.
              </p>
            </div>

            <div className="space-y-3 border-t border-border/80 pt-4">
              <span className="font-mono text-xs font-semibold text-primary">04</span>
              <h3 className="font-serif text-lg text-foreground font-normal">Actionable safety plan</h3>
              <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
                Receive practical steps organized by urgency: right now, next 24 hours, evidence
                preservation, and ongoing follow-up.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── RESEARCH VISUALIZATION: Trust & Verification ─────── */}
      <section className="px-4 sm:px-8 py-16 sm:py-24 border-b border-border/60">
        <div className="max-w-5xl mx-auto space-y-10">
          <div className="space-y-2">
            <span className="text-xs uppercase tracking-wider font-semibold text-primary">
              Resource Trust
            </span>
            <h2 className="font-serif text-3xl sm:text-4xl text-foreground font-normal tracking-tight">
              Current information, not yesterday&apos;s answer.
            </h2>
            <p className="text-sm sm:text-base text-muted-foreground max-w-2xl leading-relaxed">
              Legal procedures, emergency hotlines, and shelter availability change. HerWay queries live
              search channels rather than relying on memorized LLM data.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-5 rounded-2xl border border-border/80 bg-card space-y-2">
              <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded">
                Official Sources
              </span>
              <h3 className="text-sm font-semibold text-foreground">Government &amp; Statutory Registries</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Direct statutory provisions from PWDVA 2005, POSH Act 2013, NCW, and Sakhi One Stop Centres.
              </p>
            </div>

            <div className="p-5 rounded-2xl border border-border/80 bg-card space-y-2">
              <span className="text-xs font-semibold text-blue-700 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/40 px-2 py-0.5 rounded">
                Local Resources
              </span>
              <h3 className="text-sm font-semibold text-foreground">Verified Nearby Locations</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Structured addresses, operating hours, and retrieved phone numbers for physical women&apos;s desks.
              </p>
            </div>

            <div className="p-5 rounded-2xl border border-border/80 bg-card space-y-2">
              <span className="text-xs font-semibold text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 px-2 py-0.5 rounded">
                Evidence Guidance
              </span>
              <h3 className="text-sm font-semibold text-foreground">Safe Documentation</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Clear protocols for capturing screenshots and timestamps only when your devices are secure.
              </p>
            </div>

            <div className="p-5 rounded-2xl border border-border/80 bg-card space-y-2">
              <span className="text-xs font-semibold text-purple-700 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/20 px-2 py-0.5 rounded">
                Dynamic Adaptation
              </span>
              <h3 className="text-sm font-semibold text-foreground">Living Safety Plans</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                If your situation changes or escalates, return anytime to update HerWay and adapt your plan.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── ORIGINAL HERWAY FEATURES (Secondary & Clean) ───────── */}
      <section id="editorial-support" className="px-4 sm:px-8 py-16 sm:py-24 border-b border-border/60 bg-muted/15">
        <div className="max-w-5xl mx-auto space-y-8">
          <div className="space-y-2">
            <span className="text-xs uppercase tracking-wider font-semibold text-primary">
              Additional Support
            </span>
            <h2 className="font-serif text-2xl sm:text-3xl text-foreground font-normal tracking-tight">
              Other ways HerWay can support you today.
            </h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <Link
              href="/lawbot"
              className="p-5 rounded-2xl border border-border/80 bg-card hover:border-primary/50 transition-colors space-y-2 group"
            >
              <span className="text-xs text-muted-foreground">Need legal information?</span>
              <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors flex items-center justify-between">
                <span>LawBot</span>
                <span>→</span>
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Explore legal acts, protection orders, and legal aid rights.
              </p>
            </Link>

            <Link
              href="/therapybot"
              className="p-5 rounded-2xl border border-border/80 bg-card hover:border-primary/50 transition-colors space-y-2 group"
            >
              <span className="text-xs text-muted-foreground">Need someone to talk to?</span>
              <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors flex items-center justify-between">
                <span>Talk to Niva</span>
                <span>→</span>
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                A calm, trauma-informed supportive companion with voice support.
              </p>
            </Link>

            <Link
              href="/community"
              className="p-5 rounded-2xl border border-border/80 bg-card hover:border-primary/50 transition-colors space-y-2 group"
            >
              <span className="text-xs text-muted-foreground">Want to connect?</span>
              <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors flex items-center justify-between">
                <span>Community</span>
                <span>→</span>
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Read anonymous shared experiences and peer encouragement.
              </p>
            </Link>

            <Link
              href="/discreet-message"
              className="p-5 rounded-2xl border border-border/80 bg-card hover:border-primary/50 transition-colors space-y-2 group"
            >
              <span className="text-xs text-muted-foreground">Need discreet help?</span>
              <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors flex items-center justify-between">
                <span>Discreet Message</span>
                <span>→</span>
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Hide text inside an ordinary image using steganography.
              </p>
            </Link>

            <Link
              href="/cases"
              className="p-5 rounded-2xl border border-border/80 bg-card hover:border-primary/50 transition-colors space-y-2 group"
            >
              <span className="text-xs text-muted-foreground">Saved plans?</span>
              <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors flex items-center justify-between">
                <span>My Cases</span>
                <span>→</span>
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Access your ongoing safety plans, actions, and research trails.
              </p>
            </Link>
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
