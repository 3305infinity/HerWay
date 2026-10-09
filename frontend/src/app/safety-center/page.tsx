'use client';

/**
 * Safety Center — plans, trusted contacts and check-ins.
 *
 * Two things this page refuses to do, because doing them would be worse than
 * not having the feature:
 *
 * 1. **It never implies monitoring.** Starting a check-in shows, in plain
 *    words, that nobody is watching the clock and nobody will be alerted. A
 *    reassuring timer backed by nothing is the most dangerous thing a safety
 *    product can ship.
 * 2. **It never implies delivery.** Sharing opens the user's own messaging app
 *    with text pre-filled. The page says so before and after.
 *
 * Emergency numbers sit at the top and are plain `tel:` links — they work with
 * no account, no plan, no network call and no JavaScript beyond rendering.
 */

import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';

import { apiDelete, apiGet, apiPatch, apiPost } from '@/lib/api';
import { Reveal } from '@/components/motion/Reveal';
import { fadeUp, slideInRight } from '@/lib/motion';

type PlanStep = {
  id: string;
  text: string;
  origin: 'user' | 'accepted_suggestion' | 'suggested';
  status: 'todo' | 'done' | 'not_applicable';
  user_edited_text: string | null;
  source_urls: string[];
};

type Plan = {
  id: string;
  title: string;
  purpose: string | null;
  status: 'active' | 'paused' | 'archived';
  steps: PlanStep[];
  suggestions: PlanStep[];
  contact_ids: string[];
  case_id: string | null;
  updated_at: string;
};

type Contact = {
  id: string;
  display_name: string;
  method: 'phone' | 'email' | 'other';
  value: string | null;
  relationship: string | null;
  enabled: boolean;
  contact_has_consented: boolean;
};

type CheckIn = {
  id: string;
  status: 'active' | 'completed_safe' | 'cancelled' | 'overdue';
  destination: string | null;
  expected_back_at: string | null;
  started_at: string;
  is_overdue?: boolean;
};

type ShareDraft = {
  message: string;
  recipient_name: string | null;
  wa_me_url: string | null;
  sms_url: string | null;
  mailto_url: string | null;
  notice: string;
};

function Section({
  title,
  children,
  action,
  delay = 0,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  delay?: number;
}) {
  return (
    <Reveal as="section" delay={delay} className="mb-10">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="font-serif text-xl font-normal tracking-tight">{title}</h2>
        {action}
      </div>
      {/* A hairline under the heading gives the page an editorial spine and
          stops the sections running together on a long scroll. */}
      <div className="mb-4 h-px bg-gradient-to-r from-border via-border/60 to-transparent" />
      {children}
    </Reveal>
  );
}

export default function SafetyCenterPage() {
  const [plans, setPlans] = React.useState<Plan[] | null>(null);
  const [contacts, setContacts] = React.useState<Contact[] | null>(null);
  const [checkIns, setCheckIns] = React.useState<CheckIn[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const [newPlanTitle, setNewPlanTitle] = React.useState('');
  const [newContactName, setNewContactName] = React.useState('');
  const [newContactValue, setNewContactValue] = React.useState('');
  const [destination, setDestination] = React.useState('');
  const [draft, setDraft] = React.useState<ShareDraft | null>(null);

  const activeCheckIn = checkIns?.find((c) => c.status === 'active') ?? null;

  const load = React.useCallback(async () => {
    const [p, c, k] = await Promise.all([
      apiGet<{ plans: Plan[] }>('/api/v2/safety-center/plans'),
      apiGet<{ contacts: Contact[] }>('/api/v2/safety-center/contacts'),
      apiGet<{ check_ins: CheckIn[] }>('/api/v2/safety-center/check-ins'),
    ]);
    if (p.ok) setPlans(p.data.plans);
    else setError(p.error.message);
    if (c.ok) setContacts(c.data.contacts);
    if (k.ok) setCheckIns(k.data.check_ins);
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  async function createPlan(e: React.FormEvent) {
    e.preventDefault();
    if (!newPlanTitle.trim()) return;
    setBusy(true);
    const result = await apiPost<Plan>('/api/v2/safety-center/plans', {
      title: newPlanTitle.trim(),
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setNewPlanTitle('');
    load();
  }

  async function archivePlan(id: string) {
    // Archiving is reversible, so no confirmation. Deletion below is not.
    await apiPatch(`/api/v2/safety-center/plans/${id}`, { status: 'archived' });
    load();
  }

  async function deletePlan(id: string, title: string) {
    if (!window.confirm(`Delete "${title}"? This cannot be undone.`)) return;
    await apiDelete(`/api/v2/safety-center/plans/${id}`);
    load();
  }

  async function addContact(e: React.FormEvent) {
    e.preventDefault();
    if (!newContactName.trim()) return;
    setBusy(true);
    const result = await apiPost<Contact>('/api/v2/safety-center/contacts', {
      display_name: newContactName.trim(),
      method: newContactValue.includes('@') ? 'email' : 'phone',
      value: newContactValue.trim() || null,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setNewContactName('');
    setNewContactValue('');
    load();
  }

  async function removeContact(id: string, name: string) {
    if (!window.confirm(`Remove ${name} from your trusted contacts?`)) return;
    await apiDelete(`/api/v2/safety-center/contacts/${id}`);
    load();
  }

  async function startCheckIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const result = await apiPost<CheckIn>('/api/v2/safety-center/check-ins', {
      destination: destination.trim() || null,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setDestination('');
    load();
  }

  async function resolveCheckIn(id: string, status: 'completed_safe' | 'cancelled') {
    await apiPatch(`/api/v2/safety-center/check-ins/${id}`, { status });
    load();
  }

  async function prepareShare(checkInId: string, contactId?: string) {
    const result = await apiPost<ShareDraft>('/api/v2/safety-center/share-draft', {
      check_in_id: checkInId,
      contact_id: contactId ?? null,
      include_destination: true,
    });
    if (result.ok) setDraft(result.data);
    else setError(result.error.message);
  }

  const loading = plans === null && contacts === null && checkIns === null;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <Reveal>
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-primary">
          Yours alone
        </p>
        <h1 className="mt-2 font-serif text-3xl font-normal sm:text-4xl">Safety Center</h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
          Your plans, the people you trust, and your check-ins. Everything here is
          yours and private to you.
        </p>
      </Reveal>

      {/* Emergency access.
          Deliberately NOT wrapped in Reveal. These three numbers must be on the
          screen the instant it paints — a fade-in, however short, is a delay on
          the one thing that cannot afford one. */}
      <div className="mt-6 overflow-hidden rounded-xl border border-destructive/30 bg-destructive/[0.04]">
        <div className="flex items-center gap-2 border-b border-destructive/20 bg-destructive/[0.06] px-4 py-2">
          <span className="h-1.5 w-1.5 rounded-full bg-destructive" aria-hidden />
          <h2 className="text-xs font-semibold uppercase tracking-wider">
            If you need help right now
          </h2>
        </div>
        <div className="grid gap-px bg-destructive/15 sm:grid-cols-3">
          {[
            { number: '112', label: 'Police, ambulance, fire' },
            { number: '181', label: 'Women helpline' },
            { number: '1091', label: 'Women in distress' },
          ].map((line) => (
            <a
              key={line.number}
              href={`tel:${line.number}`}
              className="group flex flex-col bg-card px-4 py-3 transition-colors hover:bg-destructive/[0.06] focus-visible:bg-destructive/[0.06]"
            >
              <span className="font-serif text-2xl text-foreground transition-transform duration-150 group-hover:translate-x-0.5">
                {line.number}
              </span>
              <span className="mt-0.5 text-xs text-muted-foreground">{line.label}</span>
            </a>
          ))}
        </div>
        <p className="px-4 py-2.5 text-xs leading-relaxed text-muted-foreground">
          These reach real services. HerWay cannot call them for you and cannot tell
          anyone where you are.
        </p>
      </div>

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
          {error}
        </div>
      )}

      {/* Skeleton rather than a line of text: it holds the shape the content
          will take, so the page does not jump when it arrives. */}
      {loading && (
        <div role="status" aria-label="Loading your Safety Center" className="mt-10 space-y-8">
          {[0, 1].map((block) => (
            <div key={block} className="space-y-3">
              <div className="skeleton h-4 w-32 rounded" />
              <div className="skeleton h-24 w-full rounded-xl" />
              <div className="skeleton h-12 w-full rounded-lg" />
            </div>
          ))}
        </div>
      )}

      {!loading && (
        <div className="mt-8">
          {/* ---------------- Check-in ---------------- */}
          <Section title="Check-in">
            {/* The start-form and the running state replace each other, so they
                cross-fade rather than both animating in from nothing. */}
            <AnimatePresence mode="wait" initial={false}>
            {activeCheckIn ? (
              <motion.div
                key="active"
                variants={fadeUp}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="rounded-xl border border-border bg-card p-4 elevate-1"
              >
                <p className="text-sm">
                  Check-in running
                  {activeCheckIn.destination ? ` — ${activeCheckIn.destination}` : ''}.
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Started {new Date(activeCheckIn.started_at).toLocaleString()}.{' '}
                  <strong>Nobody is being notified.</strong> HerWay is not watching this
                  and will not alert anyone — if you want someone to know, send them a
                  message below.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    onClick={() => resolveCheckIn(activeCheckIn.id, 'completed_safe')}
                    className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
                  >
                    I&apos;m safe
                  </button>
                  <button
                    onClick={() => resolveCheckIn(activeCheckIn.id, 'cancelled')}
                    className="rounded-md border border-border px-3 py-1.5 text-sm"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() =>
                      prepareShare(activeCheckIn.id, contacts?.find((c) => c.enabled)?.id)
                    }
                    className="rounded-md border border-border px-3 py-1.5 text-sm"
                  >
                    Prepare a message
                  </button>
                </div>
              </motion.div>
            ) : (
              <motion.form
                key="start"
                variants={fadeUp}
                initial="hidden"
                animate="visible"
                exit="exit"
                onSubmit={startCheckIn}
                className="rounded-xl border border-border bg-card p-4 elevate-1"
              >
                <label className="block text-sm">
                  <span className="mb-1 block font-medium">Where are you going? (optional)</span>
                  <input
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                    placeholder="e.g. Office, then home"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  />
                </label>
                <button
                  type="submit"
                  disabled={busy}
                  className="mt-3 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
                >
                  Start a check-in
                </button>
                <p className="mt-2 text-xs text-muted-foreground">
                  A check-in is a note for yourself. HerWay does not track your location
                  and does not alert anyone if you do not come back.
                </p>
              </motion.form>
            )}
            </AnimatePresence>

            {checkIns && checkIns.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-sm text-muted-foreground">
                  Past check-ins ({checkIns.length})
                </summary>
                <ul className="mt-2 space-y-1 text-sm">
                  {checkIns.slice(0, 10).map((c) => (
                    <li key={c.id} className="text-muted-foreground">
                      {new Date(c.started_at).toLocaleString()} — {c.status.replace(/_/g, ' ')}
                      {c.destination ? ` (${c.destination})` : ''}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </Section>

          {/* ---------------- Share draft ---------------- */}
          {/* Slides in from the right: it is a panel arriving in response to an
              action, not content that was always part of the page. The
              direction carries that meaning. */}
          <AnimatePresence>
          {draft && (
            <motion.section
              key="draft"
              variants={slideInRight}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="mb-10"
            >
              <h2 className="mb-3 font-serif text-xl font-normal tracking-tight">
                Message ready to send
              </h2>
              <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 shadow-sm">
                <p className="text-xs font-medium">{draft.notice}</p>
                {draft.recipient_name && (
                  <p className="mt-2 text-sm">To: {draft.recipient_name}</p>
                )}
                <pre className="mt-2 whitespace-pre-wrap rounded bg-background p-3 text-sm">
                  {draft.message}
                </pre>
                <div className="mt-3 flex flex-wrap gap-2">
                  {draft.wa_me_url && (
                    <a
                      href={draft.wa_me_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
                    >
                      Open WhatsApp
                    </a>
                  )}
                  {draft.sms_url && (
                    <a href={draft.sms_url} className="rounded-md border border-border px-3 py-1.5 text-sm">
                      Open SMS
                    </a>
                  )}
                  {draft.mailto_url && (
                    <a href={draft.mailto_url} className="rounded-md border border-border px-3 py-1.5 text-sm">
                      Open email
                    </a>
                  )}
                  <button
                    onClick={() => setDraft(null)}
                    className="rounded-md border border-border px-3 py-1.5 text-sm"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </motion.section>
          )}
          </AnimatePresence>

          {/* ---------------- Plans ---------------- */}
          <Section title="Your plans">
            <form onSubmit={createPlan} className="mb-3 flex flex-wrap gap-2">
              <input
                value={newPlanTitle}
                onChange={(e) => setNewPlanTitle(e.target.value)}
                placeholder="e.g. Getting home late"
                className="min-w-0 flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
              >
                Create
              </button>
            </form>

            {plans?.length === 0 && (
              <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
                No plans yet. A plan is just a few steps you want to remember — where
                you keep spare keys, who you call, what you do if a route feels wrong.
              </p>
            )}

            {/* AnimatePresence so a deleted plan fades and collapses rather
                than vanishing — the list staying still underneath makes it
                clear which one went. */}
            <motion.ul layout className="space-y-3">
              <AnimatePresence initial={false}>
              {plans?.map((plan, index) => (
                <motion.li
                  key={plan.id}
                  layout
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0, transition: { delay: index * 0.045 } }}
                  exit={{ opacity: 0, height: 0, marginBottom: 0, transition: { duration: 0.18 } }}
                  className="overflow-hidden rounded-xl border border-border bg-card p-4 elevate-1 transition-colors hover:border-primary/30"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h3 className="font-semibold">{plan.title}</h3>
                      <p className="text-xs text-muted-foreground">
                        {plan.steps.length} step(s) · {plan.status}
                      </p>
                    </div>
                    <div className="flex gap-2 text-xs">
                      <button onClick={() => archivePlan(plan.id)} className="underline">
                        Archive
                      </button>
                      <button
                        onClick={() => deletePlan(plan.id, plan.title)}
                        className="text-destructive underline"
                      >
                        Delete
                      </button>
                    </div>
                  </div>

                  {plan.steps.length > 0 && (
                    <ul className="mt-2 space-y-1 text-sm">
                      {plan.steps.map((step) => (
                        <li key={step.id} className="flex items-start gap-2">
                          <span aria-hidden>·</span>
                          <span>
                            {step.user_edited_text || step.text}
                            {step.origin === 'accepted_suggestion' && (
                              <span className="ml-2 text-xs text-muted-foreground">
                                (suggested by HerWay, kept by you)
                              </span>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}

                  {plan.suggestions.length > 0 && (
                    <div className="mt-3 rounded-md bg-muted/50 p-3">
                      <p className="text-xs font-medium">
                        {plan.suggestions.length} suggestion(s) waiting for you — not part
                        of your plan until you accept them.
                      </p>
                    </div>
                  )}
                </motion.li>
              ))}
              </AnimatePresence>
            </motion.ul>
          </Section>

          {/* ---------------- Contacts ---------------- */}
          <Section title="Trusted contacts">
            <form onSubmit={addContact} className="mb-3 flex flex-wrap gap-2">
              <input
                value={newContactName}
                onChange={(e) => setNewContactName(e.target.value)}
                placeholder="Name"
                className="min-w-0 flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <input
                value={newContactValue}
                onChange={(e) => setNewContactValue(e.target.value)}
                placeholder="Phone or email (optional)"
                className="min-w-0 flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
              >
                Add
              </button>
            </form>

            <p className="mb-3 rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
              Saving someone here does not tell them. They have not agreed to be part of
              a safety plan — if you want them to know, ask them yourself.
            </p>

            {contacts?.length === 0 ? (
              <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
                No contacts saved.
              </p>
            ) : (
              <motion.ul layout className="space-y-2">
                <AnimatePresence initial={false}>
                {contacts?.map((contact, index) => (
                  <motion.li
                    key={contact.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: index * 0.04 } }}
                    exit={{ opacity: 0, height: 0, marginBottom: 0, transition: { duration: 0.18 } }}
                    className="flex flex-wrap items-center justify-between gap-2 overflow-hidden rounded-lg border border-border bg-card p-3 text-sm transition-colors hover:border-primary/30"
                  >
                    <span>
                      {contact.display_name}
                      {contact.relationship ? ` · ${contact.relationship}` : ''}
                      {contact.value ? (
                        <span className="ml-2 text-muted-foreground">{contact.value}</span>
                      ) : (
                        <span className="ml-2 italic text-muted-foreground">
                          no contact details saved
                        </span>
                      )}
                    </span>
                    <button
                      onClick={() => removeContact(contact.id, contact.display_name)}
                      className="text-xs text-destructive underline"
                    >
                      Remove
                    </button>
                  </motion.li>
                ))}
                </AnimatePresence>
              </motion.ul>
            )}
          </Section>

          <p className="mt-10 border-t border-border pt-4 text-xs text-muted-foreground">
            Your plans, contacts and check-ins are stored on your HerWay session and are
            not shown to anyone else or posted to the community.{' '}
            <a href="/privacy" className="text-primary hover:underline">
              What HerWay cannot protect against
            </a>
            .
          </p>
        </div>
      )}
    </main>
  );
}
