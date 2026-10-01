import React from 'react';
import Link from 'next/link';
import { currentUser } from '@clerk/nextjs/server';
import LiveTitle from '@/components/LiveTitle';
import RealtimeList from '@/components/RealtimeList';
import { isClerkConfigured } from '@/lib/server-auth';

/**
 * Responder dashboard — lists incoming community reports.
 *
 * Access is deliberately strict. This page shows abuse reports written by real
 * people, and it used to be reachable by anyone: the auth stand-in returned a
 * fabricated user with `isAdmin: true`, so with no Clerk keys configured every
 * visitor passed the check.
 *
 * Now a viewer must be signed in through a configured Clerk project **and**
 * listed in `HERWAY_ADMIN_USER_IDS`. Self-assigned metadata is not trusted:
 * `unsafeMetadata` is writable by the user themselves.
 */

function adminIds(): string[] {
  return (process.env.HERWAY_ADMIN_USER_IDS || '')
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean);
}

function Denied({ reason }: { reason: string }) {
  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-3.5rem)] p-6">
      <div className="max-w-md w-full text-center space-y-3 border border-border rounded-2xl bg-card p-8">
        <h1 className="text-lg font-semibold text-foreground">Not available</h1>
        <p className="text-sm text-muted-foreground leading-relaxed">{reason}</p>
        <Link href="/" className="inline-block text-sm text-primary hover:underline">
          ← Back to HerWay
        </Link>
      </div>
    </div>
  );
}

export default async function Page() {
  if (!isClerkConfigured()) {
    return (
      <Denied reason="This area requires a signed-in responder account, and accounts are not configured on this deployment." />
    );
  }

  const user = await currentUser();
  if (!user) {
    return <Denied reason="Please sign in with a responder account to view this page." />;
  }

  const allowed = adminIds();
  if (allowed.length === 0 || !allowed.includes(user.id)) {
    return (
      <Denied reason="Your account does not have access to the responder dashboard." />
    );
  }

  return (
    <div className="flex flex-col justify-center mx-auto max-w-5xl w-full p-4">
      <LiveTitle />
      <RealtimeList />
    </div>
  );
}
