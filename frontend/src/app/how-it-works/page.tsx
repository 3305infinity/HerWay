'use client';

/**
 * How HerWay works — the product and the stack behind it.
 *
 * Written against the code, not against the env template. Every technology
 * listed here is actually wired in and doing the job described; anything
 * configured-but-unverified is labelled as such, because a page explaining how
 * a safety product works is the last place to overstate what it does.
 *
 * Live status comes from `GET /health`, so a reader sees what is actually
 * running on this deployment rather than an aspirational list.
 */

import React from 'react';
import Link from 'next/link';

import { apiGet } from '@/lib/api';
import { Reveal } from '@/components/motion/Reveal';

type Health = {
  status: string;
  database: string;
  integrations: Record<string, boolean>;
  degraded: string[];
};

const PIPELINE = [
  {
    step: 'Understand',
    agent: 'situation_agent',
    body: 'Your words become a structured situation — what you stated as fact, what you believe, and what is still unknown. These are kept apart: a claim is never promoted to a fact.',
  },
  {
    step: 'Triage',
    agent: 'safety_triage',
    body: 'Urgency is assessed by deterministic rules, not by a model. It can only ever be raised, never lowered, and it works when every AI provider is down.',
  },
  {
    step: 'Plan research',
    agent: 'research_orchestrator',
    body: 'A small number of targeted searches are planned — typically two to four — with a budget, Indian jurisdiction, and personal details stripped before anything leaves the server.',
  },
  {
    step: 'Retrieve',
    agent: 'SerpApi',
    body: 'Live search across the engines that suit the question. Results are cached so the same query is not bought twice.',
  },
  {
    step: 'Verify',
    agent: 'source_verifier',
    body: 'Sources are scored by authority, agreement and contradiction. A .gov.in page and a random blog do not carry the same weight, and disagreement between sources is surfaced rather than averaged away.',
  },
  {
    step: 'Act',
    agent: 'action_planner',
    body: 'Findings become prioritised steps — now, next, alternatives — each keeping the source it came from. Nothing suggests confronting the person causing harm.',
  },
  {
    step: 'Keep',
    agent: 'safety_plan_agent',
    body: 'The result becomes a case and, where relevant, a safety plan you can return to, edit and adapt as things change.',
  },
];

const ENGINES = [
  {
    name: 'Google Search',
    id: 'google',
    retrieves: 'Statutes, official procedures, helpline numbers, government portals',
    why: 'Legal procedure and helpline numbers change, and a model answering from memory will quote a number that was retired two years ago. This retrieves the current page and links you to it.',
    query: 'POSH Act 2013 internal committee complaint procedure site:gov.in',
  },
  {
    name: 'Google News',
    id: 'google_news',
    retrieves: 'Recent public reporting about an area or an ongoing matter',
    why: 'Used sparingly and only when recency matters. Each item is labelled allegation, reported incident or official statement — and a handful of articles can never establish a crime rate.',
    query: 'women safety police advisory Bengaluru recent',
  },
  {
    name: 'Google Maps',
    id: 'google_maps',
    retrieves: 'One Stop Centres, women police stations, hospitals, legal aid, transport',
    why: 'A phone number for a centre in your district is worth more than a national average. Listings are shown with their provenance and never presented as confirmed or verified.',
    query: 'One Stop Centre Lucknow Uttar Pradesh',
  },
];

/** What happens to a result between the search returning and you reading it. */
const RESULT_FLOW = [
  {
    name: 'Plan',
    body: 'Two to four targeted questions are chosen, with an engine for each and a budget. Personal details are stripped before a query is formed.',
  },
  {
    name: 'Search',
    body: 'SerpApi runs them. Results are cached briefly and retried with backoff, so one flaky minute does not become a wrong answer.',
  },
  {
    name: 'Normalise',
    body: 'Web results, map listings and news items become one shape — title, URL, domain, snippet, retrieval time — so everything after this treats them identically.',
  },
  {
    name: 'Verify',
    body: 'Each source is scored, agreement and contradiction between sources are recorded, and every resource gets its provenance label.',
  },
  {
    name: 'Act',
    body: 'What survives becomes prioritised steps, each keeping a link back to the page it came from.',
  },
];

/**
 * The confidence weights, copied from the formula in
 * `backend/agents/source_verifier.py`. If that formula changes, this is wrong.
 */
const SCORE_WEIGHTS = [
  { weight: '0.40', name: 'Authority', body: 'A .gov.in page and an anonymous blog do not carry the same weight.' },
  { weight: '0.25', name: 'Agreement', body: 'Independent sources saying the same thing raise confidence; disagreement is surfaced, not averaged away.' },
  { weight: '0.20', name: 'Directness', body: 'A page that answers the question beats one that merely mentions the topic.' },
  { weight: '0.15', name: 'Freshness', body: 'Recency counts for most where procedure and numbers change.' },
];

const STACK = [
  { name: 'SerpApi', role: 'Live search across Google, News and Maps', detail: 'The retrieval layer the whole product rests on. Cached, budgeted, rate limited, with PII stripped from every query.' },
  { name: 'Google Gemini', role: 'Situation analysis, research planning, verification, drafting', detail: 'Reasoning only. It never supplies facts — those come from search, and when search fails HerWay says so instead of letting the model fill the gap.' },
  { name: 'FastAPI', role: 'Backend, 66 endpoints', detail: 'Ownership checks on every case route, request-scoped trace IDs, per-caller rate limits.' },
  { name: 'Next.js 15', role: 'Frontend, App Router', detail: 'All backend calls go through a same-origin proxy, so the session cookie stays first-party and no API key reaches the browser.' },
  { name: 'MongoDB', role: 'Cases, plans, contacts, check-ins', detail: 'Falls back to in-memory storage when unreachable — and says so on /health rather than pretending to persist.' },
  { name: 'OpenCage', role: 'Reverse geocoding', detail: 'Only when you share coordinates. Without it you type a place name; HerWay never guesses where you are.' },
  { name: 'Clerk', role: 'Optional accounts', detail: 'Without it every visitor gets an isolated anonymous session. Cases are still private — they just do not follow you across devices.' },
];

export default function HowItWorksPage() {
  const [health, setHealth] = React.useState<Health | null>(null);

  React.useEffect(() => {
    apiGet<Health>('/health').then((r) => {
      if (r.ok) setHealth(r.data);
    });
  }, []);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <Reveal as="header" className="mb-10">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-primary">
          How it works
        </p>
        <h1 className="mt-2 font-serif text-3xl font-normal sm:text-4xl">
          Evidence, not guesses.
        </h1>
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-muted-foreground">
          HerWay helps women in India work out what to do about a difficult or
          unsafe situation — harassment at work, threatening messages, an
          unfamiliar area, a journey home late at night. It reads what you write,
          looks up current Indian information for it, shows you where every answer
          came from, and turns that into steps you can choose from.
        </p>
      </Reveal>

      {/* What makes it different */}
      <Reveal className="mb-10">
        <h2 className="mb-3 font-serif text-xl font-normal">Why not just ask a chatbot?</h2>
        <div className="space-y-3 text-sm leading-relaxed text-muted-foreground">
          <p>
            Because a chatbot answers from memory. Ask one for a women&apos;s helpline
            number and it will give you one confidently, whether or not that number
            still works — and you have no way to tell which.
          </p>
          <p>
            HerWay <strong className="text-foreground">looks it up</strong>, shows you
            the page it came from, and tells you when it could not find out. Every
            resource is labelled <em>official source</em>, <em>likely official</em> or{' '}
            <em>unverified listing</em>. When the search fails, it says the search
            failed — it does not quietly answer from the model instead.
          </p>
        </div>
      </Reveal>

      {/* Pipeline */}
      <Reveal className="mb-10">
        <h2 className="mb-1 font-serif text-xl font-normal">The seven steps</h2>
        <p className="mb-4 text-xs text-muted-foreground">
          Separate agents, each with one job. You can watch all of it in the research
          trail on any case.
        </p>
        <ol className="relative space-y-0 border-l border-border/70 pl-6">
          {PIPELINE.map((item, index) => (
            <li key={item.step} className="relative pb-5 last:pb-0">
              <span
                aria-hidden
                className="absolute -left-[1.655rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-primary bg-background"
              />
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-serif text-sm tabular-nums text-primary">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <h3 className="text-sm font-medium text-foreground">{item.step}</h3>
                <code className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {item.agent}
                </code>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.body}</p>
            </li>
          ))}
        </ol>
      </Reveal>

      {/* Engines */}
      <Reveal className="mb-10">
        <h2 className="mb-1 font-serif text-xl font-normal">What we search, and why</h2>
        <p className="mb-4 text-xs text-muted-foreground">
          Only engines that suit the question — not every engine for every request.
        </p>
        <div className="space-y-3">
          {ENGINES.map((engine) => (
            <div key={engine.id} className="rounded-xl border border-border/80 bg-card p-4 elevate-1">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-foreground">{engine.name}</h3>
                <code className="text-[10px] text-muted-foreground">{engine.id}</code>
              </div>
              <p className="mt-1.5 text-xs text-foreground">{engine.retrieves}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{engine.why}</p>
              <p className="mt-2 text-[11px] text-muted-foreground">
                Query it runs:{' '}
                <code className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-foreground">
                  {engine.query}
                </code>
              </p>
            </div>
          ))}
        </div>

        {/* What happens between the search returning and you reading it.
            Deliberately placed inside this section rather than beside the
            seven steps above — it is one of those steps, in detail. */}
        <h3 className="mb-1 mt-7 font-serif text-base font-normal">
          What happens to a result
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Between the search returning and you reading it.
        </p>
        <ol className="grid grid-cols-1 gap-2.5 sm:grid-cols-5">
          {RESULT_FLOW.map((stage, index) => (
            <li key={stage.name} className="rounded-xl border border-border/80 bg-card p-3 elevate-1">
              <span className="font-serif text-xs tabular-nums text-primary">
                {String(index + 1).padStart(2, '0')}
              </span>
              <h4 className="mt-0.5 text-xs font-medium text-foreground">{stage.name}</h4>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {stage.body}
              </p>
            </li>
          ))}
        </ol>

        <h3 className="mb-1 mt-7 font-serif text-base font-normal">How a source is scored</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          One confidence figure per source, from four weighted parts.
        </p>
        <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/80 bg-card elevate-1">
          {SCORE_WEIGHTS.map((s) => (
            <li key={s.name} className="flex items-baseline gap-3 px-4 py-2.5 sm:gap-4">
              <span className="w-9 shrink-0 font-serif text-sm tabular-nums text-primary">
                {s.weight}
              </span>
              <span className="w-20 shrink-0 text-xs font-medium text-foreground sm:w-24">
                {s.name}
              </span>
              <span className="text-[11px] leading-relaxed text-muted-foreground">{s.body}</span>
            </li>
          ))}
        </ul>
      </Reveal>

      {/* Stack */}
      <Reveal className="mb-10">
        <h2 className="mb-1 font-serif text-xl font-normal">What it is built on</h2>
        <p className="mb-4 text-xs text-muted-foreground">
          Everything listed is wired in and doing the job described.
        </p>
        <ul className="divide-y divide-border/60 border-y border-border/60">
          {STACK.map((tech) => {
            const key = tech.name.toLowerCase().split(' ')[0];
            const live = health?.integrations?.[key === 'google' ? 'gemini' : key];
            return (
              <li key={tech.name} className="py-3">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <h3 className="text-sm font-medium text-foreground">{tech.name}</h3>
                  <span className="text-xs text-muted-foreground">— {tech.role}</span>
                  {/* Live status, so this page reflects the deployment rather
                      than an aspirational list. */}
                  {health && live !== undefined && (
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        live
                          ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                          : 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
                      }`}
                    >
                      {live ? 'configured' : 'not configured here'}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{tech.detail}</p>
              </li>
            );
          })}
        </ul>

        {health && (
          <p className="mt-3 text-[11px] text-muted-foreground">
            Status read live from <code className="text-foreground">/health</code>. Storage:{' '}
            <strong className="text-foreground">{health.database}</strong>
            {health.database === 'in-memory' && ' — data is lost when the server restarts.'}
          </p>
        )}
      </Reveal>

      {/* Limits — the section most products leave out */}
      <Reveal className="mb-10">
        <h2 className="mb-3 font-serif text-xl font-normal">What HerWay does not do</h2>
        <ul className="space-y-2 text-sm leading-relaxed text-muted-foreground">
          {[
            'It does not monitor you. A check-in is a note to yourself — nobody is watching a timer and nobody is alerted if it passes.',
            'It does not send messages. Sharing opens your own WhatsApp, SMS or email with the text filled in. HerWay cannot confirm anything was delivered.',
            'It does not call anyone for you, and cannot tell anyone where you are.',
            'It does not say whether a place is safe. Search results cannot establish that, so there is no safety score anywhere in this product.',
            'It is not a lawyer. It finds legal information and links you to the source; it does not advise you or guarantee an outcome.',
            'Quick Exit leaves the page immediately, but it cannot erase your browser history.',
          ].map((item) => (
            <li key={item} className="flex gap-2.5">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/60" />
              {item}
            </li>
          ))}
        </ul>
      </Reveal>

      <Reveal className="rounded-xl border border-border/80 bg-card p-5 elevate-1">
        <h2 className="font-serif text-lg font-normal">See it run</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          The common situations on the home page go through this exact pipeline —
          real analysis, real search, real sources. Anything they create is yours
          to delete.
        </p>
        <Link
          href="/"
          className="mt-4 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Try a situation →
        </Link>
      </Reveal>
    </main>
  );
}
