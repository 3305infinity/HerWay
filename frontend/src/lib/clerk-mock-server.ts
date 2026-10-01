import { NextResponse } from 'next/server';

/**
 * Server-side stand-in for `@clerk/nextjs/server`, used only when no Clerk
 * project is configured.
 *
 * It reports **no signed-in user**. The previous version returned a fabricated
 * admin (`user_haven_local_admin` with `isAdmin: true`) from `currentUser()`,
 * which meant `/dashboard` — the list of every community abuse report —
 * rendered for any visitor, including in a production build that happened to
 * ship without Clerk keys.
 *
 * Nothing here grants access. Case ownership is enforced by the backend.
 */

export function clerkMiddleware() {
  return () => NextResponse.next();
}

export async function currentUser(): Promise<null> {
  return null;
}

export function auth() {
  return {
    userId: null,
    sessionId: null,
    getToken: async (): Promise<string | null> => null,
  };
}
