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
import { apiDelete, apiGet, apiPatch, apiPost } from '@/lib/api';

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
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
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
      <h1 className="text-2xl font-bold tracking-tight">Safety Center</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Your plans, the people you trust, and your check-ins. Everything here is
        yours and private to you.
      </p>

      {/* Emergency access first, always, no JS required beyond rendering. */}
      <div className="mt-4 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
        <h2 className="text-sm font-semibold">If you need help right now</h2>
        <div className="mt-2 flex flex-wrap gap-3 text-sm">
          <a href="tel:112" className="font-semibold text-primary hover:underline">
            112 — Police, ambulance, fire
          </a>
          <a href="tel:181" className="font-semibold text-primary hover:underline">
            181 — Women helpline
          </a>
          <a href="tel:1091" className="font-semibold text-primary hover:underline">
            1091 — Women in distress
          </a>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          These reach real services. HerWay cannot call them for you and cannot tell
          anyone where you are.
        </p>
      </div>

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
          {error}
        </div>
      )}

      {loading && (
        <p role="status" className="mt-8 text-sm text-muted-foreground">
          Loading your Safety Center…
        </p>
      )}

      {!loading && (
        <div className="mt-8">
          {/* ---------------- Check-in ---------------- */}
          <Section title="Check-in">
            {activeCheckIn ? (
              <div className="rounded-lg border border-border bg-card p-4">
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
              </div>
            ) : (
              <form onSubmit={startCheckIn} className="rounded-lg border border-border bg-card p-4">
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
              </form>
            )}

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
          {draft && (
            <Section title="Message ready to send">
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
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
            </Section>
          )}

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

            <ul className="space-y-3">
              {plans?.map((plan) => (
                <li key={plan.id} className="rounded-lg border border-border bg-card p-4">
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
                </li>
              ))}
            </ul>
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
              <ul className="space-y-2">
                {contacts?.map((contact) => (
                  <li
                    key={contact.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card p-3 text-sm"
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
                  </li>
                ))}
              </ul>
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
