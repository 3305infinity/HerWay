import { NextResponse } from 'next/server';
import { clerkMiddleware } from '@clerk/nextjs/server';
import { isClerkConfigured } from '@/lib/clerk-config';

/**
 * Clerk's middleware is only mounted when the keys actually belong to a Clerk
 * project. Running it with a key for an instance that does not exist makes
 * Clerk answer every request with `{"errors":[{"message":"Invalid host"}]}`,
 * which breaks the whole site rather than just sign-in.
 *
 * `isClerkConfigured` is the same check `next.config.ts` uses to decide whether
 * to alias the Clerk SDK to the local stand-ins, so the two cannot disagree.
 */
export default isClerkConfigured() ? clerkMiddleware() : () => NextResponse.next();

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
};
