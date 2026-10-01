import React from 'react';
import Link from 'next/link';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  // A neutral title: this page may sit in a browser history someone else reads.
  title: 'About this site',
};

/**
 * What HerWay protects, and — just as importantly — what it does not.
 *
 * Quick Exit in particular was previously presented as if it made a visit
 * untraceable. It does not. Someone deciding whether it is safe to use this
 * site needs the accurate version, not the reassuring one.
 */
export default function PrivacyPage() {
  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-background">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        <div className="space-y-2">
          <h1 className="font-serif text-2xl sm:text-3xl text-foreground font-normal">
            Your privacy, honestly
          </h1>
          <p className="text-sm text-muted-foreground leading-relaxed">
            If someone may be monitoring your phone or computer, please read this before you
            use HerWay. We would rather you know the limits than assume protection that is
            not there.
          </p>
        </div>

        <section className="space-y-3">
          <h2 className="text-base font-semibold text-foreground">What HerWay does</h2>
          <ul className="space-y-2 text-sm text-muted-foreground leading-relaxed">
            <li>
              <strong className="text-foreground">Your case is private to you.</strong> It is
              never posted publicly and is not shown to other users.
            </li>
            <li>
              <strong className="text-foreground">You do not need an account.</strong> You can
              use HerWay anonymously. We give your browser its own private space so your case
              is not mixed with anyone else&apos;s.
            </li>
            <li>
              <strong className="text-foreground">Searches are stripped of personal details.</strong>{' '}
              When HerWay searches the web for you, names, phone numbers and email addresses
              are removed from the search terms first.
            </li>
            <li>
              <strong className="text-foreground">Community posts never show contact details.</strong>{' '}
              Phone numbers and email addresses are not published, even if a form collected them.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-base font-semibold text-foreground">What HerWay cannot do</h2>
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 space-y-3">
            <ul className="space-y-2 text-sm text-muted-foreground leading-relaxed">
              <li>
                <strong className="text-foreground">Quick Exit does not erase your tracks.</strong>{' '}
                The Exit button (or pressing Escape) sends you to Google straight away and
                replaces the current page in your history. It cannot delete pages you visited
                before, clear your browsing history, or remove the site from an autocomplete
                suggestion. To cover a visit properly you need to clear your browser history
                yourself, or use private/incognito browsing from the start.
              </li>
              <li>
                <strong className="text-foreground">It cannot protect you from monitoring software.</strong>{' '}
                If someone has installed an app that records your screen or keystrokes, they
                can see everything you type here, whatever this site does.
              </li>
              <li>
                <strong className="text-foreground">Hidden messages are not encrypted.</strong>{' '}
                The discreet message feature hides text inside a photo. That conceals it from
                a casual look, but someone technical could still find it.
              </li>
              <li>
                <strong className="text-foreground">Shared devices and networks.</strong> A
                shared computer, a family phone plan, or a network someone else controls may
                record that you visited this site.
              </li>
            </ul>
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-base font-semibold text-foreground">Safer ways to use HerWay</h2>
          <ul className="space-y-2 text-sm text-muted-foreground leading-relaxed list-disc pl-5">
            <li>Use a device the other person cannot access, if you have one.</li>
            <li>Open a private or incognito window before you start.</li>
            <li>A public library or a friend&apos;s phone is often safer than your own.</li>
            <li>
              Press <kbd className="px-1.5 py-0.5 rounded border border-border bg-muted text-xs">Esc</kbd>{' '}
              at any moment to leave this site immediately.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-base font-semibold text-foreground">What HerWay is not</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">
            HerWay gives information and helps you find official resources. It is not a lawyer,
            a counsellor, or an emergency service. Nothing here is legal advice, and no outcome
            is guaranteed. In an emergency, call{' '}
            <a href="tel:112" className="text-primary font-semibold hover:underline">112</a>.
            For the women helpline, call{' '}
            <a href="tel:181" className="text-primary font-semibold hover:underline">181</a>.
          </p>
        </section>

        <div className="border-t border-border pt-5">
          <Link href="/" className="text-sm text-primary hover:underline">
            ← Back to HerWay
          </Link>
        </div>
      </div>
    </div>
  );
}
